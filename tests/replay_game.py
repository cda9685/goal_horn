#!/usr/bin/env python3
"""
Replay a recorded game through its monitor in a second or two: no stream delay
waits, no live API, no light. Prints the events the monitor queued and when.

Usage:
    python3 tests/replay_game.py tests/fixtures/rangers_2026-10-25.json
    python3 tests/replay_game.py tests/fixtures/rangers_2026-10-25.json -v   # monitor log too
"""

import argparse
import contextlib
import io
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness import load_fixture, run_replay  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="Replay a recorded game through its monitor.")
    parser.add_argument("fixture", help="replay file made by record_game.py")
    parser.add_argument("-v", "--verbose", action="store_true", help="show the monitor's log")
    args = parser.parse_args()

    fixture = load_fixture(args.fixture)
    log     = io.StringIO()
    with tempfile.TemporaryDirectory() as state_dir:
        with contextlib.redirect_stdout(sys.stdout if args.verbose else log):
            result = run_replay(fixture["team"], fixture["steps"], state_dir)

    print(f"{fixture['team']}: {fixture.get('description') or os.path.basename(args.fixture)}")
    print(f"Replayed {len(result.replay.requests)} responses "
          f"({result.clock.elapsed() / 3600:.1f}h of monitor time)")
    for event, at in result.event_times():
        print(f"  {int(at // 3600)}:{int(at % 3600 // 60):02d}:{int(at % 60):02d}  {event}")
    if not result.events:
        print("  (no events)")

    expected = fixture.get("expected_events")
    if expected is None:
        print('No "expected_events" in the file yet. If the events above are right, '
              'copy them in so the tests check this game.')
    elif result.events == expected:
        print("Matches expected_events.")
    else:
        sys.exit(f"Does NOT match expected_events: {expected}")


if __name__ == "__main__":
    main()
