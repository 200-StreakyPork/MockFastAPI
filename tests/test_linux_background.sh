#!/usr/bin/env bash
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
test_root="$(mktemp -d)"
pid_file="$test_root/mockfastapi.linux.pid"
blocker_pid=""
delayed_pid=""
cleanup() {
    if [[ -n "$blocker_pid" ]]; then kill "$blocker_pid" 2>/dev/null || true; fi
    if [[ -n "$delayed_pid" ]]; then kill "$delayed_pid" 2>/dev/null || true; fi
    if [[ -f "$pid_file" ]]; then
        read -r pid _ < "$pid_file"
        kill "$pid" 2>/dev/null || true
    fi
    rm -rf -- "$test_root"
}
trap cleanup EXIT

mkdir -p "$test_root/scripts" "$test_root/.venv/bin"
cp "$repo/scripts/start.sh" "$repo/scripts/stop.sh" "$test_root/scripts/"
cat > "$test_root/.venv/bin/python" <<'SH'
#!/usr/bin/env bash
if [[ "$1" == '-c' ]]; then exec python3 "$@"; fi
port="${@: -1}"
sleep "${MOCKFASTAPI_FAKE_START_DELAY:-0}"
if [[ -n "${MOCKFASTAPI_FAKE_TERM_DELAY:-}" ]]; then
    exec python3 -c 'import http.server,os,signal,sys,time; signal.signal(signal.SIGTERM, lambda *_: (time.sleep(float(os.environ["MOCKFASTAPI_FAKE_TERM_DELAY"])), open(os.environ["MOCKFASTAPI_FAKE_TERM_MARKER"], "w").write("done"), sys.exit(0))); http.server.ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), http.server.SimpleHTTPRequestHandler).serve_forever()' "$port"
fi
exec python3 -m http.server "$port" --bind 127.0.0.1
SH
chmod +x "$test_root/.venv/bin/python"

port="$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()')"
export MOCKFASTAPI_PORT="$port" MOCKFASTAPI_PID_FILE="$pid_file"

bash "$test_root/scripts/start.sh"
[[ -f "$pid_file" ]]
read -r pid start_ticks < "$pid_file"
[[ "$pid" =~ ^[0-9]+$ && "$start_ticks" =~ ^[0-9]+$ ]]

is_listening() {
    python3 -c 'import socket,sys; s=socket.socket(); s.settimeout(.2); result=s.connect_ex(("127.0.0.1", int(sys.argv[1]))); s.close(); sys.exit(0 if result == 0 else 1)' "$port"
}
for _ in {1..50}; do
    if is_listening; then break; fi
    sleep .1
done
is_listening

bash "$test_root/scripts/stop.sh"
[[ ! -f "$pid_file" ]]
for _ in {1..50}; do
    if ! is_listening; then break; fi
    sleep .1
done
! is_listening

python3 -m http.server "$port" --bind 127.0.0.1 >/dev/null 2>&1 &
blocker_pid=$!
for _ in {1..50}; do
    if is_listening; then break; fi
    sleep .1
done
is_listening
if MOCKFASTAPI_FAKE_START_DELAY=0.7 bash "$test_root/scripts/start.sh"; then
    echo 'FAIL: start succeeded while the port was occupied' >&2
    exit 1
fi
[[ ! -f "$pid_file" ]]
kill "$blocker_pid"
wait "$blocker_pid" 2>/dev/null || true
blocker_pid=""

MOCKFASTAPI_FAKE_TERM_DELAY=1 MOCKFASTAPI_FAKE_TERM_MARKER="$test_root/terminated" \
    bash "$test_root/scripts/start.sh"
read -r delayed_pid _ < "$pid_file"
for _ in {1..50}; do
    if is_listening; then break; fi
    sleep .1
done
is_listening
MOCKFASTAPI_FAKE_TERM_DELAY=1 bash "$test_root/scripts/stop.sh"
[[ -f "$test_root/terminated" ]]
! is_listening
[[ ! -f "$pid_file" ]]
delayed_pid=""
echo 'PASS: Linux background start and stop release the port'
