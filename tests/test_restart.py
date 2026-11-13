"""
restart.sh, run against fake process tools: nothing is really killed or started.
pgrep/pkill match against a pretend process list, and python3 just records
which script it was asked to start.
"""

import os
import re
import subprocess
import time
from pathlib import Path

import pytest

from harness import REPO_ROOT, all_monitors

RESTART = REPO_ROOT / "restart.sh"

# Fake commands. FAKE_PS is the pretend process list, one command line per line.
STUBS = {
    "pgrep": 'grep -qE -- "$2" "$FAKE_PS"\n',
    "pkill": ('echo "pkill $2" >> "$FAKE_LOG"\n'
              'grep -vE -- "$2" "$FAKE_PS" > "$FAKE_PS.new"; mv "$FAKE_PS.new" "$FAKE_PS"\n'),
    "sudo":  '"$@"\n',
    "sleep": "true\n",
    "python3": 'echo "start $(basename "$2")${3:+ ${*:3}}" >> "$FAKE_LOG"\n',
}


@pytest.fixture
def restart(tmp_path):
    """restart(args, running=[...]) -> (exit code, output, log of kills and starts, still running)."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in STUBS.items():
        stub = bin_dir / name
        stub.write_text("#!/bin/bash\n" + body)
        stub.chmod(0o755)

    # A copy of restart.sh pointed at the temp dir instead of the Pi's project folder
    script = tmp_path / "restart.sh"
    script.write_text(re.sub(r"^DIR=.*$", f"DIR={tmp_path}", RESTART.read_text(), flags=re.M))
    script.chmod(0o755)

    def run(*args, running=()):
        ps, log = tmp_path / "ps", tmp_path / "log"
        ps.write_text("".join(f"python3 -u {tmp_path}/{name}.py\n" for name in running))
        log.write_text("")
        env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}",
               "FAKE_PS": str(ps), "FAKE_LOG": str(log)}
        proc = subprocess.run(["bash", str(script), *args], env=env,
                              capture_output=True, text=True, timeout=10)
        # Scripts are started in the background (&): wait for each "Started" to land
        expected = proc.stdout.count("Started ")
        deadline = time.monotonic() + 5
        while (sum(line.startswith("start") for line in log.read_text().splitlines()) < expected
               and time.monotonic() < deadline):
            time.sleep(0.01)
        still = [Path(line.split()[-1]).stem for line in ps.read_text().splitlines()]
        return proc.returncode, proc.stdout, log.read_text().splitlines(), still
    return run


def test_all_lists_the_controller_and_every_monitor():
    # Adding a team step 3: a monitor missing from ALL is never restarted
    names = re.search(r'^ALL="(.*)"$', RESTART.read_text(), flags=re.M).group(1).split()
    assert sorted(names) == sorted(["controller"] + all_monitors())


def test_restart_giants_leaves_ny_giants_running(restart):
    # Issue #25: "giants" must not also match ny_giants_monitor.py
    code, _, log, still = restart("giants", running=["giants_monitor", "ny_giants_monitor"])
    assert code == 0
    assert still == ["ny_giants_monitor"]
    assert log == [r"pkill /giants_monitor\.py", "start giants_monitor.py"]


def test_missing_only_starts_giants_when_only_ny_giants_runs(restart):
    # Issue #25: with -m, a running ny_giants_monitor.py must not make giants look running
    code, out, log, still = restart("-m", "giants", "ny_giants", running=["ny_giants_monitor"])
    assert code == 0
    assert log == ["start giants_monitor.py"]
    assert "ny_giants_monitor.py already running" in out


def test_restart_everything(restart):
    code, _, log, _ = restart(running=["controller", "rangers_monitor"])
    starts = sorted(line.split()[1] for line in log if line.startswith("start"))
    assert code == 0
    assert starts == sorted(["controller.py"] + [f"{m}_monitor.py" for m in all_monitors()])


@pytest.mark.parametrize("name", ["rangers", "rangers_monitor", "rangers_monitor.py"])
def test_accepts_any_form_of_a_name(restart, name):
    code, _, log, _ = restart(name)
    assert code == 0
    assert log == ["start rangers_monitor.py"]


@pytest.mark.parametrize("args", [["bogus"], ["rangers", "bogus"], ["-x"]])
def test_unknown_name_or_flag_changes_nothing(restart, args):
    code, out, log, still = restart(*args, running=["rangers_monitor"])
    assert code == 1
    assert "Usage" in out
    assert log == []
    assert still == ["rangers_monitor"]
