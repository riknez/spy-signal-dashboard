# Running the scanner on the Windows PC (market hours only)

1. Logs out of OneDrive (copies + verifies, originals untouched):
   `powershell -ExecutionPolicy Bypass -File worker\windows\move_logs_out_of_onedrive.ps1 -UpdateEnv`
2. Add to `.env`: `ARGUS_SPY_INGEST_URL`, `ARGUS_SPY_INGEST_SECRET` (see `.env.example`).
3. Test one push: `py worker\wp_push.py --once`
4. Install the startup task: `powershell -ExecutionPolicy Bypass -File worker\windows\install_startup_task.ps1`
   Remove it any time with `uninstall_startup_task.ps1`.

`run_market_hours.py` follows the NYSE calendar (holidays, early closes, DST). While the
market is open it runs the scanner + WordPress pusher, restarts them if they crash and
keeps the PC awake; outside hours it stops them and sends a snapshot every 5 minutes so the
site shows "market closed". Logs: `supervisor.log`, `scanner.out.log`, `pusher.out.log`
in the log folder. Telegram runs only with `SPY_ENABLE_TELEGRAM=1`.
