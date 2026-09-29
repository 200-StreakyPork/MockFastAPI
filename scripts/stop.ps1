param(
    [string]$PidFile
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
if (-not $PidFile) {
    $PidFile = Join-Path $root 'mockfastapi.pid'
}
if (-not (Test-Path -LiteralPath $PidFile)) {
    Write-Output "No PID file at $PidFile; nothing to stop."
    return
}

$record = Get-Content -LiteralPath $PidFile -Raw | ConvertFrom-Json
$serverPid = [int]$record.pid
$server = Get-Process -Id $serverPid -ErrorAction SilentlyContinue
if (-not $server) {
    Remove-Item -LiteralPath $PidFile
    Write-Output "Process $serverPid is gone; stale PID file removed."
    return
}
$expectedPython = Join-Path $root '.venv\Scripts\python.exe'
if ($server.Path -ne $expectedPython -or
    $server.StartTime.ToUniversalTime().Ticks -ne [long]$record.started_at_utc_ticks) {
    throw "PID $serverPid no longer identifies this MockFastAPI process; no process stopped."
}

Stop-Process -Id $serverPid
Remove-Item -LiteralPath $PidFile
Write-Output "MockFastAPI stopped: PID=$serverPid"
