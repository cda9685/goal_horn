"""
Every recorded game replays to its expected events, as it happened (with
debug off and on) and with each variation (see variations.py) added: the
example recordings in tests/recordings/examples/ (committed, so tested
everywhere), and your own in tests/recordings/ (not committed, so tested only
on your machine) once their "expected_events" is filled in.
"""

import json
from pathlib import Path

import pytest

import variations
from harness import known_bug_marks, load_recording, load_script, team_id

FOLDER     = Path(__file__).parent / "recordings"
RECORDINGS = sorted(FOLDER.glob("examples/*.json")) + sorted(FOLDER.glob("*.json"))


@pytest.mark.parametrize("debug", [False, True], ids=["normal", "debug"])
@pytest.mark.parametrize("path", RECORDINGS, ids=[p.stem for p in RECORDINGS])
def test_recording(path, debug, replay):
    recording = load_recording(path)
    if recording.get("expected_events") is None:
        pytest.skip(f'{path.name} has no "expected_events" yet')
    result = replay(recording["team"], recording["steps"], debug=debug)
    assert result.events == recording["expected_events"]
    assert bool(result.debug_lines) == debug

# ─── Variations ───────────────────────────────────────────────────────────────

# Variations that hit a known bug, by (variation, API)
KNOWN_BUGS = {
    ("glitch", "espn"):        (20, "a one-poll score glitch is taken as an overturn"),
    ("blank_score", "espn"):   (36, "a blank score is read as 0"),
    ("blank_score", "nhl"):    (37, "unexpected API data crashes the monitor"),
    ("blank_score", "mlb"):    (37, "unexpected API data crashes the monitor"),
    ("request_error", "nhl"):  (33, "a failed API request resets the baseline"),
    ("request_error", "mlb"):  (33, "a failed API request resets the baseline"),
    ("request_error", "espn"): (33, "a failed API request resets the baseline"),
    ("overturn", "nhl"):       (20, "overturned goal hides the next goal"),
    ("overturn", "mlb"):       (20, "overturned run hides the next run"),
}


def variation_cases():
    cases = []
    for path in RECORDINGS:
        with open(path) as f:
            recording = json.load(f)
        if recording.get("expected_events") is None:
            continue
        api = variations.api_of(recording["team"])
        for variation in variations.VARIATIONS:
            if not variations.applies(variation, api):
                continue
            bug   = KNOWN_BUGS.get((variation, api))
            marks = known_bug_marks(*bug) if bug else []
            cases.append(pytest.param(path, variation, marks=marks,
                                      id=f"{path.stem}-{variation}"))
    return cases


@pytest.mark.parametrize("path, variation", variation_cases())
def test_recording_variation(path, variation, replay):
    recording = load_recording(path)
    team    = recording["team"]
    api     = variations.api_of(team)
    tid     = team_id(load_script(team))
    polls   = variations.group_polls(recording["steps"], api)
    expected = recording["expected_events"]

    at = None
    if variation == "overturn":
        # Overturn the last score that fired an event: it should fire again
        # when it's scored again, right after its first time
        for i in reversed(variations.scoring_polls(polls, api, tid)):
            before = replay(team, variations.flatten(polls[:i])).events
            after  = replay(team, variations.flatten(polls[:i + 1])).events
            fired  = after[len(before):]
            if fired:
                at, expected = i, after + fired + expected[len(after):]
                break
        else:
            pytest.skip(f"{path.name}: no score fires an event")

    varied = variations.vary(polls, variation, api, tid, at=at)
    if varied is None:
        pytest.skip(f"{path.name} has nowhere to add {variation}")
    assert len(varied) > len(polls), "the variation should add polls"
    assert replay(team, variations.flatten(varied)).events == expected
