"""
Recording games ahead of time: the append-only recording log, the recorder
stopping by itself, team schedules, and dvr.py.
"""

import json
import os
import shutil
import sys
from datetime import datetime, timedelta, timezone

import pytest

import dvr
import record_game
import schedules
from builders import ESPN, MLB, NHL
from harness import Journal, load_fixture, load_script, team_id
from record_game import AFTER_FINAL_REQUESTS, journal_path
from test_record_game import record

NOW = datetime(2026, 11, 13, 20, 0, tzinfo=timezone.utc)

# ─── The Recording Log ────────────────────────────────────────────────────────

def nhl_game():
    nhl = NHL(team_id(load_script("rangers")))
    return (nhl.poll(1, "PRE") * 3 + nhl.poll(1, "LIVE", 0, 0) * 5 + nhl.poll(1, "LIVE", 1, 0) * 5
            + nhl.poll(1, "LIVE", 2, 0) * 5 + nhl.poll(1, "OFF", 2, 0) * 2)


def test_recording_log_only_ever_grows(monkeypatch, tmp_path):
    # Nothing already written is rewritten: each check, the old log is the
    # start of the new one. That's what spares the Pi's SD card.
    seen = []

    def snapshot(n, output):
        log = journal_path(output)
        if os.path.exists(log):
            with open(log, "rb") as f:
                seen.append(f.read())

    path = record(monkeypatch, tmp_path, "rangers", nhl_game(), on_request=snapshot)
    assert len(seen) > 10
    for before, after in zip(seen, seen[1:]):
        assert after.startswith(before)
    assert not os.path.exists(journal_path(path))      # Turned into the replay file
    assert len(load_fixture(path)["steps"]) == len(nhl_game())


def test_recording_log_survives_a_power_cut(monkeypatch, tmp_path, replay):
    # Copy the log mid-game and cut its last line in half, as a power cut would
    copies = []

    def cut(n, output):
        if n == 20:
            copy = tmp_path / "cut.partial.jsonl"
            shutil.copy(journal_path(output), copy)
            with open(copy, "r+b") as f:
                f.truncate(os.path.getsize(copy) - 15)
            copies.append(copy)

    record(monkeypatch, tmp_path, "rangers", nhl_game(), on_request=cut)
    steps = load_fixture(copies[0])["steps"]
    assert 17 <= len(steps) <= 19       # Only the damaged last line is lost
    assert replay("rangers", steps).events == ["rangers_goal"]


def test_recording_carries_on_after_a_restart(monkeypatch, tmp_path, replay):
    # The first part of the game is already in a log left by a crash
    steps  = nhl_game()
    output = tmp_path / "fixtures" / "rangers.json"
    output.parent.mkdir()
    log = Journal(journal_path(output), {"team": "rangers"})
    for step in steps[:9]:              # 3 pregame checks, then 3 live ones (2 requests each)
        log.add(step)
    log.close()
    path = record(monkeypatch, tmp_path, "rangers", steps[9:])
    fixture = load_fixture(path)
    assert len(fixture["steps"]) == len(steps)
    assert replay("rangers", fixture["steps"]).events == ["rangers_goal", "rangers_goal"]


def test_finish_saves_a_crashed_recording(monkeypatch, tmp_path):
    log = tmp_path / "rangers.partial.jsonl"
    journal = Journal(log, {"team": "rangers", "expected_events": None})
    for step in nhl_game()[:8]:
        journal.add(step)
    journal.close()
    monkeypatch.setattr(sys, "argv", ["record_game.py", "--finish", str(log)])
    record_game.main()
    assert not log.exists()
    assert len(load_fixture(tmp_path / "rangers.json")["steps"]) == 8

# ─── Stopping by Itself ───────────────────────────────────────────────────────

def stops_after_final(steps_to_final):
    """The recorder stopped a few requests after the final, not at the end of the network data."""
    # The request that would come next is never made
    assert record.requests == steps_to_final + AFTER_FINAL_REQUESTS


def test_stops_after_nhl_final(monkeypatch, tmp_path):
    nhl   = NHL(team_id(load_script("rangers")))
    steps = nhl.poll(1, "LIVE", 0, 0) * 3 + nhl.poll(1, "OFF", 1, 0) + nhl.no_game() * 40
    record(monkeypatch, tmp_path, "rangers", steps, args=["--stop-after-final"])
    stops_after_final(7)


def test_stops_after_mlb_final(monkeypatch, tmp_path):
    mlb   = MLB(team_id(load_script("yankees")))
    steps = mlb.poll(1, "Live", 0, 0) * 3 + mlb.poll(1, "Final", 2, 1) + mlb.schedule((1, "Final")) * 40
    record(monkeypatch, tmp_path, "yankees", steps, args=["--stop-after-final"])
    stops_after_final(7)


def test_stops_after_football_final(monkeypatch, tmp_path):
    espn  = ESPN(team_id(load_script("vols")))
    steps = espn.poll(5, "in", 0, 0) * 3 + espn.poll(5, "post", 7, 0) * 40
    record(monkeypatch, tmp_path, "vols", steps, args=["--stop-after-final"])
    stops_after_final(4)


@pytest.mark.parametrize("team, status", [("vols", "postponed"), ("rangers", "PPD")])
def test_stops_when_the_game_is_postponed(monkeypatch, tmp_path, team, status):
    tid = team_id(load_script(team))
    if team == "vols":
        steps = ESPN(tid).poll(5, status) * 40
    else:
        steps = NHL(tid).schedule(5, status) * 40
    record(monkeypatch, tmp_path, team, steps, args=["--stop-after-final", "--game", "5"])
    stops_after_final(1)


def test_game_picks_which_final_stops_it(monkeypatch, tmp_path):
    # Doubleheader: game 1's final doesn't stop a recording of game 2
    mlb    = MLB(team_id(load_script("yankees")))
    g1, g2 = 1, 2
    steps  = (mlb.poll(g1, "Final", 3, 0, schedule=[(g1, "Final"), (g2, "Preview")])
              + mlb.schedule((g1, "Final"), (g2, "Preview")) * 5
              + mlb.poll(g2, "Live", 0, 0, schedule=[(g1, "Final"), (g2, "Live")]) * 3
              + mlb.poll(g2, "Final", 1, 0, schedule=[(g1, "Final"), (g2, "Final")])
              + mlb.schedule((g1, "Final"), (g2, "Final")) * 40)
    record(monkeypatch, tmp_path, "yankees", steps, args=["--stop-after-final", "--game", "2"])
    stops_after_final(2 + 5 + 6 + 1)


def test_without_stop_after_final_it_keeps_going(monkeypatch, tmp_path):
    nhl   = NHL(team_id(load_script("rangers")))
    steps = nhl.poll(1, "OFF", 1, 0) + nhl.no_game() * 40
    record(monkeypatch, tmp_path, "rangers", steps)
    assert record.requests == len(steps) + 1     # Ran until the network data ran out

# ─── Team Schedules ───────────────────────────────────────────────────────────

def fake_get(data):
    class Response:
        def json(self):
            return data
    return lambda url, timeout=None: Response()


def test_nhl_upcoming_games():
    data = {"games": [
        {"id": 1, "startTimeUTC": "2026-11-10T00:30:00Z", "gameState": "OFF",
         "awayTeam": {"abbrev": "NYR"}, "homeTeam": {"abbrev": "BOS"}},
        {"id": 3, "startTimeUTC": "2026-11-20T00:30:00Z", "gameState": "FUT",
         "awayTeam": {"abbrev": "MTL"}, "homeTeam": {"abbrev": "NYR"}},
        {"id": 2, "startTimeUTC": "2026-11-14T02:00:00Z", "gameState": "FUT",
         "awayTeam": {"abbrev": "NYR"}, "homeTeam": {"abbrev": "VAN"}},
        {"id": 4, "startTimeUTC": "2027-01-20T00:30:00Z", "gameState": "FUT",
         "awayTeam": {"abbrev": "NYR"}, "homeTeam": {"abbrev": "TOR"}}]}
    games = schedules.upcoming_games("rangers", 30, now=NOW, get=fake_get(data))
    assert [(g.id, g.matchup, g.opponent) for g in games] == [
        ("2", "NYR @ VAN", "VAN"), ("3", "MTL @ NYR", "MTL")]


def test_mlb_upcoming_games():
    tid  = team_id(load_script("yankees"))
    data = {"dates": [{"games": [
        {"gamePk": 9, "gameDate": "2026-11-14T23:05:00Z", "status": {"abstractGameState": "Preview"},
         "teams": {"home": {"team": {"id": tid, "name": "New York Yankees"}},
                   "away": {"team": {"id": 111, "name": "Boston Red Sox"}}}}]}]}
    (game,) = schedules.upcoming_games("yankees", 30, now=NOW, get=fake_get(data))
    assert (game.id, game.opponent, game.start.hour) == ("9", "Boston Red Sox", 23)


def test_football_upcoming_games_include_one_under_way():
    tid  = team_id(load_script("vols"))
    data = {"events": [
        {"id": "7", "date": "2026-11-13T19:00Z", "competitions": [{
            "status": {"type": {"completed": False}},
            "competitors": [{"homeAway": "home", "team": {"id": "99", "abbreviation": "TA&M"}},
                            {"homeAway": "away", "team": {"id": tid, "abbreviation": "TENN"}}]}]}]}
    (game,) = schedules.upcoming_games("vols", 30, now=NOW, get=fake_get(data))
    assert (game.matchup, game.opponent) == ("TENN @ TA&M", "TA&M")


@pytest.mark.parametrize("text", ["2026-11-14T02:00:00Z", "2026-11-14T02:00Z", "2026-11-13T21:00:00-05:00"])
def test_schedule_times_are_read_in_any_api_format(text):
    assert schedules.parse_time(text) == datetime(2026, 11, 14, 2, 0, tzinfo=timezone.utc)

# ─── dvr.py ───────────────────────────────────────────────────────────────────

def game(id_="2", start=NOW + timedelta(days=1), opponent="VAN"):
    return schedules.Game(id_, start, "NYR", opponent, at_home=False)


def test_scheduling_a_game_names_its_recording(tmp_path):
    recordings = []
    entry = dvr.add(recordings, "rangers", game(), str(tmp_path))
    assert entry["status"] == "scheduled"
    assert os.path.basename(entry["output"]).startswith("rangers_2026-11-1")
    assert entry["output"].endswith("_van.json")
    assert dvr.add(recordings, "rangers", game(), str(tmp_path)) is None     # Already scheduled
    second = dvr.add(recordings, "rangers", game("3"), str(tmp_path))       # Same day, same opponent
    assert second["output"].endswith("_van-2.json")


def tick(recordings, now, alive=lambda pid: False):
    started = []
    dvr.tick(recordings, now, start=lambda r: started.append(r["game_id"]) or 1234, alive=alive)
    return started


def test_recording_starts_at_lead_time(tmp_path):
    recordings = []
    dvr.add(recordings, "rangers", game(start=NOW), str(tmp_path))
    lead = timedelta(minutes=dvr.LEAD_MINUTES)
    assert tick(recordings, NOW - lead - timedelta(minutes=1)) == []
    assert recordings[0]["status"] == "scheduled"
    assert tick(recordings, NOW - lead) == ["2"]
    assert recordings[0]["status"] == "recording"


def test_recording_missed_if_the_service_was_off(tmp_path):
    recordings = []
    dvr.add(recordings, "rangers", game(start=NOW), str(tmp_path))
    assert tick(recordings, NOW + timedelta(hours=dvr.LONGEST_GAME + 1)) == []
    assert recordings[0]["status"] == "missed"


def test_finished_recording_is_done_or_failed(tmp_path):
    recordings = []
    done = dvr.add(recordings, "rangers", game("2", NOW), str(tmp_path))
    dvr.add(recordings, "rangers", game("3", NOW), str(tmp_path))
    for r in recordings:
        r["status"], r["pid"] = "recording", 99
    with open(done["output"], "w") as f:
        json.dump({}, f)
    tick(recordings, NOW + timedelta(hours=3))
    assert [r["status"] for r in recordings] == ["done", "failed"]


def test_recording_stopped_early_carries_on(tmp_path):
    # The recorder died mid-game (e.g. the Pi rebooted) and left its log
    recordings = []
    entry = dvr.add(recordings, "rangers", game(start=NOW), str(tmp_path))
    entry["status"], entry["pid"] = "recording", 99
    Journal(journal_path(entry["output"]), {"team": "rangers"}).close()
    assert tick(recordings, NOW + timedelta(hours=1)) == ["2"]
    assert entry["status"] == "recording"


def test_recording_stopped_for_good_is_saved_as_interrupted(tmp_path):
    recordings = []
    entry = dvr.add(recordings, "rangers", game(start=NOW), str(tmp_path))
    entry["status"], entry["pid"] = "recording", 99
    log = Journal(journal_path(entry["output"]), {"team": "rangers"})
    for step in nhl_game()[:6]:
        log.add(step)
    log.close()
    assert tick(recordings, NOW + timedelta(hours=dvr.LONGEST_GAME + 1)) == []
    assert entry["status"] == "interrupted"
    assert len(load_fixture(entry["output"])["steps"]) == 6


def test_running_recording_is_left_alone(tmp_path):
    recordings = []
    entry = dvr.add(recordings, "rangers", game(start=NOW), str(tmp_path))
    entry["status"], entry["pid"] = "recording", 99
    assert tick(recordings, NOW + timedelta(hours=1), alive=lambda pid: True) == []
    assert entry["status"] == "recording"


def test_service_starts_the_recorder_for_the_game(monkeypatch, tmp_path):
    calls = []

    class Popen:
        def __init__(self, cmd, **kwargs):
            calls.append(cmd)
            self.pid = 4321
    monkeypatch.setattr(dvr.subprocess, "Popen", Popen)
    recordings = []
    entry = dvr.add(recordings, "rangers", game(start=NOW), str(tmp_path))
    assert dvr.launch(entry) == 4321
    (cmd,) = calls
    assert cmd[2:] == [dvr.RECORDER, "rangers", "--game", "2", "--stop-after-final",
                       "--max-hours", str(dvr.LONGEST_GAME), "-o", entry["output"]]


@pytest.fixture
def cli(tmp_path, monkeypatch, capsys):
    """cli(*args) runs dvr.py with its schedule in a temp dir and two upcoming games."""
    monkeypatch.setattr(dvr, "SCHEDULE_FILE", str(tmp_path / "recordings.json"))
    monkeypatch.setattr(dvr, "FIXTURE_DIR", str(tmp_path))
    monkeypatch.setattr(dvr, "upcoming_games", lambda team, days: [
        game("2", NOW + timedelta(days=1), "VAN"), game("3", NOW + timedelta(days=4), "MTL")])

    def run(*args):
        monkeypatch.setattr(sys, "argv", ["dvr.py", *args])
        dvr.main()
        return capsys.readouterr().out
    return run


def test_picking_games_schedules_them(cli):
    out = cli("rangers", "--pick", "2")
    assert "2) " in out and "NYR @ MTL" in out
    assert "Scheduled:" in out
    scheduled = cli("--scheduled")
    assert "NYR @ MTL" in scheduled and "scheduled" in scheduled and "NYR @ VAN" not in scheduled


def test_pick_all_and_cancel(cli):
    cli("rangers", "--pick", "all")
    assert cli("--scheduled").count("scheduled") == 2
    assert "Canceled" in cli("--cancel", "1")
    assert "canceled" in cli("--scheduled")


def test_picking_nothing_schedules_nothing(cli, tmp_path):
    assert "Nothing scheduled" in cli("rangers", "--pick", "")
    assert not (tmp_path / "recordings.json").exists()


def test_picking_a_number_not_listed_is_refused(cli):
    with pytest.raises(SystemExit, match="No game numbered 7"):
        cli("rangers", "--pick", "7")
