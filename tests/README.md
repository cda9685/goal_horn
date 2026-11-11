# Goal Horn Tests

Everything for testing the goal horn lives in this directory. Nothing here changes how the real scripts run on the Pi.

| Tool | What it's for | Runs on |
| --- | --- | --- |
| `fire_event.py` | Set off the light and audio for any event right now | Pi |
| `run_controller.py` | Run the controller without GPIO (and optionally without the speaker) | Laptop, Claude Code |
| `record_game.py` | Save a live game's API responses to a replay file | Pi or laptop |
| `rebuild_mlb_game.py` | Build a replay of a past MLB game, no live recording needed | Anywhere |
| `replay_game.py` | Play a replay file through its monitor in a second or two | Anywhere |
| `pytest` | Automated tests of every monitor and the controller | Anywhere, and on every PR |

## Setup

```sh
pip install -r tests/requirements.txt
```

`RPi.GPIO` is only needed on the Pi. Off the Pi the tests replace it automatically.

## Fire a test event (on the Pi)

With the controller running, write events straight to the queue:

```sh
python3 tests/fire_event.py --list                     # every event, its audio and light duration
python3 tests/fire_event.py vols_touchdown             # one event
python3 tests/fire_event.py rangers_goal yankees_run   # several, played in priority order
```

Use this to check a new song or light duration in seconds. Unknown event names are refused, since the controller would play them as a 5s light with no audio; pass `--force` to send one anyway. If the queue file is owned by root, run it with `sudo`.

## Run the controller off the Pi

```sh
python3 tests/run_controller.py            # prints LIGHT ON / LIGHT OFF and the audio it would play
python3 tests/run_controller.py --audio    # also plays the audio on this computer
python3 tests/run_controller.py --fast     # skips waiting out light durations
```

It reads the same queue as the real controller, so pair it with `fire_event.py` in another terminal. Don't run it on the Pi while the real controller is running, since both would take events from the queue.

## Automated tests

```sh
python3 -m pytest tests          # everything, in about a second
python3 -m pytest tests -k vols  # one team
```

- `test_nhl_monitors.py`, `test_mlb_monitors.py`, `test_espn_monitors.py` run each monitor's real main loop against scripted games: goals, shootouts, touchdowns with PATs, walk-offs, doubleheaders, API errors, restarts mid-game. Each test runs for every team on that API.
- `test_controller.py` checks the light and audio for an event, priority order, and that every event a monitor queues is in `AUDIO` and `LIGHT_DURATION` with an audio file that exists.
- `test_fixtures.py` replays every recorded game in `fixtures/` and checks it fires the expected events.
- `test_record_game.py` checks recordings replay the same as the live run.

GitHub Actions runs these on every pull request (`.github/workflows/tests.yml`).

### Known bugs

Tests marked `xfail(strict=True)` describe the correct behavior for a known bug and are expected to fail until it's fixed. When a fix makes one pass, the run fails with `XPASS(strict)`: remove the marker in the same PR. `python3 -m pytest tests -rx` lists them.

### How it works

`harness.py` loads a monitor without running it, then swaps out its `requests` for a replay that serves responses in order, and its `time` for a fake clock where `sleep()` returns at once but moves the clock forward. The stream delay, poll intervals and the conversion window all run on that clock, so a three-hour game replays in milliseconds with the same timing the real monitor would see. The event queue and `*_completed_games.json` go to a temp folder. When the replay runs out, the monitor stops as if Ctrl+C was pressed, and the test reads the events it queued.

`builders.py` makes responses shaped like the real NHL, MLB and ESPN APIs, so a scripted game reads like:

```python
steps = (nhl.poll(GAME, "LIVE", 0, 0)
         + nhl.poll(GAME, "LIVE", 1, 0)      # goal
         + nhl.poll(GAME, "OFF",  1, 0))
assert replay("rangers", steps).events == ["rangers_goal"]
```

## Recorded games

### Record a live game

Start before the game, stop with Ctrl+C after it ends:

```sh
python3 tests/record_game.py rangers                                    # tests/fixtures/rangers_<date>.json
python3 tests/record_game.py vols -o tests/fixtures/vols_overturned_td.json
```

It runs the monitor against the live API with no stream delay and its own private queue, so it doesn't set the real goal horn off a second time; it's safe to run alongside the real monitor. Responses are trimmed to the fields the monitors read (a few MB per game instead of a few GB) and each distinct response is stored once. If a monitor starts reading a new field, older recordings won't have it: re-record, or record with `--raw` to keep full responses.

### Rebuild a past MLB game

The MLB API keeps every update of a game, so any past MLB game can become a replay without recording it live:

```sh
python3 tests/rebuild_mlb_game.py yankees 823499
```

Find a game's ID (`gamePk`) in the schedule, e.g. `https://statsapi.mlb.com/api/v1/schedule?sportId=1&teamId=147&date=2026-09-10`.

### Replay a game

```sh
python3 tests/replay_game.py tests/fixtures/yankees_2026-09-10_win.json      # events and when they fired
python3 tests/replay_game.py tests/fixtures/yankees_2026-09-10_win.json -v   # with the monitor's log
```

### Add a game to the tests

1. Record or rebuild it into `tests/fixtures/`.
2. Replay it and check the events against what really happened in the game.
3. Fill in `"description"` (what makes the game worth keeping) and `"expected_events"` in the file.

From then on `test_fixtures.py` replays it on every test run. Games worth keeping: overturned goals (#20), double goals (#16), doubleheaders (#5), shootouts, postponed games (#8), and PATs after touchdowns.

### Replay file format

```json
{
  "team": "rangers",
  "description": "Goal overturned for offside, then scored again",
  "recorded": "2026-10-25T19:02:11",
  "expected_events": ["rangers_goal", "rangers_goal"],
  "steps": [
    {"url": "https://api-web.nhle.com/v1/schedule/now", "response": 0},
    {"repeat": 40, "steps": [
      {"url": "https://api-web.nhle.com/v1/schedule/now", "response": 1},
      {"url": "https://api-web.nhle.com/v1/gamecenter/2026020001/landing", "response": 2}
    ]},
    {"url": "https://api-web.nhle.com/v1/schedule/now", "error": "Connection reset"}
  ],
  "responses": [{"gameWeek": []}, "..."]
}
```

Steps are served in order, one per request. A step's `url` must appear in the URL the monitor asks for, so a replay that no longer matches what the monitor does fails loudly. `response` indexes into `responses`; scripted steps can give the body inline as `json` instead. `error` makes the request fail, `status` sets an HTTP status, and `repeat` serves a step or group of steps several times in a row.

## Adding a team

A new monitor is tested automatically: the controller config tests check its events, and the NHL, MLB and ESPN football test files pick up every monitor that calls their API. Run `python3 -m pytest tests -k <team>` to see it covered. A monitor for a new API or sport (e.g. ESPN basketball) needs a builder in `builders.py`, a trimmer in `record_game.py`, and its own test file.
