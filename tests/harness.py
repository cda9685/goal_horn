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
    def __init__(self, data, status_code: int = 200):
        self._data       = data
        self.status_code = status_code

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"{self.status_code} (replayed)")


def expand_steps(steps: list) -> list:
    """Expand {"repeat": n} steps and {"repeat": n, "steps": [...]} groups into n copies."""
    out = []
    for step in steps:
        body = expand_steps(step["steps"]) if "steps" in step else [step]
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
    connection error instead of responding), "repeat" (serve it n times in a row).
    {"repeat": n, "steps": [...]} serves a group of steps n times in a row.
    """

    def __init__(self, steps: list):
        self.steps    = expand_steps(steps)
        self.index    = 0
        self.requests = []          # Every URL requested, in order

    def get(self, url: str, *args, **kwargs):
        if self.index >= len(self.steps):
            raise ReplayFinished()
        self.requests.append(url)
        step = self.steps[self.index]
        self.index += 1

        if step["url"] not in url:
            raise AssertionError(
                f"Replay step {self.index - 1}: monitor requested {url!r}, "
                f"but the replay expected a URL containing {step['url']!r}")
        if step.get("error"):
            import requests
            raise requests.ConnectionError(f"{step['error']} (replayed)")
        return FakeResponse(step.get("json"), step.get("status", 200))


def load_fixture(path) -> dict:
    """
    Load a replay file: {"team", "description", "expected_events", "steps",
    "responses"}. Recorded steps hold {"response": i}, an index into
    "responses"; these are swapped for the response itself.
    """
    with open(path) as f:
        fixture = json.load(f)
    responses = fixture.get("responses", [])
    fixture["steps"] = [{**s, "json": responses[s["response"]]} if "response" in s else s
                        for s in expand_steps(fixture["steps"])]
    return fixture

# ─── Running a Monitor ────────────────────────────────────────────────────────

class ReplayResult:
    def __init__(self, module, clock: FakeClock, replay: Replay):
        self.module = module
        self.clock  = clock
        self.replay = replay
        events = []
        if os.path.exists(module.EVENT_FILE):
            with open(module.EVENT_FILE) as f:
                events = json.load(f)
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
