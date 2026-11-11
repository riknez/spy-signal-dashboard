@echo off
title SPY - copy logs out of OneDrive
cd /d "%~dp0..\.."
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Transcript -Path '_backups\step1_move_logs.log' -Force; & '.\worker\windows\move_logs_out_of_onedrive.ps1' -UpdateEnv; Stop-Transcript"
echo.
echo Done. You can close this window.
pause
