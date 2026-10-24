# setup-https.ps1
# Generate a locally trusted TLS certificate for LAN HTTPS development on Windows.
#
# Requirements: mkcert  https://github.com/FiloSottile/mkcert
#   Install via Chocolatey : choco install mkcert
#   Install via Scoop       : scoop bucket add extras; scoop install mkcert
#   Or download the .exe   : https://github.com/FiloSottile/mkcert/releases
#     and place it somewhere on your PATH (e.g. C:\Windows\System32\mkcert.exe)
#
# Run once per machine.  Re-run whenever your LAN IP changes.
#
# Usage (from the project root in PowerShell):
#   .\setup-https.ps1
#   .\setup-https.ps1 -LanIP 192.168.1.42   # override the LAN IP

param(
    [string]$LanIP = "192.168.18.117"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Move to the project root (the folder that contains this script)
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

Write-Host ""
Write-Host "=== Satyapan HTTPS setup ===" -ForegroundColor Cyan

# ── 1. Locate mkcert ─────────────────────────────────────────────────────────
$mkcert = Get-Command mkcert -ErrorAction SilentlyContinue
if (-not $mkcert) {
    Write-Host ""
    Write-Host "ERROR: mkcert not found on PATH." -ForegroundColor Red
    Write-Host "Install it with one of:"
    Write-Host "  choco install mkcert"
    Write-Host "  scoop install mkcert"
    Write-Host "  or download from https://github.com/FiloSottile/mkcert/releases"
    Write-Host "  (rename the .exe to mkcert.exe and add it to your PATH)"
    exit 1
}
Write-Host "Found mkcert: $($mkcert.Source)"

# ── 2. Install the local CA into the Windows trust store ─────────────────────
Write-Host ""
Write-Host "Installing the local CA into the Windows certificate store."
Write-Host "A UAC prompt may appear – accept it to trust the certificate."
& mkcert -install
if ($LASTEXITCODE -ne 0) { Write-Host "mkcert -install failed." -ForegroundColor Red; exit 1 }

# ── 3. Generate the certificate ──────────────────────────────────────────────
$CertDir = "frontend\certs"
New-Item -ItemType Directory -Force -Path $CertDir | Out-Null

& mkcert `
    -cert-file "$CertDir\lan.crt" `
    -key-file  "$CertDir\lan.key" `
    $LanIP localhost 127.0.0.1

if ($LASTEXITCODE -ne 0) { Write-Host "Certificate generation failed." -ForegroundColor Red; exit 1 }

# Copy the root CA so it can be transferred to other test devices
$caroot = & mkcert -CAROOT
Copy-Item "$caroot\rootCA.pem" "$CertDir\rootCA.pem" -Force

Write-Host ""
Write-Host "Certificate written to $CertDir\lan.crt" -ForegroundColor Green
Write-Host "Private key at        $CertDir\lan.key  (never commit this file)"
Write-Host "CA cert at            $CertDir\rootCA.pem (install on test devices)"
Write-Host ""
Write-Host "Next: start the app with .\start.ps1"
Write-Host "Then open: https://${LanIP}:5173  on this machine and other LAN devices."
Write-Host ""
Write-Host "To trust the certificate on Android/iOS see README.md section 'HTTPS / LAN setup'."
