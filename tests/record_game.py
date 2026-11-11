#!/usr/bin/env python3
"""
Record a live game for replaying later. Runs a monitor against the real API
and saves every response it gets, in order, to a replay file. The monitor runs
with no stream delay and its own temporary event queue, so the real goal horn
isn't set off twice. Start it before the game and stop it (Ctrl+C) after.

Usage:
    python3 tests/record_game.py rangers
    python3 tests/record_game.py vols -o tests/fixtures/vols_overturned_td.json
    python3 tests/record_game.py yankees --raw    # keep full responses (large)

The file is saved every 30 seconds, so a crash or power cut loses at most the
last 30 seconds. Once the game is over, fill in "description" and
"expected_events" so test_fixtures.py checks the replay on every test run.
"""

import argparse
import json
import os
import sys
import tempfile
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness import compress_steps, load_script, script_path, team_id  # noqa: E402

FIXTURE_DIR   = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
SAVE_INTERVAL = 30          # Seconds between saves; errors and Ctrl+C save right away

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
        {"games": [pick(g, "id", "gameState", "homeTeam.abbrev", "awayTeam.abbrev")
                   for g in day.get("games", [])]}
        for day in data.get("gameWeek", [])]}


def trim_nhl_landing(data, tid):
    return pick(data, "homeTeam.abbrev", "homeTeam.score", "awayTeam.abbrev",
                "awayTeam.score", "periodDescriptor", "summary.shootout")


def trim_mlb_schedule(data, tid):
    return {"dates": [
        {"games": [pick(g, "gamePk", "status.abstractGameState",
                        "teams.home.team.id", "teams.home.team.name",
                        "teams.away.team.id", "teams.away.team.name")
                   for g in date.get("games", [])]}
        for date in data.get("dates", [])]}


def trim_mlb_feed(data, tid):
    out = pick(data, "gameData.status.abstractGameState",
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
        trimmed = pick(event, "id", "status.period", "status.type.state", "status.type.name")
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

# ─── Recording ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Record a live game to a replay file.")
    parser.add_argument("team", help="monitor name, e.g. rangers")
    parser.add_argument("-o", "--output", help="replay file (default tests/fixtures/<team>_<date>.json)")
    parser.add_argument("--raw", action="store_true", help="save full API responses")
    args = parser.parse_args()

    team   = os.path.basename(script_path(args.team)).removesuffix("_monitor.py")
    output = args.output or os.path.join(
        FIXTURE_DIR, f"{team}_{datetime.now().strftime('%Y-%m-%d')}.json")
    os.makedirs(os.path.dirname(os.path.abspath(output)), exist_ok=True)

    module = load_script(team, tempfile.mkdtemp(prefix="goal_horn_record_"))
    module.STREAM_DELAY_SECONDS = 0
    tid       = team_id(module)
    real_get  = module.requests.get
    steps     = []
    responses = []              # Each distinct response once; steps refer to it by index
    known     = {}              # Serialized response -> index in responses
    last_save = 0.0
    fixture   = {
        "team":            team,
        "description":     "",
        "recorded":        datetime.now().isoformat(timespec="seconds"),
        "expected_events": None,
    }

    def save():
        nonlocal last_save
        tmp = output + ".tmp"
        with open(tmp, "w") as f:
            json.dump({**fixture, "steps": compress_steps(steps), "responses": responses},
                      f, indent=1)
        os.replace(tmp, output)     # Never leave a half-written file
        last_save = time.monotonic()

    def record(step, force_save=False):
        steps.append(step)
        if force_save or time.monotonic() - last_save >= SAVE_INTERVAL:
            save()

    def recording_get(url, *a, **kw):
        try:
            response = real_get(url, *a, **kw)
        except Exception as e:
            record({"url": url, "error": str(e)}, force_save=True)
            raise
        step = {"url": url}
        if response.status_code != 200:
            step["status"] = response.status_code
        try:
            data = response.json()
            data = data if args.raw else trim(url, data, tid)
        except ValueError:
            data = None
        key = json.dumps(data, sort_keys=True)
        if key not in known:
            known[key] = len(responses)
            responses.append(data)
        step["response"] = known[key]
        record(step)
        return response

    module.requests.get = recording_get
    print(f"[RECORD] Recording {team} to {output}. Press Ctrl+C when the game is over.")
    try:
        module.main()
    finally:
        module.requests.get = real_get
        save()
        print(f"[RECORD] Saved {len(steps)} responses to {output}")


if __name__ == "__main__":
    main()
