"""Checks that apply to every monitor, whatever its sport."""

import json

import pytest

from builders import ESPN, MLB, NHL
from harness import all_monitors, known_bug, load_script, monitors_using, team_id

GAME = 2001


def short_game(team) -> list:
    """A goal/run/touchdown in a live game, for whichever API the team's monitor uses."""
    tid = team_id(load_script(team))
    if team in monitors_using("api-web.nhle.com"):
        nhl = NHL(tid)
        return nhl.poll(GAME, "LIVE", 0, 0) + nhl.poll(GAME, "LIVE", 1, 0)
    if team in monitors_using("statsapi.mlb.com"):
        mlb = MLB(tid)
        return (mlb.poll(GAME, "Live", 0, 0, plays=["walk"])
                + mlb.poll(GAME, "Live", 1, 0, plays=["walk", "single"]))
    if team in monitors_using("site.api.espn.com/apis/site/v2/sports/football/"):
        espn = ESPN(tid)
        return espn.poll(GAME, "in", 0, 0) + espn.poll(GAME, "in", 7, 0)
    pytest.fail(f"No scripted game for {team}: add its API to short_game()")


@pytest.mark.parametrize("team", all_monitors())
def test_every_request_has_a_timeout(team, replay):
    # Issue #4: API calls stalled after a replay review. Without a timeout a
    # request that never answers hangs the monitor for good.
    result = replay(team, short_game(team))
    assert result.events, "scripted game should fire an event"
    for url, options in zip(result.replay.requests, result.replay.options):
        assert options.get("timeout"), f"{url} was requested without a timeout"


@known_bug(26, "the event queue isn't locked")
def test_two_monitors_queueing_at_once_keep_both_events(tmp_path):
    # Issue #26: monitor A reads the queue, monitor B appends its event, then
    # A writes back what it read plus its own event, wiping B's
    first, second = load_script("rangers", tmp_path), load_script("yankees", tmp_path)
    for m in (first, second):
        m.STREAM_DELAY_SECONDS = 0
    with open(first.EVENT_FILE, "w") as f:
        json.dump([], f)

    real_load = first.json.load

    def load_then_let_other_monitor_write(f):
        events = real_load(f)
        second.queue_event("yankees_run")       # Lands between A's read and write
        return events

    first.json = type("json", (), {"load": staticmethod(load_then_let_other_monitor_write),
                                   "dump": staticmethod(json.dump)})
    first.queue_event("rangers_goal")

    with open(first.EVENT_FILE) as f:
        assert sorted(e["event"] for e in json.load(f)) == ["rangers_goal", "yankees_run"]
