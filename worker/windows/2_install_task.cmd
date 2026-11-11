@echo off
title SPY - install startup task
cd /d "%~dp0..\.."
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Transcript -Path '_backups\step2_install_task.log' -Force; & '.\worker\windows\install_startup_task.ps1'; Start-ScheduledTask -TaskName 'Argus SPY Scanner'; Start-Sleep 5; Get-ScheduledTask -TaskName 'Argus SPY Scanner' | Select-Object TaskName,State; Stop-Transcript"
echo.
echo Done. You can close this window.
pause
