"""Tests for the four approved measurement fixes, CALL/PUT symmetry, and an
integration test proving the main loop keeps updating while an alert's
result is being tracked."""
import csv
import os
import sys
import tempfile
import threading
import time as real_time
import types
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ET = ZoneInfo("America/New_York")
MARKER = "\nensure_log_dir()\n\nprint(\"Starting SPY options alert scanner"


def source():
    return open(os.path.join(ROOT, "spy_options_alert_scanner.py"), encoding="utf-8").read()


def load(log_dir, include_loop=False):
    os.environ["SPY_LOG_DIR"] = log_dir
    defs, loop = source().split(MARKER, 1)
    mod = types.ModuleType("scanner_under_test")
    mod.__file__ = os.path.join(ROOT, "spy_options_alert_scanner.py")
    exec(compile(defs, mod.__file__, "exec"), mod.__dict__)
    mod._loop_src = MARKER.lstrip("\n") + loop
    return mod


def freeze(mod, when):
    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return when if tz is None else when.astimezone(tz)
    mod.datetime = Frozen


# ---------------------------------------------------------------- fix 1
def bars(volumes, last_start):
    idx = pd.date_range(end=last_start, periods=len(volumes), freq="1min", tz=ET)
    return pd.DataFrame({"Open": 1.0, "High": 1.0, "Low": 1.0, "Close": 1.0, "Volume": volumes}, index=idx)


def test_volume_uses_last_completed_bar_not_in_progress_bar(tmp_path):
    m = load(str(tmp_path))
    data = bars([41000, 52000, 0], pd.Timestamp("2026-11-11 10:15", tz=ET))   # 10:15 bar in progress
    m.record_last_completed_1m_bar(data, now_ts=pd.Timestamp("2026-11-11 10:15:30", tz=ET))
    total, avg, flt = m.update_rolling_bid_volume(0, "x", 0)
    assert (total, flt) == (52000.0, "PASS")          # the 10:14 bar, not the 0 of 10:15
    assert m.MIN_1M_BID_TOTAL == 200                  # threshold unchanged


def test_volume_skips_just_closed_bar_yahoo_has_not_filled(tmp_path):
    m = load(str(tmp_path))
    data = bars([41000, 52000, 0, 0], pd.Timestamp("2026-11-11 10:16", tz=ET))   # 10:15 closed but still 0
    m.record_last_completed_1m_bar(data, now_ts=pd.Timestamp("2026-11-11 10:16:02", tz=ET))
    assert m.update_rolling_bid_volume(0, "x", 0)[:1] == (52000.0,)


def test_volume_too_old_counts_as_missing(tmp_path):
    m = load(str(tmp_path))
    data = bars([41000, 0, 0, 0, 0], pd.Timestamp("2026-11-11 10:16", tz=ET))
    m.record_last_completed_1m_bar(data, now_ts=pd.Timestamp("2026-11-11 10:16:30", tz=ET))
    assert m.update_rolling_bid_volume(0, "x", 0)[2] == "FAIL"


def test_volume_genuinely_zero_still_fails(tmp_path):
    m = load(str(tmp_path))
    m.record_last_completed_1m_bar(bars([0, 0], pd.Timestamp("2026-11-11 10:15", tz=ET)),
                                   now_ts=pd.Timestamp("2026-11-11 10:16:05", tz=ET))
    assert m.update_rolling_bid_volume(0, "x", 0)[2] == "FAIL"


# ---------------------------------------------------------------- fix 2
def test_regime_mapping():
    with tempfile.TemporaryDirectory() as d:
        m = load(d)
        assert m.regime_direction("TRENDING UP") == "CALL"
        assert m.regime_direction("TRENDING DOWN") == "PUT"
        assert m.regime_direction("CHOPPY") == "NEUTRAL"
        assert m.regime_direction("REVERSAL RISK") == "NEUTRAL"


# ---------------------------------------------------------------- fix 3
@pytest.mark.parametrize("when,expected", [
    (datetime(2026, 11, 14, 10, 0, tzinfo=ET), "Market Closed"),     # Saturday
    (datetime(2026, 11, 26, 10, 0, tzinfo=ET), "Market Closed"),     # Thanksgiving
    (datetime(2026, 12, 25, 10, 0, tzinfo=ET), "Market Closed"),     # Christmas
    (datetime(2026, 11, 27, 12, 59, tzinfo=ET), "Midday Chop"),      # early-close day, still open
    (datetime(2026, 11, 27, 13, 0, tzinfo=ET), "Market Closed"),     # 1:00 PM early close
    (datetime(2026, 12, 24, 13, 30, tzinfo=ET), "Market Closed"),
    (datetime(2026, 11, 11, 9, 20, tzinfo=ET), "Pre-Market Analysis"),
    (datetime(2026, 11, 11, 9, 32, tzinfo=ET), "Opening Range"),
    (datetime(2026, 11, 11, 15, 30, tzinfo=ET), "Power Hour"),
    (datetime(2026, 11, 11, 16, 0, tzinfo=ET), "Market Closed"),
    (datetime(2026, 11, 2, 9, 45, tzinfo=ET), "Opening Momentum"),   # first Monday after DST ends
])
def test_market_phase_calendar(tmp_path, when, expected):
    m = load(str(tmp_path))
    freeze(m, when)
    assert m.get_market_phase() == expected


# ---------------------------------------------------------------- fix 4
def write_predictions(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["time", "spy_price", "prediction", "reason"])
        for t, p in rows:
            w.writerow([t, f"{p:.4f}", "WAIT", "text, with, commas"])


def test_yesterday_midpoint_uses_previous_regular_session(tmp_path):
    m = load(str(tmp_path))
    write_predictions(m.PREDICTION_LOG_FILE, [
        ("2026-11-24 10:00:00", 100.0),          # older session: ignored
        ("2026-11-25 09:00:00", 900.0),          # pre-market: ignored
        ("2026-11-25 10:00:00", 500.0),
        ("2026-11-25 15:59:58", 510.0),
        ("2026-11-25 20:00:00", 1000.0),         # after hours: ignored
        ("2026-11-26 10:00:00", 2000.0),         # Thanksgiving rows: ignored
    ])
    freeze(m, datetime(2026, 11, 27, 10, 0, tzinfo=ET))   # previous session = Nov 25
    assert m.get_yesterday_midpoint_direction(505.20) == "CALL"
    assert m.yesterday_midpoint_cache_value == 505.0
    assert m.get_yesterday_midpoint_direction(504.80) == "PUT"
    assert m.get_yesterday_midpoint_direction(505.05) == "NEUTRAL"


def test_yesterday_midpoint_respects_early_close(tmp_path):
    m = load(str(tmp_path))
    write_predictions(m.PREDICTION_LOG_FILE, [
        ("2026-11-27 10:00:00", 600.0),
        ("2026-11-27 12:59:00", 610.0),
        ("2026-11-27 13:30:00", 9999.0),         # after the 1:00 PM close
        ("2026-11-28 11:00:00", 1.0),            # Saturday
    ])
    freeze(m, datetime(2026, 11, 30, 10, 0, tzinfo=ET))
    m.get_yesterday_midpoint_direction(0)
    assert m.yesterday_midpoint_cache_value == 605.0


def test_reverse_reader_stops_early_on_big_file(tmp_path):
    m = load(str(tmp_path))
    rows = [(f"2026-10-{d:02d} 10:00:00", 1.0) for d in range(1, 29)] * 2000 + [("2026-11-25 10:00:00", 7.0)]
    write_predictions(m.PREDICTION_LOG_FILE, rows)
    t = real_time.time()
    prices = m.read_session_prices_from_end(m.PREDICTION_LOG_FILE, "2026-11-25", "09:30", "16:00", block=4096)
    assert prices == [7.0] and real_time.time() - t < 0.5


# ---------------------------------------------------------------- symmetry
def candles(direction):
    base, out = 500.0, []
    for i in range(6):
        step = 0.3 * i * direction
        o = base + step
        c = o + 0.25 * direction
        out.append({"time": str(i), "open": o, "high": max(o, c) + 0.02, "low": min(o, c) - 0.02,
                    "close": c, "completed_epoch": float(i)})
    return out


def run_prediction(m, direction):
    cs = candles(direction)
    price = cs[-1]["close"] + 0.05 * direction
    vwap = 500.0
    hist = m.deque([(i, 500.0 + 0.02 * i * direction) for i in range(45)])
    return m.calculate_direction_prediction(
        price, 0.08 * direction, 0.03 * direction, 0.05 * direction,
        "BULLISH" if direction > 0 else "BEARISH",
        "Strong Bullish" if direction > 0 else "Strong Bearish",
        50000, 50000, "PASS", "ACTIVE", hist, cs, vwap,
        "Above" if direction > 0 else "Below",
        499.0 if direction > 0 else 501.5, 498.5 if direction > 0 else 501.0,
        "Above" if direction > 0 else "Below")


def test_call_and_put_are_mirror_images(tmp_path):
    m = load(str(tmp_path))
    up, down = run_prediction(m, +1), run_prediction(m, -1)
    assert up["prediction"] == "CALL" and down["prediction"] == "PUT", (up["reason"], down["reason"])
    assert up["confidence"] == down["confidence"]
    assert up["regime"] == "TRENDING UP" and down["regime"] == "TRENDING DOWN"


def test_a_plus_filter_mirror_and_regime_factor_counts(tmp_path):
    m = load(str(tmp_path))
    m.get_a_plus_trade_risk = lambda *a: "NORMAL"
    results = {}
    for d, name in ((+1, "CALL"), (-1, "PUT")):
        pdata = run_prediction(m, d)
        pdata.update({"market_phase": "Opening Momentum", "mode_stability": "HIGH",
                      "market_structure": "Higher highs and higher lows" if d > 0 else "Lower highs and lower lows",
                      "current_advantage": "Buyers" if d > 0 else "Sellers", "total_confidence": 90,
                      "pre_market_relative_volume": 0})
        one = [{"open": 500, "high": 500 + 0.1 * i * d if d > 0 else 500.2, "low": 499.8 if d > 0 else 500 + 0.1 * i * d,
                "close": 500, "completed_epoch": i} for i in range(5)]
        tf = {"1m": one, "5m": candles(d)}
        out = m.apply_a_plus_setup_filter(pdata, pdata["vwap"] + 5 * d, tf,
                                          "BULLISH" if d > 0 else "BEARISH",
                                          "Strong Bullish" if d > 0 else "Strong Bearish")
        results[name] = out
        assert f"Market Regime={name}" in out["confluence_factors"]
    assert results["CALL"]["confluence_score"] == results["PUT"]["confluence_score"]
    assert results["CALL"]["a_plus_setup"] == results["PUT"]["a_plus_setup"]


# ---------------------------------------------------------------- loop keeps running after an alert
def test_main_loop_keeps_updating_while_alert_result_is_tracked(tmp_path):
    m = load(str(tmp_path))
    clock = {"t": 1_800_000_000.0}
    loops = {"n": 0}
    status_writes = []

    class Stop(Exception):
        pass

    fake_time = types.SimpleNamespace(
        time=lambda: clock["t"], strftime=real_time.strftime, localtime=real_time.localtime)

    def fake_sleep(s):
        loops["n"] += 1
        clock["t"] += s
        real_time.sleep(0.01)
        if loops["n"] > 80:
            raise Stop()
    fake_time.sleep = fake_sleep
    m.time = fake_time

    def snapshot():
        # flat for 70 s, then a +0.50 jump: passes 10 s / 2 s / 30 s / 60 s alert checks
        price = 500.0 if loops["n"] < 36 else 500.5
        tf = {"1m": candles(1), "3m": candles(1), "5m": candles(1)}
        return (price, 1000.0, "bar", candles(1), tf, 499.0, "Above", 499.5, 498.5, "Above")
    m.get_spy_snapshot = snapshot
    m.refresh_engine_health = lambda: []
    m.refresh_market_breadth = lambda rows: None
    m.get_daily_market_row = lambda ticker: None
    m.yf = None   # no network in tests
    m.opening_confirmation_ready = lambda tf: True

    def force_call(pd_, *a, **k):
        pd_.update({"prediction": "CALL", "a_plus_setup": "YES", "a_plus_wait_reason": "",
                    "confluence_score": 9, "bullish_confluence_score": 9, "bearish_confluence_score": 0,
                    "confluence_factors": ""})
        return pd_
    m.apply_a_plus_setup_filter = force_call
    real_save = m.save_live_status
    m.save_live_status = lambda *a, **k: (status_writes.append(loops["n"]), real_save(*a, **k))

    tracking = {"started": None, "finished": None}

    def slow_tracker(option_type, entry, a_plus="YES"):
        tracking["started"] = loops["n"]
        real_time.sleep(0.5)                 # stands in for the 120 s of sampling
        tracking["finished"] = loops["n"]
    m.track_alert_result = slow_tracker

    with pytest.raises(Stop):
        exec(compile(m._loop_src, m.__file__, "exec"), m.__dict__)
    alerts = list(csv.reader(open(os.path.join(str(tmp_path), "spy_options_alerts.csv"))))
    assert len(alerts) == 2, alerts                                   # header + exactly one alert
    assert tracking["started"] is not None
    assert tracking["finished"] - tracking["started"] >= 5            # loop kept iterating meanwhile
    during = [n for n in status_writes if tracking["started"] <= n <= tracking["finished"]]
    assert len(during) >= 5                                           # live status kept updating
