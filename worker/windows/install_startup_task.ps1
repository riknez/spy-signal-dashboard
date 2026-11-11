<#
  Registers a Windows Scheduled Task that runs the market-hours supervisor:
    - at log-on, and every weekday at 9:20 AM (wakes the PC from sleep if needed)
    - restarts automatically if it stops
  The supervisor itself decides, from the NYSE calendar, when the scanner runs.
  Runs only while you are logged in (no stored password). Undo with
  uninstall_startup_task.ps1.
#>
$ErrorActionPreference = "Stop"
$TaskName = "Argus SPY Scanner"
$Project  = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Script   = Join-Path $Project "worker\run_market_hours.py"

$python = (& py -3 -c "import sys; print(sys.executable)").Trim()
if (-not (Test-Path $python)) { throw "Python launcher 'py' not found." }
$pythonw = Join-Path (Split-Path $python) "pythonw.exe"
if (-not (Test-Path $pythonw)) { $pythonw = $python }
& $python -c "import exchange_calendars, pandas, yfinance" 2>$null
if ($LASTEXITCODE -ne 0) {
  Write-Host "Installing required packages ..."
  & $python -m pip install --user -r (Join-Path $Project "worker\requirements-worker.txt")
}

$action   = New-ScheduledTaskAction -Execute $pythonw -Argument "`"$Script`"" -WorkingDirectory $Project
$logon    = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$morning  = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 9:20am
$settings = New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable -AllowStartIfOnBatteries `
              -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) `
              -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger @($logon, $morning) -Settings $settings `
  -Principal $principal -Description "Runs the SPY scanner during NYSE hours and pushes to argusclients.com/spy. No orders." -Force | Out-Null
Write-Host "Installed '$TaskName'. Start it now with:  Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "Wake timers must be allowed: Control Panel > Power Options > Change plan settings > Advanced > Sleep > Allow wake timers = Enable."
