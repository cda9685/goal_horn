"""ESPN football monitors (college and NFL) against scripted games."""

import pytest

from builders import ESPN, api_error
from harness import monitors_using, team_id

TEAMS     = monitors_using("site.api.espn.com/apis/site/v2/sports/football/")
NFL_TEAMS = monitors_using("football/nfl/")
GAME      = "401700001"


@pytest.fixture(params=TEAMS)
def team(request):
    return request.param


@pytest.fixture
def espn(team, monitor):
    return ESPN(team_id(monitor(team)))


def polls_past_window(module, espn, us, them) -> list:
    """Enough identical polls for the conversion window to run out."""
    count = module.CONVERSION_WINDOW // module.POLL_INTERVAL + 1
    return espn.poll(GAME, "in", us, them) * count


def test_no_game_idles(team, espn, replay):
    result = replay(team, espn.no_game() * 2)
    assert result.events == []
    assert result.clock.sleeps == [result.module.IDLE_INTERVAL] * 2


@pytest.mark.parametrize("status", ["pre", "postponed", "canceled"])
def test_not_playing_idles(team, espn, replay, status):
    # #8: postponed and canceled games idle instead of polling fast
    result = replay(team, espn.poll(GAME, status) * 2)
    assert result.events == []
    assert result.clock.sleeps == [result.module.IDLE_INTERVAL] * 2


def test_touchdown_then_extra_point(team, espn, replay):
    steps = (espn.poll(GAME, "in", 0, 0)
             + espn.poll(GAME, "in", 6, 0)
             + espn.poll(GAME, "in", 7, 0))
    result = replay(team, steps)
    assert result.events == [f"{team}_touchdown"]
    (_, at), = result.event_times()
    assert at >= result.module.STREAM_DELAY_SECONDS


def test_touchdown_and_extra_point_in_one_poll(team, espn, replay):
    steps = espn.poll(GAME, "in", 0, 0) + espn.poll(GAME, "in", 7, 0)
    assert replay(team, steps).events == [f"{team}_touchdown"]


def test_two_point_conversion(team, espn, replay):
    steps = (espn.poll(GAME, "in", 0, 0)
             + espn.poll(GAME, "in", 6, 0)
             + espn.poll(GAME, "in", 8, 0))
    assert replay(team, steps).events == [f"{team}_touchdown"]


def test_field_goal(team, espn, replay):
    steps = espn.poll(GAME, "in", 7, 0) + espn.poll(GAME, "in", 10, 0)
    assert replay(team, steps).events == [f"{team}_score"]


def test_field_goal_right_after_touchdown(team, espn, replay):
    # Missed PAT, then a quick field goal inside the window is still a score
    steps = (espn.poll(GAME, "in", 0, 0)
             + espn.poll(GAME, "in", 6, 0)
             + espn.poll(GAME, "in", 9, 0))
    assert replay(team, steps).events == [f"{team}_touchdown", f"{team}_score"]


def test_safety_long_after_touchdown(team, espn, replay, monitor):
    steps = (espn.poll(GAME, "in", 0, 0)
             + espn.poll(GAME, "in", 6, 0)
             + polls_past_window(monitor(team), espn, 6, 0)
             + espn.poll(GAME, "in", 8, 0))
    assert replay(team, steps).events == [f"{team}_touchdown", f"{team}_score"]


def test_opponent_score_does_nothing(team, espn, replay):
    steps = espn.poll(GAME, "in", 0, 0) + espn.poll(GAME, "in", 0, 7)
    assert replay(team, steps).events == []


def test_away_team_touchdown(team, monitor, replay):
    espn = ESPN(team_id(monitor(team)), home=False)
    steps = espn.poll(GAME, "in", 0, 0) + espn.poll(GAME, "in", 7, 0)
    assert replay(team, steps).events == [f"{team}_touchdown"]


def test_first_poll_sets_baseline(team, espn, replay):
    steps = espn.poll(GAME, "in", 21, 0) + espn.poll(GAME, "halftime", 21, 0, 2)
    assert replay(team, steps).events == []


def test_touchdown_after_overturned_touchdown(team, espn, replay):
    # #20: the score drops back, then the real touchdown still fires
    steps = (espn.poll(GAME, "in", 7, 0)
             + espn.poll(GAME, "in", 13, 0)     # touchdown
             + espn.poll(GAME, "in", 7, 0)      # overturned
             + espn.poll(GAME, "in", 13, 0))    # scored on the next play
    assert replay(team, steps).events == [f"{team}_touchdown"] * 2


@pytest.mark.parametrize("team", NFL_TEAMS)
def test_nfl_win(team, espn, replay):
    steps = (espn.poll(GAME, "in", 17, 14, 4)
             + espn.poll(GAME, "in", 20, 14, 4)
             + espn.poll(GAME, "post", 20, 14, 4)
             + espn.poll(GAME, "post", 20, 14, 4))
    assert replay(team, steps).events == [f"{team}_score", f"{team}_win"]


@pytest.mark.parametrize("team", NFL_TEAMS)
def test_nfl_loss_does_not_fire_win(team, espn, replay):
    steps = espn.poll(GAME, "in", 10, 14, 4) + espn.poll(GAME, "post", 10, 14, 4)
    assert replay(team, steps).events == []


@pytest.mark.parametrize("team", NFL_TEAMS)
def test_nfl_restart_after_final_is_quiet(team, espn, replay):
    result = replay(team, espn.poll(GAME, "post", 30, 0, 4) * 2)
    assert result.events == []

# ─── Known Bugs ───────────────────────────────────────────────────────────────
# strict=True: when the bug is fixed these start passing and fail the run, so
# remember to remove the marker in the PR that fixes it.

@pytest.mark.xfail(strict=True, reason="a failed API call is treated as no game, resetting the baseline")
def test_score_during_api_error(team, espn, replay):
    steps = (espn.poll(GAME, "in", 0, 0)
             + api_error("scoreboard")
             + espn.poll(GAME, "in", 3, 0))
    assert replay(team, steps).events == [f"{team}_score"]


@pytest.mark.xfail(strict=True, reason="#27: vols doesn't queue a win event")
@pytest.mark.parametrize("team", ["vols"])
def test_vols_win(team, espn, replay):
    steps = espn.poll(GAME, "in", 17, 14, 4) + espn.poll(GAME, "post", 17, 14, 4)
    assert replay(team, steps).events == ["vols_win"]
