$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot 'env\Scripts\python.exe'
$healthUrl = 'http://127.0.0.1:8000/health/'
$stdoutLog = Join-Path $projectRoot 'server.out.log'
$stderrLog = Join-Path $projectRoot 'server.err.log'
$pidFile = Join-Path $projectRoot 'server.pid'

if (-not (Test-Path -LiteralPath $python)) {
    throw "Python environment not found at $python. Create it with: python -m venv env"
}

Set-Location -LiteralPath $projectRoot

$listener = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if ($listener) {
    try {
        $response = Invoke-WebRequest -Uri $healthUrl -UseBasicParsing -TimeoutSec 5
        if ($response.StatusCode -eq 200) {
            Write-Host 'FABRO is already running: http://127.0.0.1:8000/' -ForegroundColor Green
            exit 0
        }
    }
    catch {
        throw 'Port 8000 is occupied by another process. Stop it before starting FABRO.'
    }
}

& $python manage.py check
if ($LASTEXITCODE -ne 0) {
    throw 'Django checks failed. The server was not started.'
}

# Some automation shells expose both Path and PATH. Normalize them before
# Start-Process so Windows does not reject the inherited environment block.
$cleanPath = [Environment]::GetEnvironmentVariable('PATH', 'Process')
[Environment]::SetEnvironmentVariable('PATH', $null, 'Process')
[Environment]::SetEnvironmentVariable('Path', $null, 'Process')
[Environment]::SetEnvironmentVariable('Path', $cleanPath, 'Process')

$process = Start-Process `
    -FilePath $python `
    -ArgumentList 'manage.py', 'runserver', '127.0.0.1:8000', '--noreload' `
    -WorkingDirectory $projectRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput $stdoutLog `
    -RedirectStandardError $stderrLog `
    -PassThru

Set-Content -LiteralPath $pidFile -Value $process.Id

for ($attempt = 0; $attempt -lt 30; $attempt++) {
    Start-Sleep -Milliseconds 500
    if ($process.HasExited) {
        $details = Get-Content -Tail 30 -LiteralPath $stderrLog -ErrorAction SilentlyContinue
        throw "FABRO exited during startup.`n$details"
    }
    try {
        $response = Invoke-WebRequest -Uri $healthUrl -UseBasicParsing -TimeoutSec 2
        if ($response.StatusCode -eq 200) {
            Write-Host "FABRO started (PID $($process.Id)): http://127.0.0.1:8000/" -ForegroundColor Green
            exit 0
        }
    }
    catch {
        # The process can take a few seconds to bind the port.
    }
}

Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
throw "FABRO did not become healthy. Review $stderrLog."
