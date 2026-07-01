@echo off
title START SPY SIGNAL LAB

echo Starting SPY Signal Lab...
echo NO AUTO BUY
echo NO AUTO SELL
echo NO BROKER CONNECTION
echo.

start "SPY OPTIONS SCANNER" powershell -NoExit -Command "title SPY OPTIONS SCANNER; cd 'C:\Users\Erikm\OneDrive\Desktop\spy-signal-lab'; py spy_options_alert_scanner.py"

timeout /t 3 /nobreak >nul

start "SPY LANDING STATUS PUSHER" powershell -NoExit -Command "title SPY LANDING STATUS PUSHER; cd 'C:\Users\Erikm\OneDrive\Desktop\spy-signal-lab'; py push_spy_status_to_landing.py"

timeout /t 3 /nobreak >nul

start "SPY DASHBOARD" powershell -NoExit -Command "title SPY DASHBOARD; cd 'C:\Users\Erikm\OneDrive\Desktop\spy-signal-lab'; py spy_dashboard.py"

echo.
echo Started:
echo - SPY options scanner
echo - SPY landing status pusher
echo - SPY dashboard
echo.
pause