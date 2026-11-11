@echo off
title SPY - restart scanner task
cd /d "%~dp0..\.."
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Transcript -Path '_backups\step4_restart.log' -Force; & '.\worker\windows\restart_task.ps1'; Stop-Transcript"
echo.
pause
