#!/usr/bin/env python3
"""
Rangers Goal Horn — Raspberry Pi 4
GPIO 18 (Pin 12) is triggered when the New York Rangers score.
Goal song is played through Bluetooth to Alexa speaker.
Uses the NHL API (api-web.nhle.com) — no API key required.
"""

import time
import subprocess
import requests
import RPi.GPIO as GPIO
from datetime import datetime, timezone

# ─── Configuration ────────────────────────────────────────────────────────────

GOAL_LIGHT_PIN    = 18          # GPIO 18 = physical pin 12
RANGERS_TEAM_ID   = "NYR"       # NHL team abbreviation
POLL_INTERVAL     = 5           # Seconds between API calls during a live game
IDLE_INTERVAL     = 60          # Seconds between checks when no game is live
LIGHT_ON_SECONDS        = 60    # How long the goal light stays on per goal
SHOOTOUT_LIGHT_SECONDS  = 5     # How long the light stays on for a shootout goal (no audio)

STREAM_DELAY_SECONDS = 10       # Delay to sync with TV streaming delay

GOAL_SONG_PATH    = "/home/coledallen/projects/goal_horn/audio/rangers_goal_song.mp3"
ALSA_DEVICE       = "hw:1,0"
# BLUETOOTH_SINK    = "bluez_output.44_00_49_13_75_F4.1"  # from pactl list sinks short

NHL_SCHEDULE_URL  = "https://api-web.nhle.com/v1/schedule/now"
NHL_GAME_URL      = "https://api-web.nhle.com/v1/gamecenter/{game_id}/landing"

# ─── GPIO Setup ───────────────────────────────────────────────────────────────

def setup_gpio():
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(GOAL_LIGHT_PIN, GPIO.OUT, initial=GPIO.LOW)
    print(f"[SETUP] GPIO {GOAL_LIGHT_PIN} configured as output.")

def cleanup_gpio():
    GPIO.output(GOAL_LIGHT_PIN, GPIO.LOW)
    GPIO.cleanup()
    print("[SHUTDOWN] GPIO cleaned up.")

# ─── Audio ────────────────────────────────────────────────────────────────────

def play_goal_song():
    """Play the goal song through the wired USB speaker."""
    try:
        subprocess.Popen(
            ["mpg123", "-o", "alsa", "-a", ALSA_DEVICE, GOAL_SONG_PATH],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        print("[AUDIO] Goal song sent to speaker!")
    except Exception as e:
        print(f"[AUDIO] Failed to play goal song: {e}")

# ─── Goal Light ───────────────────────────────────────────────────────────────

def activate_goal_light(duration: float = LIGHT_ON_SECONDS):
    """Wait for stream delay, then turn on the goal light and play the goal song simultaneously."""
    print(f"[GOAL!] Rangers scored! Waiting {STREAM_DELAY_SECONDS}s for stream delay...")
    time.sleep(STREAM_DELAY_SECONDS)
    print(f"[GOAL!] Activating goal light for {duration}s!")
    GPIO.output(GOAL_LIGHT_PIN, GPIO.HIGH)
    play_goal_song()        # Starts playing immediately, non-blocking
    time.sleep(duration)
    GPIO.output(GOAL_LIGHT_PIN, GPIO.LOW)
    print("[GOAL!] Light off.")

def activate_shootout_light(duration: float = SHOOTOUT_LIGHT_SECONDS):
    """Wait for stream delay, then flash the light briefly for a shootout goal — no audio."""
    print(f"[SO GOAL!] Rangers shootout goal! Waiting {STREAM_DELAY_SECONDS}s for stream delay...")
    time.sleep(STREAM_DELAY_SECONDS)
    print(f"[SO GOAL!] Activating goal light for {duration}s (no audio).")
    GPIO.output(GOAL_LIGHT_PIN, GPIO.HIGH)
    time.sleep(duration)
    GPIO.output(GOAL_LIGHT_PIN, GPIO.LOW)
    print("[SO GOAL!] Light off.")

# ─── NHL API Helpers ──────────────────────────────────────────────────────────

def get_todays_rangers_game() -> dict | None:
    """
    Fetch today's schedule and return the Rangers game info, or None if not playing.
    Returns a dict with keys: game_id, state
    """
    try:
        response = requests.get(NHL_SCHEDULE_URL, timeout=10)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        print(f"[API ERROR] Schedule fetch failed: {e}")
        return None

    game_weeks = data.get("gameWeek", [])
    for day in game_weeks:
        for game in day.get("games", []):
            home = game.get("homeTeam", {}).get("abbrev", "")
            away = game.get("awayTeam", {}).get("abbrev", "")
            if RANGERS_TEAM_ID in (home, away):
                return {
                    "game_id": game["id"],
                    "state":   game.get("gameState", ""),  # FUT, PRE, LIVE, CRIT, FINAL, OFF
                    "home":    home,
                    "away":    away,
                }
    return None


def get_game_data(game_id: int) -> dict | None:
    """
    Return a dict with the Rangers' goal count, current period type, and shootout goals.
    Returns None on error.
    Period types: REG, OT, SO
    """
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
    period_type = period_desc.get("periodType", "REG")  # REG, OT, SO

    # Determine which team is the Rangers
    if home_team.get("abbrev") == RANGERS_TEAM_ID:
        rangers_team = home_team
    elif away_team.get("abbrev") == RANGERS_TEAM_ID:
        rangers_team = away_team
    else:
        return None

    score = rangers_team.get("score", 0)

    # Count Rangers shootout goals if in a shootout
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
    setup_gpio()
    print(f"[START] Monitoring NHL games for the {RANGERS_TEAM_ID}...")

    last_goal_count = None
    last_so_goals   = None
    active_game_id  = None

    try:
        while True:
            now = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
            game = get_todays_rangers_game()

            # ── No game today ──────────────────────────────────────────────────
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

            # ── Game hasn't started yet ────────────────────────────────────────
            if state in ("FUT", "PRE"):
                print(f"[{now}] Game found ({matchup}) but not yet live (state={state}). "
                      f"Checking again in {IDLE_INTERVAL}s.")
                last_goal_count = None
                last_so_goals   = None
                active_game_id  = None
                time.sleep(IDLE_INTERVAL)
                continue

            # ── Game is live or just ended ─────────────────────────────────────
            if state in ("LIVE", "CRIT", "FINAL", "OFF"):

                # Reset goal tracker when a new game is detected
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

                # ── Shootout period ────────────────────────────────────────────
                if period_type == "SO":
                    if last_so_goals is None:
                        last_so_goals = so_goals
                        print(f"[{now}] Shootout started! Rangers SO goals: {so_goals} "
                              f"(baseline set)")
                    elif so_goals > last_so_goals:
                        new_so_goals = so_goals - last_so_goals
                        print(f"[{now}] RANGERS SHOOTOUT GOAL! (+{new_so_goals})")
                        for _ in range(new_so_goals):
                            activate_shootout_light(SHOOTOUT_LIGHT_SECONDS)
                            time.sleep(1)
                        last_so_goals = so_goals
                    else:
                        print(f"[{now}] {matchup} | SO | Rangers SO goals: {so_goals}")

                # ── Regular / OT period ────────────────────────────────────────
                else:
                    # First poll — establish baseline without triggering light
                    if last_goal_count is None:
                        last_goal_count = current_goals
                        print(f"[{now}] Game live ({matchup}) | Period: {period_type} | "
                              f"Rangers goals: {current_goals} (baseline set)")

                    # Goal(s) scored since last poll
                    elif current_goals > last_goal_count:
                        new_goals = current_goals - last_goal_count
                        print(f"[{now}] RANGERS SCORED! (+{new_goals}) | Total: {current_goals}")
                        for _ in range(new_goals):
                            activate_goal_light(LIGHT_ON_SECONDS)
                            time.sleep(1)
                        last_goal_count = current_goals

                    else:
                        print(f"[{now}] {matchup} | {period_type} | State={state} | "
                              f"Rangers goals: {current_goals}")

                # Stop polling after game is truly over
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
        print("\n[STOP] Interrupted by user.")
    finally:
        cleanup_gpio()


if __name__ == "__main__":
    main()
