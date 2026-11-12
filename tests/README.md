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
- `test_record_game.py` checks recordings replay the same as the live run.
- `test_docs.py` checks the test case table below matches the tests.

Every test is listed in [Test cases](#test-cases).

GitHub Actions runs these on every pull request (`.github/workflows/tests.yml`), on the pytest and requests versions Raspberry Pi OS Bookworm and Trixie ship, and on the latest ones.

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

**Status:** ✅ passes, or ❌ known bug: the test describes the correct behavior and fails until the issue is fixed. When the run says `XPASS(strict)` for one, the bug is fixed: remove its `xfail` marker and change it to ✅ here.

`test_docs.py` fails if a test is missing from this table, a row names a test that doesn't exist, or a row's status doesn't match the test's `xfail` marker.

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
| `test_fixtures.py` | `test_fixture` | Positive | Recorded games | Each recorded game in `fixtures/` fires its expected events | ✅ |
| `test_record_game.py` | `test_record_and_replay_nhl` | Tooling | Rangers | A recording replays to the same events and stores repeats once | ✅ |
| `test_record_game.py` | `test_trimmed_mlb_replays_like_the_original` | Tooling | Yankees | Trimmed MLB responses replay exactly like the full ones | ✅ |
| `test_record_game.py` | `test_espn_keeps_only_the_teams_game` | Tooling | Vols | Recordings keep only the team's game from the scoreboard | ✅ |
| `test_record_game.py` | `test_raw_keeps_full_responses` | Tooling | Vols | `--raw` keeps full responses | ✅ |
| `test_docs.py` | `test_test_case_table_lists_every_test` | Tooling | Tests | This table lists every test, and nothing else | ✅ |
| `test_docs.py` | `test_test_case_table_status_matches_xfail` | Tooling | Tests | Each row's ❌ / ✅ and issue number match the test's `xfail` marker | ✅ |
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
| Issue #20: the next score after an overturn is missed | Open | `test_goal_after_overturned_goal` ❌, `test_run_after_overturned_run` ❌, `test_touchdown_after_overturned_touchdown`, `test_score_glitch_does_not_double_fire` (Football) ❌ |
| Issue #25: restarting `giants` also stops `ny_giants` | Fixed | `test_restart_giants_leaves_ny_giants_running`, `test_missing_only_starts_giants_when_only_ny_giants_runs` |
| Issue #26: events lost when the queue is written at the same moment | Open | `test_two_monitors_queueing_at_once_keep_both_events` ❌, `test_event_queued_while_controller_clears_is_kept` ❌ |
| Issue #27: some monitors have no win event | Open | `test_nhl_win` ❌, `test_vols_win` ❌ |
| Issue #33: a failed request mid-game misses scores | Open | `test_goal_during_schedule_api_error` ❌, `test_run_during_schedule_api_error` ❌, `test_score_during_api_error` ❌ |
| Issue #34: no MLB win when the feed goes straight to Final | Open | `test_win_when_feed_jumps_to_final` ❌, the Yankees recorded game |
| Issue #36: a blank ESPN score fires a false touchdown | Open | `test_blank_score_is_not_a_score` ❌ |
| Issue #37: unexpected API data crashes a monitor | Open | `test_empty_body_does_not_crash` ❌, `test_empty_game_data_does_not_crash` ❌, `test_null_score_does_not_crash` ❌ |
| Issue #38: a corrupted queue file loses every later event | Open | `test_monitor_recovers_from_corrupted_queue` ❌, `test_controller_recovers_from_corrupted_queue` ❌ |
| Commits `aebe461`, `af4fd3c`: the light keeps going off after a Yankees win | Fixed | `test_win_fires_once`, `test_lead_after_early_inning_is_not_a_win` |

When you fix or file a bug, add a test for it and a row here.

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
