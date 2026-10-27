import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import load_script, run_replay, stub_gpio  # noqa: E402

stub_gpio()


@pytest.fixture
def replay(tmp_path):
    """replay(team, steps) runs a monitor against the steps and returns a ReplayResult."""
    runs = iter(range(1_000_000))

    def run(team, steps, module=None):
        # Each run gets its own event queue and completed-games file
        state_dir = tmp_path / f"replay{next(runs)}"
        state_dir.mkdir()
        return run_replay(team, steps, state_dir, module=module)
    return run


@pytest.fixture
def monitor(tmp_path):
    """monitor(team) loads a monitor with its state files in a temp dir, to change config first."""
    return lambda team: load_script(team, tmp_path)
