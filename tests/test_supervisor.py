"""Supervisor: starts children when open, restarts crashes, stops at close."""
import importlib, json, os, sys, tempfile, threading, time
from datetime import datetime
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "worker"))


def test_open_restart_close(monkeypatch):
    import run_market_hours as r
    import market_session as m
    tmp = tempfile.mkdtemp()
    monkeypatch.setenv("SPY_LOG_DIR", tmp)
    monkeypatch.delenv("ARGUS_SPY_INGEST_URL", raising=False)
    crash = os.path.join(tmp, "crash.py")
    open(crash, "w").write("import time; time.sleep(1); raise SystemExit(3)\n")
    real_child = r.Child
    monkeypatch.setattr(r, "Child", lambda name, args: real_child(name, [crash]))
    monkeypatch.setattr(r, "CHECK_EVERY", 0.5)
    t0 = time.time()
    real = m.session_state
    monkeypatch.setattr(r, "session_state", lambda now=None: real(datetime(2026, 11, 11, 10 if time.time() - t0 < 5 else 17, 0, tzinfo=m.EASTERN)))
    threading.Timer(8, lambda: os.kill(os.getpid(), 15)).start()
    r.main()
    log = open(os.path.join(tmp, "supervisor.log")).read()
    state = json.load(open(os.path.join(tmp, "worker_state.json")))
    assert "started scanner" in log and "restart #1" in log
    assert state["market_label"] == "HISTORICAL" and state["scanner_running"] is False
