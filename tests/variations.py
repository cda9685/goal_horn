"""
Variations: add the things a rebuilt game can't show to any recorded game.

A recorded game only has what happened that day. These take its replay
steps and add an overturned score, a one-poll glitch, a blank score or a
failed request, so every real game also tests the rare cases. The monitor
should fire the same events as the original game (one extra for an
overturned score that's then scored again).
"""

import copy

from harness import monitors_using

VARIATIONS = ["glitch", "blank_score", "request_error", "game_data_error", "overturn"]

# URL fragments: the first request of each poll, and the one with the score
FIRST_REQUEST = {"nhl": "schedule/now", "mlb": "schedule?sportId=1", "espn": "scoreboard"}
SCORE_REQUEST = {"nhl": "/landing", "mlb": "/feed/live", "espn": "scoreboard"}


def api_of(team: str) -> str:
    if team in monitors_using("api-web.nhle.com"):
        return "nhl"
    if team in monitors_using("statsapi.mlb.com"):
        return "mlb"
    if team in monitors_using("site.api.espn.com/apis/site/v2/sports/football/"):
        return "espn"
    raise ValueError(f"No variations for {team}'s API")


def applies(variation: str, api: str) -> bool:
    # ESPN has no separate game-data request to fail
    return not (variation == "game_data_error" and api == "espn")


def group_polls(steps: list, api: str) -> list:
    """Split replay steps into polls: one list of steps per pass of the monitor's loop."""
    polls = []
    for step in steps:
        if FIRST_REQUEST[api] in step["url"] or not polls:
            polls.append([])
        polls[-1].append(step)
    return polls


def flatten(polls: list) -> list:
    return [step for poll in polls for step in poll]

# ─── Reading and Changing the Team's Score ────────────────────────────────────

def _score_step(poll: list, api: str) -> int | None:
    for i, step in enumerate(poll):
        if SCORE_REQUEST[api] in step["url"] and isinstance(step.get("json"), dict):
            return i
    return None


def _team_entry(data: dict, api: str, tid):
    """(container, key) holding the team's score in a response, or None."""
    if api == "nhl":
        for side in ("homeTeam", "awayTeam"):
            if data.get(side, {}).get("abbrev") == tid:
                return data[side], "score"
    elif api == "mlb":
        teams = data.get("gameData", {}).get("teams", {})
        side  = "home" if teams.get("home", {}).get("id") == tid else "away"
        return data["liveData"]["linescore"]["teams"][side], "runs"
    else:
        for event in data.get("events", []):
            for c in event.get("competitions", [{}])[0].get("competitors", []):
                if str(c.get("team", {}).get("id", c.get("id"))) == str(tid):
                    return c, "score"
    return None


def score(poll: list, api: str, tid):
    """The team's score in a poll, or None if the poll has no score."""
    i = _score_step(poll, api)
    entry = _team_entry(poll[i]["json"], api, tid) if i is not None else None
    if entry is None:
        return None
    value = entry[0].get(entry[1])
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def with_score(poll: list, api: str, tid, value) -> list:
    """A copy of the poll with the team's score set to value (any type)."""
    poll = copy.deepcopy(poll)
    container, key = _team_entry(poll[_score_step(poll, api)]["json"], api, tid)
    container[key] = str(value) if api == "espn" and isinstance(value, int) else value
    return poll

# ─── Where to Add a Variation ─────────────────────────────────────────────────

def scoring_polls(polls: list, api: str, tid) -> list:
    """Indexes of the polls where the team's score goes up."""
    found, last = [], None
    for i, poll in enumerate(polls):
        s = score(poll, api, tid)
        if s is None:
            continue
        if last is not None and s > last:
            found.append(i)
        last = s
    return found


def steady_poll(polls: list, api: str, tid) -> int | None:
    """The first poll after the team has scored where its score holds for the next poll too."""
    scored = scoring_polls(polls, api, tid)
    if not scored:
        return None
    for j in range(scored[0], len(polls) - 1):
        s = score(polls[j], api, tid)
        if s and s == score(polls[j + 1], api, tid):
            return j
    return None


def vary(polls: list, variation: str, api: str, tid, at: int | None = None) -> list | None:
    """
    The polls with one variation added, or None if the game has nowhere to add it.
    `at` picks the scoring poll to overturn (default: the last one).
    """
    scored = scoring_polls(polls, api, tid)
    if not scored:
        return None
    first = scored[0]

    if variation in ("glitch", "blank_score"):
        j = steady_poll(polls, api, tid)
        if j is None:
            return None
        s = score(polls[j], api, tid)
        bad = s - 1 if variation == "glitch" else ("" if api == "espn" else None)
        return polls[:j + 1] + [with_score(polls[j], api, tid, bad)] + polls[j + 1:]

    if variation == "request_error":
        # The first request of the poll where the team first scores fails just before it
        error = [{"url": polls[first][0]["url"], "error": "Connection reset"}]
        return polls[:first] + [error] + polls[first:]

    if variation == "game_data_error":
        i = _score_step(polls[first], api)
        error = polls[first][:i] + [{"url": polls[first][i]["url"], "error": "Connection reset"}]
        return polls[:first] + [error] + polls[first:]

    if variation == "overturn":
        # The score shows for 3 polls, comes off for 3 (overturned), then
        # comes back (scored again) and the game carries on
        i = scored[-1] if at is None else at
        before = max(score(p, api, tid) for p in polls[:i] if score(p, api, tid) is not None)
        taken_off = with_score(polls[i], api, tid, before)
        return (polls[:i + 1] + [copy.deepcopy(polls[i])] * 2 + [taken_off] * 3
                + [copy.deepcopy(polls[i])] + polls[i + 1:])

    raise ValueError(f"Unknown variation {variation!r}")
