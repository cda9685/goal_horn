"""MLB monitors against scripted games."""

import json

import pytest

from builders import MLB, api_error
from harness import monitors_using, team_id

TEAMS = monitors_using("statsapi.mlb.com")
GAME  = 776001


@pytest.fixture(params=TEAMS)
def team(request):
    return request.param


@pytest.fixture
def mlb(team, monitor):
    return MLB(team_id(monitor(team)))


def test_no_game_idles(team, mlb, replay):
    result = replay(team, mlb.no_game() * 2)
    assert result.events == []
    assert result.clock.sleeps == [result.module.IDLE_INTERVAL] * 2


def test_run_fires_after_stream_delay(team, mlb, replay):
    steps = (mlb.poll(GAME, "Live", 0, 0, plays=["strikeout"])
             + mlb.poll(GAME, "Live", 1, 0, plays=["strikeout", "single"]))
    result = replay(team, steps)
    assert result.events == [f"{team}_run"]
    (_, at), = result.event_times()
    assert at >= result.module.STREAM_DELAY_SECONDS


def test_home_run(team, mlb, replay):
    steps = (mlb.poll(GAME, "Live", 0, 0, plays=["strikeout"])
             + mlb.poll(GAME, "Live", 1, 0, plays=["strikeout", "home_run"]))
    assert replay(team, steps).events == [f"{team}_home_run"]


def test_home_run_seen_one_play_late(team, mlb, replay):
    # The next at-bat already started by the time the score updated (#2)
    steps = (mlb.poll(GAME, "Live", 0, 0, plays=["strikeout"])
             + mlb.poll(GAME, "Live", 1, 0, plays=["strikeout", "home_run", "walk"]))
    assert replay(team, steps).events == [f"{team}_home_run"]


def test_multiple_runs_on_one_play_fire_once(team, mlb, replay):
    # #1: once per run-scoring play, not once per run
    steps = (mlb.poll(GAME, "Live", 0, 0, plays=["walk"])
             + mlb.poll(GAME, "Live", 3, 0, plays=["walk", "double"]))
    assert replay(team, steps).events == [f"{team}_run"]


def test_away_team_run(team, monitor, replay):
    mlb = MLB(team_id(monitor(team)), home=False)
    steps = (mlb.poll(GAME, "Live", 0, 0, plays=["walk"])
             + mlb.poll(GAME, "Live", 1, 0, plays=["walk", "single"]))
    assert replay(team, steps).events == [f"{team}_run"]


def test_opponent_run_does_nothing(team, mlb, replay):
    steps = (mlb.poll(GAME, "Live", 0, 0, plays=["walk"])
             + mlb.poll(GAME, "Live", 0, 2, plays=["walk", "home_run"]))
    assert replay(team, steps).events == []


def test_first_poll_sets_baseline(team, mlb, replay):
    steps = (mlb.poll(GAME, "Live", 4, 0, plays=["single"])
             + mlb.poll(GAME, "Live", 4, 0, plays=["single", "out"]))
    assert replay(team, steps).events == []


def test_win_at_home(team, mlb, replay):
    # Home team ahead after the top of the 9th: win fires once, before the API says Final
    steps = (mlb.poll(GAME, "Live", 3, 1, inning=9, half="Top", outs=2)
             + mlb.poll(GAME, "Live", 3, 1, inning=9, half="Top", outs=3)
             + mlb.poll(GAME, "Live", 3, 1, inning=9, half="Top", outs=3)
             + mlb.poll(GAME, "Final", 3, 1, inning=9, half="Top", outs=3))
    assert replay(team, steps).events == [f"{team}_win"]


def test_win_on_the_road(team, monitor, replay):
    mlb = MLB(team_id(monitor(team)), home=False)
    steps = (mlb.poll(GAME, "Live", 3, 1, inning=9, half="Bottom", outs=2)
             + mlb.poll(GAME, "Live", 3, 1, inning=9, half="Bottom", outs=3)
             + mlb.poll(GAME, "Final", 3, 1, inning=9, half="Bottom", outs=3))
    assert replay(team, steps).events == [f"{team}_win"]


def test_walk_off(team, mlb, replay):
    steps = (mlb.poll(GAME, "Live", 2, 2, inning=9, half="Bottom", outs=1, plays=["out"])
             + mlb.poll(GAME, "Live", 3, 2, inning=9, half="Bottom", outs=1,
                        plays=["out", "home_run"]))
    assert replay(team, steps).events == [f"{team}_home_run", f"{team}_win"]


def test_loss_does_not_fire_win(team, mlb, replay):
    steps = (mlb.poll(GAME, "Live", 1, 3, inning=9, half="Top", outs=3)
             + mlb.poll(GAME, "Final", 1, 3, inning=9, half="Bottom", outs=3))
    assert replay(team, steps).events == []


def test_doubleheader(team, mlb, replay):
    # #5: game 1 ends, game 2 must still fire
    g1, g2 = GAME, GAME + 1
    steps = (mlb.poll(g1, "Live", 0, 0, schedule=[(g1, "Live"), (g2, "Preview")])
             + mlb.poll(g1, "Live", 1, 0, schedule=[(g1, "Live"), (g2, "Preview")],
                        plays=["single"])
             + mlb.poll(g1, "Final", 1, 0, schedule=[(g1, "Final"), (g2, "Preview")],
                        plays=["single"])
             + mlb.poll(g2, "Preview", schedule=[(g1, "Final"), (g2, "Preview")])
             + mlb.poll(g2, "Live", 0, 0, schedule=[(g1, "Final"), (g2, "Live")])
             + mlb.poll(g2, "Live", 1, 0, schedule=[(g1, "Final"), (g2, "Live")],
                        plays=["home_run"]))
    result = replay(team, steps)
    assert result.events == [f"{team}_run", f"{team}_home_run"]
    with open(result.module.COMPLETED_GAMES_FILE) as f:
        assert [e["pk"] for e in json.load(f)] == [g1]


def test_restart_after_final_is_quiet(team, mlb, replay):
    # Monitor starts after the game ended: no runs or win, and the game is skipped after
    steps = (mlb.poll(GAME, "Final", 5, 0, inning=9, half="Top", outs=3)
             + mlb.schedule((GAME, "Final")))
    result = replay(team, steps)
    assert result.events == []
    # The second schedule poll skipped the finished game instead of fetching it again
    assert sum("feed/live" in url for url in result.replay.requests) == 1
    assert result.clock.sleeps == [result.module.IDLE_INTERVAL] * 2


def test_api_error_recovers(team, mlb, replay):
    steps = (mlb.poll(GAME, "Live", 0, 0, plays=["walk"])
             + mlb.schedule((GAME, "Live")) + api_error(f"game/{GAME}/feed/live")
             + mlb.poll(GAME, "Live", 1, 0, plays=["walk", "single"]))
    assert replay(team, steps).events == [f"{team}_run"]

# ─── Known Bugs ───────────────────────────────────────────────────────────────
# strict=True: when the bug is fixed these start passing and fail the run, so
# remember to remove the marker in the PR that fixes it.

@pytest.mark.xfail(strict=True, reason="#20: overturned run hides the next run")
def test_run_after_overturned_run(team, mlb, replay):
    steps = (mlb.poll(GAME, "Live", 1, 0, plays=["single"])
             + mlb.poll(GAME, "Live", 2, 0, plays=["single", "double"])
             + mlb.poll(GAME, "Live", 1, 0, plays=["single", "double"])
             + mlb.poll(GAME, "Live", 1, 0, plays=["single", "double"])
             + mlb.poll(GAME, "Live", 1, 0, plays=["single", "double"])
             + mlb.poll(GAME, "Live", 2, 0, plays=["single", "double", "single"]))
    assert replay(team, steps).events == [f"{team}_run"] * 2


@pytest.mark.xfail(strict=True, reason="a failed API call is treated as no game, resetting the baseline")
def test_run_during_schedule_api_error(team, mlb, replay):
    steps = (mlb.poll(GAME, "Live", 0, 0, plays=["walk"])
             + api_error("schedule?sportId=1")
             + mlb.poll(GAME, "Live", 1, 0, plays=["walk", "single"]))
    assert replay(team, steps).events == [f"{team}_run"]
