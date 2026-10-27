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

### Team names shared across sports

When a team shares its name with a team in another sport (e.g. the San Francisco Giants and the New York Giants), prefix everything for that team with its city: the monitor file, the event names, the config variables, the audio files, and the log file. For example:

- `sf_giants_monitor.py` → `sf_giants_run`, `SF_GIANTS_TEAM_ID`, `audio/sf_giants_run.mp3`
- `ny_giants_monitor.py` → `ny_giants_touchdown`, `NY_GIANTS_TEAM_ID`, `audio/ny_giants_touchdown.mp3`

Existing files don't follow this yet (`giants_monitor.py` is the SF Giants). Use the prefix for any new team whose name clashes, and don't rename existing files unless asked.

## Light durations

- Set a new song's light duration to its audio length **rounded up**, so the light never turns off while the song is audible. Check length with `ffprobe -v error -show_entries format=duration -of csv=p=0 file.mp3`.
- Exception: songs that fade out can end the light when the audio becomes inaudible. Don't change existing durations unless asked.

## Git and GitHub workflow

- Every change starts from a GitHub issue. Branch from `master` as `feature/issue-N` (new things) or `fix/issue-N` (bugs).
- Commit messages are short, often prefixed `feature:`, `feat:`, `fix:`, or `docs:`.
- PR titles match the issue title, and the body starts with `Closes #N`.
- PRs are **squash merged** (not merge commits or rebase), so each PR lands on `master` as one commit. After a squash merge, start any follow-up work on a new branch from `master`.
- To update a branch with `master`, merge `master` in. Don't rebase or force-push shared branches.

## Testing

- There's no test suite. `RPi.GPIO` only exists on the Pi, so off the Pi, test by stubbing it (`sys.modules['RPi.GPIO'] = MagicMock()`) and replacing `play_audio` and `time.sleep`.
- Monitor logic can be tested by replacing the API helper with a scripted sequence of scores.
- Live API behavior is checked on the Pi in `<team>_monitor.log`.

## Deployment

- The Pi runs from `/home/coledallen/projects/goal_horn` on `master`. Scripts start on boot via `@reboot` cron jobs, and `restart.sh` restarts everything (`./restart.sh rangers vols` restarts only those; `-m` only starts scripts that aren't running; `-d` starts monitors with `--debug`).
