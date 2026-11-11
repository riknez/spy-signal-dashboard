<#
  Read-only status check. Copies the tail of each log plus task/process status
  into _backups\live-check\ so it can be reviewed. Changes nothing else.
#>
$Project = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$out = Join-Path $Project "_backups\live-check"
New-Item -ItemType Directory -Force -Path $out | Out-Null
$logDir = "C:\SPYData\logs\spy"
$envLine = Get-Content (Join-Path $Project ".env") | Where-Object { $_ -match '^\s*SPY_LOG_DIR\s*=' }
if ($envLine) { $logDir = ($envLine -split '=', 2)[1].Trim() }

$report = @()
$report += "checked_at=$(Get-Date -Format s)"
$report += "log_dir=$logDir"
$task = Get-ScheduledTask -TaskName "Argus SPY Scanner" -ErrorAction SilentlyContinue
if ($task) {
  $info = $task | Get-ScheduledTaskInfo
  $report += "task_state=$($task.State) last_run=$($info.LastRunTime) last_result=$($info.LastTaskResult) next_run=$($info.NextRunTime)"
  $report += "task_triggers=" + (($task.Triggers | ForEach-Object { $_.CimClass.CimClassName + ' ' + $_.StartBoundary }) -join ' | ')
  $report += "task_wake_to_run=$($task.Settings.WakeToRun) restart_count=$($task.Settings.RestartCount)"
} else { $report += "task=NOT INSTALLED" }
Get-CimInstance Win32_Process -Filter "Name LIKE 'py%.exe'" | Where-Object { $_.CommandLine -match "spy_|run_market_hours|wp_push" } |
  ForEach-Object { $report += "process pid=$($_.ProcessId) cmd=$($_.CommandLine)" }
$report += "wake_timers: " + ((powercfg /query SCHEME_CURRENT SUB_SLEEP RTCWAKE | Select-String "Current AC Power Setting Index") -join ' ')
$report | Set-Content (Join-Path $out "status.txt") -Encoding ASCII

foreach ($f in "supervisor.log","scanner.out.log","worker_state.json","spy_live_status.json","spy_runtime_heartbeat.csv","spy_options_alerts.csv","spy_options_alert_results.csv","spy_signal_events.csv") {
  $p = Join-Path $logDir $f
  if (Test-Path $p) { Get-Content $p -Tail 200 | Set-Content (Join-Path $out $f) -Encoding UTF8 }
}
$pred = Join-Path $logDir "spy_direction_predictions.csv"
if (Test-Path $pred) {
  (Get-Content $pred -TotalCount 1) | Set-Content (Join-Path $out "predictions_tail.csv") -Encoding UTF8
  Get-Content $pred -Tail 400 | Add-Content (Join-Path $out "predictions_tail.csv") -Encoding UTF8
}
Write-Host "Status written to $out"
Get-Content (Join-Path $out "status.txt")
