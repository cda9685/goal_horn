#!/usr/bin/env python3
"""
Rebuild a replay of a past MLB game from the MLB API's history, without having
recorded it live. The MLB API keeps the live feed as it stood at every update
of a game (feed/live/timestamps), so the replay is the game as the monitor
would have seen it, one poll per update.

Usage:
    python3 tests/rebuild_mlb_game.py yankees 825028
    python3 tests/rebuild_mlb_game.py giants 825100 -o tests/fixtures/giants_walk_off.json

Find a game's ID (gamePk) in the schedule, e.g.
https://statsapi.mlb.com/api/v1/schedule?sportId=1&teamId=147&date=2026-09-20
Takes a few minutes: one request per update, a few hundred per game.
"""

import argparse
import json
import os
import sys

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness import compress_steps, load_script, script_path, team_id  # noqa: E402
from record_game import FIXTURE_DIR, trim  # noqa: E402

TIMESTAMPS_URL = "https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live/timestamps"


def main():
    parser = argparse.ArgumentParser(description="Rebuild a past MLB game as a replay file.")
    parser.add_argument("team", help="monitor name, e.g. yankees")
    parser.add_argument("game_pk", type=int, help="MLB game ID (gamePk)")
    parser.add_argument("-o", "--output", help="replay file (default tests/fixtures/<team>_<gamePk>.json)")
    args = parser.parse_args()

    team   = os.path.basename(script_path(args.team)).removesuffix("_monitor.py")
    module = load_script(team)
    tid    = team_id(module)
    output = args.output or os.path.join(FIXTURE_DIR, f"{team}_{args.game_pk}.json")

    timestamps = requests.get(TIMESTAMPS_URL.format(game_pk=args.game_pk), timeout=30).json()
    print(f"[REBUILD] {len(timestamps)} updates for game {args.game_pk}")

    schedule_url = module.MLB_SCHEDULE_URL.format(team_id=tid)
    feed_url     = module.MLB_GAME_URL.format(game_pk=args.game_pk)
    steps, responses, known = [], [], {}

    def add(url, data):
        key = json.dumps(data, sort_keys=True)
        if key not in known:
            known[key] = len(responses)
            responses.append(data)
        steps.append({"url": url, "response": known[key]})

    # Team names aren't in the trimmed feed; the schedule response needs them
    full  = requests.get(feed_url, timeout=30).json()["gameData"]["teams"]
    names = {side: full[side]["name"] for side in ("home", "away")}

    for i, timecode in enumerate(timestamps, 1):
        url   = f"{feed_url}?timecode={timecode}"
        feed  = trim(url, requests.get(url, timeout=30).json(), tid)
        game  = feed["gameData"]
        state = game["status"]["abstractGameState"]

        # Each poll the monitor fetches the schedule, then the feed once the game is under way
        add(schedule_url, {"dates": [{"games": [{
            "gamePk": args.game_pk,
            "status": {"abstractGameState": state},
            "teams":  {side: {"team": {"id": game["teams"][side]["id"], "name": names[side]}}
                       for side in ("home", "away")},
        }]}]})
        if state in ("Live", "Final"):
            add(feed_url, feed)
        if i % 25 == 0:
            print(f"[REBUILD] {i}/{len(timestamps)} ({timecode})")

    fixture = {
        "team":            team,
        "description":     f"MLB game {args.game_pk}, rebuilt from MLB API timestamps",
        "recorded":        f"{timestamps[0]} to {timestamps[-1]}" if timestamps else "",
        "expected_events": None,
        "steps":           compress_steps(steps),
        "responses":       responses,
    }
    os.makedirs(os.path.dirname(os.path.abspath(output)), exist_ok=True)
    with open(output, "w") as f:
        json.dump(fixture, f, indent=1)
    print(f"[REBUILD] Saved {len(steps)} responses to {output}")



if __name__ == "__main__":
    main()
