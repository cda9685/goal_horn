"""
Build replay steps shaped like real API responses, for scripting game scenarios.

Each function returns a list of steps (see harness.Replay), so a game is written
as a sum of polls:

    steps = (nhl.poll(GAME, "LIVE", us=0, them=0)
             + nhl.poll(GAME, "LIVE", us=1, them=0)
             + nhl.poll(GAME, "OFF",  us=1, them=0))

Only the fields the monitors read are filled in. Responses keep the real APIs'
key names and nesting so recorded games and scripted games look the same.
"""

# ─── NHL (api-web.nhle.com) ───────────────────────────────────────────────────

class NHL:
    """Builder for one NHL team. team is the abbreviation, e.g. "NYR"."""

    def __init__(self, team: str, opponent: str = "BOS", home: bool = True):
        self.team     = team
        self.opponent = opponent
        self.home     = home

    def _sides(self):
        return (self.team, self.opponent) if self.home else (self.opponent, self.team)

    def schedule(self, game_id: int, state: str) -> list:
        """schedule/now with one game. state: FUT, PRE, LIVE, CRIT, FINAL, OFF, PPD."""
        home, away = self._sides()
        game = {"id": game_id, "gameState": state,
                "homeTeam": {"abbrev": home}, "awayTeam": {"abbrev": away}}
        return [{"url": "schedule/now", "json": {"gameWeek": [{"games": [game]}]}}]

    def no_game(self) -> list:
        return [{"url": "schedule/now", "json": {"gameWeek": [{"games": []}]}}]

    def landing(self, game_id: int, us: int, them: int,
                period_type: str = "REG", shootout: list | None = None) -> list:
        """
        gamecenter/<id>/landing. shootout is a list of (team_abbrev, "goal"/"save")
        attempts, in order.
        """
        home_score, away_score = (us, them) if self.home else (them, us)
        home, away = self._sides()
        data = {
            "homeTeam":         {"abbrev": home, "score": home_score},
            "awayTeam":         {"abbrev": away, "score": away_score},
            "periodDescriptor": {"periodType": period_type},
            "summary":          {"shootout": [{"teamAbbrev": t, "result": r}
                                              for t, r in (shootout or [])]},
        }
        return [{"url": f"gamecenter/{game_id}/landing", "json": data}]

    def poll(self, game_id: int, state: str, us: int = 0, them: int = 0,
             period_type: str = "REG", shootout: list | None = None) -> list:
        """One pass of the monitor loop: schedule, then the game if it's under way."""
        steps = self.schedule(game_id, state)
        if state in ("LIVE", "CRIT", "FINAL", "OFF"):
            steps += self.landing(game_id, us, them, period_type, shootout)
        return steps

# ─── MLB (statsapi.mlb.com) ───────────────────────────────────────────────────

class MLB:
    """Builder for one MLB team. team is the numeric team ID, e.g. 147."""

    def __init__(self, team: int, opponent: int = 111, home: bool = True):
        self.team     = team
        self.opponent = opponent
        self.home     = home

    def _sides(self):
        return (self.team, self.opponent) if self.home else (self.opponent, self.team)

    def schedule(self, *games: tuple) -> list:
        """schedule?teamId=... listing (game_pk, abstractGameState) pairs in order."""
        home, away = self._sides()
        return [{"url": "schedule?sportId=1", "json": {"dates": [{"games": [
            {"gamePk": pk,
             "status": {"abstractGameState": state},
             "teams": {"home": {"team": {"id": home, "name": f"Team {home}"}},
                       "away": {"team": {"id": away, "name": f"Team {away}"}}}}
            for pk, state in games]}]}}]

    def no_game(self) -> list:
        return [{"url": "schedule?sportId=1", "json": {"dates": []}}]

    def feed(self, game_pk: int, state: str, us: int, them: int, inning: int = 1,
             half: str = "Top", outs: int = 0, plays: list | None = None) -> list:
        """
        game/<pk>/feed/live. plays is the list of each play's result.eventType so
        far, e.g. ["strikeout", "single", "home_run"].
        """
        home, away = self._sides()
        home_runs, away_runs = (us, them) if self.home else (them, us)
        data = {
            "gameData": {
                "status": {"abstractGameState": state},
                "teams":  {"home": {"id": home}, "away": {"id": away}},
            },
            "liveData": {
                "linescore": {
                    "currentInning": inning,
                    "inningHalf":    half,
                    "outs":          outs,
                    "teams": {"home": {"runs": home_runs}, "away": {"runs": away_runs}},
                },
                "plays": {"allPlays": [{"result": {"eventType": p, "description": p}}
                                       for p in (plays or [])]},
            },
        }
        return [{"url": f"game/{game_pk}/feed/live", "json": data}]

    def poll(self, game_pk: int, state: str, us: int = 0, them: int = 0,
             schedule: list | None = None, **feed) -> list:
        """
        One pass of the monitor loop. schedule overrides the (pk, state) list,
        e.g. for doubleheaders.
        """
        steps = self.schedule(*(schedule or [(game_pk, state)]))
        if state in ("Live", "Final"):
            steps += self.feed(game_pk, state, us, them, **feed)
        return steps

# ─── ESPN (site.api.espn.com) ─────────────────────────────────────────────────

# status.type.name for each state ESPN reports
ESPN_STATUS = {
    "pre":       ("pre",  "STATUS_SCHEDULED"),
    "in":        ("in",   "STATUS_IN_PROGRESS"),
    "halftime":  ("in",   "STATUS_HALFTIME"),
    "post":      ("post", "STATUS_FINAL"),
    "postponed": ("post", "STATUS_POSTPONED"),
    "canceled":  ("post", "STATUS_CANCELED"),
}


class ESPN:
    """Builder for one ESPN football team. team is the ESPN team ID, e.g. "2633"."""

    def __init__(self, team: str, opponent: str = "99", home: bool = True):
        self.team     = str(team)
        self.opponent = str(opponent)
        self.home     = home

    def scoreboard(self, game_id: str, status: str, us: int = 0, them: int = 0,
                   period: int = 1) -> list:
        """scoreboard with one game. status is a key of ESPN_STATUS."""
        state, name = ESPN_STATUS[status]

        def competitor(team_id, home_away, score):
            return {"id": team_id, "homeAway": home_away, "score": str(score),
                    "team": {"id": team_id, "abbreviation": f"T{team_id}"}}

        competitors = [
            competitor(self.team,     "home" if self.home else "away", us),
            competitor(self.opponent, "away" if self.home else "home", them),
        ]
        event = {"id": str(game_id),
                 "status": {"period": period, "type": {"state": state, "name": name}},
                 "competitions": [{"competitors": competitors}]}
        return [{"url": "scoreboard", "json": {"events": [event]}}]

    def no_game(self) -> list:
        return [{"url": "scoreboard", "json": {"events": []}}]

    # The ESPN monitors make one request per loop, so a poll is just the scoreboard
    poll = scoreboard

# ─── Any API ──────────────────────────────────────────────────────────────────

def api_error(url: str, message: str = "Connection reset") -> list:
    """The next request to url fails, as if the network dropped."""
    return [{"url": url, "error": message}]
