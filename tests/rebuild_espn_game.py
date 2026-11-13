#!/usr/bin/env python3
"""
Rebuild a replay of a past football game (NFL or college) from ESPN's play
list, without having recorded it live. ESPN keeps every play with the real
time it happened (wallclock) and the score after it, so the replay is one
scoreboard per score change, spaced as the game really was.

Usage:
    python3 tests/rebuild_espn_game.py dolphins 401873015
    python3 tests/rebuild_espn_game.py vols 401856723 -o tests/recordings/vols_alabama.json

Find a game's ID in the team's schedule, e.g.
https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/15/schedule
(college: .../football/college-football/teams/2633/schedule)

ESPN's play list gives the score after a touchdown's extra point or 2-point
try, so a touchdown shows as +7 or +8. Live, the scoreboard shows +6 first
and the try a minute or so later; the rebuild splits them the same way.

What a rebuilt game can't show (see tests/README.md, "Rebuilt games"):
- Overturned scores that ESPN removed from the play list.
- API glitches, blank scores and failed requests.
test_recordings.py adds those to every recorded game as variations.
"""

import argparse
import os
import re
import sys
from datetime import datetime

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness import load_script, polls_for_gap, save_recording, script_path, team_id  # noqa: E402

SUMMARY_URL = "https://site.api.espn.com/apis/site/v2/sports/football/{league}/summary?event={event}"
TRY_DELAY   = 60    # Real seconds from a touchdown to its extra point or 2-point try


def league_of(module) -> str:
    """"nfl" or "college-football", from the monitor's scoreboard URL."""
    return re.search(r"sports/football/([a-z-]+)/scoreboard", module.ESPN_SCOREBOARD_URL).group(1)


def wallclock(play) -> float | None:
    text = play.get("wallclock")
    return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp() if text else None


def build_steps(summary: dict, module) -> list:
    """Replay steps for one team's monitor, from a game's ESPN summary."""
    tid         = str(team_id(module))
    comp        = summary["header"]["competitions"][0]
    event_id    = str(summary["header"]["id"])
    competitors = {c["homeAway"]: c for c in comp["competitors"]}
    ids         = {side: str(c["id"]) for side, c in competitors.items()}
    if tid not in ids.values():
        raise ValueError(f"Team {tid} didn't play in game {event_id}")
    url = module.ESPN_SCOREBOARD_URL

    def scoreboard(status, period, clock, score):
        state, name = status
        return {"url": url, "json": {"events": [{
            "id": event_id,
            "status": {"period": period, "displayClock": clock,
                       "type": {"state": state, "name": name}},
            "competitions": [{"competitors": [
                {"id": ids[side], "homeAway": side, "score": str(score[side]),
                 "team": {"id": ids[side],
                          "abbreviation": competitors[side]["team"]["abbreviation"]}}
                for side in ("home", "away")]}],
        }]}}

    # Plays in the order they happened. ESPN's list isn't always in that order.
    plays = [p for drive in summary.get("drives", {}).get("previous", [])
             for p in drive.get("plays", [])]
    last  = None
    for p in plays:
        last = wallclock(p) or last
        p["_t"] = last
    plays = [p for p in plays if p["_t"] is not None]
    plays.sort(key=lambda p: p["_t"])

    # Each change of score or quarter, with its real time. A touchdown that
    # already includes its try is split into the touchdown, then the try.
    changes = []    # (time, period, clock, score)
    score   = {"home": 0, "away": 0}
    period  = 1
    for i, p in enumerate(plays):
        new = {"home": p["homeScore"], "away": p["awayScore"]}
        new_period = p["period"]["number"]
        if new == score and new_period == period:
            continue
        clock = p.get("clock", {}).get("displayValue", "0:00")
        for side in ("home", "away"):
            jump = new[side] - score[side]
            if jump in (7, 8) and "Touchdown" in p.get("type", {}).get("text", ""):
                changes.append((p["_t"], new_period, clock, dict(score, **{side: score[side] + 6})))
                next_t = plays[i + 1]["_t"] if i + 1 < len(plays) else p["_t"] + 2 * TRY_DELAY
                changes.append((p["_t"] + min(TRY_DELAY, (next_t - p["_t"]) / 2),
                                new_period, clock, dict(new)))
                break
        else:
            changes.append((p["_t"], new_period, clock, dict(new)))
        score, period = new, new_period

    final = {side: int(competitors[side]["score"]) for side in ("home", "away")}
    ours  = next(side for side, i in ids.items() if i == tid)
    steps = [scoreboard(("pre", "STATUS_SCHEDULED"), 0, "15:00", {"home": 0, "away": 0})] * 2
    start = (plays[0]["_t"] if plays else 0)
    timeline = [(start, 1, "15:00", {"home": 0, "away": 0})] + changes
    last_td  = None
    for i, (t, q, clock, s) in enumerate(timeline):
        next_t = timeline[i + 1][0] if i + 1 < len(timeline) else t + module.POLL_INTERVAL
        gap    = next_t - t
        # Live, the monitor spends the stream delay queuing an event before it
        # checks again, so that time is already gone from the gap
        jump = s[ours] - timeline[i - 1][3][ours] if i else 0
        try_after_td = (jump in (1, 2) and last_td is not None
                        and t - last_td <= module.CONVERSION_WINDOW)
        if jump >= 3 or (jump > 0 and not try_after_td):
            gap -= module.STREAM_DELAY_SECONDS
        if jump >= 6:
            last_td = t
        polls  = polls_for_gap(gap, module.POLL_INTERVAL)
        steps += [scoreboard(("in", "STATUS_IN_PROGRESS"), q, clock, s)] * polls
    last_q = timeline[-1][1]
    steps += [scoreboard(("post", "STATUS_FINAL"), last_q, "0:00", final)] * 2
    return steps


def main():
    parser = argparse.ArgumentParser(description="Rebuild a past football game as a replay file.")
    parser.add_argument("team", help="monitor name, e.g. dolphins or vols")
    parser.add_argument("event_id", help="ESPN game ID, e.g. 401873015")
    parser.add_argument("-o", "--output", help="replay file (default tests/recordings/<team>_<event_id>.json)")
    args = parser.parse_args()

    team   = os.path.basename(script_path(args.team)).removesuffix("_monitor.py")
    module = load_script(team)
    output = args.output or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                         "recordings", f"{team}_{args.event_id}.json")

    url     = SUMMARY_URL.format(league=league_of(module), event=args.event_id)
    summary = requests.get(url, timeout=30).json()
    steps   = build_steps(summary, module)
    comp    = summary["header"]["competitions"][0]
    sides   = {c["homeAway"]: c for c in comp["competitors"]}
    save_recording(output, team,
                 f"{sides['away']['team']['abbreviation']} {sides['away']['score']} @ "
                 f"{sides['home']['team']['abbreviation']} {sides['home']['score']}, "
                 f"{comp.get('date', '')[:10]}, rebuilt from ESPN's play list",
                 comp.get("date", ""), steps)
    print(f"[REBUILD] Saved {len(steps)} responses to {output}")
    print("Replay it with tests/replay_game.py, check the events against the game, "
          'then fill in "expected_events".')


if __name__ == "__main__":
    main()
