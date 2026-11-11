@echo off
title SPY - push migration branch to GitHub (no merge)
cd /d "%~dp0..\.."
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Transcript -Path '_backups\step5_push.log' -Force; git status -sb | Select-Object -First 1; git push origin migration/wordpress-pc 2>&1 | Out-Host; git ls-remote --heads origin 2>&1 | Out-Host; Stop-Transcript"
echo.
pause
