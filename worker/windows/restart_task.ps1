<#
  Restart the SPY scanner after a code update: stops the scheduled task,
  stops any scanner/pusher/supervisor Python processes from THIS project
  (matched by command line), then starts the task again. Logs are kept.
#>
$TaskName = "Argus SPY Scanner"
Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
Start-Sleep 2
Get-CimInstance Win32_Process -Filter "Name LIKE 'py%.exe'" |
  Where-Object { $_.CommandLine -match "run_market_hours\.py|spy_options_alert_scanner\.py|wp_push\.py|telegram_spy_notifier\.py" } |
  ForEach-Object { Write-Host "Stopping PID $($_.ProcessId): $($_.CommandLine)"; Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep 2
Start-ScheduledTask -TaskName $TaskName
Start-Sleep 8
Get-ScheduledTask -TaskName $TaskName | Select-Object TaskName, State | Format-Table | Out-Host
Get-CimInstance Win32_Process -Filter "Name LIKE 'py%.exe'" |
  Where-Object { $_.CommandLine -match "run_market_hours|spy_options_alert_scanner" } |
  ForEach-Object { Write-Host "Running PID $($_.ProcessId): $($_.CommandLine)" }
