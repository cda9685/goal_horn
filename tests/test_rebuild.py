"""The rebuild tools turn a game's history into replays the monitors read correctly."""

import json

import pytest

import rebuild_espn_game
import rebuild_nhl_game
from builders import NHL
from harness import expand_steps, load_recording, load_script, save_recording, team_id

# ─── Replay Files ─────────────────────────────────────────────────────────────

def test_saved_repeats_replay_once(tmp_path):
    # A step repeated n times must replay n times, not n * n
    step  = {"url": "scoreboard", "json": {"events": []}}
    path  = tmp_path / "game.json"
    save_recording(path, "vols", "", "", [step] * 5 + [{"url": "scoreboard", "json": None}])
    with open(path) as f:
        assert json.load(f)["steps"][0]["repeat"] == 5
    steps = load_recording(path)["steps"]
    assert len(steps) == 6
    assert len(expand_steps(steps)) == 6        # Expanding again changes nothing

def test_replay_that_doesnt_match_the_monitor_fails(replay):
    # The monitors catch every exception from a request, so a replay that no
    # longer matches what the monitor asks for must fail the test some other way
    nhl   = NHL(team_id(load_script("rangers")))
    steps = nhl.poll(1, "LIVE", 0, 0) + nhl.schedule(1, "LIVE") + nhl.schedule(1, "LIVE")
    with pytest.raises(AssertionError, match="monitor requested .*landing"):
        replay("rangers", steps)


# ─── NHL ──────────────────────────────────────────────────────────────────────

def nhl_game(team_abbrev, home_score, away_score, plays):
    return {"id": 2026099999,
            "homeTeam": {"id": 1, "abbrev": team_abbrev, "score": home_score},
            "awayTeam": {"id": 2, "abbrev": "BOS", "score": away_score},
            "plays": plays}


def period(n, kind="REG"):
    return [{"typeDescKey": "period-start", "periodDescriptor": {"number": n, "periodType": kind},
             "timeInPeriod": "00:00", "timeRemaining": "20:00"}]


def period_end(n, kind="REG"):
    return [{"typeDescKey": "period-end", "periodDescriptor": {"number": n, "periodType": kind},
             "timeInPeriod": "20:00", "timeRemaining": "00:00"}]


def goal(n, at, home, away, owner):
    return [{"typeDescKey": "goal", "periodDescriptor": {"number": n, "periodType": "REG"},
             "timeInPeriod": at, "timeRemaining": "10:00",
             "details": {"homeScore": home, "awayScore": away, "eventOwnerTeamId": owner}}]


def shootout_attempt(owner, scored):
    return [{"typeDescKey": "goal" if scored else "shot-on-goal",
             "periodDescriptor": {"number": 5, "periodType": "SO"},
             "timeInPeriod": "00:00", "details": {"eventOwnerTeamId": owner}}]


def test_nhl_goals_and_shootout(replay):
    module = load_script("rangers")
    tid    = team_id(module)
    plays  = (period(1) + goal(1, "05:00", 1, 0, 1) + goal(1, "15:00", 1, 1, 2) + period_end(1)
              + period(2) + goal(2, "02:00", 2, 1, 1) + goal(2, "03:00", 2, 2, 2) + period_end(2)
              + period(5, "SO") + shootout_attempt(2, False) + shootout_attempt(1, True)
              + shootout_attempt(2, False) + period_end(5, "SO"))
    steps  = rebuild_nhl_game.build_steps(nhl_game(tid, 3, 2, plays), module)
    result = replay("rangers", steps)
    assert result.events == ["rangers_goal", "rangers_goal", "rangers_shootout"]


def test_nhl_real_time_is_estimated_from_the_game_clock(replay):
    # Two goals 10 game minutes apart are about 19 real minutes apart, and
    # the replay spaces them out as polls (gaps over 10 minutes are shortened)
    module = load_script("rangers")
    tid    = team_id(module)
    plays  = period(1) + goal(1, "02:00", 1, 0, 1) + goal(1, "12:00", 2, 0, 1)
    result = replay("rangers", rebuild_nhl_game.build_steps(nhl_game(tid, 2, 0, plays), module))
    (_, first), (_, second) = result.event_times()
    assert 9 * 60 < second - first < 11 * 60 + 2 * module.STREAM_DELAY_SECONDS

# ─── ESPN ─────────────────────────────────────────────────────────────────────

def espn_game(team_id_, plays, final):
    return {"header": {"id": "401999999", "competitions": [{"competitors": [
                {"id": team_id_, "homeAway": "home", "score": str(final[0]),
                 "team": {"id": team_id_, "abbreviation": "US"}},
                {"id": "99", "homeAway": "away", "score": str(final[1]),
                 "team": {"id": "99", "abbreviation": "THEM"}}]}]},
            "drives": {"previous": [{"plays": plays}]}}


def play(minute, home, away, kind="Rush", quarter=1):
    return {"wallclock": f"2026-10-01T20:{minute:02d}:00Z", "period": {"number": quarter},
            "clock": {"displayValue": "10:00"}, "homeScore": home, "awayScore": away,
            "type": {"text": kind}, "text": ""}


def test_espn_touchdown_and_extra_point_are_split(replay):
    # ESPN's play shows +7; the rebuild shows +6, then +1 a minute later
    module = load_script("dolphins")
    plays  = [play(0, 0, 0), play(5, 7, 0, "Passing Touchdown"), play(10, 7, 0)]
    steps  = rebuild_espn_game.build_steps(espn_game(team_id(module), plays, (7, 0)), module)
    scores = [s["json"]["events"][0]["competitions"][0]["competitors"][0]["score"]
              for s in steps if s["json"]["events"][0]["status"]["type"]["state"] == "in"]
    assert "6" in scores
    assert scores.index("6") < scores.index("7")
    assert replay("dolphins", steps).events == ["dolphins_touchdown", "dolphins_win"]


def test_espn_two_point_conversion_and_missed_extra_point(replay):
    module = load_script("dolphins")
    plays  = [play(0, 0, 0), play(5, 8, 0, "Rushing Touchdown"),
              play(30, 14, 0, "Passing Touchdown"), play(55, 17, 0, "Field Goal Good")]
    steps  = rebuild_espn_game.build_steps(espn_game(team_id(module), plays, (17, 0)), module)
    assert replay("dolphins", steps).events == [
        "dolphins_touchdown", "dolphins_touchdown", "dolphins_score", "dolphins_win"]


def test_espn_plays_are_put_in_time_order(replay):
    # ESPN's list can be out of order; in list order this field goal would
    # look like 3 -> 0 -> 3 and fire twice
    module = load_script("vols")
    plays  = [play(0, 0, 0), play(10, 3, 0, "Field Goal Good"), play(20, 3, 0), play(5, 0, 0)]
    steps  = rebuild_espn_game.build_steps(espn_game(team_id(module), plays, (3, 0)), module)
    assert replay("vols", steps).events == ["vols_score"]


def test_espn_league_comes_from_the_monitor():
    assert rebuild_espn_game.league_of(load_script("dolphins")) == "nfl"
    assert rebuild_espn_game.league_of(load_script("vols")) == "college-football"


def test_espn_replay_timing_matches_live(replay):
    # The live monitor spends STREAM_DELAY_SECONDS queuing each event before it
    # checks again, so the rebuild must not add that time on top. A 2-point try
    # 160 real seconds after a touchdown is inside the 180s conversion window,
    # live and in the replay.
    module = load_script("dolphins")
    plays  = [play(0, 0, 0), play(5, 6, 0, "Rushing Touchdown"),
              {**play(5, 8, 0), "wallclock": "2026-10-01T20:07:40Z"}, play(20, 8, 0)]
    steps  = rebuild_espn_game.build_steps(espn_game(team_id(module), plays, (8, 0)), module)
    assert replay("dolphins", steps).events == ["dolphins_touchdown", "dolphins_win"]


def test_nhl_goal_before_period_start(replay):
    # The play-by-play doesn't promise a period-start before the first goal
    module = load_script("rangers")
    plays  = goal(1, "01:00", 1, 0, 1)
    steps  = rebuild_nhl_game.build_steps(nhl_game(team_id(module), 1, 0, plays), module)
    assert replay("rangers", steps).events == ["rangers_goal"]
