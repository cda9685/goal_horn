"""
A team's upcoming games, from the same API its monitor uses. Used by dvr.py to
pick games to record.
"""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import requests

from harness import load_script, monitors_using, team_id

NHL_SCHEDULE  = "https://api-web.nhle.com/v1/club-schedule-season/{team}/now"
MLB_SCHEDULE  = ("https://statsapi.mlb.com/api/v1/schedule?sportId=1&teamId={team}"
                 "&startDate={start}&endDate={end}")
ESPN_SCHEDULE = "https://site.api.espn.com/apis/site/v2/sports/football/{league}/teams/{team}/schedule"


@dataclass
class Game:
    id:    str          # The API's game ID (what record_game.py --game takes)
    start: datetime     # Start time, in UTC
    away:  str
    home:  str
    at_home: bool       # Whether the tracked team is the home side
    over:  bool = False

    @property
    def matchup(self) -> str:
        return f"{self.away} @ {self.home}"

    @property
    def opponent(self) -> str:
        return self.away if self.at_home else self.home


def parse_time(text: str) -> datetime:
    """An API timestamp ("2026-11-14T02:00:00Z" or "2026-11-15T18:00Z") in UTC."""
    text = text.replace("Z", "+00:00")
    if re.search(r"T\d\d:\d\d\+", text):
        text = text.replace("+", ":00+", 1)
    return datetime.fromisoformat(text).astimezone(timezone.utc)


def nhl_games(data: dict, tid) -> list:
    return [Game(str(g["id"]), parse_time(g["startTimeUTC"]),
                 g["awayTeam"]["abbrev"], g["homeTeam"]["abbrev"],
                 g["homeTeam"]["abbrev"] == tid, g.get("gameState") in ("OFF", "FINAL"))
            for g in data.get("games", [])]


def mlb_games(data: dict, tid) -> list:
    return [Game(str(g["gamePk"]), parse_time(g["gameDate"]),
                 g["teams"]["away"]["team"]["name"], g["teams"]["home"]["team"]["name"],
                 g["teams"]["home"]["team"]["id"] == tid,
                 g.get("status", {}).get("abstractGameState") == "Final")
            for date in data.get("dates", []) for g in date.get("games", [])]


def espn_games(data: dict, tid) -> list:
    games = []
    for e in data.get("events", []):
        comp  = e["competitions"][0]
        sides = {c["homeAway"]: c for c in comp["competitors"]}
        name  = {side: c["team"]["abbreviation"] for side, c in sides.items()}
        home_id = str(sides.get("home", {}).get("team", {}).get("id", sides.get("home", {}).get("id")))
        games.append(Game(str(e["id"]), parse_time(e["date"]), name.get("away", "?"),
                          name.get("home", "?"), home_id == str(tid),
                          comp["status"]["type"].get("completed", False)))
    return games


def upcoming_games(team: str, days: int = 30, now: datetime | None = None, get=requests.get) -> list:
    """The team's games that haven't finished and start within `days`, soonest first."""
    now    = now or datetime.now(timezone.utc)
    module = load_script(team)
    tid    = team_id(module)
    if team in monitors_using("api-web.nhle.com"):
        games = nhl_games(get(NHL_SCHEDULE.format(team=tid), timeout=15).json(), tid)
    elif team in monitors_using("statsapi.mlb.com"):
        url = MLB_SCHEDULE.format(team=tid, start=now.date(), end=(now + timedelta(days=days)).date())
        games = mlb_games(get(url, timeout=15).json(), tid)
    elif team in monitors_using("site.api.espn.com"):
        league = re.search(r"sports/football/([a-z-]+)/scoreboard", module.ESPN_SCOREBOARD_URL).group(1)
        games = espn_games(get(ESPN_SCHEDULE.format(league=league, team=tid), timeout=15).json(), tid)
    else:
        raise ValueError(f"No schedule for {team}'s API")
    # Games already under way are kept, so one can still be recorded
    window = (now - timedelta(hours=6), now + timedelta(days=days))
    return sorted((g for g in games if not g.over and window[0] <= g.start <= window[1]),
                  key=lambda g: g.start)
