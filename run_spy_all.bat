@echo off
title RUN SPY SIGNAL LAB ALL

cd /d "%~dp0"

echo ==================================================
echo SPY SIGNAL LAB RUNNER
echo Folder: %cd%
echo NO AUTO BUY
echo NO AUTO SELL
echo NO BROKER CONNECTION
echo SCANNER + RENDER PUSH ONLY
echo ==================================================
echo.

findstr /C:"YOUR-SPY-DASHBOARD" ".env" >nul 2>&1
if %errorlevel%==0 (
    echo ERROR: .env still has YOUR-SPY-DASHBOARD placeholder.
    echo Fix SCANNER_STATUS_UPDATE_URL and DASHBOARD_UPDATE_URL first.
    pause
    exit /b
)

findstr /C:"latency-scanner-landing" ".env" >nul 2>&1
if %errorlevel%==0 (
    echo ERROR: .env still points to latency-scanner-landing.
    echo SPY must push to scanner-signal-members /api/push-status.
    pause
    exit /b
)

if not exist "spy_options_alert_scanner.py" (
    echo ERROR: spy_options_alert_scanner.py not found in %cd%
    pause
    exit /b
)

if not exist "push_spy_status_to_landing.py" (
    echo ERROR: push_spy_status_to_landing.py not found in %cd%
    pause
    exit /b
)

start "SPY OPTIONS ALERT SCANNER" powershell -NoExit -ExecutionPolicy Bypass -Command "Set-Location -LiteralPath '%~dp0'; py spy_options_alert_scanner.py"

start "SPY RENDER LIVE FEED PUSHER" powershell -NoExit -ExecutionPolicy Bypass -Command "Set-Location -LiteralPath '%~dp0'; py push_spy_status_to_landing.py"

echo.
echo Started SPY scanner and Render live-feed pusher.
echo.
pause