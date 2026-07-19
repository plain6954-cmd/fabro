$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot 'env\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $python)) {
    throw "Python environment not found at $python. Create it with: python -m venv env"
}

Set-Location -LiteralPath $projectRoot

$listener = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if ($listener) {
    try {
        $response = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/login/' -UseBasicParsing -TimeoutSec 5
        Write-Host "FABRO is already running (HTTP $($response.StatusCode)): http://127.0.0.1:8000/" -ForegroundColor Green
        exit 0
    }
    catch {
        throw 'Port 8000 is occupied by another process. Stop that process before starting FABRO.'
    }
}

& $python manage.py check
if ($LASTEXITCODE -ne 0) {
    throw 'Django checks failed. The server was not started.'
}

Write-Host 'Starting FABRO at http://127.0.0.1:8000/' -ForegroundColor Green
Write-Host 'Keep this window open while using the local website. Press Ctrl+C to stop it.' -ForegroundColor Yellow
& $python manage.py runserver 127.0.0.1:8000 --noreload
