#!/usr/bin/env python3
"""
Schedule game recordings ahead of time, like a DVR.

Pick games:
    python3 tests/dvr.py rangers                # list the next 30 days of games and pick some
    python3 tests/dvr.py rangers --pick 1,3     # or pick by number without being asked
    python3 tests/dvr.py vols --pick all        # every game in the next 30 days
    python3 tests/dvr.py rangers --days 60      # look further ahead

See and change what's scheduled:
    python3 tests/dvr.py --scheduled
    python3 tests/dvr.py --cancel 2

The recordings are made by the DVR service, which has to be running:
    python3 -u tests/dvr.py --run >> dvr.log 2>&1 &
or at boot, from cron (see tests/README.md). It sleeps until LEAD_MINUTES
before each scheduled game, records it with record_game.py, and stops once
the game is over. Recordings are saved to tests/fixtures/.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness import finish_journal, script_path  # noqa: E402
from record_game import FIXTURE_DIR, journal_path  # noqa: E402
from schedules import parse_time, upcoming_games  # noqa: E402

TESTS_DIR     = os.path.dirname(os.path.abspath(__file__))
SCHEDULE_FILE = os.path.join(TESTS_DIR, "recordings.json")
RECORDER      = os.path.join(TESTS_DIR, "record_game.py")
LEAD_MINUTES  = 30          # Start recording this long before the game
LONGEST_GAME  = 8           # Hours after the start a game must be over by
CHECK_EVERY   = 60          # Seconds between the service's checks

# ─── The Schedule File ────────────────────────────────────────────────────────
# tests/recordings.json: one entry per recording, with a status of scheduled,
# recording, done, interrupted, missed or failed.

def load(path=None) -> list:
    path = path or SCHEDULE_FILE
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return json.load(f)


def save(recordings, path=None):
    path = path or SCHEDULE_FILE
    tmp  = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(recordings, f, indent=1)
    os.replace(tmp, path)       # Never leave a half-written schedule


def local(when: str) -> str:
    """A UTC timestamp as the Pi's local time, e.g. "Fri Nov 13  9:00 PM"."""
    return parse_time(when).astimezone().strftime("%a %b %d %l:%M %p")


def add(recordings, team, game, fixture_dir=None) -> dict | None:
    """Schedule a game (a schedules.Game). Returns the new entry, or None if it's already scheduled."""
    fixture_dir = fixture_dir or FIXTURE_DIR
    if any(r["team"] == team and r["game_id"] == game.id for r in recordings):
        return None
    date = game.start.astimezone().strftime("%Y-%m-%d")
    name = "".join(c for c in game.opponent.lower() if c.isalnum())
    output, n = os.path.join(fixture_dir, f"{team}_{date}_{name}.json"), 2
    taken = {r["output"] for r in recordings}
    while output in taken or os.path.exists(output):
        output, n = os.path.join(fixture_dir, f"{team}_{date}_{name}-{n}.json"), n + 1
    entry = {"team": team, "game_id": game.id, "start": game.start.isoformat(),
             "matchup": game.matchup, "output": output, "status": "scheduled", "pid": None}
    recordings.append(entry)
    return entry

# ─── The Service ──────────────────────────────────────────────────────────────

def launch(entry) -> int:
    """Start record_game.py for one recording; returns its process ID."""
    log = open(os.path.splitext(entry["output"])[0] + ".log", "a")
    proc = subprocess.Popen(
        [sys.executable, "-u", RECORDER, entry["team"], "--game", entry["game_id"],
         "--stop-after-final", "--max-hours", str(LONGEST_GAME), "-o", entry["output"]],
        stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    return proc.pid


def running(pid) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    # A finished child that hasn't been reaped is a zombie: not running
    try:
        done, _ = os.waitpid(pid, os.WNOHANG)
        return done == 0
    except ChildProcessError:
        return True     # Not our child (started by an earlier service), but alive


def tick(recordings, now=None, start=launch, alive=running) -> bool:
    """One check of the schedule: start, finish or give up on recordings. Returns True if anything changed."""
    now     = now or datetime.now(timezone.utc)
    changed = False
    for r in recordings:
        begin = parse_time(r["start"])
        if r["status"] == "scheduled":
            if now > begin + timedelta(hours=LONGEST_GAME):
                r["status"] = "missed"              # The service wasn't running in time
            elif now >= begin - timedelta(minutes=LEAD_MINUTES):
                r["pid"], r["status"] = start(r), "recording"
            else:
                continue
            changed = True
        elif r["status"] == "recording" and not alive(r["pid"]):
            log = journal_path(r["output"])
            if os.path.exists(log):
                if now < begin + timedelta(hours=LONGEST_GAME):
                    # Stopped early (e.g. the Pi rebooted): carry on where it left off
                    r["pid"] = start(r)
                else:
                    finish_journal(log, r["output"])
                    r["status"] = "interrupted"
            else:
                r["status"] = "done" if os.path.exists(r["output"]) else "failed"
            changed = True
    return changed


def run(path=None):
    print(f"[DVR] Running. Recordings start {LEAD_MINUTES} minutes before each game.")
    while True:
        recordings = load(path)
        before = [dict(r) for r in recordings]
        if tick(recordings):
            save(recordings, path)
            for old, new in zip(before, recordings):
                if old["status"] != new["status"] or old["pid"] != new["pid"]:
                    print(f"[DVR] {local(new['start'])}  {new['team']}  {new['matchup']}: {new['status']}")
        time.sleep(CHECK_EVERY)

# ─── Command Line ─────────────────────────────────────────────────────────────

def show(recordings):
    if not recordings:
        print("Nothing scheduled.")
    for i, r in enumerate(recordings, 1):
        print(f"  {i}) {local(r['start'])}   {r['team']:<10} {r['matchup']:<16} {r['status']:<12} "
              f"{os.path.relpath(r['output'])}")


def choose(games, pick: str | None) -> list:
    """The games picked by number ("1,3"), "all", or by asking."""
    if pick is None:
        pick = input('Record which? (numbers like 1,3, "all", or Enter to cancel): ')
    pick = pick.strip().lower()
    if not pick:
        return []
    if pick == "all":
        return list(games)
    numbers = [int(n) for n in pick.replace(" ", "").split(",") if n]
    bad = [n for n in numbers if not 1 <= n <= len(games)]
    if bad:
        sys.exit(f"No game numbered {', '.join(map(str, bad))}.")
    return [games[n - 1] for n in numbers]


def main():
    parser = argparse.ArgumentParser(description="Schedule game recordings ahead of time.")
    parser.add_argument("team", nargs="?", help="monitor name, e.g. rangers")
    parser.add_argument("--days", type=int, default=30, help="how far ahead to list games (default 30)")
    parser.add_argument("--pick", help='games to record by number ("1,3") or "all", instead of being asked')
    parser.add_argument("--scheduled", action="store_true", help="list scheduled and past recordings")
    parser.add_argument("--cancel", type=int, metavar="N", help="cancel recording N from --scheduled")
    parser.add_argument("--run", action="store_true", help="run the DVR service")
    args = parser.parse_args()

    if args.run:
        return run()
    recordings = load()
    if args.scheduled:
        return show(recordings)
    if args.cancel:
        if not 1 <= args.cancel <= len(recordings):
            sys.exit(f"No recording numbered {args.cancel}. See --scheduled.")
        r = recordings[args.cancel - 1]
        if r["status"] == "recording" and running(r["pid"]):
            os.kill(r["pid"], 2)        # Like Ctrl+C: the recorder saves what it has
        r["status"] = "canceled"
        save(recordings)
        return print(f"Canceled: {local(r['start'])} {r['matchup']}")
    if not args.team:
        parser.error("a team is required (or --scheduled, --cancel, --run)")

    team  = os.path.basename(script_path(args.team)).removesuffix("_monitor.py")
    games = upcoming_games(team, args.days)
    if not games:
        return print(f"No {team} games in the next {args.days} days.")
    print(f"Upcoming {team} games:")
    for i, g in enumerate(games, 1):
        started = "  (under way)" if g.start <= datetime.now(timezone.utc) else ""
        print(f"  {i:>2}) {local(g.start.isoformat())}   {g.matchup}{started}")
    picked = choose(games, args.pick)
    if not picked:
        return print("Nothing scheduled.")
    for game in picked:
        entry = add(recordings, team, game)
        if entry is None:
            print(f"Already scheduled: {local(game.start.isoformat())} {game.matchup}")
        else:
            print(f"Scheduled: {local(entry['start'])} {entry['matchup']} -> {os.path.relpath(entry['output'])}")
    save(recordings)
    print("The DVR service records them; make sure it's running (see tests/README.md).")


if __name__ == "__main__":
    main()
