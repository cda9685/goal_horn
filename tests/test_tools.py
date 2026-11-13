"""
fire_event.py and run_controller.py, the tools for checking the light and audio.
Both use a temporary event queue here, so running the tests on the Pi never
sets off the real goal horn.
"""

import json
import sys

import pytest

import fire_event
import run_controller
from harness import load_controller, load_script
from test_controller import StopAfter


@pytest.fixture
def fire(tmp_path, monkeypatch):
    """fire(*args) runs fire_event.py with its queue in a temp dir; returns the queue file."""
    controller = load_script("controller", tmp_path)
    monkeypatch.setattr(fire_event, "load_script", lambda name: controller)

    def run(*args):
        monkeypatch.setattr(sys, "argv", ["fire_event.py", *args])
        fire_event.main()
        return controller.EVENT_FILE
    return run


def queued(path) -> list:
    with open(path) as f:
        return json.load(f)


def test_fire_event_queues_events(fire):
    path = fire("vols_touchdown", "rangers_goal", "--priority", "2")
    events = queued(path)
    assert [e["event"] for e in events] == ["vols_touchdown", "rangers_goal"]
    assert all(e["priority"] == 2 and e["timestamp"] for e in events)


def test_fire_event_adds_to_events_already_queued(fire):
    fire("rangers_goal")
    path = fire("yankees_run")
    assert [e["event"] for e in queued(path)] == ["rangers_goal", "yankees_run"]


def test_fire_event_refuses_unknown_events(fire, tmp_path):
    with pytest.raises(SystemExit) as exit_:
        fire("rangers_gaol")
    assert "Unknown event(s): rangers_gaol" in str(exit_.value)
    assert not (tmp_path / "goal_horn_events.json").exists()


def test_fire_event_force_sends_unknown_events(fire):
    assert [e["event"] for e in queued(fire("--force", "made_up"))] == ["made_up"]


def test_fire_event_list_shows_every_event(fire, capsys):
    fire("--list")
    out = capsys.readouterr().out
    controller = load_script("controller")
    for event in set(controller.AUDIO) | set(controller.LIGHT_DURATION):
        assert event in out


def test_fired_events_play_on_the_controller(fire, tmp_path):
    # What fire_event.py writes is what the controller reads and plays
    fire("rangers_goal")
    controller = load_controller(tmp_path)
    controller.time = StopAfter(polls=2, poll_interval=controller.POLL_INTERVAL)
    controller.GPIO.clock = controller.time
    played = []
    controller.play_audio = lambda path: played.append(path)
    controller.main()
    assert [p and p.split("/")[-1] for p in played] == ["rangers_goal_song.mp3"]
    assert controller.GPIO.actions[-2:] == [("on", 0), ("off", controller.LIGHT_DURATION["rangers_goal"])]


def test_run_controller_fast_clock_skips_only_light_durations(monkeypatch):
    waited = []
    monkeypatch.setattr("time.sleep", lambda seconds: waited.append(seconds))
    clock = run_controller.FastClock(poll_interval=0.5)
    clock.sleep(0.5)
    clock.sleep(60)
    assert waited == [0.5]          # The queue poll waits; the 60s light doesn't


def test_run_controller_finds_a_player_or_none(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda cmd: "/usr/bin/ffplay" if cmd == "ffplay" else None)
    assert run_controller.local_player()[0] == "ffplay"
    monkeypatch.setattr("shutil.which", lambda cmd: None)
    assert run_controller.local_player() is None
