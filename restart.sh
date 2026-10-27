#!/bin/bash
# Restart the controller and monitors.
#
# Usage: ./restart.sh [-m] [-d] [name ...]
#   (no names)   act on the controller and every monitor
#   name ...     act only on these, e.g. ./restart.sh rangers ny_giants
#   -m           only start scripts that aren't running; leave running ones alone
#   -d, --debug  start monitors with --debug so they print [DEBUG] lines to their logs
#                (restarting without it, or rebooting, turns debug back off)

DIR=/home/coledallen/projects/goal_horn
ALL="controller rangers yankees giants panthers vols dolphins ny_giants"

usage() {
    echo "Usage: $0 [-m] [-d] [name ...]"
    echo "  -m    only start scripts that aren't running"
    echo "  -d    start monitors in debug mode (--debug)"
    echo "  names: $ALL"
}

MISSING_ONLY=0
DEBUG_ARGS=()
NAMES=()
for arg in "$@"; do
    case "$arg" in
        -m|--missing) MISSING_ONLY=1 ;;
        -d|--debug)   DEBUG_ARGS=(--debug) ;;
        -h|--help)    usage; exit 0 ;;
        -*)           echo "Unknown flag: $arg"; usage; exit 1 ;;
        *)            NAMES+=("$arg") ;;
    esac
done
[ ${#NAMES[@]} -eq 0 ] && NAMES=($ALL)

# Validate names (accept "rangers", "rangers_monitor" or "rangers_monitor.py")
SELECTED=()
for name in "${NAMES[@]}"; do
    name="${name%.py}"
    name="${name%_monitor}"
    if [[ " $ALL " != *" $name "* ]]; then
        echo "Unknown script: $name"; usage; exit 1
    fi
    SELECTED+=("$name")
done

script_for() {
    if [ "$1" = "controller" ]; then echo "controller"; else echo "$1_monitor"; fi
}

# Match on "/<script>.py" so giants_monitor.py doesn't also match ny_giants_monitor.py
is_running() {
    pgrep -f "/$(script_for "$1")\.py" > /dev/null
}

start() {
    local script
    script=$(script_for "$1")
    if [ "$1" = "controller" ]; then
        sudo python3 -u "$DIR/$script.py" >> "$DIR/$script.log" 2>&1 &
    else
        python3 -u "$DIR/$script.py" "${DEBUG_ARGS[@]}" >> "$DIR/$script.log" 2>&1 &
    fi
    echo "Started $script.py${DEBUG_ARGS:+ (debug)}"
}

TO_START=()
for name in "${SELECTED[@]}"; do
    if is_running "$name"; then
        if [ $MISSING_ONLY -eq 1 ]; then
            echo "$(script_for "$name").py already running"
            continue
        fi
        sudo pkill -f "/$(script_for "$name")\.py"
    fi
    TO_START+=("$name")
done

[ ${#TO_START[@]} -eq 0 ] && { echo "Nothing to start."; exit 0; }

sleep 2
for name in "${TO_START[@]}"; do
    start "$name"
done
echo "Done."
