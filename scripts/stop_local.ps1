$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $projectRoot 'server.pid'
$listeners = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue

if (-not $listeners) {
    Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
    Write-Host 'FABRO is not running on port 8000.' -ForegroundColor Yellow
    exit 0
}

$processIds = $listeners | Select-Object -ExpandProperty OwningProcess -Unique
foreach ($processId in $processIds) {
    $process = Get-Process -Id $processId -ErrorAction Stop
    if ($process.ProcessName -notin @('python', 'pythonw')) {
        throw "Port 8000 belongs to $($process.ProcessName) (PID $processId), so it was not stopped."
    }
    Stop-Process -Id $processId -Force
    Write-Host "Stopped FABRO process $processId." -ForegroundColor Green
}

Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
