#!/usr/bin/env python3
"""
Run controller.py off the Pi. The light is replaced by "LIGHT ON / LIGHT OFF"
log lines, and audio is skipped or played on this computer's speakers.
It reads the same event queue as the real controller, so pair it with
fire_event.py or a running monitor.

Usage:
    python3 tests/run_controller.py            # log the light and audio, play nothing
    python3 tests/run_controller.py --audio    # also play the audio locally
    python3 tests/run_controller.py --fast     # don't wait out light durations

Don't run it on the Pi while the real controller is running: both would take
events from the same queue.
"""

import argparse
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness import FakeClock, load_controller  # noqa: E402

# First player found on this computer is used for --audio
PLAYERS = [
    ["mpg123", "-q"],
    ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"],
    ["afplay"],                 # macOS
]


def local_player():
    for cmd in PLAYERS:
        if shutil.which(cmd[0]):
            return cmd
    return None


class FastClock(FakeClock):
    """Real waits for the queue poll, instant waits for light durations."""

    def __init__(self, poll_interval: float):
        super().__init__()
        self.poll_interval = poll_interval

    def time(self):
        import time
        return time.time()

    def sleep(self, seconds):
        import time
        if seconds == self.poll_interval:
            time.sleep(seconds)
        else:
            print(f"[FAST] Skipping {seconds}s wait")


def main():
    parser = argparse.ArgumentParser(description="Run the goal horn controller off the Pi.")
    parser.add_argument("--audio", action="store_true", help="play audio on this computer")
    parser.add_argument("--fast", action="store_true", help="don't wait out light durations")
    args = parser.parse_args()

    controller = load_controller(log=print)

    if args.fast:
        controller.time = FastClock(controller.POLL_INTERVAL)

    player = local_player() if args.audio else None
    if args.audio and player is None:
        print(f"[AUDIO] No player found (tried {', '.join(c[0] for c in PLAYERS)}); "
              f"audio will be skipped.")

    def play_audio(path):
        if path is None:
            return None
        print(f"[AUDIO] {'Playing' if player else 'Would play'}: {os.path.basename(path)}")
        if player is None:
            return None
        proc = subprocess.Popen(player + [path], stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
        # With --fast, don't make the next event wait for the song
        return None if args.fast else proc

    controller.play_audio = play_audio
    print(f"[TEST] Watching {controller.EVENT_FILE}")
    controller.main()


if __name__ == "__main__":
    main()
