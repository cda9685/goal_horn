#!/usr/bin/env python3
"""
Rebuild a replay of a past NHL game from its play-by-play, without having
recorded it live. The NHL API keeps every play of a game (goals, shootout
attempts, period starts and ends), so the replay is one poll per change, as
the monitor would have seen the game's score.

Usage:
    python3 tests/rebuild_nhl_game.py rangers 2026010045
    python3 tests/rebuild_nhl_game.py panthers 2026020289 -o tests/fixtures/panthers_win.json

Find a game's ID in the team's schedule, e.g.
https://api-web.nhle.com/v1/club-schedule-season/NYR/now

What a rebuilt game can't show (see tests/README.md, "Rebuilt games"):
- Overturned goals: the play-by-play only keeps goals that stood.
- API glitches and failed requests.
- Real time: the play-by-play only has the game clock, so real time is estimated.
test_fixtures.py adds the first two to every recorded game as variations.
"""

import argparse
import os
import sys

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness import load_script, polls_for_gap, save_fixture, script_path, team_id  # noqa: E402

PBP_URL = "https://api-web.nhle.com/v1/gamecenter/{game_id}/play-by-play"

# Estimating real time from the game clock
REAL_PER_GAME_SECOND = 1.75     # A 20-minute period takes about 35 real minutes
INTERMISSION         = 18 * 60  # After the 1st and 2nd periods
SHORT_BREAK          = 2 * 60   # Before overtime and the shootout
SHOOTOUT_ATTEMPT     = 45       # Real seconds per shootout attempt


def clock_seconds(text: str) -> int:
    minutes, seconds = text.split(":")
    return int(minutes) * 60 + int(seconds)


def build_steps(pbp: dict, module) -> list:
    """Replay steps for one team's monitor, from a game's play-by-play."""
    tid     = team_id(module)
    game_id = pbp["id"]
    home    = pbp["homeTeam"]["abbrev"]
    away    = pbp["awayTeam"]["abbrev"]
    if tid not in (home, away):
        raise ValueError(f"{tid} didn't play in game {game_id} ({away} @ {home})")
    abbrev  = {pbp["homeTeam"]["id"]: home, pbp["awayTeam"]["id"]: away}

    schedule_url = module.NHL_SCHEDULE_URL
    landing_url  = module.NHL_GAME_URL.format(game_id=game_id)

    def schedule(state):
        return {"url": schedule_url, "json": {"gameWeek": [{"games": [{
            "id": game_id, "gameState": state, "gameScheduleState": "OK",
            "homeTeam": {"abbrev": home}, "awayTeam": {"abbrev": away}}]}]}}

    def landing(s):
        return {"url": landing_url, "json": {
            "homeTeam":         {"abbrev": home, "score": s["home"]},
            "awayTeam":         {"abbrev": away, "score": s["away"]},
            "periodDescriptor": {"number": s["period"], "periodType": s["period_type"]},
            "clock":            {"timeRemaining": s["clock"], "inIntermission": s["intermission"]},
            "summary":          {"shootout": [dict(a) for a in s["shootout"]]},
        }}

    # Walk the plays, recording each state the landing page would have shown
    state  = {"home": 0, "away": 0, "period": 1, "period_type": "REG", "clock": "20:00",
              "intermission": False, "shootout": []}
    states = []     # (real seconds since puck drop, state)
    t = 0.0
    last_period_end = 0.0
    for play in pbp["plays"]:
        kind   = play["typeDescKey"]
        period = play["periodDescriptor"]
        ptype  = period.get("periodType", "REG")
        if kind == "period-start":
            if period["number"] > 1:
                t = last_period_end + (INTERMISSION if period["number"] <= 3 else SHORT_BREAK)
            state.update(period=period["number"], period_type=ptype, intermission=False,
                         clock=play.get("timeRemaining", "00:00"))
            period_start = t
        elif ptype == "SO":
            if kind in ("goal", "shot-on-goal", "missed-shot", "failed-shot-attempt"):
                t += SHOOTOUT_ATTEMPT
                owner  = abbrev.get(play.get("details", {}).get("eventOwnerTeamId"))
                result = "goal" if kind == "goal" else "save"
                state["shootout"] = state["shootout"] + [{"teamAbbrev": owner, "result": result}]
            else:
                continue
        else:
            t = period_start + clock_seconds(play["timeInPeriod"]) * REAL_PER_GAME_SECOND
            if kind == "goal":
                details = play["details"]
                state.update(home=details["homeScore"], away=details["awayScore"],
                             clock=play.get("timeRemaining", state["clock"]))
            elif kind == "period-end":
                last_period_end = t
                state.update(intermission=True, clock="00:00")
            else:
                continue
        states.append((t, dict(state)))

    # The final score counts the shootout winner's extra goal
    final = dict(state, home=pbp["homeTeam"]["score"], away=pbp["awayTeam"]["score"])

    steps = [schedule("PRE")] * 2
    for i, (t, s) in enumerate(states):
        next_t = states[i + 1][0] if i + 1 < len(states) else t + module.POLL_INTERVAL
        polls  = polls_for_gap(next_t - t, module.POLL_INTERVAL)
        steps += [schedule("LIVE"), landing(s)] * polls
    steps += [schedule("OFF"), landing(final)]
    return steps


def main():
    parser = argparse.ArgumentParser(description="Rebuild a past NHL game as a replay file.")
    parser.add_argument("team", help="monitor name, e.g. rangers")
    parser.add_argument("game_id", type=int, help="NHL game ID, e.g. 2026010045")
    parser.add_argument("-o", "--output", help="replay file (default tests/fixtures/<team>_<game_id>.json)")
    args = parser.parse_args()

    team   = os.path.basename(script_path(args.team)).removesuffix("_monitor.py")
    module = load_script(team)
    output = args.output or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                         "fixtures", f"{team}_{args.game_id}.json")

    pbp   = requests.get(PBP_URL.format(game_id=args.game_id), timeout=30).json()
    steps = build_steps(pbp, module)
    home, away = pbp["homeTeam"], pbp["awayTeam"]
    save_fixture(output, team,
                 f"{away['abbrev']} {away['score']} @ {home['abbrev']} {home['score']}, "
                 f"{pbp.get('gameDate', '')}, rebuilt from NHL play-by-play",
                 pbp.get("gameDate", ""), steps)
    print(f"[REBUILD] Saved {len(steps)} responses to {output}")
    print("Replay it with tests/replay_game.py, check the events against the game, "
          'then fill in "expected_events".')


if __name__ == "__main__":
    main()
