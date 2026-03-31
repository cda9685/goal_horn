#!/usr/bin/env python3
"""
Yankees Goal Horn — Raspberry Pi Zero WH
GPIO 18 (Pin 12) is triggered when the New York Yankees score.
Audio is played through a wired USB speaker.
Coordinates with the Rangers script via a shared lock file.
Uses the MLB Stats API — no API key required.
"""

import time
import json
import os
import subprocess
import requests
import RPi.GPIO as GPIO
from datetime import datetime, timezone

# ─── Configuration ────────────────────────────────────────────────────────────

GOAL_LIGHT_PIN          = 18        # GPIO 18 = physical pin 12
YANKEES_TEAM_ID         = 147       # MLB team ID for New York Yankees
POLL_INTERVAL           = 5        # Seconds between API calls during a live game
IDLE_INTERVAL           = 60        # Seconds between checks when no game is live
STREAM_DELAY_SECONDS    = 10        # Delay to sync with Fubo streaming delay

# Light durations
RUN_LIGHT_SECONDS       = 5         # Light duration for a run scored
HOME_RUN_LIGHT_SECONDS  = 10        # Light duration for a home run
WIN_LIGHT_SECONDS       = 15        # Light duration for a Yankees win

# Audio files
AUDIO_DIR               = "/home/coledallen/projects/goal_horn/audio"
RUN_SONG_PATH           = f"{AUDIO_DIR}/yankees_doorbell.mp3"
HOME_RUN_SONG_PATH      = f"{AUDIO_DIR}/yankees_home_run.mp3"
WIN_SONG_PATH           = f"{AUDIO_DIR}/new_york_new_york.mp3"

# Audio device
ALSA_DEVICE             = "hw:1,0"  # USB speaker (card 1, device 0)

# ─── Lock File Configuration ──────────────────────────────────────────────────
# Lower number = higher priority. Set PRIORITY = 1 for Yankees to take priority
# over Rangers (PRIORITY = 2), or swap them to give Rangers priority.

PRIORITY                = 2         # 1 = highest priority, 2 = lower priority
LOCK_FILE               = "/tmp/goal_horn.lock"
LOCK_TTL                = 60        # Seconds before a lock is considered stale

# ─── MLB API ──────────────────────────────────────────────────────────────────

MLB_SCHEDULE_URL        = "https://statsapi.mlb.com/api/v1/schedule?sportId=1&teamId={team_id}"
MLB_GAME_URL            = "https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"

# ─── GPIO Setup ───────────────────────────────────────────────────────────────

def setup_gpio():
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(GOAL_LIGHT_PIN, GPIO.OUT, initial=GPIO.LOW)
    print(f"[SETUP] GPIO {GOAL_LIGHT_PIN} configured as output.")

def cleanup_gpio():
    GPIO.output(GOAL_LIGHT_PIN, GPIO.LOW)
    GPIO.cleanup()
    print("[SHUTDOWN] GPIO cleaned up.")

# ─── Lock File System ─────────────────────────────────────────────────────────

def acquire_lock() -> bool:
    """
    Try to acquire the shared lock file.
    Returns True if lock was acquired, False if blocked by higher priority script.
    """
    now = time.time()

    # Check if lock already exists
    if os.path.exists(LOCK_FILE):
        try:
            with open(LOCK_FILE, "r") as f:
                lock_data = json.load(f)

            lock_priority = lock_data.get("priority", 99)
            lock_expires  = lock_data.get("expires", 0)

            # Lock is still valid
            if now < lock_expires:
                # Other script has higher or equal priority — back off
                if lock_priority <= PRIORITY:
                    print(f"[LOCK] Blocked by higher priority script "
                          f"(priority={lock_priority}). Skipping this event.")
                    return False
                # We have higher priority — take over the lock
                else:
                    print(f"[LOCK] Overriding lower priority lock (priority={lock_priority}).")
            # Lock is stale — take it
            else:
                print(f"[LOCK] Stale lock found, taking over.")

        except Exception as e:
            print(f"[LOCK] Error reading lock file: {e}. Proceeding.")

    # Write our lock
    try:
        lock_data = {
            "priority": PRIORITY,
            "pid":      os.getpid(),
            "expires":  now + LOCK_TTL,
        }
        with open(LOCK_FILE, "w") as f:
            json.dump(lock_data, f)
        return True
    except Exception as e:
        print(f"[LOCK] Failed to write lock file: {e}. Proceeding anyway.")
        return True


def release_lock():
    """Release the shared lock file if we own it."""
    try:
        if os.path.exists(LOCK_FILE):
            with open(LOCK_FILE, "r") as f:
                lock_data = json.load(f)
            if lock_data.get("pid") == os.getpid():
                os.remove(LOCK_FILE)
    except Exception as e:
        print(f"[LOCK] Failed to release lock: {e}")

# ─── Audio ────────────────────────────────────────────────────────────────────

def play_audio(path: str):
    """Play an audio file through the wired USB speaker."""
    try:
        subprocess.Popen(
            ["mpg123", "-o", "alsa", "-a", ALSA_DEVICE, path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        print(f"[AUDIO] Playing: {os.path.basename(path)}")
    except Exception as e:
        print(f"[AUDIO] Failed to play audio: {e}")

# ─── Event Activations ────────────────────────────────────────────────────────

def activate_run(home_run: bool = False):
    """Wait for stream delay, then trigger light and audio for a run or home run."""
    event = "HOME RUN" if home_run else "RUN SCORED"
    duration = HOME_RUN_LIGHT_SECONDS if home_run else RUN_LIGHT_SECONDS
    song = HOME_RUN_SONG_PATH if home_run else RUN_SONG_PATH

    print(f"[{event}] Yankees {event.lower()}! Waiting {STREAM_DELAY_SECONDS}s for stream delay...")

    if not acquire_lock():
        return

    try:
        time.sleep(STREAM_DELAY_SECONDS)
        print(f"[{event}] Activating light for {duration}s!")
        GPIO.output(GOAL_LIGHT_PIN, GPIO.HIGH)
        play_audio(song)
        time.sleep(duration)
        GPIO.output(GOAL_LIGHT_PIN, GPIO.LOW)
        print(f"[{event}] Light off.")
    finally:
        release_lock()


def activate_win():
    """Wait for stream delay, then trigger light and audio for a Yankees win."""
    print(f"[WIN] Yankees won! Waiting {STREAM_DELAY_SECONDS}s for stream delay...")

    if not acquire_lock():
        return

    try:
        time.sleep(STREAM_DELAY_SECONDS)
        print(f"[WIN] Activating light for {WIN_LIGHT_SECONDS}s!")
        GPIO.output(GOAL_LIGHT_PIN, GPIO.HIGH)
        play_audio(WIN_SONG_PATH)
        time.sleep(WIN_LIGHT_SECONDS)
        GPIO.output(GOAL_LIGHT_PIN, GPIO.LOW)
        print("[WIN] Light off.")
    finally:
        release_lock()

# ─── MLB API Helpers ──────────────────────────────────────────────────────────

def get_todays_yankees_game() -> dict | None:
    """
    Fetch today's schedule and return the Yankees game info, or None if not playing.
    Returns a dict with keys: game_pk, state, home, away
    """
    try:
        url = MLB_SCHEDULE_URL.format(team_id=YANKEES_TEAM_ID)
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        print(f"[API ERROR] Schedule fetch failed: {e}")
        return None

    dates = data.get("dates", [])
    for date in dates:
        for game in date.get("games", []):
            home_id = game.get("teams", {}).get("home", {}).get("team", {}).get("id")
            away_id = game.get("teams", {}).get("away", {}).get("team", {}).get("id")
            if YANKEES_TEAM_ID in (home_id, away_id):
                status = game.get("status", {}).get("abstractGameState", "")
                return {
                    "game_pk": game["gamePk"],
                    "state":   status,   # Preview, Live, Final
                    "home":    game["teams"]["home"]["team"]["name"],
                    "away":    game["teams"]["away"]["team"]["name"],
                }
    return None


def get_game_data(game_pk: int) -> dict | None:
    """
    Return a dict with:
    - yankees_runs: current run total
    - yankees_won: True if game is Final and Yankees won
    - last_play_index: index of the most recent completed play
    - last_play_is_hr: True if the most recent new play was a home run
    """
    try:
        url = MLB_GAME_URL.format(game_pk=game_pk)
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        print(f"[API ERROR] Game fetch failed: {e}")
        return None

    game_state  = data.get("gameData", {}).get("status", {}).get("abstractGameState", "")
    teams       = data.get("liveData", {}).get("linescore", {}).get("teams", {})
    home_team   = data.get("gameData", {}).get("teams", {}).get("home", {})
    away_team   = data.get("gameData", {}).get("teams", {}).get("away", {})

    # Determine if Yankees are home or away
    if home_team.get("id") == YANKEES_TEAM_ID:
        yankees_runs    = teams.get("home", {}).get("runs", 0)
        opponent_runs   = teams.get("away", {}).get("runs", 0)
    else:
        yankees_runs    = teams.get("away", {}).get("runs", 0)
        opponent_runs   = teams.get("home", {}).get("runs", 0)

    yankees_won = game_state == "Final" and yankees_runs > opponent_runs

    # Scan plays for home runs
    all_plays       = data.get("liveData", {}).get("plays", {}).get("allPlays", [])
    last_play_index = len(all_plays) - 1
    last_play_is_hr = False

    if all_plays:
        last_play       = all_plays[-1]
        event_type      = last_play.get("result", {}).get("eventType", "")
        last_play_is_hr = event_type == "home_run"

    return {
        "yankees_runs":     yankees_runs,
        "yankees_won":      yankees_won,
        "last_play_index":  last_play_index,
        "last_play_is_hr":  last_play_is_hr,
        "game_state":       game_state,
    }

# ─── Main Loop ────────────────────────────────────────────────────────────────

def main():
    setup_gpio()
    print(f"[START] Monitoring MLB games for the Yankees (ID={YANKEES_TEAM_ID})...")

    last_run_count      = None
    last_play_index     = None
    win_triggered       = False
    active_game_pk      = None

    try:
        while True:
            now = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
            game = get_todays_yankees_game()

            # ── No game today ──────────────────────────────────────────────────
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

            # ── Game hasn't started yet ────────────────────────────────────────
            if state == "Preview":
                print(f"[{now}] Game found ({matchup}) but not yet live. "
                      f"Checking again in {IDLE_INTERVAL}s.")
                last_run_count  = None
                last_play_index = None
                win_triggered   = False
                active_game_pk  = None
                time.sleep(IDLE_INTERVAL)
                continue

            # ── Game is live or finished ───────────────────────────────────────
            if state in ("Live", "Final"):

                # Reset trackers when a new game is detected
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

                # ── First poll — establish baseline ────────────────────────────
                if last_run_count is None:
                    last_run_count  = current_runs
                    last_play_index = play_index
                    print(f"[{now}] Game live ({matchup}) | Yankees runs: {current_runs} "
                          f"(baseline set)")

                # ── Runs scored since last poll ────────────────────────────────
                elif current_runs > last_run_count:
                    new_runs    = current_runs - last_run_count
                    is_home_run = play_is_hr and play_index != last_play_index

                    if is_home_run:
                        print(f"[{now}] YANKEES HOME RUN! (+{new_runs}) | "
                              f"Total: {current_runs}")
                        activate_run(home_run=True)
                    else:
                        print(f"[{now}] YANKEES SCORED! (+{new_runs}) | "
                              f"Total: {current_runs}")
                        for _ in range(new_runs):
                            activate_run(home_run=False)
                            time.sleep(1)

                    last_run_count  = current_runs
                    last_play_index = play_index

                else:
                    print(f"[{now}] {matchup} | State={game_state} | "
                          f"Yankees runs: {current_runs}")

                # ── Yankees win ────────────────────────────────────────────────
                if yankees_won and not win_triggered:
                    print(f"[{now}] YANKEES WIN!")
                    win_triggered = True
                    activate_win()

                # ── Stop polling after game ends ───────────────────────────────
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
        print("\n[STOP] Interrupted by user.")
    finally:
        release_lock()
        cleanup_gpio()


if __name__ == "__main__":
    main()
