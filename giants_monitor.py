#!/usr/bin/env python3
"""
Giants Monitor — Raspberry Pi Zero WH
Monitors the MLB API for Giants runs and writes events to the shared queue.
GPIO and audio are handled by controller.py.
Uses the MLB Stats API — no API key required.
"""

import time
import json
import os
import requests
from datetime import datetime, timezone

# ─── Configuration ────────────────────────────────────────────────────────────

GIANTS_TEAM_ID          = 137
POLL_INTERVAL           = 2         # Seconds between API calls during a live game
IDLE_INTERVAL           = 60        # Seconds between checks when no game is live
STREAM_DELAY_SECONDS    = 25        # Delay to sync with Fubo streaming delay
PRIORITY                = 3         # 1 = highest priority, 3 = lower priority
BASE_DIR                = os.path.dirname(os.path.abspath(__file__))
EVENT_FILE              = os.path.join(BASE_DIR, "goal_horn_events.json")
COMPLETED_GAMES_FILE    = os.path.join(BASE_DIR, "giants_completed_games.json")

MLB_SCHEDULE_URL        = "https://statsapi.mlb.com/api/v1/schedule?sportId=1&teamId={team_id}"
MLB_GAME_URL            = "https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"

# ─── Completed Games Persistence ─────────────────────────────────────────────

def load_completed_games() -> set:
    """Load completed game PKs from disk, pruning any older than 2 days."""
    if not os.path.exists(COMPLETED_GAMES_FILE):
        return set()
    try:
        with open(COMPLETED_GAMES_FILE, "r") as f:
            data = json.load(f)
        now = time.time()
        return {e["pk"] for e in data if now - e["timestamp"] < 172800}
    except Exception as e:
        print(f"[COMPLETED] Failed to load completed games: {e}")
        return set()


def save_completed_game(game_pk: int, completed_games: set):
    """Save a completed game PK to disk and add to in-memory set."""
    try:
        existing = []
        if os.path.exists(COMPLETED_GAMES_FILE):
            with open(COMPLETED_GAMES_FILE, "r") as f:
                existing = json.load(f)
        existing.append({"pk": game_pk, "timestamp": time.time()})
        with open(COMPLETED_GAMES_FILE, "w") as f:
            json.dump(existing, f)
        completed_games.add(game_pk)
    except Exception as e:
        print(f"[COMPLETED] Failed to save completed game: {e}")

# ─── Event Queue ──────────────────────────────────────────────────────────────

def queue_event(event_type: str):
    """Write an event to the shared event queue after the stream delay."""
    print(f"[QUEUE] Waiting {STREAM_DELAY_SECONDS}s before queuing: {event_type}")
    time.sleep(STREAM_DELAY_SECONDS)

    event = {
        "event":     event_type,
        "priority":  PRIORITY,
        "timestamp": time.time(),
    }

    try:
        events = []
        if os.path.exists(EVENT_FILE):
            with open(EVENT_FILE, "r") as f:
                events = json.load(f)

        events.append(event)

        with open(EVENT_FILE, "w") as f:
            json.dump(events, f)

        print(f"[QUEUE] Event queued: {event_type}")
    except Exception as e:
        print(f"[QUEUE] Failed to queue event: {e}")

# ─── MLB API Helpers ──────────────────────────────────────────────────────────

def get_todays_giants_game(skip_pks: set = None) -> dict | None:
    try:
        url = MLB_SCHEDULE_URL.format(team_id=GIANTS_TEAM_ID)
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        print(f"[API ERROR] Schedule fetch failed: {e}")
        return None

    for date in data.get("dates", []):
        for game in date.get("games", []):
            home_id = game.get("teams", {}).get("home", {}).get("team", {}).get("id")
            away_id = game.get("teams", {}).get("away", {}).get("team", {}).get("id")
            if GIANTS_TEAM_ID not in (home_id, away_id):
                continue
            game_pk = game["gamePk"]
            if skip_pks and game_pk in skip_pks:
                continue
            status = game.get("status", {}).get("abstractGameState", "")
            return {
                "game_pk": game_pk,
                "state":   status,
                "home":    game["teams"]["home"]["team"]["name"],
                "away":    game["teams"]["away"]["team"]["name"],
            }
    return None


def get_game_data(game_pk: int) -> dict | None:
    try:
        url = MLB_GAME_URL.format(game_pk=game_pk)
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        print(f"[API ERROR] Game fetch failed: {e}")
        return None

    game_state  = data.get("gameData", {}).get("status", {}).get("abstractGameState", "")
    linescore   = data.get("liveData", {}).get("linescore", {})
    teams       = linescore.get("teams", {})
    home_team   = data.get("gameData", {}).get("teams", {}).get("home", {})
    away_team   = data.get("gameData", {}).get("teams", {}).get("away", {})

    if home_team.get("id") == GIANTS_TEAM_ID:
        giants_runs   = teams.get("home", {}).get("runs", 0)
        opponent_runs = teams.get("away", {}).get("runs", 0)
        opponent_half = "Top"       # Opponent (away) bats in the top of the inning
    else:
        giants_runs   = teams.get("away", {}).get("runs", 0)
        opponent_runs = teams.get("home", {}).get("runs", 0)
        opponent_half = "Bottom"    # Opponent (home) bats in the bottom of the inning

    current_inning = linescore.get("currentInning", 0)
    inning_half    = linescore.get("inningHalf", "")    # "Top" or "Bottom"
    outs           = linescore.get("outs", 0)

    giants_won = ((
        current_inning >= 9 and
        outs == 3 and
        inning_half == opponent_half and
        giants_runs > opponent_runs
    ) or (  # In case of a walk-off win
        current_inning >= 9 and
        inning_half != opponent_half and
        giants_runs > opponent_runs and
        home_team.get("id") == GIANTS_TEAM_ID
    )) and (
        game_state != "Final"
    )

    all_plays       = data.get("liveData", {}).get("plays", {}).get("allPlays", [])
    last_play_index = len(all_plays) - 1
    last_play_is_hr = False

    if all_plays:
        last_play                = all_plays[-1]
        event_type               = all_plays[-1].get("result", {}).get("eventType", "")
        if len(all_plays) >= 2:
            two_plays_ago_event_type = all_plays[-2].get("result", {}).get("eventType", "")
            two_plays_ago_description = all_plays[-2].get("result", {}).get("description", "")
        else:
            two_plays_ago_event_type  = ""
            two_plays_ago_description = ""
        print(f"[DEBUG] Last play event type: {event_type}")
        print(f"[DEBUG] Last play description: {all_plays[-1].get('result', {}).get('description', '')}")
        print(f"[DEBUG] Two plays ago event type: {two_plays_ago_event_type}")
        print(f"[DEBUG] Two plays ago description: {two_plays_ago_description}")
        print(f"[DEBUG] Last play raw: {json.dumps(last_play, indent=2)[:500]}")
        last_play_is_hr = event_type == "home_run" or two_plays_ago_event_type == "home_run"

    return {
        "giants_runs":      giants_runs,
        "giants_won":       giants_won,
        "last_play_index":  last_play_index,
        "last_play_is_hr":  last_play_is_hr,
        "game_state":       game_state,
    }

# ─── Main Loop ────────────────────────────────────────────────────────────────

def main():
    print(f"[START] Giants monitor running...")

    last_run_count  = None
    last_play_index = None
    win_triggered   = False
    active_game_pk  = None
    completed_games = load_completed_games()
    print(f"[START] Loaded {len(completed_games)} completed game(s) from disk.")

    try:
        while True:
            now = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
            game = get_todays_giants_game(skip_pks=completed_games)

            if game is None:
                print(f"[{now}] No Giants game today. Checking again in {IDLE_INTERVAL}s.")
                last_run_count  = None
                last_play_index = None
                win_triggered   = False
                active_game_pk  = None
                time.sleep(IDLE_INTERVAL)
                continue

            game_pk = game["game_pk"]
            state   = game["state"]
            matchup = f"{game['away']} @ {game['home']}"

            if state == "Preview":
                print(f"[{now}] Game found ({matchup}) but not yet live. "
                      f"Checking again in {IDLE_INTERVAL}s.")
                last_run_count  = None
                last_play_index = None
                win_triggered   = False
                active_game_pk  = None
                time.sleep(IDLE_INTERVAL)
                continue

            if state in ("Live", "Final"):

                if game_pk != active_game_pk:
                    print(f"[{now}] New game detected: {matchup} (PK={game_pk})")
                    active_game_pk  = game_pk
                    last_run_count  = None
                    last_play_index = None
                    win_triggered   = False

                game_data = get_game_data(game_pk)

                if game_data is None:
                    print(f"[{now}] Could not retrieve game data. Retrying...")
                    time.sleep(POLL_INTERVAL)
                    continue

                current_runs    = game_data["giants_runs"]
                giants_won      = game_data["giants_won"]
                play_index      = game_data["last_play_index"]
                play_is_hr      = game_data["last_play_is_hr"]
                game_state      = game_data["game_state"]

                if last_run_count is None:
                    last_run_count  = current_runs
                    last_play_index = play_index
                    print(f"[{now}] Game live ({matchup}) | Giants runs: {current_runs} "
                          f"(baseline set)")

                elif current_runs > last_run_count:
                    new_runs        = current_runs - last_run_count
                    last_run_count  = current_runs
                    last_play_index = play_index

                    print(f"[{now}] GIANTS SCORED! (+{new_runs}) | Total: {current_runs} "
                          f"| Checking if it was a home run...")

                    if play_is_hr:
                        print(f"[{now}] Confirmed home run!")
                        queue_event("giants_home_run")
                    else:
                        print(f"[{now}] Confirmed non-home run.")
                        queue_event("giants_run")

                else:
                    print(f"[{now}] {matchup} | State={game_state} | "
                          f"Giants runs: {current_runs}")

                if giants_won and not win_triggered:
                    print(f"[{now}] GIANTS WIN!")
                    win_triggered = True
                    queue_event("giants_win")

                if game_state == "Final":
                    print(f"[{now}] Game over. Final Giants runs: {current_runs}. "
                          f"Resuming idle checks in {IDLE_INTERVAL}s.")
                    save_completed_game(game_pk, completed_games)
                    last_run_count  = None
                    last_play_index = None
                    win_triggered   = False
                    active_game_pk  = None
                    time.sleep(IDLE_INTERVAL)
                    continue

                time.sleep(POLL_INTERVAL)

    except KeyboardInterrupt:
        print("\n[STOP] Giants monitor stopped.")


if __name__ == "__main__":
    main()
