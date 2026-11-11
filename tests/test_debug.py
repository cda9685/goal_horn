"""
Debug logging (DEBUG = True, or --debug on the Pi) for every monitor.
Debug mode must only add [DEBUG] lines: it must never change which events fire.
"""

import re

import pytest

from builders import ESPN, MLB, NHL
from harness import load_script, monitors_using, team_id

NHL_TEAMS  = monitors_using("api-web.nhle.com")
MLB_TEAMS  = monitors_using("statsapi.mlb.com")
ESPN_TEAMS = monitors_using("site.api.espn.com/apis/site/v2/sports/football/")
GAME       = 1001

# ─── Scripted Games ───────────────────────────────────────────────────────────
# One game per API that goes through most of the monitor's debug lines.

def nhl_game(team):
    nhl = NHL(team_id(load_script(team)))
    us, them = nhl.team, nhl.opponent
    return (nhl.no_game()
            + nhl.poll(GAME, "PRE")
            + nhl.poll(GAME, "LIVE", 0, 0)
            + nhl.poll(GAME, "LIVE", 1, 0)                  # goal
            + nhl.poll(GAME, "LIVE", 0, 0)                  # overturned
            + nhl.poll(GAME, "LIVE", 1, 1)                  # real goal, then they tie
            + nhl.poll(GAME, "LIVE", 1, 1, "OT")
            + nhl.poll(GAME, "LIVE", 1, 1, "SO", [])
            + nhl.poll(GAME, "LIVE", 1, 1, "SO", [(them, "save"), (us, "goal")])
            + nhl.poll(GAME, "OFF", 2, 1, "SO", [(them, "save"), (us, "goal")]))


def mlb_game(team):
    mlb    = MLB(team_id(load_script(team)))
    g1, g2 = GAME, GAME + 1
    return (mlb.no_game()
            + mlb.poll(g1, "Preview", schedule=[(g1, "Preview"), (g2, "Preview")])
            + mlb.poll(g1, "Live", 0, 0, schedule=[(g1, "Live"), (g2, "Preview")],
                       plays=["walk"])
            + mlb.poll(g1, "Live", 2, 0, schedule=[(g1, "Live"), (g2, "Preview")],
                       plays=["walk", "home_run"])
            + mlb.poll(g1, "Live", 1, 0, schedule=[(g1, "Live"), (g2, "Preview")],
                       plays=["walk", "home_run"])         # a run taken off
            + mlb.poll(g1, "Live", 2, 0, inning=9, half="Top", outs=3,
                       schedule=[(g1, "Live"), (g2, "Preview")],
                       plays=["walk", "home_run", "out"])
            + mlb.poll(g1, "Final", 2, 0, inning=9, half="Top", outs=3,
                       schedule=[(g1, "Final"), (g2, "Preview")],
                       plays=["walk", "home_run", "out"])
            # Doubleheader: game 1 is skipped from here on
            + mlb.poll(g2, "Live", 0, 0, schedule=[(g1, "Final"), (g2, "Live")])
            + mlb.poll(g2, "Live", 1, 0, schedule=[(g1, "Final"), (g2, "Live")],
                       plays=["single"]))


def espn_game(team):
    espn = ESPN(team_id(load_script(team)))
    return (espn.no_game()
            + espn.poll(GAME, "pre")
            + espn.poll(GAME, "in", 0, 0)
            + espn.poll(GAME, "in", 6, 0, 1, "8:12")         # touchdown
            + espn.poll(GAME, "in", 7, 0, 1, "8:12")         # PAT
            + espn.poll(GAME, "in", 10, 0, 2, "0:00")        # field goal
            + espn.poll(GAME, "in", 7, 0, 2, "0:00")         # field goal overturned
            + espn.poll(GAME, "post", 7, 3, 4, "0:00"))


GAMES = ([(team, nhl_game) for team in NHL_TEAMS]
         + [(team, mlb_game) for team in MLB_TEAMS]
         + [(team, espn_game) for team in ESPN_TEAMS])
ALL   = pytest.mark.parametrize("team, game", GAMES, ids=[t for t, _ in GAMES])

# ─── Every Monitor ────────────────────────────────────────────────────────────

@ALL
def test_debug_off_prints_no_debug_lines(team, game, replay):
    # Keeping the logs small on the Pi is the point of the flag (Issue #28)
    assert replay(team, game(team)).debug_lines == []


@ALL
def test_debug_on_fires_the_same_events(team, game, replay):
    # A mistake in a debug line would be caught by the API helpers' except and
    # look like a failed request, silently dropping scores
    steps = game(team)
    off   = replay(team, steps)
    on    = replay(team, steps, debug=True)
    assert on.events == off.events
    assert on.events, "scripted game should fire at least one event"
    assert not [line for line in on.log if "[API ERROR]" in line]


@ALL
def test_debug_lines_show_api_calls_and_queue(team, game, replay):
    result = replay(team, game(team), debug=True)
    assert any(re.match(r"\[DEBUG\] GET https://\S+ -> 200 in \d+\.\d\ds", line)
               for line in result.debug_lines)
    assert any(re.match(rf"\[DEBUG\] Queue has \d+ event\(s\) before adding {team}_", line)
               for line in result.debug_lines)


@ALL
def test_debug_lines_have_no_missing_fields(team, game, replay):
    # "None" means a debug line reads a field the API response doesn't have.
    # If a monitor starts logging a new field, add it to builders.py and to
    # the trimmers in record_game.py so recorded games keep it.
    missing = [line for line in replay(team, game(team), debug=True).debug_lines
               if "None" in line]
    assert missing == []

# ─── Situations Debug Mode Is For ─────────────────────────────────────────────

@pytest.mark.parametrize("team", NHL_TEAMS)
def test_nhl_overturned_goal_is_logged(team, replay):
    lines = replay(team, nhl_game(team), debug=True).debug_lines
    assert any("goals went down 1 -> 0" in line for line in lines)


@pytest.mark.parametrize("team", NHL_TEAMS)
def test_nhl_no_game_is_logged(team, replay):
    lines = replay(team, nhl_game(team), debug=True).debug_lines
    assert any(re.search(r"No \w+ game in \d+ day\(s\) of schedule", line) for line in lines)


@pytest.mark.parametrize("team", MLB_TEAMS)
def test_mlb_run_taken_off_is_logged(team, replay):
    lines = replay(team, mlb_game(team), debug=True).debug_lines
    assert any("runs went down 2 -> 1" in line for line in lines)


@pytest.mark.parametrize("team", MLB_TEAMS)
def test_mlb_doubleheader_skip_is_logged(team, replay):
    lines = replay(team, mlb_game(team), debug=True).debug_lines
    assert any(f"skipping completed game {GAME}" in line for line in lines)


@pytest.mark.parametrize("team", ESPN_TEAMS)
def test_espn_conversion_window_is_logged(team, replay):
    result = replay(team, espn_game(team), debug=True)
    window = result.module.CONVERSION_WINDOW
    assert any(re.search(rf"\+1 came \d+s after the last touchdown \(conversion window {window}s\)",
                         line) for line in result.debug_lines)


@pytest.mark.parametrize("team", ESPN_TEAMS)
def test_espn_not_on_scoreboard_is_logged(team, replay):
    lines = replay(team, espn_game(team), debug=True).debug_lines
    assert any("not on scoreboard (0 event(s))" in line for line in lines)
