"""Every recorded game in tests/fixtures/ replays to its expected events."""

from pathlib import Path

import pytest

from harness import load_fixture

FIXTURES = sorted((Path(__file__).parent / "fixtures").glob("*.json"))


@pytest.mark.parametrize("path", FIXTURES, ids=[p.stem for p in FIXTURES])
def test_fixture(path, replay):
    fixture = load_fixture(path)
    if fixture.get("expected_events") is None:
        pytest.skip(f'{path.name} has no "expected_events" yet')
    assert replay(fixture["team"], fixture["steps"]).events == fixture["expected_events"]
