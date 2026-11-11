"""Market-hours supervisor for the existing scanner.

Starts the UNMODIFIED spy_options_alert_scanner.py at the NYSE open and
stops it at the NYSE close (holidays, early closes and DST handled by
market_session.py). Restarts the scanner if it crashes mid-session and
writes a heartbeat file the dashboard/monitoring can check.

Replaces run_spy_all.bat on the cloud worker. No broker connection.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from market_session import EASTERN, session_state  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCANNER = os.path.join(ROOT, "spy_options_alert_scanner.py")
STATE_FILE = os.path.join(ROOT, "logs", "spy", "worker_state.json")
CHECK_EVERY = 15          # seconds between supervisor checks
MAX_RESTARTS = 20         # per session, to avoid a crash loop


def log(msg: str) -> None:
    print(f"{datetime.now(EASTERN).isoformat(timespec='seconds')} [supervisor] {msg}", flush=True)


def write_state(state, scanner_running: bool, restarts: int) -> None:
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    payload = {
        "updated_at": datetime.now(EASTERN).isoformat(),
        "market_label": state.label,
        "session_date": state.session_date,
        "session_close": state.close_at.isoformat() if state.close_at else None,
        "early_close": state.early_close,
        "next_open": state.next_open.isoformat(),
        "scanner_running": scanner_running,
        "restarts_this_session": restarts,
    }
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    os.replace(tmp, STATE_FILE)


def stop(proc: subprocess.Popen | None) -> None:
    if proc and proc.poll() is None:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()


def main() -> None:
    proc: subprocess.Popen | None = None
    restarts = 0
    current_session = None
    stopping = False

    def _term(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, _term)
    signal.signal(signal.SIGINT, _term)

    while not stopping:
        state = session_state()
        if state.session_date != current_session:
            current_session, restarts = state.session_date, 0

        running = proc is not None and proc.poll() is None
        if state.is_open and not running:
            if proc is not None and restarts >= MAX_RESTARTS:
                log("scanner crashed too often this session; not restarting (alert!)")
            else:
                if proc is not None:
                    restarts += 1
                    log(f"scanner exited (code {proc.returncode}); restart #{restarts}")
                log(f"market OPEN (closes {state.close_at:%H:%M} ET) - starting scanner")
                proc = subprocess.Popen([sys.executable, "-u", SCANNER], cwd=ROOT)
        elif not state.is_open and running:
            log("market CLOSED - stopping scanner; data now HISTORICAL")
            stop(proc)
            proc = None

        write_state(state, proc is not None and proc.poll() is None, restarts)
        time.sleep(CHECK_EVERY)

    stop(proc)
    log("supervisor stopped")


if __name__ == "__main__":
    main()
