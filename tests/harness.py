"""
Test harness for the goal horn.

Loads a monitor or the controller off the Pi and runs it against scripted or
recorded API responses, with a fake clock so a full game replays in a fraction
of a second. Nothing here changes how the real scripts run on the Pi.
"""

import importlib.util
import json
import os
import sys
import types
from datetime import timedelta
from pathlib import Path
from unittest.mock import MagicMock

REPO_ROOT   = Path(__file__).resolve().parent.parent
# Monitors may move into monitors/ (#26); look in both places
SEARCH_DIRS = [REPO_ROOT, REPO_ROOT / "monitors"]

# ─── RPi.GPIO ─────────────────────────────────────────────────────────────────

def stub_gpio() -> bool:
    """Replace RPi.GPIO with a MagicMock when it isn't installed. Returns True if stubbed."""
    try:
        import RPi.GPIO  # noqa: F401  # type: ignore
        return False
    except (ImportError, RuntimeError):
        gpio = MagicMock(name="RPi.GPIO")
        rpi  = types.ModuleType("RPi")
        rpi.GPIO = gpio
        sys.modules["RPi"]      = rpi
        sys.modules["RPi.GPIO"] = gpio
        return True

# ─── Known Bugs ───────────────────────────────────────────────────────────────

def known_bug(issue: int, reason: str):
    """
    Mark a test as describing the correct behavior for an open bug, e.g.

        @known_bug(20, "overturned goal hides the next goal")
        def test_goal_after_overturned_goal(...):

    The test fails until the issue is fixed, and that failure is expected: the
    run stays green and lists it under "known bugs". Once the fix works the
    test passes, and the run fails to remind you to delete this line (and set
    the test's row in tests/README.md to ✅). The test itself doesn't change.
    """
    def mark(test):
        for m in known_bug_marks(issue, reason):
            test = m(test)
        return test
    return mark


def known_bug_marks(issue: int, reason: str) -> list:
    """
    known_bug for one case of a parametrized test:

        pytest.param("vols", marks=known_bug_marks(36, "a blank score is read as 0"))
    """
    import pytest   # Here, not at the top: the tools in tests/ run without pytest
    return [pytest.mark.known_bug(issue=issue, reason=reason),
            pytest.mark.xfail(strict=True, reason=f"Issue #{issue}: {reason}")]

# ─── Loading Scripts ──────────────────────────────────────────────────────────

def script_path(name: str) -> Path:
    """Find a script by name: "controller", "rangers", "rangers_monitor" or "rangers_monitor.py"."""
    name = name.removesuffix(".py")
    if name != "controller" and not name.endswith("_monitor"):
        name += "_monitor"
    for d in SEARCH_DIRS:
        path = d / f"{name}.py"
        if path.exists():
            return path
    raise FileNotFoundError(f"No script named {name}.py in {[str(d) for d in SEARCH_DIRS]}")


def all_monitors() -> list[str]:
    """Team names of every monitor in the repo, e.g. ["dolphins", "giants", ...]."""
    names = set()
    for d in SEARCH_DIRS:
        names.update(p.name.removesuffix("_monitor.py") for p in d.glob("*_monitor.py"))
    return sorted(names)


def monitors_using(api_host: str) -> list[str]:
    """Team names of every monitor whose source calls api_host, e.g. "api-web.nhle.com"."""
    return [team for team in all_monitors() if api_host in script_path(team).read_text()]


def load_script(name: str, state_dir: Path | None = None) -> types.ModuleType:
    """
    Import a fresh copy of a script without running main().
    If state_dir is given, the event queue and completed-games files are moved
    there so tests never touch the real files on the Pi.
    """
    stub_gpio()
    path   = script_path(name)
    spec   = importlib.util.spec_from_file_location(f"under_test_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    if state_dir is not None:
        state_dir = Path(state_dir)
        module.EVENT_FILE = str(state_dir / "goal_horn_events.json")
        if hasattr(module, "COMPLETED_GAMES_FILE"):
            module.COMPLETED_GAMES_FILE = str(
                state_dir / os.path.basename(module.COMPLETED_GAMES_FILE))
    return module


def team_id(module: types.ModuleType):
    """The monitor's <TEAM>_TEAM_ID value."""
    ids = [v for k, v in vars(module).items() if k.endswith("_TEAM_ID")]
    if len(ids) != 1:
        raise ValueError(f"Expected one *_TEAM_ID in {module.__file__}, found {len(ids)}")
    return ids[0]

# ─── Fake Clock ───────────────────────────────────────────────────────────────

class FakeClock:
    """Stands in for the time module: sleep() advances the clock instantly."""

    def __init__(self, start: float = 1_700_000_000.0):
        self.now    = start
        self.start  = start
        self.sleeps = []            # Every sleep duration, in order

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float):
        self.sleeps.append(seconds)
        self.now += seconds

    def elapsed(self) -> float:
        return self.now - self.start

    def __getattr__(self, name):
        # Anything else (strftime, monotonic, ...) comes from the real time module
        import time
        return getattr(time, name)

# ─── Replays ──────────────────────────────────────────────────────────────────

class ReplayFinished(KeyboardInterrupt):
    """Raised when the replay runs out. Monitors catch KeyboardInterrupt and exit cleanly."""


class FakeResponse:
    """Stands in for requests.Response. Add any attribute the monitors start reading."""

    def __init__(self, data, status_code: int = 200, url: str = "", text: str | None = None):
        self._data       = data
        self.status_code = status_code
        self.url         = url
        self.elapsed     = timedelta(0)     # Replayed responses arrive instantly
        self.text        = text             # Set for a body that isn't JSON

    def json(self):
        if self.text is not None:
            raise ValueError(f"Response body is not JSON: {self.text[:40]!r} (replayed)")
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"{self.status_code} (replayed)")


def expand_steps(steps: list) -> list:
    """Expand {"repeat": n} steps and {"repeat": n, "steps": [...]} groups into n copies."""
    out = []
    for step in steps:
        if "steps" in step:
            body = expand_steps(step["steps"])
        else:
            body = [{k: v for k, v in step.items() if k != "repeat"}]
        out.extend(body * step.get("repeat", 1))
    return out


def compress_steps(steps: list, max_group: int = 3) -> list:
    """Collapse back-to-back repeats of 1 to max_group steps into repeat groups."""
    out, i = [], 0
    while i < len(steps):
        best_len, best_count = 1, 1
        for length in range(1, max_group + 1):
            block, count = steps[i:i + length], 1
            while steps[i + count * length:i + (count + 1) * length] == block:
                count += 1
            if count > 1 and count * length > best_count * best_len:
                best_len, best_count = length, count
        block = steps[i:i + best_len]
        if best_count == 1:
            out.append(block[0])
        elif best_len == 1:
            out.append({**block[0], "repeat": best_count})
        else:
            out.append({"repeat": best_count, "steps": block})
        i += best_len * best_count
    return out


class Replay:
    """
    Serves API responses in order. Each step is a dict:
        {"url": "<substring of the requested URL>", "json": <response body>}
    Optional keys: "status" (HTTP status, default 200), "error" (raise a
    connection error instead of responding), "text" (a body that isn't JSON,
    e.g. an HTML error page), "repeat" (serve it n times in a row).
    {"repeat": n, "steps": [...]} serves a group of steps n times in a row.
    """

    def __init__(self, steps: list):
        self.steps    = expand_steps(steps)
        self.index    = 0
        self.requests = []          # Every URL requested, in order
        self.options  = []          # The keyword arguments of each request (timeout=...)
        self.mismatch = None        # Set if the monitor asked for a URL the replay didn't expect

    def get(self, url: str, *args, **kwargs):
        if self.index >= len(self.steps):
            raise ReplayFinished()
        self.requests.append(url)
        self.options.append(kwargs)
        step = self.steps[self.index]
        self.index += 1

        if step["url"] not in url:
            # Stop the monitor rather than raise an error it would catch as a failed request
            self.mismatch = (f"Replay step {self.index - 1}: monitor requested {url!r}, "
                             f"but the replay expected a URL containing {step['url']!r}")
            raise ReplayFinished()
        if step.get("error"):
            import requests
            raise requests.ConnectionError(f"{step['error']} (replayed)")
        return FakeResponse(step.get("json"), step.get("status", 200), url, step.get("text"))


def save_fixture(path, team: str, description: str, recorded: str, steps: list,
                 expected_events: list | None = None):
    """
    Write steps to a replay file (see load_fixture). Each distinct response is
    stored once in "responses", and repeated steps are collapsed.
    """
    responses, index, out = [], {}, []
    for step in steps:
        step = dict(step)
        if "json" in step:
            key = json.dumps(step["json"], sort_keys=True)
            if key not in index:
                index[key] = len(responses)
                responses.append(step["json"])
            step["response"] = index[key]
            del step["json"]
        out.append(step)
    fixture = {"team": team, "description": description, "recorded": recorded,
               "expected_events": expected_events, "steps": compress_steps(out),
               "responses": responses}
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w") as f:
        json.dump(fixture, f, indent=1)


def polls_for_gap(seconds: float, poll_interval: float, max_gap: float = 600) -> int:
    """
    How many identical polls stand for `seconds` of real time between two
    changes in a rebuilt game, so the monitor's fake clock moves about as far
    as it would have live. Gaps over max_gap are shortened: past a few
    minutes, extra waiting doesn't change what any monitor does.
    """
    return max(1, round(min(seconds, max_gap) / poll_interval))


def load_fixture(path) -> dict:
    """
    Load a replay file: {"team", "description", "expected_events", "steps",
    "responses"}. Recorded steps hold {"response": i}, an index into
    "responses"; these are swapped for the response itself. A recording's
    log (.partial.jsonl, see Journal) loads the same way.
    """
    if str(path).endswith(".jsonl"):
        fixture = read_journal(path)
    else:
        with open(path) as f:
            fixture = json.load(f)
    responses = fixture.get("responses", [])
    fixture["steps"] = [{**s, "json": responses[s["response"]]} if "response" in s else s
                        for s in expand_steps(fixture["steps"])]
    return fixture

# ─── Recording Logs ───────────────────────────────────────────────────────────
# While recording, nothing already written is ever rewritten: each new
# response and each step is added to the end of a log, one JSON object per
# line. That keeps writes to the Pi's SD card to about the recording's final
# size, and a power cut can only damage the last line, which read_journal()
# skips. When the recording ends the log becomes a normal replay file.

class Journal:
    """An append-only recording log. Lines are {"header"}, {"response", "json"} or {"step"}."""

    SYNC_INTERVAL = 30          # Seconds between forcing new lines onto the card

    def __init__(self, path, header: dict):
        self.path      = str(path)
        self.index     = {}     # Serialized response -> its number
        self.steps     = 0
        self.last_sync = 0.0
        resuming = os.path.exists(self.path)
        if resuming:
            # Carry on an interrupted recording: learn which responses it already has
            for line in _journal_lines(self.path):
                if "response" in line and "json" in line:
                    self.index[json.dumps(line["json"], sort_keys=True)] = line["response"]
                elif "step" in line:
                    self.steps += 1
        self.file = open(self.path, "a")
        if not resuming:
            self._write({"header": header})

    def add(self, step: dict):
        """Add one step; a "json" response is written once and referred to by number."""
        step = dict(step)
        if "json" in step:
            data = step.pop("json")
            key  = json.dumps(data, sort_keys=True)
            if key not in self.index:
                self.index[key] = len(self.index)
                self._write({"response": self.index[key], "json": data})
            step["response"] = self.index[key]
        self._write({"step": step})
        self.steps += 1

    def _write(self, line: dict):
        self.file.write(json.dumps(line) + "\n")
        self.file.flush()
        import time
        if time.monotonic() - self.last_sync >= self.SYNC_INTERVAL:
            os.fsync(self.file.fileno())
            self.last_sync = time.monotonic()

    def close(self):
        if not self.file.closed:
            self.file.flush()
            os.fsync(self.file.fileno())
            self.file.close()


def _journal_lines(path):
    """Each line of a log as a dict, skipping a damaged last line."""
    with open(path) as f:
        for line in f:
            try:
                yield json.loads(line)
            except ValueError:
                continue                # Half-written by a power cut or a crash


def read_journal(path) -> dict:
    """A recording log as a replay file's contents (steps still refer to responses)."""
    fixture, responses, steps = {}, {}, []
    for line in _journal_lines(path):
        if "header" in line:
            fixture = dict(line["header"])
        elif "response" in line and "json" in line:
            responses[line["response"]] = line["json"]
        elif "step" in line:
            steps.append(line["step"])
    # A step whose response line was lost can't be replayed: stop there
    for i, step in enumerate(steps):
        if "response" in step and step["response"] not in responses:
            steps = steps[:i]
            break
    fixture["responses"] = [responses.get(i) for i in range(max(responses, default=-1) + 1)]
    fixture["steps"]     = steps
    return fixture


def finish_journal(path, output) -> int:
    """Turn a recording log into a replay file at output, then delete the log. Returns the step count."""
    fixture   = read_journal(path)
    responses = fixture["responses"]
    steps = [{**{k: v for k, v in s.items() if k != "response"}, "json": responses[s["response"]]}
             if "response" in s else s for s in fixture["steps"]]
    tmp = str(output) + ".tmp"
    save_fixture(tmp, fixture.get("team", ""), fixture.get("description", ""),
                 fixture.get("recorded", ""), steps, fixture.get("expected_events"))
    os.replace(tmp, output)         # Never leave a half-written replay file
    os.remove(path)
    return len(steps)

# ─── Running a Monitor ────────────────────────────────────────────────────────

class ReplayResult:
    def __init__(self, module, clock: FakeClock, replay: Replay):
        self.module = module
        self.clock  = clock
        self.replay = replay
        events = []
        self.queue_readable = True
        if os.path.exists(module.EVENT_FILE):
            try:
                with open(module.EVENT_FILE) as f:
                    events = json.load(f)
            except ValueError:
                self.queue_readable = False     # Left corrupted; no events can be read
        self.queued = events        # Full event dicts as written to the queue

    @property
    def events(self) -> list[str]:
        """Event names in the order they were queued."""
        return [e["event"] for e in self.queued]

    def event_times(self) -> list[tuple[str, float]]:
        """(event, seconds since the replay started) for each queued event."""
        return [(e["event"], e["timestamp"] - self.clock.start) for e in self.queued]


def run_replay(team: str, steps: list, state_dir, module=None) -> ReplayResult:
    """
    Run a monitor's main loop against a replay until the replay runs out.
    Pass a module from load_script() to change its config first; otherwise one
    is loaded with its state files in state_dir.
    """
    if module is None:
        module = load_script(team, state_dir)
    clock  = FakeClock()
    replay = Replay(steps)

    module.time     = clock
    module.requests = _requests_with(replay.get)
    module.main()

    if replay.mismatch:
        raise AssertionError(replay.mismatch)
    if replay.index < len(replay.steps):
        raise AssertionError(
            f"Monitor stopped after {replay.index} of {len(replay.steps)} replay steps")
    return ReplayResult(module, clock, replay)


def _requests_with(get):
    """A stand-in for the requests module whose get() is replaced."""
    import requests
    fake = types.SimpleNamespace(**{k: getattr(requests, k) for k in dir(requests)
                                    if not k.startswith("_")})
    fake.get = get
    return fake

# ─── Running the Controller ───────────────────────────────────────────────────

class FakeLight:
    """Stands in for RPi.GPIO: records the light turning on and off."""

    BCM, OUT, HIGH, LOW = "BCM", "OUT", 1, 0

    def __init__(self, clock: FakeClock | None = None, log=None):
        self.clock   = clock
        self.log     = log          # Called with "LIGHT ON"/"LIGHT OFF" if given
        self.actions = []           # ("on"/"off", seconds since start)

    def output(self, pin, value):
        state = "on" if value else "off"
        at    = self.clock.elapsed() if self.clock else 0
        if not self.actions or self.actions[-1][0] != state:
            self.actions.append((state, at))
            if self.log:
                self.log(f"[GPIO] LIGHT {state.upper()} (pin {pin})")

    def setmode(self, mode):
        pass

    def setup(self, pin, mode, initial=0):
        self.output(pin, initial)

    def cleanup(self):
        pass


def load_controller(state_dir=None, clock: FakeClock | None = None, log=None):
    """
    Load controller.py with a FakeLight in place of GPIO. With a clock, sleeps
    are instant. play_audio is left alone; replace it to skip audio.
    """
    module = load_script("controller", state_dir)
    module.GPIO = FakeLight(clock, log)
    if clock is not None:
        module.time = clock
    return module
