"""
Adversarial tests: broken, missing or unexpected data from the APIs and the
event queue. The goal horn runs unattended for months on APIs it doesn't
control, so a bad response must never crash a monitor, fake a score, or lose
events.
"""

import json
import os

import pytest

from builders import ESPN, MLB, NHL
from harness import known_bug, load_controller, load_script, monitors_using, team_id
from test_all_monitors import short_game
from test_controller import StopAfter

NHL_TEAMS  = monitors_using("api-web.nhle.com")
MLB_TEAMS  = monitors_using("statsapi.mlb.com")
ESPN_TEAMS = monitors_using("site.api.espn.com/apis/site/v2/sports/football/")
ALL_TEAMS  = NHL_TEAMS + MLB_TEAMS + ESPN_TEAMS
GAME       = 3001

BLANK_SCORE = known_bug(36, "a blank score is read as 0")
CRASH       = known_bug(37, "unexpected API data crashes the monitor")
BAD_QUEUE   = known_bug(38, "a corrupted queue file loses every later event")


def builder(team):
    tid = team_id(load_script(team))
    if team in NHL_TEAMS:
        return NHL(tid)
    if team in MLB_TEAMS:
        return MLB(tid)
    return ESPN(tid)


def live(team, score):
    """One poll of a live game with the tracked team on score and the opponent on 0."""
    b = builder(team)
    if team in NHL_TEAMS:
        return b.poll(GAME, "LIVE", score, 0)
    if team in MLB_TEAMS:
        return b.poll(GAME, "Live", score, 0, plays=["single"] * (score + 1))
    return b.poll(GAME, "in", score, 0)


def first_request(team) -> str:
    """URL fragment of the first request in each poll."""
    if team in NHL_TEAMS:
        return "schedule/now"
    if team in MLB_TEAMS:
        return "schedule?sportId=1"
    return "scoreboard"


def game_request(team) -> str | None:
    """URL fragment of the second request (game data), if the API has one."""
    if team in NHL_TEAMS:
        return f"gamecenter/{GAME}/landing"
    if team in MLB_TEAMS:
        return f"game/{GAME}/feed/live"
    return None


def with_bad_game_data(team, step) -> list:
    """A poll whose game-data request gets step instead of a real response."""
    return builder(team).poll(GAME, "LIVE" if team in NHL_TEAMS else "Live")[:1] + [step]

# ─── Bad Responses ────────────────────────────────────────────────────────────
# A monitor that crashes stays down until the Pi reboots or someone runs
# ./restart.sh -m, so every game after that is missed.

@pytest.mark.parametrize("team", ALL_TEAMS)
def test_html_error_page_does_not_crash(team, replay):
    # A 200 response whose body is an HTML page (e.g. a CDN error page)
    steps = (live(team, 0)
             + [{"url": first_request(team), "text": "<html>Service Unavailable</html>"}]
             + live(team, 0))
    replay(team, steps)                 # Fails if the monitor crashes before using every step


@pytest.mark.parametrize("team", NHL_TEAMS + MLB_TEAMS)
def test_server_error_on_game_data_is_retried(team, replay):
    # A 500 on the game-data request: the monitor keeps its baseline and retries
    steps = (live(team, 0)
             + with_bad_game_data(team, {"url": game_request(team), "status": 500, "json": {}})
             + live(team, 1))
    assert len(replay(team, steps).events) == 1


@CRASH
@pytest.mark.parametrize("team", ALL_TEAMS)
def test_empty_body_does_not_crash(team, replay):
    # A 200 response with "null" as its body
    steps = live(team, 0) + [{"url": first_request(team), "json": None}] + live(team, 0)
    replay(team, steps)


@CRASH
@pytest.mark.parametrize("team", NHL_TEAMS + MLB_TEAMS)
def test_empty_game_data_does_not_crash(team, replay):
    steps = (live(team, 0)
             + with_bad_game_data(team, {"url": game_request(team), "json": None})
             + live(team, 0))
    replay(team, steps)


@CRASH
@pytest.mark.parametrize("team", NHL_TEAMS + MLB_TEAMS)
def test_null_score_does_not_crash(team, replay):
    # The score field is present but null for one poll
    bad = live(team, 1)[-1]
    data = json.loads(json.dumps(bad["json"]))
    if team in NHL_TEAMS:
        data["homeTeam"]["score"] = None
    else:
        data["liveData"]["linescore"]["teams"]["home"]["runs"] = None
    steps = live(team, 0) + live(team, 0)[:1] + [{**bad, "json": data}] + live(team, 1)
    assert len(replay(team, steps).events) == 1


@BLANK_SCORE
@pytest.mark.parametrize("team", ESPN_TEAMS)
@pytest.mark.parametrize("blank", ["", None, "--"])
def test_blank_score_is_not_a_score(team, replay, blank):
    # 7 -> blank -> 7: the blank is read as 0, taken as an overturn, and the
    # same touchdown fires again when 7 comes back
    bad = live(team, 7)[0]
    data = json.loads(json.dumps(bad["json"]))
    data["events"][0]["competitions"][0]["competitors"][0]["score"] = blank
    steps = live(team, 7) + [{**bad, "json": data}] + live(team, 7)
    assert replay(team, steps).events == []


@pytest.mark.parametrize("team", ALL_TEAMS)
def test_other_teams_games_are_ignored(team, replay):
    # Another game, with scores changing, listed before the tracked team's game
    other_tid = "1" if team in ESPN_TEAMS else ("TOR" if team in NHL_TEAMS else 999)
    other     = type(builder(team))(other_tid, builder(team).opponent)

    def with_other_game(steps, other_score):
        first   = json.loads(json.dumps(steps[0]))
        decoy   = (other.poll(GAME + 1, "in", other_score, 0) if team in ESPN_TEAMS
                   else other.schedule(GAME + 1, "LIVE") if team in NHL_TEAMS
                   else other.schedule((GAME + 1, "Live")))[0]["json"]
        if team in ESPN_TEAMS:
            first["json"]["events"] = decoy["events"] + first["json"]["events"]
        elif team in NHL_TEAMS:
            first["json"]["gameWeek"][0]["games"] = (decoy["gameWeek"][0]["games"]
                                                     + first["json"]["gameWeek"][0]["games"])
        else:
            first["json"]["dates"][0]["games"] = (decoy["dates"][0]["games"]
                                                  + first["json"]["dates"][0]["games"])
        return [first] + steps[1:]

    steps = with_other_game(live(team, 0), 0) + with_other_game(live(team, 0), 14)
    assert replay(team, steps).events == []

# ─── Bad Event Queue ──────────────────────────────────────────────────────────
# A power cut while the queue is being written leaves half a JSON file.

HALF_WRITTEN = '[{"event": "rangers_go'


@BAD_QUEUE
@pytest.mark.parametrize("team", ALL_TEAMS)
def test_monitor_recovers_from_corrupted_queue(team, monitor, replay):
    module = monitor(team)
    with open(module.EVENT_FILE, "w") as f:
        f.write(HALF_WRITTEN)
    result = replay(team, short_game(team), module=module)
    assert result.queue_readable
    assert len(result.events) == 1


@BAD_QUEUE
def test_controller_recovers_from_corrupted_queue(tmp_path):
    controller = load_controller(tmp_path)
    controller.time = StopAfter(polls=2, poll_interval=controller.POLL_INTERVAL)
    with open(controller.EVENT_FILE, "w") as f:
        f.write(HALF_WRITTEN)
    controller.main()
    with open(controller.EVENT_FILE) as f:
        json.load(f)                    # The controller should have reset the file
    assert os.path.getsize(controller.EVENT_FILE) > 0
