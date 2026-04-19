#!/usr/bin/env python3
"""
Yankees Monitor — Raspberry Pi Zero WH
Monitors the MLB API for Yankees runs and writes events to the shared queue.
GPIO and audio are handled by controller.py.
Uses the MLB Stats API — no API key required.
"""

import time
import json
import os
import requests
from datetime import datetime, timezone

# ─── Configuration ────────────────────────────────────────────────────────────

YANKEES_TEAM_ID         = 147
POLL_INTERVAL           = 2         # Seconds between API calls during a live game
IDLE_INTERVAL           = 60        # Seconds between checks when no game is live
STREAM_DELAY_SECONDS    = 25        # Delay to sync with Fubo streaming delay
PRIORITY                = 1         # 1 = highest priority, 2 = lower priority
BASE_DIR                = os.path.dirname(os.path.abspath(__file__))
EVENT_FILE              = os.path.join(BASE_DIR, "goal_horn_events.json")

MLB_SCHEDULE_URL        = "https://statsapi.mlb.com/api/v1/schedule?sportId=1&teamId={team_id}"
MLB_GAME_URL            = "https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"

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

def get_todays_yankees_game() -> dict | None:
    try:
        url = MLB_SCHEDULE_URL.format(team_id=YANKEES_TEAM_ID)
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
            if YANKEES_TEAM_ID in (home_id, away_id):
                status = game.get("status", {}).get("abstractGameState", "")
                return {
                    "game_pk": game["gamePk"],
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

    if home_team.get("id") == YANKEES_TEAM_ID:
        yankees_runs  = teams.get("home", {}).get("runs", 0)
        opponent_runs = teams.get("away", {}).get("runs", 0)
        opponent_half = "Top"   # Opponent (away) bats in the top of the inning
    else:
        yankees_runs  = teams.get("away", {}).get("runs", 0)
        opponent_runs = teams.get("home", {}).get("runs", 0)
        opponent_half = "Bottom"  # Opponent (home) bats in the bottom of the inning

    current_inning = linescore.get("currentInning", 0)
    inning_half    = linescore.get("inningHalf", "") # "Top" or "Bottom"
    outs           = linescore.get("outs", 0)

    yankees_won = ((
        current_inning >= 9 and
        outs == 3 and
        inning_half == opponent_half and
        yankees_runs > opponent_runs
    ) or (  # In case of a walk-off win
        current_inning >= 9 and
        inning_half != opponent_half and
        yankees_runs > opponent_runs and
        home_team.get("id") == YANKEES_TEAM_ID
    )) and (
        game_state != "Final"
    )

    all_plays       = data.get("liveData", {}).get("plays", {}).get("allPlays", [])
    last_play_index = len(all_plays) - 1
    last_play_is_hr = False

    if all_plays:
        last_play                   = all_plays[-1]
        event_type                  = all_plays[-1].get("result", {}).get("eventType", "")
        two_plays_ago_event_type    = all_plays[-2].get("result", {}).get("eventType", "")
        print(f"[DEBUG] Last play event type: {event_type}")
        print(f"[DEBUG] Last play description: {all_plays[-1].get('result', {}).get('description', '')}")
        print(f"[DEBUG] Two plays ago event type: {two_plays_ago_event_type}")
        print(f"[DEBUG] Two plays ago description: {all_plays[-2].get('result', {}).get('description', '')}")
        print(f"[DEBUG] Last play raw: {json.dumps(last_play, indent=2)[:500]}")
        last_play_is_hr = event_type == "home_run" or two_plays_ago_event_type == "home_run"

    return {
        "yankees_runs":     yankees_runs,
        "yankees_won":      yankees_won,
        "last_play_index":  last_play_index,
        "last_play_is_hr":  last_play_is_hr,
        "game_state":       game_state,
    }

# ─── Main Loop ────────────────────────────────────────────────────────────────

def main():
    print(f"[START] Yankees monitor running...")

    last_run_count  = None
    last_play_index = None
    win_triggered   = False
    active_game_pk  = None

    try:
        while True:
            now = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
            game = get_todays_yankees_game()

            if game is None:
                print(f"[{now}] No Yankees game today. Checking again in {IDLE_INTERVAL}s.")
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

                current_runs    = game_data["yankees_runs"]
                yankees_won     = game_data["yankees_won"]
                play_index      = game_data["last_play_index"]
                play_is_hr      = game_data["last_play_is_hr"]
                game_state      = game_data["game_state"]

                if last_run_count is None:
                    last_run_count  = current_runs
                    last_play_index = play_index
                    print(f"[{now}] Game live ({matchup}) | Yankees runs: {current_runs} "
                          f"(baseline set)")

                elif current_runs > last_run_count:
                    new_runs       = current_runs - last_run_count
                    last_run_count = current_runs
                    last_play_index = play_index

                    print(f"[{now}] YANKEES SCORED! (+{new_runs}) | Total: {current_runs} "
                          f"| Checking if it was a home run...")

                    if play_is_hr:
                        print(f"[{now}] Confirmed home run!")
                        queue_event("yankees_home_run")
                    else:
                        print(f"[{now}] Confirmed non-home run.")
                        queue_event("yankees_run")

                else:
                    print(f"[{now}] {matchup} | State={game_state} | "
                          f"Yankees runs: {current_runs}")

                if yankees_won and not win_triggered:
                    print(f"[{now}] YANKEES WIN!")
                    win_triggered = True
                    queue_event("yankees_win")

                if game_state == "Final":
                    print(f"[{now}] Game over. Final Yankees runs: {current_runs}. "
                          f"Resuming idle checks in {IDLE_INTERVAL}s.")
                    last_run_count  = None
                    last_play_index = None
                    win_triggered   = False
                    active_game_pk  = None
                    time.sleep(IDLE_INTERVAL)
                    continue

                time.sleep(POLL_INTERVAL)

    except KeyboardInterrupt:
        print("\n[STOP] Yankees monitor stopped.")


if __name__ == "__main__":
    main()
