# Goal Horn Tests

Everything for testing the goal horn lives in this directory. Nothing here changes how the real scripts run on the Pi.

| Tool | What it's for | Runs on |
| --- | --- | --- |
| `fire_event.py` | Set off the light and audio for any event right now | Pi |
| `run_controller.py` | Run the controller without GPIO (and optionally without the speaker) | Laptop, Claude Code |
| `record_game.py` | Save a live game's API responses to a replay file | Pi or laptop |
| `dvr.py` | Schedule recordings of upcoming games ahead of time, like a DVR | Pi |
| `rebuild_mlb_game.py`, `rebuild_nhl_game.py`, `rebuild_espn_game.py` | Build a replay of a past game from the API's history, no live recording needed | Anywhere |
| `replay_game.py` | Play a replay file through its monitor in a second or two | Anywhere |
| `pytest` | Automated tests of every monitor and the controller | Anywhere, and on every PR |

## Setup

The tests need `pytest` and `requests`.

**On the Pi** (Raspberry Pi OS), install pytest from Raspberry Pi OS's own packages. `requests` is already there for the monitors.

```sh
sudo apt install python3-pytest
```

Raspberry Pi OS refuses `pip install` into the system Python (`error: externally-managed-environment`), so use `apt` instead. Don't get around it with `--break-system-packages`: it can break the Python packages the goal horn itself runs on.

Running the tests on the Pi is safe while the goal horn is running. Tests use their own temporary event queue, and `test_restart.py` uses fake `sudo`, `pkill` and `python3` commands, so nothing real is stopped, started or set off.

**On a laptop or desktop**, use a virtual environment (many systems, like the Pi, refuse a system-wide `pip install`):

```sh
python3 -m venv .venv
.venv/bin/pip install -r tests/requirements.txt
.venv/bin/python -m pytest tests
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
- `test_all_monitors.py` has checks that apply to every monitor, and `test_adversarial.py` feeds them broken data: bad responses, blank scores, a corrupted queue.
- `test_restart.py` runs `restart.sh` against fake process tools, so nothing is really stopped or started.
- `test_controller.py` checks the light and audio for an event, priority order, and that every event a monitor queues is in `AUDIO` and `LIGHT_DURATION` with an audio file that exists.
- `test_fixtures.py` replays every recorded game in `fixtures/` and checks it fires the expected events.
- `test_debug.py` checks debug mode (`DEBUG = True` or `--debug`) for every monitor, as described below.
- `test_record_game.py` checks recordings replay the same as the live run, including what the debug lines log.
- `test_docs.py` checks the test case table below matches the tests.

Every test is listed in [Test cases](#test-cases).

GitHub Actions runs these on every pull request (`.github/workflows/tests.yml`), on the pytest and requests versions Raspberry Pi OS Bookworm and Trixie ship, and on the latest ones.

### Debug mode

Debug lines only print what the monitor read from the API, so a replay shows them exactly as a live game would. `test_debug.py` runs one scripted game per API through every monitor and checks that:

- With debug off, nothing starts with `[DEBUG]` (keeping the logs small is the point of the flag).
- With debug on, the same events fire, and no request turns into an `[API ERROR]`. The API helpers catch every exception, so a mistake in a debug line would look like a failed request and silently drop scores.
- The lines for the situations debug mode is for show up: API calls and response times, the queue size, overturned scores, doubleheader skips, the PAT conversion window, and "no game" checks. Tests look for key phrases, not exact wording, so rewording a message doesn't break them.
- No debug line prints `None`. That means a line reads a field the response doesn't have. When a monitor starts logging a new field, add it to the responses in `builders.py` and to the trimmers in `record_game.py`. `test_record_game.py` fails if the trimmers drop a field a debug line logs.

Every recorded game in `fixtures/` is also replayed with debug on. The `--debug` command-line flag and `./restart.sh -d` aren't tested, since they only run when the script is started directly; check those on the Pi.

### Known bugs

Some tests are for bugs that are filed but not fixed yet. Each is marked with the issue it belongs to:

```python
@known_bug(20, "overturned goal hides the next goal")
def test_goal_after_overturned_goal(team, nhl, replay):
```

The test checks the **correct** behavior, so it fails until the issue is fixed. That failure doesn't turn the run red: pytest counts it as `xfailed`, and the end of every run lists the known bugs by issue:

```
--------------------- known bugs: 55 tests, 9 open issues ----------------------
Issue #20: overturned goal hides the next goal (2 tests)
Issue #33: a failed API request resets the baseline (7 tests)
...
```

Keeping them in the run means a new failure always stands out, and every open bug has a test ready to prove its fix.

To see why one fails, run it with `--runxfail`, which runs it like a normal test. That shows what was expected, what happened, and everything the monitor printed:

```sh
python3 -m pytest tests -rx                                   # one line per known-bug test, with its issue
python3 -m pytest tests --runxfail -k overturned_goal         # the full failure
python3 -m pytest tests -m known_bug                          # only the known bugs
python3 -m pytest tests -m "not known_bug"                    # everything else
python3 -m pytest tests -rx > test_results.log 2>&1           # save the results to a file
```

**When a bug is fixed**, its tests start passing and the run fails, listing them under "known bugs that now pass". Delete the `@known_bug` line above each one and set its row in [Test cases](#test-cases) to ✅. The test itself doesn't change.

**When filing a bug**, add a test for the correct behavior with `@known_bug(<issue number>, "<what's wrong>")`, and a row in the table. Don't use pytest's `xfail` directly; `test_docs.py` rejects it.

### How it works

`harness.py` loads a monitor without running it, then swaps out its `requests` for a replay that serves responses in order, and its `time` for a fake clock where `sleep()` returns at once but moves the clock forward. The stream delay, poll intervals and the conversion window all run on that clock, so a three-hour game replays in milliseconds with the same timing the real monitor would see. The event queue and `*_completed_games.json` go to a temp folder. When the replay runs out, the monitor stops as if Ctrl+C was pressed, and the test reads the events it queued.

`builders.py` makes responses shaped like the real NHL, MLB and ESPN APIs, so a scripted game reads like:

```python
steps = (nhl.poll(GAME, "LIVE", 0, 0)
         + nhl.poll(GAME, "LIVE", 1, 0)      # goal
         + nhl.poll(GAME, "OFF",  1, 0))
assert replay("rangers", steps).events == ["rangers_goal"]
```

## Test cases

Every test has a name, and with its file that name is how you run it on its own:

```sh
python3 -m pytest "tests/test_nhl_monitors.py::test_shootout_goals"            # for every NHL team
python3 -m pytest "tests/test_nhl_monitors.py::test_shootout_goals[rangers]"   # Rangers only
```

"Team" always means the monitor's own team, the one the goal horn is for. "Opponent" is the team it's playing. "Plays away" means the team is the away side of the game; the horn still goes off for its scores.

**Types**

- **Positive:** something that should set the horn off does.
- **Negative:** something that should not set the horn off doesn't.
- **Boundary:** the edges where bugs live: timing windows, several scores at once, restarts, one game ending and the next starting.
- **Adversarial:** broken or unexpected data: failed requests, bad responses, a corrupted queue file.
- **Config:** the settings, files and scripts agree with each other.
- **Tooling:** the test tools themselves work.

**Status:** ✅ passes, or ❌ known bug: the test has `@known_bug` and fails until the issue is fixed (see [Known bugs](#known-bugs)). When the run lists one under "known bugs that now pass", delete its `@known_bug` line and change it to ✅ here.

`test_docs.py` fails if a test is missing from this table, a row names a test that doesn't exist, or a row's status doesn't match the test's `@known_bug`.

<!-- test-cases:start -->
| File | Test | Type | Runs for | What it checks | Status |
| --- | --- | --- | --- | --- | --- |
| `test_nhl_monitors.py` | `test_no_game_idles` | Negative | NHL | No game today: nothing fires, checks every `IDLE_INTERVAL` | ✅ |
| `test_nhl_monitors.py` | `test_upcoming_game_idles` | Negative | NHL | A game that hasn't started (FUT, PRE): nothing fires, idle checks | ✅ |
| `test_nhl_monitors.py` | `test_goal_fires_after_stream_delay` | Positive | NHL | A team goal fires one `<team>_goal`, after the stream delay | ✅ |
| `test_nhl_monitors.py` | `test_goal_when_team_plays_away` | Positive | NHL | A team goal fires when the team is the away side | ✅ |
| `test_nhl_monitors.py` | `test_opponent_goal_does_nothing` | Negative | NHL | An opponent goal fires nothing | ✅ |
| `test_nhl_monitors.py` | `test_first_poll_sets_baseline` | Boundary | NHL | Started mid-game at 3-0: the old goals don't fire | ✅ |
| `test_nhl_monitors.py` | `test_two_goals_between_polls` | Boundary | NHL | 2 goals between checks fire 2 lights | ✅ |
| `test_nhl_monitors.py` | `test_full_game` | Positive | NHL | A whole game, PRE to OFF: 2 team goals fire 2 lights, the opponent goal none | ✅ |
| `test_nhl_monitors.py` | `test_score_glitch_does_not_double_fire` | Boundary | NHL | The score blips down one goal and back: no extra light (Issue #16) | ✅ |
| `test_nhl_monitors.py` | `test_goal_fires_once_across_state_changes` | Boundary | NHL | One goal fires once while the game goes LIVE → CRIT → OFF (Issue #16) | ✅ |
| `test_nhl_monitors.py` | `test_shootout_goals` | Positive | NHL | Each team shootout goal fires `<team>_shootout`; saves and opponent goals don't | ✅ |
| `test_nhl_monitors.py` | `test_new_game_resets_baseline` | Boundary | NHL | A new game ID starts the count over | ✅ |
| `test_nhl_monitors.py` | `test_game_data_error_is_retried` | Adversarial | NHL | A failed game-data request is retried; the next goal still fires | ✅ |
| `test_nhl_monitors.py` | `test_goal_after_overturned_goal` | Boundary | NHL | A goal overturned on review, then a real goal: the real goal fires | ❌ Issue #20 |
| `test_nhl_monitors.py` | `test_goal_during_schedule_api_error` | Adversarial | NHL | A goal scored while a schedule request fails still fires | ❌ Issue #33 |
| `test_nhl_monitors.py` | `test_postponed_game_idles` | Negative | NHL | A postponed game (PPD) idles instead of checking the API nonstop | ❌ Issue #8 |
| `test_nhl_monitors.py` | `test_nhl_win` | Positive | NHL | A win fires `<team>_win` at the final | ❌ Issue #27 |
| `test_mlb_monitors.py` | `test_no_game_idles` | Negative | MLB | No game today: nothing fires, idle checks | ✅ |
| `test_mlb_monitors.py` | `test_run_fires_after_stream_delay` | Positive | MLB | A team run fires one `<team>_run`, after the stream delay | ✅ |
| `test_mlb_monitors.py` | `test_home_run` | Positive | MLB | A team home run fires `<team>_home_run` | ✅ |
| `test_mlb_monitors.py` | `test_home_run_seen_one_play_late` | Boundary | MLB | The next at-bat has started before the score updates: still a home run (Issue #2) | ✅ |
| `test_mlb_monitors.py` | `test_multiple_runs_on_one_play_fire_once` | Boundary | MLB | 3 runs on one play fire 1 light (Issue #1) | ✅ |
| `test_mlb_monitors.py` | `test_run_when_team_plays_away` | Positive | MLB | A team run fires when the team is the away side | ✅ |
| `test_mlb_monitors.py` | `test_opponent_run_does_nothing` | Negative | MLB | An opponent home run fires nothing | ✅ |
| `test_mlb_monitors.py` | `test_first_poll_sets_baseline` | Boundary | MLB | Started mid-game at 4-0: the old runs don't fire | ✅ |
| `test_mlb_monitors.py` | `test_win_when_team_plays_home` | Positive | MLB | Ahead after the top of the 9th at home: `<team>_win` fires once | ✅ |
| `test_mlb_monitors.py` | `test_win_when_team_plays_away` | Positive | MLB | Ahead after the bottom of the 9th on the road: `<team>_win` fires | ✅ |
| `test_mlb_monitors.py` | `test_walk_off` | Positive | MLB | A walk-off home run fires the home run, then the win | ✅ |
| `test_mlb_monitors.py` | `test_loss_does_not_fire_win` | Negative | MLB | A loss fires no win | ✅ |
| `test_mlb_monitors.py` | `test_doubleheader` | Boundary | MLB | Game 1 ends, game 2 still fires; game 1 is saved as finished (Issue #5) | ✅ |
| `test_mlb_monitors.py` | `test_restart_after_final_is_quiet` | Boundary | MLB | Started after a final: no runs or win fire, and the game is skipped after | ✅ |
| `test_mlb_monitors.py` | `test_game_data_error_is_retried` | Adversarial | MLB | A failed game-data request is retried; the next run still fires | ✅ |
| `test_mlb_monitors.py` | `test_run_after_overturned_run` | Boundary | MLB | A run taken off, then a real run: the real run fires | ❌ Issue #20 |
| `test_mlb_monitors.py` | `test_run_during_schedule_api_error` | Adversarial | MLB | A run scored while a schedule request fails still fires | ❌ Issue #33 |
| `test_mlb_monitors.py` | `test_win_fires_once` | Boundary | MLB | 10 checks after the last out fire the win once (commits `aebe461`, `af4fd3c`) | ✅ |
| `test_mlb_monitors.py` | `test_lead_after_early_inning_is_not_a_win` | Negative | MLB | Leading after 3 outs in the 5th or 8th is not a win (commit `af4fd3c`) | ✅ |
| `test_mlb_monitors.py` | `test_extra_innings_win` | Boundary | MLB | A win in the 10th fires | ✅ |
| `test_mlb_monitors.py` | `test_doubleheader_after_restart` | Boundary | MLB | Restarted between games of a doubleheader: game 1 stays skipped, game 2 fires (Issue #5) | ✅ |
| `test_mlb_monitors.py` | `test_completed_games_are_forgotten_after_two_days` | Boundary | MLB | A finished game is skipped at 1.9 days and forgotten at 2.1 days (Issue #5) | ✅ |
| `test_mlb_monitors.py` | `test_postponed_game_moves_on` | Negative | MLB | A postponed game (reported as Final) fires nothing and is skipped after (Issue #8) | ✅ |
| `test_mlb_monitors.py` | `test_win_when_feed_jumps_to_final` | Boundary | MLB | The feed goes from 2 outs straight to Final: the win still fires | ❌ Issue #34 |
| `test_espn_monitors.py` | `test_no_game_idles` | Negative | Football | No game this week: nothing fires, idle checks | ✅ |
| `test_espn_monitors.py` | `test_not_playing_idles` | Negative | Football | Scheduled, postponed and canceled games idle (Issue #8) | ✅ |
| `test_espn_monitors.py` | `test_touchdown_then_extra_point` | Positive | Football | A touchdown then its PAT fire one `<team>_touchdown`, after the stream delay | ✅ |
| `test_espn_monitors.py` | `test_touchdown_and_extra_point_in_one_poll` | Boundary | Football | A touchdown and PAT seen together (+7) fire one touchdown | ✅ |
| `test_espn_monitors.py` | `test_two_point_conversion` | Boundary | Football | A touchdown then a 2-point conversion fire one touchdown | ✅ |
| `test_espn_monitors.py` | `test_field_goal` | Positive | Football | A field goal fires `<team>_score` | ✅ |
| `test_espn_monitors.py` | `test_field_goal_right_after_touchdown` | Boundary | Football | A missed PAT, then a field goal inside the PAT window: still a score | ✅ |
| `test_espn_monitors.py` | `test_safety_long_after_touchdown` | Boundary | Football | A safety just after the PAT window ends counts as a score | ✅ |
| `test_espn_monitors.py` | `test_opponent_score_does_nothing` | Negative | Football | An opponent touchdown fires nothing | ✅ |
| `test_espn_monitors.py` | `test_touchdown_when_team_plays_away` | Positive | Football | A team touchdown fires when the team is the away side | ✅ |
| `test_espn_monitors.py` | `test_first_poll_sets_baseline` | Boundary | Football | Started mid-game at 21-0: the old scores don't fire | ✅ |
| `test_espn_monitors.py` | `test_touchdown_after_overturned_touchdown` | Boundary | Football | A touchdown overturned, then scored again: both fire (Issue #20) | ✅ |
| `test_espn_monitors.py` | `test_nfl_win` | Positive | NFL | A win fires `<team>_win` at the final | ✅ |
| `test_espn_monitors.py` | `test_nfl_loss_does_not_fire_win` | Negative | NFL | A loss fires no win | ✅ |
| `test_espn_monitors.py` | `test_nfl_restart_after_final_is_quiet` | Boundary | NFL | Started after a final: no win fires | ✅ |
| `test_espn_monitors.py` | `test_score_during_api_error` | Adversarial | Football | A score made while a request fails still fires | ❌ Issue #33 |
| `test_espn_monitors.py` | `test_score_glitch_does_not_double_fire` | Boundary | Football | The score blips 7 → 0 → 7 for one check: no second touchdown | ❌ Issue #20 |
| `test_espn_monitors.py` | `test_vols_win` | Positive | Vols | A Vols win fires `vols_win` | ❌ Issue #27 |
| `test_all_monitors.py` | `test_every_request_has_a_timeout` | Config | All | Every API request has a timeout, so one can't hang forever (Issue #4) | ✅ |
| `test_all_monitors.py` | `test_two_monitors_queueing_at_once_keep_both_events` | Adversarial | Rangers + Yankees | Two monitors writing the queue at the same moment keep both events | ❌ Issue #26 |
| `test_adversarial.py` | `test_html_error_page_does_not_crash` | Adversarial | All | A 200 response with an HTML page instead of JSON doesn't crash the monitor | ✅ |
| `test_adversarial.py` | `test_server_error_on_game_data_is_retried` | Adversarial | NHL, MLB | A 500 on game data is retried; the next score still fires | ✅ |
| `test_adversarial.py` | `test_empty_body_does_not_crash` | Adversarial | All | A 200 response with an empty (`null`) body doesn't crash the monitor | ❌ Issue #37 |
| `test_adversarial.py` | `test_empty_game_data_does_not_crash` | Adversarial | NHL, MLB | Empty game data doesn't crash the monitor | ❌ Issue #37 |
| `test_adversarial.py` | `test_null_score_does_not_crash` | Adversarial | NHL, MLB | A `null` score for one check doesn't crash the monitor | ❌ Issue #37 |
| `test_adversarial.py` | `test_blank_score_is_not_a_score` | Adversarial | Football | A blank, `null` or `--` score for one check fires no false touchdown | ❌ Issue #36 |
| `test_adversarial.py` | `test_other_teams_games_are_ignored` | Adversarial | All | Other teams' games, listed first and scoring, fire nothing | ✅ |
| `test_adversarial.py` | `test_monitor_recovers_from_corrupted_queue` | Adversarial | All | A half-written queue file (power cut) doesn't lose later events | ❌ Issue #38 |
| `test_adversarial.py` | `test_controller_recovers_from_corrupted_queue` | Adversarial | Controller | The controller resets a half-written queue file | ❌ Issue #38 |
| `test_controller.py` | `test_monitor_events_are_configured` | Config | All | Every event a monitor queues is in `AUDIO` and `LIGHT_DURATION` | ✅ |
| `test_controller.py` | `test_every_light_duration_has_audio_entry` | Config | Controller | Every `LIGHT_DURATION` event is also in `AUDIO` | ✅ |
| `test_controller.py` | `test_audio_files_exist` | Config | Controller | Every mp3 in `AUDIO` exists in `audio/` | ✅ |
| `test_controller.py` | `test_events_are_prefixed_with_their_team` | Config | All | Each monitor's events start with its team name | ✅ |
| `test_controller.py` | `test_event_turns_light_on_plays_audio_then_off` | Positive | Controller | Light on, song plays, light off after the event's duration | ✅ |
| `test_controller.py` | `test_light_only_event` | Positive | Controller | An event with no audio turns the light on for its duration | ✅ |
| `test_controller.py` | `test_unknown_event_falls_back_to_short_light` | Boundary | Controller | An unknown event gets a 5s light and no audio | ✅ |
| `test_controller.py` | `test_random_version_uses_its_own_duration` | Positive | Controller | A song picked at random (Vols) uses its own light duration | ✅ |
| `test_controller.py` | `test_main_plays_queue_in_priority_order` | Positive | Controller | Queued events play in priority order and the queue is cleared | ✅ |
| `test_controller.py` | `test_event_queued_while_controller_clears_is_kept` | Adversarial | Controller | An event written while the controller clears the queue still plays | ❌ Issue #26 |
| `test_restart.py` | `test_all_lists_the_controller_and_every_monitor` | Config | All | `ALL` in `restart.sh` lists the controller and every monitor | ✅ |
| `test_restart.py` | `test_restart_giants_leaves_ny_giants_running` | Boundary | `restart.sh` | Restarting `giants` doesn't stop `ny_giants` (Issue #25) | ✅ |
| `test_restart.py` | `test_missing_only_starts_giants_when_only_ny_giants_runs` | Boundary | `restart.sh` | With `-m`, a running `ny_giants` doesn't make `giants` look running (Issue #25) | ✅ |
| `test_restart.py` | `test_restart_everything` | Positive | `restart.sh` | No names restarts the controller and every monitor | ✅ |
| `test_restart.py` | `test_accepts_any_form_of_a_name` | Positive | `restart.sh` | `rangers`, `rangers_monitor` and `rangers_monitor.py` all work | ✅ |
| `test_restart.py` | `test_unknown_name_or_flag_changes_nothing` | Negative | `restart.sh` | An unknown name or flag prints usage and stops or starts nothing | ✅ |
| `test_restart.py` | `test_debug_flag_starts_monitors_in_debug_mode` | Positive | `restart.sh` | `-d` starts monitors with `--debug`, and the controller without it (Issue #28) | ✅ |
| `test_debug.py` | `test_debug_off_prints_no_debug_lines` | Negative | All | With debug off, a whole game prints no `[DEBUG]` lines | ✅ |
| `test_debug.py` | `test_debug_on_fires_the_same_events` | Boundary | All | With debug on, the same events fire and no request turns into an API error | ✅ |
| `test_debug.py` | `test_debug_lines_show_api_calls_and_queue` | Positive | All | Debug lines show each request with its response time, and the queue size | ✅ |
| `test_debug.py` | `test_debug_lines_have_no_missing_fields` | Config | All | No debug line prints `None` (a field the response doesn't have) | ✅ |
| `test_debug.py` | `test_nhl_overturned_goal_is_logged` | Positive | NHL | An overturned goal is logged ("goals went down 1 -> 0") | ✅ |
| `test_debug.py` | `test_nhl_no_game_is_logged` | Positive | NHL | "No game" checks are logged | ✅ |
| `test_debug.py` | `test_mlb_run_taken_off_is_logged` | Positive | MLB | A run taken off is logged ("runs went down 2 -> 1") | ✅ |
| `test_debug.py` | `test_mlb_doubleheader_skip_is_logged` | Positive | MLB | Skipping a finished doubleheader game is logged | ✅ |
| `test_debug.py` | `test_espn_conversion_window_is_logged` | Positive | Football | A PAT logs how long after the touchdown it came, and the window | ✅ |
| `test_debug.py` | `test_espn_not_on_scoreboard_is_logged` | Positive | Football | "Not on scoreboard" checks are logged | ✅ |
| `test_fixtures.py` | `test_fixture` | Positive | Recorded games | Each recorded or rebuilt game in `fixtures/` fires its expected events, with debug off and on | ✅ |
| `test_fixtures.py` | `test_fixture_variation` | Boundary | Recorded games | Each game in `fixtures/` with a glitch, blank score, failed request or overturn added still fires the right events | ❌ Issue #20, Issue #33, Issue #36, Issue #37 (some cases) |
| `test_record_game.py` | `test_record_and_replay_nhl` | Tooling | Rangers | A recording replays to the same events and stores repeats once | ✅ |
| `test_record_game.py` | `test_trimmed_mlb_replays_like_the_original` | Tooling | Yankees | Trimmed MLB responses replay exactly like the full ones | ✅ |
| `test_record_game.py` | `test_espn_keeps_only_the_teams_game` | Tooling | Vols | Recordings keep only the team's game from the scoreboard | ✅ |
| `test_record_game.py` | `test_raw_keeps_full_responses` | Tooling | Vols | `--raw` keeps full responses | ✅ |
| `test_record_game.py` | `test_recording_keeps_what_debug_lines_read` | Tooling | All | A recording keeps every field the debug lines log | ✅ |
| `test_rebuild.py` | `test_saved_repeats_replay_once` | Tooling | Tests | A step repeated in a replay file plays the right number of times | ✅ |
| `test_rebuild.py` | `test_replay_that_doesnt_match_the_monitor_fails` | Tooling | Tests | A replay the monitor asks different URLs of fails the test, though the monitor catches the error | ✅ |
| `test_rebuild.py` | `test_nhl_goals_and_shootout` | Tooling | Rangers | A rebuilt NHL game fires its goals and shootout goals, not the opponent's | ✅ |
| `test_rebuild.py` | `test_nhl_real_time_is_estimated_from_the_game_clock` | Tooling | Rangers | Goals 10 game minutes apart replay about 10 real minutes apart (19, shortened to the 10-minute cap) | ✅ |
| `test_rebuild.py` | `test_nhl_goal_before_period_start` | Tooling | Rangers | A goal before any period-start play still fires | ✅ |
| `test_rebuild.py` | `test_espn_touchdown_and_extra_point_are_split` | Tooling | Dolphins | A touchdown shown as +7 is rebuilt as +6, then the extra point | ✅ |
| `test_rebuild.py` | `test_espn_two_point_conversion_and_missed_extra_point` | Tooling | Dolphins | +8 and +6 touchdowns and a field goal rebuild to the right events | ✅ |
| `test_rebuild.py` | `test_espn_plays_are_put_in_time_order` | Tooling | Vols | Plays listed out of order are sorted by time, so a score doesn't fire twice | ✅ |
| `test_rebuild.py` | `test_espn_replay_timing_matches_live` | Tooling | Dolphins | The stream delay isn't counted twice: a 2-point try 160s after a touchdown stays in the conversion window | ✅ |
| `test_rebuild.py` | `test_espn_league_comes_from_the_monitor` | Tooling | Football | NFL and college monitors rebuild from the right league | ✅ |
| `test_tools.py` | `test_fire_event_queues_events` | Positive | `fire_event.py` | Named events are queued with the given priority | ✅ |
| `test_tools.py` | `test_fire_event_adds_to_events_already_queued` | Positive | `fire_event.py` | Events already in the queue are kept | ✅ |
| `test_tools.py` | `test_fire_event_refuses_unknown_events` | Negative | `fire_event.py` | A misspelled event is refused and nothing is queued | ✅ |
| `test_tools.py` | `test_fire_event_force_sends_unknown_events` | Positive | `fire_event.py` | `--force` queues an event the controller doesn't know | ✅ |
| `test_tools.py` | `test_fire_event_list_shows_every_event` | Positive | `fire_event.py` | `--list` shows every configured event | ✅ |
| `test_tools.py` | `test_fired_events_play_on_the_controller` | Positive | `fire_event.py`, controller | A fired event is played by the controller: light, song, light off | ✅ |
| `test_tools.py` | `test_run_controller_fast_clock_skips_only_light_durations` | Tooling | `run_controller.py` | `--fast` skips light durations but still waits between queue checks | ✅ |
| `test_tools.py` | `test_run_controller_finds_a_player_or_none` | Tooling | `run_controller.py` | `--audio` uses a player it finds, or skips audio when there's none | ✅ |
| `test_dvr.py` | `test_recording_log_only_ever_grows` | Tooling | `record_game.py` | While recording, the log is only ever added to, never rewritten (spares the SD card) | ✅ |
| `test_dvr.py` | `test_recording_log_survives_a_power_cut` | Adversarial | `record_game.py` | A log cut off mid-line by a power cut still loads, losing only the last line | ✅ |
| `test_dvr.py` | `test_recording_carries_on_after_a_restart` | Boundary | `record_game.py` | Restarting the recorder with the same output carries on the interrupted recording | ✅ |
| `test_dvr.py` | `test_finish_saves_a_crashed_recording` | Tooling | `record_game.py` | `--finish` turns a leftover log into a replay file | ✅ |
| `test_dvr.py` | `test_stops_after_nhl_final` | Positive | `record_game.py` | `--stop-after-final` stops a few checks after an NHL game ends | ✅ |
| `test_dvr.py` | `test_stops_after_mlb_final` | Positive | `record_game.py` | `--stop-after-final` stops a few checks after an MLB game ends | ✅ |
| `test_dvr.py` | `test_stops_after_football_final` | Positive | `record_game.py` | `--stop-after-final` stops a few checks after a football game ends | ✅ |
| `test_dvr.py` | `test_stops_when_the_game_is_postponed` | Boundary | `record_game.py` | A postponed game (NHL, football) stops the recording too | ✅ |
| `test_dvr.py` | `test_game_picks_which_final_stops_it` | Boundary | `record_game.py` | With `--game`, a doubleheader's first game ending doesn't stop a recording of the second | ✅ |
| `test_dvr.py` | `test_without_stop_after_final_it_keeps_going` | Negative | `record_game.py` | Without `--stop-after-final`, the recorder keeps going after the final | ✅ |
| `test_dvr.py` | `test_nhl_upcoming_games` | Positive | `schedules.py` | An NHL team's upcoming games: finished and far-off games left out, soonest first, opponent right | ✅ |
| `test_dvr.py` | `test_mlb_upcoming_games` | Positive | `schedules.py` | An MLB team's upcoming games, with the start time and opponent | ✅ |
| `test_dvr.py` | `test_football_upcoming_games_include_one_under_way` | Boundary | `schedules.py` | A football game already under way can still be picked | ✅ |
| `test_dvr.py` | `test_schedule_times_are_read_in_any_api_format` | Tooling | `schedules.py` | Start times in each API's format are read the same | ✅ |
| `test_dvr.py` | `test_scheduling_a_game_names_its_recording` | Positive | `dvr.py` | A scheduled game gets a file named by team, date and opponent; scheduling it twice is refused | ✅ |
| `test_dvr.py` | `test_recording_starts_at_lead_time` | Boundary | `dvr.py` | Recording starts 30 minutes before the game, not a minute sooner | ✅ |
| `test_dvr.py` | `test_recording_missed_if_the_service_was_off` | Negative | `dvr.py` | A game the service was off for is marked missed | ✅ |
| `test_dvr.py` | `test_finished_recording_is_done_or_failed` | Positive | `dvr.py` | A finished recording is marked done, or failed if it saved nothing | ✅ |
| `test_dvr.py` | `test_recording_stopped_early_carries_on` | Adversarial | `dvr.py` | A recording cut off mid-game (e.g. a reboot) is started again and carries on | ✅ |
| `test_dvr.py` | `test_recording_stopped_for_good_is_saved_as_interrupted` | Adversarial | `dvr.py` | A recording cut off and never resumed is saved and marked interrupted | ✅ |
| `test_dvr.py` | `test_running_recording_is_left_alone` | Negative | `dvr.py` | A recording still running isn't touched | ✅ |
| `test_dvr.py` | `test_service_starts_the_recorder_for_the_game` | Positive | `dvr.py` | The service runs the recorder for that game, stopping after the final | ✅ |
| `test_dvr.py` | `test_picking_games_schedules_them` | Positive | `dvr.py` | Picking a game by number schedules it | ✅ |
| `test_dvr.py` | `test_pick_all_and_cancel` | Positive | `dvr.py` | `--pick all` schedules every game; `--cancel` cancels one | ✅ |
| `test_dvr.py` | `test_picking_nothing_schedules_nothing` | Negative | `dvr.py` | Picking nothing schedules nothing and writes no schedule file | ✅ |
| `test_dvr.py` | `test_picking_a_number_not_listed_is_refused` | Negative | `dvr.py` | A number that isn't in the list is refused | ✅ |
| `test_docs.py` | `test_test_case_table_lists_every_test` | Tooling | Tests | This table lists every test, and nothing else | ✅ |
| `test_docs.py` | `test_test_case_table_status_matches_known_bug` | Tooling | Tests | Each row's ❌ / ✅ and issue number match the test's `@known_bug` | ✅ |
<!-- test-cases:end -->

"Runs for": NHL = Rangers, Panthers. MLB = Yankees, Giants. Football = Vols, Dolphins, NY Giants. NFL = Dolphins, NY Giants. All = every monitor. New monitors on these APIs are added automatically.

### Bugs covered

Every bug filed as an issue, plus bugs fixed in commits without one, has a test so it can't come back unnoticed:

| Bug | State | Tests |
| --- | --- | --- |
| Issue #1: multiple runs on one play fire several lights | Fixed | `test_multiple_runs_on_one_play_fire_once` |
| Issue #2: a home run sometimes plays the run sound | Fixed | `test_home_run_seen_one_play_late` |
| Issue #4: API calls stall after a replay review | Fixed | `test_every_request_has_a_timeout` |
| Issue #5: the second game of a doubleheader never fires | Fixed | `test_doubleheader`, `test_doubleheader_after_restart`, `test_completed_games_are_forgotten_after_two_days` |
| Issue #8: postponed games are checked every few seconds | Open (NHL) | `test_postponed_game_idles` ❌, `test_not_playing_idles`, `test_postponed_game_moves_on` |
| Issue #16: a goal sometimes plays twice | Open, cause unknown | `test_score_glitch_does_not_double_fire` (NHL), `test_goal_fires_once_across_state_changes` |
| Issue #20: the next score after an overturn is missed | Open | `test_goal_after_overturned_goal` ❌, `test_run_after_overturned_run` ❌, `test_touchdown_after_overturned_touchdown`, `test_score_glitch_does_not_double_fire` (Football) ❌, `test_fixture_variation` (some cases) ❌ |
| Issue #25: restarting `giants` also stops `ny_giants` | Fixed | `test_restart_giants_leaves_ny_giants_running`, `test_missing_only_starts_giants_when_only_ny_giants_runs` |
| Issue #26: events lost when the queue is written at the same moment | Open | `test_two_monitors_queueing_at_once_keep_both_events` ❌, `test_event_queued_while_controller_clears_is_kept` ❌ |
| Issue #27: some monitors have no win event | Open | `test_nhl_win` ❌, `test_vols_win` ❌ |
| Issue #33: a failed request mid-game misses scores | Open | `test_goal_during_schedule_api_error` ❌, `test_run_during_schedule_api_error` ❌, `test_score_during_api_error` ❌, `test_fixture_variation` (some cases) ❌ |
| Issue #34: no MLB win when the feed goes straight to Final | Open | `test_win_when_feed_jumps_to_final` ❌, the Yankees recorded game |
| Issue #36: a blank ESPN score fires a false touchdown | Open | `test_blank_score_is_not_a_score` ❌, `test_fixture_variation` (some cases) ❌ |
| Issue #37: unexpected API data crashes a monitor | Open | `test_empty_body_does_not_crash` ❌, `test_empty_game_data_does_not_crash` ❌, `test_null_score_does_not_crash` ❌, `test_fixture_variation` (some cases) ❌ |
| Issue #38: a corrupted queue file loses every later event | Open | `test_monitor_recovers_from_corrupted_queue` ❌, `test_controller_recovers_from_corrupted_queue` ❌ |
| Issue #39: the NHL API rate-limits requests (429 Too Many Requests) | Open | `test_fixture` and `test_fixture_variation` with `rangers_2026-11-11_cgy_live` (two real 429s; nothing is missed there, but Issue #33 shows what one at the wrong moment does) |
| Commits `aebe461`, `af4fd3c`: the light keeps going off after a Yankees win | Fixed | `test_win_fires_once`, `test_lead_after_early_inning_is_not_a_win` |
| Test tools: a repeated step in a replay file played back squared (5 → 25) | Fixed | `test_saved_repeats_replay_once` |
| Test tools: a replay that didn't match the monitor's requests didn't fail, because the monitor caught the error | Fixed | `test_replay_that_doesnt_match_the_monitor_fails`, and every replay in the suite |
| Test tools: `rebuild_mlb_game.py` added game data after the final, which the monitor never asks for | Fixed | `test_fixture` (the Yankees game) |
| Test tools: `rebuild_nhl_game.py` crashed, or missed the first goal, when a game had no period-start play | Fixed | `test_nhl_goal_before_period_start` |
| Test tools: rebuilt football games counted the stream delay twice after each score, so timing drifted 30s per score | Fixed | `test_espn_replay_timing_matches_live` |
| Test tools: `dvr.py` read and wrote the real `tests/recordings.json` even when told to use another file | Fixed | the `dvr.py` tests, and `conftest.py` fails any run that leaves a new file in the project |

When you fix or file a bug, add a test for it and a row here.

## Recorded games

### Record a live game

Start before the game. Stop with Ctrl+C after it ends, or let `--stop-after-final` stop it:

```sh
python3 tests/record_game.py rangers                                    # tests/fixtures/rangers_<date>.json
python3 tests/record_game.py rangers --stop-after-final                 # stops a few checks after the final
python3 tests/record_game.py vols -o tests/fixtures/vols_overturned_td.json
```

It runs the monitor against the live API with no stream delay and its own private queue, so it doesn't set the real goal horn off a second time; it's safe to run alongside the real monitor.

- **Trimmed responses.** Responses are trimmed to the fields the monitors read, and each distinct response is stored once.
- **`--raw` keeps full responses:** every field the API sends, for looking into how the API reports something, or for a field a monitor doesn't read yet. It's about 30 times bigger (an NHL game reaches megabytes in minutes), so it's not for the Pi.
- **Stopping by itself.** With `--stop-after-final`, the recorder stops a few checks after the game is over, postponed or canceled. `--game <ID>` says which game counts (e.g. the second game of a doubleheader); without it, it's the first game that goes live. `--max-hours` (default 8) stops it no matter what.

**Saving without wearing out the SD card.** While recording, each new response and each step is added to the end of a log, `<output>.partial.jsonl`, one line at a time. Nothing already written is ever rewritten, so the card is written about as much as the recording's final size (around 1MB for a hockey game, 10MB for baseball). New lines are forced onto the card every 30 seconds. When the recording stops, the log is turned into the replay file once and deleted.

**After a crash or power cut.** The log is still there, missing at most its last few seconds. A half-written last line is skipped. Then either:

- Run the same command again (same `-o`) during the game to carry on where it left off.
- Save what was recorded as it is: `python3 tests/record_game.py --finish tests/fixtures/<name>.partial.jsonl`.

`replay_game.py` can also play a `.partial.jsonl` log directly.

### Schedule recordings (DVR)

`dvr.py` lists a team's upcoming games and records the ones you pick, like a DVR:

```
$ python3 tests/dvr.py rangers
Upcoming rangers games:
   1) Fri Nov 13  9:00 PM   NYR @ VAN
   2) Mon Nov 16  7:30 PM   MTL @ NYR
   ...
Record which? (numbers like 1,3, "all", or Enter to cancel): 1
Scheduled: Fri Nov 13  9:00 PM NYR @ VAN -> tests/fixtures/rangers_2026-11-13_van.json
```

```sh
python3 tests/dvr.py rangers --pick 1,3    # pick without being asked
python3 tests/dvr.py vols --pick all       # every game in the next 30 days
python3 tests/dvr.py rangers --days 60     # look further ahead
python3 tests/dvr.py --scheduled           # what's scheduled, recording, done, missed...
python3 tests/dvr.py --cancel 2            # cancel one (stops it, keeping what's recorded, if it's under way)
```

Games come from the same API the team's monitor uses, and times are shown in the Pi's timezone. The schedule is kept in `tests/recordings.json` (not committed).

**The DVR service makes the recordings.** It has to be running. It's light: it checks the schedule once a minute and otherwise sleeps. Each recording costs about as much as one more monitor. Start it now, and at every boot with a line in `crontab -e` next to the monitors' `@reboot` lines:

```sh
python3 -u tests/dvr.py --run >> dvr.log 2>&1 &
```

```
@reboot python3 -u /home/coledallen/projects/goal_horn/tests/dvr.py --run >> /home/coledallen/projects/goal_horn/dvr.log 2>&1
```

For each scheduled game, the service:

- **Starts** `record_game.py --game <ID> --stop-after-final` 30 minutes before the game, and the recorder stops itself after the final. Each recording's output goes to a `.log` next to its replay file.
- **Carries on after a reboot mid-game:** the recording continues where it left off. If the game is over by then, what was recorded is saved and marked `interrupted`.
- **Marks a game `missed`** when the service wasn't running at any point in the 8 hours after its start.

When a recording is `done`, replay it, check its events against the real game's scoring, and fill in `expected_events` (see [Add a game to the tests](#add-a-game-to-the-tests)).

### Rebuild a past game

Every API keeps finished games, so any past game can become a replay without recording it live:

```sh
python3 tests/rebuild_mlb_game.py yankees 823499       # MLB
python3 tests/rebuild_nhl_game.py rangers 2026010045   # NHL
python3 tests/rebuild_espn_game.py dolphins 401873015  # NFL and college football
```

Where to find a game's ID:

| API | Schedule with game IDs | ID |
| --- | --- | --- |
| MLB | `https://statsapi.mlb.com/api/v1/schedule?sportId=1&teamId=147&date=2026-09-10` | `gamePk` |
| NHL | `https://api-web.nhle.com/v1/club-schedule-season/NYR/now` | `id` |
| ESPN | `https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/15/schedule` (college: `.../college-football/teams/2633/schedule`) | `id` |

The APIs keep different kinds of history, so rebuilt games differ:

| API | What it keeps | The rebuilt replay |
| --- | --- | --- |
| MLB | A snapshot of the live game at every update (`feed/live/timestamps`) | Exactly what the monitor would have seen, update by update |
| NHL | Every play (goals, shootout attempts, period starts and ends) with the game clock | One poll per change. Real time is estimated: a 20-minute period takes about 38 minutes (measured in a live game), plus intermissions |
| ESPN | Every play with the real time it happened and the score after it | One poll per score change, spaced by the real times. ESPN's play list isn't always in time order, so it's sorted first |

Gaps longer than 10 minutes are shortened, since extra waiting doesn't change anything a monitor does.

### What rebuilt games can't show

A rebuilt game only has what the API kept, which leaves out the rare cases that cause bugs:

| Missing from the history | How the tests cover it |
| --- | --- |
| Overturned scores: the NHL and ESPN histories only keep scores that stood | Scripted tests, and the `overturn` variation |
| API glitches, blank scores, failed requests | Scripted and adversarial tests, and the `glitch`, `blank_score`, `request_error` and `game_data_error` variations |
| A touchdown and its extra point or 2-point try as separate updates: ESPN's plays give the score after the try (+7 or +8) | The rebuild splits them: +6, then the try a minute later, as the live scoreboard shows them |
| Real time between NHL plays: only the game clock is kept | Estimated at 1.9 real seconds per game second, measured from a live recording (1.75 to 2.0). No NHL logic depends on how much time passes between goals |

**Variations.** `test_fixture_variation` takes every recorded and rebuilt game and adds one of these to it (see `variations.py`). The monitor must still fire the game's expected events:

- `glitch`: once the team has scored, its score drops by one for a single poll, then comes back.
- `blank_score`: the same, but the score is blank (football) or `null` (NHL, MLB).
- `request_error`: the first request of a poll fails, just before the team's first score.
- `game_data_error`: the same, for the game-data request (NHL and MLB; ESPN has only one request).
- `overturn`: the team's last score shows for 3 polls, comes off for 3, then comes back. That counts as scored again, so its event fires a second time.

So every real game also tests the rare cases. A new fixture gets all of them automatically.

**Checking the simulations against reality.** `record_game.py` during a live game is still worth running when something rare happens, like an overturned goal. That shows how the API really reports it: whether the score drops right away, and for how long. Compare it with the variation, and adjust `variations.py` if they differ.

### Replay a game

```sh
python3 tests/replay_game.py tests/fixtures/yankees_2026-09-10_win.json      # events and when they fired
python3 tests/replay_game.py tests/fixtures/yankees_2026-09-10_win.json -v   # with the monitor's log
python3 tests/replay_game.py tests/fixtures/yankees_2026-09-10_win.json -v -d   # in debug mode, with [DEBUG] lines
```

### Add a game to the tests

1. Record it or rebuild it into `tests/fixtures/`.
2. Replay it and check the events against what really happened in the game.
3. Fill in `"description"` (what makes the game worth keeping) and `"expected_events"` in the file.

From then on `test_fixtures.py` replays it on every test run, as it happened and with each variation. Games worth keeping: overturned goals (Issue #20), double goals (Issue #16), doubleheaders (Issue #5), shootouts, postponed games (Issue #8), missed extra points and 2-point tries, and ties.

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
