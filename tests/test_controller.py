"""controller.py off the Pi, and that its config matches the monitors and audio/."""

import json
import os
import re

import pytest

from harness import FakeClock, ReplayFinished, all_monitors, load_controller, script_path


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def controller(tmp_path, clock):
    module = load_controller(tmp_path, clock)
    module.played = []
    module.play_audio = lambda path: module.played.append(
        path and os.path.basename(path))
    return module


def queued_event_names(team: str) -> set[str]:
    """Every event name a monitor's source passes to queue_event()."""
    source = script_path(team).read_text()
    return set(re.findall(r'queue_event\(\s*"([a-z_]+)"', source))

# ─── Config ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("team", all_monitors())
def test_monitor_events_are_configured(team, controller):
    # Unknown events silently fall back to a 5s light with no audio
    events = queued_event_names(team)
    assert events, f"No queue_event calls found in {team}_monitor.py"
    for event in events:
        assert event in controller.AUDIO, f"{event} missing from AUDIO"
        if not isinstance(controller.AUDIO[event], list):
            assert event in controller.LIGHT_DURATION, f"{event} missing from LIGHT_DURATION"


def test_every_light_duration_has_audio_entry(controller):
    assert set(controller.LIGHT_DURATION) <= set(controller.AUDIO)


def test_audio_files_exist(controller):
    for event, audio in controller.AUDIO.items():
        paths = [p for p, _ in audio] if isinstance(audio, list) else [audio]
        for path in paths:
            assert path is None or os.path.isfile(path), f"{event}: {path} not found"


def test_events_are_prefixed_with_their_team():
    for team in all_monitors():
        for event in queued_event_names(team):
            assert event.startswith(f"{team}_"), f"{team}_monitor.py queues {event}"

# ─── Processing Events ────────────────────────────────────────────────────────

def test_event_turns_light_on_plays_audio_then_off(controller):
    controller.process_event({"event": "rangers_goal"})
    assert controller.played == ["rangers_goal_song.mp3"]
    assert controller.GPIO.actions == [("on", 0), ("off", controller.LIGHT_DURATION["rangers_goal"])]


def test_light_only_event(controller):
    controller.process_event({"event": "rangers_shootout"})
    assert controller.played == [None]
    assert controller.GPIO.actions == [("on", 0), ("off", 5)]


def test_unknown_event_falls_back_to_short_light(controller):
    controller.process_event({"event": "not_a_real_event"})
    assert controller.played == [None]
    assert controller.GPIO.actions == [("on", 0), ("off", 5)]


def test_random_version_uses_its_own_duration(controller):
    for _ in range(20):
        controller.GPIO.actions.clear()
        controller.played.clear()
        controller.process_event({"event": "vols_touchdown"})
        durations = {os.path.basename(p): d for p, d in controller.AUDIO["vols_touchdown"]}
        (song,) = controller.played
        (_, on), (_, off) = controller.GPIO.actions
        assert off - on == durations[song]


class StopAfter(FakeClock):
    """A clock that ends the controller's main loop after a number of queue polls."""

    def __init__(self, polls: int, poll_interval: float):
        super().__init__()
        self.polls, self.poll_interval = polls, poll_interval

    def sleep(self, seconds):
        super().sleep(seconds)
        if seconds == self.poll_interval:
            self.polls -= 1
            if self.polls == 0:
                raise ReplayFinished()


def test_main_plays_queue_in_priority_order(tmp_path):
    controller = load_controller(tmp_path)
    controller.time = StopAfter(polls=2, poll_interval=controller.POLL_INTERVAL)
    controller.GPIO.clock = controller.time
    controller.played = []
    controller.play_audio = lambda path: controller.played.append(path and os.path.basename(path))

    queue = [{"event": "vols_touchdown", "priority": 3, "timestamp": 0},
             {"event": "yankees_run",    "priority": 1, "timestamp": 0},
             {"event": "rangers_goal",   "priority": 2, "timestamp": 0}]
    with open(controller.EVENT_FILE, "w") as f:
        json.dump(queue, f)

    controller.main()

    assert controller.played[:2] == ["yankees_doorbell.mp3", "rangers_goal_song.mp3"]
    assert controller.played[2].startswith("vols_rocky_top")
    with open(controller.EVENT_FILE) as f:
        assert json.load(f) == []
    assert controller.GPIO.actions[-1][0] == "off"
