"""NHL monitors against scripted games."""

import pytest

from builders import NHL, api_error
from harness import monitors_using, team_id

TEAMS = monitors_using("api-web.nhle.com")
GAME  = 2026020001


@pytest.fixture(params=TEAMS)
def team(request):
    return request.param


@pytest.fixture
def nhl(team, monitor):
    return NHL(team_id(monitor(team)))


def test_no_game_idles(team, nhl, replay):
    result = replay(team, nhl.no_game() * 3)
    assert result.events == []
    assert result.clock.sleeps == [result.module.IDLE_INTERVAL] * 3


def test_upcoming_game_idles(team, nhl, replay):
    result = replay(team, nhl.poll(GAME, "FUT") + nhl.poll(GAME, "PRE"))
    assert result.events == []
    assert result.clock.sleeps == [result.module.IDLE_INTERVAL] * 2


def test_goal_fires_after_stream_delay(team, nhl, replay):
    result = replay(team, nhl.poll(GAME, "LIVE", 0, 0) + nhl.poll(GAME, "LIVE", 1, 0))
    assert result.events == [f"{team}_goal"]
    (_, at), = result.event_times()
    assert at >= result.module.STREAM_DELAY_SECONDS


def test_away_team_goal(team, monitor, replay):
    nhl = NHL(team_id(monitor(team)), home=False)
    result = replay(team, nhl.poll(GAME, "LIVE", 0, 0) + nhl.poll(GAME, "LIVE", 1, 0))
    assert result.events == [f"{team}_goal"]


def test_opponent_goal_does_nothing(team, nhl, replay):
    result = replay(team, nhl.poll(GAME, "LIVE", 0, 0) + nhl.poll(GAME, "LIVE", 0, 1))
    assert result.events == []


def test_first_poll_sets_baseline(team, nhl, replay):
    # Monitor restarted mid-game with the team already up 3-0: no light for old goals
    result = replay(team, nhl.poll(GAME, "LIVE", 3, 0) + nhl.poll(GAME, "LIVE", 3, 0))
    assert result.events == []


def test_two_goals_between_polls(team, nhl, replay):
    result = replay(team, nhl.poll(GAME, "LIVE", 0, 0) + nhl.poll(GAME, "LIVE", 2, 0))
    assert result.events == [f"{team}_goal"] * 2


def test_full_game(team, nhl, replay):
    steps = (nhl.poll(GAME, "PRE")
             + nhl.poll(GAME, "LIVE", 0, 0)
             + nhl.poll(GAME, "LIVE", 1, 0)
             + nhl.poll(GAME, "LIVE", 1, 1)
             + nhl.poll(GAME, "CRIT", 2, 1)
             + nhl.poll(GAME, "OFF", 2, 1)
             + nhl.no_game())
    result = replay(team, steps)
    assert result.events == [f"{team}_goal"] * 2


def test_score_glitch_does_not_double_fire(team, nhl, replay):
    # API briefly reports one goal fewer, then corrects itself (#16)
    steps = (nhl.poll(GAME, "LIVE", 2, 0)
             + nhl.poll(GAME, "LIVE", 1, 0)
             + nhl.poll(GAME, "LIVE", 2, 0))
    assert replay(team, steps).events == []


def test_shootout_goals(team, nhl, replay):
    us, them = nhl.team, nhl.opponent
    steps = (nhl.poll(GAME, "LIVE", 2, 2, "OT")
             + nhl.poll(GAME, "LIVE", 2, 2, "SO", [])
             + nhl.poll(GAME, "LIVE", 2, 2, "SO", [(them, "save"), (us, "goal")])
             + nhl.poll(GAME, "LIVE", 2, 2, "SO", [(them, "save"), (us, "goal"),
                                                    (them, "goal"), (us, "save")])
             + nhl.poll(GAME, "LIVE", 2, 2, "SO", [(them, "save"), (us, "goal"),
                                                    (them, "goal"), (us, "save"),
                                                    (them, "save"), (us, "goal")]))
    assert replay(team, steps).events == [f"{team}_shootout"] * 2


def test_new_game_resets_baseline(team, nhl, replay):
    # Game 1 ends 4-0 but the monitor misses the final; game 2 starts at 0-0
    steps = (nhl.poll(GAME, "LIVE", 4, 0)
             + nhl.poll(GAME + 1, "LIVE", 0, 0)
             + nhl.poll(GAME + 1, "LIVE", 1, 0))
    assert replay(team, steps).events == [f"{team}_goal"]


def test_api_error_recovers(team, nhl, replay):
    steps = (nhl.poll(GAME, "LIVE", 0, 0)
             + nhl.schedule(GAME, "LIVE") + api_error(f"gamecenter/{GAME}")
             + nhl.poll(GAME, "LIVE", 1, 0))
    assert replay(team, steps).events == [f"{team}_goal"]

# ─── Known Bugs ───────────────────────────────────────────────────────────────
# strict=True: when the bug is fixed these start passing and fail the run, so
# remember to remove the marker in the PR that fixes it.

@pytest.mark.xfail(strict=True, reason="#20: overturned goal hides the next goal")
def test_goal_after_overturned_goal(team, nhl, replay):
    steps = (nhl.poll(GAME, "LIVE", 1, 0)
             + nhl.poll(GAME, "LIVE", 2, 0)     # goal
             + nhl.poll(GAME, "LIVE", 1, 0)     # overturned
             + nhl.poll(GAME, "LIVE", 1, 0)
             + nhl.poll(GAME, "LIVE", 1, 0)
             + nhl.poll(GAME, "LIVE", 2, 0))    # real goal
    assert replay(team, steps).events == [f"{team}_goal"] * 2


@pytest.mark.xfail(strict=True, reason="a failed API call is treated as no game, resetting the baseline")
def test_goal_during_schedule_api_error(team, nhl, replay):
    steps = (nhl.poll(GAME, "LIVE", 0, 0)
             + api_error("schedule/now")
             + nhl.poll(GAME, "LIVE", 1, 0))
    assert replay(team, steps).events == [f"{team}_goal"]


@pytest.mark.xfail(strict=True, reason="#8/#27: postponed games aren't skipped")
def test_postponed_game_idles(team, nhl, replay):
    result = replay(team, nhl.schedule(GAME, "PPD") * 3)
    assert result.clock.sleeps == [result.module.IDLE_INTERVAL] * 3


@pytest.mark.xfail(strict=True, reason="#27: NHL monitors don't queue a win event")
def test_win_event(team, nhl, replay):
    steps = (nhl.poll(GAME, "LIVE", 1, 0) + nhl.poll(GAME, "LIVE", 2, 0)
             + nhl.poll(GAME, "OFF", 2, 0))
    assert replay(team, steps).events == [f"{team}_goal", f"{team}_win"]
