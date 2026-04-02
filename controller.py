#!/usr/bin/env python3
"""
Goal Horn Controller — Raspberry Pi Zero WH
The ONLY script that controls GPIO and audio.
Monitors a shared event queue and processes events by priority.
"""

import time
import json
import os
import subprocess
import RPi.GPIO as GPIO
from datetime import datetime, timezone

# ─── Configuration ────────────────────────────────────────────────────────────

GOAL_LIGHT_PIN  = 18                # GPIO 18 = physical pin 12
ALSA_DEVICE     = "hw:1,0"         # USB speaker (card 1, device 0)
BASE_DIR        = os.path.dirname(os.path.abspath(__file__))
AUDIO_DIR       = os.path.join(BASE_DIR, "audio")  # Directory for audio files
EVENT_FILE      = os.path.join(BASE_DIR, "goal_horn_events.json")
POLL_INTERVAL   = 0.5              # Seconds between event queue checks

# ─── Audio Files ──────────────────────────────────────────────────────────────

AUDIO = {
    # Rangers
    "rangers_goal":     f"{AUDIO_DIR}/rangers_goal_song.mp3",
    "rangers_shootout": None,       # No audio for shootout goals
    # Yankees
    "yankees_run":      f"{AUDIO_DIR}/yankees_doorbell.mp3",
    "yankees_home_run": f"{AUDIO_DIR}/yankees_home_run.mp3",
    "yankees_win":      f"{AUDIO_DIR}/new_york_new_york.mp3",
}

# ─── Light Durations (seconds) ────────────────────────────────────────────────

LIGHT_DURATION = {
    "rangers_goal":     60,
    "rangers_shootout": 5,
    "yankees_run":      13,
    "yankees_home_run": 31,
    "yankees_win":      210,
}

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

def play_audio(path: str):
    """Play an audio file through the wired USB speaker."""
    if path is None:
        return
    try:
        proc = subprocess.Popen(
            ["mpg123", "-o", "alsa", "-a", ALSA_DEVICE, path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        print(f"[AUDIO] Playing: {os.path.basename(path)}")
        return proc
    except Exception as e:
        print(f"[AUDIO] Failed to play audio: {e}")
        return None

# ─── Event Queue ──────────────────────────────────────────────────────────────

def read_events() -> list:
    """Read all pending events from the event queue file."""
    if not os.path.exists(EVENT_FILE):
        return []
    try:
        with open(EVENT_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return []


def clear_events():
    """Clear all events from the queue."""
    try:
        with open(EVENT_FILE, "w") as f:
            json.dump([], f)
    except Exception as e:
        print(f"[QUEUE] Failed to clear events: {e}")


def process_event(event: dict):
    """Process a single event — activate light and play audio."""
    event_type  = event.get("event")
    now         = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")

    duration    = LIGHT_DURATION.get(event_type, 5)
    audio_path  = AUDIO.get(event_type)

    print(f"[{now}] [CONTROLLER] Processing event: {event_type}")

    GPIO.output(GOAL_LIGHT_PIN, GPIO.HIGH)
    proc = play_audio(audio_path)
    time.sleep(duration)
    GPIO.output(GOAL_LIGHT_PIN, GPIO.LOW)

    # Wait for audio to finish if it's still playing
    if proc:
        proc.wait()

    print(f"[{now}] [CONTROLLER] Event complete: {event_type}")

# ─── Main Loop ────────────────────────────────────────────────────────────────

def main():
    print("[CONTROLLER] Waiting 15s for USB devices to initialize...")
    time.sleep(15)
    setup_gpio()
    print("[CONTROLLER] Goal horn controller running...")

    # Ensure event file exists
    if not os.path.exists(EVENT_FILE):
        clear_events()

    try:
        while True:
            events = read_events()

            if events:
                # Sort by priority (lower number = higher priority)
                events.sort(key=lambda e: e.get("priority", 99))
                clear_events()

                for event in events:
                    process_event(event)

            time.sleep(POLL_INTERVAL)

    except KeyboardInterrupt:
        print("\n[STOP] Interrupted by user.")
    finally:
        cleanup_gpio()


if __name__ == "__main__":
    main()
