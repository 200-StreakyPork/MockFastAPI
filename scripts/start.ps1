param(
    [int]$Port = 8000,
    [string]$PidFile
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    throw "Python not found at $python. Run uv sync first."
}

if (-not $PidFile) {
    $PidFile = Join-Path $root 'mockfastapi.pid'
}
if (Test-Path -LiteralPath $PidFile) {
    $saved = Get-Content -LiteralPath $PidFile -Raw | ConvertFrom-Json
    $running = Get-Process -Id ([int]$saved.pid) -ErrorAction SilentlyContinue
    if ($running -and $running.StartTime.ToUniversalTime().Ticks -eq [long]$saved.started_at_utc_ticks) {
        throw "MockFastAPI is already running as PID $($saved.pid). Run scripts\stop.ps1 first."
    }
    Remove-Item -LiteralPath $PidFile
}

if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
    throw "Port $Port is already in use."
}

$logName = if ($Port -eq 8000) { 'mockfastapi' } else { "mockfastapi.$Port" }
$stdout = Join-Path $root "$logName.stdout.log"
$stderr = Join-Path $root "$logName.stderr.log"
$server = Start-Process -FilePath $python `
    -ArgumentList @('-m', 'uvicorn', 'mockfastapi.app:create_app', '--factory', '--host', '127.0.0.1', '--port', "$Port") `
    -WorkingDirectory $root -RedirectStandardOutput $stdout -RedirectStandardError $stderr `
    -WindowStyle Hidden -PassThru
$record = @{ pid = $server.Id; started_at_utc_ticks = $server.StartTime.ToUniversalTime().Ticks }
$record | ConvertTo-Json -Compress | Set-Content -LiteralPath $PidFile -Encoding ascii
Write-Output "MockFastAPI started: PID=$($server.Id), port=$Port, PID file=$PidFile"
Write-Output "Logs: $stdout; $stderr"
