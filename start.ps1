# start.ps1
# Starts the Django backend (port 8000) and the Vite frontend (port 5173).
#
# Requirements:
#   Python 3.12  https://www.python.org/downloads/  (NOT 3.13 / 3.14)
#   Node.js 18+  https://nodejs.org
#
# Usage (from the project root in PowerShell):
#   .\start.ps1
#
# For HTTPS / camera access from other LAN devices, run .\setup-https.ps1 first.

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Move to the project root (the folder that contains this script)
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

Write-Host ""
Write-Host "=== Satyapan – starting backend + frontend ===" -ForegroundColor Cyan

# ── 1. Verify Python 3.12 ────────────────────────────────────────────────────
$PY = $null

# Try py launcher first (standard Windows Python installer)
$pyLauncher = Get-Command py -ErrorAction SilentlyContinue
if ($pyLauncher) {
    $ver = & py -3.12 --version 2>&1
    if ($LASTEXITCODE -eq 0 -and $ver -match "3\.12") { $PY = "py -3.12" }
}

# Fall back to python3.12 or python if it reports 3.12
if (-not $PY) {
    foreach ($candidate in @("python3.12", "python3", "python")) {
        $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($cmd) {
            $ver = & $cmd --version 2>&1
            if ($ver -match "3\.12") { $PY = $cmd.Source; break }
        }
    }
}

if (-not $PY) {
    Write-Host ""
    Write-Host "ERROR: Python 3.12 not found." -ForegroundColor Red
    Write-Host "Download it from https://www.python.org/downloads/"
    Write-Host "Python 3.13 and 3.14 are NOT supported."
    exit 1
}
Write-Host "Using Python: $PY"

# ── 2. Verify Node / npm ─────────────────────────────────────────────────────
$npm = Get-Command npm -ErrorAction SilentlyContinue
if (-not $npm) {
    Write-Host ""
    Write-Host "ERROR: Node.js 18+ is required." -ForegroundColor Red
    Write-Host "Download it from https://nodejs.org"
    exit 1
}
Write-Host "Using npm:    $($npm.Source)"

# ── 3. Backend setup ─────────────────────────────────────────────────────────
Write-Host ""
Write-Host "--- Backend setup ---" -ForegroundColor Yellow
Set-Location "$ProjectRoot\backend"

# Recreate the venv if it exists but is the wrong Python version
if (Test-Path ".venv") {
    $venvPython = ".venv\Scripts\python.exe"
    if (Test-Path $venvPython) {
        $venvVer = & $venvPython --version 2>&1
        if ($venvVer -notmatch "3\.12") {
            Write-Host "Existing venv is not Python 3.12 – removing it..." -ForegroundColor Yellow
            Remove-Item -Recurse -Force ".venv"
        }
    }
}

# Create venv if absent
if (-not (Test-Path ".venv")) {
    Write-Host "Creating Python 3.12 virtual environment..."
    if ($PY -eq "py -3.12") {
        & py -3.12 -m venv .venv
    } else {
        & $PY -m venv .venv
    }
    if ($LASTEXITCODE -ne 0) { Write-Host "venv creation failed." -ForegroundColor Red; exit 1 }
}

$PythonVenv = "$ProjectRoot\backend\.venv\Scripts\python.exe"
$PipVenv    = "$ProjectRoot\backend\.venv\Scripts\pip.exe"

Write-Host "Upgrading pip..."
& $PipVenv install -q --upgrade pip

Write-Host "Installing Python dependencies..."
& $PipVenv install -q -r requirements.txt
if ($LASTEXITCODE -ne 0) { Write-Host "pip install failed." -ForegroundColor Red; exit 1 }

# Model dependencies (PyTorch, transformers, MediaPipe, OpenCV). Large download; set SATYAPAN_ML=0 to skip.
if ($env:SATYAPAN_ML -ne "0") {
    Write-Host "Installing model dependencies (large download the first time)..."
    & $PipVenv install -q -r requirements-ml.txt
    if ($LASTEXITCODE -ne 0) { Write-Host "WARNING: model dependencies failed to install. The site still starts, but the model-based checks will show as unavailable." -ForegroundColor Yellow }
}

# Copy .env if missing
if (-not (Test-Path ".env")) {
    Write-Host "Creating .env from .env.example..."
    Copy-Item ".env.example" ".env"
}

Write-Host "Preparing the database (migrations are generated on first run and the schema is verified)..."
& $PythonVenv manage.py setup_db
if ($LASTEXITCODE -ne 0) { Write-Host "Database setup failed - see the messages above." -ForegroundColor Red; exit 1 }

Write-Host "Creating demo users (development only)..."
& $PythonVenv manage.py create_demo_users 2>$null
# Ignore exit code – the command refuses silently in production

# ── 4. Start backend in a new window ────────────────────────────────────────
Write-Host ""
Write-Host "Starting Django backend on port 8000..." -ForegroundColor Yellow
$DaphneExe = "$ProjectRoot\backend\.venv\Scripts\daphne.exe"
$backendProc = Start-Process -FilePath $DaphneExe `
    -ArgumentList "-b", "0.0.0.0", "-p", "8000", "satyapan.asgi:application" `
    -WorkingDirectory "$ProjectRoot\backend" `
    -PassThru `
    -NoNewWindow

if (-not $backendProc) {
    Write-Host "Failed to start backend." -ForegroundColor Red; exit 1
}
Write-Host "Backend PID: $($backendProc.Id)"

# ── 5. Frontend setup + start ────────────────────────────────────────────────
Write-Host ""
Write-Host "--- Frontend setup ---" -ForegroundColor Yellow
Set-Location "$ProjectRoot\frontend"

if (-not (Test-Path "node_modules")) {
    Write-Host "Installing Node dependencies (this may take a minute)..."
    & npm install
    if ($LASTEXITCODE -ne 0) {
        Write-Host "npm install failed." -ForegroundColor Red
        Stop-Process -Id $backendProc.Id -Force -ErrorAction SilentlyContinue
        exit 1
    }
}

# ── 6. Print startup banner ──────────────────────────────────────────────────
$certPresent = (Test-Path "certs\lan.crt") -and (Test-Path "certs\lan.key")
if ($certPresent) {
    $Scheme = "https"
    Write-Host ""
    Write-Host "+----------------------------------------------------------+" -ForegroundColor Green
    Write-Host "|  HTTPS is enabled - camera will work on LAN devices.    |" -ForegroundColor Green
    Write-Host "+----------------------------------------------------------+" -ForegroundColor Green
} else {
    $Scheme = "http"
    Write-Host ""
    Write-Host "+--------------------------------------------------------------+" -ForegroundColor Yellow
    Write-Host "|  WARNING: No TLS certificate found.                         |" -ForegroundColor Yellow
    Write-Host "|  Camera will NOT work on other LAN devices over plain HTTP. |" -ForegroundColor Yellow
    Write-Host "|  Run: .\setup-https.ps1  to generate the certificate.       |" -ForegroundColor Yellow
    Write-Host "+--------------------------------------------------------------+" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Open ${Scheme}://localhost:5173   (API docs: http://127.0.0.1:8000/docs)" -ForegroundColor Cyan
Write-Host "Demo logins (development only):  officer / officer-pass-123   customer / customer-pass-123"
Write-Host ""
Write-Host "Press Ctrl+C to stop both servers." -ForegroundColor Gray

# ── 7. Register Ctrl+C handler to kill backend ───────────────────────────────
[Console]::TreatControlCAsInput = $false
$null = Register-EngineEvent -SourceIdentifier PowerShell.Exiting -Action {
    if ($backendProc -and -not $backendProc.HasExited) {
        Stop-Process -Id $backendProc.Id -Force -ErrorAction SilentlyContinue
    }
}

try {
    # npm run dev blocks until Ctrl+C
    & npm run dev
} finally {
    Write-Host ""
    Write-Host "Shutting down backend (PID $($backendProc.Id))..." -ForegroundColor Yellow
    if (-not $backendProc.HasExited) {
        Stop-Process -Id $backendProc.Id -Force -ErrorAction SilentlyContinue
    }
    Write-Host "Done." -ForegroundColor Green
}
