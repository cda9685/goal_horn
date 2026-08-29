#!/usr/bin/env python3
"""
Dolphins Monitor — Raspberry Pi Zero WH
Monitors the ESPN API for Dolphins scores and writes events to the shared queue.
GPIO and audio are handled by controller.py.
Uses the ESPN API — no API key required.
"""

import time
import json
import os
import requests
from datetime import datetime, timezone

# ─── Configuration ────────────────────────────────────────────────────────────

DOLPHINS_TEAM_ID        = "15"      # ESPN team ID for Miami Dolphins
POLL_INTERVAL           = 10        # Seconds between API calls during a live game
IDLE_INTERVAL           = 60        # Seconds between checks when no game is live
STREAM_DELAY_SECONDS    = 25        # Delay to sync with Fubo streaming delay
PRIORITY                = 4         # 1 = highest priority
MONITOR_NAME            = "dolphins"
BASE_DIR                = os.path.dirname(os.path.abspath(__file__))
EVENT_FILE              = os.path.join(BASE_DIR, "goal_horn_events.json")
COMPLETED_GAMES_FILE    = os.path.join(BASE_DIR, "dolphins_completed_games.json")
CONFIG_FILE             = os.path.join(BASE_DIR, "monitor_config.json")

ESPN_SCOREBOARD_URL     = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
ESPN_GAME_URL           = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary?event={game_id}"

# Scoring play types to skip — these follow TDs and shouldn't trigger events
SKIP_PLAY_TYPES         = {"Extra Point", "Two-Point Conversion", "Two Point Conversion"}

# ─── Monitor Config ───────────────────────────────────────────────────────────

def is_enabled() -> bool:
    """Check if this monitor is enabled in monitor_config.json."""
    try:
        with open(CONFIG_FILE, "r") as f:
            config = json.load(f)
        return config.get(MONITOR_NAME, True)
    except Exception:
        return True     # Default to enabled if config can't be read

# ─── Completed Games Persistence ─────────────────────────────────────────────

def load_completed_games() -> set:
    """Load completed game IDs from disk, pruning any older than 2 days."""
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


def save_completed_game(game_id: str, completed_games: set):
    """Save a completed game ID to disk and add to in-memory set."""
    try:
        existing = []
        if os.path.exists(COMPLETED_GAMES_FILE):
            with open(COMPLETED_GAMES_FILE, "r") as f:
                existing = json.load(f)
        existing.append({"pk": game_id, "timestamp": time.time()})
        with open(COMPLETED_GAMES_FILE, "w") as f:
            json.dump(existing, f)
        completed_games.add(game_id)
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

# ─── ESPN API Helpers ─────────────────────────────────────────────────────────

def get_todays_dolphins_game(skip_ids: set = None) -> dict | None:
    """Fetch today's NFL scoreboard and return the Dolphins game if found."""
    try:
        response = requests.get(ESPN_SCOREBOARD_URL, timeout=5)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        print(f"[API ERROR] Scoreboard fetch failed: {e}")
        return None

    for event in data.get("events", []):
        game_id = event.get("id", "")
        if skip_ids and game_id in skip_ids:
            continue

        competition = event.get("competitions", [{}])[0]
        competitors = competition.get("competitors", [])
        team_ids    = [c.get("team", {}).get("id", "") for c in competitors]

        if DOLPHINS_TEAM_ID not in team_ids:
            continue

        status      = event.get("status", {})
        state       = status.get("type", {}).get("state", "")   # pre, in, post
        status_name = status.get("type", {}).get("name", "")

        home = next((c for c in competitors if c.get("homeAway") == "home"), {})
        away = next((c for c in competitors if c.get("homeAway") == "away"), {})

        return {
            "game_id":     game_id,
            "state":       state,
            "status_name": status_name,
            "home":        home.get("team", {}).get("displayName", ""),
            "away":        away.get("team", {}).get("displayName", ""),
        }

    return None


def get_game_data(game_id: str) -> dict | None:
    """Fetch game summary and return Dolphins score, win status, and scoring plays."""
    try:
        url = ESPN_GAME_URL.format(game_id=game_id)
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        print(f"[API ERROR] Game fetch failed: {e}")
        return None

    # ── Scores ────────────────────────────────────────────────────────────────
    competitors = data.get("header", {}).get("competitions", [{}])[0].get("competitors", [])
    dolphins_score  = 0
    opponent_score  = 0
    dolphins_home   = False

    for comp in competitors:
        team_id = comp.get("team", {}).get("id", "")
        score   = int(comp.get("score", 0) or 0)
        if team_id == DOLPHINS_TEAM_ID:
            dolphins_score = score
            dolphins_home  = comp.get("homeAway", "") == "home"
        else:
            opponent_score = score

    # ── Game status ───────────────────────────────────────────────────────────
    status      = data.get("header", {}).get("competitions", [{}])[0].get("status", {})
    status_name = status.get("type", {}).get("name", "")
    dolphins_won = status_name == "STATUS_FINAL" and dolphins_score > opponent_score

    # ── Scoring plays for Dolphins ────────────────────────────────────────────
    # Filter out PATs and 2-pt conversions — only primary scoring plays
    scoring_plays = []
    for play in data.get("scoringPlays", []):
        play_team = play.get("team", {}).get("id", "")
        play_type = play.get("type", {}).get("text", "")
        if play_team == DOLPHINS_TEAM_ID and play_type not in SKIP_PLAY_TYPES:
            scoring_plays.append({
                "id":   play.get("id", ""),
                "type": play_type,
            })

    return {
        "dolphins_score":  dolphins_score,
        "dolphins_won":    dolphins_won,
        "status_name":     status_name,
        "scoring_plays":   scoring_plays,
    }

# ─── Main Loop ────────────────────────────────────────────────────────────────

def main():
    print(f"[START] Dolphins monitor running...")

    last_scoring_play_ids   = None
    win_triggered           = False
    active_game_id          = None
    completed_games         = load_completed_games()
    print(f"[START] Loaded {len(completed_games)} completed game(s) from disk.")

    try:
        while True:
            now = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")

            if not is_enabled():
                print(f"[{now}] Dolphins monitor is disabled. Checking again in {IDLE_INTERVAL}s.")
                time.sleep(IDLE_INTERVAL)
                continue

            game = get_todays_dolphins_game(skip_ids=completed_games)

            if game is None:
                print(f"[{now}] No Dolphins game today. Checking again in {IDLE_INTERVAL}s.")
                last_scoring_play_ids   = None
                win_triggered           = False
                active_game_id          = None
                time.sleep(IDLE_INTERVAL)
                continue

            game_id     = game["game_id"]
            state       = game["state"]
            status_name = game["status_name"]
            matchup     = f"{game['away']} @ {game['home']}"

            if state == "pre":
                print(f"[{now}] Game found ({matchup}) but not yet live. "
                      f"Checking again in {IDLE_INTERVAL}s.")
                last_scoring_play_ids   = None
                win_triggered           = False
                active_game_id          = None
                time.sleep(IDLE_INTERVAL)
                continue

            if state in ("in", "post"):

                if game_id != active_game_id:
                    print(f"[{now}] New game detected: {matchup} (ID={game_id})")
                    active_game_id          = game_id
                    last_scoring_play_ids   = None
                    win_triggered           = False

                game_data = get_game_data(game_id)

                if game_data is None:
                    print(f"[{now}] Could not retrieve game data. Retrying...")
                    time.sleep(POLL_INTERVAL)
                    continue

                current_score   = game_data["dolphins_score"]
                dolphins_won    = game_data["dolphins_won"]
                scoring_plays   = game_data["scoring_plays"]
                status_name     = game_data["status_name"]
                current_ids     = {p["id"] for p in scoring_plays}

                # ── Baseline on first poll ─────────────────────────────────────
                if last_scoring_play_ids is None:
                    last_scoring_play_ids = current_ids
                    print(f"[{now}] Game live ({matchup}) | Dolphins score: {current_score} "
                          f"(baseline set, {len(current_ids)} scoring play(s))")

                # ── New scoring plays detected ─────────────────────────────────
                elif current_ids != last_scoring_play_ids:
                    new_play_ids = current_ids - last_scoring_play_ids
                    last_scoring_play_ids = current_ids

                    for play in scoring_plays:
                        if play["id"] not in new_play_ids:
                            continue
                        play_type = play["type"]
                        print(f"[{now}] DOLPHINS SCORED! Play type: {play_type} | "
                              f"Score: {current_score}")

                        if "Touchdown" in play_type:
                            queue_event("dolphins_td")
                        elif "Field Goal" in play_type:
                            queue_event("dolphins_fg")
                        elif "Safety" in play_type:
                            queue_event("dolphins_safety")

                else:
                    print(f"[{now}] {matchup} | {status_name} | "
                          f"Dolphins score: {current_score}")

                # ── Win detection ──────────────────────────────────────────────
                if dolphins_won and not win_triggered:
                    print(f"[{now}] DOLPHINS WIN!")
                    win_triggered = True
                    queue_event("dolphins_win")

                # ── Game over ──────────────────────────────────────────────────
                if status_name == "STATUS_FINAL":
                    print(f"[{now}] Game over. Final Dolphins score: {current_score}. "
                          f"Resuming idle checks in {IDLE_INTERVAL}s.")
                    save_completed_game(game_id, completed_games)
                    last_scoring_play_ids   = None
                    win_triggered           = False
                    active_game_id          = None
                    time.sleep(IDLE_INTERVAL)
                    continue

                time.sleep(POLL_INTERVAL)

    except KeyboardInterrupt:
        print("\n[STOP] Dolphins monitor stopped.")


if __name__ == "__main__":
    main()
