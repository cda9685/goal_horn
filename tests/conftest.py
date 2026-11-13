import fnmatch
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import load_script, run_replay, stub_gpio  # noqa: E402

stub_gpio()


# Tests must never write to the real goal horn's files: on the Pi a test that
# wrote to goal_horn_events.json would set off the light. The run fails if any
# test leaves a new file in the project.
# On the Pi the goal horn keeps running during a test run, so files it makes
# on its own don't count: logs (and logrotate's rotated copies), temporary
# files, and recordings the DVR saves in tests/recordings/ (not examples/).
IGNORED      = ("__pycache__", ".pytest_cache", ".git", ".venv")
LIVE_SYSTEM  = ("*.log", "*.log.*", "*.tmp", "tests/recordings/*")


def project_files() -> set:
    root  = Path(__file__).resolve().parent.parent
    files = set()
    for p in root.rglob("*"):
        rel = p.relative_to(root)
        if not p.is_file() or any(part in IGNORED for part in rel.parts):
            continue
        if rel.parts[:3] != ("tests", "recordings", "examples") and any(
                fnmatch.fnmatch(str(rel), pattern) for pattern in LIVE_SYSTEM):
            continue
        files.add(str(rel))
    return files


def pytest_sessionstart(session):
    session.config._files_before = project_files()


def pytest_sessionfinish(session, exitstatus):
    new = sorted(project_files() - session.config._files_before)
    if new:
        tr = session.config.pluginmanager.get_plugin("terminalreporter")
        tr.write_sep("=", "FAILED: tests left new files in the project", red=True)
        tr.write_line(f"{new}: tests must use a temp folder, never the goal horn's real files")
        session.exitstatus = 1


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "known_bug(issue, reason): correct behavior for an open bug; "
                   "add it with harness.known_bug()")


def pytest_report_teststatus(report, config):
    # Say "KNOWN BUG" instead of pytest's "XFAIL" in -v output
    if hasattr(report, "wasxfail") and report.skipped and "known_bug" in report.keywords:
        return "xfailed", "x", "KNOWN BUG"


def pytest_terminal_summary(terminalreporter):
    """After the run, list the known bugs by issue, and any that now pass."""
    tr = terminalreporter
    by_issue = {}
    for report in tr.stats.get("xfailed", []):
        match = re.match(r"Issue #(\d+): (.*)", getattr(report, "wasxfail", ""))
        if match:
            issue, reason = int(match.group(1)), match.group(2)
            by_issue.setdefault(issue, {}).setdefault(reason, 0)
            by_issue[issue][reason] += 1
    if by_issue:
        total = sum(sum(r.values()) for r in by_issue.values())
        tr.write_sep("-", f"known bugs: {total} tests, {len(by_issue)} open issues")
        for issue in sorted(by_issue):
            for reason, count in by_issue[issue].items():
                tr.write_line(f"Issue #{issue}: {reason} ({count} test{'s' * (count > 1)})")
        tr.write_line("These tests check the correct behavior and fail until the issue is "
                      "fixed. To see why one fails: python3 -m pytest tests --runxfail -k <test name>")

    fixed = [r for r in tr.stats.get("failed", [])
             if "known_bug" in r.keywords and "XPASS(strict)" in str(r.longrepr)]
    if fixed:
        tr.write_sep("-", "known bugs that now pass", yellow=True)
        for report in fixed:
            tr.write_line(report.nodeid)
        tr.write_line("If the bug is fixed, delete the @known_bug line above each test and set "
                      "its row in tests/README.md to ✅.")


@pytest.fixture(autouse=True)
def no_real_recorders(monkeypatch):
    """dvr.py can't start real processes in tests; a test that checks launching gives its own Popen."""
    import subprocess
    import types

    import dvr

    def refuse(*args, **kwargs):
        raise AssertionError("a test tried to start a real recorder process")

    fake = types.SimpleNamespace(DEVNULL=subprocess.DEVNULL, STDOUT=subprocess.STDOUT, Popen=refuse)
    monkeypatch.setattr(dvr, "subprocess", fake)


@pytest.fixture
def replay(tmp_path):
    """
    replay(team, steps) runs a monitor against the steps and returns a ReplayResult.
    replay(team, steps, debug=True) runs it with DEBUG on.
    """
    runs = iter(range(1_000_000))

    def run(team, steps, module=None, debug=False):
        # Each run gets its own event queue and completed-games file
        state_dir = tmp_path / f"replay{next(runs)}"
        state_dir.mkdir()
        return run_replay(team, steps, state_dir, module=module, debug=debug)
    return run


@pytest.fixture
def monitor(tmp_path):
    """monitor(team) loads a monitor with its state files in a temp dir, to change config first."""
    return lambda team: load_script(team, tmp_path)
