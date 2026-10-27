"""record_game.py writes a replay that plays back the same events as the live run."""

import json
import sys
import time

import requests

import record_game
from builders import ESPN, MLB, NHL
from harness import FakeResponse, ReplayFinished, load_fixture, load_script, team_id


def record(monkeypatch, tmp_path, team, steps, raw=False):
    """Run record_game.py for team with the network serving steps. Returns the fixture path."""
    served = iter(steps)

    def fake_get(url, *args, **kwargs):
        step = next(served, None)
        if step is None:
            raise ReplayFinished()
        assert step["url"] in url
        if step.get("error"):
            raise requests.ConnectionError(step["error"])
        return FakeResponse(step["json"])

    output = tmp_path / "fixtures" / f"{team}.json"
    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr(time, "sleep", lambda seconds: None)
    monkeypatch.setattr(sys, "argv", ["record_game.py", team, "-o", str(output)]
                        + (["--raw"] if raw else []))
    record_game.main()
    return output


def test_record_and_replay_nhl(monkeypatch, tmp_path, replay):
    nhl   = NHL(team_id(load_script("rangers")))
    steps = (nhl.poll(1, "PRE") * 3
             + nhl.poll(1, "LIVE", 0, 0) * 5
             + nhl.poll(1, "LIVE", 1, 0) * 5
             + nhl.schedule(1, "LIVE") + [{"url": "landing", "error": "Connection reset"}]
             + nhl.poll(1, "LIVE", 2, 0) * 5
             + nhl.poll(1, "OFF", 2, 0))
    path    = record(monkeypatch, tmp_path, "rangers", steps)
    fixture = load_fixture(path)

    assert fixture["team"] == "rangers"
    assert len(fixture["steps"]) == len(steps)
    # Repeated polls are stored once
    with open(path) as f:
        saved = json.load(f)
    assert len(saved["steps"]) < len(steps) / 3
    assert replay("rangers", fixture["steps"]).events == ["rangers_goal"] * 2


def test_trimmed_mlb_replays_like_the_original(monkeypatch, tmp_path, replay):
    mlb   = MLB(team_id(load_script("yankees")))
    steps = (mlb.poll(1, "Live", 0, 0, plays=["walk"])
             + mlb.poll(1, "Live", 1, 0, plays=["walk", "home_run"])
             + mlb.poll(1, "Live", 3, 0, plays=["walk", "home_run", "single", "double"])
             + mlb.poll(1, "Live", 3, 1, inning=9, half="Top", outs=3,
                        plays=["walk", "home_run", "single", "double", "out"]))
    # Extra fields a real response has, which trimming should drop
    for step in steps:
        step["json"]["copyright"] = "x" * 1000

    path    = record(monkeypatch, tmp_path, "yankees", steps)
    fixture = load_fixture(path)
    assert all("copyright" not in s["json"] for s in fixture["steps"])
    assert (replay("yankees", fixture["steps"]).events
            == replay("yankees", steps).events
            == ["yankees_home_run", "yankees_run", "yankees_win"])


def test_espn_keeps_only_the_teams_game(monkeypatch, tmp_path):
    espn  = ESPN(team_id(load_script("vols")))
    other = ESPN("1", "2").scoreboard("999", "in", 7, 0)[0]["json"]["events"][0]
    steps = espn.poll("5", "in", 0, 0) + espn.poll("5", "in", 7, 0)
    for step in steps:
        step["json"]["events"].insert(0, other)

    fixture = load_fixture(record(monkeypatch, tmp_path, "vols", steps))
    assert all([e["id"] for e in s["json"]["events"]] == ["5"] for s in fixture["steps"])


def test_raw_keeps_full_responses(monkeypatch, tmp_path):
    espn  = ESPN(team_id(load_script("vols")))
    steps = espn.poll("5", "in", 0, 0)
    steps[0]["json"]["leagues"] = ["extra"]
    fixture = load_fixture(record(monkeypatch, tmp_path, "vols", steps, raw=True))
    assert fixture["steps"][0]["json"] == steps[0]["json"]
