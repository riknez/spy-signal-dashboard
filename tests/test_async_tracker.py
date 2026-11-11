"""The background tracker must (a) return immediately and (b) write exactly
the rows the original blocking tracker wrote, for the same price path."""
import csv, os, sys, tempfile, time, types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_scanner(log_dir):
    os.environ["SPY_LOG_DIR"] = log_dir
    src = open(os.path.join(ROOT, "spy_options_alert_scanner.py"), encoding="utf-8").read()
    src = src.split("\nensure_log_dir()\n\nprint(\"Starting SPY options alert scanner")[0]
    mod = types.ModuleType("scanner_under_test")
    mod.__file__ = os.path.join(ROOT, "spy_options_alert_scanner.py")
    exec(compile(src, mod.__file__, "exec"), mod.__dict__)
    return mod


def fake_clock(mod, prices):
    seq = iter(prices)
    mod.get_spy_price = lambda: next(seq)
    real_sleep = time.sleep
    mod.time = types.SimpleNamespace(**{k: getattr(time, k) for k in ("time", "strftime", "localtime")})
    mod.time.sleep = lambda s: real_sleep(0.05)   # 30/30/60s compressed


def read(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return [{k: v for k, v in r.items() if k != "time"} for r in csv.DictReader(fh)]


def test_async_matches_blocking_and_does_not_block():
    prices = [500.10, 500.30, 499.70]
    with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
        m1 = load_scanner(a); m1.ensure_log_dir(); fake_clock(m1, prices)
        m1.track_alert_result("CALL", 500.00, "YES")          # original, blocking
        m2 = load_scanner(b); m2.ensure_log_dir(); fake_clock(m2, prices)
        t0 = time.time()
        worker = m2.track_alert_result_async("CALL", 500.00, "YES")
        returned_after = time.time() - t0
        worker.join(5)
        assert returned_after < 0.05, returned_after
        for name in ("spy_options_alert_results.csv", "spy_options_a_plus_results.csv"):
            r1, r2 = read(os.path.join(a, name)), read(os.path.join(b, name))
            assert r1 == r2 and len(r1) == 1, (r1, r2)
        assert r1[0]["result"] == "WIN"   # best move +0.30 >= 0.20, checked first


def test_timestamps_are_eastern():
    with tempfile.TemporaryDirectory() as a:
        m = load_scanner(a)
        from datetime import datetime
        from zoneinfo import ZoneInfo
        assert m.eastern_strftime("%Y-%m-%d %H") == datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H")


def test_log_dir_env_override():
    with tempfile.TemporaryDirectory() as a:
        m = load_scanner(a)
        assert m.LOG_DIR == a and m.PREDICTION_LOG_FILE.startswith(a)
