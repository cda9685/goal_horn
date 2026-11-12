"""MLB monitors against scripted games."""

import json

import pytest

from builders import MLB, api_error
from harness import FakeClock, known_bug, monitors_using, team_id

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


def test_run_when_team_plays_away(team, monitor, replay):
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


def test_win_when_team_plays_home(team, mlb, replay):
    # Home team ahead after the top of the 9th: win fires once, before the API says Final
    steps = (mlb.poll(GAME, "Live", 3, 1, inning=9, half="Top", outs=2)
             + mlb.poll(GAME, "Live", 3, 1, inning=9, half="Top", outs=3)
             + mlb.poll(GAME, "Live", 3, 1, inning=9, half="Top", outs=3)
             + mlb.poll(GAME, "Final", 3, 1, inning=9, half="Top", outs=3))
    assert replay(team, steps).events == [f"{team}_win"]


def test_win_when_team_plays_away(team, monitor, replay):
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


def test_game_data_error_is_retried(team, mlb, replay):
    steps = (mlb.poll(GAME, "Live", 0, 0, plays=["walk"])
             + mlb.schedule((GAME, "Live")) + api_error(f"game/{GAME}/feed/live")
             + mlb.poll(GAME, "Live", 1, 0, plays=["walk", "single"]))
    assert replay(team, steps).events == [f"{team}_run"]

# ─── Known Bugs ───────────────────────────────────────────────────────────────
# These check the correct behavior and fail until the issue is fixed. When a
# fix makes one pass, delete its @known_bug line in the same PR.

@known_bug(20, "overturned run hides the next run")
def test_run_after_overturned_run(team, mlb, replay):
    steps = (mlb.poll(GAME, "Live", 1, 0, plays=["single"])
             + mlb.poll(GAME, "Live", 2, 0, plays=["single", "double"])
             + mlb.poll(GAME, "Live", 1, 0, plays=["single", "double"])
             + mlb.poll(GAME, "Live", 1, 0, plays=["single", "double"])
             + mlb.poll(GAME, "Live", 1, 0, plays=["single", "double"])
             + mlb.poll(GAME, "Live", 2, 0, plays=["single", "double", "single"]))
    assert replay(team, steps).events == [f"{team}_run"] * 2


@known_bug(33, "a failed API request resets the baseline")
def test_run_during_schedule_api_error(team, mlb, replay):
    steps = (mlb.poll(GAME, "Live", 0, 0, plays=["walk"])
             + api_error("schedule?sportId=1")
             + mlb.poll(GAME, "Live", 1, 0, plays=["walk", "single"]))
    assert replay(team, steps).events == [f"{team}_run"]


# ─── Former Bugs ──────────────────────────────────────────────────────────────

def test_win_fires_once(team, mlb, replay):
    # Commits aebe461/af4fd3c: the light kept going off after a win
    steps = (mlb.poll(GAME, "Live", 3, 1, inning=9, half="Top", outs=3) * 10
             + mlb.poll(GAME, "Final", 3, 1, inning=9, half="Top", outs=3))
    assert replay(team, steps).events == [f"{team}_win"]


def test_lead_after_early_inning_is_not_a_win(team, mlb, replay):
    # Commit af4fd3c: the win check accepted any inning (>= 0), so every
    # half-inning the team led after 3 outs set the light off
    steps = (mlb.poll(GAME, "Live", 3, 1, inning=5, half="Top", outs=2)
             + mlb.poll(GAME, "Live", 3, 1, inning=5, half="Top", outs=3)
             + mlb.poll(GAME, "Live", 3, 1, inning=8, half="Top", outs=3))
    assert replay(team, steps).events == []


def test_extra_innings_win(team, monitor, replay):
    # Boundary of the inning >= 9 check: a road win in the 10th
    mlb   = MLB(team_id(monitor(team)), home=False)
    steps = (mlb.poll(GAME, "Live", 4, 3, inning=10, half="Bottom", outs=2)
             + mlb.poll(GAME, "Live", 4, 3, inning=10, half="Bottom", outs=3))
    assert replay(team, steps).events == [f"{team}_win"]


def test_doubleheader_after_restart(team, mlb, monitor, replay):
    # Issue #5: the monitor restarts between games; game 1 is remembered on disk
    g1, g2 = GAME, GAME + 1
    module = monitor(team)
    module.time = FakeClock()
    module.save_completed_game(g1, set())
    steps = (mlb.poll(g2, "Live", 0, 0, schedule=[(g1, "Final"), (g2, "Live")])
             + mlb.poll(g2, "Live", 1, 0, schedule=[(g1, "Final"), (g2, "Live")],
                        plays=["single"]))
    result = replay(team, steps, module=module)
    assert result.events == [f"{team}_run"]
    assert not any(f"game/{g1}/" in url for url in result.replay.requests)


@pytest.mark.parametrize("age_days, skipped", [(1.9, True), (2.1, False)])
def test_completed_games_are_forgotten_after_two_days(team, mlb, monitor, replay,
                                                       age_days, skipped):
    # Issue #5 fix: finished games are skipped for 2 days, then forgotten
    module = monitor(team)
    clock  = FakeClock()
    clock.now -= age_days * 86400
    module.time = clock
    module.save_completed_game(GAME, set())
    # Skipped: one schedule poll, then idle. Forgotten: the game is fetched again
    steps  = mlb.schedule((GAME, "Final"))
    if not skipped:
        steps += mlb.feed(GAME, "Final", 0, 0)
    result = replay(team, steps, module=module)
    assert any("feed/live" in url for url in result.replay.requests) != skipped
    assert result.events == []


def test_postponed_game_moves_on(team, mlb, replay):
    # Issue #8: MLB reports a postponed game as Final; the monitor should treat
    # it as over, fire nothing, and stop fetching it
    steps = (mlb.poll(GAME, "Final", 0, 0, inning=1, half="Top", outs=0)
             + mlb.schedule((GAME, "Final")))
    result = replay(team, steps)
    assert result.events == []
    assert result.clock.sleeps == [result.module.IDLE_INTERVAL] * 2


@known_bug(34, "no win when the feed goes straight to Final")
def test_win_when_feed_jumps_to_final(team, mlb, replay):
    steps = (mlb.poll(GAME, "Live", 3, 1, inning=9, half="Top", outs=2)
             + mlb.poll(GAME, "Final", 3, 1, inning=9, half="Top", outs=3))
    assert replay(team, steps).events == [f"{team}_win"]
