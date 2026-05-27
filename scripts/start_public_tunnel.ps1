# Start ngrok tunnel to expose Streamlit dashboard to the public internet.
# Prerequisites:
#   1. Install ngrok: https://ngrok.com/download
#   2. Register at https://dashboard.ngrok.com and get your authtoken
#   3. Run: ngrok config add-authtoken YOUR_TOKEN
#
# Usage:
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_public_tunnel.ps1
#
# After starting, ngrok will display a public URL like https://xxxx.ngrok-free.app
# Share this URL with external users. They can access the Streamlit dashboard directly.
#
# Note: The free ngrok URL changes every time you restart. Copy the new URL and
# update CORS_ORIGINS in .env if needed (for API calls from Streamlit to FastAPI,
# CORS is usually not an issue since Streamlit runs on localhost).

[CmdletBinding()]
param(
    [int]$StreamlitPort = 8501
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [Text.Encoding]::UTF8

# Check ngrok is available
$NgrokPath = $null
$NgrokCandidates = @(
    "ngrok",
    "C:\ngrok\ngrok.exe",
    "J:\ngrok\ngrok.exe",
    "$env:LOCALAPPDATA\ngrok\ngrok.exe",
    "$env:USERPROFILE\AppData\Local\ngrok\ngrok.exe",
    "$env:ProgramFiles\ngrok\ngrok.exe"
)
foreach ($candidate in $NgrokCandidates) {
    try {
        $null = & $candidate version 2>&1
        $NgrokPath = $candidate
        break
    } catch {
        continue
    }
}

if (-not $NgrokPath) {
    Write-Host "[ERROR] ngrok not found." -ForegroundColor Red
    Write-Host "  Download from: https://ngrok.com/download" -ForegroundColor Yellow
    Write-Host "  Extract to J:\ngrok\ or C:\ngrok\ or add to PATH." -ForegroundColor Yellow
    Write-Host "  Then run: ngrok config add-authtoken YOUR_TOKEN" -ForegroundColor Yellow
    exit 1
}

Write-Host "Starting ngrok tunnel to localhost:$StreamlitPort ..." -ForegroundColor Cyan
Write-Host "The public URL will appear below. Share it with external users." -ForegroundColor DarkGray
Write-Host "Press Ctrl+C to stop the tunnel." -ForegroundColor DarkGray
Write-Host ""

# Start ngrok (foreground - keeps the window open)
& $NgrokPath http $StreamlitPort --host-header=rewrite
