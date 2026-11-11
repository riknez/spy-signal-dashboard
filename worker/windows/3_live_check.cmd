@echo off
title SPY - status check
cd /d "%~dp0..\.."
powershell -NoProfile -ExecutionPolicy Bypass -File ".\worker\windows\live_check.ps1"
echo.
pause
