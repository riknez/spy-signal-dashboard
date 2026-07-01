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
echo Started:
echo - SPY options scanner
echo - SPY Render live-feed pusher
echo.
pause