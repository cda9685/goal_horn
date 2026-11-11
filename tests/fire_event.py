#!/usr/bin/env python3
"""
Fire goal horn events on demand by writing them straight to the event queue.
The running controller picks them up within half a second, so the light and
audio for any event can be checked without waiting for a game.

Usage:
    python3 tests/fire_event.py vols_touchdown            # one event
    python3 tests/fire_event.py rangers_goal yankees_run  # several, played by priority
    python3 tests/fire_event.py --list                    # every configured event
"""

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness import load_script  # noqa: E402


def configured_events(controller) -> list[str]:
    return sorted(set(controller.AUDIO) | set(controller.LIGHT_DURATION))


def describe(controller, event: str) -> str:
    audio = controller.AUDIO.get(event)
    if isinstance(audio, list):
        return " or ".join(f"{os.path.basename(p)} ({d}s)" for p, d in audio)
    duration = controller.LIGHT_DURATION.get(event, 5)
    sound    = os.path.basename(audio) if audio else "no audio"
    return f"{sound}, light {duration}s"


def main():
    parser = argparse.ArgumentParser(description="Write test events to the goal horn queue.")
    parser.add_argument("events", nargs="*", help="event names, e.g. vols_touchdown")
    parser.add_argument("--list", action="store_true", help="list configured events and exit")
    parser.add_argument("--priority", type=int, default=1, help="priority for the events (default 1)")
    parser.add_argument("--force", action="store_true",
                        help="queue event names the controller doesn't know (they get a 5s light)")
    args = parser.parse_args()

    controller = load_script("controller")
    known      = configured_events(controller)

    if args.list or not args.events:
        for event in known:
            print(f"  {event:<22} {describe(controller, event)}")
        return

    unknown = [e for e in args.events if e not in known]
    if unknown and not args.force:
        sys.exit(f"Unknown event(s): {', '.join(unknown)}. "
                 f"Use --list to see valid names, or --force to send anyway.")

    try:
        events = []
        if os.path.exists(controller.EVENT_FILE):
            with open(controller.EVENT_FILE) as f:
                events = json.load(f)
        for event in args.events:
            events.append({"event": event, "priority": args.priority, "timestamp": time.time()})
        with open(controller.EVENT_FILE, "w") as f:
            json.dump(events, f)
    except PermissionError:
        sys.exit(f"Can't write {controller.EVENT_FILE}. Try again with sudo.")

    for event in args.events:
        print(f"[QUEUE] Event queued: {event} ({describe(controller, event)})")
    print("The controller must be running to play them (./restart.sh -m controller).")


if __name__ == "__main__":
    main()
