#!/usr/bin/env python3
"""
Vols Monitor — Raspberry Pi Zero WH
Monitors the ESPN API for Tennessee Volunteers football scores and writes events
to the shared queue. GPIO and audio are handled by controller.py.
Uses the ESPN API (site.api.espn.com) — no API key required.
"""

import time
import json
import os
import requests
from datetime import datetime, timezone

# ─── Configuration ────────────────────────────────────────────────────────────

VOLS_TEAM_ID            = "2633"    # ESPN team ID for Tennessee
POLL_INTERVAL           = 5         # Seconds between API calls during a live game
IDLE_INTERVAL           = 60        # Seconds between checks when no game is live
STREAM_DELAY_SECONDS    = 30        # Delay to sync with Fubo streaming delay
PRIORITY                = 3         # 1 = highest priority, 3 = lower priority
CONVERSION_WINDOW       = 180       # Seconds after a touchdown to treat a 1/2 point score as the PAT
BASE_DIR                = os.path.dirname(os.path.abspath(__file__))
EVENT_FILE              = os.path.join(BASE_DIR, "goal_horn_events.json")

# groups=80 = all FBS games; no date returns the current week, so late games
# that run past midnight are still found
ESPN_SCOREBOARD_URL     = ("https://site.api.espn.com/apis/site/v2/sports/football/"
                           "college-football/scoreboard?groups=80&limit=300")

# ESPN status names that mean the game will not be played today
NOT_PLAYING_STATUSES    = ("STATUS_POSTPONED", "STATUS_CANCELED", "STATUS_FORFEIT")

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

# ─── ESPN API Helpers ─────────────────────────────────────────────────────────

def get_vols_game() -> dict | None:
    """Find this week's Vols game and return its state and score."""
    try:
        response = requests.get(ESPN_SCOREBOARD_URL, timeout=10)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        print(f"[API ERROR] Scoreboard fetch failed: {e}")
        return None

    for event in data.get("events", []):
        competitions = event.get("competitions", [])
        if not competitions:
            continue
        competitors = competitions[0].get("competitors", [])

        vols = None
        home = away = ""
        for team in competitors:
            abbrev = team.get("team", {}).get("abbreviation", "")
            if team.get("homeAway") == "home":
                home = abbrev
            else:
                away = abbrev
            if str(team.get("team", {}).get("id", team.get("id"))) == VOLS_TEAM_ID:
                vols = team

        if vols is None:
            continue

        status = event.get("status", {}).get("type", {})
        try:
            score = int(vols.get("score", 0))
        except (TypeError, ValueError):
            score = 0

        return {
            "game_id": event["id"],
            "state":   status.get("state", ""),   # pre / in / post
            "status":  status.get("name", ""),
            "period":  event.get("status", {}).get("period", 0),
            "score":   score,
            "home":    home,
            "away":    away,
        }
    return None

# ─── Main Loop ────────────────────────────────────────────────────────────────

def main():
    print(f"[START] Vols monitor running...")

    last_score       = None
    active_game_id   = None
    last_td_time     = None     # Set after a touchdown; the PAT/2pt that follows is not a new score

    try:
        while True:
            now  = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
            game = get_vols_game()

            if game is None:
                print(f"[{now}] No Vols game this week. Checking again in {IDLE_INTERVAL}s.")
                last_score     = None
                active_game_id = None
                last_td_time   = None
                time.sleep(IDLE_INTERVAL)
                continue

            game_id = game["game_id"]
            state   = game["state"]
            matchup = f"{game['away']} @ {game['home']}"

            if state == "pre" or game["status"] in NOT_PLAYING_STATUSES:
                print(f"[{now}] Game found ({matchup}) but not yet live "
                      f"(status={game['status']}). Checking again in {IDLE_INTERVAL}s.")
                last_score     = None
                active_game_id = None
                last_td_time   = None
                time.sleep(IDLE_INTERVAL)
                continue

            if game_id != active_game_id:
                print(f"[{now}] New game detected: {matchup} (ID={game_id})")
                active_game_id = game_id
                last_score     = None
                last_td_time   = None

            current_score = game["score"]
            period        = game["period"]

            if last_score is None:
                last_score = current_score
                print(f"[{now}] Game live ({matchup}) | Q{period} | "
                      f"Vols points: {current_score} (baseline set)")

            elif current_score > last_score:
                points = current_score - last_score
                in_conversion_window = (last_td_time is not None and
                                        time.time() - last_td_time <= CONVERSION_WINDOW)

                if points >= 6:
                    # Touchdown (possibly with the PAT already included)
                    print(f"[{now}] VOLS TOUCHDOWN! (+{points}) | Total: {current_score}")
                    last_td_time = time.time() if points == 6 else None
                    queue_event("vols_touchdown")
                elif points <= 2 and in_conversion_window:
                    # Extra point or two-point conversion after a touchdown
                    print(f"[{now}] Vols conversion (+{points}) | Total: {current_score}")
                    last_td_time = None
                else:
                    # Field goal, safety, or overtime two-point attempt
                    print(f"[{now}] VOLS SCORED! (+{points}) | Total: {current_score}")
                    last_td_time = None
                    queue_event("vols_score")

                last_score = current_score

            elif current_score < last_score:
                # Score was corrected (e.g. overturned on review)
                print(f"[{now}] Vols score corrected: {last_score} -> {current_score}")
                last_score   = current_score
                last_td_time = None

            else:
                print(f"[{now}] {matchup} | Q{period} | State={state} | "
                      f"Vols points: {current_score}")

            if state == "post":
                print(f"[{now}] Game over. Final Vols points: {current_score}. "
                      f"Resuming idle checks in {IDLE_INTERVAL}s.")
                last_score     = None
                active_game_id = None
                last_td_time   = None
                time.sleep(IDLE_INTERVAL)
                continue

            time.sleep(POLL_INTERVAL)

    except KeyboardInterrupt:
        print("\n[STOP] Vols monitor stopped.")


if __name__ == "__main__":
    main()
