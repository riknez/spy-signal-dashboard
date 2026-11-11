"""Market-hours supervisor (Windows PC or Linux).

During each NYSE session (official XNYS calendar: holidays, 1:00 PM early
closes and DST handled) it runs:
  * spy_options_alert_scanner.py   (UNMODIFIED trading logic)
  * worker/wp_push.py              (sends results to WordPress)
  * telegram_spy_notifier.py       (only if SPY_ENABLE_TELEGRAM=1)
and stops them at the close. Outside market hours it pushes one snapshot
every 5 minutes so WordPress can show "market closed / PC online" with the
last session labelled HISTORICAL.

Crashed processes are restarted (max 20 per session). On Windows the PC is
kept awake while the market is open (released at the close). If the PC
slept anyway, the gap is recorded so the dashboard can warn about it.

No broker connection. No orders.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from market_session import EASTERN, session_state  # noqa: E402

CHECK_EVERY = 15
MAX_RESTARTS = 20
CLOSED_PUSH_EVERY = 300
SLEEP_GAP_SECONDS = 120
IS_WINDOWS = os.name == "nt"


def load_env_file(path: str) -> None:
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8-sig") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def log_dir() -> str:
    return os.environ.get("SPY_LOG_DIR") or os.path.join(ROOT, "logs", "spy")


def log(msg: str) -> None:
    line = f"{datetime.now(EASTERN).isoformat(timespec='seconds')} [supervisor] {msg}"
    print(line, flush=True)
    try:
        with open(os.path.join(log_dir(), "supervisor.log"), "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def keep_awake(on: bool) -> None:
    """Windows only: ask the OS not to sleep while the market is open."""
    if not IS_WINDOWS:
        return
    try:
        import ctypes
        ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
        flags = ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if on else 0)
        ctypes.windll.kernel32.SetThreadExecutionState(flags)
    except Exception as err:  # never let this stop the scanner
        log(f"keep-awake call failed: {err}")


class Child:
    def __init__(self, name: str, args: list[str]):
        self.name, self.args = name, args
        self.proc: subprocess.Popen | None = None
        self.restarts = 0

    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self) -> None:
        kwargs = {"cwd": ROOT, "env": os.environ.copy()}
        out = open(os.path.join(log_dir(), f"{self.name}.out.log"), "a", encoding="utf-8")
        kwargs.update(stdout=out, stderr=subprocess.STDOUT)
        if IS_WINDOWS:
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | 0x08000000  # no window
        self.proc = subprocess.Popen([sys.executable, "-u", *self.args], **kwargs)
        log(f"started {self.name} (pid {self.proc.pid})")

    def stop(self) -> None:
        if not self.running():
            self.proc = None
            return
        self.proc.terminate()
        try:
            self.proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        log(f"stopped {self.name}")
        self.proc = None


def write_state(state, children, sleep_at) -> None:
    payload = {
        "updated_at": datetime.now(EASTERN).isoformat(),
        "market_label": state.label,
        "session_date": state.session_date,
        "session_close": state.close_at.isoformat() if state.close_at else None,
        "early_close": state.early_close,
        "next_open": state.next_open.isoformat(),
        "scanner_running": children["scanner"].running(),
        "pusher_running": bool(children.get("pusher") and children["pusher"].running()),
        "restarts_this_session": sum(c.restarts for c in children.values()),
        "pc_sleep_detected_at": sleep_at,
    }
    path = os.path.join(log_dir(), "worker_state.json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    os.replace(tmp, path)


def main() -> None:
    load_env_file(os.path.join(ROOT, ".env"))
    os.makedirs(log_dir(), exist_ok=True)
    os.environ["SPY_LOG_DIR"] = log_dir()   # children inherit the same folder

    children = {
        "scanner": Child("scanner", ["spy_options_alert_scanner.py"]),
        "pusher": Child("pusher", [os.path.join("worker", "wp_push.py")]),
    }
    if os.environ.get("SPY_ENABLE_TELEGRAM", "0") == "1":
        children["telegram"] = Child("telegram", ["telegram_spy_notifier.py"])
    push_configured = bool(os.environ.get("ARGUS_SPY_INGEST_URL"))
    if not push_configured:
        log("ARGUS_SPY_INGEST_URL not set - WordPress pushing disabled")
        children.pop("pusher")

    stopping = False

    def _term(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, _term)
    signal.signal(signal.SIGINT, _term)

    current_session, last_closed_push, last_loop, sleep_at, awake = None, 0.0, time.time(), None, False
    log(f"supervisor up; logs in {log_dir()}")

    while not stopping:
        now = time.time()
        if now - last_loop > SLEEP_GAP_SECONDS:
            sleep_at = datetime.now(EASTERN).isoformat(timespec="seconds")
            log(f"PC appears to have slept/paused for {int(now - last_loop)} s")
        last_loop = now

        state = session_state()
        if state.session_date != current_session:
            current_session = state.session_date
            for c in children.values():
                c.restarts = 0

        if state.is_open:
            if not awake:
                keep_awake(True); awake = True
            for c in children.values():
                if not c.running():
                    if c.proc is not None:
                        if c.restarts >= MAX_RESTARTS:
                            continue
                        c.restarts += 1
                        log(f"{c.name} exited (code {c.proc.returncode}); restart #{c.restarts}")
                    c.start()
        else:
            if awake:
                keep_awake(False); awake = False
            for c in children.values():
                if c.running():
                    c.stop()
            if push_configured and now - last_closed_push >= CLOSED_PUSH_EVERY:
                last_closed_push = now
                write_state(state, children, sleep_at)
                subprocess.run([sys.executable, os.path.join(HERE, "wp_push.py"), "--once"],
                               cwd=ROOT, env=os.environ.copy(),
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)

        write_state(state, children, sleep_at)
        time.sleep(CHECK_EVERY)

    for c in children.values():
        c.stop()
    keep_awake(False)
    log("supervisor stopped")


if __name__ == "__main__":
    main()
