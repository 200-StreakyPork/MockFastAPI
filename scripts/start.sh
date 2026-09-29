#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
python="$root/.venv/bin/python"
port="${MOCKFASTAPI_PORT:-8000}"
pid_file="${MOCKFASTAPI_PID_FILE:-$root/mockfastapi.linux.pid}"
stdout="$root/mockfastapi.linux.stdout.log"
stderr="$root/mockfastapi.linux.stderr.log"

if [[ ! -x "$python" ]]; then
    echo "Python not found at $python. Run uv sync on Linux first." >&2
    exit 1
fi

if [[ -f "$pid_file" ]]; then
    read -r saved_pid saved_start < "$pid_file"
    if [[ -r "/proc/$saved_pid/stat" ]] &&
       [[ "$(awk '{print $22}' "/proc/$saved_pid/stat")" == "$saved_start" ]] &&
       [[ "$(readlink -f "/proc/$saved_pid/cwd")" == "$root" ]]; then
        echo "MockFastAPI is already running as PID $saved_pid. Run scripts/stop.sh first." >&2
        exit 1
    fi
    rm -- "$pid_file"
fi

if ! "$python" -c 'import socket,sys; s=socket.socket(); s.bind(("127.0.0.1", int(sys.argv[1]))); s.close()' "$port" \
    >/dev/null 2>&1; then
    echo "Port $port is already in use." >&2
    exit 1
fi

cd "$root"
nohup "$python" -m uvicorn mockfastapi.app:create_app --factory --host 127.0.0.1 --port "$port" \
    >"$stdout" 2>"$stderr" </dev/null &
pid=$!
ready=0
for _ in {1..100}; do
    state="$(awk '{print $3}' "/proc/$pid/stat" 2>/dev/null || true)"
    if ! kill -0 "$pid" 2>/dev/null || [[ -z "$state" || "$state" == Z ]]; then
        break
    fi
    if "$python" -c 'import socket,sys; s=socket.socket(); s.settimeout(.2); result=s.connect_ex(("127.0.0.1", int(sys.argv[1]))); s.close(); sys.exit(0 if result == 0 else 1)' "$port" \
        >/dev/null 2>&1; then
        ready=1
        break
    fi
    sleep 0.1
done
if [[ "$ready" -ne 1 ]]; then
    kill -TERM "$pid" 2>/dev/null || true
    wait "$pid" 2>/dev/null || true
    tail -n 20 "$stderr" >&2
    echo "MockFastAPI did not start on port $port." >&2
    exit 1
fi
start_ticks="$(awk '{print $22}' "/proc/$pid/stat")"
printf '%s %s\n' "$pid" "$start_ticks" > "$pid_file"
echo "MockFastAPI started: PID=$pid, port=$port, PID file=$pid_file"
echo "Logs: $stdout; $stderr"
