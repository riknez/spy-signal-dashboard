$TaskName = "Argus SPY Scanner"
Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
Write-Host "Removed '$TaskName' (if it existed). Your files and logs are unchanged."
