# Goal Horn

A Raspberry Pi goal light: when a tracked team scores, a relay turns on a rotating light and a USB speaker plays the team's song.

## How it works

- **`controller.py`** is the only script that touches GPIO and audio. It polls `goal_horn_events.json`, sorts events by priority, and for each one turns the light on, plays the audio, and turns the light off after `LIGHT_DURATION[event]` seconds.
  - `AUDIO` maps event name → mp3 path, `None` for light only, or a list of `(path, duration)` tuples to pick one at random (see `VOLS_ROCKY_TOP`).
  - Unknown events fall back to a 5s light with no audio, so event names must match exactly.
- **`<team>_monitor.py`** scripts each poll a sports API (NHL `api-web.nhle.com`, MLB `statsapi.mlb.com`, ESPN `site.api.espn.com`), detect scores, wait `STREAM_DELAY_SECONDS` to sync with the TV stream, then append `{"event", "priority", "timestamp"}` to the queue. Monitors never touch GPIO or audio.
- Monitors follow the same layout (config block, `queue_event`, API helpers, main loop with a score baseline). New monitors should copy the closest existing one.
- Audio files live in `audio/`. Convert other formats with `ffmpeg -i in.m4a -codec:a libmp3lame -q:a 2 out.mp3`.

## Adding a team

1. Write `<team>_monitor.py`.
2. In `controller.py`, add the team's events to both `AUDIO` and `LIGHT_DURATION`, using the exact event names the monitor queues.
3. In `restart.sh`, add the team's name (the monitor file name without `_monitor.py`) to `ALL`.
4. In `README.md`, add the `@reboot` cron line and the monitor's config variables under Usage.
5. Add the audio to `audio/`.
6. Run `python3 -m pytest tests -k <team>`. Monitors on the NHL, MLB and ESPN football APIs are picked up by the tests automatically; a new API or sport needs its own tests (see `tests/README.md`).

### Team names shared across sports

When a team shares its name with a team in another sport (e.g. the San Francisco Giants and the New York Giants), prefix everything for that team with its city: the monitor file, the event names, the config variables, the audio files, and the log file. For example:

- `sf_giants_monitor.py` → `sf_giants_run`, `SF_GIANTS_TEAM_ID`, `audio/sf_giants_run.mp3`
- `ny_giants_monitor.py` → `ny_giants_touchdown`, `NY_GIANTS_TEAM_ID`, `audio/ny_giants_touchdown.mp3`

Existing files don't follow this yet (`giants_monitor.py` is the SF Giants). Use the prefix for any new team whose name clashes, and don't rename existing files unless asked.

## Light durations

- Set a new song's light duration to its audio length **rounded up**, so the light never turns off while the song is audible. Check length with `ffprobe -v error -show_entries format=duration -of csv=p=0 file.mp3`.
- Exception: songs that fade out can end the light when the audio becomes inaudible. Don't change existing durations unless asked.

## Git and GitHub workflow

- Every change starts from a GitHub issue. Branch from `master` as `feature/issue-N` (new things) or `fix/issue-N` (bugs), where `N` is the issue number.
- **Branch names are a hard requirement.** Never commit or push to a branch with any other name, including names generated or assigned by a tool, harness, or session (e.g. `claude/<random-words>`). If you start on such a branch, create the correct `feature/issue-N` or `fix/issue-N` branch from `master` before your first commit. If you don't know the issue number, ask before committing.
- Commit messages are short, often prefixed `feature:`, `feat:`, `fix:`, or `docs:`.
- PR titles match the issue title, and the body starts with `Closes #N`.
- PRs are **squash merged** (not merge commits or rebase), so each PR lands on `master` as one commit. After a squash merge, start any follow-up work on a new branch from `master`.
- To update a branch with `master`, merge `master` in. Don't rebase or force-push shared branches.

## Testing

- Everything for testing lives in `tests/`; see `tests/README.md`. Keep test code, tools and recorded games there, not in the repo root, and don't add test hooks to the production scripts. The harness patches them from outside.
- Run `pip install -r tests/requirements.txt` once, then `python3 -m pytest tests` before every commit. GitHub Actions runs the same on every PR.
- Monitor tests run each monitor's real `main()` against scripted API responses (`tests/builders.py`) on a fake clock. Add a test for any behavior you change or bug you fix.
- Known bugs have `xfail(strict=True)` tests naming the issue. When a fix makes one pass (`XPASS(strict)`), remove its marker in the same PR. Don't mark a new failure `xfail` to get CI green unless it's a known bug with an issue.
- Recorded games live in `tests/fixtures/` (`record_game.py`, or `rebuild_mlb_game.py` for past MLB games) and are checked by `test_fixtures.py` once `expected_events` is filled in.
- On the Pi, `python3 tests/fire_event.py <event>` sets off the light and audio for any event. Live API behavior is checked in `<team>_monitor.log`.

## Deployment

- The Pi runs from `/home/coledallen/projects/goal_horn` on `master`. Scripts start on boot via `@reboot` cron jobs, and `restart.sh` restarts everything (`./restart.sh rangers vols` restarts only those; `-m` only starts scripts that aren't running).
