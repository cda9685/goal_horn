#!/usr/bin/env python3
"""
Rangers Monitor — Raspberry Pi Zero WH
Monitors the NHL API for Rangers goals and writes events to the shared queue.
GPIO and audio are handled by controller.py.
Uses the NHL API (api-web.nhle.com) — no API key required.
"""

import time
import json
import os
import requests
from datetime import datetime, timezone

# ─── Configuration ────────────────────────────────────────────────────────────

RANGERS_TEAM_ID         = "NYR"
POLL_INTERVAL           = 5         # Seconds between API calls during a live game
IDLE_INTERVAL           = 60        # Seconds between checks when no game is live
STREAM_DELAY_SECONDS    = 25        # Delay to sync with Fubo streaming delay
PRIORITY                = 2         # 1 = highest priority, 2 = lower priority
BASE_DIR                = os.path.dirname(os.path.abspath(__file__))
EVENT_FILE              = os.path.join(BASE_DIR, "goal_horn_events.json")

NHL_SCHEDULE_URL        = "https://api-web.nhle.com/v1/schedule/now"
NHL_GAME_URL            = "https://api-web.nhle.com/v1/gamecenter/{game_id}/landing"

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
        # Read existing events
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

# ─── NHL API Helpers ──────────────────────────────────────────────────────────

def get_todays_rangers_game() -> dict | None:
    try:
        response = requests.get(NHL_SCHEDULE_URL, timeout=10)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        print(f"[API ERROR] Schedule fetch failed: {e}")
        return None

    for day in data.get("gameWeek", []):
        for game in day.get("games", []):
            home = game.get("homeTeam", {}).get("abbrev", "")
            away = game.get("awayTeam", {}).get("abbrev", "")
            if RANGERS_TEAM_ID in (home, away):
                return {
                    "game_id": game["id"],
                    "state":   game.get("gameState", ""),
                    "home":    home,
                    "away":    away,
                }
    return None


def get_game_data(game_id: int) -> dict | None:
    try:
        url = NHL_GAME_URL.format(game_id=game_id)
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        print(f"[API ERROR] Game fetch failed: {e}")
        return None

    home_team   = data.get("homeTeam", {})
    away_team   = data.get("awayTeam", {})
    period_desc = data.get("periodDescriptor", {})
    period_type = period_desc.get("periodType", "REG")

    if home_team.get("abbrev") == RANGERS_TEAM_ID:
        rangers_team = home_team
    elif away_team.get("abbrev") == RANGERS_TEAM_ID:
        rangers_team = away_team
    else:
        return None

    score = rangers_team.get("score", 0)

    so_goals = 0
    if period_type == "SO":
        shootout_data = data.get("summary", {}).get("shootout", [])
        for attempt in shootout_data:
            if not isinstance(attempt, dict):
                continue
            if (attempt.get("teamAbbrev") == RANGERS_TEAM_ID and
                    attempt.get("result") == "goal"):
                so_goals += 1

    return {
        "score":       score,
        "period_type": period_type,
        "so_goals":    so_goals,
    }

# ─── Main Loop ────────────────────────────────────────────────────────────────

def main():
    print(f"[START] Rangers monitor running...")

    last_goal_count = None
    last_so_goals   = None
    active_game_id  = None

    try:
        while True:
            now = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
            game = get_todays_rangers_game()

            if game is None:
                print(f"[{now}] No Rangers game today. Checking again in {IDLE_INTERVAL}s.")
                last_goal_count = None
                last_so_goals   = None
                active_game_id  = None
                time.sleep(IDLE_INTERVAL)
                continue

            game_id = game["game_id"]
            state   = game["state"]
            matchup = f"{game['away']} @ {game['home']}"

            if state in ("FUT", "PRE"):
                print(f"[{now}] Game found ({matchup}) but not yet live (state={state}). "
                      f"Checking again in {IDLE_INTERVAL}s.")
                last_goal_count = None
                last_so_goals   = None
                active_game_id  = None
                time.sleep(IDLE_INTERVAL)
                continue

            if state in ("LIVE", "CRIT", "FINAL", "OFF"):

                if game_id != active_game_id:
                    print(f"[{now}] New game detected: {matchup} (ID={game_id})")
                    active_game_id  = game_id
                    last_goal_count = None
                    last_so_goals   = None

                game_data = get_game_data(game_id)

                if game_data is None:
                    print(f"[{now}] Could not retrieve game data. Retrying...")
                    time.sleep(POLL_INTERVAL)
                    continue

                current_goals = game_data["score"]
                period_type   = game_data["period_type"]
                so_goals      = game_data["so_goals"]

                # ── Shootout ───────────────────────────────────────────────────
                if period_type == "SO":
                    if last_so_goals is None:
                        last_so_goals = so_goals
                        print(f"[{now}] Shootout started! Rangers SO goals: {so_goals} "
                              f"(baseline set)")
                    elif so_goals > last_so_goals:
                        new_so_goals = so_goals - last_so_goals
                        print(f"[{now}] RANGERS SHOOTOUT GOAL! (+{new_so_goals})")
                        for _ in range(new_so_goals):
                            queue_event("rangers_shootout")
                            time.sleep(1)
                        last_so_goals = so_goals
                    else:
                        print(f"[{now}] {matchup} | SO | Rangers SO goals: {so_goals}")

                # ── Regular / OT ───────────────────────────────────────────────
                else:
                    if last_goal_count is None:
                        last_goal_count = current_goals
                        print(f"[{now}] Game live ({matchup}) | Period: {period_type} | "
                              f"Rangers goals: {current_goals} (baseline set)")

                    elif current_goals > last_goal_count:
                        new_goals = current_goals - last_goal_count
                        print(f"[{now}] RANGERS SCORED! (+{new_goals}) | Total: {current_goals}")
                        for _ in range(new_goals):
                            queue_event("rangers_goal")
                            time.sleep(1)
                        last_goal_count = current_goals

                    else:
                        print(f"[{now}] {matchup} | {period_type} | State={state} | "
                              f"Rangers goals: {current_goals}")

                if state in ("FINAL", "OFF"):
                    print(f"[{now}] Game over. Final Rangers goals: {current_goals}. "
                          f"Resuming idle checks in {IDLE_INTERVAL}s.")
                    last_goal_count = None
                    last_so_goals   = None
                    active_game_id  = None
                    time.sleep(IDLE_INTERVAL)
                    continue

                time.sleep(POLL_INTERVAL)

    except KeyboardInterrupt:
        print("\n[STOP] Rangers monitor stopped.")


if __name__ == "__main__":
    main()
