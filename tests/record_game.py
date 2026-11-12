#!/usr/bin/env python3
"""
Record a live game for replaying later. Runs a monitor against the real API
and saves every response it gets, in order, to a replay file. The monitor runs
with no stream delay and its own temporary event queue, so the real goal horn
isn't set off twice. Start it before the game, and stop it (Ctrl+C) after, or
let --stop-after-final stop it. To schedule recordings ahead of time, use dvr.py.

Usage:
    python3 tests/record_game.py rangers
    python3 tests/record_game.py rangers --stop-after-final
    python3 tests/record_game.py vols -o tests/fixtures/vols_overturned_td.json
    python3 tests/record_game.py yankees --raw    # keep full responses (large; not for the Pi)
    python3 tests/record_game.py --finish tests/fixtures/rangers_2026-11-13.partial.jsonl

While recording, responses are added to the end of a log (<output>.partial.jsonl)
and nothing already written is rewritten, which spares the Pi's SD card. When
the recording stops, the log becomes the replay file. After a crash or power
cut the log is still there, missing at most its last few seconds: run the
recorder again with the same -o to carry on, or --finish to save it as is.
Once the game is over, fill in "description" and "expected_events" so
test_fixtures.py checks the replay on every test run.
"""

import argparse
import os
import sys
import tempfile
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness import Journal, finish_journal, load_script, script_path, team_id  # noqa: E402

FIXTURE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")

# ─── Trimming ─────────────────────────────────────────────────────────────────
# Responses are cut down to the fields the monitors read, so a game is a few MB
# instead of a few GB. If a monitor starts reading a new field, older
# recordings won't have it: re-record, or record with --raw.

def pick(data, *paths):
    """Copy only the given dotted paths (e.g. "status.type.name") out of data."""
    out = {}
    for path in paths:
        src, dst, keys = data, out, path.split(".")
        for key in keys[:-1]:
            if not isinstance(src, dict) or key not in src:
                break
            src = src[key]
            dst = dst.setdefault(key, {})
        else:
            if isinstance(src, dict) and keys[-1] in src:
                dst[keys[-1]] = src[keys[-1]]
    return out


def trim_nhl_schedule(data, tid):
    return {"gameWeek": [
        {"games": [pick(g, "id", "gameState", "gameScheduleState",
                        "homeTeam.abbrev", "awayTeam.abbrev")
                   for g in day.get("games", [])]}
        for day in data.get("gameWeek", [])]}


def trim_nhl_landing(data, tid):
    return pick(data, "homeTeam.abbrev", "homeTeam.score", "awayTeam.abbrev",
                "awayTeam.score", "periodDescriptor", "summary.shootout",
                "clock.timeRemaining", "clock.inIntermission")


def trim_mlb_schedule(data, tid):
    return {"dates": [
        {"games": [pick(g, "gamePk", "status.abstractGameState", "status.detailedState",
                        "teams.home.team.id", "teams.home.team.name",
                        "teams.away.team.id", "teams.away.team.name")
                   for g in date.get("games", [])]}
        for date in data.get("dates", [])]}


def trim_mlb_feed(data, tid):
    out = pick(data, "gameData.status.abstractGameState", "gameData.status.detailedState",
               "gameData.teams.home.id", "gameData.teams.away.id",
               "liveData.linescore.currentInning", "liveData.linescore.inningHalf",
               "liveData.linescore.outs", "liveData.linescore.teams.home.runs",
               "liveData.linescore.teams.away.runs")
    plays = data.get("liveData", {}).get("plays", {}).get("allPlays", [])
    out.setdefault("liveData", {})["plays"] = {"allPlays": [
        pick(p, "result.eventType", "result.description") for p in plays]}
    return out


def trim_espn_scoreboard(data, tid):
    events = []
    for event in data.get("events", []):
        competitions = event.get("competitions", [])
        competitors  = competitions[0].get("competitors", []) if competitions else []
        ids = {str(c.get("team", {}).get("id", c.get("id"))) for c in competitors}
        if str(tid) not in ids:
            continue    # Other teams' games; the monitor skips them anyway
        trimmed = pick(event, "id", "status.period", "status.displayClock",
                       "status.type.state", "status.type.name")
        trimmed["competitions"] = [{"competitors": [
            pick(c, "id", "homeAway", "score", "team.id", "team.abbreviation")
            for c in competitors]}]
        events.append(trimmed)
    return {"events": events}


TRIMMERS = [
    ("api-web.nhle.com/v1/schedule",   trim_nhl_schedule),
    ("/landing",                       trim_nhl_landing),
    ("statsapi.mlb.com/api/v1/schedule", trim_mlb_schedule),
    ("/feed/live",                     trim_mlb_feed),
    ("site.api.espn.com",              trim_espn_scoreboard),
]


def trim(url, data, tid):
    for pattern, trimmer in TRIMMERS:
        if pattern in url:
            return trimmer(data, tid)
    return data

# ─── Game State ───────────────────────────────────────────────────────────────

def games_in(url, data, tid) -> list:
    """(game ID, "upcoming" / "live" / "over") for the team's games in a schedule or scoreboard."""
    found = []
    if not isinstance(data, dict):
        return found
    if "api-web.nhle.com/v1/schedule" in url:
        for day in data.get("gameWeek", []):
            for g in day.get("games", []):
                if tid in (g.get("homeTeam", {}).get("abbrev"), g.get("awayTeam", {}).get("abbrev")):
                    state = g.get("gameState", "")
                    off = ("PPD", "CNCL", "SUSP")   # Postponed, canceled, suspended
                    if g.get("gameScheduleState") in off or state in off + ("OFF", "FINAL"):
                        found.append((str(g.get("id")), "over"))
                    else:
                        found.append((str(g.get("id")), "live" if state in ("LIVE", "CRIT") else "upcoming"))
    elif "statsapi.mlb.com/api/v1/schedule" in url:
        for date in data.get("dates", []):
            for g in date.get("games", []):
                teams = g.get("teams", {})
                if tid in (teams.get("home", {}).get("team", {}).get("id"),
                           teams.get("away", {}).get("team", {}).get("id")):
                    state = g.get("status", {}).get("abstractGameState", "")
                    found.append((str(g.get("gamePk")), {"Live": "live", "Final": "over"}.get(state, "upcoming")))
    elif "site.api.espn.com" in url:
        for event in data.get("events", []):
            competitors = (event.get("competitions") or [{}])[0].get("competitors", [])
            if str(tid) in {str(c.get("team", {}).get("id", c.get("id"))) for c in competitors}:
                state = event.get("status", {}).get("type", {}).get("state", "")
                found.append((str(event.get("id")), {"in": "live", "post": "over"}.get(state, "upcoming")))
    return found

# ─── Recording ────────────────────────────────────────────────────────────────

AFTER_FINAL_REQUESTS = 6    # Requests to keep recording after the game is over


class StopRecording(KeyboardInterrupt):
    """Stops the monitor the way Ctrl+C does, so the recording is saved."""


def journal_path(output) -> str:
    return os.path.splitext(str(output))[0] + ".partial.jsonl"


def main():
    parser = argparse.ArgumentParser(description="Record a live game to a replay file.")
    parser.add_argument("team", nargs="?", help="monitor name, e.g. rangers")
    parser.add_argument("-o", "--output", help="replay file (default tests/fixtures/<team>_<date>.json)")
    parser.add_argument("--raw", action="store_true", help="save full API responses (large; not for the Pi)")
    parser.add_argument("--game", help="the game to record (its API ID); others are ignored for stopping")
    parser.add_argument("--stop-after-final", action="store_true",
                        help="stop by itself once the game is over (or postponed)")
    parser.add_argument("--max-hours", type=float, default=8, help="stop after this long no matter what (default 8)")
    parser.add_argument("--finish", metavar="LOG",
                        help="turn a recording log left by a crash (.partial.jsonl) into a replay file")
    args = parser.parse_args()

    if args.finish:
        output = args.output or args.finish.replace(".partial.jsonl", ".json")
        print(f"[RECORD] Saved {finish_journal(args.finish, output)} responses to {output}")
        return
    if not args.team:
        parser.error("a team is required")

    team   = os.path.basename(script_path(args.team)).removesuffix("_monitor.py")
    output = args.output or os.path.join(
        FIXTURE_DIR, f"{team}_{datetime.now().strftime('%Y-%m-%d')}.json")
    os.makedirs(os.path.dirname(os.path.abspath(output)), exist_ok=True)

    module = load_script(team, tempfile.mkdtemp(prefix="goal_horn_record_"))
    module.STREAM_DELAY_SECONDS = 0
    tid      = team_id(module)
    real_get = module.requests.get
    log      = journal_path(output)
    journal  = Journal(log, {"team": team, "description": "",
                             "recorded": datetime.now().isoformat(timespec="seconds"),
                             "expected_events": None})
    started  = time.monotonic()
    target   = args.game        # The game whose end stops the recording
    after_final = None          # Requests made since the game ended

    def recording_get(url, *a, **kw):
        nonlocal target, after_final
        if time.monotonic() - started > args.max_hours * 3600:
            print(f"[RECORD] Stopping after {args.max_hours} hours.")
            raise StopRecording()
        if after_final is not None:
            after_final += 1
            if after_final > AFTER_FINAL_REQUESTS:
                print("[RECORD] The game is over. Stopping.")
                raise StopRecording()
        try:
            response = real_get(url, *a, **kw)
        except Exception as e:
            journal.add({"url": url, "error": str(e)})
            raise
        step = {"url": url}
        if response.status_code != 200:
            step["status"] = response.status_code
        try:
            data = response.json()
        except ValueError:
            data = None
        if args.stop_after_final:
            for game, state in games_in(url, data, tid):
                if target is None and state == "live":
                    target = game
                if game == str(target) and state == "over" and after_final is None:
                    after_final = 0
        step["json"] = data if args.raw else trim(url, data, tid)
        journal.add(step)
        return response

    module.requests.get = recording_get
    stop = "It stops by itself after the game." if args.stop_after_final else "Press Ctrl+C when the game is over."
    print(f"[RECORD] Recording {team} to {output}. {stop}")
    try:
        module.main()
    finally:
        module.requests.get = real_get
        journal.close()
        print(f"[RECORD] Saved {finish_journal(log, output)} responses to {output}")


if __name__ == "__main__":
    main()
