#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
pid_file="${MOCKFASTAPI_PID_FILE:-$root/mockfastapi.linux.pid}"
if [[ ! -f "$pid_file" ]]; then
    echo "No PID file at $pid_file; nothing to stop."
    exit 0
fi

read -r pid start_ticks < "$pid_file"
if [[ ! -r "/proc/$pid/stat" ]]; then
    rm -- "$pid_file"
    echo "Process $pid is gone; stale PID file removed."
    exit 0
fi
if [[ "$(awk '{print $22}' "/proc/$pid/stat")" != "$start_ticks" ]] ||
   [[ "$(readlink -f "/proc/$pid/cwd")" != "$root" ]]; then
    echo "PID $pid no longer identifies this MockFastAPI process; no process stopped." >&2
    exit 1
fi

kill -TERM "$pid"
for _ in {1..100}; do
    state="$(awk '{print $3}' "/proc/$pid/stat" 2>/dev/null || true)"
    if [[ -z "$state" || "$state" == Z ]]; then
        break
    fi
    sleep 0.1
done
state="$(awk '{print $3}' "/proc/$pid/stat" 2>/dev/null || true)"
if [[ -n "$state" && "$state" != Z ]]; then
    echo "Process $pid did not exit after SIGTERM; PID file retained." >&2
    exit 1
fi
rm -- "$pid_file"
echo "MockFastAPI stopped: PID=$pid"
