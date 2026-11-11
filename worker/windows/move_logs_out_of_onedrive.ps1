<#
  Copies the SPY logs out of OneDrive to a local folder, verifies every file
  by SHA-256, and (optionally) points the scanner at the new folder.

  The ORIGINAL logs are NOT moved or deleted - they stay in OneDrive as the
  backup until you decide to remove them yourself.

  Usage (PowerShell, from the project folder):
    powershell -ExecutionPolicy Bypass -File worker\windows\move_logs_out_of_onedrive.ps1
    powershell -ExecutionPolicy Bypass -File worker\windows\move_logs_out_of_onedrive.ps1 -UpdateEnv
#>
param(
  [string]$Destination = "C:\SPYData\logs\spy",
  [switch]$UpdateEnv
)
$ErrorActionPreference = "Stop"
$Project = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Source  = Join-Path $Project "logs\spy"

if (-not (Test-Path $Source)) { throw "Source not found: $Source" }
if ($Destination -like "*OneDrive*") { throw "Destination is inside OneDrive. Pick a local folder such as C:\SPYData\logs\spy." }

$running = Get-CimInstance Win32_Process -Filter "Name LIKE 'py%.exe'" |
  Where-Object { $_.CommandLine -match "spy_options_alert_scanner|run_market_hours|push_spy_status|wp_push" }
if ($running) {
  Write-Host "Stop the scanner first (these are running):" -ForegroundColor Yellow
  $running | ForEach-Object { Write-Host "  PID $($_.ProcessId): $($_.CommandLine)" }
  exit 1
}

# OneDrive "files on demand" may hold placeholders; make sure they are local.
Get-ChildItem $Source -Recurse -File | ForEach-Object {
  if ($_.Attributes -band [IO.FileAttributes]::Offline) { throw "$($_.FullName) is online-only in OneDrive. Right-click the logs folder > 'Always keep on this device', wait for sync, then rerun." }
}

New-Item -ItemType Directory -Force -Path $Destination | Out-Null
Write-Host "Copying $Source -> $Destination ..."
robocopy $Source $Destination /E /COPY:DAT /DCOPY:T /R:2 /W:2 /NP /NFL /NDL | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy failed with code $LASTEXITCODE" }

Write-Host "Verifying SHA-256 of every file ..."
$bad = 0; $count = 0; $bytes = 0
Get-ChildItem $Source -Recurse -File | ForEach-Object {
  $rel = $_.FullName.Substring($Source.Length).TrimStart('\')
  $dst = Join-Path $Destination $rel
  $count++; $bytes += $_.Length
  if (-not (Test-Path $dst)) { Write-Host "MISSING $rel" -ForegroundColor Red; $bad++; return }
  if ((Get-FileHash $_.FullName -Algorithm SHA256).Hash -ne (Get-FileHash $dst -Algorithm SHA256).Hash) {
    Write-Host "MISMATCH $rel" -ForegroundColor Red; $bad++
  }
}
if ($bad) { throw "$bad file(s) failed verification. Nothing was changed in .env." }
"{0} files, {1:N1} MB copied and verified." -f $count, ($bytes/1MB) | Write-Host -ForegroundColor Green
Set-Content -Path (Join-Path $Destination "COPIED_FROM.txt") -Value "Copied from $Source on $(Get-Date -Format s). Originals left in place as backup."

$envFile = Join-Path $Project ".env"
if ($UpdateEnv) {
  Copy-Item $envFile "$envFile.before-logdir-$(Get-Date -Format yyyyMMdd-HHmmss)"
  $lines = Get-Content $envFile | Where-Object { $_ -notmatch '^\s*SPY_LOG_DIR\s*=' }
  $lines + "SPY_LOG_DIR=$Destination" | Set-Content $envFile -Encoding UTF8
  Write-Host "Set SPY_LOG_DIR=$Destination in .env (backup of the old .env saved next to it)."
} else {
  Write-Host "Next: add this line to .env (or rerun with -UpdateEnv):  SPY_LOG_DIR=$Destination"
}
Write-Host "The OneDrive copy in $Source is untouched. Keep it until the new location has run for a week."
