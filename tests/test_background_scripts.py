"""Exercise the documented Windows background start/stop workflow."""

import os
import json
import shutil
import signal
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = shutil.which("powershell.exe")


def _listening(port: int) -> bool:
    with socket.socket() as connection:
        connection.settimeout(0.2)
        return connection.connect_ex(("127.0.0.1", port)) == 0


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell background scripts are Windows-specific")
def test_background_service_stops_from_a_new_shell() -> None:
    """A lost $server variable must not prevent stopping the launched service."""
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        port = reserved.getsockname()[1]

    pid_file = ROOT / f"test-background-{uuid.uuid4().hex}.pid"
    start = ROOT / "scripts" / "start.ps1"
    stop = ROOT / "scripts" / "stop.ps1"
    command = [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File"]

    try:
        started = subprocess.run(
            [*command, str(start), "-Port", str(port), "-PidFile", str(pid_file)],
            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20,
        )
        assert started.returncode == 0, f"start.ps1 exited {started.returncode}"
        assert pid_file.exists()
        saved = json.loads(pid_file.read_text())
        assert saved["pid"] > 0

        deadline = time.monotonic() + 12
        while not _listening(port) and time.monotonic() < deadline:
            time.sleep(0.2)
        assert _listening(port), "background service did not listen"

        stopped = subprocess.run(
            [*command, str(stop), "-PidFile", str(pid_file)],
            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20,
        )
        assert stopped.returncode == 0, f"stop.ps1 exited {stopped.returncode}"
        assert not pid_file.exists()

        deadline = time.monotonic() + 12
        while _listening(port) and time.monotonic() < deadline:
            time.sleep(0.2)
        assert not _listening(port), "background service kept the port after stop"
    finally:
        if stop.exists() and pid_file.exists():
            subprocess.run([*command, str(stop), "-PidFile", str(pid_file)],
                           cwd=ROOT, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=20)
        if pid_file.exists():
            os.kill(json.loads(pid_file.read_text())["pid"], signal.SIGTERM)
