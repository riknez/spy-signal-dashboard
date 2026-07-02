import base64
import binascii
import csv
import html
import json
import math
import os
import re
import secrets
import socket
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Lock
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo


def load_env_file(path=".env"):
    if not os.path.exists(path):
        return

    with open(path, "r", encoding="utf-8") as file:
        for raw_line in file:
            line = raw_line.strip()

            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip("\"'")

            if key and key not in os.environ:
                os.environ[key] = value


APP_ROOT = os.path.dirname(os.path.abspath(__file__))


def app_path(*parts):
    return os.path.join(APP_ROOT, *parts)


load_env_file(app_path(".env"))

DASHBOARD_VERSION = "1.1.8"
DASHBOARD_BUILD_TIME = datetime.now(ZoneInfo("America/New_York")).strftime(
    "%Y-%m-%d %H:%M ET"
)
DASHBOARD_FILE = os.path.abspath(__file__)
DASHBOARD_HOSTNAME = socket.gethostname()
DASHBOARD_BUILD_SOURCE = os.getenv(
    "DASHBOARD_BUILD_SOURCE",
    "local" if os.name == "nt" else "godaddy"
).strip().lower() or "local"

PREDICTION_FILE = os.path.join("logs", "spy", "spy_direction_predictions.csv")
ALERT_FILE = os.path.join("logs", "spy", "spy_options_alerts.csv")
RESULT_FILE = os.path.join("logs", "spy", "spy_options_alert_results.csv")
A_PLUS_RESULT_FILE = os.path.join("logs", "spy", "spy_options_a_plus_results.csv")
ENGINE_HEALTH_FILE = os.path.join("logs", "spy", "spy_engine_health.csv")
MARKET_BREADTH_FILE = os.path.join("logs", "spy", "spy_market_breadth.csv")
LIVE_STATUS_FILE = app_path("logs", "spy", "spy_live_status.json")
LEVEL_HITS_FILE = os.path.join("logs", "spy", "spy_level_hits.json")
HISTORY_DIR = os.path.join("logs", "spy", "history")
AI_BENCHMARK_STATE_FILE = os.path.join("logs", "spy", "ai_paper_benchmark_state.json")
AI_BENCHMARK_TRADES_FILE = os.path.join("logs", "spy", "ai_paper_benchmark_trades.csv")
AI_BENCHMARK_CYCLES_FILE = os.path.join("logs", "spy", "ai_paper_benchmark_cycles.json")
LIVE_STATUS_STALE_SECONDS = 60
LIVE_STATUS_DISCONNECTED_SECONDS = 180
HOST = os.getenv("DASHBOARD_HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", os.getenv("DASHBOARD_PORT", "8000")))
DASHBOARD_USERNAME = ""
DASHBOARD_PASSWORD = ""
level_set_id = None
previous_level_set_id = None
level_set_values = None
level_set_generation = 0
last_hit_bull_level = 0
last_hit_bear_level = 0
session_extreme_date = None
session_high_price = None
session_low_price = None
level_set_high_price = None
level_set_low_price = None
level_hit_timestamp = {"bull": {}, "bear": {}}
level_first_hit_times = {}
level_first_hit_epochs = {}
level_hits_loaded_date = None
last_saved_hit_time = None
last_history_archive_write = 0
LEVEL_SET_RESET_DISTANCE = 0.20
LEVEL_ACTIVE_SECONDS = 30
CONFIRMATION_HOLD_SECONDS = 5
CORRECTION_BAR_COUNT = 3
CORRECTION_MIN_MOVE = 0.05
correction_activation = {"mode": "NEUTRAL", "time": None}
last_live_api_status = None
last_daily_midpoint_analysis = None
dashboard_engine_source = "local_csv"
dashboard_engine_unique_count = 0
ai_benchmark_lock = Lock()

AI_BENCHMARK_STARTING_BALANCE = 1000.0
AI_BENCHMARK_FAILURE_BALANCE = 500.0
AI_BENCHMARK_ENTRY_PREMIUM = 1.0
AI_BENCHMARK_SYNTHETIC_DELTA = 0.50
AI_BENCHMARK_MAX_EQUITY_POINTS = 500
AI_BENCHMARK_DAILY_MIN_TARGET = 3
AI_BENCHMARK_DAILY_MAX_TRADES = 10
AI_BENCHMARK_DAILY_STOP_AMOUNT = AI_BENCHMARK_STARTING_BALANCE * 0.05
AI_BENCHMARK_CONTINUE_AFTER_PROFIT = os.getenv(
    "AI_BENCHMARK_CONTINUE_AFTER_PROFIT",
    ""
).strip().lower() in ("1", "true", "yes", "on")
PAPER_RESEARCH_MODE = True
AI_BENCHMARK_TRADE_HEADERS = (
    "time",
    "exit_time",
    "cycle",
    "signal",
    "direction",
    "entry_spy_price",
    "exit_spy_price",
    "simulated_contract_entry",
    "simulated_contract_exit",
    "duration_minutes",
    "pnl",
    "entry_reason",
    "reason",
    "result"
)

LEVEL_HIT_FIELDS = (
    "bull_trigger_first_hit_time",
    "bull_confirmation_first_hit_time",
    "bull_breakout_first_hit_time",
    "bear_trigger_first_hit_time",
    "bear_confirmation_first_hit_time",
    "bear_breakdown_first_hit_time"
)


def market_date_text():
    return datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")


def get_dashboard_build_metadata():
    return {
        "dashboard_version": DASHBOARD_VERSION,
        "dashboard_file": DASHBOARD_FILE,
        "dashboard_build_time": DASHBOARD_BUILD_TIME,
        "dashboard_hostname": DASHBOARD_HOSTNAME,
        "build_time": DASHBOARD_BUILD_TIME,
        "build_source": DASHBOARD_BUILD_SOURCE
    }


def empty_level_hit_times():
    return {field: None for field in LEVEL_HIT_FIELDS}


def save_level_hits(latest_live_price=None):
    global last_saved_hit_time

    saved_at = datetime.now(ZoneInfo("America/New_York")).isoformat()
    payload = {
        "trading_date": market_date_text(),
        "level_set_id": level_set_id,
        "latest_live_price": parse_float(latest_live_price),
        "saved_hit_times_file_path": os.path.abspath(LEVEL_HITS_FILE),
        "last_saved_hit_time": saved_at,
        "hit_epochs": level_first_hit_epochs
    }
    payload.update(level_first_hit_times)
    temporary_file = f"{LEVEL_HITS_FILE}.tmp"
    try:
        os.makedirs(os.path.dirname(LEVEL_HITS_FILE), exist_ok=True)
        with open(temporary_file, "w", encoding="utf-8") as file:
            json.dump(payload, file, indent=2)
        os.replace(temporary_file, LEVEL_HITS_FILE)
        last_saved_hit_time = saved_at
    except OSError as error:
        print(f"Unable to save level hit times: {error}")


def ensure_level_hits_loaded():
    global level_first_hit_times, level_first_hit_epochs
    global level_hits_loaded_date, last_saved_hit_time
    global last_hit_bull_level, last_hit_bear_level, level_hit_timestamp

    today = market_date_text()
    if level_hits_loaded_date == today:
        return

    level_first_hit_times = empty_level_hit_times()
    level_first_hit_epochs = {}
    last_saved_hit_time = None
    level_hits_loaded_date = today
    loaded_today = False
    try:
        with open(LEVEL_HITS_FILE, "r", encoding="utf-8") as file:
            payload = json.load(file)
        if payload.get("trading_date") == today:
            loaded_today = True
            for field in LEVEL_HIT_FIELDS:
                level_first_hit_times[field] = payload.get(field)
            level_first_hit_epochs = {
                key: float(value)
                for key, value in payload.get("hit_epochs", {}).items()
                if key in LEVEL_HIT_FIELDS and value is not None
            }
            last_saved_hit_time = payload.get("last_saved_hit_time")
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        pass

    # Daily first-hit timestamps are historical replay data. Live card state
    # belongs only to the current structure level set and must not be restored
    # from earlier levels reached during the same trading day.
    last_hit_bull_level = 0
    last_hit_bear_level = 0
    level_hit_timestamp = {"bull": {}, "bear": {}}
    if not loaded_today:
        save_level_hits()


def record_first_level_hit(field, tier, direction, latest_live_price):
    hit_now = datetime.now(ZoneInfo("America/New_York"))
    hit_epoch = hit_now.timestamp()
    level_hit_timestamp[direction][str(tier)] = hit_epoch
    if not level_first_hit_times.get(field):
        level_first_hit_times[field] = hit_now.isoformat()
        level_first_hit_epochs[field] = hit_epoch
        save_level_hits(latest_live_price)


def read_saved_level_hits():
    ensure_level_hits_loaded()
    return dict(level_first_hit_times)


def read_predictions():
    if not os.path.exists(PREDICTION_FILE):
        return []

    with open(PREDICTION_FILE, "r", newline="") as file:
        return list(csv.DictReader(file))


def read_recent_predictions(limit=300, tail_bytes=2 * 1024 * 1024):
    if not os.path.exists(PREDICTION_FILE):
        return []

    try:
        with open(PREDICTION_FILE, "rb") as file:
            header = file.readline().decode("utf-8", errors="replace").rstrip("\r\n")
            file.seek(0, os.SEEK_END)
            end = file.tell()
            start = max(len(header) + 1, end - tail_bytes)
            file.seek(start)
            if start > len(header) + 1:
                file.readline()
            lines = file.read().decode("utf-8", errors="replace").splitlines()
        recent_lines = [line for line in lines if line.strip()][-limit:]
        return list(csv.DictReader([header, *recent_lines]))
    except OSError:
        return []


def read_live_status():
    attempted_path = os.path.abspath(LIVE_STATUS_FILE)
    server_epoch = time.time()
    raw_preview = ""

    if not os.path.exists(LIVE_STATUS_FILE):
        return {
            "available": False,
            "path": attempted_path,
            "live_status_file_path": attempted_path,
            "live_status_raw_first_200_chars": raw_preview,
            "live_status_exists": False,
            "update_epoch": None,
            "server_epoch": server_epoch,
            "data_age": None,
            "data_age_seconds": None,
            "feed_connected": False,
            "analysis_delayed": False,
            "feed_status": "DASHBOARD FEED DISCONNECTED",
            "stale": True,
            "stale_reason": "Live status file is missing.",
            "error": f"Live status file missing: {attempted_path}"
        }

    try:
        with open(LIVE_STATUS_FILE, "r", encoding="utf-8") as file:
            raw_status = file.read()
        raw_preview = raw_status[:200]
        status = json.loads(raw_status)
        update_epoch_value = status.get("update_epoch")
        if update_epoch_value is None:
            update_epoch_value = status.get("updated_at_epoch")
        updated_at_epoch = float(update_epoch_value)
        if not math.isfinite(updated_at_epoch):
            raise ValueError("update_epoch is not a finite number")
        data_age = server_epoch - updated_at_epoch
        spy_price_value = status.get("current_spy_price")
        if spy_price_value is None:
            spy_price_value = status.get("spy_price")
        spy_price = float(spy_price_value)
        if not math.isfinite(spy_price):
            raise ValueError("current_spy_price is not a finite number")
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        return {
            "available": False,
            "path": attempted_path,
            "live_status_file_path": attempted_path,
            "live_status_raw_first_200_chars": raw_preview,
            "live_status_exists": True,
            "update_epoch": None,
            "server_epoch": server_epoch,
            "data_age": None,
            "data_age_seconds": None,
            "feed_connected": False,
            "analysis_delayed": False,
            "feed_status": "DASHBOARD FEED DISCONNECTED",
            "stale": True,
            "stale_reason": f"Live status parse error: {error}",
            "error": f"Live status parse error: {error}"
        }

    feed_connected = data_age <= LIVE_STATUS_DISCONNECTED_SECONDS
    analysis_delayed = LIVE_STATUS_STALE_SECONDS < data_age <= LIVE_STATUS_DISCONNECTED_SECONDS
    feed_status = (
        "FEED LIVE"
        if data_age <= LIVE_STATUS_STALE_SECONDS
        else "PRICE LIVE â€” ANALYSIS DELAYED"
        if analysis_delayed
        else "DASHBOARD FEED DISCONNECTED"
    )
    stale_reason = (
        ""
        if data_age <= LIVE_STATUS_STALE_SECONDS
        else f"Price feed age is {data_age:.1f}s; analysis may be delayed."
        if analysis_delayed
        else f"Price feed age is {data_age:.1f}s; disconnected threshold is {LIVE_STATUS_DISCONNECTED_SECONDS}s."
    )
    return {
        "available": True,
        "path": attempted_path,
        "live_status_file_path": attempted_path,
        "live_status_raw_first_200_chars": raw_preview,
        "live_status_exists": True,
        "spy_price": f"{spy_price:.4f}",
        "updated_at": status.get("last_update", status.get("updated_at", "N/A")),
        "data_source": status.get("data_source", "legacy live status"),
        "update_epoch": updated_at_epoch,
        "server_epoch": server_epoch,
        "data_age": data_age,
        "data_age_seconds": data_age,
        "data_age_text": f"{data_age:.1f}s",
        "feed_connected": feed_connected,
        "analysis_delayed": analysis_delayed,
        "feed_status": feed_status,
        "stale": data_age > LIVE_STATUS_DISCONNECTED_SECONDS,
        "stale_reason": stale_reason,
        "latest_engine_health": status.get("latest_engine_health"),
        "latest_market_breadth": status.get("latest_market_breadth"),
        "latest_engine_health_rows": status.get("latest_engine_health_rows"),
        "latest_market_breadth_rows": status.get("latest_market_breadth_rows"),
        "latest_prediction_history": status.get("latest_prediction_history"),
        "latest_alert_history": status.get("latest_alert_history"),
        "latest_alert_result_history": status.get("latest_alert_result_history"),
        "latest_accuracy_history": status.get("latest_accuracy_history"),
        "latest_paper_trade_history": status.get("latest_paper_trade_history"),
        "latest_prediction_history_count": status.get("latest_prediction_history_count", 0),
        "latest_alert_history_count": status.get("latest_alert_history_count", 0),
        "latest_alert_result_history_count": status.get("latest_alert_result_history_count", 0),
        "latest_paper_trade_history_count": status.get("latest_paper_trade_history_count", 0)
    }


def read_alerts():
    if not os.path.exists(ALERT_FILE):
        return []

    with open(ALERT_FILE, "r", newline="") as file:
        return list(csv.DictReader(file))


def read_results():
    if not os.path.exists(RESULT_FILE):
        return []

    with open(RESULT_FILE, "r", newline="") as file:
        return list(csv.DictReader(file))


def read_a_plus_results():
    if not os.path.exists(A_PLUS_RESULT_FILE):
        return []

    with open(A_PLUS_RESULT_FILE, "r", newline="") as file:
        return list(csv.DictReader(file))


def read_engine_health():
    global dashboard_engine_source, dashboard_engine_unique_count

    local_rows = []

    if os.path.exists(ENGINE_HEALTH_FILE):
        try:
            with open(ENGINE_HEALTH_FILE, "r", newline="") as file:
                local_rows = list(csv.DictReader(file))
        except (OSError, csv.Error):
            local_rows = []

    def latest_rows_by_ticker(rows):
        latest_by_ticker = {}
        latest_keys = {}

        for row_index, row in enumerate(rows):
            if not isinstance(row, dict):
                continue

            ticker = row.get("ticker") or row.get("symbol")
            if not ticker:
                continue

            normalized_row = dict(row)
            normalized_row.setdefault("ticker", ticker)
            timestamp = str(
                row.get("time")
                or row.get("timestamp")
                or row.get("last_update")
                or row.get("updated_at")
                or ""
            )
            row_key = (timestamp, row_index)

            if ticker not in latest_keys or row_key >= latest_keys[ticker]:
                latest_keys[ticker] = row_key
                latest_by_ticker[ticker] = normalized_row

        return list(latest_by_ticker.values())

    local_engine_rows = latest_rows_by_ticker(local_rows)
    server_mode = (
        os.name != "nt"
        or os.environ.get("RENDER", "").strip().lower() in {"1", "true", "yes"}
    )

    if local_engine_rows and not server_mode:
        dashboard_engine_source = "local_csv"
        dashboard_engine_unique_count = len(local_engine_rows)
        return local_engine_rows

    live_status = read_live_status()
    pushed_rows = live_status.get("latest_engine_health_rows")

    if not isinstance(pushed_rows, list) or not pushed_rows:
        pushed_rows = live_status.get("latest_engine_health")

    if isinstance(pushed_rows, dict):
        pushed_rows = [pushed_rows] if pushed_rows else []
    elif isinstance(pushed_rows, list):
        pushed_rows = [row for row in pushed_rows if isinstance(row, dict)]
    else:
        pushed_rows = []

    pushed_engine_rows = latest_rows_by_ticker(pushed_rows)
    prefer_pushed = pushed_engine_rows and (
        not local_engine_rows
        or len(pushed_rows) > len(local_rows)
        or len(pushed_engine_rows) > len(local_engine_rows)
    )

    if prefer_pushed:
        dashboard_engine_source = "pushed_live_status"
        dashboard_engine_unique_count = len(pushed_engine_rows)
        return pushed_engine_rows

    dashboard_engine_source = "local_csv"
    dashboard_engine_unique_count = len(local_engine_rows)
    return local_engine_rows


def read_market_breadth():
    rows = []

    if os.path.exists(MARKET_BREADTH_FILE):
        try:
            with open(MARKET_BREADTH_FILE, "r", newline="") as file:
                rows = list(csv.DictReader(file))
        except (OSError, csv.Error):
            rows = []

    if rows:
        return rows[-1]

    live_status = read_live_status()
    pushed_row = live_status.get("latest_market_breadth")

    if isinstance(pushed_row, dict) and pushed_row:
        return pushed_row

    pushed_rows = live_status.get("latest_market_breadth_rows")

    if isinstance(pushed_rows, list):
        valid_rows = [row for row in pushed_rows if isinstance(row, dict) and row]
        return valid_rows[-1] if valid_rows else None

    return None


def write_json_atomic(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary_path = f"{path}.tmp"
    with open(temporary_path, "w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2)
    os.replace(temporary_path, path)


def infer_level_hit_times(day_rows):
    checks = (
        ("bull_trigger_first_hit_time", "bullish_trigger", lambda price, level: price >= level),
        ("bull_confirmation_first_hit_time", "bullish_confirmation", lambda price, level: price >= level),
        ("bull_breakout_first_hit_time", "bullish_breakout", lambda price, level: price >= level),
        ("bear_trigger_first_hit_time", "bearish_trigger", lambda price, level: price <= level),
        ("bear_confirmation_first_hit_time", "bearish_confirmation", lambda price, level: price <= level),
        ("bear_breakdown_first_hit_time", "bearish_breakdown", lambda price, level: price <= level)
    )
    hit_times = empty_level_hit_times()
    for field, level_field, comparison in checks:
        for row in day_rows:
            price = parse_float(row.get("spy_price"))
            level = parse_float(row.get(level_field))
            if price is not None and level is not None and comparison(price, level):
                hit_times[field] = row.get("time")
                break
    return hit_times


def build_archive_payloads(trading_date, day_rows, alert_rows, result_rows):
    prices = [parse_float(row.get("spy_price")) for row in day_rows]
    prices = [price for price in prices if price is not None]
    if not prices:
        return None

    latest = day_rows[-1]
    open_price, close_price = prices[0], prices[-1]
    high_price, low_price = max(prices), min(prices)
    price_range = high_price - low_price
    direction = "Bullish" if close_price > open_price else "Bearish" if close_price < open_price else "Flat"
    hit_times = infer_level_hit_times(day_rows)
    if trading_date == market_date_text():
        for field, value in read_saved_level_hits().items():
            if value:
                hit_times[field] = value

    trend_midpoint = (high_price + low_price) / 2
    trend_box = (
        "Above midpoint - buyers stronger"
        if close_price > trend_midpoint else
        "Below midpoint - sellers stronger"
        if close_price < trend_midpoint else "At midpoint - neutral"
    )
    market_source = prices[-13:-1] or prices[:-1] or prices
    market_high, market_low = max(market_source), min(market_source)
    market_box = (
        "ABOVE BOX = Bullish" if close_price > market_high
        else "BELOW BOX = Bearish" if close_price < market_low
        else "INSIDE BOX = Wait"
    )
    bullish_score = int(parse_float(latest.get("bullish_confluence_score")) or 0)
    bearish_score = int(parse_float(latest.get("bearish_confluence_score")) or 0)
    confluence_score = max(bullish_score, bearish_score)
    regime = latest.get("regime") or "CHOPPY"
    a_plus = (latest.get("a_plus_setup") or "NO").upper()
    if regime.upper() == "CHOPPY":
        final_decision = "NEUTRAL / CHOP - WAIT FOR CONFIRMATION"
    elif a_plus == "YES" and bullish_score >= 8:
        final_decision = "CALL MODE"
    elif a_plus == "YES" and bearish_score >= 8:
        final_decision = "PUT MODE"
    elif bullish_score >= 6:
        final_decision = "WATCHING BULLISH TRIGGER"
    elif bearish_score >= 6:
        final_decision = "WATCHING BEARISH TRIGGER"
    else:
        final_decision = "WAIT"

    best_row = max(
        day_rows,
        key=lambda row: parse_float(row.get("confluence_score")) or parse_float(row.get("confidence")) or 0
    )
    best_setup = (
        f"{best_row.get('prediction', 'WAIT')} at {best_row.get('time', 'N/A')} "
        f"with {best_row.get('confluence_score') or best_row.get('confidence') or '0'} score"
    )
    fakeouts = []
    for row in day_rows:
        prediction = (row.get("prediction") or "WAIT").upper()
        row_price = parse_float(row.get("spy_price"))
        if row_price is None or prediction not in ("CALL", "PUT"):
            continue
        wrong = (prediction == "CALL" and close_price < row_price) or (
            prediction == "PUT" and close_price > row_price
        )
        if wrong:
            fakeouts.append(row)
    worst_fakeout = "No clear directional fakeout recorded."
    if fakeouts:
        fakeout = max(fakeouts, key=lambda row: parse_float(row.get("confidence")) or 0)
        worst_fakeout = (
            f"{fakeout.get('prediction')} at {fakeout.get('time')} "
            f"with {fakeout.get('confidence', 'N/A')}% confidence"
        )

    move_quality = abs(close_price - open_price) / price_range if price_range else 0
    trade_grade = "A" if move_quality >= 0.65 else "B" if move_quality >= 0.35 else "C"
    day_alerts = [row for row in alert_rows if (row.get("time") or "").startswith(trading_date)]
    day_results = [row for row in result_rows if (row.get("time") or "").startswith(trading_date)]
    wins = sum(row.get("result") == "WIN" for row in day_results)
    losses = sum(row.get("result") == "LOSS" for row in day_results)
    flats = sum(row.get("result") == "FLAT" for row in day_results)

    market_summary = {
        "Date": trading_date,
        "Open": open_price,
        "High": high_price,
        "Low": low_price,
        "Close": close_price,
        "Daily Direction": direction,
        "Range": price_range
    }
    level_hits = {
        "Date": trading_date,
        "Bull Trigger Hit Time": hit_times["bull_trigger_first_hit_time"],
        "Bull Confirmation Hit Time": hit_times["bull_confirmation_first_hit_time"],
        "Bull Breakout Hit Time": hit_times["bull_breakout_first_hit_time"],
        "Bear Trigger Hit Time": hit_times["bear_trigger_first_hit_time"],
        "Bear Confirmation Hit Time": hit_times["bear_confirmation_first_hit_time"],
        "Bear Breakdown Hit Time": hit_times["bear_breakdown_first_hit_time"],
        **hit_times
    }
    market_recap = {
        "Date": trading_date,
        "Market Regime": regime,
        "Trend Box": trend_box,
        "Market Box": market_box,
        "Confluence Score": confluence_score,
        "Final Dashboard Decision": final_decision,
        "Best Setup": best_setup,
        "Worst Fakeout": worst_fakeout,
        "Trade Grade": trade_grade,
        "Reason": latest.get("a_plus_wait_reason") or latest.get("reason") or "No reason recorded."
    }
    scanner_stats = {
        "Date": trading_date,
        "Prediction Rows": len(day_rows),
        "CALL Predictions": sum((row.get("prediction") or "").upper() == "CALL" for row in day_rows),
        "PUT Predictions": sum((row.get("prediction") or "").upper() == "PUT" for row in day_rows),
        "WAIT Predictions": sum((row.get("prediction") or "").upper() == "WAIT" for row in day_rows),
        "A+ Setups": sum((row.get("a_plus_setup") or "").upper() == "YES" for row in day_rows),
        "Alerts": len(day_alerts),
        "Tracked Results": len(day_results),
        "Wins": wins,
        "Losses": losses,
        "Flats": flats,
        "Win Rate Excluding Flats": (wins / (wins + losses) * 100) if wins + losses else 0
    }
    return market_summary, level_hits, market_recap, scanner_stats


def update_historical_market_archive(rows, alert_rows, result_rows):
    global last_history_archive_write

    now = time.time()
    if now - last_history_archive_write < 30:
        return
    grouped_rows = {}
    for row in rows:
        timestamp = row.get("time") or ""
        if len(timestamp) >= 10:
            grouped_rows.setdefault(timestamp[:10], []).append(row)
    for trading_date, day_rows in grouped_rows.items():
        try:
            payloads = build_archive_payloads(trading_date, day_rows, alert_rows, result_rows)
            if not payloads:
                continue
            day_directory = os.path.join(HISTORY_DIR, trading_date)
            for filename, payload in zip(
                ("market_summary.json", "level_hits.json", "market_recap.json", "scanner_stats.json"),
                payloads
            ):
                write_json_atomic(os.path.join(day_directory, filename), payload)
        except (OSError, TypeError, ValueError) as error:
            print(f"Unable to update historical archive for {trading_date}: {error}")
    last_history_archive_write = now


def build_historical_market_archive():
    if not os.path.exists(HISTORY_DIR):
        return '<p class="empty">No historical market archive has been created yet.</p>'

    day_sections = []
    for trading_date in sorted(os.listdir(HISTORY_DIR), reverse=True):
        day_directory = os.path.join(HISTORY_DIR, trading_date)
        if not os.path.isdir(day_directory):
            continue
        payloads = {}
        for filename in ("market_summary.json", "level_hits.json", "market_recap.json", "scanner_stats.json"):
            try:
                with open(os.path.join(day_directory, filename), "r", encoding="utf-8") as file:
                    payloads[filename] = json.load(file)
            except (OSError, json.JSONDecodeError):
                payloads[filename] = {}
        summary = payloads["market_summary.json"]
        recap = payloads["market_recap.json"]
        hits = payloads["level_hits.json"]
        stats = payloads["scanner_stats.json"]
        readable_hit_fields = {
            "Bull Trigger Hit Time",
            "Bull Confirmation Hit Time",
            "Bull Breakout Hit Time",
            "Bear Trigger Hit Time",
            "Bear Confirmation Hit Time",
            "Bear Breakdown Hit Time"
        }
        hit_rows = "".join(
            f"<li><b>{escape_value(field.replace('_first_hit_time', '').replace('_', ' ').title())}:</b> {escape_value(value or 'Not hit')}</li>"
            for field, value in hits.items() if field in readable_hit_fields
        )
        day_sections.append(f"""
        <details class="archive-day">
          <summary>{escape_value(trading_date)} | {escape_value(recap.get("Final Dashboard Decision"))} | Grade {escape_value(recap.get("Trade Grade"))}</summary>
          <div class="archive-grid">
            <div><h3>Market Summary</h3><p>Open: {escape_value(summary.get("Open"))} | High: {escape_value(summary.get("High"))} | Low: {escape_value(summary.get("Low"))} | Close: {escape_value(summary.get("Close"))}</p></div>
            <div><h3>Structure</h3><p>{escape_value(recap.get("Market Regime"))} | {escape_value(recap.get("Trend Box"))} | {escape_value(recap.get("Market Box"))}</p></div>
            <div><h3>Review</h3><p><b>Best Setup:</b> {escape_value(recap.get("Best Setup"))}</p><p><b>Worst Fakeout:</b> {escape_value(recap.get("Worst Fakeout"))}</p></div>
            <div><h3>Scanner Stats</h3><p>{escape_value(stats.get("Tracked Results"))} results | {escape_value(stats.get("Wins"))} wins | {escape_value(stats.get("Win Rate Excluding Flats"))}% win rate</p></div>
          </div>
          <h3>Level First Hits</h3><ul>{hit_rows}</ul>
          <p><b>Reason:</b> {escape_value(recap.get("Reason"))}</p>
        </details>
        """)
    return (
        '<section class="historical-archive">'
        '<p class="note">Daily files are stored under logs/spy/history/YYYY-MM-DD for replay, training, accuracy analysis, and future website expansion.</p>'
        + "".join(day_sections)
        + "</section>"
    )


def escape_value(value, fallback="N/A"):
    if value in (None, ""):
        value = fallback

    return html.escape(str(value))


def parse_float(value):
    if isinstance(value, (int, float)):
        return float(value)
    if value is None:
        return None

    cleaned = str(value).replace("$", "").replace(",", "").strip()
    match = re.search(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)", cleaned)
    if not match:
        return None

    try:
        return float(match.group(0))
    except (TypeError, ValueError):
        return None


def new_ai_benchmark_state(cycle=1, previous_cycle=None):
    now = datetime.now(ZoneInfo("America/New_York"))
    return {
        "mode": "AI PAPER BENCHMARK",
        "paper_only": True,
        "cycle": cycle,
        "status": "Active",
        "starting_balance": AI_BENCHMARK_STARTING_BALANCE,
        "current_balance": AI_BENCHMARK_STARTING_BALANCE,
        "open_position": None,
        "closed_trades": [],
        "equity_curve": [{
            "time": now.isoformat(),
            "epoch": now.timestamp(),
            "equity": AI_BENCHMARK_STARTING_BALANCE
        }],
        "daily_pnl": {},
        "milestones_hit": [],
        "last_signal_key": "",
        "last_trade": None,
        "benchmark_bias": "Neutral",
        "benchmark_confidence": 0,
        "benchmark_entry_reason": "Waiting for benchmark evidence.",
        "reason_not_trading": "Waiting for benchmark evidence.",
        "next_condition_needed": "Need directional evidence and a valid structure stop.",
        "trades_today": 0,
        "daily_goal": "3-10",
        "daily_status": "Waiting for setup",
        "continue_benchmark": AI_BENCHMARK_CONTINUE_AFTER_PROFIT,
        "last_event": "No paper trade yet.",
        "paper_research_mode": PAPER_RESEARCH_MODE,
        "paper_mode": "LIVE SESSION",
        "paper_last_block_reason": "Blocked: no directional edge",
        "paper_entry_rule_used": "None",
        "paper_exit_rule_used": "Structure stop/target, opposite evidence, or session close",
        "paper_last_evaluation_time": now.isoformat(),
        "paper_trade_candidate_direction": None,
        "paper_trade_candidate_confidence": 0,
        "paper_stop_source": "none",
        "paper_stop": None,
        "paper_target": None,
        "paper_risk_per_share": None,
        "paper_reward_per_share": None,
        "paper_risk_reward": None,
        "paper_stop_computed": False,
        "paper_block_stage": "pre_compute",
        "max_equity": AI_BENCHMARK_STARTING_BALANCE,
        "max_drawdown": 0.0,
        "cycle_started_at": now.isoformat(),
        "previous_cycle": previous_cycle
    }


def load_ai_benchmark_state():
    try:
        with open(AI_BENCHMARK_STATE_FILE, "r", encoding="utf-8") as file:
            state = json.load(file)
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return new_ai_benchmark_state()

    defaults = new_ai_benchmark_state(int(state.get("cycle") or 1))
    for key, value in defaults.items():
        state.setdefault(key, value)
    if not isinstance(state.get("closed_trades"), list):
        state["closed_trades"] = []
    if not isinstance(state.get("equity_curve"), list):
        state["equity_curve"] = defaults["equity_curve"]
    if not isinstance(state.get("daily_pnl"), dict):
        state["daily_pnl"] = {}
    if not isinstance(state.get("milestones_hit"), list):
        state["milestones_hit"] = []
    state["continue_benchmark"] = AI_BENCHMARK_CONTINUE_AFTER_PROFIT
    return state


def save_ai_benchmark_state(state):
    write_json_atomic(AI_BENCHMARK_STATE_FILE, state)


def append_ai_benchmark_trade(trade):
    os.makedirs(os.path.dirname(AI_BENCHMARK_TRADES_FILE), exist_ok=True)
    if os.path.exists(AI_BENCHMARK_TRADES_FILE):
        try:
            with open(AI_BENCHMARK_TRADES_FILE, "r", newline="", encoding="utf-8") as file:
                reader = csv.DictReader(file)
                existing_headers = tuple(reader.fieldnames or ())
                existing_rows = list(reader)
            if existing_headers != AI_BENCHMARK_TRADE_HEADERS:
                temp_file = f"{AI_BENCHMARK_TRADES_FILE}.tmp"
                with open(temp_file, "w", newline="", encoding="utf-8") as file:
                    writer = csv.DictWriter(file, fieldnames=AI_BENCHMARK_TRADE_HEADERS)
                    writer.writeheader()
                    for existing_row in existing_rows:
                        writer.writerow({
                            field: existing_row.get(field, "")
                            for field in AI_BENCHMARK_TRADE_HEADERS
                        })
                os.replace(temp_file, AI_BENCHMARK_TRADES_FILE)
        except (OSError, csv.Error):
            pass
    write_header = not os.path.exists(AI_BENCHMARK_TRADES_FILE)
    with open(AI_BENCHMARK_TRADES_FILE, "a", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=AI_BENCHMARK_TRADE_HEADERS)
        if write_header:
            writer.writeheader()
        writer.writerow({
            field: trade.get(field, "")
            for field in AI_BENCHMARK_TRADE_HEADERS
        })


def archive_ai_benchmark_cycle(state, failed_reason):
    try:
        with open(AI_BENCHMARK_CYCLES_FILE, "r", encoding="utf-8") as file:
            cycles = json.load(file)
        if not isinstance(cycles, list):
            cycles = []
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        cycles = []

    metrics = calculate_ai_benchmark_metrics(state)
    cycles.append({
        "cycle": state.get("cycle"),
        "started_at": state.get("cycle_started_at"),
        "ended_at": datetime.now(ZoneInfo("America/New_York")).isoformat(),
        "status": "Failed",
        "reason": failed_reason,
        "ending_balance": round(parse_float(state.get("current_balance")) or 0, 2),
        "total_trades": metrics["total_trades"],
        "win_rate": metrics["win_rate"],
        "max_drawdown": metrics["max_drawdown"],
        "profit_factor": metrics["profit_factor"]
    })
    write_json_atomic(AI_BENCHMARK_CYCLES_FILE, cycles)


def calculate_ai_benchmark_metrics(state):
    trades = state.get("closed_trades") or []
    wins = [trade for trade in trades if trade.get("result") == "WIN"]
    losses = [trade for trade in trades if trade.get("result") == "LOSS"]
    flats = [trade for trade in trades if trade.get("result") == "FLAT"]
    gross_profit = sum(max(0, parse_float(trade.get("pnl")) or 0) for trade in trades)
    gross_loss = abs(sum(min(0, parse_float(trade.get("pnl")) or 0) for trade in trades))
    profit_factor = gross_profit / gross_loss if gross_loss else (gross_profit if gross_profit else 0)
    consecutive_wins = 0
    consecutive_losses = 0
    current_wins = 0
    current_losses = 0
    for trade in trades:
        if trade.get("result") == "WIN":
            current_wins += 1
            current_losses = 0
        elif trade.get("result") == "LOSS":
            current_losses += 1
            current_wins = 0
        else:
            current_wins = 0
            current_losses = 0
        consecutive_wins = max(consecutive_wins, current_wins)
        consecutive_losses = max(consecutive_losses, current_losses)

    return {
        "total_trades": len(trades),
        "closed_trade_count": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "flats": len(flats),
        "win_rate": (len(wins) / len(trades) * 100) if trades else 0,
        "loss_rate": (len(losses) / len(trades) * 100) if trades else 0,
        "profit_factor": profit_factor,
        "max_drawdown": parse_float(state.get("max_drawdown")) or 0,
        "consecutive_wins": consecutive_wins,
        "consecutive_losses": consecutive_losses,
        "best_trade": max((parse_float(trade.get("pnl")) or 0 for trade in trades), default=0),
        "worst_trade": min((parse_float(trade.get("pnl")) or 0 for trade in trades), default=0),
        "daily_pnl": parse_float((state.get("daily_pnl") or {}).get(market_date_text())) or 0
    }


def get_ai_benchmark_daily_stats(state):
    today = market_date_text()
    daily_trades = [
        trade for trade in (state.get("closed_trades") or [])
        if str(trade.get("time") or "").startswith(today)
    ]
    open_position = state.get("open_position")
    trades_today = len(daily_trades) + (
        1 if open_position and str(open_position.get("entry_time") or "").startswith(today) else 0
    )
    consecutive_losses = 0
    for trade in reversed(daily_trades):
        if trade.get("result") == "LOSS":
            consecutive_losses += 1
        else:
            break
    return {
        "trades_today": trades_today,
        "closed_trades_today": len(daily_trades),
        "consecutive_losses_today": consecutive_losses,
        "daily_pnl": parse_float((state.get("daily_pnl") or {}).get(today)) or 0
    }


def get_ai_benchmark_box_biases(latest, prediction_rows, current_price):
    saved = {}
    for item in str((latest or {}).get("confluence_factors") or "").split(";"):
        if "=" in item:
            name, value = item.split("=", 1)
            saved[name.strip().replace(" / ", "/")] = value.strip().upper()

    def normalize(value):
        text = str(value or "").upper()
        if any(word in text for word in ("CALL", "BULL", "ABOVE", "BUYERS")):
            return "Bullish"
        if any(word in text for word in ("PUT", "BEAR", "BELOW", "SELLERS")):
            return "Bearish"
        return "Neutral"

    trend_bias = normalize(saved.get("Trend Box"))
    market_bias = normalize(saved.get("Market Box"))
    prices = [
        parse_float(row.get("spy_price"))
        for row in (prediction_rows or [])[-120:]
        if parse_float(row.get("spy_price")) is not None
    ]
    price = parse_float(current_price)
    if price is not None and len(prices) >= 5:
        source = prices[:-1] or prices
        if trend_bias == "Neutral":
            trend_mid = (max(source) + min(source)) / 2
            trend_bias = "Bullish" if price > trend_mid else "Bearish" if price < trend_mid else "Neutral"
        if market_bias == "Neutral":
            market_source = source[-12:] or source
            market_high = max(market_source)
            market_low = min(market_source)
            market_bias = "Bullish" if price > market_high else "Bearish" if price < market_low else "Neutral"
    return trend_bias, market_bias


def get_ai_benchmark_entry_permission(
    state,
    now,
    plan_available,
    data_stale,
    research_replay=False,
    paper_stop_computed=False
):
    daily = get_ai_benchmark_daily_stats(state)
    reason = None
    next_condition = "Wait for the next qualifying benchmark setup."
    minutes = now.hour * 60 + now.minute
    if data_stale:
        reason = "Blocked: stale data"
        next_condition = "Wait for the live feed to become current."
    elif (minutes < 9 * 60 + 30 or minutes >= 16 * 60) and not research_replay:
        reason = "Blocked: market closed"
        next_condition = "Wait for the regular trading session."
    elif minutes >= 15 * 60 + 45 and not research_replay:
        reason = "Blocked: no-new-trades time"
        next_condition = "Manage open paper positions only."
    elif state.get("open_position"):
        reason = "Blocked: existing paper position"
        next_condition = "Wait for the open paper trade to close."
    elif daily["trades_today"] >= AI_BENCHMARK_DAILY_MAX_TRADES:
        reason = "Blocked: max trades reached"
        next_condition = "Wait for the next trading day."
    elif daily["consecutive_losses_today"] >= 2:
        reason = "Blocked: two consecutive paper losses"
        next_condition = "Daily benchmark is paused until the next trading day."
    elif daily["daily_pnl"] <= -AI_BENCHMARK_DAILY_STOP_AMOUNT:
        reason = "Blocked: daily paper loss limit reached"
        next_condition = "Daily benchmark is paused until the next trading day."
    elif (
        daily["daily_pnl"] >= AI_BENCHMARK_DAILY_STOP_AMOUNT
        and not state.get("continue_benchmark", AI_BENCHMARK_CONTINUE_AFTER_PROFIT)
    ):
        reason = "Blocked: daily paper profit target reached"
        next_condition = "Enable continue benchmark mode or wait for the next trading day."
    elif paper_stop_computed and not plan_available:
        reason = "Blocked: missing stop level"
        next_condition = "Wait for a valid structure stop and target."
    return {
        **daily,
        "allowed": reason is None,
        "reason": reason,
        "next_condition": next_condition
    }


def get_ai_benchmark_entry_signal(decision, latest, data_stale, prediction_rows=None, alert_rows=None, level_states=None):
    if not latest:
        return {
            "direction": None,
            "bias": "Neutral",
            "confidence": 0,
            "reason": "Prediction data is unavailable.",
            "next_condition": "Wait for current prediction data."
        }
    if data_stale:
        return {
            "direction": None,
            "bias": "Neutral",
            "confidence": 0,
            "reason": "Data is stale.",
            "next_condition": "Wait for the live feed to become current."
        }
    if latest.get("bearish_breakdown_extended") and not PAPER_RESEARCH_MODE:
        return {
            "direction": None,
            "bias": "Bearish",
            "confidence": 60,
            "reason": "Bearish candle is extended; benchmark will not chase it.",
            "next_condition": "Wait for a retest or a fresh bearish setup."
        }

    bullish_score = int(parse_float(decision.get("bullish_score")) or parse_float(latest.get("bullish_confluence_score")) or 0)
    bearish_score = int(parse_float(decision.get("bearish_score")) or parse_float(latest.get("bearish_confluence_score")) or 0)
    scanner_signal = str(
        latest.get("prediction")
        or latest.get("trade_action")
        or latest.get("direction")
        or latest.get("signal")
        or ""
    ).upper()
    scanner_confidence = parse_float(
        latest.get("confidence")
        or latest.get("total_confidence")
        or latest.get("total_score")
    ) or 0
    mtf_signal = str(latest.get("mtf_overall_signal") or "").upper()
    mtf_alignment = str(latest.get("mtf_alignment") or "").upper()
    mtf_usable = not any(
        label in mtf_alignment for label in ("STRONGLY MIXED", "CONFLICTING")
    )
    confluence_score = parse_float(latest.get("confluence_score")) or 0
    latest_price = parse_float(latest.get("spy_price"))
    bullish_trigger = parse_float(latest.get("bullish_trigger"))
    bearish_trigger = parse_float(latest.get("bearish_trigger"))
    confidence_call = scanner_signal == "CALL" and scanner_confidence >= 60
    confidence_put = scanner_signal == "PUT" and scanner_confidence >= 60
    mtf_call = mtf_signal == "CALL" and mtf_usable
    mtf_put = mtf_signal == "PUT" and mtf_usable
    trigger_call = (
        latest_price is not None
        and bullish_trigger is not None
        and latest_price >= bullish_trigger
    )
    trigger_put = (
        latest_price is not None
        and bearish_trigger is not None
        and latest_price <= bearish_trigger
    )
    confluence_call = confluence_score >= 5 and (
        scanner_signal == "CALL"
        or mtf_signal == "CALL"
        or bullish_score > bearish_score
    )
    confluence_put = confluence_score >= 5 and (
        scanner_signal == "PUT"
        or mtf_signal == "PUT"
        or bearish_score > bullish_score
    )
    bull_level = level_states["debug"].get("last_hit_bull_level", 0) if level_states else last_hit_bull_level
    bear_level = level_states["debug"].get("last_hit_bear_level", 0) if level_states else last_hit_bear_level
    breakout_active = bull_level >= 3
    breakdown_active = bool(latest.get("bearish_breakdown_active")) or bear_level >= 3

    pressure_windows = calculate_alert_pressure_windows(alert_rows or [], prediction_rows or [])
    pressure_15m = next((window for window in pressure_windows if window["minutes"] == 15), None)
    strong_call_pressure = bool(
        pressure_15m
        and pressure_15m["bias"] == "Bullish Pressure"
        and pressure_15m["call_count"] > pressure_15m["put_count"]
    )
    strong_put_pressure = bool(
        pressure_15m
        and pressure_15m["bias"] == "Bearish Pressure"
        and pressure_15m["put_count"] > pressure_15m["call_count"]
    )

    recent_direction_rows = []
    reference_time = parse_row_timestamp((prediction_rows or [])[-1]) if prediction_rows else None
    if reference_time:
        cutoff = reference_time.timestamp() - 15 * 60
        recent_direction_rows = [
            row for row in (prediction_rows or [])
            if parse_row_timestamp(row) is not None
            and parse_row_timestamp(row).timestamp() >= cutoff
        ]
    pressure_directions = [
        (row.get("alert_direction") or "").upper()
        for row in recent_direction_rows
        if (row.get("alert_direction") or "").upper() in ("CALL", "PUT")
    ]
    call_pressure_count = pressure_directions.count("CALL")
    put_pressure_count = pressure_directions.count("PUT")
    directional_total = call_pressure_count + put_pressure_count
    if directional_total >= 3:
        strong_call_pressure = strong_call_pressure or (
            call_pressure_count / directional_total >= 0.60
            and call_pressure_count > put_pressure_count
        )
        strong_put_pressure = strong_put_pressure or (
            put_pressure_count / directional_total >= 0.60
            and put_pressure_count > call_pressure_count
        )

    momentum_score = parse_float(latest.get("momentum_score")) or 0
    context = " ".join(str(value or "") for value in (
        latest.get("current_advantage"),
        latest.get("mtf_1m_status"),
        latest.get("mtf_3m_status"),
        latest.get("last_3_candle_reading"),
        latest.get("market_structure"),
        latest.get("alert_direction")
    )).upper()
    vwap_position = str(latest.get("vwap_position") or "").upper()
    bullish_momentum = momentum_score >= 12 and "ABOVE" in vwap_position and any(
        word in context for word in ("BULL", "CALL", "BUYERS", "HIGHER")
    )
    bearish_momentum = momentum_score >= 12 and "BELOW" in vwap_position and any(
        word in context for word in ("BEAR", "PUT", "SELLERS", "LOWER")
    )
    trend_box_bias, market_box_bias = get_ai_benchmark_box_biases(
        latest,
        prediction_rows,
        latest.get("spy_price")
    )
    bullish_box_agreement = trend_box_bias == "Bullish" and market_box_bias == "Bullish"
    bearish_box_agreement = trend_box_bias == "Bearish" and market_box_bias == "Bearish"

    bullish_evidence = bullish_score
    bearish_evidence = bearish_score
    if strong_call_pressure:
        bullish_evidence += 2
    if strong_put_pressure:
        bearish_evidence += 2
    if breakout_active:
        bullish_evidence += 3
    if breakdown_active:
        bearish_evidence += 3
    if bullish_momentum:
        bullish_evidence += 2
    if bearish_momentum:
        bearish_evidence += 2
    if bullish_box_agreement:
        bullish_evidence += 2
    if bearish_box_agreement:
        bearish_evidence += 2

    bullish_qualifies = (
        bullish_score >= 5
        or breakout_active
        or bullish_momentum
        or bullish_box_agreement
        or strong_call_pressure
        or confidence_call
        or mtf_call
        or trigger_call
        or confluence_call
    )
    bearish_qualifies = (
        bearish_score >= 5
        or breakdown_active
        or bearish_momentum
        or bearish_box_agreement
        or strong_put_pressure
        or confidence_put
        or mtf_put
        or trigger_put
        or confluence_put
    )
    if not bullish_qualifies and not bearish_qualifies:
        return {
            "direction": None,
            "bias": "Neutral",
            "confidence": min(100, max(bullish_evidence, bearish_evidence) * 10),
            "reason": "No benchmark entry condition is active.",
            "next_condition": "Need 5/11 confluence, box agreement, VWAP-aligned momentum, pressure dominance, or a breakout/breakdown."
        }
    if bullish_qualifies and bearish_qualifies and bullish_evidence == bearish_evidence:
        return {
            "direction": None,
            "bias": "Neutral",
            "confidence": min(100, max(bullish_evidence, bearish_evidence) * 10),
            "reason": "Bullish and bearish benchmark evidence are balanced.",
            "next_condition": "Wait for one side to gain a clear evidence advantage."
        }

    direction = (
        "CALL" if bullish_qualifies and not bearish_qualifies
        else "PUT" if bearish_qualifies and not bullish_qualifies
        else "CALL" if bullish_evidence > bearish_evidence
        else "PUT"
    )
    evidence = bullish_evidence if direction == "CALL" else bearish_evidence
    opposing = bearish_evidence if direction == "CALL" else bullish_evidence
    confidence = min(100, max(0, 50 + ((evidence - opposing) * 7)))
    reasons = []
    entry_rules = []
    if direction == "CALL":
        if confidence_call:
            reasons.append(f"CALL confidence {scanner_confidence:.0f}%")
            entry_rules.append("Directional confidence >= 60")
        if confluence_call:
            reasons.append(f"Confluence {confluence_score:.0f}")
            entry_rules.append("Confluence >= 5 with CALL bias")
        if mtf_call:
            reasons.append(f"MTF CALL ({mtf_alignment or 'aligned'})")
            entry_rules.append("MTF CALL alignment")
        if trigger_call:
            reasons.append("Bullish trigger hold")
            entry_rules.append("Price held above bullish trigger")
        if breakout_active:
            reasons.append("Breakout")
            entry_rules.append("Bullish breakout")
        if strong_call_pressure:
            reasons.append("Bullish pressure")
            entry_rules.append("Bullish pressure dominance")
        if bullish_score >= 5:
            reasons.append(f"Bullish score {bullish_score}/11")
            entry_rules.append("Bullish score >= 5")
        if bullish_momentum:
            reasons.append("Momentum + VWAP")
            entry_rules.append("Bullish momentum above VWAP")
        if bullish_box_agreement:
            reasons.append("Trend box + market box")
            entry_rules.append("Bullish trend/market box agreement")
    else:
        if confidence_put:
            reasons.append(f"PUT confidence {scanner_confidence:.0f}%")
            entry_rules.append("Directional confidence >= 60")
        if confluence_put:
            reasons.append(f"Confluence {confluence_score:.0f}")
            entry_rules.append("Confluence >= 5 with PUT bias")
        if mtf_put:
            reasons.append(f"MTF PUT ({mtf_alignment or 'aligned'})")
            entry_rules.append("MTF PUT alignment")
        if trigger_put:
            reasons.append("Bearish trigger hold")
            entry_rules.append("Price held below bearish trigger")
        if breakdown_active:
            reasons.append("Breakdown")
            entry_rules.append("Bearish breakdown")
        if strong_put_pressure:
            reasons.append("Bearish pressure")
            entry_rules.append("Bearish pressure dominance")
        if bearish_score >= 5:
            reasons.append(f"Bearish score {bearish_score}/11")
            entry_rules.append("Bearish score >= 5")
        if bearish_momentum:
            reasons.append("Momentum + VWAP")
            entry_rules.append("Bearish momentum below VWAP")
        if bearish_box_agreement:
            reasons.append("Trend box + market box")
            entry_rules.append("Bearish trend/market box agreement")

    return {
        "direction": direction,
        "signal": f"BENCHMARK {direction}",
        "bias": "Bullish" if direction == "CALL" else "Bearish",
        "confidence": confidence,
        "reason": ", ".join(reasons) if reasons else "Directional evidence",
        "entry_rule_used": "; ".join(dict.fromkeys(entry_rules)) or "Directional evidence",
        "next_condition": "Valid structure stop and available daily risk capacity."
    }


def build_ai_benchmark_trade_plan(latest, direction, entry, research_replay=False):
    entry_price = (
        parse_float(entry)
        or parse_float(latest.get("live_price"))
        or parse_float(latest.get("current_spy_price"))
        or parse_float(latest.get("spy_price"))
    )
    if entry_price is None or not math.isfinite(entry_price):
        return None

    support = parse_float(latest.get("nearest_support"))
    resistance = parse_float(latest.get("nearest_resistance"))
    paper_stop_computed = False

    if direction == "CALL":
        if support is not None and support < entry_price:
            stop = support
            stop_source = "structure_support"
        else:
            stop = entry_price - 0.35
            stop_source = "research_fallback"
        risk = entry_price - stop
        target = entry_price + (risk * 1.5)
        paper_stop_computed = True
    elif direction == "PUT":
        if resistance is not None and resistance > entry_price:
            stop = resistance
            stop_source = "structure_resistance"
        else:
            stop = entry_price + 0.35
            stop_source = "research_fallback"
        risk = stop - entry_price
        target = entry_price - (risk * 1.5)
        paper_stop_computed = True
    else:
        return None

    if not paper_stop_computed:
        return None
    if stop is None or target is None:
        return None

    reward = abs(target - entry_price)
    if not all(math.isfinite(value) for value in (stop, target, risk, reward)):
        return None
    if risk <= 0 or reward <= 0:
        return None
    return {
        "stop": stop,
        "target": target,
        "risk": risk,
        "reward": reward,
        "risk_reward": reward / risk,
        "stop_source": stop_source,
        "paper_stop_computed": True,
        "paper_block_stage": "post_compute"
    }


def ai_benchmark_contract_price(position, current_spy_price):
    entry = parse_float(position.get("entry_spy_price")) or current_spy_price
    direction_move = (
        current_spy_price - entry
        if position.get("direction") == "CALL"
        else entry - current_spy_price
    )
    return max(
        0.01,
        (parse_float(position.get("simulated_contract_entry")) or AI_BENCHMARK_ENTRY_PREMIUM)
        + (direction_move * AI_BENCHMARK_SYNTHETIC_DELTA)
    )


def append_ai_benchmark_equity(state, equity, force=False):
    curve = state.setdefault("equity_curve", [])
    now = datetime.now(ZoneInfo("America/New_York"))
    last_epoch = parse_float(curve[-1].get("epoch")) if curve else None
    if force or last_epoch is None or time.time() - last_epoch >= 60:
        curve.append({
            "time": now.isoformat(),
            "epoch": time.time(),
            "equity": round(equity, 2)
        })
        del curve[:-AI_BENCHMARK_MAX_EQUITY_POINTS]

    max_equity = max(parse_float(state.get("max_equity")) or AI_BENCHMARK_STARTING_BALANCE, equity)
    state["max_equity"] = round(max_equity, 2)
    drawdown = max(0, max_equity - equity)
    state["max_drawdown"] = round(max(parse_float(state.get("max_drawdown")) or 0, drawdown), 2)


def close_ai_benchmark_position(state, current_spy_price, exit_reason):
    position = state.get("open_position")
    if not position:
        return None

    exit_premium = ai_benchmark_contract_price(position, current_spy_price)
    entry_premium = parse_float(position.get("simulated_contract_entry")) or AI_BENCHMARK_ENTRY_PREMIUM
    pnl = round((exit_premium - entry_premium) * 100, 2)
    result = "WIN" if pnl > 0.01 else "LOSS" if pnl < -0.01 else "FLAT"
    now = datetime.now(ZoneInfo("America/New_York"))
    trade = {
        "time": position.get("entry_time"),
        "exit_time": now.isoformat(),
        "cycle": state.get("cycle"),
        "signal": position.get("signal"),
        "direction": position.get("direction"),
        "entry_spy_price": round(parse_float(position.get("entry_spy_price")) or 0, 4),
        "exit_spy_price": round(current_spy_price, 4),
        "simulated_contract_entry": round(entry_premium, 2),
        "simulated_contract_exit": round(exit_premium, 2),
        "duration_minutes": round(max(0, (now.timestamp() - (parse_float(position.get("entry_epoch")) or now.timestamp())) / 60), 2),
        "pnl": pnl,
        "entry_reason": position.get("entry_reason"),
        "reason": exit_reason,
        "result": result
    }
    state["current_balance"] = round((parse_float(state.get("current_balance")) or 0) + pnl, 2)
    state["closed_trades"].append(trade)
    del state["closed_trades"][:-250]
    state["last_trade"] = trade
    state["last_event"] = f"Paper trade closed: {trade['direction']} {trade['result']} ({trade['reason']})"
    state["open_position"] = None
    state["daily_pnl"][market_date_text()] = round(
        (parse_float(state["daily_pnl"].get(market_date_text())) or 0) + pnl,
        2
    )
    append_ai_benchmark_trade(trade)
    append_ai_benchmark_equity(state, state["current_balance"], True)
    return trade


def update_ai_paper_benchmark(latest, decision, regime, trade_risk, current_price, data_stale=False, prediction_rows=None, alert_rows=None, level_states=None):
    price = parse_float(current_price)
    with ai_benchmark_lock:
        state_missing = not os.path.exists(AI_BENCHMARK_STATE_FILE)
        state = load_ai_benchmark_state()
        changed = state_missing
        now = datetime.now(ZoneInfo("America/New_York"))
        minutes = now.hour * 60 + now.minute
        live_session = now.weekday() < 5 and 9 * 60 + 30 <= minutes < 16 * 60
        paper_mode = "LIVE SESSION" if live_session else "RESEARCH REPLAY"
        entry_signal = get_ai_benchmark_entry_signal(
            decision,
            latest,
            data_stale,
            prediction_rows,
            alert_rows,
            level_states
        )
        state["benchmark_bias"] = entry_signal.get("bias", "Neutral")
        state["benchmark_confidence"] = entry_signal.get("confidence", 0)
        state["benchmark_entry_reason"] = entry_signal.get("reason", "Waiting for benchmark evidence.")
        state["paper_research_mode"] = PAPER_RESEARCH_MODE
        state["paper_mode"] = paper_mode
        state["paper_last_evaluation_time"] = now.isoformat()
        state["paper_trade_candidate_direction"] = entry_signal.get("direction")
        state["paper_trade_candidate_confidence"] = entry_signal.get("confidence", 0)
        state["paper_entry_rule_used"] = entry_signal.get("entry_rule_used", "None")
        state["paper_stop_computed"] = False
        state["paper_block_stage"] = "pre_compute"
        state.setdefault(
            "paper_exit_rule_used",
            "Structure stop/target, opposite evidence, or session close"
        )
        if price is None or data_stale:
            daily = get_ai_benchmark_daily_stats(state)
            state.update(daily)
            state["daily_goal"] = "3-10"
            state["daily_status"] = "Paused - live data unavailable"
            state["reason_not_trading"] = (
                "Blocked: no valid SPY price"
                if price is None else "Blocked: stale data"
            )
            state["paper_last_block_reason"] = state["reason_not_trading"]
            state["next_condition_needed"] = "Wait for a current live SPY price feed."
            save_ai_benchmark_state(state)
            metrics = calculate_ai_benchmark_metrics(state)
            return {**state, **metrics, "mark_to_market_equity": state.get("current_balance")}

        position = state.get("open_position")
        if state.get("open_position"):
            state["benchmark_bias"] = (
                "Bullish" if state["open_position"].get("direction") == "CALL" else "Bearish"
            )
            state["benchmark_entry_reason"] = state["open_position"].get(
                "entry_reason",
                "Open benchmark paper trade."
            )
        if position:
            direction = position.get("direction")
            stop = parse_float(position.get("stop"))
            target = parse_float(position.get("target"))
            exit_reason = None
            if direction == "CALL" and stop is not None and price <= stop:
                exit_reason = "Structure stop reached."
            elif direction == "CALL" and target is not None and price >= target:
                exit_reason = "Structure target reached."
            elif direction == "PUT" and stop is not None and price >= stop:
                exit_reason = "Structure stop reached."
            elif direction == "PUT" and target is not None and price <= target:
                exit_reason = "Structure target reached."
            elif entry_signal and entry_signal.get("direction") and entry_signal["direction"] != direction:
                exit_reason = "Opposite benchmark evidence."
            elif paper_mode == "LIVE SESSION" and minutes >= 15 * 60 + 55:
                exit_reason = "End-of-day close/manage-only rule."
            if exit_reason:
                close_ai_benchmark_position(state, price, exit_reason)
                state["paper_exit_rule_used"] = exit_reason
                changed = True

        research_replay = PAPER_RESEARCH_MODE and paper_mode == "RESEARCH REPLAY"
        plan = (
            build_ai_benchmark_trade_plan(
                latest,
                entry_signal["direction"],
                price,
                research_replay
            )
            if entry_signal.get("direction") and not state.get("open_position")
            else None
        )
        active_position = state.get("open_position")
        resolved_plan = plan or active_position
        if resolved_plan:
            state["paper_stop_source"] = resolved_plan.get("stop_source", "structure_plan")
            state["paper_stop"] = resolved_plan.get("stop")
            state["paper_target"] = resolved_plan.get("target")
            state["paper_risk_per_share"] = resolved_plan.get("risk")
            state["paper_reward_per_share"] = resolved_plan.get("reward")
            state["paper_risk_reward"] = resolved_plan.get("risk_reward")
            state["paper_stop_computed"] = bool(
                resolved_plan.get("paper_stop_computed", True)
            )
            state["paper_block_stage"] = resolved_plan.get(
                "paper_block_stage",
                "post_compute"
            )
        else:
            state["paper_stop_source"] = "none"
            state["paper_stop"] = None
            state["paper_target"] = None
            state["paper_risk_per_share"] = None
            state["paper_reward_per_share"] = None
            state["paper_risk_reward"] = None
            state["paper_stop_computed"] = False
            state["paper_block_stage"] = "pre_compute"
        permission = get_ai_benchmark_entry_permission(
            state,
            now,
            bool(plan) if entry_signal.get("direction") else True,
            data_stale,
            research_replay,
            state["paper_stop_computed"]
        )
        state.update({
            "trades_today": permission["trades_today"],
            "daily_goal": "3-10",
            "continue_benchmark": state.get("continue_benchmark", AI_BENCHMARK_CONTINUE_AFTER_PROFIT)
        })
        if state.get("open_position"):
            state["daily_status"] = "Paper trade open"
            state["reason_not_trading"] = "Blocked: existing paper position"
            state["paper_last_block_reason"] = state["reason_not_trading"]
            state["next_condition_needed"] = "Wait for the open paper trade to close."
        elif not permission["allowed"]:
            state["daily_status"] = "Paused"
            state["reason_not_trading"] = permission["reason"]
            state["paper_last_block_reason"] = permission["reason"]
            state["next_condition_needed"] = permission["next_condition"]
        elif not entry_signal.get("direction"):
            state["daily_status"] = (
                "Seeking minimum daily goal"
                if permission["trades_today"] < AI_BENCHMARK_DAILY_MIN_TARGET
                else "Watching for setup"
            )
            state["reason_not_trading"] = (
                "Blocked: confidence below research threshold"
                if (parse_float(entry_signal.get("confidence")) or 0) < 60
                else "Blocked: no directional edge"
            )
            state["paper_last_block_reason"] = state["reason_not_trading"]
            state["next_condition_needed"] = entry_signal.get(
                "next_condition",
                "Wait for the next qualifying benchmark setup."
            )

        if (
            not state.get("open_position")
            and entry_signal.get("direction")
            and permission["allowed"]
            and plan
        ):
            bucket_minutes = 3 if permission["trades_today"] < AI_BENCHMARK_DAILY_MIN_TARGET else 5
            signal_key = "|".join((
                market_date_text(),
                entry_signal["direction"],
                entry_signal["signal"],
                str(level_set_id or latest.get("level_set_id") or ""),
                f"{now.hour:02d}:{now.minute // bucket_minutes}",
            ))
            if (
                signal_key != state.get("last_signal_key")
                and (parse_float(state.get("current_balance")) or 0) >= AI_BENCHMARK_ENTRY_PREMIUM * 100
            ):
                state["open_position"] = {
                    "entry_time": now.isoformat(),
                    "entry_epoch": now.timestamp(),
                    "signal": entry_signal["signal"],
                    "direction": entry_signal["direction"],
                    "entry_spy_price": round(price, 4),
                    "simulated_contract_entry": AI_BENCHMARK_ENTRY_PREMIUM,
                    "contracts": 1,
                    "stop": round(plan["stop"], 4),
                    "target": round(plan["target"], 4),
                    "stop_source": plan["stop_source"],
                    "risk": round(plan["risk"], 4),
                    "reward": round(plan["reward"], 4),
                    "risk_reward": round(plan["risk_reward"], 2),
                    "paper_stop_computed": plan["paper_stop_computed"],
                    "paper_block_stage": plan["paper_block_stage"],
                    "result": "OPEN",
                    "reason": entry_signal.get("reason"),
                    "entry_reason": entry_signal.get("reason"),
                    "signal_key": signal_key
                }
                state["last_signal_key"] = signal_key
                state["last_event"] = f"Paper trade open: {entry_signal['direction']} ({entry_signal.get('reason')})"
                state["daily_status"] = "Paper trade open"
                state["reason_not_trading"] = ""
                state["paper_last_block_reason"] = ""
                state["next_condition_needed"] = "Monitor the structure stop and target."
                changed = True
            elif signal_key == state.get("last_signal_key"):
                state["daily_status"] = "Waiting for fresh setup window"
                state["reason_not_trading"] = "This benchmark setup was already evaluated in the current time window."
                state["paper_last_block_reason"] = "Blocked: setup already evaluated"
                state["next_condition_needed"] = "Wait for a fresh three- or five-minute setup window."
            else:
                state["daily_status"] = "Paused"
                state["reason_not_trading"] = "Benchmark balance cannot support one synthetic contract."
                state["paper_last_block_reason"] = "Blocked: insufficient paper balance"
                state["next_condition_needed"] = "Wait for the next benchmark cycle."

        position = state.get("open_position")
        mark_to_market_equity = parse_float(state.get("current_balance")) or AI_BENCHMARK_STARTING_BALANCE
        if position:
            current_premium = ai_benchmark_contract_price(position, price)
            position["current_spy_price"] = round(price, 4)
            position["simulated_contract_current"] = round(current_premium, 2)
            position["duration_minutes"] = round(
                max(0, (now.timestamp() - (parse_float(position.get("entry_epoch")) or now.timestamp())) / 60),
                2
            )
            position["unrealized_pnl"] = round(
                (current_premium - AI_BENCHMARK_ENTRY_PREMIUM) * 100,
                2
            )
            mark_to_market_equity += position["unrealized_pnl"]
        curve_length = len(state.get("equity_curve") or [])
        append_ai_benchmark_equity(state, mark_to_market_equity, changed)
        changed = changed or len(state.get("equity_curve") or []) != curve_length

        milestones = (
            (1250, "+25%"),
            (1500, "+50%"),
            (2000, "2x")
        )
        for threshold, label in milestones:
            if (parse_float(state.get("current_balance")) or 0) >= threshold and label not in state["milestones_hit"]:
                state["milestones_hit"].append(label)
                state["status"] = f"Milestone Hit: {label}"
                changed = True

        if (parse_float(state.get("current_balance")) or 0) < AI_BENCHMARK_FAILURE_BALANCE:
            failed_cycle = {
                "cycle": state.get("cycle"),
                "ending_balance": state.get("current_balance"),
                "status": "Failed"
            }
            archive_ai_benchmark_cycle(state, "Balance dropped below $500.")
            state = new_ai_benchmark_state(int(state.get("cycle") or 1) + 1, failed_cycle)
            mark_to_market_equity = state["current_balance"]
            changed = True

        daily = get_ai_benchmark_daily_stats(state)
        state.update(daily)
        if not state.get("open_position") and not state.get("reason_not_trading"):
            state["reason_not_trading"] = "Waiting for the next qualifying setup."
            state["next_condition_needed"] = "Need directional evidence and a valid structure stop."
        status_signature = "|".join(str(state.get(field) or "") for field in (
            "daily_status",
            "reason_not_trading",
            "next_condition_needed",
            "trades_today",
            "benchmark_bias",
            "benchmark_confidence",
            "benchmark_entry_reason",
            "paper_mode",
            "paper_last_block_reason",
            "paper_entry_rule_used",
            "paper_last_evaluation_time",
            "paper_trade_candidate_direction",
            "paper_trade_candidate_confidence",
            "paper_stop_source",
            "paper_stop",
            "paper_target",
            "paper_risk_per_share",
            "paper_reward_per_share",
            "paper_risk_reward",
            "paper_stop_computed",
            "paper_block_stage"
        ))
        if status_signature != state.get("last_status_signature"):
            state["last_status_signature"] = status_signature
            changed = True
        if changed or state.get("open_position"):
            save_ai_benchmark_state(state)
        metrics = calculate_ai_benchmark_metrics(state)
        return {**state, **metrics, "mark_to_market_equity": round(mark_to_market_equity, 2)}


def detect_short_term_correction(rows, live_price, bar_count=CORRECTION_BAR_COUNT):
    global correction_activation

    minute_closes = {}
    for row in rows[-300:]:
        price = parse_float(row.get("spy_price"))
        timestamp_text = row.get("time")
        if price is None or not timestamp_text:
            continue
        try:
            timestamp = datetime.strptime(timestamp_text, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        minute_closes[timestamp.replace(second=0, microsecond=0)] = price

    closes = list(minute_closes.values())[-max(2, bar_count):]
    current_price = parse_float(live_price)
    latest = rows[-1] if rows else {}
    regime = (latest.get("regime") or "CHOPPY").upper()
    if current_price is not None and (not closes or current_price != closes[-1]):
        closes.append(current_price)
    closes = closes[-(bar_count + 1):]

    mode = "NEUTRAL"
    signal = "WAIT"
    reason = "Waiting for enough short-term price bars."
    if len(closes) >= 2:
        changes = [closes[index] - closes[index - 1] for index in range(1, len(closes))]
        positive_moves = sum(change >= CORRECTION_MIN_MOVE for change in changes)
        negative_moves = sum(change <= -CORRECTION_MIN_MOVE for change in changes)
        net_move = closes[-1] - closes[0]

        if regime == "TRENDING UP" and negative_moves >= 1 and net_move <= -CORRECTION_MIN_MOVE:
            mode = "BEARISH CORRECTION"
            signal = "PUT"
            reason = "Short-term closes are pulling back against the bullish trend."
        elif regime == "TRENDING DOWN" and positive_moves >= 1 and net_move >= CORRECTION_MIN_MOVE:
            mode = "BULLISH CORRECTION"
            signal = "CALL"
            reason = "Short-term closes are bouncing against the bearish trend."
        elif negative_moves >= max(1, len(changes) - 1) and net_move < 0:
            mode = "BEARISH CONTINUATION"
            signal = "PUT"
            reason = "Recent short-term closes are stepping lower."
        elif positive_moves >= max(1, len(changes) - 1) and net_move > 0:
            mode = "BULLISH CONTINUATION"
            signal = "CALL"
            reason = "Recent short-term closes are stepping higher."
        else:
            mode = "MIXED / NO CORRECTION"
            reason = "Recent short-term closes do not show a clean continuation or retracement."

    if mode != correction_activation["mode"]:
        correction_activation = {
            "mode": mode,
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

    return {
        "correction_mode": mode,
        "correction_signal": signal,
        "correction_reason": reason,
        "correction_activation_time": correction_activation["time"] or "N/A",
        "correction_bar_count": bar_count,
        "correction_closes": closes
    }


def detect_bearish_breakdown_state(latest, rows, current_price, level_states=None):
    price = parse_float(current_price)
    breakdown = parse_float(latest.get("bearish_breakdown")) if latest else None
    support = parse_float(latest.get("nearest_support")) if latest else None
    vwap = parse_float(latest.get("vwap")) if latest else None
    vwap_position = (latest.get("vwap_position") or "").upper() if latest else ""
    recent_prices = [
        value for row in rows[-120:]
        for value in [parse_float(row.get("spy_price"))]
        if value is not None
    ]
    recent_slice = recent_prices[-8:]
    recent_move = (
        price - recent_slice[0]
        if price is not None and recent_slice else 0
    )
    bearish_steps = sum(
        recent_slice[index] < recent_slice[index - 1]
        for index in range(1, len(recent_slice))
    )
    context = " ".join(str(value or "") for value in (
        latest.get("last_3_candle_reading") if latest else "",
        latest.get("mtf_1m_status") if latest else "",
        latest.get("mtf_1m_reason") if latest else "",
        latest.get("market_structure") if latest else "",
        latest.get("correction_mode") if latest else ""
    )).upper()
    bearish_momentum = (
        any(word in context for word in (
            "BEARISH", "LOWER LOW", "LOWER HIGH", "STEPPING LOWER",
            "SELLER", "BREAKDOWN", "TRENDING DOWN"
        ))
        or (len(recent_slice) >= 3 and bearish_steps >= len(recent_slice) - 2 and recent_move < 0)
    )
    vwap_bearish = (
        "BELOW" in vwap_position
        or "BEAR" in vwap_position
        or (
            price is not None and vwap is not None and price < vwap
        )
    )
    price_below_breakdown = (
        price is not None and breakdown is not None and price <= breakdown
    )
    breakdown_active = (
        price_below_breakdown
        and bearish_momentum
        and vwap_bearish
    )
    distance_below_breakdown = (
        max(0, breakdown - price)
        if price is not None and breakdown is not None else 0
    )
    extended = breakdown_active and (
        distance_below_breakdown >= 0.20 or recent_move <= -0.20
    )
    touched_retest_zone = (
        breakdown is not None
        and any(value >= breakdown - 0.03 for value in recent_slice[:-1])
    )
    retest_failed = (
        breakdown_active
        and not extended
        and touched_retest_zone
        and price is not None
        and breakdown is not None
        and price <= breakdown - 0.03
        and recent_move < 0
    )
    price_below_support = (
        price is not None and support is not None and price < support
    )
    reason = ""
    if retest_failed:
        reason = "Breakdown + failed retest + bearish continuation."
    elif extended:
        reason = "Bearish breakdown active, but do not chase extended candle."
    elif breakdown_active:
        reason = "Bearish breakdown active; wait for a failed retest before confirmation."

    return {
        "bearish_breakdown_active": breakdown_active,
        "bearish_breakdown_extended": extended,
        "bearish_retest_failed": retest_failed,
        "bearish_momentum_active": bearish_momentum,
        "bearish_vwap_confirmed": vwap_bearish,
        "price_below_support": price_below_support,
        "breakdown_distance": distance_below_breakdown,
        "bearish_breakdown_reason": reason
    }


def format_seconds_age(epoch_value):
    epoch = parse_float(epoch_value)
    if epoch is None:
        return "N/A", None

    age = max(0, time.time() - epoch)
    return f"{age:.0f} sec", age


def level_age_class(age):
    if age is None:
        return ""
    if age > 120:
        return "age-red"
    if age > 60:
        return "age-yellow"
    return "age-fresh"


def correct_levels_from_live_price(latest, current_price):
    corrected = dict(latest)
    price = parse_float(current_price)
    level_names = (
        "bullish_trigger",
        "bullish_confirmation",
        "bullish_breakout",
        "bearish_trigger",
        "bearish_confirmation",
        "bearish_breakdown"
    )
    values = [parse_float(corrected.get(name)) for name in level_names]

    valid = price is not None and all(value is not None for value in values)
    if valid:
        bull_trigger, bull_confirm, bull_breakout, bear_trigger, bear_confirm, bear_breakdown = values
        valid = (
            bull_trigger > price
            and bull_confirm > bull_trigger
            and bull_breakout > bull_confirm
            and bear_trigger < price
            and bear_confirm < bear_trigger
            and bear_breakdown < bear_confirm
            and bull_confirm - bull_trigger >= 0.05
            and bull_breakout - bull_confirm >= 0.05
            and bear_trigger - bear_confirm >= 0.05
            and bear_confirm - bear_breakdown >= 0.05
        )

    scanner_corrected = str(corrected.get("levels_corrected", "")).upper() == "TRUE"
    if valid:
        return corrected, scanner_corrected
    if price is None:
        return corrected, scanner_corrected

    fallback_levels = {
        "bullish_trigger": price + 0.10,
        "bullish_confirmation": price + 0.25,
        "bullish_breakout": price + 0.50,
        "bearish_trigger": price - 0.10,
        "bearish_confirmation": price - 0.25,
        "bearish_breakdown": price - 0.50
    }
    corrected.update({
        name: f"{value:.4f}"
        for name, value in fallback_levels.items()
    })
    return corrected, True


def recalculate_levels_for_refresh(latest, live_price):
    refreshed = dict(latest or {})
    current_price = parse_float(live_price)
    reference_price = parse_float(
        refreshed.get("level_reference_price", refreshed.get("spy_price"))
    )
    if current_price is None or reference_price is None:
        return refreshed

    price_shift = current_price - reference_price
    for key in (
        "bullish_trigger",
        "bullish_confirmation",
        "bullish_breakout",
        "bearish_trigger",
        "bearish_confirmation",
        "bearish_breakdown",
        "nearest_support",
        "nearest_resistance"
    ):
        level = parse_float(refreshed.get(key))
        if level is not None:
            refreshed[key] = f"{level + price_shift:.4f}"

    refreshed["level_reference_price"] = f"{current_price:.4f}"
    refreshed["level_update_time"] = datetime.now().strftime("%I:%M:%S %p")
    refreshed["level_update_epoch"] = f"{time.time():.3f}"
    return refreshed


def get_level_activation_states(latest, current_price):
    global level_set_id, previous_level_set_id, level_set_values, level_set_generation
    global last_hit_bull_level, last_hit_bear_level, level_hit_timestamp
    global session_extreme_date, session_high_price, session_low_price
    global level_set_high_price, level_set_low_price

    ensure_level_hits_loaded()
    price = parse_float(current_price)
    bull_trigger = parse_float(latest.get("bullish_trigger"))
    bull_confirm = parse_float(latest.get("bullish_confirmation"))
    bull_breakout = parse_float(latest.get("bullish_breakout"))
    bear_trigger = parse_float(latest.get("bearish_trigger"))
    bear_confirm = parse_float(latest.get("bearish_confirmation"))
    bear_breakdown = parse_float(latest.get("bearish_breakdown"))
    support = parse_float(latest.get("nearest_support"))
    resistance = parse_float(latest.get("nearest_resistance"))
    current_level_values = (
        support,
        resistance
    ) if support is not None or resistance is not None else (
        bull_trigger,
        bull_confirm,
        bull_breakout,
        bear_trigger,
        bear_confirm,
        bear_breakdown
    )
    data_stale = bool(latest.get("_data_stale"))
    level_set_changed = level_set_values is None
    if not level_set_changed:
        for previous_value, current_value in zip(level_set_values, current_level_values):
            if (previous_value is None) != (current_value is None):
                level_set_changed = True
                break
            if (
                previous_value is not None
                and abs(previous_value - current_value) >= LEVEL_SET_RESET_DISTANCE
            ):
                level_set_changed = True
                break

    if level_set_changed and not data_stale:
        previous_level_set_id = level_set_id
        level_set_values = current_level_values
        level_set_generation += 1
        level_set_id = f"level-set-{level_set_generation}"
        last_hit_bull_level = 0
        last_hit_bear_level = 0
        level_hit_timestamp = {"bull": {}, "bear": {}}
        level_set_high_price = price
        level_set_low_price = price
    states = {
        "bull_trigger": ("waiting-level", "WAITING"),
        "bull_confirm": ("waiting-level", "WAITING"),
        "bull_breakout": ("waiting-level", "WAITING"),
        "bear_trigger": ("waiting-level", "WAITING"),
        "bear_confirm": ("waiting-level", "WAITING"),
        "bear_breakdown": ("waiting-level", "WAITING"),
        "bull_status": "WAITING",
        "bear_status": "WAITING",
        "debug": {
            "live_price": price,
            "bull_trigger": bull_trigger,
            "bull_confirmation": bull_confirm,
            "bull_breakout": bull_breakout,
            "bear_trigger": bear_trigger,
            "bear_confirmation": bear_confirm,
            "bear_breakdown": bear_breakdown,
            "level_set_id": level_set_id,
            "last_level_set_id": previous_level_set_id
        }
    }

    if price is None:
        states["debug"]["calculated_status"] = "Live price unavailable; levels remain WAITING"
        states["debug"]["last_hit_bull_level"] = last_hit_bull_level
        states["debug"]["last_hit_bear_level"] = last_hit_bear_level
        states["debug"]["level_hit_timestamp"] = level_hit_timestamp
        states["debug"]["saved_hit_times_file_path"] = os.path.abspath(LEVEL_HITS_FILE)
        states["debug"]["last_saved_hit_time"] = last_saved_hit_time
        states["debug"]["first_hit_times"] = level_first_hit_times
        return states

    now = time.time()
    if not data_stale:
        today = market_date_text()
        if session_extreme_date != today:
            session_extreme_date = today
            session_high_price = price
            session_low_price = price
        session_high_price = price if session_high_price is None else max(session_high_price, price)
        session_low_price = price if session_low_price is None else min(session_low_price, price)
        level_set_high_price = price if level_set_high_price is None else max(level_set_high_price, price)
        level_set_low_price = price if level_set_low_price is None else min(level_set_low_price, price)

        new_bull_level = last_hit_bull_level
        if bull_trigger is not None and level_set_high_price >= bull_trigger and new_bull_level < 1:
            new_bull_level = max(new_bull_level, 1)
            record_first_level_hit(
                "bull_trigger_first_hit_time", 1, "bull", price
            )
        if bull_confirm is not None and level_set_high_price >= bull_confirm and new_bull_level < 2:
            new_bull_level = max(new_bull_level, 2)
            record_first_level_hit(
                "bull_confirmation_first_hit_time", 2, "bull", price
            )
        if bull_breakout is not None and level_set_high_price >= bull_breakout and new_bull_level < 3:
            new_bull_level = max(new_bull_level, 3)
            record_first_level_hit(
                "bull_breakout_first_hit_time", 3, "bull", price
            )
        if new_bull_level > last_hit_bull_level:
            last_hit_bull_level = new_bull_level

        new_bear_level = last_hit_bear_level
        if bear_trigger is not None and level_set_low_price <= bear_trigger and new_bear_level < 1:
            new_bear_level = max(new_bear_level, 1)
            record_first_level_hit(
                "bear_trigger_first_hit_time", 1, "bear", price
            )
        if bear_confirm is not None and level_set_low_price <= bear_confirm and new_bear_level < 2:
            new_bear_level = max(new_bear_level, 2)
            record_first_level_hit(
                "bear_confirmation_first_hit_time", 2, "bear", price
            )
        if bear_breakdown is not None and level_set_low_price <= bear_breakdown and new_bear_level < 3:
            new_bear_level = max(new_bear_level, 3)
            record_first_level_hit(
                "bear_breakdown_first_hit_time", 3, "bear", price
            )
        if new_bear_level > last_hit_bear_level:
            last_hit_bear_level = new_bear_level

    bull_recent = (
        now - level_hit_timestamp["bull"].get(str(last_hit_bull_level), 0)
        < LEVEL_ACTIVE_SECONDS
    )
    bear_recent = (
        now - level_hit_timestamp["bear"].get(str(last_hit_bear_level), 0)
        < LEVEL_ACTIVE_SECONDS
    )

    if last_hit_bull_level >= 3:
        states["bull_trigger"] = ("done-bull-level", "DONE âœ…")
        states["bull_confirm"] = ("done-bull-level", "DONE âœ…")
        states["bull_breakout"] = ("active-bull-level level-glow", "BREAKOUT ACTIVE")
        states["bull_status"] = "BREAKOUT ACTIVE"
    elif last_hit_bull_level >= 2:
        states["bull_trigger"] = ("done-bull-level", "DONE âœ…")
        states["bull_confirm"] = (
            "active-bull-level level-glow" if bull_recent else "done-bull-level level-fade-done",
            "CONFIRMED" if bull_recent else "DONE &#9989;"
        )
        states["bull_status"] = "CONFIRMED" if bull_recent else "DONE"
    elif last_hit_bull_level >= 1:
        states["bull_trigger"] = (
            "active-bull-level level-glow" if bull_recent else "done-bull-level level-fade-done",
            "TRIGGER HIT" if bull_recent else "DONE Ã¢Å“â€¦"
        )
        states["bull_status"] = "TRIGGER HIT" if bull_recent else "DONE"

    if last_hit_bear_level >= 3:
        states["bear_trigger"] = ("done-bear-level", "DONE âœ…")
        states["bear_confirm"] = ("done-bear-level", "DONE âœ…")
        states["bear_breakdown"] = ("active-bear-level level-glow", "BREAKDOWN ACTIVE")
        states["bear_status"] = "BREAKDOWN ACTIVE"
    elif last_hit_bear_level >= 2:
        states["bear_trigger"] = ("done-bear-level", "DONE âœ…")
        states["bear_confirm"] = (
            "active-bear-level level-glow" if bear_recent else "done-bear-level level-fade-done",
            "CONFIRMED" if bear_recent else "DONE &#9989;"
        )
        states["bear_status"] = "CONFIRMED" if bear_recent else "DONE"
    elif last_hit_bear_level >= 1:
        states["bear_trigger"] = (
            "active-bear-level level-glow" if bear_recent else "done-bear-level level-fade-done",
            "TRIGGER HIT" if bear_recent else "DONE Ã¢Å“â€¦"
        )
        states["bear_status"] = "TRIGGER HIT" if bear_recent else "DONE"

    # The highest reached tier stays active until the structure level set changes.
    if last_hit_bull_level == 1:
        states["bull_trigger"] = ("active-bull-level level-glow", "TRIGGER HIT")
        states["bull_status"] = "TRIGGER HIT"
    elif last_hit_bull_level == 2:
        states["bull_trigger"] = ("done-bull-level", "DONE &#9989;")
        states["bull_confirm"] = ("active-bull-level level-glow", "CONFIRMED")
        states["bull_status"] = "CONFIRMED"

    if last_hit_bear_level == 1:
        states["bear_trigger"] = ("active-bear-level level-glow", "TRIGGER HIT")
        states["bear_status"] = "TRIGGER HIT"
    elif last_hit_bear_level == 2:
        states["bear_trigger"] = ("done-bear-level", "DONE &#9989;")
        states["bear_confirm"] = ("active-bear-level level-glow", "CONFIRMED")
        states["bear_status"] = "CONFIRMED"

    for level_key in (
        "bull_trigger",
        "bull_confirm",
        "bull_breakout",
        "bear_trigger",
        "bear_confirm",
        "bear_breakdown"
    ):
        class_name, label = states[level_key]
        if label.startswith("DONE"):
            states[level_key] = (class_name, "DONE &#9989;")

    states["debug"]["last_hit_bull_level"] = last_hit_bull_level
    states["debug"]["last_hit_bear_level"] = last_hit_bear_level
    states["debug"]["level_hit_timestamp"] = level_hit_timestamp
    states["debug"]["saved_hit_times_file_path"] = os.path.abspath(LEVEL_HITS_FILE)
    states["debug"]["last_saved_hit_time"] = last_saved_hit_time
    states["debug"]["first_hit_times"] = level_first_hit_times
    states["debug"]["session_high"] = session_high_price
    states["debug"]["session_low"] = session_low_price
    states["debug"]["level_set_high"] = level_set_high_price
    states["debug"]["level_set_low"] = level_set_low_price
    states["debug"]["calculated_status"] = (
        f"Bullish: {states['bull_status']} | Bearish: {states['bear_status']}"
    )
    return states


EDUCATION_TEXT = {
    "CALL / PUT / WAIT": "This is the scanner's current bias. It is not an entry by itself. Use it with confirmation and risk levels.",
    "Market Regime": "Regime tells you the type of market. Trending markets are easier to trade. Choppy markets create fakeouts.",
    "Stability": "Stability shows how long the signal has held. Low stability means the scanner is flipping too much.",
    "Current Advantage": "Shows who has control right now: buyers, sellers, or mixed.",
    "Confirmation Needed": "This tells you what must happen before the bias becomes stronger.",
    "Invalidation": "This is the level that proves the idea wrong.",
    "Support": "Support is where buyers recently defended price. If support breaks, sellers may gain control.",
    "Resistance": "Resistance is where sellers recently rejected price. If resistance breaks, buyers may gain control.",
    "Bullish Levels": "These are staged upside levels. Trigger is first sign. Confirmation is stronger. Breakout means buyers control nearby structure.",
    "Bearish Levels": "These are staged downside levels. Trigger is first sign. Confirmation is stronger. Breakdown means sellers control nearby structure.",
    "What Happens Next": "This explains what the next price area means so you can plan instead of react.",
    "Position Plan": "Shows estimated risk and reward based on SPY price levels. Options P/L will not match exactly.",
    "SPY Chart": "Use the SPY chart to compare current price with structure, entry, stop, and target levels.",
    "Engine Health": "Shows whether major SPY holdings are helping or hurting SPY direction.",
    "Market Breadth": "Shows whether strength or weakness is broad or only coming from a few stocks.",
    "VWAP": "VWAP is the average price institutions watch. Above VWAP favors buyers. Below VWAP favors sellers.",
    "Opening Range": "The first 5 minutes creates a reference range. Above it favors buyers. Below it favors sellers. Inside it often means chop.",
    "Accuracy": "Tracks whether scanner predictions were correct, wrong, or flat. Use this to improve rules.",
    "Logs": "Raw scanner history. Use this for review, not live decision-making.",
    "Trade Risk": "Combines time of day, volume, activity, regime, stability, VWAP, candles, and nearby structure. Lower risk still requires entry confirmation."
}


def build_education_box(title, button_text="How to use this"):
    instruction = EDUCATION_TEXT.get(title)
    if not instruction:
        return ""
    education_id = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")

    return f"""
    <details class="education-box" data-persist-id="education-{education_id}">
      <summary>{escape_value(button_text)}</summary>
      <p>{escape_value(instruction)}</p>
    </details>
    """


def get_eastern_time_window():
    eastern_now = datetime.now(ZoneInfo("America/New_York"))
    minutes = eastern_now.hour * 60 + eastern_now.minute

    if 570 <= minutes < 630:
        label = "Opening Momentum"
    elif 630 <= minutes < 690:
        label = "Caution Window"
    elif 690 <= minutes < 840:
        label = "Midday Chop"
    elif 840 <= minutes < 900:
        label = "Afternoon Setup"
    elif 900 <= minutes < 960:
        label = "Power Hour"
    else:
        label = "Outside Regular Hours"

    return eastern_now, label


def get_trade_risk_override(latest, regime):
    _, time_window = get_eastern_time_window()
    stability = (latest.get("mode_stability") or "LOW").upper() if latest else "LOW"
    volume_filter = (latest.get("volume_filter") or "FAIL").upper() if latest else "FAIL"
    activity_filter = (latest.get("activity_filter") or "SLOW").upper() if latest else "SLOW"
    bearish_breakdown_active = bool(latest and latest.get("bearish_breakdown_active"))
    no_trade = (
        bool(latest and latest.get("_data_stale"))
        or (regime.upper() == "CHOPPY" and not bearish_breakdown_active)
        or stability == "LOW"
        or volume_filter == "FAIL"
        or activity_filter == "SLOW"
        or time_window == "Midday Chop"
    )
    return "NO TRADE" if no_trade else "TRADE ALLOWED"


def get_top_banner_state(regime, trade_risk, level_states, latest=None, current_price=None):
    if latest and latest.get("_data_stale"):
        return "WAIT", "DATA STALE â€” DO NOT TRADE", "Live price data is older than 180 seconds."

    stability = (latest.get("mode_stability") or "LOW").upper() if latest else "LOW"
    one_min_trend = (latest.get("mtf_1m_status") or "Neutral").upper() if latest else "NEUTRAL"
    one_min_reason = (latest.get("mtf_1m_reason") or "").lower() if latest else ""
    vwap_position = (latest.get("vwap_position") or "Mixed").upper() if latest else "MIXED"
    correction_mode = (latest.get("correction_mode") or "NEUTRAL").upper() if latest else "NEUTRAL"
    if regime.upper() == "CHOPPY":
        return (
            "WAIT",
            "NEUTRAL / CHOP â€” WAIT FOR CONFIRMATION",
            "No clean trade yet. Need breakout or breakdown confirmation."
        )

    if False and trade_risk == "NO TRADE":
        advantage = (latest.get("current_advantage") or "Mixed").upper() if latest else "MIXED"
        if advantage == "SELLERS" or regime.upper() == "TRENDING DOWN":
            return (
                "WAIT",
                "BEARISH BIAS â€” NO TRADE UNTIL BREAKDOWN CONFIRMS",
                "Chop or low stability prevents a clean PUT entry."
            )
        if advantage == "BUYERS" or regime.upper() == "TRENDING UP":
            return (
                "WAIT",
                "BULLISH BIAS â€” NO TRADE UNTIL BREAKOUT CONFIRMS",
                "Chop or low stability prevents a clean CALL entry."
            )
        return "WAIT", "WAIT", "No clean trade yet. Need breakout or breakdown confirmation."

    bull_level = level_states["debug"].get("last_hit_bull_level", 0)
    bear_level = level_states["debug"].get("last_hit_bear_level", 0)
    bearish_structure = one_min_trend == "BEARISH" and (
        "lower" in one_min_reason or regime.upper() == "TRENDING DOWN"
    )
    bullish_structure = one_min_trend == "BULLISH" and (
        "higher" in one_min_reason or regime.upper() == "TRENDING UP"
    )
    bearish_correction = correction_mode in ("BEARISH CORRECTION", "BEARISH CONTINUATION")
    bullish_correction = correction_mode in ("BULLISH CORRECTION", "BULLISH CONTINUATION")

    if bear_level >= 3 and bearish_structure and vwap_position == "BELOW" and not bullish_correction:
        return "PUT", "PUT MODE", "Bearish breakdown is active below VWAP with bearish 1-minute structure."
    if bear_level >= 2 and bearish_structure and vwap_position == "BELOW":
        return "WAIT", "CORRECTION PUT", "Bearish confirmation is active below VWAP."
    if bear_level >= 1:
        return "WAIT", "WATCHING BEARISH TRIGGER", "Bearish trigger reached; waiting for confirmation."
    if bearish_correction and bearish_structure and vwap_position == "BELOW":
        return "WAIT", "CORRECTION PUT", "Bearish correction overrides the previous CALL bias."

    if bull_level >= 3 and bullish_structure and vwap_position == "ABOVE" and not bearish_correction:
        return "CALL", "CALL MODE", "Bullish breakout is active above VWAP with bullish 1-minute structure."
    if bull_level >= 2 and bullish_structure and vwap_position == "ABOVE" and not bearish_correction:
        return "CALL", "CALL MODE", "Bullish confirmation is active above VWAP with bullish 1-minute structure."
    if bull_level >= 1:
        return "WAIT", "WATCHING BULLISH TRIGGER", "Bullish trigger reached; waiting for confirmation."
    if bullish_correction and bullish_structure and vwap_position == "ABOVE":
        return "WAIT", "CORRECTION CALL", "Bullish correction overrides the previous PUT bias."

    if trade_risk == "NO TRADE":
        if bearish_structure:
            return "WAIT", "BEARISH BIAS â€” NO TRADE UNTIL BREAKDOWN CONFIRMS", "Low stability or participation blocks PUT MODE."
        if bullish_structure:
            return "WAIT", "BULLISH BIAS â€” NO TRADE UNTIL BREAKOUT CONFIRMS", "Low stability or participation blocks CALL MODE."
        return "WAIT", "WAIT", "No clean trade yet. Need breakout or breakdown confirmation."

    price = parse_float(current_price)
    bull_confirmation = parse_float(latest.get("bullish_confirmation")) if latest else None
    bear_confirmation = parse_float(latest.get("bearish_confirmation")) if latest else None
    bull_confirm_time = level_hit_timestamp["bull"].get(
        "2", level_hit_timestamp["bull"].get("3", 0)
    )
    bear_confirm_time = level_hit_timestamp["bear"].get(
        "2", level_hit_timestamp["bear"].get("3", 0)
    )
    bull_holding = (
        bull_level >= 2
        and bullish_structure
        and vwap_position == "ABOVE"
        and not bearish_correction
        and price is not None
        and bull_confirmation is not None
        and price >= bull_confirmation
        and time.time() - bull_confirm_time >= CONFIRMATION_HOLD_SECONDS
    )
    bear_holding = (
        bear_level >= 2
        and bearish_structure
        and vwap_position == "BELOW"
        and not bullish_correction
        and price is not None
        and bear_confirmation is not None
        and price <= bear_confirmation
        and time.time() - bear_confirm_time >= CONFIRMATION_HOLD_SECONDS
    )
    if bull_holding and bull_level >= bear_level:
        return "CALL", "CALL MODE", ""
    if bear_holding and bear_level > bull_level:
        return "PUT", "PUT MODE", ""
    if bull_level == 1 and bull_level >= bear_level:
        return "WAIT", "WATCHING BULLISH TRIGGER", ""
    if bear_level == 1:
        return "WAIT", "WATCHING BEARISH TRIGGER", ""
    return "WAIT", "WAIT", "No clean trade yet. Need breakout or breakdown confirmation."


def get_trade_decision_data(latest, regime, trade_risk, level_states=None):
    bullish_score = int(parse_float(latest.get("bullish_confluence_score")) or 0) if latest else 0
    bearish_score = int(parse_float(latest.get("bearish_confluence_score")) or 0) if latest else 0
    bullish_score = max(
        bullish_score,
        int(parse_float(latest.get("dashboard_bullish_weighted_score")) or 0) if latest else 0
    )
    bearish_score = max(
        bearish_score,
        int(parse_float(latest.get("dashboard_bearish_weighted_score")) or 0) if latest else 0
    )
    breakdown_active = bool(latest and latest.get("bearish_breakdown_active"))
    breakdown_extended = bool(latest and latest.get("bearish_breakdown_extended"))
    retest_failed = bool(latest and latest.get("bearish_retest_failed"))
    if breakdown_active:
        bearish_score = max(bearish_score, 8 if retest_failed else 7)
    neutral_score = max(0, 11 - bullish_score - bearish_score)
    hard_wait = (
        (regime.upper() == "CHOPPY" and not breakdown_active)
        or trade_risk == "NO TRADE"
    )
    bull_level = level_states["debug"].get("last_hit_bull_level", 0) if level_states else 0
    bear_level = level_states["debug"].get("last_hit_bear_level", 0) if level_states else 0
    a_plus_setup = (latest.get("a_plus_setup") or "NO").upper() if latest else "NO"

    trend_direction = (latest.get("dashboard_trend_direction") or "NEUTRAL").upper() if latest else "NEUTRAL"
    trend_action = latest.get("dashboard_trade_action") if latest else ""
    trend_reason = latest.get("dashboard_trend_reason") if latest else ""
    trend_override = bool(latest and latest.get("dashboard_trend_override"))
    strict_bullish_override = bool(latest and latest.get("dashboard_strict_bullish_override"))
    support_hold = bool(latest and latest.get("dashboard_support_hold"))
    resistance_hold = bool(latest and latest.get("dashboard_resistance_hold"))
    trend_extended = bool(latest and latest.get("dashboard_trend_extended"))

    if breakdown_active and retest_failed and trade_risk != "NO TRADE":
        mode = "PUT"
        header = "PUT CONFIRMATION"
        final_read = "PUT CONFIRMATION"
        reason = "Breakdown + failed retest + bearish continuation."
        advantage = "Sellers"
    elif breakdown_active and breakdown_extended:
        mode = "WAIT"
        header = "PUT WATCH â€” WAIT FOR RETEST"
        final_read = "PUT WATCH"
        reason = "Bearish breakdown active, but do not chase extended candle."
        advantage = "Sellers"
    elif breakdown_active:
        mode = "WAIT"
        header = "PUT WATCH"
        final_read = "PUT WATCH"
        reason = (
            "Bearish breakdown active; wait for failed-retest confirmation."
            if trade_risk != "NO TRADE"
            else "Bearish breakdown active, but risk controls still require WAIT."
        )
        advantage = "Sellers"
    elif trend_override and trend_direction == "BULLISH":
        mode = "CALL" if strict_bullish_override else (
            "CALL" if support_hold and not trend_extended and trade_risk != "NO TRADE" else "WAIT"
        )
        header = trend_action or "TRENDING UP â€” CALL WATCH"
        final_read = "CALL CONFIRMATION" if mode == "CALL" else "BULLISH TREND / CALL WATCH"
        reason = trend_reason + (
            " Risk controls and structure-based stops remain required."
            if strict_bullish_override else ""
        )
        advantage = "Buyers"
    elif trend_override and trend_direction == "BEARISH":
        mode = "PUT" if resistance_hold and not trend_extended and trade_risk != "NO TRADE" else "WAIT"
        header = trend_action or "TRENDING DOWN â€” PUT WATCH"
        final_read = "PUT CONFIRMATION" if mode == "PUT" else "BEARISH TREND / PUT WATCH"
        reason = trend_reason
        advantage = "Sellers"
    elif hard_wait:
        mode = "WAIT"
        header = "NEUTRAL / CHOP â€” WAIT FOR CONFIRMATION"
        final_read = "MIXED / WAIT"
        reason = "Market regime is CHOPPY or trade risk is NO TRADE."
        advantage = "Mixed"
    elif bearish_score >= 8 and bear_level >= 2 and a_plus_setup == "YES":
        mode = "PUT"
        header = "PUT MODE"
        final_read = "STRONG BEARISH ALIGNMENT"
        reason = f"{bearish_score} of 11 confluence factors align bearish."
        advantage = "Sellers"
    elif bullish_score >= 8 and bull_level >= 2 and a_plus_setup == "YES":
        mode = "CALL"
        header = "CALL MODE"
        final_read = "STRONG BULLISH ALIGNMENT"
        reason = f"{bullish_score} of 11 confluence factors align bullish."
        advantage = "Buyers"
    elif bearish_score >= 6 and bearish_score > bullish_score:
        mode = "WAIT"
        header = "WATCHING BEARISH TRIGGER"
        final_read = "BEARISH BUT NEEDS CONFIRMATION"
        reason = f"Bearish alignment is {bearish_score} of 11; waiting for confirmation or breakdown."
        advantage = "Sellers"
    elif bullish_score >= 6 and bullish_score > bearish_score:
        mode = "WAIT"
        header = "WATCHING BULLISH TRIGGER"
        final_read = "BULLISH BUT NEEDS CONFIRMATION"
        reason = f"Bullish alignment is {bullish_score} of 11; waiting for confirmation or breakout."
        advantage = "Buyers"
    else:
        mode = "WAIT"
        header = "NEUTRAL / CHOP â€” WAIT FOR CONFIRMATION"
        final_read = "MIXED / WAIT"
        reason = (latest.get("a_plus_wait_reason") or "No side has enough confluence.") if latest else "Waiting for confluence data."
        advantage = "Mixed"

    return {
        "mode": mode,
        "header": header,
        "final_read": final_read,
        "reason": reason,
        "advantage": advantage,
        "bullish_score": bullish_score,
        "bearish_score": bearish_score,
        "neutral_score": neutral_score,
        "a_plus_setup": a_plus_setup
    }


def build_trade_decision_meter(decision):
    net_score = decision["bullish_score"] - decision["bearish_score"]
    marker_position = max(4, min(96, 50 + (net_score / 11 * 46)))
    decision_class = (
        "bullish" if decision["mode"] == "CALL"
        else "bearish" if decision["mode"] == "PUT"
        else "mixed"
    )
    return f"""
    <section id="trade-decision-meter" class="trade-decision-meter {decision_class}">
      <div class="decision-meter-scale">
        <span>Bearish</span><span>Neutral</span><span>Bullish</span>
        <div class="decision-meter-track"><i id="decision-meter-marker" style="left: {marker_position:.1f}%"></i></div>
      </div>
      <div class="decision-meter-scores">
        <div>Bearish Score <strong id="decision-meter-bearish">{decision["bearish_score"]} / 11</strong></div>
        <div>Neutral/Conflict <strong id="decision-meter-neutral">{decision["neutral_score"]} / 11</strong></div>
        <div>Bullish Score <strong id="decision-meter-bullish">{decision["bullish_score"]} / 11</strong></div>
      </div>
      <p><b>Reason:</b> <span id="decision-meter-reason">{escape_value(decision["reason"])}</span></p>
    </section>
    """


def build_top_confluence_checklist(latest, decision, rows=None):
    def bias_from_text(value):
        text = str(value or "").upper()
        if "CONFLICT" in text or text == "LOW":
            return "conflict"
        if any(word in text for word in ("CALL", "BULL", "ABOVE", "HIGHER", "BUYERS")):
            return "bullish"
        if any(word in text for word in ("PUT", "BEAR", "BELOW", "LOWER", "SELLERS")):
            return "bearish"
        return "neutral"

    saved = {}
    if latest:
        for item in str(latest.get("confluence_factors") or "").split(";"):
            if "=" in item:
                name, value = item.split("=", 1)
                saved[name.strip().replace(" / ", "/")] = value.strip()

    advantage = latest.get("current_advantage") if latest else ""
    stability = latest.get("mode_stability") if latest else ""
    breakdown_active = bool(latest and latest.get("bearish_breakdown_active"))
    bearish_override = "Bearish" if breakdown_active else None
    trend_direction = (latest.get("dashboard_trend_direction") or "").title() if latest else ""
    weighted_direction = trend_direction if latest and latest.get("dashboard_trend_override") else None
    momentum_bias = weighted_direction or advantage
    factor_values = (
        ("Trend Box (High Weight)", bearish_override or weighted_direction or saved.get("Trend Box")),
        ("Momentum (High Weight)", bearish_override or momentum_bias),
        ("Last 15-Min Midpoint", latest.get("dashboard_midpoint_15m_bias") if latest else ""),
        ("Last 30-Min Midpoint", latest.get("dashboard_midpoint_30m_bias") if latest else ""),
        ("Market Box", bearish_override or saved.get("Market Box")),
        ("VWAP", bearish_override or saved.get("VWAP") or (latest.get("vwap_position") if latest else "")),
        ("Support/Resistance", bearish_override if latest and latest.get("price_below_support") else saved.get("Support/Resistance") or advantage),
        ("Candle Structure", bearish_override or (latest.get("last_3_candle_reading") if latest else "")),
        ("Stability", "CONFLICT" if str(stability).upper() == "LOW" else advantage if str(stability).upper() == "HIGH" else ""),
        ("Opening Range", latest.get("opening_range_position") if latest else ""),
        ("Market Breadth", saved.get("Market Breadth"))
    )
    labels = {
        "bullish": "Bias: Bullish &#10003;",
        "bearish": "Bias: Bearish &#10003;",
        "neutral": "Bias: Neutral &#9675;",
        "conflict": "Bias: Conflict &#9888;"
    }
    cards = "".join(
        f'<div class="top-confluence-factor {bias_from_text(value)}">'
        f'<span>{escape_value(name)}</span><strong>{labels[bias_from_text(value)]}</strong></div>'
        for name, value in factor_values
    )
    return f"""
    <details class="mobile-collapsible checklist-mobile-details" data-persist-id="trade-checklist">
      <summary>Trade checklist</summary>
      <section class="top-confluence-checklist standalone-confluence">
        <div class="top-confluence-heading">
          <div>
            <span>Decision alignment</span>
            <strong>TRADE CONFLUENCE CHECKLIST</strong>
          </div>
          <div class="top-confluence-final">
            <span>Final Read</span>
            <b id="top-confluence-final-read">{escape_value(decision["mode"])}</b>
          </div>
        </div>
        <div class="top-confluence-scores">
          <span>Bullish <b id="top-confluence-bullish">{decision["bullish_score"]} / 11</b></span>
          <span>Bearish <b id="top-confluence-bearish">{decision["bearish_score"]} / 11</b></span>
          <span>Neutral/Conflict <b id="top-confluence-neutral">{decision["neutral_score"]} / 11</b></span>
          <span>A+ Setup <b id="top-confluence-a-plus">{escape_value(decision["a_plus_setup"])}</b></span>
        </div>
        <p class="top-confluence-reason">Reason: <b id="top-confluence-reason">{escape_value(decision["reason"])}</b></p>
        <div class="top-confluence-factors">{cards}</div>
      </section>
    </details>
    """


def build_trade_risk_meter(latest, regime_data):
    eastern_now, time_window = get_eastern_time_window()
    regime = (regime_data.get("regime") or "CHOPPY").upper()
    stability = (latest.get("mode_stability") or "LOW").upper() if latest else "LOW"
    volume_filter = (latest.get("volume_filter") or "FAIL").upper() if latest else "FAIL"
    activity_filter = (latest.get("activity_filter") or "SLOW").upper() if latest else "SLOW"
    prediction = (latest.get("prediction") or "WAIT").upper() if latest else "WAIT"
    vwap_position = (latest.get("vwap_position") or "Mixed").upper() if latest else "MIXED"
    candle_reading = (latest.get("last_3_candle_reading") or "").lower() if latest else ""
    live_price = parse_float(latest.get("spy_price")) if latest else None
    support = parse_float(latest.get("nearest_support")) if latest else None
    resistance = parse_float(latest.get("nearest_resistance")) if latest else None
    live_volume = parse_float(latest.get("last_1m_bid_total")) if latest else None
    recent_volume_average = parse_float(latest.get("last_1m_bid_average")) if latest else None
    inside_structure = (
        live_price is not None
        and support is not None
        and resistance is not None
        and support <= live_price <= resistance
    )
    volume_below_average = volume_filter == "FAIL"
    signal_unstable = stability == "LOW"
    trending = regime in ("TRENDING UP", "TRENDING DOWN")
    vwap_candle_agree = (
        prediction == "CALL"
        and vwap_position == "ABOVE"
        and "bullish" in candle_reading
    ) or (
        prediction == "PUT"
        and vwap_position == "BELOW"
        and "bearish" in candle_reading
    )

    no_trade_reasons = []
    if latest and latest.get("_data_stale"):
        no_trade_reasons.append("live price data is older than 180 seconds")
    if regime == "CHOPPY":
        no_trade_reasons.append("market regime is CHOPPY")
    if stability == "LOW":
        no_trade_reasons.append("signal stability is LOW")
    if volume_filter == "FAIL":
        no_trade_reasons.append("volume filter failed")
    if activity_filter == "SLOW":
        no_trade_reasons.append("activity is SLOW")
    if time_window == "Midday Chop":
        no_trade_reasons.append("current time is Midday Chop")

    if no_trade_reasons:
        risk = "NO TRADE"
        risk_class = "no-trade"
        lesson = "Conditions do not support a clean trade."
        reasons = no_trade_reasons
    else:
        high_risk_reasons = []
        if 630 <= eastern_now.hour * 60 + eastern_now.minute < 900:
            high_risk_reasons.append("time is after 10:30 ET and before 3:00 ET")
        if volume_below_average:
            high_risk_reasons.append("volume is below normal")
        if signal_unstable:
            high_risk_reasons.append("signal is unstable")
        if inside_structure:
            high_risk_reasons.append("price is inside nearby support and resistance")

        low_risk = (
            time_window in ("Opening Momentum", "Power Hour")
            and volume_filter == "PASS"
            and activity_filter == "ACTIVE"
            and trending
            and stability == "HIGH"
            and vwap_candle_agree
        )

        if low_risk:
            risk = "LOW RISK"
            risk_class = "low"
            lesson = "Conditions are cleaner. Still wait for entry confirmation."
            reasons = ["time, participation, trend, stability, VWAP, and candles align"]
        elif high_risk_reasons:
            risk = "HIGH RISK"
            risk_class = "high"
            lesson = "Risk of fakeouts is elevated. Be very selective."
            reasons = high_risk_reasons
        else:
            risk = "MODERATE RISK"
            risk_class = "moderate"
            lesson = "Trade smaller or wait for stronger confirmation."
            reasons = ["conditions are usable but do not meet the cleanest setup criteria"]

    reason_items = "".join(f"<li>{escape_value(reason)}</li>" for reason in reasons)
    return f"""
    <section class="trade-risk-meter {risk_class}">
      <div class="trade-risk-heading">
        <span>Trade Risk</span>
        <strong>{escape_value(risk)}</strong>
        <p>{escape_value(lesson)}</p>
      </div>
      <div class="trade-risk-time">
        <span>{escape_value(time_window)}</span>
        <strong>{escape_value(eastern_now.strftime("%I:%M:%S %p ET"))}</strong>
      </div>
      <details>
        <summary>Risk details</summary>
        {build_education_box("Trade Risk", "Definition")}
        <ul>{reason_items}</ul>
        <div class="risk-input-grid">
          <span>Volume filter</span><strong>{escape_value(volume_filter)}</strong>
          <span>Activity filter</span><strong>{escape_value(activity_filter)}</strong>
          <span>Regime</span><strong>{escape_value(regime)}</strong>
          <span>Stability</span><strong>{escape_value(stability)}</strong>
          <span>Live SPY volume</span><strong>{escape_value(live_volume)}</strong>
          <span>Recent volume average</span><strong>{escape_value(recent_volume_average)}</strong>
          <span>Volume comparison</span><strong>{"BELOW NORMAL" if volume_below_average else "NORMAL / STRONG"}</strong>
          <span>Inside support/resistance</span><strong>{"YES" if inside_structure else "NO"}</strong>
          <span>VWAP + candles agree</span><strong>{"YES" if vwap_candle_agree else "NO"}</strong>
        </div>
        <p class="time-window-guide">
          Opening Momentum: 9:30-10:30 ET | Caution Window: 10:30-11:30 ET |
          Midday Chop: 11:30-2:00 ET | Afternoon Setup: 2:00-3:00 ET |
          Power Hour: 3:00-4:00 ET
        </p>
      </details>
    </section>
    """


def build_pre_market_panel(latest):
    if not latest:
        return ""

    bias = (latest.get("pre_market_bias") or "NEUTRAL").upper()
    bias_class = bias.lower()
    return f"""
    <section class="pre-market-panel {bias_class}">
      <div>
        <span>Current Market Phase</span>
        <strong>{escape_value(latest.get("market_phase") or "Market Closed")}</strong>
      </div>
      <div>
        <span>Pre-Market Bias</span>
        <strong>{escape_value(bias)}</strong>
        <p>Confidence: {escape_value(latest.get("pre_market_confidence"))}%</p>
      </div>
      <div class="pre-market-reason">
        <span>Reason</span>
        <p>{escape_value(latest.get("pre_market_reason"))}</p>
      </div>
      <details>
        <summary>Pre-market details</summary>
        <p><strong>High:</strong> {escape_value(latest.get("pre_market_high"))} |
           <strong>Low:</strong> {escape_value(latest.get("pre_market_low"))} |
           <strong>SPY move:</strong> {escape_value(latest.get("pre_market_spy_move"))}% |
           <strong>QQQ move:</strong> {escape_value(latest.get("pre_market_qqq_move"))}% |
           <strong>Relative volume:</strong> {escape_value(latest.get("pre_market_relative_volume"))}x</p>
        <p>Pre-market bias is not a trade signal. It is a directional expectation that must be confirmed after the open.</p>
      </details>
    </section>
    """


def detect_regime(rows):
    recent = []

    for row in rows[-45:]:
        price = parse_float(row.get("spy_price"))
        prediction = row.get("prediction", "WAIT").upper()
        vwap_position = (row.get("vwap_position") or "").upper()

        if price is not None:
            recent.append((price, prediction, vwap_position))

    if len(recent) < 9:
        return {
            "regime": "RANGE",
            "reason": "Not enough recent price history for a stable regime.",
            "call_percent": 0,
            "put_percent": 0,
            "wait_percent": 0,
            "flip_percent": 0,
            "range_percent": 0
        }

    prices = [price for price, _, _ in recent]
    predictions = [prediction for _, prediction, _ in recent]
    third = len(recent) // 3
    first_prices = prices[:third]
    middle_prices = prices[third:third * 2]
    last_prices = prices[third * 2:]
    counts = {
        prediction: predictions.count(prediction)
        for prediction in ("CALL", "PUT", "WAIT")
    }
    total = len(predictions)
    call_percent = counts["CALL"] / total * 100
    put_percent = counts["PUT"] / total * 100
    wait_percent = counts["WAIT"] / total * 100
    flips = sum(
        1
        for index in range(1, len(predictions))
        if predictions[index] != predictions[index - 1]
    )
    flip_percent = flips / (len(predictions) - 1) * 100
    average_price = sum(prices) / len(prices)
    price_range = max(prices) - min(prices)
    range_percent = (price_range / average_price * 100) if average_price else 0
    higher_highs = (
        max(first_prices) < max(middle_prices) < max(last_prices)
    )
    higher_lows = (
        min(first_prices) < min(middle_prices) < min(last_prices)
    )
    lower_highs = (
        max(first_prices) > max(middle_prices) > max(last_prices)
    )
    lower_lows = (
        min(first_prices) > min(middle_prices) > min(last_prices)
    )
    prior_up = (
        max(first_prices) < max(middle_prices)
        and min(first_prices) < min(middle_prices)
    )
    prior_down = (
        max(first_prices) > max(middle_prices)
        and min(first_prices) > min(middle_prices)
    )
    recent_predictions = [prediction for _, prediction, _ in recent[-third:]]
    recent_opposite_put = recent_predictions.count("PUT") / len(recent_predictions)
    recent_opposite_call = recent_predictions.count("CALL") / len(recent_predictions)
    recent_wait = recent_predictions.count("WAIT") / len(recent_predictions)
    recent_move = last_prices[-1] - last_prices[0]
    prior_move = middle_prices[-1] - first_prices[0]
    momentum_weakened = abs(recent_move) < abs(prior_move) * 0.45
    directional_slope = prices[-1] - prices[0]
    no_directional_slope = abs(directional_slope) <= max(0.05, price_range * 0.20)
    range_compression = range_percent <= 0.06
    latest_vwap_position = next(
        (position for _, _, position in reversed(recent) if position),
        "UNKNOWN"
    )
    vwap_neutral = latest_vwap_position in {"MIXED", "NEUTRAL", "INSIDE", "AT VWAP"}

    if higher_highs and higher_lows and directional_slope > 0:
        regime = "TRENDING UP"
        reason = "SPY is making higher highs and higher lows with a positive directional slope."
    elif lower_highs and lower_lows and directional_slope < 0:
        regime = "TRENDING DOWN"
        reason = "SPY is making lower highs and lower lows with a negative directional slope."
    elif prior_up and (
        recent_opposite_put >= 0.30
        or recent_wait >= 0.50
        or (momentum_weakened and not higher_highs)
    ):
        regime = "REVERSAL RISK"
        reason = "Earlier upward structure is weakening or opposite signals are increasing."
    elif prior_down and (
        recent_opposite_call >= 0.30
        or recent_wait >= 0.50
        or (momentum_weakened and not lower_lows)
    ):
        regime = "REVERSAL RISK"
        reason = "Earlier downward structure is weakening or opposite signals are increasing."
    elif vwap_neutral and no_directional_slope and range_compression:
        regime = "CHOPPY"
        reason = "VWAP is neutral, directional slope is absent, and the recent range is compressed."
    else:
        regime = "RANGE"
        reason = "Price is not compressed enough for CHOPPY and has not confirmed directional structure."

    return {
        "regime": regime,
        "reason": reason,
        "call_percent": call_percent,
        "put_percent": put_percent,
        "wait_percent": wait_percent,
        "flip_percent": flip_percent,
        "range_percent": range_percent,
        "directional_slope": directional_slope,
        "range_compression": range_compression,
        "vwap_neutral": vwap_neutral
    }


def build_regime_label(regime_data):
    regime = regime_data["regime"]
    regime_class = regime.lower().replace(" ", "-")

    return f"""
    <section class="regime-label {regime_class}">
      <span>Market Regime</span>
      <strong>{escape_value(regime)}</strong>
    </section>
    """


def build_regime_details(regime_data):
    return f"""
    <section class="regime-details">
      <p>{escape_value(regime_data["reason"])}</p>
      <div class="regime-grid">
        <div><span>CALL</span><strong>{regime_data["call_percent"]:.1f}%</strong></div>
        <div><span>PUT</span><strong>{regime_data["put_percent"]:.1f}%</strong></div>
        <div><span>WAIT</span><strong>{regime_data["wait_percent"]:.1f}%</strong></div>
        <div><span>Signal Flips</span><strong>{regime_data["flip_percent"]:.1f}%</strong></div>
        <div><span>Price Range</span><strong>{regime_data["range_percent"]:.3f}%</strong></div>
      </div>
    </section>
    """


def build_stability_label(latest):
    stability = (
        latest.get("mode_stability", "MEDIUM").upper()
        if latest else "MEDIUM"
    )
    stability_class = stability.lower()
    warning = (
        '<span class="stability-warning">Unstable signal. Avoid chasing.</span>'
        if stability == "LOW" else ""
    )

    return f"""
    <section class="stability-label {stability_class}">
      <span>Stability: <strong>{escape_value(stability)}</strong></span>
      {warning}
    </section>
    """


def build_stability_details(latest):
    if not latest:
        return '<p class="empty">Waiting for stability data.</p>'

    return f"""
    <section class="stability-details">
      <div class="stability-grid">
        <div><span>Previous Prediction</span><strong>{escape_value(latest.get("previous_prediction"))}</strong></div>
        <div><span>Current Prediction</span><strong>{escape_value(latest.get("prediction"))}</strong></div>
        <div><span>Mode Duration</span><strong>{escape_value(latest.get("mode_duration_minutes"))} min</strong></div>
        <div><span>Signal Flips 10m</span><strong>{escape_value(latest.get("signal_flip_count_10m"))}</strong></div>
        <div><span>Mode Stability</span><strong>{escape_value(latest.get("mode_stability"))}</strong></div>
      </div>
    </section>
    """


def build_vwap_label(latest):
    position = latest.get("vwap_position", "Mixed") if latest else "Mixed"
    position_class = position.lower()

    return f"""
    <section class="vwap-label {position_class}">
      <span>VWAP</span>
      <strong>{escape_value(position)}</strong>
    </section>
    """


def build_vwap_details(latest):
    if not latest:
        return '<p class="empty">Waiting for VWAP data.</p>'

    return f"""
    <section class="vwap-details">
      <div class="vwap-grid">
        <div><span>VWAP</span><strong>{escape_value(latest.get("vwap"))}</strong></div>
        <div><span>Position</span><strong>{escape_value(latest.get("vwap_position"))}</strong></div>
        <div><span>Confirmation</span><strong>{escape_value(latest.get("vwap_confirmation"))}</strong></div>
        <div><span>SPY Price</span><strong>{escape_value(latest.get("spy_price"))}</strong></div>
      </div>
    </section>
    """


def build_opening_range_label(latest):
    position = (
        latest.get("opening_range_position", "Inside")
        if latest else "Inside"
    )
    position_class = position.lower()

    return f"""
    <section class="opening-range-label {position_class}">
      <span>Opening Range: <strong>{escape_value(position)}</strong></span>
      <span>OR High: <strong>{escape_value(latest.get("opening_range_high") if latest else None)}</strong></span>
      <span>OR Low: <strong>{escape_value(latest.get("opening_range_low") if latest else None)}</strong></span>
    </section>
    """


def build_opening_range_details(latest):
    if not latest:
        return '<p class="empty">Waiting for opening range data.</p>'

    return f"""
    <section class="opening-range-details">
      <div class="opening-range-grid">
        <div><span>Position</span><strong>{escape_value(latest.get("opening_range_position"))}</strong></div>
        <div><span>Opening Range High</span><strong>{escape_value(latest.get("opening_range_high"))}</strong></div>
        <div><span>Opening Range Low</span><strong>{escape_value(latest.get("opening_range_low"))}</strong></div>
        <div><span>SPY Price</span><strong>{escape_value(latest.get("spy_price"))}</strong></div>
      </div>
      <p class="note">Opening range uses SPY candles from 9:30 through 9:34 ET.</p>
    </section>
    """


def calculate_pressure(rows, field, call_value, put_value, wait_value=None):
    call_count = sum(1 for row in rows if row.get(field) == call_value)
    put_count = sum(1 for row in rows if row.get(field) == put_value)
    wait_count = 0

    if wait_value is not None:
        wait_count = sum(1 for row in rows if row.get(field) == wait_value)

    directional_count = call_count + put_count

    if directional_count:
        call_percentage = (call_count / directional_count) * 100
        put_percentage = (put_count / directional_count) * 100
    else:
        call_percentage = 0
        put_percentage = 0

    return {
        "call_count": call_count,
        "put_count": put_count,
        "wait_count": wait_count,
        "call_percentage": call_percentage,
        "put_percentage": put_percentage
    }


def parse_row_timestamp(row):
    try:
        return datetime.strptime(row.get("time", ""), "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return None


def get_analysis_age_seconds(latest):
    for field in ("level_update_epoch", "structure_update_epoch"):
        update_epoch = parse_float((latest or {}).get(field))
        if update_epoch is not None and update_epoch > 0:
            return max(0, time.time() - update_epoch)

    timestamp = parse_row_timestamp(latest or {})
    if timestamp is None:
        return None
    eastern_now = datetime.now(ZoneInfo("America/New_York")).replace(tzinfo=None)
    return max(0, (eastern_now - timestamp).total_seconds())


def calculate_alert_pressure_windows(alert_rows, prediction_rows):
    timestamps = [
        timestamp
        for row in [*alert_rows, *prediction_rows[-1:]]
        for timestamp in [parse_row_timestamp(row)]
        if timestamp is not None
    ]
    reference_time = max(timestamps) if timestamps else None
    windows = []

    for minutes in (5, 15, 30):
        if reference_time is None:
            recent = []
        else:
            cutoff = reference_time.timestamp() - minutes * 60
            recent = [
                row for row in alert_rows
                if parse_row_timestamp(row) is not None
                and cutoff <= parse_row_timestamp(row).timestamp() <= reference_time.timestamp()
            ]
        call_rows = [
            row for row in recent
            if (row.get("option_type") or row.get("direction") or "").upper() in ("CALL", "UP")
        ]
        put_rows = [
            row for row in recent
            if (row.get("option_type") or row.get("direction") or "").upper() in ("PUT", "DOWN")
        ]
        call_moves = [
            value for row in call_rows
            for value in [parse_float(row.get("spy_change_percent"))]
            if value is not None
        ]
        put_moves = [
            value for row in put_rows
            for value in [parse_float(row.get("spy_change_percent"))]
            if value is not None
        ]
        call_average = sum(call_moves) / len(call_moves) if call_moves else None
        put_average = sum(put_moves) / len(put_moves) if put_moves else None
        if len(call_rows) > len(put_rows) and call_average is not None and call_average > 0:
            bias = "Bullish Pressure"
        elif len(put_rows) > len(call_rows) and put_average is not None and put_average < 0:
            bias = "Bearish Pressure"
        else:
            bias = "Mixed"
        windows.append({
            "minutes": minutes,
            "call_count": len(call_rows),
            "put_count": len(put_rows),
            "call_average": call_average,
            "put_average": put_average,
            "net_pressure": len(call_rows) - len(put_rows),
            "bias": bias
        })
    return windows


def directional_pressure_label(pressure_windows):
    preferred = next(
        (window for window in pressure_windows if window["minutes"] == 15),
        pressure_windows[0] if pressure_windows else None
    )
    if not preferred:
        return "Mixed"
    return preferred["bias"].replace(" Pressure", "")


def build_alert_pressure_windows(pressure_windows):
    cards = []
    for window in pressure_windows:
        bias_class = window["bias"].split()[0].lower()
        call_average = (
            f'{window["call_average"]:+.4f}%'
            if window["call_average"] is not None else "N/A"
        )
        put_average = (
            f'{window["put_average"]:+.4f}%'
            if window["put_average"] is not None else "N/A"
        )
        cards.append(f"""
        <article class="alert-pressure-window {bias_class}">
          <h3>Last {window["minutes"]} Minutes</h3>
          <strong>{escape_value(window["bias"])}</strong>
          <div><span>CALL Count</span><b>{window["call_count"]}</b></div>
          <div><span>PUT Count</span><b>{window["put_count"]}</b></div>
          <div><span>CALL Avg Move</span><b>{call_average}</b></div>
          <div><span>PUT Avg Move</span><b>{put_average}</b></div>
          <div><span>Net Pressure</span><b>{window["net_pressure"]:+d}</b></div>
        </article>
        """)
    return f"""
    <section class="recent-alert-pressure">
      <h3>Directional Pressure From Recent Alerts</h3>
      <p class="note">Pressure describes recent scanner direction. It is not a trade entry.</p>
      <div class="alert-pressure-windows">{''.join(cards)}</div>
    </section>
    """


def build_pressure_section(prediction_pressure, alert_pressure, pressure_windows=None):
    return f"""
    <section class="pressure-section">
      <h2>Call vs Put Pressure</h2>
      <p class="note">
        Scanner pressure, not real market options volume yet.
        Real options-chain volume will be added later.
      </p>
      <div class="pressure-grid">
        <div class="pressure-panel">
          <h3>Latest 50 Predictions</h3>
          <div class="counts">
            <span class="call-text">CALL {prediction_pressure['call_count']}</span>
            <span class="put-text">PUT {prediction_pressure['put_count']}</span>
            <span class="wait-text">WAIT {prediction_pressure['wait_count']}</span>
          </div>
          <div class="bar-label">
            <span>CALL {prediction_pressure['call_percentage']:.1f}%</span>
            <span>PUT {prediction_pressure['put_percentage']:.1f}%</span>
          </div>
          <div class="pressure-bar">
            <div class="call-bar" style="width: {prediction_pressure['call_percentage']:.2f}%"></div>
            <div class="put-bar" style="width: {prediction_pressure['put_percentage']:.2f}%"></div>
          </div>
        </div>
        <div class="pressure-panel">
          <h3>Accepted Alerts</h3>
          <div class="counts">
            <span class="call-text">CALL {alert_pressure['call_count']}</span>
            <span class="put-text">PUT {alert_pressure['put_count']}</span>
          </div>
          <div class="bar-label">
            <span>CALL {alert_pressure['call_percentage']:.1f}%</span>
            <span>PUT {alert_pressure['put_percentage']:.1f}%</span>
          </div>
          <div class="pressure-bar">
            <div class="call-bar" style="width: {alert_pressure['call_percentage']:.2f}%"></div>
            <div class="put-bar" style="width: {alert_pressure['put_percentage']:.2f}%"></div>
          </div>
        </div>
      </div>
      {build_alert_pressure_windows(pressure_windows or [])}
    </section>
    """


def build_mode_banner(latest):
    prediction = (
        latest.get("prediction", "WAIT").upper()
        if latest else "WAIT"
    )

    if prediction == "CALL":
        mode_text = "CALL MODE"
        mode_class = "call"
    elif prediction == "PUT":
        mode_text = "PUT MODE"
        mode_class = "put"
    else:
        mode_text = "WAIT"
        mode_class = "wait"

    return f"""
    <section class="mode-banner {mode_class}">
      <strong>{mode_text}</strong>
    </section>
    """


def get_feed_display_state(live_status):
    if live_status and bool(live_status.get("feed_connected")):
        return "FEED LIVE", "live"

    return "DASHBOARD FEED DISCONNECTED", "disconnected"


def build_sticky_signal_summary(latest, regime_data, live_status, decision=None, rows=None):
    regime = regime_data.get("regime", "CHOPPY")
    stability = (latest.get("mode_stability") or "MEDIUM") if latest else "N/A"
    live_available = bool(live_status and live_status.get("available"))
    live_price = (
        live_status.get("spy_price")
        if live_available else "Unavailable"
    )
    level_states = get_level_activation_states(latest or {}, live_price)
    trade_risk = get_trade_risk_override(latest, regime)
    decision = get_trade_decision_data(latest, regime, trade_risk, level_states)
    prediction = decision["mode"]
    mode_text = decision["header"]
    mode_reason = decision["reason"]
    mode_class = prediction.lower() if prediction in ("CALL", "PUT") else "wait"
    market_phase_display = get_market_phase_display(latest, regime)
    feed_status, feed_state = get_feed_display_state(live_status)
    choppy_warning = (
        """
        <div class="no-trade-warning">
          <strong>&#9888; NO TRADE ZONE</strong>
          <p>Market is choppy. Do not force CALL or PUT. Wait for clean structure, VWAP direction, and candle confirmation.</p>
        </div>
        """
        if regime.upper() == "CHOPPY" else ""
    )

    return f"""
    <section class="sticky-area">
    <div class="sticky-signal-summary {mode_class}">
      <div id="live-signal-banner" class="sticky-mode">
        <span>Decision</span>
        <strong id="live-market-phase">{escape_value(mode_text)}</strong>
      </div>
      <div class="sticky-context">
        <span id="live-recommendation">Phase: {escape_value(market_phase_display)}</span>
        <strong id="live-signal-reason">{escape_value(mode_reason) if mode_reason else "Waiting for confirmation."}</strong>
      </div>
      <div class="sticky-price">
        <span>SPY</span>
        <strong id="top-live-spy-price">{escape_value(live_price)}</strong>
        <small>Updated <b id="top-last-updated">{escape_value(live_status.get("updated_at") if live_status else "N/A")}</b></small>
        <small class="dashboard-version">Dashboard <b id="top-dashboard-version">v{escape_value(DASHBOARD_VERSION)}</b> Â· <span id="top-build-source">{escape_value(DASHBOARD_BUILD_SOURCE)}</span></small>
      </div>
    </div>
    <div class="sticky-pills">
      <span>Regime: <b id="top-regime-pill">{escape_value(regime)}</b></span>
      <span>Stability: <b id="top-stability-pill">{escape_value(stability)}</b></span>
      <span>Advantage: <b id="top-advantage-pill">{escape_value(decision["advantage"])}</b></span>
      <span>A+ Setup: <b id="top-a-plus-pill">{escape_value(decision["a_plus_setup"])}</b></span>
      <span>Score: <b id="top-score-pill">{max(decision["bullish_score"], decision["bearish_score"])} / 11</b></span>
    </div>
    <div id="top-stale-warning" class="data-stale-warning {feed_state}{" visible" if feed_state != "live" else ""}">
      {escape_value(feed_status)}
    </div>
    {choppy_warning}
    </section>
    """


def build_compact_sticky_signal_summary(latest, regime_data, live_status, decision=None):
    regime = regime_data.get("regime", "CHOPPY")
    stability = (latest.get("mode_stability") or "MEDIUM") if latest else "N/A"
    live_price = live_status.get("spy_price") if live_status and live_status.get("available") else "Unavailable"
    level_states = get_level_activation_states(latest or {}, live_price)
    trade_risk = get_trade_risk_override(latest, regime)
    decision = get_trade_decision_data(latest, regime, trade_risk, level_states)
    mode = decision["mode"]
    mode_class = mode.lower() if mode in ("CALL", "PUT") else "wait"
    feed_age = parse_float(live_status.get("data_age")) if live_status else None
    analysis_age = get_analysis_age_seconds(latest)
    feed_status, feed_state = get_feed_display_state(live_status)
    score = max(decision["bullish_score"], decision["bearish_score"])
    market_phase = get_market_phase_display(latest, regime)
    warning_class = " visible" if feed_state != "live" else ""
    confidence = parse_float((latest or {}).get("confidence")) or 0
    reason = str(decision.get("reason") or "Waiting for confirmation.")
    short_reason = f"{reason[:217]}..." if len(reason) > 220 else reason
    confirmation = (latest or {}).get("confirmation_needed") or "Wait for directional confirmation."
    invalidation = (latest or {}).get("invalidation_reason") or "No clean invalidation level yet."

    def level_value(field):
        value = (latest or {}).get(field)
        return value if value not in (None, "") else "N/A"

    choppy_warning = (
        '<div class="no-trade-warning"><strong>&#9888; NO TRADE ZONE</strong>'
        '<p>Market is choppy. Wait for clean structure and confirmation.</p></div>'
        if regime.upper() == "CHOPPY" else ""
    )
    return f"""
    <section id="dashboard-overview" class="sticky-area signal-hero-shell">
      <div class="sticky-signal-summary signal-hero {mode_class}">
        <div class="signal-hero-copy">
          <div class="signal-hero-kicker">
            <span class="feed-dot {feed_state}"></span>
            <strong id="top-feed-status">{escape_value(feed_status)}</strong>
            <span id="top-feed-age">Feed Age: {f"{feed_age:.0f} sec" if feed_age is not None else "N/A"}</span>
          </div>
          <h1>SPY Signal Dashboard</h1>
          <p id="live-signal-reason">{escape_value(short_reason)}</p>
          <div class="signal-hero-meta">
            <span>Updated <b id="top-last-updated">{escape_value(live_status.get("updated_at") if live_status else "N/A")}</b></span>
            <span id="top-analysis-age">Analysis Age: {f"{analysis_age:.0f} sec" if analysis_age is not None else "N/A"}</span>
            <span>v<b id="top-dashboard-version">{escape_value(DASHBOARD_VERSION)}</b> / <b id="top-build-source">{escape_value(DASHBOARD_BUILD_SOURCE)}</b></span>
          </div>
        </div>
        <div class="signal-hero-stats">
          <div class="hero-stat"><span>SPY Price</span><strong id="top-live-spy-price">{escape_value(live_price)}</strong></div>
          <div id="live-signal-banner" class="hero-stat hero-signal {mode_class}"><span>Current Signal</span><strong id="live-market-phase">{escape_value(mode)}</strong></div>
          <div class="hero-stat"><span>Confidence</span><strong>{confidence:.0f}%</strong></div>
        </div>
      </div>
      <div id="top-trend-override-pill" class="trend-override-banner{" visible" if latest and latest.get("dashboard_trend_override") else ""}">{escape_value(latest.get("dashboard_trend_override_label") or "TREND OVERRIDE ACTIVE") if latest else "TREND OVERRIDE ACTIVE"}</div>
      <div id="top-stale-warning" class="data-stale-warning {feed_state}{warning_class}">{escape_value(feed_status)}</div>
    </section>
    <div class="dashboard-primary-grid">
      <section id="signal-overview" class="overview-card signal-overview {mode_class}">
        <div class="overview-heading"><span>Signal</span><strong class="signal-badge {mode_class}">{escape_value(mode)}</strong></div>
        <div class="overview-grid">
          <div><span>Market Regime</span><strong id="top-regime-pill">{escape_value(regime)}</strong></div>
          <div><span>Current Advantage</span><strong id="top-advantage-pill">{escape_value(decision["advantage"])}</strong></div>
          <div><span>Trade Risk</span><strong>{escape_value(trade_risk)}</strong></div>
          <div><span>Stability</span><strong id="top-stability-pill">{escape_value(stability)}</strong></div>
          <div><span>A+ Setup</span><strong id="top-a-plus-pill">{escape_value(decision["a_plus_setup"])}</strong></div>
          <div><span>Confluence</span><strong id="top-score-pill">{score} / 11</strong><b id="top-score-compact" class="visually-hidden">{score} / 11</b></div>
        </div>
        <p id="live-recommendation" class="overview-footnote">Phase: {escape_value(market_phase)}</p>
      </section>
      <section id="next-action-overview" class="overview-card next-action-card">
        <div class="overview-heading"><span>Next Action</span><strong>What to wait for next</strong></div>
        <div class="action-copy"><span>Confirmation needed</span><strong>{escape_value(confirmation)}</strong></div>
        <div class="action-copy"><span>Invalidation</span><strong>{escape_value(invalidation)}</strong></div>
        <div class="level-summary-row bullish"><span>Bullish path</span><strong>{escape_value(level_value("bullish_trigger"))} / {escape_value(level_value("bullish_confirmation"))} / {escape_value(level_value("bullish_breakout"))}</strong></div>
        <div class="level-summary-row bearish"><span>Bearish path</span><strong>{escape_value(level_value("bearish_trigger"))} / {escape_value(level_value("bearish_confirmation"))} / {escape_value(level_value("bearish_breakdown"))}</strong></div>
        {choppy_warning}
      </section>
    </div>
    <section id="key-levels-overview" class="overview-card key-levels-card">
      <div class="overview-heading"><span>Key Levels</span><strong>Live structure map</strong></div>
      <div class="key-levels-grid">
        <div class="level-core"><span>Live Price</span><strong>{escape_value(live_price)}</strong></div>
        <div class="level-core"><span>Support</span><strong>{escape_value(level_value("nearest_support"))}</strong></div>
        <div class="level-core"><span>Resistance</span><strong>{escape_value(level_value("nearest_resistance"))}</strong></div>
        <div class="level-path bullish"><span>Bull Trigger</span><strong>{escape_value(level_value("bullish_trigger"))}</strong></div>
        <div class="level-path bullish"><span>Bull Confirmation</span><strong>{escape_value(level_value("bullish_confirmation"))}</strong></div>
        <div class="level-path bullish"><span>Bull Breakout</span><strong>{escape_value(level_value("bullish_breakout"))}</strong></div>
        <div class="level-path bearish"><span>Bear Trigger</span><strong>{escape_value(level_value("bearish_trigger"))}</strong></div>
        <div class="level-path bearish"><span>Bear Confirmation</span><strong>{escape_value(level_value("bearish_confirmation"))}</strong></div>
        <div class="level-path bearish"><span>Bear Breakdown</span><strong>{escape_value(level_value("bearish_breakdown"))}</strong></div>
      </div>
    </section>
    """


def build_time_discipline_card():
    return """
    <details class="mobile-collapsible time-discipline-details" data-persist-id="time-discipline">
      <summary>Time discipline</summary>
      <section id="time-discipline-card" class="time-discipline-card normal">
        <div class="time-discipline-session">
          <span>Time Discipline</span>
          <strong id="time-discipline-title">REGULAR SESSION</strong>
          <p id="time-discipline-message">Trade only confirmed setups with defined risk.</p>
        </div>
        <div class="time-discipline-clock">
          <span id="time-discipline-et">--:--:-- ET</span>
          <strong id="no-new-trades-countdown">Time until No New Trades: --:--:--</strong>
        </div>
        <button id="enable-sound-alerts" type="button" onclick="enableSoundAlerts()">
          Enable Sound Alerts
        </button>
      </section>
    </details>
    """


def calculate_intraday_midpoints(rows, current_price):
    parsed_rows = []
    for row in rows:
        timestamp_text = row.get("time") or ""
        price = parse_float(row.get("spy_price"))
        if price is None:
            continue
        try:
            timestamp = datetime.strptime(timestamp_text, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        parsed_rows.append((timestamp, price))

    if not parsed_rows:
        return []

    latest_time = parsed_rows[-1][0]
    current_date = latest_time.date()
    current = parse_float(current_price)

    def summarize(label, window_rows):
        if not window_rows:
            return {
                "label": label,
                "high": None,
                "midpoint": None,
                "low": None,
                "position": "N/A"
            }
        prices = [price for _, price in window_rows]
        high = max(prices)
        low = min(prices)
        midpoint = (high + low) / 2
        position = (
            "N/A" if current is None
            else "Above" if current > high
            else "Below" if current < low
            else "Inside"
        )
        return {
            "label": label,
            "high": high,
            "midpoint": midpoint,
            "low": low,
            "position": position
        }

    opening_rows = [
        item for item in parsed_rows
        if item[0].date() == current_date
        and (item[0].hour, item[0].minute) >= (9, 30)
        and (item[0].hour, item[0].minute) < (10, 0)
    ]
    last_30_start = latest_time.timestamp() - 30 * 60
    last_15_start = latest_time.timestamp() - 15 * 60
    last_30_rows = [
        item for item in parsed_rows
        if item[0].date() == current_date and item[0].timestamp() >= last_30_start
    ]
    last_15_rows = [
        item for item in parsed_rows
        if item[0].date() == current_date and item[0].timestamp() >= last_15_start
    ]
    return [
        summarize("Opening 30-Min Range", opening_rows),
        summarize("Last 30-Min Range", last_30_rows),
        summarize("Last 15-Min Range", last_15_rows)
    ]


def get_intraday_midpoint_bias(rows, current_price):
    current = parse_float(current_price)
    if current is None:
        return "Neutral"
    analyses = calculate_intraday_midpoints(rows, current)
    for analysis in reversed(analyses):
        midpoint = analysis.get("midpoint")
        if midpoint is not None:
            return (
                "Bullish" if current > midpoint + 0.02
                else "Bearish" if current < midpoint - 0.02
                else "Neutral"
            )
    return "Neutral"


def evaluate_dashboard_trend_override(latest, rows, alert_rows=None):
    result = {
        "dashboard_trend_override": False,
        "dashboard_strict_bullish_override": False,
        "dashboard_trend_override_label": "",
        "dashboard_trend_direction": "NEUTRAL",
        "dashboard_market_condition": "CHOPPY",
        "dashboard_trade_action": "WAIT",
        "dashboard_trend_reason": "",
        "dashboard_bullish_weighted_score": 0,
        "dashboard_bearish_weighted_score": 0,
        "dashboard_support_hold": False,
        "dashboard_resistance_hold": False,
        "dashboard_trend_extended": False,
        "dashboard_midpoint_15m_bias": "Neutral",
        "dashboard_midpoint_30m_bias": "Neutral",
        "dashboard_pressure_bias": "Mixed",
    }
    if not latest:
        return result

    price = parse_float(latest.get("spy_price"))
    if price is None:
        return result
    result["dashboard_market_condition"] = (latest.get("regime") or "CHOPPY").upper()

    minute_closes = {}
    minute_lows = {}
    for row in rows:
        timestamp = parse_row_timestamp(row)
        row_price = parse_float(row.get("spy_price"))
        if timestamp is not None and row_price is not None:
            minute = timestamp.replace(second=0, microsecond=0)
            minute_closes[minute] = row_price
            minute_lows[minute] = min(minute_lows.get(minute, row_price), row_price)
    recent = list(minute_closes.values())[-30:]
    recent_lows = list(minute_lows.values())[-30:]
    if len(recent) < 9:
        recent = [
            value
            for row in rows[-45:]
            for value in [parse_float(row.get("spy_price"))]
            if value is not None
        ]
        recent_lows = list(recent)
    if len(recent) < 6:
        return result

    third = max(2, len(recent) // 3)
    first = recent[:third]
    middle = recent[third:third * 2]
    last = recent[third * 2:] or recent[-third:]
    higher_structure = max(first) < max(middle) < max(last) and min(first) < min(middle) < min(last)
    lower_structure = max(first) > max(middle) > max(last) and min(first) > min(middle) > min(last)
    structure_text = " ".join(
        str(latest.get(field) or "")
        for field in ("market_structure", "mtf_1m_status", "mtf_1m_reason", "mtf_3m_status", "mtf_3m_reason")
    ).upper()
    bullish_structure = higher_structure or (
        "BULLISH" in structure_text and ("HIGHER HIGH" in structure_text or "HIGHER LOW" in structure_text)
    )
    bearish_structure = lower_structure or (
        "BEARISH" in structure_text and ("LOWER HIGH" in structure_text or "LOWER LOW" in structure_text)
    )
    one_min_status = str(latest.get("mtf_1m_status") or "").upper()
    one_min_reason = str(latest.get("mtf_1m_reason") or "").upper()
    vwap_position = str(latest.get("vwap_position") or "").upper()
    vwap = parse_float(latest.get("vwap"))
    price_above_vwap = vwap_position == "ABOVE" or (vwap is not None and price > vwap)
    recent_higher_lows = any(
        all(window[index] > window[index - 1] for index in range(1, len(window)))
        for size in range(3, min(5, len(recent_lows)) + 1)
        for window in [recent_lows[-size:]]
    )
    one_min_bullish = one_min_status == "BULLISH"
    higher_lows_confirmed = recent_higher_lows or "HIGHER LOW" in one_min_reason
    strict_bullish_override = (
        one_min_bullish
        and price_above_vwap
        and higher_lows_confirmed
        and not latest.get("bearish_breakdown_active")
    )

    midpoint_analyses = {
        analysis["label"]: analysis
        for analysis in calculate_intraday_midpoints(rows, price)
    }
    midpoint_15 = midpoint_analyses.get("Last 15-Min Range", {}).get("midpoint")
    midpoint_30 = midpoint_analyses.get("Last 30-Min Range", {}).get("midpoint")
    midpoint_15_bias = (
        "Bullish" if midpoint_15 is not None and price > midpoint_15 + 0.02
        else "Bearish" if midpoint_15 is not None and price < midpoint_15 - 0.02
        else "Neutral"
    )
    midpoint_30_bias = (
        "Bullish" if midpoint_30 is not None and price > midpoint_30 + 0.02
        else "Bearish" if midpoint_30 is not None and price < midpoint_30 - 0.02
        else "Neutral"
    )

    support = parse_float(latest.get("nearest_support"))
    resistance = parse_float(latest.get("nearest_resistance"))
    support_hold = support is not None and price >= support and min(recent[-6:]) >= support - 0.08
    resistance_hold = resistance is not None and price <= resistance and max(recent[-6:]) <= resistance + 0.08
    momentum_score = parse_float(latest.get("momentum_score")) or 0
    advantage = str(latest.get("current_advantage") or "").upper()
    momentum_text = " ".join(
        str(latest.get(field) or "")
        for field in ("last_3_candle_reading", "correction_mode", "mtf_overall_signal")
    ).upper()
    bullish_momentum = momentum_score >= 10 and (
        "BUYERS" in advantage or "BULL" in momentum_text or recent[-1] > recent[-4]
    )
    bearish_momentum = momentum_score >= 10 and (
        "SELLERS" in advantage or "BEAR" in momentum_text or recent[-1] < recent[-4]
    )

    pressure_windows = calculate_alert_pressure_windows(alert_rows or [], rows)
    pressure_15 = next((window for window in pressure_windows if window["minutes"] == 15), None)
    pressure_30 = next((window for window in pressure_windows if window["minutes"] == 30), None)
    pressure_biases = {
        window["bias"] for window in (pressure_15, pressure_30) if window
    }
    bullish_score = int(parse_float(latest.get("bullish_confluence_score")) or 0)
    bearish_score = int(parse_float(latest.get("bearish_confluence_score")) or 0)
    bullish_pressure = "Bullish Pressure" in pressure_biases or bullish_score >= 5
    bearish_pressure = "Bearish Pressure" in pressure_biases or bearish_score >= 5
    pressure_bias = (
        "Bullish" if "Bullish Pressure" in pressure_biases and "Bearish Pressure" not in pressure_biases
        else "Bearish" if "Bearish Pressure" in pressure_biases and "Bullish Pressure" not in pressure_biases
        else "Mixed"
    )

    # Structure, Trend Box, momentum, and the two short-term midpoints carry the
    # most weight. Daily midpoint remains macro context only.
    bull_weight = (
        (2 if bullish_structure else 0)
        + (2 if bullish_momentum else 0)
        + (1 if midpoint_15_bias == "Bullish" else 0)
        + (1 if midpoint_30_bias == "Bullish" else 0)
        + (1 if support_hold else 0)
        + (1 if bullish_pressure else 0)
    )
    bear_weight = (
        (2 if bearish_structure else 0)
        + (2 if bearish_momentum else 0)
        + (1 if midpoint_15_bias == "Bearish" else 0)
        + (1 if midpoint_30_bias == "Bearish" else 0)
        + (1 if resistance_hold or latest.get("bearish_breakdown_active") else 0)
        + (1 if bearish_pressure else 0)
    )
    recent_move = recent[-1] - recent[-6]
    recent_range = max(recent[-15:]) - min(recent[-15:])
    bullish_extended = bullish_structure and recent_move > max(0.30, recent_range * 0.70)
    bearish_extended = bearish_structure and recent_move < -max(0.30, recent_range * 0.70)
    bullish_override = strict_bullish_override or (
        bullish_structure and bullish_pressure and bull_weight >= 6 and bull_weight > bear_weight
    )
    bearish_override = (
        bearish_structure
        and bearish_pressure
        and bear_weight >= 6
        and bear_weight > bull_weight
    )

    result.update({
        "dashboard_bullish_weighted_score": min(11, max(bullish_score, bull_weight)),
        "dashboard_bearish_weighted_score": min(11, max(bearish_score, bear_weight)),
        "dashboard_support_hold": support_hold,
        "dashboard_resistance_hold": resistance_hold,
        "dashboard_midpoint_15m_bias": midpoint_15_bias,
        "dashboard_midpoint_30m_bias": midpoint_30_bias,
        "dashboard_pressure_bias": pressure_bias,
        "dashboard_strict_bullish_override": strict_bullish_override,
    })
    if bullish_override:
        action = "CALL CONFIRMATION" if support_hold and not bullish_extended else (
            "CALL WATCH â€” WAIT FOR PULLBACK / RETEST" if bullish_extended else "TRENDING UP â€” CALL WATCH"
        )
        result.update({
            "dashboard_trend_override": True,
            "dashboard_trend_override_label": "TREND OVERRIDE ACTIVE",
            "dashboard_trend_direction": "BULLISH",
            "dashboard_market_condition": "TRENDING UP",
            "dashboard_trade_action": action,
            "dashboard_trend_extended": bullish_extended,
            "dashboard_trend_reason": (
                "TREND OVERRIDE ACTIVE: 1-minute trend is bullish, price is above VWAP, "
                "and recent candles are forming higher lows."
                if strict_bullish_override else
                "Higher highs/higher lows, bullish short-term midpoints, support holding, "
                "bullish momentum, and CALL pressure/confluence override the older CHOPPY label."
            ),
        })
    elif bearish_override:
        action = "PUT CONFIRMATION" if (resistance_hold or latest.get("bearish_retest_failed")) and not bearish_extended else (
            "PUT WATCH â€” WAIT FOR PULLBACK / RETEST" if bearish_extended else "TRENDING DOWN â€” PUT WATCH"
        )
        result.update({
            "dashboard_trend_override": True,
            "dashboard_trend_override_label": "TREND OVERRIDE ACTIVE",
            "dashboard_trend_direction": "BEARISH",
            "dashboard_market_condition": "TRENDING DOWN",
            "dashboard_trade_action": action,
            "dashboard_trend_extended": bearish_extended,
            "dashboard_trend_reason": (
                "Lower highs/lower lows, bearish short-term midpoints, resistance/breakdown control, "
                "bearish momentum, and PUT pressure/confluence override the older CHOPPY label."
            ),
        })
    return result


def calculate_daily_midpoint_source(rows, current_price=None):
    session_filter = "Previous regular trading session only: 9:30 AM ET to 4:00 PM ET"
    sessions = {}
    for row in rows:
        timestamp_text = row.get("time") or ""
        price = parse_float(row.get("spy_price"))
        if price is None or price <= 0:
            continue
        try:
            timestamp = datetime.strptime(timestamp_text, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        if not (datetime.min.time().replace(hour=9, minute=30) <= timestamp.time() <= datetime.min.time().replace(hour=16, minute=0)):
            continue
        sessions.setdefault(timestamp.date(), []).append({
            "timestamp": timestamp,
            "timestamp_text": timestamp_text,
            "price": price
        })

    today_et = datetime.now(ZoneInfo("America/New_York")).date()
    prior_dates = sorted(date for date in sessions if date < today_et)
    if not prior_dates:
        return {
            "available": False,
            "suspicious": True,
            "warning": "DAILY MIDPOINT SOURCE CHECK NEEDED",
            "reasons": ["No previous regular-session rows are available."],
            "date_used": "N/A",
            "source_file": os.path.abspath(PREDICTION_FILE),
            "session_filter": session_filter,
            "rows_used": 0,
            "raw_rows": 0
        }

    session_date = prior_dates[-1]
    raw_rows = sessions[session_date]
    sorted_prices = sorted(item["price"] for item in raw_rows)
    median_price = sorted_prices[len(sorted_prices) // 2]
    outlier_limit = median_price * 0.03
    used_rows = [
        item for item in raw_rows
        if abs(item["price"] - median_price) <= outlier_limit
    ]
    reasons = []
    if len(used_rows) != len(raw_rows):
        reasons.append(
            f"{len(raw_rows) - len(used_rows)} price row(s) were more than 3% from the session median and excluded."
        )
    if len(raw_rows) < 30:
        reasons.append("Fewer than 30 regular-session rows were available.")
    session_first = min(raw_rows, key=lambda item: item["timestamp"])
    session_last = max(raw_rows, key=lambda item: item["timestamp"])
    if session_first["timestamp"].time() > datetime.min.time().replace(hour=10, minute=0):
        reasons.append("Previous-session data starts too late to represent the opening session.")
    if session_last["timestamp"].time() < datetime.min.time().replace(hour=15, minute=30):
        reasons.append("Previous-session data ends before 3:30 PM ET and may be incomplete.")
    if (today_et - session_date).days > 4:
        reasons.append("The previous-session source file may be stale.")
    if not used_rows:
        reasons.append("No usable regular-session rows remain after validation.")
        used_rows = raw_rows

    raw_high_row = max(raw_rows, key=lambda item: item["price"])
    raw_low_row = min(raw_rows, key=lambda item: item["price"])
    high_row = max(used_rows, key=lambda item: item["price"])
    low_row = min(used_rows, key=lambda item: item["price"])
    midpoint = (high_row["price"] + low_row["price"]) / 2
    validated_range_percent = (
        (high_row["price"] - low_row["price"]) / midpoint * 100
        if midpoint else 0
    )
    if validated_range_percent > 3:
        reasons.append(
            f"Validated regular-session range is unusually wide at {validated_range_percent:.2f}%."
        )

    current = parse_float(current_price)
    if current is None or reasons:
        position = "Neutral"
    elif current > midpoint + 0.10:
        position = "Bullish"
    elif current < midpoint - 0.10:
        position = "Bearish"
    else:
        position = "Neutral"

    return {
        "available": True,
        "suspicious": bool(reasons),
        "warning": "DAILY MIDPOINT SOURCE CHECK NEEDED" if reasons else "",
        "reasons": reasons,
        "date_used": session_date.isoformat(),
        "source_file": os.path.abspath(PREDICTION_FILE),
        "session_filter": session_filter,
        "rows_used": len(used_rows),
        "raw_rows": len(raw_rows),
        "high": high_row["price"],
        "high_timestamp": high_row["timestamp_text"],
        "low": low_row["price"],
        "low_timestamp": low_row["timestamp_text"],
        "raw_high": raw_high_row["price"],
        "raw_high_timestamp": raw_high_row["timestamp_text"],
        "raw_low": raw_low_row["price"],
        "raw_low_timestamp": raw_low_row["timestamp_text"],
        "session_first_timestamp": session_first["timestamp_text"],
        "session_last_timestamp": session_last["timestamp_text"],
        "midpoint": midpoint,
        "position": position,
        "validated_range_percent": validated_range_percent
    }


def neutralize_suspicious_daily_midpoint(latest, daily_midpoint):
    if not latest or not daily_midpoint.get("suspicious"):
        return
    factors = []
    removed_bias = None
    for item in str(latest.get("confluence_factors") or "").split(";"):
        if "=" not in item:
            if item.strip():
                factors.append(item.strip())
            continue
        name, value = item.split("=", 1)
        if name.strip().replace(" / ", "/") == "Yesterday Midpoint":
            removed_bias = value.strip().upper()
            value = "NEUTRAL"
        factors.append(f"{name.strip()}={value.strip()}")
    if removed_bias == "CALL":
        latest["bullish_confluence_score"] = max(
            0, int(parse_float(latest.get("bullish_confluence_score")) or 0) - 1
        )
    elif removed_bias == "PUT":
        latest["bearish_confluence_score"] = max(
            0, int(parse_float(latest.get("bearish_confluence_score")) or 0) - 1
        )
    latest["confluence_score"] = max(
        int(parse_float(latest.get("bullish_confluence_score")) or 0),
        int(parse_float(latest.get("bearish_confluence_score")) or 0)
    )
    latest["confluence_factors"] = "; ".join(factors)
    latest["daily_midpoint_source_suspicious"] = True


def build_intraday_midpoints(rows, current_price):
    analyses = calculate_intraday_midpoints(rows, current_price)
    cards = []
    for analysis in analyses:
        if analysis["midpoint"] is None:
            values = (
                "<div><span>High</span><strong>N/A</strong></div>"
                "<div><span>Midpoint</span><strong>N/A</strong></div>"
                "<div><span>Low</span><strong>N/A</strong></div>"
                "<div><span>Current Position</span><strong>N/A</strong></div>"
            )
        else:
            values = (
                f'<div><span>High</span><strong>{analysis["high"]:.2f}</strong></div>'
                f'<div><span>Midpoint</span><strong>{analysis["midpoint"]:.2f}</strong></div>'
                f'<div><span>Low</span><strong>{analysis["low"]:.2f}</strong></div>'
                f'<div><span>Current Position</span><strong>{analysis["position"]}</strong></div>'
            )
        cards.append(
            f'<article class="intraday-midpoint-card">'
            f'<h3>{escape_value(analysis["label"])}</h3>'
            f'<div class="intraday-midpoint-values">{values}</div></article>'
        )
    return f"""
    <section class="intraday-midpoints">
      <h2>INTRADAY MIDPOINTS</h2>
      <div class="intraday-midpoint-grid">{''.join(cards)}</div>
      <p>Intraday midpoints carry more weight for scalping because they describe the current session's nearby balance.</p>
    </section>
    """


def build_daily_midpoint(rows, current_price, analysis=None):
    analysis = analysis or calculate_daily_midpoint_source(rows, current_price)
    if not analysis.get("available"):
        return '<section class="daily-midpoint"><p class="empty">Yesterday midpoint data is not available yet.</p></section>'

    warning = ""
    if analysis.get("suspicious"):
        reasons = "".join(f"<li>{escape_value(reason)}</li>" for reason in analysis.get("reasons", []))
        warning = f"""
        <div class="daily-midpoint-warning">
          <strong>DAILY MIDPOINT SOURCE CHECK NEEDED</strong>
          <p>Daily Midpoint is neutral and excluded from confluence until its source is clean.</p>
          <ul>{reasons}</ul>
        </div>
        """
    return f"""
    <section class="daily-midpoint">
      <h2>Daily Midpoint <small>Macro Bias Only</small></h2>
      {warning}
      <div class="midpoint-grid">
        <div><span>Yesterday High</span><strong>{analysis["high"]:.2f}</strong></div>
        <div><span>Yesterday Midpoint (50%)</span><strong>{analysis["midpoint"]:.2f}</strong></div>
        <div><span>Yesterday Low</span><strong>{analysis["low"]:.2f}</strong></div>
        <div><span>Current Position</span><strong>{escape_value(analysis["position"])}</strong></div>
      </div>
      <p>Macro bias only. Intraday midpoints carry more weight for scalping.</p>
      <details class="daily-midpoint-debug">
        <summary>Daily Midpoint Debug Panel</summary>
        <div class="midpoint-grid">
          <div><span>Date Used</span><strong>{escape_value(analysis["date_used"])}</strong></div>
          <div><span>Source File Used</span><strong>{escape_value(analysis["source_file"])}</strong></div>
          <div><span>Row Timestamp Used For High</span><strong>{escape_value(analysis["high_timestamp"])}</strong></div>
          <div><span>Row Timestamp Used For Low</span><strong>{escape_value(analysis["low_timestamp"])}</strong></div>
          <div><span>Raw High</span><strong>{analysis["raw_high"]:.4f}</strong></div>
          <div><span>Raw Low</span><strong>{analysis["raw_low"]:.4f}</strong></div>
          <div><span>Calculated Midpoint</span><strong>{analysis["midpoint"]:.4f}</strong></div>
          <div><span>Number Of Rows Used</span><strong>{analysis["rows_used"]} of {analysis["raw_rows"]}</strong></div>
          <div><span>Session Filter Used</span><strong>{escape_value(analysis["session_filter"])}</strong></div>
          <div><span>First Session Row</span><strong>{escape_value(analysis["session_first_timestamp"])}</strong></div>
          <div><span>Last Session Row</span><strong>{escape_value(analysis["session_last_timestamp"])}</strong></div>
        </div>
      </details>
    </section>
    """


def build_trend_box(rows, current_price):
    recent_prices = [
        price
        for row in rows[-120:]
        for price in [parse_float(row.get("spy_price"))]
        if price is not None
    ]
    price = parse_float(current_price)
    if len(recent_prices) < 3 or price is None:
        return '<p class="empty">Waiting for enough recent prices to build the Trend Box.</p>'

    box_source = recent_prices[:-5] if len(recent_prices) >= 12 else recent_prices[:-1]
    evaluation_prices = recent_prices[-5:]
    box_high = max(box_source)
    box_low = min(box_source)
    midpoint = (box_high + box_low) / 2
    tolerance = max(0.03, (box_high - box_low) * 0.08)

    if price > box_high:
        location = "Above box - breakout strength"
        action = "WATCH CALL"
    elif price < box_low:
        location = "Below box - breakdown weakness"
        action = "WATCH PUT"
    elif price >= midpoint:
        location = "Inside box, above midpoint - buyers stronger"
        action = "WAIT"
    else:
        location = "Inside box, below midpoint - sellers stronger"
        action = "WAIT"

    prior_prices = evaluation_prices[:-1]
    broke_above = any(value > box_high + tolerance for value in prior_prices)
    broke_below = any(value < box_low - tolerance for value in prior_prices)
    near_top = abs(price - box_high) <= tolerance
    near_bottom = abs(price - box_low) <= tolerance
    if broke_above and near_top:
        retest_status = "RETEST HOLDING" if price >= box_high else "RETEST IN PROGRESS"
    elif broke_below and near_bottom:
        retest_status = "RETEST HOLDING" if price <= box_low else "RETEST IN PROGRESS"
    elif broke_above and price < box_high - tolerance:
        retest_status = "RETEST FAILED"
    elif broke_below and price > box_low + tolerance:
        retest_status = "RETEST FAILED"
    else:
        retest_status = "NO RETEST"

    return f"""
    <section class="trend-box">
      <div class="trend-box-grid">
        <div><span>Trend Box High</span><strong>{box_high:.2f}</strong></div>
        <div><span>Trend Box Midpoint</span><strong>{midpoint:.2f}</strong></div>
        <div><span>Trend Box Low</span><strong>{box_low:.2f}</strong></div>
        <div><span>Current Location</span><strong>{escape_value(location)}</strong></div>
        <div><span>Retest Status</span><strong>{escape_value(retest_status)}</strong></div>
        <div><span>Suggested Action</span><strong>{escape_value(action)}</strong></div>
      </div>
      <p class="note">The box shows the full recent move. The midpoint tells who controls the move. The edges act like support and resistance.</p>
    </section>
    """


def build_market_structure_box(rows, current_price, daily_midpoint_analysis=None):
    minute_closes = {}
    daily_prices = {}
    for row in rows:
        timestamp_text = row.get("time") or ""
        price = parse_float(row.get("spy_price"))
        if price is None or len(timestamp_text) < 10:
            continue
        daily_prices.setdefault(timestamp_text[:10], []).append(price)
        try:
            timestamp = datetime.strptime(timestamp_text, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        minute_closes[timestamp.replace(second=0, microsecond=0)] = price

    recent_closes = list(minute_closes.values())[-12:]
    price = parse_float(current_price)
    if len(recent_closes) < 5 or price is None:
        return '<p class="empty">Waiting for enough one-minute closes to build the Market Box.</p>'

    range_high = max(recent_closes)
    range_low = min(recent_closes)
    range_midpoint = (range_high + range_low) / 2
    range_width = range_high - range_low
    narrow_range_limit = max(0.30, price * 0.0007)
    balance_area = len(recent_closes) >= 8 and range_width <= narrow_range_limit

    if price > range_high:
        box_status = "ABOVE BOX = Bullish"
    elif price < range_low:
        box_status = "BELOW BOX = Bearish"
    else:
        box_status = "INSIDE BOX = Wait"

    daily_midpoint_analysis = daily_midpoint_analysis or calculate_daily_midpoint_source(rows, price)
    if daily_midpoint_analysis.get("available"):
        yesterday_high = daily_midpoint_analysis["high"]
        yesterday_low = daily_midpoint_analysis["low"]
        yesterday_midpoint = daily_midpoint_analysis["midpoint"]
        if daily_midpoint_analysis.get("suspicious"):
            midpoint_summary = "Yesterday Midpoint neutral - source check needed"
        elif price > yesterday_midpoint + 0.10:
            midpoint_summary = "Above Yesterday Midpoint"
        elif price < yesterday_midpoint - 0.10:
            midpoint_summary = "Below Yesterday Midpoint"
        else:
            midpoint_summary = "Near Yesterday Midpoint"
        yesterday_html = (
            f"<div><span>Yesterday High</span><strong>{yesterday_high:.2f}</strong></div>"
            f"<div><span>Yesterday Midpoint</span><strong>{yesterday_midpoint:.2f}</strong></div>"
            f"<div><span>Yesterday Low</span><strong>{yesterday_low:.2f}</strong></div>"
        )
    else:
        midpoint_summary = "Yesterday levels unavailable"
        yesterday_html = (
            "<div><span>Yesterday High</span><strong>N/A</strong></div>"
            "<div><span>Yesterday Midpoint</span><strong>N/A</strong></div>"
            "<div><span>Yesterday Low</span><strong>N/A</strong></div>"
        )

    balance_summary = "Inside Balance Area" if balance_area and range_low <= price <= range_high else "Outside Balance Area"
    balance_status = "BALANCE AREA" if balance_area else "NO BALANCE AREA"

    return f"""
    <section class="market-box">
      <div class="market-box-status {('balanced' if balance_area else 'unbalanced')}">
        <span>Consolidation Status</span><strong>{balance_status}</strong>
      </div>
      <div class="market-box-grid">
        <div><span>Range High</span><strong>{range_high:.2f}</strong></div>
        <div><span>Range Midpoint</span><strong>{range_midpoint:.2f}</strong></div>
        <div><span>Range Low</span><strong>{range_low:.2f}</strong></div>
        <div><span>Current Box Status</span><strong>{box_status}</strong></div>
        {yesterday_html}
      </div>
      <div class="market-structure-summary">
        <h3>Market Structure Summary</h3>
        <p>{escape_value(midpoint_summary)}</p>
        <p>{escape_value(balance_summary)}</p>
      </div>
      <p class="note">The Market Box uses the latest one-minute closes. A narrow range with at least eight closes is marked as a balance area.</p>
    </section>
    """


def build_trade_confluence(latest, regime_data, engine_rows, breadth_row, rows):
    if not latest:
        return '<p class="empty">Waiting for confluence data.</p>'

    regime = (regime_data.get("regime") or "CHOPPY").upper()
    trade_risk = get_trade_risk_override(latest, regime)
    price = parse_float(latest.get("spy_price"))
    vwap_position = (latest.get("vwap_position") or "Mixed").upper()
    advantage = (latest.get("current_advantage") or "Mixed").upper()
    engine_bias = "Neutral"
    if engine_rows:
        bullish = sum((row.get("status") or "").upper() == "BULLISH" for row in engine_rows)
        bearish = sum((row.get("status") or "").upper() == "BEARISH" for row in engine_rows)
        engine_bias = "Bullish" if bullish > bearish else "Bearish" if bearish > bullish else "Neutral"
    breadth_text = (breadth_row.get("classification") or "Neutral") if breadth_row else "Neutral"

    def bias_from_text(value):
        text = str(value or "").upper()
        if "CONFLICT" in text:
            return "Conflict"
        if any(word in text for word in ("BULLISH", "TRENDING UP", "ABOVE", "BUYERS", "CALL")):
            return "Bullish"
        if any(word in text for word in ("BEARISH", "TRENDING DOWN", "BELOW", "SELLERS", "PUT")):
            return "Bearish"
        return "Neutral"

    recent_prices = [parse_float(row.get("spy_price")) for row in rows[-120:]]
    recent_prices = [value for value in recent_prices if value is not None]
    trend_box_bias = "Neutral"
    market_box_bias = "Neutral"
    midpoint_bias = "Neutral"
    if len(recent_prices) >= 5 and price is not None:
        source = recent_prices[:-1]
        trend_high, trend_low = max(source), min(source)
        trend_mid = (trend_high + trend_low) / 2
        trend_box_bias = "Bullish" if price > trend_high else "Bearish" if price < trend_low else "Bullish" if price > trend_mid else "Bearish"
        minute_source = recent_prices[-13:-1] or recent_prices[:-1]
        box_high, box_low = max(minute_source), min(minute_source)
        market_box_bias = "Bullish" if price > box_high else "Bearish" if price < box_low else "Neutral"

    grouped = {}
    for row in rows:
        timestamp = row.get("time") or ""
        row_price = parse_float(row.get("spy_price"))
        if len(timestamp) >= 10 and row_price is not None:
            grouped.setdefault(timestamp[:10], []).append(row_price)
    dates = sorted(grouped)
    if len(dates) >= 2 and price is not None:
        yesterday = grouped[dates[-2]]
        yesterday_mid = (max(yesterday) + min(yesterday)) / 2
        midpoint_bias = "Bullish" if price > yesterday_mid + 0.10 else "Bearish" if price < yesterday_mid - 0.10 else "Neutral"

    bull_level = last_hit_bull_level
    bear_level = last_hit_bear_level
    level_bias = "Bullish" if bull_level > bear_level else "Bearish" if bear_level > bull_level else "Neutral"
    volume_bias = "Neutral" if (latest.get("volume_filter") or "").upper() == "FAIL" else bias_from_text(latest.get("prediction"))
    time_bias = "Conflict" if trade_risk == "NO TRADE" else "Neutral"
    factors = [
        ("Market Regime", bias_from_text(regime)),
        ("Trend Box", trend_box_bias),
        ("Market Box", market_box_bias),
        ("Intraday Midpoint", get_intraday_midpoint_bias(rows, price)),
        ("VWAP", bias_from_text(vwap_position)),
        ("Support / Resistance", bias_from_text(advantage)),
        ("Bull/Bear Levels", level_bias),
        ("Volume / RVOL", volume_bias),
        ("Engine Health", engine_bias),
        ("Market Breadth", bias_from_text(breadth_text)),
        ("Time of Day Risk", time_bias)
    ]
    saved_factors = {}
    for item in str(latest.get("confluence_factors") or "").split(";"):
        if "=" in item:
            name, value = item.split("=", 1)
            saved_factors[name.strip()] = value.strip().upper()
    if saved_factors:
        normalized = {"CALL": "Bullish", "PUT": "Bearish", "NEUTRAL": "Neutral", "CONFLICT": "Conflict"}
        factors = [
            (
                name,
                bias if name == "Intraday Midpoint"
                else normalized.get(
                    saved_factors.get(name.replace(" / ", "/"), saved_factors.get(name, "NEUTRAL")),
                    "Neutral"
                )
            )
            for name, bias in factors
        ]
    if latest.get("bearish_breakdown_active"):
        bearish_names = {
            "Market Regime", "Trend Box", "Market Box", "VWAP", "Bull/Bear Levels"
        }
        if latest.get("price_below_support"):
            bearish_names.add("Support / Resistance")
        factors = [
            (name, "Bearish" if name in bearish_names else bias)
            for name, bias in factors
        ]
    icons = {"Bullish": "Bullish &#9989;", "Bearish": "Bearish &#9989;", "Neutral": "Neutral &#9898;", "Conflict": "Conflict &#9888;"}
    factor_rows = "".join(
        f'<div class="confluence-factor {bias.lower()}"><span>&#9744; {escape_value(name)}</span><strong>{icons[bias]}</strong></div>'
        for name, bias in factors
    )
    return f"""
    <section class="confluence-checklist">
      <h2>TRADE CONFLUENCE CHECKLIST</h2>
      <details><summary>Checklist details</summary><div class="confluence-factors">{factor_rows}</div></details>
      <p class="note">Confluence means multiple independent clues agree. One signal alone is not enough.</p>
    </section>
    """


def get_market_phase_display(latest, regime):
    market_phase = (latest.get("market_phase") or "").upper() if latest else ""
    correction = (latest.get("correction_mode") or "").upper() if latest else ""
    if latest and latest.get("bearish_breakdown_active"):
        return "Bearish Breakdown"
    if market_phase == "MIDDAY CHOP":
        return "Midday Chop"
    if market_phase == "POWER HOUR":
        return "Power Hour"
    if "CORRECTION" in correction:
        return "Correction"
    if "PULLBACK" in correction:
        return "Pullback"
    if regime.upper() == "TRENDING UP":
        return "Trending Up"
    if regime.upper() == "TRENDING DOWN":
        return "Trending Down"
    if market_phase in ("OPENING RANGE", "OPENING MOMENTUM"):
        return "Opening Drive"
    return "Range"


def build_top_education_guides():
    topics = (
        "CALL / PUT / WAIT",
        "Market Regime",
        "Stability",
        "Current Advantage",
        "Confirmation Needed",
        "Invalidation"
    )
    guides = "".join(build_education_box(topic, topic) for topic in topics)
    return f'<section class="top-education-guides">{guides}</section>'


def build_reversal_monitor(latest):
    state = (
        (latest.get("reversal_state") or "NO REVERSAL SETUP").upper()
        if latest else "NO REVERSAL SETUP"
    )
    reason = (
        latest.get("reversal_reason") or "Waiting for completed reversal data."
        if latest else "Waiting for completed reversal data."
    )
    states = [
        ("POTENTIAL BULL REVERSAL", "potential-bull"),
        ("POTENTIAL BEAR REVERSAL", "potential-bear"),
        ("CONFIRMED BULL REVERSAL", "confirmed-bull"),
        ("CONFIRMED BEAR REVERSAL", "confirmed-bear")
    ]
    badges = "".join(
        f'<div class="reversal-badge {css_class}{" active" if state == label else ""}">'
        f"{escape_value(label)}</div>"
        for label, css_class in states
    )

    return f"""
    <section class="reversal-monitor">
      <div class="reversal-badges">{badges}</div>
      <p><strong>Reversal Monitor:</strong> {escape_value(state)}. {escape_value(reason)}</p>
    </section>
    """


def build_multi_timeframe_monitor(latest):
    if not latest:
        return '<section class="mtf-monitor"><p>Waiting for multi-timeframe data.</p></section>'

    timeframes = [
        ("1m", latest.get("mtf_1m_status"), latest.get("mtf_1m_reason")),
        ("3m", latest.get("mtf_3m_status"), latest.get("mtf_3m_reason")),
        ("5m", latest.get("mtf_5m_status"), latest.get("mtf_5m_reason"))
    ]
    timeframe_cards = "".join(
        f'<div class="mtf-card {(status or "neutral").lower()}">'
        f"<span>{escape_value(label)}</span>"
        f"<strong>{escape_value(status or 'Neutral')}</strong>"
        f"<p>{escape_value(reason)}</p>"
        "</div>"
        for label, status, reason in timeframes
    )
    overall_signal = latest.get("mtf_overall_signal") or "WAIT"
    alignment = latest.get("mtf_alignment") or "Mixed"
    overall_class = overall_signal.lower().replace(" ", "-")
    alignment_class = alignment.lower().replace(" ", "-")

    return f"""
    <section class="mtf-monitor">
      <div class="mtf-heading">
        <div>
          <span>Overall Signal</span>
          <strong class="{overall_class}">{escape_value(overall_signal)}</strong>
        </div>
        <div>
          <span>Alignment</span>
          <strong class="{alignment_class}">{escape_value(alignment)}</strong>
        </div>
      </div>
      <div class="mtf-grid">{timeframe_cards}</div>
    </section>
    """


def build_signal_explanation(latest, regime_data, live_status):
    if not latest:
        return '<section class="chart-brief wait"><p>Waiting for completed chart structure.</p></section>'

    latest = dict(latest)
    prediction = latest.get("prediction", "WAIT").upper()
    explanation_class = prediction.lower() if prediction in ("CALL", "PUT") else "wait"
    regime = regime_data.get("regime", "CHOPPY")
    regime_class = regime.lower().replace(" ", "-")
    stability = (latest.get("mode_stability") or "MEDIUM").upper()
    stability_class = stability.lower()
    stability_warning = (
        '<p class="top-stability-warning">Unstable signal. Avoid chasing.</p>'
        if stability == "LOW" else ""
    )
    live_available = bool(live_status and live_status.get("available"))
    displayed_price = (
        live_status.get("spy_price")
        if live_available else latest.get("spy_price")
    )
    latest, levels_corrected = correct_levels_from_live_price(
        latest,
        latest.get("level_reference_price", displayed_price)
    )
    corrected_levels_warning = (
        '<p class="levels-corrected-warning">Levels corrected from live price.</p>'
        if levels_corrected else ""
    )
    price_label = "Live SPY Price" if live_available else "Last Prediction Price"
    live_update_time = (
        live_status.get("updated_at")
        if live_available else "N/A"
    )
    live_data_age = (
        live_status.get("data_age_text")
        if live_available else "N/A"
    )
    live_source = (
        live_status.get("data_source")
        if live_available else "Prediction CSV fallback"
    )
    live_warning = (
        '<p class="live-stale-warning">Warning: live SPY price is stale.</p>'
        if live_available and live_status.get("stale")
        else (
            f'<p class="live-stale-warning">{escape_value(live_status.get("error"))}</p>'
            f'<p class="live-status-path">Path tried: {escape_value(live_status.get("path"))}</p>'
        )
        if not live_available else ""
    )
    structure_age_text, _ = format_seconds_age(
        latest.get("structure_update_epoch")
    )
    level_age_text, level_age = format_seconds_age(latest.get("level_update_epoch"))
    level_age_style = level_age_class(level_age)
    levels_stale_warning = (
        '<p class="levels-stale-warning">Levels may be stale.</p>'
        if level_age is not None and level_age > 60 else ""
    )
    level_states = get_level_activation_states(latest, displayed_price)
    level_debug = level_states["debug"]

    return f"""
    <section class="chart-brief {explanation_class}">
      <div class="top-market-state">
        <div class="top-regime {regime_class}">
          <span>Market Regime</span>
          <strong>{escape_value(regime)}</strong>
        </div>
        <div class="top-stability {stability_class}">
          <span>Stability</span>
          <strong>{escape_value(stability)}</strong>
          {stability_warning}
        </div>
      </div>
      <div class="brief-grid">
        <div class="level-summary">
          <span>{escape_value(price_label)}</span>
          <strong>{escape_value(displayed_price)}</strong>
          <p>Last update: {escape_value(live_update_time)}</p>
          <p>Data age: {escape_value(live_data_age)}</p>
          <p>Data source: {escape_value(live_source)}</p>
          {live_warning}
          <p>Levels updated: {escape_value(latest.get("level_update_time"))}</p>
          <p>Structure Age: {escape_value(structure_age_text)}</p>
          <p class="{level_age_style}">Level Age: {escape_value(level_age_text)}</p>
          {levels_stale_warning}
          {corrected_levels_warning}
        </div>
        <div>
          <span>Current Advantage</span>
          <strong>{escape_value(latest.get("current_advantage"))}</strong>
        </div>
        <div>
          <span>Confirmation Needed</span>
          <p>{escape_value(latest.get("confirmation_needed"))}</p>
        </div>
        <div>
          <span>Invalidation</span>
          <p>{escape_value(latest.get("invalidation_reason"))}</p>
        </div>
        <div class="support-level">
          <strong id="top-support-price" class="sr-price" data-sr-level="support">${escape_value(latest.get("nearest_support"))}</strong>
          <span class="sr-kind">Support</span>
          <details class="sr-description">
            <summary>Details</summary>
            <p>Why: {escape_value(latest.get("support_reason"))}</p>
            <p>Distance to Support: ${escape_value(latest.get("support_distance"))}</p>
          </details>
          {build_education_box("Support", "Definition")}
        </div>
        <div class="resistance-level">
          <strong id="top-resistance-price" class="sr-price" data-sr-level="resistance">${escape_value(latest.get("nearest_resistance"))}</strong>
          <span class="sr-kind">Resistance</span>
          <details class="sr-description">
            <summary>Details</summary>
            <p>Why: {escape_value(latest.get("resistance_reason"))}</p>
            <p>Distance to Resistance: ${escape_value(latest.get("resistance_distance"))}</p>
          </details>
          {build_education_box("Resistance", "Definition")}
        </div>
        <div class="direction-levels bullish-levels">
          <div class="direction-levels-heading">Bullish Levels {build_education_box("Bullish Levels", "Definition")}</div>
          <div class="level-status-badge bullish-status" data-level-status="bull">{escape_value(level_states["bull_status"])}</div>
          <div id="bull-trigger-card" class="direction-level bullish-trigger {level_states['bull_trigger'][0]}" data-level-key="bull_trigger">
            <strong>{escape_value(latest.get("bullish_trigger"))}</strong>
            <b>Trigger</b>
            <span id="bull-trigger-status" class="level-status-text">{level_states['bull_trigger'][1]}</span>
            <p>First sign buyers are gaining control.</p>
          </div>
          <div id="bull-confirmation-card" class="direction-level bullish-confirmation {level_states['bull_confirm'][0]}" data-level-key="bull_confirm">
            <strong>{escape_value(latest.get("bullish_confirmation"))}</strong>
            <b>Confirmation</b>
            <span id="bull-confirmation-status" class="level-status-text">{level_states['bull_confirm'][1]}</span>
            <p>Structure improving.</p>
          </div>
          <div id="bull-breakout-card" class="direction-level bullish-breakout {level_states['bull_breakout'][0]}" data-level-key="bull_breakout">
            <strong>{escape_value(latest.get("bullish_breakout"))}</strong>
            <b>Breakout</b>
            <span id="bull-breakout-status" class="level-status-text">{level_states['bull_breakout'][1]}</span>
            <p>Buyers control the nearby structure.</p>
          </div>
        </div>
        <div class="direction-levels bearish-levels">
          <div class="direction-levels-heading">Bearish Levels {build_education_box("Bearish Levels", "Definition")}</div>
          <div class="level-status-badge bearish-status" data-level-status="bear">{escape_value(level_states["bear_status"])}</div>
          <div id="bear-trigger-card" class="direction-level bearish-trigger {level_states['bear_trigger'][0]}" data-level-key="bear_trigger">
            <strong>{escape_value(latest.get("bearish_trigger"))}</strong>
            <b>Trigger</b>
            <span id="bear-trigger-status" class="level-status-text">{level_states['bear_trigger'][1]}</span>
            <p>First sign sellers are gaining control.</p>
          </div>
          <div id="bear-confirmation-card" class="direction-level bearish-confirmation {level_states['bear_confirm'][0]}" data-level-key="bear_confirm">
            <strong>{escape_value(latest.get("bearish_confirmation"))}</strong>
            <b>Confirmation</b>
            <span id="bear-confirmation-status" class="level-status-text">{level_states['bear_confirm'][1]}</span>
            <p>Structure weakening.</p>
          </div>
          <div id="bear-breakdown-card" class="direction-level bearish-breakdown {level_states['bear_breakdown'][0]}" data-level-key="bear_breakdown">
            <strong>{escape_value(latest.get("bearish_breakdown"))}</strong>
            <b>Breakdown</b>
            <span id="bear-breakdown-status" class="level-status-text">{level_states['bear_breakdown'][1]}</span>
            <p>Sellers control the nearby structure.</p>
          </div>
        </div>
        <div class="what-next">
          <span>What Happens Next?</span>
          {build_education_box("What Happens Next")}
          <p class="next-bullish"><b>Above {escape_value(latest.get("bullish_confirmation"))}:</b> Bullish momentum likely increases.</p>
          <p class="next-bearish"><b>Below {escape_value(latest.get("bearish_confirmation"))}:</b> Bearish continuation becomes more likely.</p>
          <p class="next-chop"><b>Inside {escape_value(latest.get("bearish_confirmation"))}-{escape_value(latest.get("bullish_trigger"))}:</b> Expect chop and indecision.</p>
        </div>
        <div class="correction-monitor">
          <span>Short-Term Move</span>
          <strong id="correction-mode">{escape_value(latest.get("correction_mode", "NEUTRAL"))}</strong>
          <p id="correction-reason">{escape_value(latest.get("correction_reason", "Waiting for short-term price bars."))}</p>
          <p>Correction signal: <b id="correction-signal">{escape_value(latest.get("correction_signal", "WAIT"))}</b></p>
          <p>Activated: <b id="correction-activation-time">{escape_value(latest.get("correction_activation_time", "N/A"))}</b></p>
        </div>
        <details class="level-debug">
          <summary>Live Level Debug</summary>
          <div class="level-debug-grid">
            <span>Live price used</span><strong id="debug-live-price">{escape_value(level_debug.get("live_price"))}</strong>
            <span>bull_trigger</span><strong id="debug-bull-trigger">{escape_value(level_debug.get("bull_trigger"))}</strong>
            <span>bull_confirmation</span><strong id="debug-bull-confirmation">{escape_value(level_debug.get("bull_confirmation"))}</strong>
            <span>bull_breakout</span><strong id="debug-bull-breakout">{escape_value(level_debug.get("bull_breakout"))}</strong>
            <span>bear_trigger</span><strong id="debug-bear-trigger">{escape_value(level_debug.get("bear_trigger"))}</strong>
            <span>bear_confirmation</span><strong id="debug-bear-confirmation">{escape_value(level_debug.get("bear_confirmation"))}</strong>
            <span>bear_breakdown</span><strong id="debug-bear-breakdown">{escape_value(level_debug.get("bear_breakdown"))}</strong>
            <span>level_set_id</span><strong id="debug-level-set-id">{escape_value(level_debug.get("level_set_id"))}</strong>
            <span>last_level_set_id</span><strong id="debug-last-level-set-id">{escape_value(level_debug.get("last_level_set_id"))}</strong>
            <span>data_age</span><strong id="debug-data-age">{escape_value(live_status.get("data_age_text") if live_status else "N/A")}</strong>
            <span>last_hit_bull_level</span><strong>{escape_value(level_debug.get("last_hit_bull_level"))}</strong>
            <span>last_hit_bear_level</span><strong>{escape_value(level_debug.get("last_hit_bear_level"))}</strong>
            <span>level_hit_timestamp</span><strong id="debug-level-hit-timestamp">{escape_value(level_debug.get("level_hit_timestamp"))}</strong>
            <span>Saved hit times file</span><strong id="debug-level-hits-file">{escape_value(level_debug.get("saved_hit_times_file_path"))}</strong>
            <span>Last saved hit time</span><strong id="debug-last-saved-hit-time">{escape_value(level_debug.get("last_saved_hit_time"))}</strong>
            <span>Saved first-hit times</span><strong id="debug-first-hit-times">{escape_value(level_debug.get("first_hit_times"))}</strong>
            <span>Calculated bull status</span><strong id="debug-bull-status">{escape_value(level_states.get("bull_status"))}</strong>
            <span>Calculated bear status</span><strong id="debug-bear-status">{escape_value(level_states.get("bear_status"))}</strong>
            <span>bull_trigger_status</span><strong id="debug-bull-trigger-status">{escape_value(level_states["bull_trigger"][1])}</strong>
            <span>bull_confirmation_status</span><strong id="debug-bull-confirmation-status">{escape_value(level_states["bull_confirm"][1])}</strong>
            <span>bull_breakout_status</span><strong id="debug-bull-breakout-status">{escape_value(level_states["bull_breakout"][1])}</strong>
            <span>bear_trigger_status</span><strong id="debug-bear-trigger-status">{escape_value(level_states["bear_trigger"][1])}</strong>
            <span>bear_confirmation_status</span><strong id="debug-bear-confirmation-status">{escape_value(level_states["bear_confirm"][1])}</strong>
            <span>bear_breakdown_status</span><strong id="debug-bear-breakdown-status">{escape_value(level_states["bear_breakdown"][1])}</strong>
            <span>bull_trigger_hit</span><strong id="debug-bull-trigger-hit">{escape_value(level_states["bull_trigger"][1])}</strong>
            <span>bull_confirmation_hit</span><strong id="debug-bull-confirmation-hit">{escape_value(level_states["bull_confirm"][1])}</strong>
            <span>bull_breakout_hit</span><strong id="debug-bull-breakout-hit">{escape_value(level_states["bull_breakout"][1])}</strong>
            <span>bear_trigger_hit</span><strong id="debug-bear-trigger-hit">{escape_value(level_states["bear_trigger"][1])}</strong>
            <span>bear_confirmation_hit</span><strong id="debug-bear-confirmation-hit">{escape_value(level_states["bear_confirm"][1])}</strong>
            <span>bear_breakdown_hit</span><strong id="debug-bear-breakdown-hit">{escape_value(level_states["bear_breakdown"][1])}</strong>
            <span>correction_mode</span><strong id="debug-correction-mode">{escape_value(latest.get("correction_mode", "NEUTRAL"))}</strong>
            <span>correction_signal</span><strong id="debug-correction-signal">{escape_value(latest.get("correction_signal", "WAIT"))}</strong>
            <span>correction_activation_time</span><strong id="debug-correction-activation-time">{escape_value(latest.get("correction_activation_time", "N/A"))}</strong>
            <span>current_banner_reason</span><strong id="debug-current-banner-reason">N/A</strong>
            <span>one_min_trend</span><strong id="debug-one-min-trend">{escape_value(latest.get("mtf_1m_status", "Neutral"))}</strong>
            <span>vwap_position</span><strong id="debug-vwap-position">{escape_value(latest.get("vwap_position", "Mixed"))}</strong>
            <span>active_bull_level</span><strong id="debug-active-bull-level">{escape_value(level_states.get("bull_status"))}</strong>
            <span>active_bear_level</span><strong id="debug-active-bear-level">{escape_value(level_states.get("bear_status"))}</strong>
            <span>calculated_status</span><strong id="debug-calculated-status">{escape_value(level_debug.get("calculated_status"))}</strong>
          </div>
        </details>
      </div>
    </section>
    """


def build_support_resistance_details(latest):
    if not latest:
        return '<p class="empty">Waiting for support and resistance data.</p>'

    return f"""
    <section class="support-resistance-details">
      <div class="support-detail">
        <strong id="detail-support-price" class="sr-price" data-sr-level="support">${escape_value(latest.get("nearest_support"))}</strong>
        <span class="sr-kind">Nearest Support</span>
        <details class="sr-description">
          <summary>Details</summary>
          <p>{escape_value(latest.get("support_reason"))}</p>
          <p><b>Distance:</b> ${escape_value(latest.get("support_distance"))}</p>
          <p>Support is where buyers recently stepped in. If SPY holds above it, sellers are not fully in control.</p>
          <p>A break below support means sellers are gaining control. Watch for continuation or a fakeout.</p>
        </details>
      </div>
      <div class="resistance-detail">
        <strong id="detail-resistance-price" class="sr-price" data-sr-level="resistance">${escape_value(latest.get("nearest_resistance"))}</strong>
        <span class="sr-kind">Nearest Resistance</span>
        <details class="sr-description">
          <summary>Details</summary>
          <p>{escape_value(latest.get("resistance_reason"))}</p>
          <p><b>Distance:</b> ${escape_value(latest.get("resistance_distance"))}</p>
          <p>Resistance is where sellers recently stepped in. If SPY rejects there, upside momentum is weak.</p>
          <p>A break above resistance means buyers are gaining control. Look for a hold above the level.</p>
        </details>
      </div>
    </section>
    """


def build_chart_reading_details(latest):
    if not latest:
        return '<p class="empty">Waiting for completed chart structure.</p>'

    return f"""
    <section class="chart-reading-details">
      <div>
        <span>Market Structure</span>
        <strong>{escape_value(latest.get("market_structure"))}</strong>
      </div>
      <div>
        <span>Last 3 Completed 5-Minute Candles</span>
        <p>{escape_value(latest.get("last_3_candle_reading"))}</p>
      </div>
      <div>
        <span>Confirmation</span>
        <p>{escape_value(latest.get("confirmation_needed"))}</p>
      </div>
      <div>
        <span>What Changes The Bias</span>
        <p>{escape_value(latest.get("invalidation_reason"))}</p>
      </div>
    </section>
    """


def build_live_chart(rows):
    candles_by_window = {}

    for row in rows:
        price = parse_float(row.get("spy_price"))
        timestamp_text = row.get("time")

        if price is None or not timestamp_text:
            continue

        try:
            timestamp = datetime.strptime(
                timestamp_text,
                "%Y-%m-%d %H:%M:%S"
            )
        except ValueError:
            continue

        window = timestamp.replace(
            minute=(timestamp.minute // 5) * 5,
            second=0,
            microsecond=0
        )

        if window not in candles_by_window:
            candles_by_window[window] = {
                "time": window,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "latest_row": row
            }
        else:
            candle = candles_by_window[window]
            candle["high"] = max(candle["high"], price)
            candle["low"] = min(candle["low"], price)
            candle["close"] = price
            candle["latest_row"] = row

    candles = [
        candles_by_window[window]
        for window in sorted(candles_by_window)
    ][-30:]

    if not candles:
        return """
        <section class="chart-section">
          <h2>SPY 5-Minute Chart</h2>
          <p class="empty">Waiting for SPY prediction prices.</p>
        </section>
        """

    latest = candles[-1]["latest_row"]
    plan_lines = [
        ("Entry", parse_float(latest.get("entry")), "#2474c6"),
        ("Stop", parse_float(latest.get("stop_loss")), "#c83d3d"),
        ("TP1", parse_float(latest.get("target_1")), "#16844f"),
        ("TP2", parse_float(latest.get("target_2")), "#32a66a")
    ]
    plan_lines = [line for line in plan_lines if line[1] is not None]
    all_values = []

    for candle in candles:
        all_values.extend([candle["high"], candle["low"]])

    all_values.extend(value for _, value, _ in plan_lines)
    minimum = min(all_values)
    maximum = max(all_values)
    value_range = maximum - minimum

    if value_range == 0:
        value_range = max(maximum * 0.001, 0.10)

    padding = value_range * 0.12
    minimum -= padding
    maximum += padding
    width = 1200
    height = 420
    left = 72
    right = 110
    top = 24
    bottom = 44
    plot_width = width - left - right
    plot_height = height - top - bottom

    def x_position(index):
        if len(candles) == 1:
            return left + (plot_width / 2)
        return left + ((index / (len(candles) - 1)) * plot_width)

    def y_position(value):
        return top + (((maximum - value) / (maximum - minimum)) * plot_height)

    grid_lines = []

    for step in range(5):
        value = maximum - ((maximum - minimum) * (step / 4))
        y = y_position(value)
        grid_lines.append(
            f'<line x1="{left}" y1="{y:.1f}" x2="{width - right}" '
            f'y2="{y:.1f}" class="chart-grid"/>'
            f'<text x="{left - 8}" y="{y + 4:.1f}" '
            f'class="chart-axis-label" text-anchor="end">${value:.2f}</text>'
        )

    candle_svg = []
    candle_width = max(5, min(18, (plot_width / max(len(candles), 1)) * 0.55))

    for index, candle in enumerate(candles):
        x = x_position(index)
        open_y = y_position(candle["open"])
        high_y = y_position(candle["high"])
        low_y = y_position(candle["low"])
        close_y = y_position(candle["close"])
        candle_class = (
            "up" if candle["close"] >= candle["open"] else "down"
        )
        body_top = min(open_y, close_y)
        body_height = max(abs(close_y - open_y), 2)
        candle_svg.append(
            f'<line x1="{x:.1f}" y1="{high_y:.1f}" x2="{x:.1f}" '
            f'y2="{low_y:.1f}" class="candle-wick {candle_class}"/>'
            f'<rect x="{x - (candle_width / 2):.1f}" y="{body_top:.1f}" '
            f'width="{candle_width:.1f}" height="{body_height:.1f}" '
            f'class="candle-body {candle_class}"/>'
        )

    plan_svg = []
    legend = [
        '<span class="candle-up-legend">Up Candle</span>',
        '<span class="candle-down-legend">Down Candle</span>'
    ]

    for label, value, color in plan_lines:
        y = y_position(value)
        plan_svg.append(
            f'<line x1="{left}" y1="{y:.1f}" x2="{width - right}" '
            f'y2="{y:.1f}" stroke="{color}" stroke-width="2" '
            f'stroke-dasharray="8 6"/>'
            f'<text x="{width - right + 8}" y="{y + 4:.1f}" '
            f'fill="{color}" class="chart-plan-label">'
            f'{label} ${value:.2f}</text>'
        )
        legend.append(
            f'<span style="color: {color}; border-color: {color}">{label}</span>'
        )

    first_time = candles[0]["time"].strftime("%Y-%m-%d %H:%M")
    last_time = candles[-1]["time"].strftime("%Y-%m-%d %H:%M")

    return f"""
    <section class="chart-section">
      <div class="chart-heading">
        <h2>SPY 5-Minute Chart</h2>
        <div class="chart-legend">{''.join(legend)}</div>
      </div>
      <div class="chart-wrap">
        <svg viewBox="0 0 {width} {height}" role="img"
             aria-label="SPY 5-minute candles and current trade plan">
          {''.join(grid_lines)}
          {''.join(plan_svg)}
          {''.join(candle_svg)}
          <text x="{left}" y="{height - 12}" class="chart-axis-label">{first_time}</text>
          <text x="{width - right}" y="{height - 12}" class="chart-axis-label"
                text-anchor="end">{last_time}</text>
        </svg>
      </div>
    </section>
    """


def build_engine_health_section(rows):
    def latest_rows_by_ticker(candidate_rows):
        latest_by_ticker = {}
        latest_keys = {}

        for row_index, row in enumerate(candidate_rows or []):
            if not isinstance(row, dict):
                continue

            ticker = row.get("ticker") or row.get("symbol")
            if not ticker:
                continue

            normalized_row = dict(row)
            normalized_row["ticker"] = ticker
            status = str(row.get("status") or "Neutral").strip().title()
            normalized_row["status"] = (
                status if status in {"Bullish", "Bearish", "Neutral"} else "Neutral"
            )
            timestamp = str(
                row.get("time")
                or row.get("timestamp")
                or row.get("last_update")
                or row.get("updated_at")
                or ""
            )
            row_key = (timestamp, row_index)

            if ticker not in latest_keys or row_key >= latest_keys[ticker]:
                latest_keys[ticker] = row_key
                latest_by_ticker[ticker] = normalized_row

        return list(latest_by_ticker.values())

    display_rows = latest_rows_by_ticker(rows)
    engine_source = dashboard_engine_source
    server_mode = (
        os.name != "nt"
        or os.environ.get("RENDER", "").strip().lower() in {"1", "true", "yes"}
    )

    if server_mode:
        live_status = read_live_status()
        pushed_rows = live_status.get("latest_engine_health_rows")

        if not isinstance(pushed_rows, list) or not pushed_rows:
            pushed_rows = live_status.get("latest_engine_health")

        if isinstance(pushed_rows, dict):
            pushed_rows = [pushed_rows]
        elif not isinstance(pushed_rows, list):
            pushed_rows = []

        pushed_display_rows = latest_rows_by_ticker(pushed_rows)

        if len(pushed_display_rows) > len(display_rows):
            display_rows = pushed_display_rows
            engine_source = "pushed_live_status"

    bullish_count = sum(1 for row in display_rows if row.get("status") == "Bullish")
    bearish_count = sum(1 for row in display_rows if row.get("status") == "Bearish")
    neutral_count = sum(1 for row in display_rows if row.get("status") == "Neutral")
    total_count = len(display_rows)
    engine_score = (
        ((bullish_count - bearish_count) / total_count) * 100
        if total_count else 0
    )

    if engine_score >= 20:
        engine_label = "Bullish"
        score_class = "bullish"
    elif engine_score <= -20:
        engine_label = "Bearish"
        score_class = "bearish"
    else:
        engine_label = "Mixed"
        score_class = "neutral"

    driver_rows = []

    def absolute_change(row):
        try:
            return abs(float(row.get("day_change_percent", 0)))
        except (TypeError, ValueError):
            return 0

    for status in ("Bullish", "Bearish", "Neutral"):
        status_rows = [row for row in display_rows if row.get("status") == status]

        if not status_rows:
            continue

        status_class = status.lower()
        driver_rows.append(
            f'<tr class="engine-group {status_class}">'
            f'<th colspan="4">{status} ({len(status_rows)})</th></tr>'
        )

        for row in sorted(status_rows, key=absolute_change, reverse=True):
            driver_rows.append(
                "<tr>"
                f"<td><strong>{escape_value(row.get('ticker'))}</strong></td>"
                f"<td>${escape_value(row.get('price'))}</td>"
                f"<td>{escape_value(row.get('day_change_percent'))}%</td>"
                f'<td><span class="engine-status {status_class}">'
                f"{escape_value(status)}</span></td>"
                "</tr>"
            )

    if driver_rows:
        drivers = (
            '<div class="table-wrap"><table>'
            "<thead><tr><th>Ticker</th><th>Price</th><th>Day Change</th>"
            f"<th>Status</th></tr></thead><tbody>{''.join(driver_rows)}</tbody>"
            "</table></div>"
        )
    else:
        drivers = '<p class="empty">Waiting for engine health data.</p>'

    return f"""
    <section class="engine-section">
      <h2>SPY Engine Health</h2>
      <div class="engine-grid">
        <div class="engine-score {score_class}">
          <span>Engine Score</span>
          <strong>{engine_score:+.1f}%</strong>
          <em>{engine_label}</em>
        </div>
        <div class="engine-counts">
          <div class="bullish"><strong>{bullish_count}</strong><span>Bullish</span></div>
          <div class="bearish"><strong>{bearish_count}</strong><span>Bearish</span></div>
          <div class="neutral"><strong>{neutral_count}</strong><span>Neutral</span></div>
        </div>
      </div>
      <p class="note">Source: {escape_value(engine_source)} | Unique tickers: {total_count}</p>
      <h3>Full Engine Basket</h3>
      {drivers}
    </section>
    """


def build_market_breadth_section(row):
    if not row:
        return '<p class="empty">Waiting for market breadth data.</p>'

    classification = row.get("classification", "Neutral")

    if classification == "Strong Bullish":
        breadth_class = "bullish"
    elif classification == "Strong Bearish":
        breadth_class = "bearish"
    else:
        breadth_class = "neutral"

    return f"""
    <section class="breadth-section">
      <div class="breadth-status {breadth_class}">
        <span>Market Breadth</span>
        <strong>{escape_value(classification)}</strong>
      </div>
      <div class="breadth-grid">
        <div class="bullish"><span>Advancing Stocks</span><strong>{escape_value(row.get("advancing"))}</strong></div>
        <div class="bearish"><span>Declining Stocks</span><strong>{escape_value(row.get("declining"))}</strong></div>
        <div><span>Advance %</span><strong>{escape_value(row.get("advance_percent"))}%</strong></div>
        <div><span>SPY</span><strong>{escape_value(row.get("spy_change_percent"))}%</strong></div>
        <div><span>QQQ</span><strong>{escape_value(row.get("qqq_change_percent"))}%</strong></div>
        <div><span>IWM</span><strong>{escape_value(row.get("iwm_change_percent"))}%</strong></div>
      </div>
      <p class="note">Advancing and declining counts use the tracked SPY engine stock basket.</p>
    </section>
    """


def build_prediction_card(latest):
    if latest is None:
        return """
        <section class="decision-panel wait">
          <div class="decision-grid">
            <div><span>Confidence %</span><strong>N/A</strong></div>
            <div><span>Entry</span><strong>N/A</strong></div>
            <div><span>Stop Loss</span><strong>N/A</strong></div>
            <div><span>TP1</span><strong>N/A</strong></div>
            <div><span>TP2</span><strong>N/A</strong></div>
          </div>
        </section>
        """

    prediction = latest.get("prediction", "WAIT").upper()
    card_class = prediction.lower() if prediction in ("CALL", "PUT") else "wait"

    return f"""
    <section class="decision-panel {card_class}">
      <div class="decision-grid">
        <div><span>Confidence %</span><strong>{escape_value(latest.get("confidence"))}%</strong></div>
        <div><span>Entry</span><strong>{escape_value(latest.get("entry"))}</strong></div>
        <div><span>Stop Loss</span><strong>{escape_value(latest.get("stop_loss"))}</strong></div>
        <div><span>TP1</span><strong>{escape_value(latest.get("target_1"))}</strong></div>
        <div><span>TP2</span><strong>{escape_value(latest.get("target_2"))}</strong></div>
      </div>
    </section>
    """


def build_position_plan(latest):
    if not latest:
        return '<section class="position-plan"><p class="empty">Waiting for a trade plan.</p></section>'

    prediction = (latest.get("prediction") or "WAIT").upper()
    entry = parse_float(latest.get("entry")) or parse_float(latest.get("spy_price"))
    target_1 = parse_float(latest.get("target_1"))
    target_2 = parse_float(latest.get("target_2"))
    nearest_support = parse_float(latest.get("nearest_support"))
    nearest_resistance = parse_float(latest.get("nearest_resistance"))
    vwap = parse_float(latest.get("vwap"))

    if prediction == "WAIT":
        return """
        <section class="position-plan">
          <h2>Position Plan</h2>
          <div class="stop-education wait-stop">
            <strong>No stop yet. No trade until confirmation creates a clean invalidation level.</strong>
            <p>Your stop is not where you hope price does not go. Your stop is where the setup is proven wrong.</p>
          </div>
        </section>
        """

    if entry is None:
        return '<section class="position-plan"><p class="empty">Waiting for a confirmed entry and structure stop.</p></section>'

    if prediction == "CALL":
        stop_candidates = [
            value for value in (
                nearest_support,
                vwap,
                parse_float(latest.get("bearish_trigger"))
            )
            if value is not None and value < entry
        ]
        stop_loss = max(stop_candidates) - 0.02 if stop_candidates else None
        stop_label = "Stop below buyer failure level."
        stop_explanation = "If price moves below this level, the bullish idea is invalid."
        target_1 = target_1 or parse_float(latest.get("bullish_confirmation"))
        target_2 = target_2 or parse_float(latest.get("bullish_breakout"))
    else:
        stop_candidates = [
            value for value in (
                nearest_resistance,
                vwap,
                parse_float(latest.get("bullish_trigger"))
            )
            if value is not None and value > entry
        ]
        stop_loss = min(stop_candidates) + 0.02 if stop_candidates else None
        stop_label = "Stop above seller failure level."
        stop_explanation = "If price moves above this level, the bearish idea is invalid."
        target_1 = target_1 or parse_float(latest.get("bearish_confirmation"))
        target_2 = target_2 or parse_float(latest.get("bearish_breakdown"))

    if None in (stop_loss, target_1, target_2):
        return f"""
        <section class="position-plan">
          <h2>Position Plan</h2>
          <div class="stop-education review">
            <strong>{escape_value(stop_label)}</strong>
            <p>{escape_value(stop_explanation)}</p>
            <p>Waiting for nearby structure to create complete stop and target levels.</p>
          </div>
        </section>
        """

    risk_per_contract = abs(entry - stop_loss)
    reward_tp1_per_contract = abs(target_1 - entry)
    reward_tp2_per_contract = abs(target_2 - entry)
    risk_reward = reward_tp2_per_contract / risk_per_contract if risk_per_contract else 0
    structure_references = [
        value for value in (nearest_support, nearest_resistance, vwap)
        if value is not None
    ]
    nearest_structure_distance = (
        min(abs(entry - value) for value in structure_references)
        if structure_references else None
    )
    stop_is_structure_based = (
        prediction == "CALL"
        and any(
            reference is not None and stop_loss <= reference
            for reference in (nearest_support, vwap)
        )
    ) or (
        prediction == "PUT"
        and any(
            reference is not None and stop_loss >= reference
            for reference in (nearest_resistance, vwap)
        )
    )
    risk_is_too_wide = (
        nearest_structure_distance is not None
        and risk_per_contract > max(0.50, nearest_structure_distance * 2.5)
    )

    if risk_is_too_wide:
        stop_suggestion = "Risk too wide. Reduce size or wait."
        stop_class = "wide"
    elif stop_is_structure_based:
        stop_suggestion = "Stop level is structure-based."
        stop_class = "clean"
    else:
        stop_suggestion = (
            "Stop needs a clearer structure reference. Do not use a random $1 stop."
        )
        stop_class = "review"

    rows = "".join(
        "<tr>"
        f"<td>{size}</td>"
        f"<td>${risk_per_contract * size:.2f}</td>"
        f"<td>${reward_tp1_per_contract * size:.2f}</td>"
        f"<td>${reward_tp2_per_contract * size:.2f}</td>"
        "</tr>"
        for size in range(1, 6)
    )

    risk_rule = (
        "For CALL, the stop should usually be below support, VWAP, or a recent swing low."
        if prediction == "CALL"
        else "For PUT, the stop should usually be above resistance, VWAP, or a recent swing high."
        if prediction == "PUT"
        else "Wait for a directional plan before sizing a position."
    )

    return f"""
    <section class="position-plan" data-risk-per-contract="{risk_per_contract:.8f}">
      <div class="position-plan-heading">
        <div>
          <h2>Position Plan</h2>
          <p>Estimated movement based on SPY price plan, not exact option P/L.</p>
        </div>
        <label>
          Max risk
          <select id="max-risk-selector" onchange="updatePositionPlan()">
            <option value="25">$25</option>
            <option value="50">$50</option>
            <option value="100">$100</option>
          </select>
        </label>
      </div>
      <div class="position-summary">
        <div><span>Stop Level</span><strong>${stop_loss:.2f}</strong></div>
        <div><span>Target 1</span><strong>${target_1:.2f}</strong></div>
        <div><span>Target 2</span><strong>${target_2:.2f}</strong></div>
        <div><span>Risk in SPY Points</span><strong>{risk_per_contract:.2f}</strong></div>
        <div><span>Risk per Contract Estimate</span><strong>${risk_per_contract:.2f}</strong></div>
        <div><span>Reward Estimate</span><strong>${reward_tp2_per_contract:.2f}</strong></div>
        <div><span>Risk / Reward</span><strong>1:{risk_reward:.2f}</strong></div>
        <div><span>Estimated Max Size</span><strong id="estimated-max-contracts">N/A</strong></div>
      </div>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Size</th><th>Risk at Stop</th><th>Gain at TP1</th><th>Gain at TP2</th></tr></thead>
          <tbody>{rows}</tbody>
        </table>
      </div>
      <p class="risk-rule"><strong>Risk Rule:</strong> {escape_value(risk_rule)}</p>
      <div class="stop-education {stop_class}">
        <strong>{escape_value(stop_label)}</strong>
        <p><b>Why this stop:</b> {escape_value(stop_explanation)}</p>
        <p>Your stop is not where you hope price does not go. Your stop is where the setup is proven wrong.</p>
      </div>
      <p class="stop-suggestion {stop_class}">{escape_value(stop_suggestion)}</p>
    </section>
    """


def build_ai_benchmark_equity_curve(points):
    values = [
        parse_float(point.get("equity"))
        for point in (points or [])[-120:]
        if parse_float(point.get("equity")) is not None
    ]
    if len(values) < 2:
        return '<div class="benchmark-equity-empty">Equity curve begins after the first benchmark update.</div>'

    width, height, padding = 720, 180, 18
    low, high = min(values), max(values)
    spread = max(1, high - low)
    plot_width = width - padding * 2
    plot_height = height - padding * 2
    coordinates = []
    for index, value in enumerate(values):
        x = padding + (index / max(1, len(values) - 1) * plot_width)
        y = padding + ((high - value) / spread * plot_height)
        coordinates.append(f"{x:.1f},{y:.1f}")
    return f"""
    <svg class="benchmark-equity-curve" viewBox="0 0 {width} {height}" role="img" aria-label="AI paper benchmark equity curve">
      <line x1="{padding}" y1="{height - padding}" x2="{width - padding}" y2="{height - padding}" />
      <polyline points="{' '.join(coordinates)}" />
      <text x="{padding}" y="14">${high:.2f}</text>
      <text x="{padding}" y="{height - 3}">${low:.2f}</text>
    </svg>
    """


def build_ai_paper_benchmark(benchmark):
    if not benchmark:
        return '<section class="ai-paper-benchmark"><p class="empty">AI paper benchmark is waiting for dashboard data.</p></section>'

    position = benchmark.get("open_position")
    last_trade = benchmark.get("last_trade")
    position_text = (
        f'{position.get("direction")} from ${parse_float(position.get("entry_spy_price")):.4f} | '
        f'Stop ${parse_float(position.get("stop")):.4f} | Target ${parse_float(position.get("target")):.4f} | '
        f'Unrealized ${parse_float(position.get("unrealized_pnl")) or 0:.2f} | '
        f'Duration {parse_float(position.get("duration_minutes")) or 0:.2f} min'
        if position else "None"
    )
    last_trade_text = (
        f'{last_trade.get("direction")} {last_trade.get("result")} | '
        f'${parse_float(last_trade.get("pnl")) or 0:.2f} | {last_trade.get("reason")}'
        if last_trade else "No closed paper trades yet."
    )
    profit_factor = parse_float(benchmark.get("profit_factor")) or 0
    no_trade_reason = benchmark.get("reason_not_trading") or "Waiting for the next qualifying setup."
    paper_mode = benchmark.get("paper_mode") or "LIVE SESSION"
    paper_mode_text = (
        "RESEARCH REPLAY - Research replay / paper-only evaluation"
        if paper_mode == "RESEARCH REPLAY"
        else "LIVE SESSION"
    )
    status_class = (
        "milestone" if "Milestone" in str(benchmark.get("status"))
        else "failed" if benchmark.get("status") == "Failed"
        else "active"
    )
    trades = benchmark.get("closed_trades") or []
    trade_rows = "".join(
        "<tr>"
        f"<td>{escape_value(trade.get('time'))}</td>"
        f"<td>{escape_value(trade.get('signal'))}</td>"
        f"<td>{escape_value(trade.get('direction'))}</td>"
        f"<td>${(parse_float(trade.get('entry_spy_price')) or 0):.4f}</td>"
        f"<td>${(parse_float(trade.get('exit_spy_price')) or 0):.4f}</td>"
        f"<td>${(parse_float(trade.get('simulated_contract_entry')) or 0):.2f}</td>"
        f"<td>${(parse_float(trade.get('simulated_contract_exit')) or 0):.2f}</td>"
        f"<td>{(parse_float(trade.get('duration_minutes')) or 0):.2f} min</td>"
        f"<td class=\"{'benchmark-win' if (parse_float(trade.get('pnl')) or 0) > 0 else 'benchmark-loss' if (parse_float(trade.get('pnl')) or 0) < 0 else ''}\">${(parse_float(trade.get('pnl')) or 0):.2f}</td>"
        f"<td>{escape_value(trade.get('entry_reason'))}</td>"
        f"<td>{escape_value(trade.get('reason'))}</td>"
        f"<td>{escape_value(trade.get('result'))}</td>"
        "</tr>"
        for trade in reversed(trades[-25:])
    )
    if not trade_rows:
        trade_rows = '<tr><td colspan="12">No closed benchmark trades yet.</td></tr>'

    return f"""
    <section id="paper-benchmark-overview" class="ai-paper-benchmark">
      <div class="benchmark-heading">
        <div>
          <span>Educational comparison only</span>
          <h2>AI PAPER BENCHMARK</h2>
          <p>One synthetic paper contract per confirmed setup. No broker connection and no real orders.</p>
        </div>
        <div class="benchmark-status {status_class}">
          <span>Status</span>
          <strong>{escape_value(benchmark.get("status"))}</strong>
          <small>Cycle {escape_value(benchmark.get("cycle"))}</small>
        </div>
      </div>
      <div class="benchmark-focus-grid">
        <div><span>Paper Mode</span><strong>{escape_value(paper_mode_text)}</strong></div>
        <div><span>Bias</span><strong>{escape_value(benchmark.get("benchmark_bias"))}</strong></div>
        <div><span>Confidence</span><strong>{(parse_float(benchmark.get("benchmark_confidence")) or 0):.0f}%</strong></div>
        <div class="wide"><span>Why Not Trading</span><strong>{escape_value(benchmark.get("paper_last_block_reason") or no_trade_reason)}</strong></div>
        <div><span>Stop Source</span><strong>{escape_value(benchmark.get("paper_stop_source") or "none")}</strong></div>
        <div><span>Paper Stop</span><strong>${(parse_float(benchmark.get("paper_stop")) or 0):.4f}</strong></div>
        <div><span>Paper Target</span><strong>${(parse_float(benchmark.get("paper_target")) or 0):.4f}</strong></div>
        <div><span>Research R/R</span><strong>{(parse_float(benchmark.get("paper_risk_reward")) or 0):.2f}</strong></div>
      </div>
      <details class="benchmark-detail-log">
        <summary>Benchmark details, safeguards, and paper trade log</summary>
        <div class="benchmark-detail-body">
      <div class="benchmark-summary-grid">
        <div><span>Starting Balance</span><strong>${(parse_float(benchmark.get("starting_balance")) or 0):,.2f}</strong></div>
        <div><span>Current Balance</span><strong>${(parse_float(benchmark.get("current_balance")) or 0):,.2f}</strong></div>
        <div><span>Mark-to-Market Equity</span><strong>${(parse_float(benchmark.get("mark_to_market_equity")) or 0):,.2f}</strong></div>
        <div><span>Benchmark Bias</span><strong>{escape_value(benchmark.get("benchmark_bias"))}</strong></div>
        <div><span>Benchmark Confidence</span><strong>{(parse_float(benchmark.get("benchmark_confidence")) or 0):.0f}%</strong></div>
        <div><span>Benchmark Entry Reason</span><strong>{escape_value(benchmark.get("benchmark_entry_reason"))}</strong></div>
        <div><span>Paper Mode</span><strong>{escape_value(paper_mode_text)}</strong></div>
        <div><span>Block Reason</span><strong>{escape_value(benchmark.get("paper_last_block_reason") or "None")}</strong></div>
        <div><span>Entry Rule Used</span><strong>{escape_value(benchmark.get("paper_entry_rule_used") or "None")}</strong></div>
        <div><span>Exit Rule Used</span><strong>{escape_value(benchmark.get("paper_exit_rule_used"))}</strong></div>
        <div><span>Last Evaluation Time</span><strong>{escape_value(benchmark.get("paper_last_evaluation_time"))}</strong></div>
        <div><span>Stop Source</span><strong>{escape_value(benchmark.get("paper_stop_source") or "none")}</strong></div>
        <div><span>Paper Stop</span><strong>${(parse_float(benchmark.get("paper_stop")) or 0):.4f}</strong></div>
        <div><span>Paper Target</span><strong>${(parse_float(benchmark.get("paper_target")) or 0):.4f}</strong></div>
        <div><span>Risk Per Share</span><strong>${(parse_float(benchmark.get("paper_risk_per_share")) or 0):.4f}</strong></div>
        <div><span>Reward Per Share</span><strong>${(parse_float(benchmark.get("paper_reward_per_share")) or 0):.4f}</strong></div>
        <div><span>Research R/R</span><strong>{(parse_float(benchmark.get("paper_risk_reward")) or 0):.2f}</strong></div>
        <div><span>Trades Today</span><strong>{escape_value(benchmark.get("trades_today"))} / 10</strong></div>
        <div><span>Daily Goal</span><strong>{escape_value(benchmark.get("daily_goal") or "3-10")}</strong></div>
        <div><span>Daily Benchmark Status</span><strong>{escape_value(benchmark.get("daily_status"))}</strong></div>
        <div><span>Continue After +5%</span><strong>{"ENABLED" if benchmark.get("continue_benchmark") else "DISABLED"}</strong></div>
        <div><span>Total Trades</span><strong>{escape_value(benchmark.get("total_trades"))}</strong></div>
        <div><span>Closed Trades</span><strong>{escape_value(benchmark.get("closed_trade_count"))}</strong></div>
        <div><span>Win Rate</span><strong>{(parse_float(benchmark.get("win_rate")) or 0):.1f}%</strong></div>
        <div><span>Loss Rate</span><strong>{(parse_float(benchmark.get("loss_rate")) or 0):.1f}%</strong></div>
        <div><span>Profit Factor</span><strong>{profit_factor:.2f}</strong></div>
        <div><span>Max Drawdown</span><strong>${(parse_float(benchmark.get("max_drawdown")) or 0):.2f}</strong></div>
        <div><span>Consecutive Wins</span><strong>{escape_value(benchmark.get("consecutive_wins"))}</strong></div>
        <div><span>Consecutive Losses</span><strong>{escape_value(benchmark.get("consecutive_losses"))}</strong></div>
        <div><span>Best Trade</span><strong>${(parse_float(benchmark.get("best_trade")) or 0):.2f}</strong></div>
        <div><span>Worst Trade</span><strong>${(parse_float(benchmark.get("worst_trade")) or 0):.2f}</strong></div>
        <div><span>Daily P&amp;L</span><strong>${(parse_float(benchmark.get("daily_pnl")) or 0):.2f}</strong></div>
        <div><span>Milestones</span><strong>{escape_value(", ".join(benchmark.get("milestones_hit") or []) or "None")}</strong></div>
      </div>
      <div class="benchmark-position-grid">
        <div><span>Paper Trade Status</span><strong>{escape_value(position.get("result") or "OPEN") if position else "PENDING / waiting"}</strong></div>
        <div><span>Paper Trade Reason</span><strong>{escape_value(position.get("entry_reason") if position else last_trade.get("reason") if last_trade else benchmark.get("benchmark_entry_reason"))}</strong></div>
        <div><span>Open Paper Position</span><strong>{escape_value(position_text)}</strong></div>
        <div><span>Last Trade</span><strong>{escape_value(last_trade_text)}</strong></div>
        <div><span>Last Benchmark Event</span><strong>{escape_value(benchmark.get("last_event"))}</strong></div>
        <div><span>Reason Not Trading</span><strong>No benchmark trade because: {escape_value(no_trade_reason)}</strong></div>
        <div><span>Why Not Trading</span><strong>{escape_value(benchmark.get("paper_last_block_reason") or no_trade_reason)}</strong></div>
        <div><span>Next Condition Needed</span><strong>{escape_value(benchmark.get("next_condition_needed"))}</strong></div>
      </div>
      <div class="benchmark-equity-panel">
        <h3>Equity Curve</h3>
        {build_ai_benchmark_equity_curve(benchmark.get("equity_curve"))}
      </div>
      <details>
        <summary>Benchmark model and safeguards</summary>
        <p>The benchmark uses its own educational entry model. A 5/11 side score, dominant 15-minute pressure, active breakout/breakdown, VWAP-aligned momentum, or Trend Box and Market Box agreement may open a paper trade even while the dashboard recommendation remains WAIT.</p>
        <p>It targets 3-10 paper trades when valid setups appear. It pauses at 10 trades, two consecutive losses, a -5% daily loss, or a +5% daily profit unless continue benchmark mode is enabled.</p>
        <p>Stale data, invalid prices, a missing resolved stop/target, an existing paper position, daily trade limits, and two consecutive paper losses remain blocked. Research replay may use a fixed paper-only fallback when structure support or resistance is unavailable; the visible dashboard recommendation and risk controls are unchanged.</p>
        <p>The synthetic comparison starts each contract at $1.00 and applies a fixed 0.50 delta to SPY movement. Exits use structure stop, structure target, opposite confirmation, or the 3:55 PM ET manage-only rule.</p>
        <p>This mode evaluates scanner behavior only. It does not create recommendations, connect to a broker, or represent exact option pricing.</p>
      </details>
      <h3>AI Paper Trade Log</h3>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Time</th><th>Signal</th><th>Direction</th><th>Entry SPY Price</th><th>Exit SPY Price</th><th>Simulated Contract Entry</th><th>Simulated Contract Exit</th><th>Duration</th><th>P&amp;L</th><th>Entry Reason</th><th>Exit Reason</th><th>Result</th></tr></thead>
          <tbody>{trade_rows}</tbody>
        </table>
      </div>
        </div>
      </details>
    </section>
    """


def build_score_breakdown(latest):
    if not latest:
        return '<p class="empty">Waiting for score data.</p>'

    activity_filter = latest.get("activity_filter", "N/A").upper()
    warning = (
        '<p class="activity-warning">Low activity. Be careful forcing trades.</p>'
        if activity_filter == "SLOW" else ""
    )

    return f"""
    <section class="score-section">
      <div class="score-grid">
        <div><span>Trend</span><strong>{escape_value(latest.get("trend_score"))} / 20</strong></div>
        <div><span>Momentum</span><strong>{escape_value(latest.get("momentum_score"))} / 20</strong></div>
        <div><span>Engine</span><strong>{escape_value(latest.get("engine_score"))} / 20</strong></div>
        <div><span>Breadth</span><strong>{escape_value(latest.get("breadth_score"))} / 15</strong></div>
        <div><span>Volume</span><strong>{escape_value(latest.get("volume_activity_score"))} / 10</strong></div>
        <div><span>Candle Analysis</span><strong>{escape_value(latest.get("candle_analysis_score"))} / 15</strong></div>
        <div class="total"><span>Total Confidence</span><strong>{escape_value(latest.get("total_confidence", latest.get("confidence")))} / 100</strong></div>
      </div>
      <p class="note">
        Volume: {escape_value(latest.get("last_1m_bid_total"))}
        {escape_value(latest.get("volume_filter"))} |
        30m Activity: {escape_value(latest.get("rolling_30m_trade_count"))}
        {escape_value(activity_filter)} |
        Avg/min: {escape_value(latest.get("avg_trades_per_min_30m"))}
      </p>
      {warning}
    </section>
    """


def build_accuracy_tracker(rows, a_plus_rows):
    def summary(summary_rows):
        wins = sum(1 for row in summary_rows if row.get("result") == "WIN")
        losses = sum(1 for row in summary_rows if row.get("result") == "LOSS")
        flats = sum(1 for row in summary_rows if row.get("result") == "FLAT")
        decided = wins + losses
        return {
            "tracked": len(summary_rows),
            "wins": wins,
            "losses": losses,
            "flats": flats,
            "win_rate": (wins / decided * 100) if decided else 0
        }

    all_signals = summary(rows)
    a_plus_signals = summary(a_plus_rows)

    return f"""
    <section class="accuracy-section">
      <h3>All Signals</h3>
      <div class="accuracy-grid">
        <div><span>Tracked</span><strong>{all_signals["tracked"]}</strong></div>
        <div class="win"><span>Wins</span><strong>{all_signals["wins"]}</strong></div>
        <div class="loss"><span>Losses</span><strong>{all_signals["losses"]}</strong></div>
        <div><span>Flats</span><strong>{all_signals["flats"]}</strong></div>
        <div><span>Win Rate</span><strong>{all_signals["win_rate"]:.1f}%</strong></div>
      </div>
      <h3>A+ Signals Only</h3>
      <div class="accuracy-grid">
        <div><span>Tracked</span><strong>{a_plus_signals["tracked"]}</strong></div>
        <div class="win"><span>Wins</span><strong>{a_plus_signals["wins"]}</strong></div>
        <div class="loss"><span>Losses</span><strong>{a_plus_signals["losses"]}</strong></div>
        <div><span>Flats</span><strong>{a_plus_signals["flats"]}</strong></div>
        <div><span>Win Rate</span><strong>{a_plus_signals["win_rate"]:.1f}%</strong></div>
      </div>
      <p class="note">Win rates exclude FLAT results. A+ results are tracked separately from the original all-signals history.</p>
    </section>
    """


def build_a_plus_setup_filter(latest):
    if not latest:
        return '<section class="a-plus-filter no"><h2>A+ SETUP FILTER</h2><p class="empty">Waiting for scanner data.</p></section>'

    is_a_plus = (latest.get("a_plus_setup") or "NO").upper() == "YES"
    score = latest.get("confluence_score", "0")
    wait_reason = latest.get("a_plus_wait_reason") or "Waiting for eight aligned factors."
    return f"""
    <section class="a-plus-filter {'yes' if is_a_plus else 'no'}">
      <div>
        <span>A+ Setup</span>
        <strong>{'YES' if is_a_plus else 'NO'}</strong>
      </div>
      <div>
        <span>Confluence Score</span>
        <strong>{escape_value(score)} / 11</strong>
      </div>
      <div class="a-plus-reason">
        <span>{'Why it qualifies' if is_a_plus else 'Reason for WAIT'}</span>
        <strong>{escape_value(wait_reason)}</strong>
      </div>
    </section>
    """


def build_alert_table(rows, pressure_windows=None):
    if not rows:
        return (
            build_alert_pressure_windows(pressure_windows or [])
            + '<p class="empty">No alerts found yet.</p>'
        )

    columns = [
        "time",
        "option_type",
        "direction",
        "spy_price",
        "spy_change_percent"
    ]
    column_labels = {
        "directional_pressure": "Directional Pressure",
        "trade_decision": "Trade Decision",
        "decision_reason": "Reason"
    }
    header = "".join(
        f"<th>{escape_value(column_labels.get(column, column))}</th>"
        for column in columns
    )
    body_rows = []

    for row in reversed(rows[-25:]):
        cells = "".join(
            f"<td>{escape_value(row.get(column))}</td>"
            for column in columns
        )
        body_rows.append(f"<tr>{cells}</tr>")

    return (
        build_alert_pressure_windows(pressure_windows or [])
        + '<div class="table-wrap"><table>'
        f"<thead><tr>{header}</tr></thead>"
        f"<tbody>{''.join(body_rows)}</tbody></table></div>"
    )


def select_dashboard_history(local_rows, live_status, pushed_field):
    local_rows = [row for row in (local_rows or []) if isinstance(row, dict)]
    pushed_rows = live_status.get(pushed_field) if live_status else None
    pushed_rows = (
        [row for row in pushed_rows if isinstance(row, dict)]
        if isinstance(pushed_rows, list)
        else []
    )
    server_mode = (
        os.name != "nt"
        or os.environ.get("RENDER", "").strip().lower() in {"1", "true", "yes"}
    )
    if server_mode and len(pushed_rows) > len(local_rows):
        return pushed_rows
    return local_rows or pushed_rows


def build_recent_signal_history(rows):
    if not rows:
        return '<p class="empty">No prediction history received yet.</p>'

    body_rows = []
    for row in reversed(rows[-20:]):
        decision = (
            row.get("prediction")
            or row.get("trade_action")
            or row.get("decision")
            or row.get("direction")
            or row.get("signal")
            or "WAIT"
        )
        reason = str(row.get("reason") or row.get("banner_reason") or "")
        if len(reason) > 180:
            reason = f"{reason[:177]}..."
        body_rows.append(
            "<tr>"
            f"<td>{escape_value(row.get('time') or row.get('last_update'))}</td>"
            f"<td><strong>{escape_value(decision)}</strong></td>"
            f"<td>{escape_value(row.get('confidence') or row.get('total_confidence'))}%</td>"
            f"<td>${escape_value(row.get('spy_price') or row.get('current_spy_price'))}</td>"
            f"<td>{escape_value(reason)}</td>"
            f"<td>{escape_value(row.get('a_plus_setup') or 'N/A')}</td>"
            "</tr>"
        )

    return (
        '<div class="table-wrap"><table>'
        '<thead><tr><th>Time</th><th>Signal / Decision</th><th>Confidence</th>'
        '<th>SPY Price</th><th>Reason Summary</th><th>A+ Setup</th></tr></thead>'
        f"<tbody>{''.join(body_rows)}</tbody></table></div>"
    )


def build_recent_alert_history(alert_rows, result_rows):
    if not alert_rows:
        return '<p class="empty">No alert history received yet.</p>'

    result_by_direction = {}
    result_by_key = {}
    for result_row in result_rows or []:
        direction = str(
            result_row.get("option_type") or result_row.get("direction") or ""
        ).upper()
        entry_price = parse_float(
            result_row.get("entry_spy_price") or result_row.get("entry_price")
        )
        if direction:
            result_by_direction[direction] = result_row
            if entry_price is not None:
                result_by_key[(direction, round(entry_price, 4))] = result_row

    body_rows = []
    for row in reversed(alert_rows[-20:]):
        legacy_shifted = str(row.get("spy_price") or "").upper() in {"CALL", "PUT"}
        direction = str(
            row.get("spy_price")
            if legacy_shifted
            else row.get("option_type") or row.get("direction") or ""
        ).upper()
        if direction == "UP":
            direction = "CALL"
        elif direction == "DOWN":
            direction = "PUT"
        spy_price = parse_float(
            row.get("confidence")
            if legacy_shifted
            else row.get("spy_price") or row.get("entry_spy_price") or row.get("entry_price")
        )
        display_price = row.get("confidence") if legacy_shifted else (
            row.get("spy_price") or row.get("entry_spy_price")
        )
        display_move = row.get("reason") if legacy_shifted else (
            row.get("spy_change_percent") or row.get("move_percent")
        )
        result_row = (
            result_by_key.get((direction, round(spy_price, 4)))
            if direction and spy_price is not None
            else None
        ) or result_by_direction.get(direction, {})
        body_rows.append(
            "<tr>"
            f"<td>{escape_value(row.get('time'))}</td>"
            f"<td><strong>{escape_value(direction or 'N/A')}</strong></td>"
            f"<td>${escape_value(display_price)}</td>"
            f"<td>{escape_value(display_move)}%</td>"
            f"<td>{escape_value(result_row.get('result') or 'PENDING')}</td>"
            "</tr>"
        )

    return (
        '<div class="table-wrap"><table>'
        '<thead><tr><th>Time</th><th>Direction</th><th>SPY Price</th>'
        '<th>Move</th><th>Result</th></tr></thead>'
        f"<tbody>{''.join(body_rows)}</tbody></table></div>"
    )


def build_collapsible(title, content, open_by_default=False):
    section_ids = {
        "SPY Chart": "chart",
        "Regime Details": "regime-details",
        "Stability Details": "stability-details",
        "VWAP Details": "vwap-details",
        "Opening Range Details": "opening-range-details",
        "Market Breadth": "market-breadth",
        "Engine Health": "engine-health",
        "Call vs Put Pressure": "call-vs-put-pressure",
        "Accuracy": "accuracy",
        "Logs": "logs",
        "Support/Resistance Details": "support-resistance-details",
        "Score Breakdown": "score-breakdown"
    }
    section_id = section_ids.get(
        title,
        re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    )
    open_attribute = " open" if open_by_default else ""
    instruction = build_education_box(title)
    return f"""
    <details id="section-{section_id}" class="detail-section"
             data-section-id="{section_id}" data-persist-id="section-{section_id}"{open_attribute}>
      <summary>{escape_value(title)}</summary>
      <div class="detail-content">{instruction}{content}</div>
    </details>
    """


def build_prediction_table(rows, pressure_windows=None):
    if not rows:
        return "<p class=\"empty\">No direction predictions found yet.</p>"

    columns = [
        "directional_pressure",
        "trade_decision",
        "decision_reason",
        "time",
        "prediction",
        "confidence",
        "a_plus_setup",
        "confluence_score",
        "a_plus_wait_reason",
        "spy_price",
        "entry",
        "stop_loss",
        "target_1",
        "target_2",
        "risk_reward",
        "last_1m_bid_total",
        "last_1m_bid_average",
        "volume_filter",
        "rolling_30m_trade_count",
        "rolling_30m_call_count",
        "rolling_30m_put_count",
        "rolling_30m_wait_count",
        "avg_trades_per_min_30m",
        "activity_filter",
        "trend_score",
        "momentum_score",
        "engine_score",
        "breadth_score",
        "volume_activity_score",
        "candle_score",
        "candle_analysis_score",
        "candle_indecision",
        "last_3_candle_reading",
        "total_confidence",
        "regime",
        "previous_prediction",
        "mode_duration_minutes",
        "signal_flip_count_10m",
        "mode_stability",
        "vwap",
        "vwap_position",
        "vwap_confirmation",
        "opening_range_high",
        "opening_range_low",
        "opening_range_position",
        "market_structure",
        "current_advantage",
        "reversal_state",
        "reversal_reason",
        "mtf_1m_status",
        "mtf_1m_reason",
        "mtf_3m_status",
        "mtf_3m_reason",
        "mtf_5m_status",
        "mtf_5m_reason",
        "mtf_overall_signal",
        "mtf_alignment",
        "confirmation_needed",
        "invalidation_reason",
        "next_candle_bullish_scenario",
        "next_candle_bearish_scenario",
        "bullish_trigger",
        "bullish_confirmation",
        "bullish_breakout",
        "bearish_trigger",
        "bearish_confirmation",
        "bearish_breakdown",
        "level_update_time",
        "structure_update_epoch",
        "level_update_epoch",
        "levels_corrected",
        "nearest_support",
        "support_reason",
        "nearest_resistance",
        "resistance_reason",
        "support_distance",
        "resistance_distance",
        "alert_direction",
        "invalid_level",
        "reason"
    ]
    column_labels = {
        "directional_pressure": "Directional Pressure",
        "trade_decision": "Trade Decision",
        "decision_reason": "Reason"
    }
    header = "".join(
        f"<th>{escape_value(column_labels.get(column, column))}</th>"
        for column in columns
    )
    body_rows = []
    pressure = directional_pressure_label(pressure_windows or [])

    for row in reversed(rows[-50:]):
        prediction = row.get("prediction", "WAIT").lower()
        cells = []

        for column in columns:
            if column == "directional_pressure":
                value = escape_value(pressure)
            elif column == "trade_decision":
                value = escape_value(row.get("prediction", "WAIT"))
            elif column == "decision_reason":
                decision = (row.get("prediction") or "WAIT").upper()
                base_reason = row.get("a_plus_wait_reason") or row.get("reason") or "Waiting for confirmation."
                if decision == "WAIT" and pressure != "Mixed":
                    value = escape_value(
                        f"{pressure} pressure detected, but trade decision remains WAIT: {base_reason}"
                    )
                elif decision == "WAIT":
                    value = escape_value(f"Pressure is mixed; trade decision remains WAIT: {base_reason}")
                else:
                    value = escape_value(base_reason)
            else:
                value = escape_value(row.get(column))

            if column in ("prediction", "trade_decision"):
                value = f'<span class="tag {prediction}">{value}</span>'
            elif column == "confidence":
                value = f"{value}%"

            cells.append(f"<td>{value}</td>")

        body_rows.append(f"<tr>{''.join(cells)}</tr>")

    return (
        "<div class=\"table-wrap\"><table>"
        f"<thead><tr>{header}</tr></thead>"
        f"<tbody>{''.join(body_rows)}</tbody>"
        "</table></div>"
    )


def build_market_replay_education(rows):
    today_text = market_date_text()
    today_rows = [
        (row, parse_float(row.get("spy_price")))
        for row in rows
        if (row.get("time") or "").startswith(today_text)
        and parse_float(row.get("spy_price")) is not None
    ]
    if not today_rows:
        return '<p class="empty">No market replay data available for today yet.</p>'

    prices = [price for _, price in today_rows]
    open_price, close_price = prices[0], prices[-1]
    high_price, low_price = max(prices), min(prices)
    daily_move = close_price - open_price
    daily_direction = "Bullish" if daily_move > 0 else "Bearish" if daily_move < 0 else "Flat"

    def segment_story(start_hour, end_hour, label):
        segment = []
        for row, price in today_rows:
            try:
                row_time = datetime.strptime(row["time"], "%Y-%m-%d %H:%M:%S")
            except (KeyError, ValueError):
                continue
            if start_hour <= row_time.hour < end_hour:
                segment.append(price)
        if len(segment) < 2:
            return f"{label}: Not enough data yet."
        move = segment[-1] - segment[0]
        behavior = "advanced" if move > 0.03 else "declined" if move < -0.03 else "held a range"
        return f"{label}: SPY {behavior} by {abs(move):.2f}."

    timeline = [
        segment_story(9, 11, "Opening move"),
        segment_story(11, 14, "Midday behavior"),
        segment_story(14, 15, "Afternoon behavior"),
        segment_story(15, 17, "Closing behavior")
    ]
    saved_level_hits = read_saved_level_hits()
    hit_fields = (
        ("Bull Trigger", "bull_trigger_first_hit_time"),
        ("Bull Confirmation", "bull_confirmation_first_hit_time"),
        ("Bull Breakout", "bull_breakout_first_hit_time"),
        ("Bear Trigger", "bear_trigger_first_hit_time"),
        ("Bear Confirmation", "bear_confirmation_first_hit_time"),
        ("Bear Breakdown", "bear_breakdown_first_hit_time")
    )
    hit_times = {}
    for label, field in hit_fields:
        saved_time = saved_level_hits.get(field)
        if not saved_time:
            hit_times[label] = "Not hit"
            continue
        try:
            hit_times[label] = datetime.fromisoformat(saved_time).strftime("%I:%M:%S %p ET")
        except (TypeError, ValueError):
            hit_times[label] = saved_time

    directional = [row for row, _ in today_rows if (row.get("prediction") or "").upper() in ("CALL", "PUT")]
    if directional:
        first_direction = directional[0]["prediction"].upper()
        correct = (first_direction == "CALL" and daily_move > 0) or (first_direction == "PUT" and daily_move < 0)
        direction_review = f"First directional bias: {first_direction}. Correct by latest close: {'YES' if correct else 'NO'}."
    else:
        direction_review = "No directional CALL/PUT prediction was recorded today."

    combined_text = " ".join(
        " ".join(str(row.get(field, "")) for field in ("market_structure", "last_3_candle_reading", "reason", "mtf_1m_reason")).lower()
        for row, _ in today_rows
    )
    patterns = {
        "Lower High": "lower high" in combined_text,
        "Lower Low": "lower low" in combined_text,
        "Higher High": "higher high" in combined_text,
        "Higher Low": "higher low" in combined_text,
        "Rejection Wick": "rejection" in combined_text or "wick" in combined_text,
        "Engulfing Candle": "engulf" in combined_text,
        "Inside Bar": "inside" in combined_text,
        "Breakout": hit_times["Bull Breakout"] != "Not hit",
        "Breakdown": hit_times["Bear Breakdown"] != "Not hit"
    }
    vwap_positions = [(row.get("vwap_position") or "Mixed").upper() for row, _ in today_rows]
    vwap_crosses = sum(vwap_positions[index] != vwap_positions[index - 1] for index in range(1, len(vwap_positions)))
    total_range = high_price - low_price
    trend_grade = "A" if total_range and abs(daily_move) >= total_range * 0.65 else "B" if total_range and abs(daily_move) >= total_range * 0.35 else "C"
    volatility_grade = "A" if total_range >= 2 else "B" if total_range >= 1 else "C"
    cleanliness_grade = "A" if vwap_crosses <= 2 else "B" if vwap_crosses <= 5 else "C"
    tradeability_grade = "A" if trend_grade in ("A", "B") and cleanliness_grade in ("A", "B") else "C"

    hit_rows = "".join(f"<tr><td>{escape_value(label)}</td><td>{escape_value(hit)}</td></tr>" for label, hit in hit_times.items())
    timeline_items = "".join(f"<li>{escape_value(item)}</li>" for item in timeline)
    pattern_items = "".join(f'<li><strong>{escape_value(name)}:</strong> {"Detected" if found else "Not detected"}</li>' for name, found in patterns.items())
    lessons = (
        "Bull traps: Review bullish triggers that failed to reach confirmation.",
        "Bear traps: Review bearish triggers that failed to reach confirmation.",
        f"Failed breakouts: {'Possible' if hit_times['Bull Trigger'] != 'Not hit' and hit_times['Bull Breakout'] == 'Not hit' else 'No clear example detected'}.",
        f"Failed breakdowns: {'Possible' if hit_times['Bear Trigger'] != 'Not hit' and hit_times['Bear Breakdown'] == 'Not hit' else 'No clear example detected'}.",
        f"VWAP interactions: {vwap_crosses} position changes detected."
    )
    lesson_items = "".join(f"<li>{escape_value(item)}</li>" for item in lessons)
    quizzes = (
        f"Why did SPY finish {daily_direction.lower()} despite any opposite intraday signals?",
        f"What did the {vwap_crosses} VWAP position changes suggest about market cleanliness?",
        "Which trigger needed confirmation before becoming a higher-quality trade?"
    )
    quiz_items = "".join(f"<li>{escape_value(question)}</li>" for question in quizzes)
    latest_row = today_rows[-1][0]
    best_setup = (
        "Bullish confirmation above VWAP"
        if daily_direction == "Bullish"
        else "Bearish confirmation below VWAP"
        if daily_direction == "Bearish"
        else "Wait for a range break"
    )
    mistake_to_avoid = (
        "Do not chase moves after they extend away from structure."
        if trend_grade in ("A", "B")
        else "Do not force direction while price rotates through the range."
    )
    candle_lesson = latest_row.get("last_3_candle_reading") or "Wait for candle closes to confirm structure."
    recap_items = (
        ("Market structure", latest_row.get("market_structure") or "Range / mixed"),
        ("Trend direction", daily_direction),
        ("Best setup", best_setup),
        ("Mistake to avoid", mistake_to_avoid),
        ("Candle lesson", candle_lesson),
        ("Educational summary", "Use structure, VWAP, and confirmation together. A trigger alone is observation, not permission.")
    )
    recap_html = "".join(
        f"<div><span>{escape_value(label)}</span><strong>{escape_value(value)}</strong></div>"
        for label, value in recap_items
    )

    return f"""
    <section class="market-replay">
      <div class="replay-summary-grid">
        <div><span>Open</span><strong>{open_price:.2f}</strong></div><div><span>High</span><strong>{high_price:.2f}</strong></div>
        <div><span>Low</span><strong>{low_price:.2f}</strong></div><div><span>Close</span><strong>{close_price:.2f}</strong></div>
        <div><span>Daily Direction</span><strong>{daily_direction}</strong></div><div><span>Range</span><strong>{total_range:.2f}</strong></div>
      </div>
      <div class="replay-grid">
        <article><h3>Candle Story Timeline</h3><ul>{timeline_items}</ul></article>
        <article><h3>Dashboard Decision Review</h3><div class="table-wrap"><table><thead><tr><th>Level</th><th>First Hit</th></tr></thead><tbody>{hit_rows}</tbody></table></div><p>{escape_value(direction_review)}</p></article>
        <article><h3>Educational Lessons</h3><ul>{lesson_items}</ul></article>
        <article><h3>Candle Patterns Detected</h3><ul>{pattern_items}</ul></article>
        <article><h3>Student Quiz</h3><ol>{quiz_items}</ol></article>
        <article><h3>Trade Grade</h3><div class="replay-grade-grid"><div>Trend quality <strong>{trend_grade}</strong></div><div>Volatility <strong>{volatility_grade}</strong></div><div>Cleanliness <strong>{cleanliness_grade}</strong></div><div>Tradeability <strong>{tradeability_grade}</strong></div></div></article>
        <article class="daily-recap"><h3>Daily Market Recap</h3><div class="daily-recap-grid">{recap_html}</div></article>
      </div>
    </section>
    """


def get_eastern_clock_fields():
    eastern_now = datetime.now(ZoneInfo("America/New_York"))
    return {
        "eastern_time": eastern_now.strftime("%I:%M:%S %p ET"),
        "eastern_seconds": (
            eastern_now.hour * 3600
            + eastern_now.minute * 60
            + eastern_now.second
        ),
        "eastern_iso": eastern_now.isoformat(),
        "eastern_weekday": eastern_now.weekday(),
        "market_session_open": (
            eastern_now.weekday() < 5
            and 9 * 60 + 30
            <= eastern_now.hour * 60 + eastern_now.minute
            < 16 * 60
        )
    }


def get_live_status_debug_fields(live_status):
    return {
        "live_status_file_path": live_status.get("live_status_file_path"),
        "live_status_raw_first_200_chars": live_status.get(
            "live_status_raw_first_200_chars", ""
        ),
        "live_status_exists": live_status.get("live_status_exists", False),
        "update_epoch": live_status.get("update_epoch"),
        "server_epoch": live_status.get("server_epoch"),
        "data_age_seconds": live_status.get("data_age_seconds"),
        "feed_connected": live_status.get("feed_connected", False),
        "feed_status": live_status.get("feed_status", "DASHBOARD FEED DISCONNECTED"),
        "analysis_delayed": live_status.get("analysis_delayed", False),
        "stale_reason": live_status.get("stale_reason", ""),
        "latest_prediction_history_count": live_status.get("latest_prediction_history_count", 0),
        "latest_alert_history_count": live_status.get("latest_alert_history_count", 0),
        "latest_alert_result_history_count": live_status.get("latest_alert_result_history_count", 0),
        "latest_paper_trade_history_count": live_status.get("latest_paper_trade_history_count", 0)
    }


def get_live_level_status():
    global last_live_api_status

    rows = read_recent_predictions()
    latest = dict(rows[-1]) if rows else None
    live_status = read_live_status()
    if not latest:
        if live_status.get("available"):
            return {
                "available": True,
                "live_price": parse_float(live_status.get("spy_price")),
                "live_spy_price": parse_float(live_status.get("spy_price")),
                "data_stale": live_status.get("stale", True),
                "data_age": live_status.get("data_age"),
                "last_updated": live_status.get("updated_at", "N/A"),
                "data_source": live_status.get("data_source", "N/A"),
                "analysis_age": None,
                "analysis_age_seconds": None,
                "banner": "WAIT",
                "banner_text": (
                    "DATA STALE - DO NOT TRADE"
                    if live_status.get("stale", True)
                    else "WAIT - LIVE PRICE CONNECTED"
                ),
                "banner_reason": "Prediction levels are not available yet.",
                "current_banner_reason": "Prediction levels are not available yet.",
                "trade_risk": "NO TRADE",
                "error": "No prediction levels available",
                **get_dashboard_build_metadata(),
                **get_live_status_debug_fields(live_status),
                **get_eastern_clock_fields()
            }
        return {
            "available": False,
            "error": "No prediction levels available",
            "analysis_age": None,
            "analysis_age_seconds": None,
            **get_dashboard_build_metadata(),
            **get_live_status_debug_fields(live_status),
            **get_eastern_clock_fields()
        }

    data_stale = not live_status.get("available") or live_status.get("stale", True)
    if data_stale and last_live_api_status:
        frozen_status = dict(last_live_api_status)
        frozen_status.update({
            "data_stale": True,
            "data_age": live_status.get("data_age"),
            "last_updated": live_status.get("updated_at", frozen_status.get("last_updated", "N/A")),
            "banner": "WAIT",
            "banner_text": "DATA STALE â€” DO NOT TRADE",
            "banner_reason": "Live price data is older than 180 seconds.",
            "current_banner_reason": "Live price data is older than 180 seconds.",
            "trade_risk": "NO TRADE",
            "analysis_age": frozen_status.get("analysis_age"),
            "analysis_age_seconds": frozen_status.get("analysis_age_seconds"),
            **get_dashboard_build_metadata(),
            **get_live_status_debug_fields(live_status),
            **get_eastern_clock_fields()
        })
        return frozen_status

    displayed_price = (
        live_status.get("spy_price")
        if live_status.get("available") else latest.get("spy_price")
    )
    latest["_data_stale"] = data_stale
    if last_daily_midpoint_analysis:
        neutralize_suspicious_daily_midpoint(latest, last_daily_midpoint_analysis)
    level_reference_price = latest.get("spy_price")
    latest, corrected = correct_levels_from_live_price(
        latest,
        latest.get("level_reference_price", level_reference_price)
    )
    states = get_level_activation_states(latest, displayed_price)
    correction = detect_short_term_correction(rows, displayed_price)
    latest.update(correction)
    breakdown = detect_bearish_breakdown_state(latest, rows, displayed_price, states)
    latest.update(breakdown)
    if breakdown["bearish_breakdown_active"]:
        latest["market_phase"] = "BEARISH BREAKDOWN"
        latest["current_advantage"] = "Sellers"
    latest.update(evaluate_dashboard_trend_override(latest, rows, read_alerts()))
    regime = (
        "TRENDING DOWN"
        if breakdown["bearish_breakdown_active"]
        else latest.get("dashboard_market_condition")
        if latest.get("dashboard_trend_override")
        else (latest.get("regime") or "CHOPPY").upper()
    )
    market_phase_display = get_market_phase_display(latest, regime)
    trade_risk = get_trade_risk_override(latest, regime)
    decision = get_trade_decision_data(latest, regime, trade_risk, states)
    benchmark = update_ai_paper_benchmark(
        latest,
        decision,
        regime,
        trade_risk,
        displayed_price,
        data_stale,
        rows,
        read_alerts(),
        states
    )
    banner = decision["mode"]
    banner_text = decision["header"]
    banner_reason = decision["reason"]
    trend = "UP" if regime == "TRENDING UP" else (
        "DOWN" if regime == "TRENDING DOWN" else "MIXED"
    )
    confidence = parse_float(latest.get("confidence")) or 0
    bullish_confidence = confidence if trend == "UP" else max(0, 100 - confidence)
    bearish_confidence = confidence if trend == "DOWN" else max(0, 100 - confidence)
    pushed_engine_rows = live_status.get("latest_engine_health_rows")
    engine_health_rows = read_engine_health()
    response = {
        "available": True,
        "live_price": parse_float(displayed_price),
        "live_spy_price": parse_float(displayed_price),

        # Main signal fields for Render /api/status
        "prediction": (
            latest.get("prediction")
            or latest.get("spy_signal")
            or latest.get("signal")
            or latest.get("direction")
            or banner
            or "WAIT"
        ),
        "confidence": (
            parse_float(latest.get("confidence"))
            or parse_float(latest.get("total_confidence"))
            or parse_float(latest.get("total_score"))
            or 0
        ),
        "level_update_time": (
            latest.get("level_update_time")
            or live_status.get("level_update_time")
            or "N/A"
        ),

        "bull_trigger": parse_float(latest.get("bullish_trigger")),
        "bull_confirmation": parse_float(latest.get("bullish_confirmation")),
        "bull_breakout": parse_float(latest.get("bullish_breakout")),
        "bear_trigger": parse_float(latest.get("bearish_trigger")),
        "bear_confirmation": parse_float(latest.get("bearish_confirmation")),
        "bear_breakdown": parse_float(latest.get("bearish_breakdown")),
        "nearest_support": parse_float(latest.get("nearest_support")),
        "nearest_resistance": parse_float(latest.get("nearest_resistance")),
        "trend": trend,
        "bullish_confidence": bullish_confidence,
        "bearish_confidence": bearish_confidence,
        "banner": banner,
        "banner_text": banner_text,
        "banner_reason": banner_reason,
        "market_phase_display": market_phase_display,
        "current_banner_reason": banner_reason,
        "one_min_trend": latest.get("mtf_1m_status", "Neutral"),
        "vwap_position": latest.get("vwap_position", "Mixed"),
        "active_bull_level": states["bull_status"],
        "active_bear_level": states["bear_status"],
        "current_advantage": decision["advantage"],
        "mode_stability": latest.get("mode_stability", "N/A"),
        "confluence_final_read": decision["final_read"],
        "bullish_confluence_score": decision["bullish_score"],
        "bearish_confluence_score": decision["bearish_score"],
        "neutral_confluence_score": decision["neutral_score"],
        "confluence_score": max(decision["bullish_score"], decision["bearish_score"]),
        "a_plus_setup": decision["a_plus_setup"],
        "market_regime": regime,
        "market_condition": latest.get("dashboard_market_condition", regime),
        "trade_action": latest.get("dashboard_trade_action", decision["header"]),
        "trend_override_active": bool(latest.get("dashboard_trend_override")),
        "trend_override_label": latest.get("dashboard_trend_override_label", ""),
        "strict_bullish_override": bool(latest.get("dashboard_strict_bullish_override")),
        "trend_override_reason": latest.get("dashboard_trend_reason", ""),
        "midpoint_15m_bias": latest.get("dashboard_midpoint_15m_bias", "Neutral"),
        "midpoint_30m_bias": latest.get("dashboard_midpoint_30m_bias", "Neutral"),
        "pressure_bias": latest.get("dashboard_pressure_bias", "Mixed"),
        "trade_risk": trade_risk,
        "ai_paper_benchmark": benchmark,
        "paper_research_mode": benchmark.get("paper_research_mode", PAPER_RESEARCH_MODE),
        "paper_last_block_reason": benchmark.get("paper_last_block_reason", ""),
        "paper_entry_rule_used": benchmark.get("paper_entry_rule_used", "None"),
        "paper_last_evaluation_time": benchmark.get("paper_last_evaluation_time"),
        "paper_trade_candidate_direction": benchmark.get("paper_trade_candidate_direction"),
        "paper_trade_candidate_confidence": benchmark.get("paper_trade_candidate_confidence", 0),
        "paper_stop_source": benchmark.get("paper_stop_source", "none"),
        "paper_stop": benchmark.get("paper_stop"),
        "paper_target": benchmark.get("paper_target"),
        "paper_risk_per_share": benchmark.get("paper_risk_per_share"),
        "paper_reward_per_share": benchmark.get("paper_reward_per_share"),
        "paper_risk_reward": benchmark.get("paper_risk_reward"),
        "paper_stop_computed": benchmark.get("paper_stop_computed", False),
        "paper_block_stage": benchmark.get("paper_block_stage", "pre_compute"),
        "daily_midpoint_source_suspicious": bool(
            last_daily_midpoint_analysis
            and last_daily_midpoint_analysis.get("suspicious")
        ),
        "data_stale": (
            not live_status.get("available") or live_status.get("stale", True)
            if live_status else True
        ),
        "data_age": live_status.get("data_age") if live_status else None,
        "feed_age": live_status.get("data_age") if live_status else None,
        "analysis_age": get_analysis_age_seconds(latest),
        "analysis_age_seconds": get_analysis_age_seconds(latest),
        "last_updated": live_status.get("updated_at") if live_status else "N/A",
        "engine_health_row_count": len(engine_health_rows),
        "latest_engine_health_rows_count": (
            len(pushed_engine_rows) if isinstance(pushed_engine_rows, list) else 0
        ),
        "dashboard_engine_source": dashboard_engine_source,
        "dashboard_engine_unique_count": dashboard_engine_unique_count,
        **get_dashboard_build_metadata(),
        **get_live_status_debug_fields(live_status),
        **get_eastern_clock_fields(),
        "level_set_id": states["debug"].get("level_set_id"),
        "last_level_set_id": states["debug"].get("last_level_set_id"),
        "level_hit_timestamp": states["debug"].get("level_hit_timestamp", {}),
        "saved_hit_times_file_path": states["debug"].get("saved_hit_times_file_path"),
        "last_saved_hit_time": states["debug"].get("last_saved_hit_time"),
        "first_hit_times": states["debug"].get("first_hit_times", {}),
        "last_hit_bull_level": states["debug"].get("last_hit_bull_level", 0),
        "last_hit_bear_level": states["debug"].get("last_hit_bear_level", 0),
        "session_high": states["debug"].get("session_high"),
        "session_low": states["debug"].get("session_low"),
        "level_set_high": states["debug"].get("level_set_high"),
        "level_set_low": states["debug"].get("level_set_low"),
        "bull_trigger_hit": states["debug"].get("last_hit_bull_level", 0) >= 1,
        "bull_confirmation_hit": states["debug"].get("last_hit_bull_level", 0) >= 2,
        "bull_breakout_hit": states["debug"].get("last_hit_bull_level", 0) >= 3,
        "bear_trigger_hit": states["debug"].get("last_hit_bear_level", 0) >= 1,
        "bear_confirmation_hit": states["debug"].get("last_hit_bear_level", 0) >= 2,
        "bear_breakdown_hit": states["debug"].get("last_hit_bear_level", 0) >= 3,
        "levels_corrected": corrected,
        "bull_status": states["bull_status"],
        "bear_status": states["bear_status"],
        **correction,
        **breakdown,
        "states": {
            key: {"class_name": states[key][0], "label": states[key][1]}
            for key in (
                "bull_trigger",
                "bull_confirm",
                "bull_breakout",
                "bear_trigger",
                "bear_confirm",
                "bear_breakdown"
            )
        },
        **level_first_hit_times
    }
    if not data_stale:
        last_live_api_status = dict(response)
    return response


def build_dashboard_content():
    global last_daily_midpoint_analysis

    rows = read_predictions()
    live_status = read_live_status()
    alert_rows = read_alerts()
    result_rows = read_results()
    a_plus_result_rows = read_a_plus_results()
    engine_rows = read_engine_health()
    breadth_row = read_market_breadth()
    history_prediction_rows = select_dashboard_history(
        rows,
        live_status,
        "latest_prediction_history"
    )
    history_alert_rows = select_dashboard_history(
        alert_rows,
        live_status,
        "latest_alert_history"
    )
    history_result_rows = select_dashboard_history(
        result_rows,
        live_status,
        "latest_alert_result_history"
    )
    update_historical_market_archive(rows, alert_rows, result_rows)
    latest = dict(rows[-1]) if rows else None

    if latest and live_status and live_status.get("available"):
        latest["level_reference_price"] = latest.get("spy_price")
        latest["spy_price"] = live_status["spy_price"]
    last_daily_midpoint_analysis = calculate_daily_midpoint_source(
        rows,
        latest.get("spy_price") if latest else None
    )
    neutralize_suspicious_daily_midpoint(latest, last_daily_midpoint_analysis)
    if latest:
        latest["_data_stale"] = not live_status.get("available") or live_status.get("stale", True)
        latest.update(detect_short_term_correction(rows, latest.get("spy_price")))
        breakdown_states = get_level_activation_states(
            latest,
            live_status.get("spy_price") if live_status and live_status.get("available") else latest.get("spy_price")
        )
        latest.update(
            detect_bearish_breakdown_state(
                latest,
                rows,
                latest.get("spy_price"),
                breakdown_states
            )
        )
        if latest.get("bearish_breakdown_active"):
            latest["market_phase"] = "BEARISH BREAKDOWN"
            latest["current_advantage"] = "Sellers"
            latest["regime"] = "TRENDING DOWN"
        latest.update(evaluate_dashboard_trend_override(latest, rows, alert_rows))
    recent_rows = rows[-50:]
    regime_data = detect_regime(rows)
    if latest and latest.get("dashboard_trend_override"):
        regime_data["regime"] = latest["dashboard_market_condition"]
        regime_data["reason"] = latest["dashboard_trend_reason"]
    elif latest and latest.get("regime"):
        regime_data["regime"] = latest["regime"]
        regime_data["reason"] = (
            latest.get("bearish_breakdown_reason")
            if latest.get("bearish_breakdown_active")
            else latest.get("reason", regime_data["reason"])
        )
    dashboard_trade_risk = get_trade_risk_override(
        latest,
        regime_data.get("regime", "CHOPPY")
    )
    dashboard_level_states = get_level_activation_states(
        latest or {},
        live_status.get("spy_price") if live_status and live_status.get("available") else None
    )
    trade_decision = get_trade_decision_data(
        latest,
        regime_data.get("regime", "CHOPPY"),
        dashboard_trade_risk,
        dashboard_level_states
    )
    if latest:
        latest["current_advantage"] = trade_decision["advantage"]
    benchmark = update_ai_paper_benchmark(
        latest,
        trade_decision,
        regime_data.get("regime", "CHOPPY"),
        dashboard_trade_risk,
        live_status.get("spy_price") if live_status and live_status.get("available") else None,
        not live_status or not live_status.get("available") or live_status.get("stale", True),
        rows,
        alert_rows,
        dashboard_level_states
    )
    prediction_pressure = calculate_pressure(
        recent_rows,
        "prediction",
        "CALL",
        "PUT",
        "WAIT"
    )
    alert_pressure = calculate_pressure(
        alert_rows,
        "option_type",
        "CALL",
        "PUT"
    )
    alert_pressure_windows = calculate_alert_pressure_windows(alert_rows, rows)
    prediction_card = build_prediction_card(latest)
    position_plan = f'{build_education_box("Position Plan")}{build_position_plan(latest)}'
    pressure_section = build_pressure_section(
        prediction_pressure,
        alert_pressure,
        alert_pressure_windows
    )
    engine_health_section = build_engine_health_section(engine_rows)
    market_breadth_section = build_market_breadth_section(breadth_row)
    multi_timeframe_monitor = build_multi_timeframe_monitor(latest)
    reversal_monitor = build_reversal_monitor(latest)
    sticky_signal_summary = build_compact_sticky_signal_summary(
        latest,
        regime_data,
        live_status,
        trade_decision
    )
    top_confluence_checklist = build_top_confluence_checklist(
        latest,
        trade_decision,
        rows
    )
    trade_decision_meter = build_trade_decision_meter(trade_decision)
    ai_paper_benchmark = build_ai_paper_benchmark(benchmark)
    time_discipline_card = build_time_discipline_card()
    trade_risk_meter = build_trade_risk_meter(latest, regime_data)
    pre_market_panel = build_pre_market_panel(latest)
    top_education_guides = build_top_education_guides()
    signal_explanation = build_signal_explanation(latest, regime_data, live_status)
    regime_label = build_regime_label(regime_data)
    stability_label = build_stability_label(latest)
    vwap_label = build_vwap_label(latest)
    opening_range_label = build_opening_range_label(latest)
    regime_section = build_regime_details(regime_data)
    stability_section = build_stability_details(latest)
    vwap_section = build_vwap_details(latest)
    opening_range_section = build_opening_range_details(latest)
    live_chart = build_live_chart(rows)
    accuracy_tracker = build_accuracy_tracker(result_rows, a_plus_result_rows)
    score_breakdown = build_score_breakdown(latest)
    chart_reading_section = build_chart_reading_details(latest)
    support_resistance_section = build_support_resistance_details(latest)
    alert_table = build_alert_table(alert_rows, alert_pressure_windows)
    prediction_table = build_prediction_table(rows, alert_pressure_windows)
    recent_signal_history = build_recent_signal_history(history_prediction_rows)
    recent_alert_history = build_recent_alert_history(
        history_alert_rows,
        history_result_rows
    )
    market_replay = build_market_replay_education(rows)
    historical_archive = build_historical_market_archive()
    intraday_midpoints = build_intraday_midpoints(rows, latest.get("spy_price") if latest else None)
    daily_midpoint = build_daily_midpoint(
        rows,
        latest.get("spy_price") if latest else None,
        last_daily_midpoint_analysis
    )
    trend_box = build_trend_box(rows, latest.get("spy_price") if latest else None)
    market_box = build_market_structure_box(
        rows,
        latest.get("spy_price") if latest else None,
        last_daily_midpoint_analysis
    )
    chart_details = build_collapsible("SPY Chart", live_chart, True)
    chart_reading_details = build_collapsible(
        "Chart Reading Details",
        chart_reading_section
    )
    support_resistance_details = build_collapsible(
        "Support/Resistance Details",
        support_resistance_section
    )
    engine_details = build_collapsible(
        "Engine Health",
        engine_health_section
    )
    pressure_details = build_collapsible("Call vs Put Pressure", pressure_section)
    breadth_details = build_collapsible(
        "Market Breadth",
        market_breadth_section
    )
    regime_details = build_collapsible("Regime Details", regime_section)
    stability_details = build_collapsible(
        "Stability Details",
        stability_section
    )
    vwap_details = build_collapsible("VWAP Details", vwap_section)
    opening_range_details = build_collapsible(
        "Opening Range Details",
        opening_range_section
    )
    score_details = build_collapsible("Score Breakdown", score_breakdown)
    accuracy_details = build_collapsible("Accuracy", accuracy_tracker)
    market_replay_details = build_collapsible(
        "MARKET REPLAY & EDUCATION",
        market_replay
    )
    historical_archive_details = build_collapsible(
        "HISTORICAL MARKET ARCHIVE",
        historical_archive
    )
    trend_box_details = build_collapsible("TREND BOX", trend_box)
    market_box_details = build_collapsible("MARKET BOX", market_box)
    logs_details = build_collapsible(
        "Logs",
        f"<h2>Recent Predictions</h2>{prediction_table}"
        f"<h2>Recent Alerts</h2>{alert_table}"
    )
    recent_signal_history_details = build_collapsible(
        "Recent Signal History",
        recent_signal_history
    )
    recent_alert_history_details = build_collapsible(
        "Recent Alert History",
        recent_alert_history
    )

    return f"""
    {sticky_signal_summary}
    {top_confluence_checklist}
    {trade_decision_meter}
    {time_discipline_card}
    {intraday_midpoints}
    {daily_midpoint}
    {pre_market_panel}
    {trade_risk_meter}
    {top_education_guides}
    {signal_explanation}
    {multi_timeframe_monitor}
    {reversal_monitor}
    {vwap_label}
    {opening_range_label}
    {prediction_card}
    {position_plan}
    {score_details}
    {chart_details}
    {support_resistance_details}
    {market_box_details}
    {trend_box_details}
    {chart_reading_details}
    {regime_details}
    {stability_details}
    {vwap_details}
    {opening_range_details}
    {breadth_details}
    {engine_details}
    {pressure_details}
    {accuracy_details}
    {market_replay_details}
    {historical_archive_details}
    {ai_paper_benchmark}
    {recent_signal_history_details}
    {recent_alert_history_details}
    {logs_details}
    """


def build_page():
    dashboard_content = build_dashboard_content()

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SPY Direction Dashboard</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: #eef2f5;
      color: #17202a;
      font-family: Arial, sans-serif;
    }}
    main {{ width: min(1500px, 100%); margin: auto; padding: 24px; }}
    h2 {{ margin: 28px 0 12px; font-size: 18px; }}
    .top-actions {{
      display: flex;
      justify-content: flex-end;
      margin-bottom: 8px;
    }}
    .refresh-button {{
      border: 1px solid #b8c3cc;
      background: white;
      color: #17202a;
      padding: 9px 14px;
      border-radius: 4px;
      cursor: pointer;
      font-weight: bold;
    }}
    .refresh-button:hover {{ background: #e4eaf0; }}
    .dashboard-version {{
      color: #60707d;
      font-size: 10px;
      font-weight: normal;
      white-space: nowrap;
    }}
    .dashboard-footer {{
      display: grid;
      gap: 3px;
      margin: 18px 0 6px;
      color: #60707d;
      font-size: 11px;
      text-align: center;
    }}
    .dashboard-footer span, .dashboard-footer b {{
      overflow-wrap: anywhere;
    }}
    .mtf-monitor {{
      margin-bottom: 8px;
      padding: 12px;
      background: white;
      border: 1px solid #d9e1e8;
      border-radius: 6px;
    }}
    .mtf-heading {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
      margin-bottom: 8px;
    }}
    .mtf-heading > div {{
      border: 1px solid #e1e6ea;
      padding: 10px;
    }}
    .mtf-heading span, .mtf-card span {{
      display: block;
      color: #66727c;
      font-size: 11px;
      font-weight: bold;
      text-transform: uppercase;
    }}
    .mtf-heading strong {{ display: block; margin-top: 4px; font-size: 22px; }}
    .mtf-heading .strong-call, .mtf-heading .call,
    .mtf-heading .high-conviction {{ color: #137a4b; }}
    .mtf-heading .strong-put, .mtf-heading .put {{ color: #b83a3a; }}
    .mtf-heading .wait, .mtf-heading .choppy {{ color: #a8831d; }}
    .mtf-heading .early-warning {{ color: #2474c6; }}
    .mtf-grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 8px;
    }}
    .mtf-card {{
      border: 1px solid #e1e6ea;
      border-left: 5px solid #75808a;
      padding: 10px;
    }}
    .mtf-card.bullish {{ border-left-color: #137a4b; }}
    .mtf-card.bearish {{ border-left-color: #b83a3a; }}
    .mtf-card strong {{ display: block; margin-top: 4px; font-size: 18px; }}
    .mtf-card.bullish strong {{ color: #137a4b; }}
    .mtf-card.bearish strong {{ color: #b83a3a; }}
    .mtf-card p {{ margin: 6px 0 0; color: #4d5963; font-size: 12px; line-height: 1.4; }}
    .reversal-monitor {{
      margin-bottom: 8px;
      padding: 12px;
      background: white;
      border: 1px solid #d9e1e8;
      border-radius: 6px;
    }}
    .reversal-badges {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 8px;
    }}
    .reversal-badge {{
      padding: 10px 8px;
      border: 1px solid #d9e1e8;
      color: #75808a;
      text-align: center;
      font-size: 12px;
      font-weight: bold;
    }}
    .reversal-badge.active {{ color: white; border-color: transparent; }}
    .reversal-badge.potential-bull.active {{ background: #4f8f70; }}
    .reversal-badge.potential-bear.active {{ background: #a76767; }}
    .reversal-badge.confirmed-bull.active {{ background: #137a4b; }}
    .reversal-badge.confirmed-bear.active {{ background: #b83a3a; }}
    .reversal-monitor p {{ margin: 10px 0 0; color: #4d5963; line-height: 1.45; }}
    .mode-banner {{
      display: flex;
      align-items: center;
      justify-content: center;
      color: white;
      margin: 0;
      min-height: 110px;
      padding: 20px;
      border-radius: 6px;
    }}
    .mode-banner.call {{ background: #137a4b; }}
    .mode-banner.put {{ background: #b83a3a; }}
    .mode-banner.wait {{ background: #c49a26; color: #171717; }}
    .mode-banner strong {{ font-size: 42px; }}
    .sticky-area {{
      position: sticky;
      top: 0;
      z-index: 999;
      background: #f8fafb;
      box-shadow: 0 5px 16px rgba(10, 18, 24, 0.20);
      border: 1px solid #d7dfe5;
      margin-bottom: 8px;
    }}
    .sticky-area .trade-decision-meter {{
      margin: 0;
      border: 0;
      border-top: 1px solid #d7dfe5;
      padding: 6px 10px 7px;
    }}
    .sticky-area .decision-meter-scale {{ margin: 2px 0 5px; }}
    .sticky-area .decision-meter-scores > div {{ padding: 4px 7px; }}
    .sticky-area .decision-meter-scores strong {{ display: inline; margin-left: 4px; font-size: 12px; }}
    .sticky-area .trade-decision-meter p {{ margin: 5px 0 0; color: #596774; font-size: 11px; }}
    .top-confluence-checklist {{
      background: white;
      border: 1px solid #d7dfe5;
      border-left: 7px solid #596774;
      box-shadow: 0 2px 10px rgba(31, 45, 61, 0.10);
      margin: 10px 0;
      padding: 16px 18px;
      width: 100%;
      overflow: hidden;
    }}
    .top-confluence-heading {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 18px;
    }}
    .top-confluence-heading span, .top-confluence-scores span {{
      display: block;
      color: #596774;
      font-size: 11px;
    }}
    .top-confluence-heading strong {{
      display: block;
      margin-top: 3px;
      font-size: 18px;
    }}
    .top-confluence-final {{
      min-width: 150px;
      border-left: 5px solid #c98b00;
      background: #f4f7fa;
      padding: 9px 12px;
    }}
    .top-confluence-final b {{ display: block; margin-top: 3px; font-size: 17px; }}
    .top-confluence-scores {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 8px;
      margin-top: 12px;
    }}
    .top-confluence-scores span {{
      background: #f4f7fa;
      padding: 9px 10px;
    }}
    .top-confluence-scores b {{ display: block; margin-top: 3px; color: #17202a; font-size: 15px; }}
    .top-confluence-reason {{
      margin: 10px 0 0;
      color: #596774;
      font-size: 12px;
      line-height: 1.4;
    }}
    .top-confluence-factors {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
      gap: 12px;
      margin-top: 12px;
    }}
    .top-confluence-factor {{
      min-width: 0;
      border: 1px solid #d7dfe5;
      border-left: 5px solid #8a8f98;
      background: #f0f3f5;
      padding: 10px 11px;
    }}
    .top-confluence-factor span, .top-confluence-factor strong {{
      display: block;
      overflow-wrap: anywhere;
      font-size: 12px;
      line-height: 1.35;
    }}
    .top-confluence-factor strong {{ margin-top: 5px; font-size: 13px; }}
    .top-confluence-factor.bullish {{ border-left-color: #137a4b; background: #e9f7ef; }}
    .top-confluence-factor.bearish {{ border-left-color: #b83a3a; background: #fde9e9; }}
    .top-confluence-factor.conflict {{ border-left-color: #c98b00; background: #fff6d8; }}
    .sticky-signal-summary {{
      display: grid;
      grid-template-columns: 1.3fr 1.5fr 0.8fr;
      gap: 6px;
      background: #f8fafb;
      border-top: 4px solid #b08b32;
      padding: 6px;
    }}
    .sticky-signal-summary.call {{ border-top-color: #247451; }}
    .sticky-signal-summary.put {{ border-top-color: #a94747; }}
    .sticky-signal-summary.wait {{ border-top-color: #b08b32; }}
    .sticky-signal-summary > div {{
      min-width: 0;
      border-left: 3px solid #b9c4cc;
      background: white;
      padding: 7px 9px;
    }}
    .sticky-signal-summary .sticky-mode {{
      display: flex;
      flex-direction: column;
      align-items: flex-start;
      justify-content: center;
      border-left: 0;
      background: #b08b32;
      color: white;
      min-height: 52px;
      font-size: 38px;
      font-weight: bold;
      text-align: left;
      letter-spacing: 0;
    }}
    .sticky-signal-summary .sticky-mode strong {{
      margin: 0;
      color: inherit;
      font-size: inherit;
      line-height: 1.12;
      text-align: left;
    }}
    .sticky-signal-summary .sticky-mode small {{
      display: block;
      max-width: 900px;
      margin-top: 8px;
      color: inherit;
      font-size: 14px;
      font-weight: bold;
      line-height: 1.35;
      text-align: center;
    }}
    .sticky-signal-summary.call .sticky-mode {{ background: #247451; color: white; }}
    .sticky-signal-summary.put .sticky-mode {{ background: #a94747; color: white; }}
    .sticky-signal-summary span {{
      display: block;
      color: #66727c;
      font-size: 10px;
      font-weight: bold;
      text-transform: uppercase;
    }}
    .sticky-signal-summary strong {{
      display: block;
      margin-top: 4px;
      font-size: 20px;
      overflow-wrap: anywhere;
    }}
    .sticky-context strong {{ font-size: 13px; line-height: 1.3; }}
    .sticky-price {{ text-align: right; }}
    .sticky-price strong {{ font-size: 25px; }}
    .sticky-price small {{ display: block; margin-top: 2px; color: #66727c; font-size: 10px; }}
    .sticky-signal-summary.compact {{
      grid-template-columns: minmax(210px, 1.5fr) minmax(120px, .7fr) minmax(190px, 1fr) minmax(90px, .45fr) minmax(90px, .45fr);
      align-items: stretch;
    }}
    .sticky-signal-summary.compact .sticky-mode {{ min-height: 46px; font-size: 24px; }}
    .sticky-signal-summary.compact .sticky-price,
    .sticky-signal-summary.compact .sticky-feed,
    .sticky-signal-summary.compact .sticky-score,
    .sticky-signal-summary.compact .sticky-version {{
      display: flex;
      flex-direction: column;
      justify-content: center;
      text-align: left;
    }}
    .sticky-signal-summary.compact .sticky-price strong {{ font-size: 22px; }}
    .sticky-signal-summary.compact .sticky-feed strong,
    .sticky-signal-summary.compact .sticky-score strong,
    .sticky-signal-summary.compact .sticky-version strong {{ font-size: 14px; }}
    .sticky-signal-summary.compact small {{ display: block; margin-top: 3px; color: #66727c; font-size: 10px; }}
    .header-details-below {{
      display: grid;
      grid-template-columns: minmax(260px, 1.4fr) minmax(0, 2fr);
      gap: 8px;
      margin: 8px 0 10px;
      border: 1px solid #d7dfe5;
      background: white;
      padding: 9px 11px;
    }}
    .header-details-below .sticky-context span,
    .header-details-below .sticky-context small {{ display: block; color: #66727c; font-size: 10px; }}
    .header-details-below .sticky-context strong {{ display: block; margin: 3px 0; font-size: 12px; }}
    .header-details-below .sticky-pills {{ margin: 0; align-content: center; justify-content: flex-end; }}
    .header-details-below .no-trade-warning {{ grid-column: 1 / -1; margin: 0; }}
    .sticky-pills {{
      display: flex;
      flex-wrap: wrap;
      gap: 5px;
      padding: 0 6px 6px;
      background: #f8fafb;
    }}
    .sticky-pills span {{
      background: #edf1f4;
      border: 1px solid #d7dfe5;
      border-radius: 12px;
      color: #596774;
      padding: 3px 8px;
      font-size: 10px;
      white-space: nowrap;
    }}
    .trend-override-banner {{
      display: none;
      background: #dcfce7;
      border: 1px solid #22c55e;
      color: #166534;
      font-weight: 800;
      padding: 5px 10px;
      text-align: center;
    }}
    .trend-override-banner.visible {{ display: block; }}
    .no-trade-warning {{
      border-left: 5px solid #a94747;
      background: #f4dddd;
      color: #6b2929;
      padding: 5px 9px;
      text-align: left;
    }}
    .no-trade-warning strong {{ font-size: 11px; }}
    .no-trade-warning p {{ display: inline; margin-left: 6px; font-size: 10px; }}
    .data-stale-warning {{
      display: none;
      background: #b91c1c;
      color: white;
      padding: 12px 16px;
      font-weight: 800;
      text-align: center;
    }}
    .data-stale-warning.visible {{ display: block; }}
    .mobile-collapsible > summary {{
      cursor: pointer;
      border: 1px solid #d7dfe5;
      background: #f4f7fa;
      padding: 9px 11px;
      color: #33414c;
      font-size: 12px;
      font-weight: 800;
    }}
    @media (min-width: 769px) {{
      .mobile-collapsible > summary {{ display: none; }}
      .mobile-collapsible:not([open]) > .header-details-below {{ display: grid; }}
      .mobile-collapsible:not([open]) > .top-confluence-checklist {{ display: block; }}
      .mobile-collapsible:not([open]) > .time-discipline-card {{ display: grid; }}
    }}
    .time-discipline-card {{
      display: grid;
      grid-template-columns: minmax(300px, 1fr) minmax(280px, auto) max-content;
      gap: 16px;
      align-items: center;
      background: white;
      border-left: 7px solid #2474c6;
      box-shadow: 0 2px 10px rgba(31, 45, 61, 0.12);
      padding: 14px 18px;
      margin: 10px 0;
    }}
    .time-discipline-card span {{ display: block; color: #5d6872; font-size: 12px; }}
    .time-discipline-card strong {{ display: block; font-size: 18px; line-height: 1.3; }}
    .time-discipline-card p {{ margin: 4px 0 0; line-height: 1.4; }}
    .time-discipline-session {{
      min-width: 0;
      overflow-wrap: normal;
      word-break: normal;
    }}
    .time-discipline-card.caution {{ background: #fff7d6; border-left-color: #d6a400; }}
    .time-discipline-card.no-new {{ background: #ffe4c7; border-left-color: #e56b00; }}
    .time-discipline-card.close-only {{ background: #ffd6d6; border-left-color: #c1121f; }}
    .time-discipline-card.closed {{ background: #e5e7eb; border-left-color: #596774; }}
    .time-discipline-clock {{
      min-width: 0;
      text-align: right;
      white-space: nowrap;
      overflow-wrap: normal;
      word-break: normal;
    }}
    #enable-sound-alerts {{
      border: 0;
      background: #172a3a;
      color: white;
      padding: 10px 12px;
      font-weight: bold;
      cursor: pointer;
      white-space: nowrap;
    }}
    .no-trade-warning strong {{
      display: inline;
      font-size: 11px;
    }}
    .no-trade-warning p {{
      display: inline;
      margin: 0 0 0 6px;
      font-size: 10px;
      font-weight: bold;
    }}
    .education-box {{
      margin-top: 7px;
      font-size: 12px;
      text-transform: none;
    }}
    .education-box summary {{
      display: inline-block;
      cursor: pointer;
      color: #2474c6;
      font-size: 11px;
      font-weight: bold;
      text-decoration: underline;
      text-transform: none;
    }}
    .education-box summary::marker {{ display: none; }}
    .education-box p {{
      margin: 7px 0 0 !important;
      border: 1px solid #d9e1e8 !important;
      background: #f7f9fb;
      color: #37424b !important;
      padding: 8px;
      font-size: 12px;
      font-weight: normal;
      line-height: 1.4;
      text-transform: none;
    }}
    .sticky-mode .education-box summary {{ color: inherit; }}
    .sticky-mode .education-box p {{ color: #17202a !important; text-align: left; }}
    .top-education-guides {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px 14px;
      margin: 8px 0;
      padding: 8px 10px;
      background: white;
      border: 1px solid #d9e1e8;
    }}
    .top-education-guides .education-box {{ margin: 0; }}
    .trade-risk-meter {{
      display: grid;
      grid-template-columns: minmax(220px, 1fr) minmax(180px, 0.6fr);
      gap: 10px;
      margin: 8px 0;
      border: 2px solid #d9e1e8;
      background: white;
      padding: 12px;
    }}
    .pre-market-panel {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
      margin: 8px 0;
      border: 2px solid #75808a;
      background: white;
      padding: 12px;
    }}
    .pre-market-panel.bullish {{ border-color: #137a4b; }}
    .pre-market-panel.bearish {{ border-color: #b83a3a; }}
    .pre-market-panel.neutral {{ border-color: #a8831d; }}
    .pre-market-panel > div {{ border: 1px solid #d9e1e8; padding: 10px; }}
    .pre-market-panel span {{
      display: block;
      color: #66727c;
      font-size: 11px;
      font-weight: bold;
      text-transform: uppercase;
    }}
    .pre-market-panel strong {{ display: block; margin-top: 4px; font-size: 22px; }}
    .pre-market-panel p {{ margin: 6px 0 0; color: #37424b; line-height: 1.4; }}
    .pre-market-panel.bullish strong {{ color: #137a4b; }}
    .pre-market-panel.bearish strong {{ color: #b83a3a; }}
    .pre-market-panel.neutral strong {{ color: #a8831d; }}
    .pre-market-panel > details {{ grid-column: 1 / -1; }}
    .trade-risk-heading,
    .trade-risk-time {{
      padding: 12px;
      border: 1px solid rgba(0, 0, 0, 0.12);
    }}
    .trade-risk-heading span,
    .trade-risk-time span {{
      display: block;
      font-size: 11px;
      font-weight: bold;
      text-transform: uppercase;
    }}
    .trade-risk-heading strong {{
      display: block;
      margin-top: 4px;
      font-size: 28px;
    }}
    .trade-risk-heading p {{ margin: 6px 0 0; font-weight: bold; }}
    .trade-risk-time strong {{ display: block; margin-top: 6px; font-size: 18px; }}
    .trade-risk-meter.low {{ border-color: #137a4b; }}
    .trade-risk-meter.low .trade-risk-heading {{ background: #dff5e5; color: #174c2a; }}
    .trade-risk-meter.moderate {{ border-color: #c49a26; }}
    .trade-risk-meter.moderate .trade-risk-heading {{ background: #fff3c4; color: #634a00; }}
    .trade-risk-meter.high {{ border-color: #d87500; }}
    .trade-risk-meter.high .trade-risk-heading {{ background: #ffe0b2; color: #723d00; }}
    .trade-risk-meter.no-trade {{ border-color: #b83a3a; }}
    .trade-risk-meter.no-trade .trade-risk-heading {{ background: #ffd6d6; color: #6e1111; }}
    .trade-risk-meter > details {{
      grid-column: 1 / -1;
      border-top: 1px solid #d9e1e8;
      padding-top: 8px;
    }}
    .trade-risk-meter > details > summary {{ cursor: pointer; font-weight: bold; }}
    .trade-risk-meter ul {{ margin: 10px 0; color: #37424b; }}
    .risk-input-grid {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 8px;
    }}
    .risk-input-grid > * {{
      border: 1px solid #d9e1e8;
      padding: 7px;
    }}
    .risk-input-grid span {{ color: #66727c; font-size: 11px; }}
    .time-window-guide {{
      margin: 10px 0 0;
      color: #4d5963;
      font-size: 12px;
      line-height: 1.45;
    }}
    .sticky-signal-summary p {{
      margin: 4px 0 0;
      color: #37424b;
      font-size: 12px;
      line-height: 1.3;
      overflow-wrap: anywhere;
    }}
    .signal-explanation {{
      margin-top: 8px;
      padding: 14px 18px;
      background: white;
      border: 1px solid #d9e1e8;
      border-left: 6px solid #a8831d;
      border-radius: 6px;
    }}
    .signal-explanation.call {{ border-left-color: #137a4b; }}
    .signal-explanation.put {{ border-left-color: #b83a3a; }}
    .signal-explanation.wait {{ border-left-color: #a8831d; }}
    .signal-explanation h2 {{ margin: 0 0 8px; font-size: 17px; }}
    .signal-explanation ul {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px 18px;
      margin: 0;
      padding-left: 20px;
      color: #37424b;
      line-height: 1.5;
    }}
    .signal-explanation p {{
      margin: 10px 0 0;
      padding-top: 9px;
      border-top: 1px solid #e2e7eb;
      color: #4d5963;
      line-height: 1.45;
    }}
    .chart-brief {{
      margin-top: 8px;
      padding: 14px;
      background: white;
      border: 1px solid #d9e1e8;
      border-left: 6px solid #a8831d;
      border-radius: 6px;
    }}
    .chart-brief.call {{ border-left-color: #137a4b; }}
    .chart-brief.put {{ border-left-color: #b83a3a; }}
    .top-market-state {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
      margin-bottom: 10px;
    }}
    .top-market-state > div {{
      border: 1px solid #e1e6ea;
      border-left: 5px solid #75808a;
      padding: 12px;
    }}
    .top-market-state span {{
      display: block;
      color: #66727c;
      font-size: 11px;
      font-weight: bold;
      text-transform: uppercase;
    }}
    .top-market-state strong {{
      display: block;
      margin-top: 5px;
      font-size: 22px;
    }}
    .top-regime.trending-up, .top-stability.high {{ border-left-color: #137a4b; }}
    .top-regime.trending-down, .top-stability.low {{ border-left-color: #b83a3a; }}
    .top-regime.choppy, .top-regime.reversal-risk,
    .top-stability.medium {{ border-left-color: #a8831d; }}
    .top-stability-warning {{
      margin: 8px 0 0 !important;
      color: #b83a3a !important;
      font-weight: bold;
    }}
    .brief-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
    }}
    .brief-grid > div {{
      border: 1px solid #e1e6ea;
      padding: 12px;
    }}
    .brief-grid span {{
      display: block;
      color: #66727c;
      font-size: 11px;
      font-weight: bold;
      text-transform: uppercase;
    }}
    .brief-grid strong {{ display: block; margin-top: 5px; font-size: 18px; }}
    .brief-grid p {{ margin: 5px 0 0; color: #37424b; line-height: 1.45; }}
    .brief-grid .bullish {{ border-left: 4px solid #137a4b; }}
    .brief-grid .bearish {{ border-left: 4px solid #b83a3a; }}
    .brief-grid .support-level {{ border-left: 4px solid #137a4b; }}
    .brief-grid .resistance-level {{ border-left: 4px solid #b83a3a; }}
    .direction-levels {{
      display: grid;
      gap: 0;
      overflow: hidden;
      padding: 0 !important;
    }}
    .direction-levels.bullish-levels {{
      border: 1px solid #9bcdb2;
      background: #f3fbf6;
    }}
    .direction-levels.bearish-levels {{
      border: 1px solid #dfaaaa;
      background: #fff6f6;
    }}
    .direction-levels-heading {{
      padding: 14px 16px;
      font-size: 13px;
      font-weight: bold;
      text-transform: uppercase;
    }}
    .direction-levels.bullish-levels > .direction-levels-heading {{
      color: #0f633d;
      background: #e6f5ec;
    }}
    .direction-levels.bearish-levels > .direction-levels-heading {{
      color: #912d2d;
      background: #fde9e9;
    }}
    .level-status-badge {{
      padding: 12px 16px;
      color: white;
      font-size: 15px;
      font-weight: bold;
      text-align: center;
      letter-spacing: 0;
    }}
    .level-status-badge.bullish-status {{ background: #137a4b; }}
    .level-status-badge.bearish-status {{ background: #b83a3a; }}
    .direction-level {{
      display: grid;
      grid-template-columns: 112px 120px 90px minmax(0, 1fr);
      gap: 12px;
      align-items: center;
      border-top: 1px solid rgba(70, 84, 95, 0.16);
      border-left: 7px solid transparent;
      margin: 0;
      padding: 14px 16px;
      transition: opacity 160ms ease, box-shadow 160ms ease, transform 160ms ease;
    }}
    .direction-level strong {{
      margin: 0;
      font-size: 24px;
      font-variant-numeric: tabular-nums;
    }}
    .direction-level b {{ color: #27323a; font-size: 15px; }}
    .direction-level p {{ margin: 0; color: #37424b; }}
    .direction-level .level-status-text {{
      justify-self: start;
      border: 1px solid currentColor;
      border-radius: 3px;
      padding: 3px 6px;
      font-size: 10px;
      font-weight: bold;
    }}
    .direction-level.waiting-level {{
      background: #e5e7eb !important;
      color: #6b7280 !important;
      border-left: 6px solid #9ca3af !important;
      opacity: 0.55 !important;
    }}
    .direction-level.waiting-level b,
    .direction-level.waiting-level p,
    .direction-level.waiting-level .level-status-text,
    .direction-level.waiting-level strong {{
      color: #6b7280 !important;
    }}
    .direction-level.active-bull-level {{
      background: #b7f7c4 !important;
      color: #063b16 !important;
      border-left: 6px solid #0f9d3f !important;
      box-shadow: inset 0 0 0 3px #0f9d3f, 0 5px 15px rgba(15, 157, 63, 0.24);
      font-weight: 800;
      opacity: 1 !important;
    }}
    .direction-level.done-bull-level {{
      background: #dff5e5 !important;
      color: #2f6b3f !important;
      border-left-color: #65a878 !important;
      opacity: 0.75 !important;
    }}
    .direction-level.active-bear-level {{
      background: #ffc4c4 !important;
      color: #5c0000 !important;
      border-left: 6px solid #d00000 !important;
      box-shadow: inset 0 0 0 3px #d00000, 0 5px 15px rgba(208, 0, 0, 0.22);
      font-weight: 800;
      opacity: 1 !important;
    }}
    .direction-level.done-bear-level {{
      background: #f5dddd !important;
      color: #7a3333 !important;
      border-left-color: #b97878 !important;
      opacity: 0.75 !important;
    }}
    .direction-level.active-bull-level b,
    .direction-level.active-bull-level p {{ color: #063b16; }}
    .direction-level.done-bull-level b,
    .direction-level.done-bull-level p {{ color: #2f6b3f; }}
    .direction-level.active-bear-level b,
    .direction-level.active-bear-level p {{ color: #5c0000; }}
    .direction-level.done-bear-level b,
    .direction-level.done-bear-level p {{ color: #7a3333; }}
    .level-pulse {{ animation: pulseLevel 0.8s ease-in-out; }}
    .level-glow {{ animation: levelGlow 2s ease-in-out infinite; }}
    .level-fade-done {{ transition: background-color 2s ease, opacity 2s ease; }}
    .correction-monitor {{
      border-left: 6px solid #2474c6;
      background: #eef5fc;
      padding: 14px 16px;
    }}
    .correction-monitor strong {{ display: block; font-size: 20px; margin: 4px 0; }}
    .correction-monitor p {{ margin: 4px 0; }}
    .correction-overlay-bull {{ outline: 3px solid #16a34a; outline-offset: -3px; }}
    .correction-overlay-bear {{ outline: 3px solid #dc2626; outline-offset: -3px; }}
    @keyframes pulseLevel {{
      0% {{ transform: scale(1); }}
      50% {{ transform: scale(1.025); box-shadow: 0 0 0 5px rgba(36, 116, 198, 0.22); }}
      100% {{ transform: scale(1); }}
    }}
    @keyframes levelGlow {{
      0%, 100% {{ filter: brightness(1); }}
      50% {{ filter: brightness(1.12); box-shadow: 0 0 18px currentColor; }}
    }}
    .direction-level.bullish-trigger,
    .direction-level.bullish-confirmation,
    .direction-level.bullish-breakout,
    .direction-level.bearish-trigger,
    .direction-level.bearish-confirmation,
    .direction-level.bearish-breakdown {{
      background: #e5e7eb;
      color: #6b7280;
      border-left-color: #9ca3af;
    }}
    .what-next {{
      grid-column: 1 / -1;
      border: 1px solid #a9c8e8 !important;
      border-left: 5px solid #2474c6 !important;
      background: #f3f8fd;
    }}
    .what-next p {{
      border-top: 1px solid #e7ebee;
      padding-top: 8px;
    }}
    .what-next .next-bullish {{ color: #137a4b; }}
    .what-next .next-bearish {{ color: #b83a3a; }}
    .what-next .next-chop {{ color: #a06f00; }}
    .level-debug {{
      grid-column: 1 / -1;
      border: 1px solid #9ca3af;
      background: #f8fafc;
      padding: 10px;
    }}
    .level-debug summary {{
      cursor: pointer;
      color: #334155;
      font-weight: bold;
    }}
    .level-debug-grid {{
      display: grid;
      grid-template-columns: minmax(150px, 0.5fr) minmax(0, 1fr);
      gap: 5px 12px;
      margin-top: 10px;
      font-family: Consolas, monospace;
      font-size: 12px;
    }}
    .replay-summary-grid, .replay-grade-grid {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
      margin: 14px 0;
    }}
    .replay-summary-grid > div, .replay-grade-grid > div {{
      background: #f4f7fa;
      border-left: 4px solid #2474c6;
      padding: 12px;
    }}
    .replay-summary-grid span {{ display: block; color: #5d6872; font-size: 12px; }}
    .replay-summary-grid strong, .replay-grade-grid strong {{ display: block; font-size: 20px; }}
    .replay-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px;
    }}
    .replay-grid article {{ border-top: 3px solid #8aa4bd; padding: 10px 2px; }}
    .replay-grid h3 {{ margin: 0 0 8px; }}
    .daily-recap {{ grid-column: 1 / -1; }}
    .daily-recap-grid, .midpoint-grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
    }}
    .daily-recap-grid > div, .midpoint-grid > div {{
      background: #f4f7fa;
      border-left: 4px solid #8aa4bd;
      padding: 10px;
    }}
    .daily-recap-grid span, .midpoint-grid span {{ display: block; color: #66727c; font-size: 11px; }}
    .daily-midpoint {{ background: white; padding: 14px 18px; margin: 10px 0; }}
    .daily-midpoint h2 small {{
      margin-left: 6px;
      color: #7a6670;
      font-size: 11px;
      font-weight: bold;
      text-transform: uppercase;
    }}
    .daily-midpoint-warning {{
      margin: 10px 0;
      border-left: 5px solid #c98b00;
      background: #fff3c4;
      color: #6f4d00;
      padding: 10px 12px;
    }}
    .daily-midpoint-warning strong {{ display: block; margin-bottom: 4px; }}
    .daily-midpoint-warning p, .daily-midpoint-warning ul {{ margin: 5px 0; }}
    .daily-midpoint-debug {{
      margin-top: 12px;
      border: 1px solid #d9e1e8;
      background: #f8fafb;
    }}
    .daily-midpoint-debug summary {{ cursor: pointer; padding: 10px; font-weight: bold; }}
    .daily-midpoint-debug .midpoint-grid {{ padding: 0 10px 10px; }}
    .daily-midpoint-debug strong {{ overflow-wrap: anywhere; }}
    .intraday-midpoints {{
      background: white;
      border-left: 5px solid #2474c6;
      padding: 14px 18px;
      margin: 10px 0;
    }}
    .intraday-midpoint-grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
    }}
    .intraday-midpoint-card {{
      border: 1px solid #d9e1e8;
      background: #f8fafb;
      padding: 10px;
    }}
    .intraday-midpoint-card h3 {{ margin: 0 0 8px; font-size: 13px; }}
    .intraday-midpoint-values {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 6px;
    }}
    .intraday-midpoint-values > div {{ background: white; padding: 7px; }}
    .intraday-midpoint-values span {{ display: block; color: #66727c; font-size: 10px; }}
    .intraday-midpoint-values strong {{ display: block; margin-top: 3px; font-size: 15px; }}
    .trend-box-grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
      margin-top: 14px;
    }}
    .trend-box-grid > div {{
      background: #f4f7fa;
      border-left: 4px solid #2474c6;
      padding: 12px;
    }}
    .trend-box-grid span {{ display: block; color: #66727c; font-size: 11px; }}
    .trend-box-grid strong {{ display: block; margin-top: 4px; font-size: 17px; }}
    .market-box-grid {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
      margin-top: 12px;
    }}
    .market-box-grid > div {{
      background: #f4f7fa;
      border-left: 4px solid #596774;
      padding: 12px;
    }}
    .market-box-grid span, .market-box-status span {{
      display: block;
      color: #66727c;
      font-size: 11px;
    }}
    .market-box-grid strong, .market-box-status strong {{ display: block; margin-top: 4px; }}
    .market-box-status {{ padding: 12px; border-left: 6px solid #596774; background: #f1f3f5; }}
    .market-box-status.balanced {{ border-left-color: #c98b00; background: #fff5d9; }}
    .market-structure-summary {{ margin-top: 14px; border-top: 1px solid #d9e1e8; padding-top: 10px; }}
    .market-structure-summary p {{ margin: 5px 0; }}
    .confluence-checklist {{
      background: white;
      padding: 14px 18px;
      margin: 10px 0;
    }}
    .trade-decision-meter {{
      background: white;
      border-left: 7px solid #c98b00;
      padding: 14px 18px;
      margin: 10px 0;
    }}
    .trade-decision-meter.bullish {{ border-left-color: #137a4b; }}
    .trade-decision-meter.bearish {{ border-left-color: #b83a3a; }}
    .ai-paper-benchmark {{
      background: white;
      border: 1px solid #d7dfe5;
      border-left: 7px solid #2474c6;
      box-shadow: 0 2px 10px rgba(31, 45, 61, 0.10);
      margin: 10px 0;
      padding: 16px 18px;
    }}
    .benchmark-heading {{
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 18px;
    }}
    .benchmark-heading h2 {{ margin: 3px 0 5px; }}
    .benchmark-heading p {{ margin: 0; color: #596774; }}
    .benchmark-heading span, .benchmark-summary-grid span,
    .benchmark-position-grid span, .benchmark-status span {{
      display: block;
      color: #66727c;
      font-size: 11px;
    }}
    .benchmark-status {{
      min-width: 165px;
      border-left: 5px solid #2474c6;
      background: #edf5ff;
      padding: 10px 12px;
    }}
    .benchmark-status.milestone {{ border-left-color: #137a4b; background: #e9f7ef; }}
    .benchmark-status.failed {{ border-left-color: #b83a3a; background: #fde9e9; }}
    .benchmark-status strong {{ display: block; margin: 4px 0; }}
    .benchmark-summary-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(145px, 1fr));
      gap: 8px;
      margin-top: 14px;
    }}
    .benchmark-summary-grid > div, .benchmark-position-grid > div {{
      min-width: 0;
      background: #f4f7fa;
      padding: 10px;
    }}
    .benchmark-summary-grid strong {{
      display: block;
      margin-top: 5px;
      font-size: 17px;
      overflow-wrap: anywhere;
    }}
    .benchmark-position-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
      margin-top: 10px;
    }}
    .benchmark-position-grid strong {{
      display: block;
      margin-top: 5px;
      line-height: 1.4;
      overflow-wrap: anywhere;
    }}
    .benchmark-equity-panel {{
      margin-top: 12px;
      border: 1px solid #d7dfe5;
      padding: 10px;
      overflow: hidden;
    }}
    .benchmark-equity-panel h3 {{ margin: 0 0 8px; }}
    .benchmark-equity-curve {{ display: block; width: 100%; height: auto; }}
    .benchmark-equity-curve line {{ stroke: #aab5bf; stroke-width: 1; }}
    .benchmark-equity-curve polyline {{
      fill: none;
      stroke: #2474c6;
      stroke-width: 3;
      stroke-linejoin: round;
      stroke-linecap: round;
    }}
    .benchmark-equity-curve text {{ fill: #66727c; font-size: 11px; }}
    .benchmark-equity-empty {{ color: #66727c; padding: 18px; text-align: center; }}
    .benchmark-win {{ color: #137a4b; font-weight: bold; }}
    .benchmark-loss {{ color: #b83a3a; font-weight: bold; }}
    .ai-paper-benchmark details {{ margin-top: 12px; }}
    .decision-meter-heading, .decision-meter-scores {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
    }}
    .decision-meter-heading > div, .decision-meter-scores > div {{
      background: #f4f7fa;
      padding: 10px;
    }}
    .decision-meter-heading span {{
      display: block;
      color: #66727c;
      font-size: 11px;
    }}
    .decision-meter-heading strong {{
      display: block;
      margin-top: 4px;
      font-size: 19px;
    }}
    .decision-meter-scale {{
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 5px;
      margin: 15px 0;
      color: #66727c;
      font-size: 11px;
      text-align: center;
    }}
    .decision-meter-scale span:first-child {{ text-align: left; color: #b83a3a; }}
    .decision-meter-scale span:last-child {{ text-align: right; color: #137a4b; }}
    .decision-meter-track {{
      position: relative;
      grid-column: 1 / -1;
      height: 10px;
      background: linear-gradient(90deg, #d96b6b, #e5e7eb 50%, #57b982);
      border-radius: 5px;
    }}
    .decision-meter-track i {{
      position: absolute;
      top: -5px;
      width: 4px;
      height: 20px;
      background: #17212b;
      border-radius: 2px;
      transform: translateX(-50%);
      transition: left 0.3s ease;
    }}
    .decision-meter-scores {{
      grid-template-columns: repeat(3, minmax(0, 1fr));
    }}
    .decision-meter-scores strong {{ display: block; margin-top: 4px; font-size: 17px; }}
    .confluence-summary {{
      padding: 14px;
      border-left: 6px solid #c98b00;
      background: #fff5d9;
    }}
    .confluence-summary.bullish {{ border-left-color: #137a4b; background: #e9f7ef; }}
    .confluence-summary.bearish {{ border-left-color: #b83a3a; background: #fde9e9; }}
    .confluence-summary span {{ display: block; color: #66727c; font-size: 11px; }}
    .confluence-summary strong {{ display: block; margin-top: 4px; font-size: 20px; }}
    .confluence-summary p {{ margin: 6px 0 0; }}
    .confluence-scores {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
      margin: 12px 0;
    }}
    .confluence-scores > div {{ background: #f4f7fa; padding: 10px; }}
    .confluence-scores strong {{ display: block; margin-top: 4px; font-size: 17px; }}
    .confluence-factors {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 7px;
      margin-top: 10px;
    }}
    .confluence-factor {{
      display: flex;
      justify-content: space-between;
      gap: 10px;
      padding: 9px;
      background: #f1f3f5;
    }}
    .confluence-factor.bullish {{ border-left: 4px solid #137a4b; }}
    .confluence-factor.bearish {{ border-left: 4px solid #b83a3a; }}
    .confluence-factor.conflict {{ border-left: 4px solid #c98b00; }}
    .confluence-factor.neutral {{ border-left: 4px solid #8a8f98; }}
    .historical-archive {{ display: grid; gap: 8px; }}
    .archive-day {{
      border: 1px solid #d9e1e8;
      background: white;
    }}
    .archive-day > summary {{
      cursor: pointer;
      padding: 11px 13px;
      background: #f4f7fa;
      font-weight: bold;
    }}
    .archive-day[open] > summary {{ border-bottom: 1px solid #d9e1e8; }}
    .archive-day > :not(summary) {{ margin-left: 13px; margin-right: 13px; }}
    .archive-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
      margin-top: 12px;
    }}
    .archive-grid > div {{ background: #f7f9fb; padding: 10px; }}
    .archive-grid h3, .archive-grid p {{ margin: 3px 0; }}
    .a-plus-filter {{
      display: grid;
      grid-template-columns: 0.7fr 0.8fr 2.5fr;
      gap: 10px;
      background: white;
      border-left: 7px solid #c98b00;
      padding: 14px 18px;
      margin: 10px 0;
    }}
    .a-plus-filter.yes {{ border-left-color: #137a4b; background: #e9f7ef; }}
    .a-plus-filter.no {{ border-left-color: #c98b00; background: #fff5d9; }}
    .a-plus-filter > div {{ padding: 8px; background: rgba(255, 255, 255, 0.62); }}
    .a-plus-filter span {{ display: block; color: #66727c; font-size: 11px; }}
    .a-plus-filter strong {{ display: block; margin-top: 4px; }}
    .a-plus-filter > div:first-child strong {{ font-size: 24px; }}
    .level-debug-grid span {{ color: #64748b; }}
    .level-debug-grid strong {{ color: #0f172a; overflow-wrap: anywhere; }}
    .live-stale-warning {{
      color: #b83a3a !important;
      font-weight: bold;
    }}
    .live-status-path {{
      overflow-wrap: anywhere;
      color: #66727c !important;
      font-size: 12px;
    }}
    .age-fresh {{
      color: #137a4b !important;
      font-weight: bold;
    }}
    .age-yellow {{
      background: #fff3c4;
      color: #8a6100 !important;
      font-weight: bold;
      padding: 4px 6px;
    }}
    .age-red {{
      background: #fff0f0;
      color: #b83a3a !important;
      font-weight: bold;
      padding: 4px 6px;
    }}
    .levels-stale-warning {{
      color: #b83a3a !important;
      font-weight: bold;
    }}
    .levels-corrected-warning {{
      background: #fff3c4;
      border-left: 4px solid #c98b00;
      color: #805900 !important;
      font-weight: bold;
      padding: 7px 9px;
    }}
    .support-resistance-details {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
      margin-top: 18px;
    }}
    .support-resistance-details > div {{
      border: 1px solid #e1e6ea;
      padding: 14px;
    }}
    .support-detail {{ border-left: 5px solid #137a4b !important; }}
    .resistance-detail {{ border-left: 5px solid #b83a3a !important; }}
    .support-resistance-details span {{
      display: block;
      color: #66727c;
      font-size: 11px;
      font-weight: bold;
      text-transform: uppercase;
    }}
    .support-resistance-details strong {{
      display: block;
      margin-top: 5px;
      font-size: 24px;
    }}
    .sr-price {{
      width: fit-content;
      padding: 4px 7px;
      border-radius: 4px;
      transition: background-color 0.3s ease, color 0.3s ease, box-shadow 0.3s ease;
    }}
    .sr-price.near-level {{
      background: #fff0b8;
      color: #674900;
      box-shadow: 0 0 0 2px rgba(201, 139, 0, 0.18);
    }}
    .sr-kind {{
      display: block;
      margin-top: 7px;
      color: #66727c !important;
      font-size: 11px !important;
      font-weight: bold;
      text-transform: uppercase;
    }}
    .sr-description {{
      margin-top: 8px;
      color: #66727c;
      font-size: 12px;
    }}
    .sr-description summary {{
      width: fit-content;
      color: #596774;
      cursor: pointer;
      font-size: 11px;
      font-weight: bold;
      text-transform: uppercase;
    }}
    .sr-description p {{
      color: #66727c !important;
      font-size: 12px;
      margin: 7px 0;
    }}
    .support-resistance-details p {{
      color: #37424b;
      line-height: 1.45;
    }}
    .level-ladder p {{
      display: grid;
      grid-template-columns: 72px 1fr;
      gap: 8px;
      align-items: baseline;
      border-top: 1px solid #e7ebee;
      padding-top: 7px;
    }}
    .level-ladder p:first-of-type {{ border-top: 0; }}
    .level-ladder p strong {{ font-size: 16px; }}
    .chart-reading-details {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
      margin-top: 18px;
    }}
    .chart-reading-details > div {{
      border: 1px solid #e1e6ea;
      padding: 12px;
    }}
    .chart-reading-details span {{
      display: block;
      color: #66727c;
      font-size: 11px;
      font-weight: bold;
      text-transform: uppercase;
    }}
    .chart-reading-details strong {{
      display: block;
      margin-top: 5px;
      font-size: 18px;
    }}
    .chart-reading-details p {{
      margin: 5px 0 0;
      color: #37424b;
      line-height: 1.45;
    }}
    .regime-label {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      margin-top: 8px;
      padding: 12px 16px;
      color: white;
      border-radius: 6px;
    }}
    .regime-label span {{ font-size: 12px; text-transform: uppercase; }}
    .regime-label strong {{ font-size: 20px; }}
    .regime-label.trending-up {{ background: #137a4b; }}
    .regime-label.trending-down {{ background: #b83a3a; }}
    .regime-label.choppy {{ background: #596774; }}
    .regime-label.reversal-risk {{ background: #a8831d; color: #171717; }}
    .stability-label {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-top: 6px;
      padding: 10px 16px;
      background: white;
      border: 1px solid #d9e1e8;
      border-left: 6px solid #8b98a3;
      border-radius: 6px;
    }}
    .stability-label.high {{ border-left-color: #137a4b; }}
    .stability-label.medium {{ border-left-color: #a8831d; }}
    .stability-label.low {{ border-left-color: #b83a3a; }}
    .stability-warning {{ color: #b83a3a; font-weight: bold; }}
    .vwap-label {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-top: 6px;
      padding: 10px 16px;
      background: white;
      border: 1px solid #d9e1e8;
      border-left: 6px solid #596774;
      border-radius: 6px;
    }}
    .vwap-label.above {{ border-left-color: #137a4b; }}
    .vwap-label.below {{ border-left-color: #b83a3a; }}
    .vwap-label.mixed {{ border-left-color: #a8831d; }}
    .opening-range-label {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-top: 6px;
      padding: 10px 16px;
      background: white;
      border: 1px solid #d9e1e8;
      border-left: 6px solid #a8831d;
      border-radius: 6px;
    }}
    .opening-range-label.above {{ border-left-color: #137a4b; }}
    .opening-range-label.below {{ border-left-color: #b83a3a; }}
    .opening-range-label.inside {{ border-left-color: #a8831d; }}
    .decision-panel {{
      color: white;
      margin-top: 10px;
      padding: 20px;
      border-radius: 6px;
    }}
    .decision-panel.call {{ background: #116b42; }}
    .decision-panel.put {{ background: #a63333; }}
    .decision-panel.wait {{ background: #b88d20; color: #151515; }}
    .decision-grid {{
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 10px;
    }}
    .decision-grid div {{
      background: rgba(255,255,255,.13);
      border: 1px solid rgba(255,255,255,.3);
      padding: 12px;
    }}
    .decision-grid span {{
      display: block;
      font-size: 11px;
      text-transform: uppercase;
    }}
    .decision-grid strong {{ display: block; margin-top: 5px; font-size: 20px; }}
    .volume-filter {{
      display: block;
      margin-top: 8px;
      padding-top: 7px;
      border-top: 1px solid rgba(255,255,255,.3);
      font-size: 12px;
      font-style: normal;
      font-weight: bold;
    }}
    .volume-filter.pass {{ color: #bff4d5; }}
    .volume-filter.fail {{ color: #ffe098; }}
    .activity-filter, .activity-average {{
      display: block;
      margin-top: 5px;
      font-size: 12px;
      font-style: normal;
      font-weight: bold;
    }}
    .activity-filter.active {{ color: #bff4d5; }}
    .activity-filter.normal {{ color: #dbe8f2; }}
    .activity-filter.slow {{ color: #ffe098; }}
    .activity-average {{ font-weight: normal; opacity: .9; }}
    .activity-warning {{
      background: rgba(255,255,255,.15);
      border-left: 4px solid #ffe098;
      padding: 9px 12px;
    }}
    .decision-panel p {{ margin: 18px 0 0; font-size: 16px; text-align: center; }}
    .position-plan {{
      margin-top: 10px;
      padding: 16px;
      background: white;
      border: 1px solid #d9e1e8;
      border-left: 5px solid #2474c6;
      border-radius: 6px;
    }}
    .stop-education {{
      margin-top: 14px;
      border-left: 5px solid #2474c6;
      background: #eef5fc;
      padding: 12px 14px;
    }}
    .stop-education strong {{ display: block; font-size: 17px; }}
    .stop-education p {{ margin: 6px 0 0; line-height: 1.45; }}
    .stop-education.clean {{ border-left-color: #137a4b; background: #e9f7ef; }}
    .stop-education.wide, .stop-education.review {{ border-left-color: #c98b00; background: #fff5d9; }}
    .stop-education.wait-stop {{ border-left-color: #596774; background: #f1f3f5; }}
    .position-plan-heading {{
      display: flex;
      align-items: start;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 12px;
    }}
    .position-plan-heading h2 {{ margin: 0; }}
    .position-plan-heading p {{ margin: 5px 0 0; color: #5d6872; }}
    .position-plan-heading label {{
      color: #5d6872;
      font-size: 12px;
      font-weight: bold;
      text-transform: uppercase;
    }}
    .position-plan-heading select {{
      display: block;
      margin-top: 5px;
      min-width: 90px;
      padding: 7px 9px;
      border: 1px solid #b8c3cc;
      background: white;
    }}
    .position-summary {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 8px;
      margin-bottom: 12px;
    }}
    .position-summary > div {{
      border: 1px solid #e1e6ea;
      padding: 10px;
    }}
    .position-summary span {{
      display: block;
      color: #66727c;
      font-size: 11px;
      font-weight: bold;
      text-transform: uppercase;
    }}
    .position-summary strong {{ display: block; margin-top: 5px; font-size: 20px; }}
    .risk-rule {{ color: #37424b; line-height: 1.45; }}
    .stop-suggestion {{
      margin-bottom: 0;
      border-left: 4px solid #a8831d;
      padding: 9px 11px;
      background: #fff9e9;
      font-weight: bold;
    }}
    .stop-suggestion.clean {{ border-left-color: #137a4b; background: #eef9f2; color: #137a4b; }}
    .stop-suggestion.wide {{ border-left-color: #b83a3a; background: #fff1f1; color: #b83a3a; }}
    .detail-section {{
      margin-top: 14px;
      background: white;
      border: 1px solid #d9e1e8;
      border-radius: 6px;
      overflow: hidden;
    }}
    .detail-section summary {{
      cursor: pointer;
      padding: 16px 18px;
      background: #e4eaf0;
      font-size: 17px;
      font-weight: bold;
      list-style-position: inside;
    }}
    .detail-section[open] summary {{ border-bottom: 1px solid #d9e1e8; }}
    .detail-content {{ padding: 0 18px 18px; }}
    .accuracy-grid {{
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 10px;
      margin-top: 18px;
    }}
    .accuracy-grid div {{ border: 1px solid #d9e1e8; padding: 14px; }}
    .accuracy-grid span {{ display: block; color: #66727c; font-size: 12px; }}
    .accuracy-grid strong {{ display: block; margin-top: 4px; font-size: 24px; }}
    .accuracy-grid .win strong {{ color: #137a4b; }}
    .accuracy-grid .loss strong {{ color: #b83a3a; }}
    .score-section {{ margin-top: 18px; }}
    .score-grid {{
      display: grid;
      grid-template-columns: repeat(7, minmax(0, 1fr));
      gap: 10px;
    }}
    .score-grid div {{ border: 1px solid #d9e1e8; padding: 12px; }}
    .score-grid span {{ display: block; color: #66727c; font-size: 11px; }}
    .score-grid strong {{ display: block; margin-top: 4px; font-size: 19px; }}
    .score-grid .total {{ border-color: #2474c6; }}
    .score-grid .total strong {{ color: #2474c6; }}
    .stability-details {{ margin-top: 18px; }}
    .stability-grid {{
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 10px;
    }}
    .stability-grid div {{ border: 1px solid #d9e1e8; padding: 12px; }}
    .stability-grid span {{ display: block; color: #66727c; font-size: 11px; }}
    .stability-grid strong {{ display: block; margin-top: 4px; font-size: 19px; }}
    .vwap-details {{ margin-top: 18px; }}
    .vwap-grid {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
    }}
    .vwap-grid div {{ border: 1px solid #d9e1e8; padding: 12px; }}
    .vwap-grid span {{ display: block; color: #66727c; font-size: 11px; }}
    .vwap-grid strong {{ display: block; margin-top: 4px; font-size: 19px; }}
    .opening-range-details {{ margin-top: 18px; }}
    .opening-range-grid {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
    }}
    .opening-range-grid div {{ border: 1px solid #d9e1e8; padding: 12px; }}
    .opening-range-grid span {{ display: block; color: #66727c; font-size: 11px; }}
    .opening-range-grid strong {{ display: block; margin-top: 4px; font-size: 19px; }}
    .regime-details {{ margin-top: 18px; }}
    .regime-details p {{ color: #4d5963; line-height: 1.5; }}
    .regime-grid {{
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 10px;
    }}
    .regime-grid div {{ border: 1px solid #d9e1e8; padding: 12px; }}
    .regime-grid span {{ display: block; color: #66727c; font-size: 11px; }}
    .regime-grid strong {{ display: block; margin-top: 4px; font-size: 20px; }}
    .breadth-section {{ margin-top: 18px; }}
    .breadth-status {{
      padding: 20px;
      color: white;
      border-radius: 6px;
    }}
    .breadth-status.bullish {{ background: #137a4b; }}
    .breadth-status.bearish {{ background: #b83a3a; }}
    .breadth-status.neutral {{ background: #596774; }}
    .breadth-status span {{ display: block; font-size: 12px; text-transform: uppercase; }}
    .breadth-status strong {{ display: block; margin-top: 5px; font-size: 30px; }}
    .breadth-grid {{
      display: grid;
      grid-template-columns: repeat(6, minmax(0, 1fr));
      gap: 10px;
      margin-top: 10px;
    }}
    .breadth-grid div {{ border: 1px solid #d9e1e8; padding: 12px; }}
    .breadth-grid span {{ display: block; color: #66727c; font-size: 11px; }}
    .breadth-grid strong {{ display: block; margin-top: 4px; font-size: 20px; }}
    .breadth-grid .bullish strong {{ color: #137a4b; }}
    .breadth-grid .bearish strong {{ color: #b83a3a; }}
    .chart-section {{ margin-top: 28px; }}
    .chart-heading {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
    }}
    .chart-legend {{ display: flex; flex-wrap: wrap; gap: 8px; }}
    .chart-legend span {{
      border-bottom: 3px solid;
      padding: 3px 5px;
      font-size: 12px;
      font-weight: bold;
    }}
    .candle-up-legend {{ color: #137a4b; border-color: #137a4b; }}
    .candle-down-legend {{ color: #b83a3a; border-color: #b83a3a; }}
    .chart-wrap {{
      overflow-x: auto;
      background: white;
      border: 1px solid #d9e1e8;
      padding: 10px;
    }}
    .chart-wrap svg {{ display: block; min-width: 760px; width: 100%; height: auto; }}
    .chart-grid {{ stroke: #dfe5ea; stroke-width: 1; }}
    .chart-axis-label {{ fill: #66727c; font-size: 11px; }}
    .chart-plan-label {{ font-size: 12px; font-weight: bold; }}
    .candle-wick {{ stroke-width: 2; }}
    .candle-wick.up {{ stroke: #137a4b; }}
    .candle-wick.down {{ stroke: #b83a3a; }}
    .candle-body.up {{ fill: #15965b; }}
    .candle-body.down {{ fill: #d34a4a; }}
    .pressure-section {{ margin-top: 28px; }}
    .note {{ color: #5d6872; margin: 0 0 14px; }}
    .pressure-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px;
    }}
    .pressure-panel {{ background: white; padding: 18px; border: 1px solid #d9e1e8; }}
    .pressure-panel h3 {{ margin: 0 0 14px; font-size: 16px; }}
    .recent-alert-pressure {{
      margin: 14px 0;
      border-top: 1px solid #d9e1e8;
      padding-top: 12px;
    }}
    .recent-alert-pressure > h3 {{ margin: 0 0 4px; font-size: 15px; }}
    .alert-pressure-windows {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 8px;
      margin-top: 8px;
    }}
    .alert-pressure-window {{
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 5px 10px;
      border-left: 5px solid #8a8f98;
      background: #f4f7fa;
      padding: 10px;
    }}
    .alert-pressure-window h3, .alert-pressure-window > strong {{ grid-column: 1 / -1; }}
    .alert-pressure-window h3 {{ margin: 0; font-size: 12px; }}
    .alert-pressure-window > strong {{ margin-bottom: 4px; }}
    .alert-pressure-window span {{ color: #66727c; font-size: 10px; }}
    .alert-pressure-window b {{ font-size: 11px; text-align: right; }}
    .alert-pressure-window.bullish {{ border-left-color: #137a4b; background: #e9f7ef; }}
    .alert-pressure-window.bearish {{ border-left-color: #b83a3a; background: #fde9e9; }}
    .alert-pressure-window.mixed {{ border-left-color: #c98b00; background: #fff6d8; }}
    .counts, .bar-label {{
      display: flex;
      justify-content: space-between;
      gap: 14px;
      margin-bottom: 10px;
      font-weight: bold;
    }}
    .bar-label {{ font-size: 13px; color: #53616c; }}
    .call-text {{ color: #137a4b; }}
    .put-text {{ color: #b83a3a; }}
    .wait-text {{ color: #9a7412; }}
    .pressure-bar {{
      display: flex;
      height: 24px;
      overflow: hidden;
      background: #d8dee4;
      border-radius: 3px;
    }}
    .call-bar {{ background: #15965b; }}
    .put-bar {{ background: #d34a4a; }}
    .engine-section {{ margin-top: 28px; }}
    .engine-grid {{
      display: grid;
      grid-template-columns: minmax(220px, .7fr) minmax(0, 1.3fr);
      gap: 14px;
      margin-bottom: 18px;
    }}
    .engine-score, .engine-counts {{
      background: white;
      border: 1px solid #d9e1e8;
      padding: 18px;
    }}
    .engine-score span, .engine-score em {{ display: block; color: #5d6872; }}
    .engine-score strong {{ display: block; margin: 5px 0; font-size: 38px; }}
    .engine-score em {{ font-style: normal; font-weight: bold; }}
    .engine-score.bullish strong, .engine-counts .bullish strong {{ color: #137a4b; }}
    .engine-score.bearish strong, .engine-counts .bearish strong {{ color: #b83a3a; }}
    .engine-score.neutral strong, .engine-counts .neutral strong {{ color: #596774; }}
    .engine-counts {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
    }}
    .engine-counts div {{ border-left: 4px solid #d9e1e8; padding: 8px 12px; }}
    .engine-counts strong {{ display: block; font-size: 30px; }}
    .engine-counts span {{ color: #5d6872; }}
    .engine-status {{
      display: inline-block;
      color: white;
      padding: 3px 7px;
      border-radius: 3px;
      font-weight: bold;
    }}
    .engine-status.bullish {{ background: #137a4b; }}
    .engine-status.bearish {{ background: #b83a3a; }}
    .engine-status.neutral {{ background: #596774; }}
    .table-wrap {{ overflow-x: auto; background: white; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{
      padding: 10px;
      border: 1px solid #d9e1e8;
      text-align: left;
      white-space: nowrap;
      font-size: 13px;
    }}
    th {{ background: #e4eaf0; }}
    tr:nth-child(even) {{ background: #f7f9fb; }}
    .tag {{ color: white; padding: 3px 7px; border-radius: 3px; font-weight: bold; }}
    .tag.call {{ background: #137a4b; }}
    .tag.put {{ background: #b83a3a; }}
    .tag.wait {{ background: #596774; }}
    .empty {{ background: white; padding: 20px; }}
    @media (max-width: 1050px) {{
      .time-discipline-card {{
        grid-template-columns: minmax(0, 1fr) max-content;
      }}
      .time-discipline-clock {{
        text-align: left;
        white-space: normal;
      }}
      #enable-sound-alerts {{
        grid-column: 1 / -1;
        justify-self: start;
      }}
    }}
    @media (max-width: 700px) {{
      main {{ padding: 14px; }}
      .sticky-signal-summary.compact {{ grid-template-columns: repeat(2, minmax(0, 1fr)); padding: 4px; gap: 4px; }}
      .sticky-signal-summary.compact .sticky-mode {{ grid-column: 1 / -1; min-height: 36px; font-size: 22px; }}
      .sticky-signal-summary.compact .sticky-feed {{ grid-column: 1 / -1; }}
      .sticky-signal-summary.compact > div {{ padding: 4px 6px; }}
      .sticky-signal-summary.compact .sticky-price strong {{ font-size: 18px; }}
      .sticky-signal-summary.compact .sticky-feed strong,
      .sticky-signal-summary.compact .sticky-score strong,
      .sticky-signal-summary.compact .sticky-version strong {{ font-size: 12px; }}
      .sticky-signal-summary .sticky-mode small {{ font-size: 12px; }}
      .sticky-signal-summary p {{ font-size: 11px; }}
      .sticky-price {{ text-align: left; }}
      .header-details-below {{ grid-template-columns: 1fr; padding: 8px; }}
      .header-details-below .sticky-pills {{ justify-content: flex-start; }}
      .sticky-pills {{ gap: 4px; }}
      .sticky-pills span {{ font-size: 9px; padding: 2px 6px; }}
      .sticky-area .decision-meter-scores {{ grid-template-columns: repeat(3, minmax(0, 1fr)); }}
      .no-trade-warning {{ padding: 4px 7px; }}
      .no-trade-warning strong {{ font-size: 10px; }}
      .no-trade-warning p {{ font-size: 9px; }}
      .education-box p {{ font-size: 11px; }}
      .top-education-guides {{ display: block; }}
      .top-education-guides .education-box {{ margin: 5px 0; }}
      .trade-risk-meter {{ grid-template-columns: 1fr; }}
      .pre-market-panel {{ grid-template-columns: 1fr; }}
      .pre-market-panel > details {{ grid-column: auto; }}
      .trade-risk-meter > details {{ grid-column: auto; }}
      .risk-input-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .mode-banner {{ min-height: 84px; }}
      .mode-banner strong {{ font-size: 30px; }}
      .signal-explanation ul {{ display: block; }}
      .brief-grid {{ grid-template-columns: 1fr; }}
      .top-market-state {{ grid-template-columns: 1fr; }}
      .direction-level {{
        grid-template-columns: 1fr;
        gap: 4px;
        padding: 14px;
      }}
      .direction-level strong {{ font-size: 26px; }}
      .direction-level p {{ grid-column: auto; }}
      .direction-level .level-status-text {{ justify-self: start; }}
      .direction-level.active-bull-level,
      .direction-level.active-bear-level {{
        transform: none;
        box-shadow: inset 0 0 0 4px currentColor;
      }}
      .level-status-badge {{
        position: sticky;
        top: 0;
        z-index: 2;
        font-size: 13px;
      }}
      .reversal-badges {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .mtf-grid {{ grid-template-columns: 1fr; }}
      .chart-reading-details {{ grid-template-columns: 1fr; }}
      .support-resistance-details {{ grid-template-columns: 1fr; }}
      .time-discipline-card {{ grid-template-columns: 1fr; gap: 10px; }}
      .time-discipline-clock {{ min-width: 0; text-align: left; white-space: normal; }}
      .time-discipline-clock strong {{ font-size: 15px; line-height: 1.35; }}
      #enable-sound-alerts {{ grid-column: auto; width: 100%; }}
      .top-confluence-checklist {{ padding: 13px; }}
      .top-confluence-heading {{ align-items: stretch; flex-direction: column; }}
      .top-confluence-final {{ min-width: 0; }}
      .top-confluence-scores {{ grid-template-columns: 1fr; }}
      .top-confluence-factors {{ grid-template-columns: 1fr; }}
      .benchmark-heading {{ flex-direction: column; }}
      .benchmark-status {{ width: 100%; min-width: 0; }}
      .benchmark-summary-grid, .benchmark-position-grid {{ grid-template-columns: 1fr; }}
      .replay-summary-grid, .replay-grade-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .replay-grid {{ grid-template-columns: 1fr; }}
      .daily-recap-grid, .midpoint-grid {{ grid-template-columns: 1fr; }}
      .intraday-midpoint-grid {{ grid-template-columns: 1fr; }}
      .trend-box-grid {{ grid-template-columns: 1fr; }}
      .market-box-grid {{ grid-template-columns: 1fr; }}
      .confluence-scores, .confluence-factors {{ grid-template-columns: 1fr; }}
      .archive-grid {{ grid-template-columns: 1fr; }}
      .decision-meter-heading {{ grid-template-columns: 1fr; }}
      .decision-meter-scores {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .a-plus-filter {{ grid-template-columns: 1fr; }}
      .level-debug-grid {{ grid-template-columns: 1fr; }}
      .position-plan-heading {{ display: block; }}
      .position-plan-heading label {{ display: block; margin-top: 12px; }}
      .position-summary {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .decision-grid, .accuracy-grid, .breadth-grid, .regime-grid, .score-grid, .stability-grid, .vwap-grid, .opening-range-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .stability-label {{ display: block; }}
      .stability-warning {{ display: block; margin-top: 5px; }}
      .opening-range-label {{ display: grid; grid-template-columns: 1fr; }}
      .pressure-grid {{ grid-template-columns: 1fr; }}
      .alert-pressure-windows {{ grid-template-columns: 1fr; }}
      .engine-grid, .engine-counts {{ grid-template-columns: 1fr; }}
      .chart-heading {{ display: block; }}
      .chart-legend {{ margin-bottom: 10px; }}
      .detail-content {{ padding: 0 10px 12px; }}
    }}
    @media (max-width: 768px) {{
      main {{ padding: 8px; }}
      .sticky-area {{
        max-height: 22vh;
        overflow-y: auto;
        margin-bottom: 6px;
      }}
      .sticky-signal-summary.compact {{
        grid-template-columns: repeat(6, minmax(0, 1fr));
        gap: 3px;
        padding: 3px;
      }}
      .sticky-signal-summary.compact > div {{
        min-height: 0;
        padding: 4px 5px;
      }}
      .sticky-signal-summary.compact .sticky-mode {{
        grid-column: 1 / 5;
        min-height: 0;
        font-size: 22px;
      }}
      .sticky-signal-summary.compact .sticky-mode strong {{
        margin-top: 1px;
        font-size: 22px;
        line-height: 1.05;
      }}
      .sticky-signal-summary.compact .sticky-price {{
        grid-column: 5 / 7;
      }}
      .sticky-signal-summary.compact .sticky-price strong {{
        margin-top: 1px;
        font-size: 20px;
        line-height: 1.05;
      }}
      .sticky-signal-summary.compact .sticky-feed {{
        grid-column: 1 / 4;
      }}
      .sticky-signal-summary.compact .sticky-score {{
        grid-column: 4 / 6;
      }}
      .sticky-signal-summary.compact .sticky-version {{
        grid-column: 6 / 7;
      }}
      .sticky-signal-summary.compact .sticky-feed > span,
      .sticky-signal-summary.compact .sticky-feed > small,
      .sticky-signal-summary.compact .sticky-version > small {{
        display: none;
      }}
      .sticky-signal-summary.compact .sticky-feed strong,
      .sticky-signal-summary.compact .sticky-score strong,
      .sticky-signal-summary.compact .sticky-version strong {{
        margin-top: 1px;
        font-size: 11px;
        line-height: 1.1;
      }}
      .sticky-signal-summary.compact span {{
        font-size: 8px;
      }}
      .data-stale-warning {{
        padding: 4px 7px;
        font-size: 10px;
      }}
      .mobile-collapsible {{
        margin: 6px 0;
      }}
      .mobile-collapsible > summary {{
        padding: 8px;
      }}
      .mobile-collapsible[open] > summary {{
        border-bottom-color: transparent;
      }}
      .header-details-below {{
        margin: 0;
        padding: 8px;
      }}
      .top-confluence-checklist {{
        margin: 0;
        padding: 10px;
      }}
      .time-discipline-card {{
        margin: 0;
        padding: 10px;
      }}
    }}
  
    /* =========================================================
       SOFT MODERN UI OVERRIDE - PHASE 1
       Visual cleanup only.
       ========================================================= */

    :root {{
      --soft-bg: #f4f7fb;
      --soft-card: #ffffff;
      --soft-border: #dbe7f3;
      --soft-text: #111827;
      --soft-muted: #64748b;
      --soft-blue: #2798ff;
      --soft-green: #16a34a;
      --soft-red: #dc2626;
      --soft-navy: #071426;
      --soft-shadow: 0 12px 30px rgba(15, 23, 42, 0.08);
      --soft-shadow-small: 0 8px 18px rgba(15, 23, 42, 0.06);
    }}

    body {{
      background:
        radial-gradient(circle at top left, rgba(39, 152, 255, 0.12), transparent 34rem),
        linear-gradient(180deg, #f8fbff 0%, #f4f7fb 45%, #edf4fb 100%) !important;
      color: var(--soft-text) !important;
      font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif !important;
      letter-spacing: -0.01em;
    }}

    h1, h2, h3 {{
      letter-spacing: -0.035em;
    }}

    h1 {{
      font-size: clamp(34px, 5vw, 62px) !important;
      line-height: 1 !important;
      font-weight: 850 !important;
    }}

    h2 {{
      font-size: clamp(22px, 3vw, 34px) !important;
      line-height: 1.08 !important;
      font-weight: 820 !important;
    }}

    p {{
      color: var(--soft-muted);
    }}

    section,
    .detail-section,
    .decision-panel,
    .position-plan,
    .score-section,
    .accuracy-section,
    .engine-section,
    .breadth-section,
    .pressure-section,
    .chart-section,
    .market-box,
    .trend-box,
    .confluence-checklist,
    .top-confluence-checklist,
    .trade-decision-meter,
    .trade-risk-meter,
    .pre-market-panel,
    .mode-banner,
    .time-discipline-card {{
      border-radius: 24px !important;
      border: 1px solid var(--soft-border) !important;
      background: rgba(255, 255, 255, 0.94) !important;
      box-shadow: var(--soft-shadow-small) !important;
    }}

    section {{
      margin-top: 18px !important;
    }}

    .detail-section {{
      overflow: hidden !important;
      margin-top: 18px !important;
    }}

    .detail-section summary {{
      min-height: 58px;
      padding: 18px 20px !important;
      background: linear-gradient(180deg, #ffffff 0%, #f8fbff 100%) !important;
      color: var(--soft-text) !important;
      font-weight: 800 !important;
      border-bottom: 1px solid transparent !important;
    }}

    .detail-section[open] summary {{
      border-bottom: 1px solid var(--soft-border) !important;
    }}

    .decision-panel {{
      padding: 28px !important;
      border: 0 !important;
      box-shadow: var(--soft-shadow) !important;
      color: white !important;
    }}

    .decision-panel h2,
    .decision-panel h3,
    .decision-panel p,
    .decision-panel span,
    .decision-panel strong {{
      color: inherit !important;
    }}

    .decision-panel.call {{
      background:
        radial-gradient(circle at top right, rgba(34, 197, 94, 0.30), transparent 18rem),
        linear-gradient(135deg, #062015, #0a3d2a 52%, #0f5132) !important;
    }}

    .decision-panel.put {{
      background:
        radial-gradient(circle at top right, rgba(248, 113, 113, 0.34), transparent 18rem),
        linear-gradient(135deg, #2a0b0b, #5f1515 52%, #7f1d1d) !important;
    }}

    .decision-panel.wait {{
      background:
        radial-gradient(circle at top right, rgba(39, 152, 255, 0.28), transparent 18rem),
        linear-gradient(135deg, #071426, #10243f 55%, #1e3a5f) !important;
    }}

    .time-discipline-card {{
      background: linear-gradient(135deg, #ffffff, #f6fbff) !important;
      border-left: 6px solid var(--soft-blue) !important;
      padding: 22px !important;
    }}

    .market-box,
    .trend-box,
    .position-plan,
    .score-section,
    .accuracy-section,
    .engine-section,
    .breadth-section,
    .pressure-section,
    .chart-section {{
      padding: 24px !important;
    }}

    .position-plan {{
      background: linear-gradient(180deg, #ffffff 0%, #f7fbff 100%) !important;
    }}

    .mtf-card,
    .intraday-midpoint-card,
    .direction-level,
    .alert-pressure-window,
    .confluence-factor,
    .engine-card,
    .breadth-card {{
      border-radius: 18px !important;
      border: 1px solid var(--soft-border) !important;
      background: #ffffff !important;
      box-shadow: 0 8px 18px rgba(15, 23, 42, 0.045) !important;
    }}

    .direction-level {{
      padding: 16px !important;
    }}

    button,
    .button,
    .refresh-button,
    .refresh-btn,
    a.button {{
      border-radius: 999px !important;
      border: 0 !important;
      box-shadow: 0 10px 24px rgba(39, 152, 255, 0.18) !important;
    }}

    .empty {{
      color: #7c8da0 !important;
      background: #f8fbff !important;
      border: 1px dashed var(--soft-border) !important;
      border-radius: 18px !important;
      padding: 18px !important;
    }}

    @media (max-width: 760px) {{
      body {{
        font-size: 15px !important;
      }}

      section,
      .detail-section,
      .decision-panel,
      .position-plan,
      .score-section,
      .accuracy-section,
      .engine-section,
      .breadth-section,
      .pressure-section,
      .chart-section,
      .market-box,
      .trend-box,
      .confluence-checklist,
      .top-confluence-checklist,
      .trade-decision-meter,
      .trade-risk-meter,
      .pre-market-panel,
      .mode-banner,
      .time-discipline-card {{
        border-radius: 22px !important;
      }}

      .decision-panel {{
        padding: 24px 20px !important;
      }}

      .market-box,
      .trend-box,
      .position-plan,
      .score-section,
      .accuracy-section,
      .engine-section,
      .breadth-section,
      .pressure-section,
      .chart-section {{
        padding: 20px !important;
      }}

      .detail-section summary {{
        padding: 17px 18px !important;
        font-size: 16px !important;
      }}
    }}

    /* =========================================================
       SPY HERO SUMMARY - PHASE 2
       Top hierarchy only. No scanner logic changed.
       ========================================================= */

    .spy-hero {{
      border: 0 !important;
      border-radius: 32px !important;
      padding: 34px !important;
      margin-bottom: 22px !important;
      color: #ffffff !important;
      background:
        radial-gradient(circle at top right, rgba(87, 211, 216, 0.30), transparent 22rem),
        linear-gradient(135deg, #071426 0%, #102b52 55%, #0f5ea8 100%) !important;
      box-shadow: 0 22px 48px rgba(15, 23, 42, 0.18) !important;
      overflow: hidden !important;
    }}

    .spy-hero.call {{
      background:
        radial-gradient(circle at top right, rgba(34, 197, 94, 0.36), transparent 22rem),
        linear-gradient(135deg, #052015 0%, #075033 55%, #0d7a4a 100%) !important;
    }}

    .spy-hero.put {{
      background:
        radial-gradient(circle at top right, rgba(248, 113, 113, 0.38), transparent 22rem),
        linear-gradient(135deg, #2a0b0b 0%, #651717 55%, #9f1d1d 100%) !important;
    }}

    .spy-hero.wait {{
      background:
        radial-gradient(circle at top right, rgba(39, 152, 255, 0.34), transparent 22rem),
        linear-gradient(135deg, #071426 0%, #10243f 55%, #1f5f99 100%) !important;
    }}

    .spy-hero * {{
      color: inherit !important;
    }}

    .spy-hero-shell {{
      display: grid;
      grid-template-columns: 1.15fr 0.85fr;
      gap: 26px;
      align-items: stretch;
    }}

    .spy-hero-topline {{
      text-transform: uppercase;
      letter-spacing: 0.14em;
      font-size: 12px;
      font-weight: 900;
      opacity: 0.78;
      margin-bottom: 14px;
    }}

    .spy-hero h1 {{
      margin: 0;
      font-size: clamp(42px, 7vw, 82px) !important;
      line-height: 0.92 !important;
      letter-spacing: -0.06em;
      font-weight: 900 !important;
    }}

    .spy-hero-subtitle {{
      max-width: 680px;
      margin: 18px 0 0;
      font-size: clamp(16px, 2vw, 21px);
      line-height: 1.45;
      opacity: 0.88;
    }}

    .spy-hero-pills {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 22px;
    }}

    .spy-hero-pills span {{
      border: 1px solid rgba(255, 255, 255, 0.24);
      background: rgba(255, 255, 255, 0.12);
      backdrop-filter: blur(12px);
      border-radius: 999px;
      padding: 9px 13px;
      font-size: 12px;
      font-weight: 900;
    }}

    .spy-hero-metrics {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
    }}

    .spy-hero-metric {{
      min-height: 112px;
      border-radius: 22px;
      padding: 18px;
      background: rgba(255, 255, 255, 0.12);
      border: 1px solid rgba(255, 255, 255, 0.22);
      box-shadow: 0 10px 22px rgba(0, 0, 0, 0.10);
    }}

    .spy-hero-metric.primary {{
      grid-column: span 2;
    }}

    .spy-hero-metric span {{
      display: block;
      font-size: 12px;
      font-weight: 850;
      text-transform: uppercase;
      letter-spacing: 0.10em;
      opacity: 0.72;
      margin-bottom: 10px;
    }}

    .spy-hero-metric strong {{
      display: block;
      font-size: clamp(26px, 4vw, 44px);
      line-height: 1;
      font-weight: 900;
      letter-spacing: -0.05em;
    }}

    .spy-hero-reason {{
      margin-top: 26px;
      padding: 22px;
      border-radius: 24px;
      background: rgba(255, 255, 255, 0.10);
      border: 1px solid rgba(255, 255, 255, 0.18);
    }}

    .spy-hero-reason h2 {{
      margin: 0 0 12px;
      font-size: 18px !important;
      letter-spacing: -0.02em;
    }}

    .spy-hero-reason ul {{
      margin: 0;
      padding-left: 19px;
      display: grid;
      gap: 7px;
      opacity: 0.92;
    }}

    .spy-hero-reason li {{
      line-height: 1.42;
    }}

    @media (max-width: 760px) {{
      .spy-hero {{
        border-radius: 28px !important;
        padding: 26px 20px !important;
      }}

      .spy-hero-shell {{
        grid-template-columns: 1fr;
      }}

      .spy-hero-metrics {{
        grid-template-columns: 1fr 1fr;
      }}

      .spy-hero-metric {{
        min-height: 94px;
        padding: 16px;
      }}

      .spy-hero-metric.primary {{
        grid-column: span 2;
      }}
    }}

    /* =========================================================
       DARK SIGNAL UI - VISUAL LAYER ONLY
       ========================================================= */
    :root {{
      --bg: #07101d;
      --panel: #101b2b;
      --panel-soft: #162337;
      --text: #edf4fb;
      --muted: #91a3b8;
      --green: #38d996;
      --red: #ff6b7a;
      --amber: #f2bd55;
      --border: rgba(151, 172, 198, 0.18);
      --shadow: 0 18px 48px rgba(0, 0, 0, 0.28);
      --shadow-soft: 0 10px 26px rgba(0, 0, 0, 0.20);
    }}

    html {{ scroll-behavior: smooth; background: var(--bg); }}
    body {{
      min-height: 100vh;
      background:
        radial-gradient(circle at 12% -10%, rgba(45, 115, 180, 0.22), transparent 34rem),
        radial-gradient(circle at 92% 10%, rgba(56, 217, 150, 0.08), transparent 28rem),
        var(--bg) !important;
      color: var(--text) !important;
      font-family: Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif !important;
      line-height: 1.5;
    }}
    main {{ width: min(1320px, 100%); padding: 18px 24px 44px; }}
    h1, h2, h3, strong {{ color: var(--text); }}
    h1, h2, h3 {{ letter-spacing: -0.03em; }}
    h2 {{ font-size: clamp(19px, 2vw, 27px) !important; }}
    p, small, .note {{ color: var(--muted) !important; }}
    a {{ color: inherit; }}
    [id] {{ scroll-margin-top: 92px; }}
    .visually-hidden {{
      position: absolute !important;
      width: 1px !important;
      height: 1px !important;
      overflow: hidden !important;
      clip: rect(0 0 0 0) !important;
      white-space: nowrap !important;
    }}

    .dashboard-nav {{
      position: sticky;
      top: 10px;
      z-index: 50;
      display: grid;
      grid-template-columns: auto 1fr auto;
      align-items: center;
      gap: 18px;
      margin-bottom: 18px;
      padding: 11px 12px 11px 18px;
      border: 1px solid var(--border);
      border-radius: 18px;
      background: rgba(10, 19, 32, 0.88);
      box-shadow: var(--shadow-soft);
      backdrop-filter: blur(18px);
    }}
    .dashboard-brand {{
      text-decoration: none;
      font-weight: 900;
      letter-spacing: -0.03em;
      white-space: nowrap;
    }}
    .dashboard-brand span {{ color: var(--muted); font-weight: 650; }}
    .dashboard-nav nav {{ display: flex; justify-content: center; gap: 4px; }}
    .dashboard-nav nav a {{
      padding: 8px 11px;
      border-radius: 10px;
      color: var(--muted);
      font-size: 13px;
      font-weight: 750;
      text-decoration: none;
      transition: 160ms ease;
    }}
    .dashboard-nav nav a:hover {{ color: var(--text); background: var(--panel-soft); }}
    .dashboard-nav nav {{ scrollbar-width: none; }}
    .dashboard-nav nav::-webkit-scrollbar {{ display: none; }}
    .refresh-button {{
      padding: 9px 15px !important;
      border: 1px solid rgba(56, 217, 150, 0.35) !important;
      border-radius: 11px !important;
      background: rgba(56, 217, 150, 0.12) !important;
      color: var(--green) !important;
      box-shadow: none !important;
    }}
    .refresh-button:hover {{ background: rgba(56, 217, 150, 0.2) !important; }}

    section,
    .detail-section,
    .position-plan,
    .score-section,
    .accuracy-section,
    .engine-section,
    .breadth-section,
    .pressure-section,
    .chart-section,
    .market-box,
    .trend-box,
    .confluence-checklist,
    .top-confluence-checklist,
    .trade-decision-meter,
    .trade-risk-meter,
    .pre-market-panel,
    .mode-banner,
    .time-discipline-card,
    .ai-paper-benchmark {{
      border: 1px solid var(--border) !important;
      border-radius: 18px !important;
      background: var(--panel) !important;
      color: var(--text) !important;
      box-shadow: var(--shadow-soft) !important;
    }}
    section {{ margin-top: 18px !important; }}
    .detail-section {{ margin-top: 16px !important; overflow: hidden; }}
    .detail-section summary,
    .benchmark-detail-log > summary {{
      padding: 17px 20px !important;
      border: 0 !important;
      background: linear-gradient(180deg, rgba(24, 39, 60, 0.94), rgba(16, 27, 43, 0.94)) !important;
      color: var(--text) !important;
      font-weight: 800 !important;
      cursor: pointer;
    }}
    .detail-section[open] > summary {{ border-bottom: 1px solid var(--border) !important; }}
    .detail-content {{ padding: 18px !important; background: transparent !important; }}

    .signal-hero-shell {{
      position: static !important;
      max-height: none !important;
      overflow: visible !important;
      margin: 0 !important;
      padding: 0 !important;
      border: 0 !important;
      background: transparent !important;
      box-shadow: none !important;
    }}
    .signal-hero {{
      display: grid !important;
      grid-template-columns: minmax(0, 1.35fr) minmax(320px, .65fr) !important;
      gap: 24px !important;
      align-items: stretch !important;
      margin: 0 !important;
      padding: 30px !important;
      border: 1px solid rgba(120, 154, 194, 0.23) !important;
      border-radius: 22px !important;
      background:
        radial-gradient(circle at 90% 10%, rgba(86, 145, 211, 0.25), transparent 23rem),
        linear-gradient(135deg, #101f34 0%, #0d192a 68%) !important;
      box-shadow: var(--shadow) !important;
    }}
    .signal-hero.call {{
      background: radial-gradient(circle at 90% 10%, rgba(56, 217, 150, 0.20), transparent 23rem), linear-gradient(135deg, #10271f, #0d192a 68%) !important;
    }}
    .signal-hero.put {{
      background: radial-gradient(circle at 90% 10%, rgba(255, 107, 122, 0.20), transparent 23rem), linear-gradient(135deg, #2b171f, #0d192a 68%) !important;
    }}
    .signal-hero > .signal-hero-copy,
    .signal-hero > .signal-hero-stats {{
      min-width: 0 !important;
      padding: 0 !important;
      border: 0 !important;
      background: transparent !important;
    }}
    .signal-hero-copy {{ display: flex; flex-direction: column; justify-content: center; min-width: 0; }}
    .signal-hero-kicker {{ display: flex; flex-wrap: wrap; align-items: center; gap: 9px; color: var(--muted); font-size: 12px; font-weight: 750; }}
    .signal-hero-kicker strong {{ color: var(--text); }}
    .feed-dot {{ width: 9px; height: 9px; border-radius: 50%; background: var(--red); box-shadow: 0 0 0 5px rgba(255, 107, 122, .10); }}
    .feed-dot.live {{ background: var(--green); box-shadow: 0 0 0 5px rgba(56, 217, 150, .10); }}
    .signal-hero h1 {{ margin: 17px 0 12px; color: var(--text) !important; font-size: clamp(34px, 5vw, 60px) !important; line-height: 1 !important; font-weight: 860 !important; }}
    .signal-hero-copy > p {{ max-width: 760px; margin: 0; color: #c6d3e1 !important; font-size: 16px; line-height: 1.65; }}
    .signal-hero-meta {{ display: flex; flex-wrap: wrap; gap: 8px 16px; margin-top: 20px; color: var(--muted); font-size: 11px; }}
    .signal-hero-meta b {{ color: #cbd7e5; }}
    .signal-hero-stats {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }}
    .hero-stat {{ display: flex; flex-direction: column; justify-content: center; min-height: 104px; padding: 17px; border: 1px solid var(--border); border-radius: 16px; background: rgba(255, 255, 255, 0.045); }}
    .hero-stat:first-child {{ grid-column: 1; grid-row: 1; }}
    .hero-stat:last-child {{ grid-column: 2; grid-row: 1; }}
    .hero-signal {{ grid-column: 1 / -1; grid-row: 2; }}
    .hero-stat span {{ color: var(--muted); font-size: 11px; font-weight: 800; letter-spacing: .08em; text-transform: uppercase; }}
    .hero-stat strong {{ margin-top: 7px; font-size: clamp(22px, 2.5vw, 34px); line-height: 1; letter-spacing: -.04em; white-space: nowrap; }}
    .hero-signal.call strong {{ color: var(--green); }}
    .hero-signal.put strong {{ color: var(--red); }}
    .hero-signal.wait strong {{ color: var(--amber); }}
    .hero-signal strong {{ overflow-wrap: normal !important; word-break: normal; }}
    .data-stale-warning {{ margin: 10px 0 0 !important; border-radius: 12px !important; background: rgba(255, 107, 122, .12) !important; color: var(--red) !important; }}

    .dashboard-primary-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-top: 16px; }}
    .overview-card {{ margin: 0 !important; padding: 22px !important; }}
    .overview-heading {{ display: flex; justify-content: space-between; gap: 16px; align-items: center; margin-bottom: 18px; }}
    .overview-heading > span {{ color: var(--muted); font-size: 12px; font-weight: 850; letter-spacing: .09em; text-transform: uppercase; }}
    .overview-heading > strong {{ text-align: right; }}
    .signal-badge {{ display: inline-flex; align-items: center; justify-content: center; min-width: 92px; padding: 9px 15px; border-radius: 999px; font-size: 22px; }}
    .signal-badge.call {{ color: var(--green); background: rgba(56, 217, 150, .12); border: 1px solid rgba(56, 217, 150, .26); }}
    .signal-badge.put {{ color: var(--red); background: rgba(255, 107, 122, .12); border: 1px solid rgba(255, 107, 122, .26); }}
    .signal-badge.wait {{ color: var(--amber); background: rgba(242, 189, 85, .12); border: 1px solid rgba(242, 189, 85, .26); }}
    .overview-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 9px; }}
    .overview-grid > div,
    .key-levels-grid > div,
    .benchmark-focus-grid > div {{ padding: 13px 14px; border: 1px solid var(--border); border-radius: 13px; background: var(--panel-soft); }}
    .overview-grid span,
    .key-levels-grid span,
    .benchmark-focus-grid span {{ display: block; color: var(--muted); font-size: 11px; font-weight: 750; margin-bottom: 5px; }}
    .overview-grid strong,
    .key-levels-grid strong,
    .benchmark-focus-grid strong {{ display: block; overflow-wrap: anywhere; }}
    .overview-footnote {{ margin: 14px 0 0; font-size: 12px; }}
    .action-copy {{ margin-bottom: 10px; padding: 13px 14px; border-left: 3px solid #4c6f96; border-radius: 0 12px 12px 0; background: rgba(255,255,255,.03); }}
    .action-copy span, .level-summary-row span {{ display: block; color: var(--muted); font-size: 11px; margin-bottom: 4px; }}
    .action-copy strong {{ font-size: 13px; line-height: 1.5; }}
    .level-summary-row {{ display: flex; justify-content: space-between; gap: 14px; margin-top: 8px; padding: 10px 12px; border-radius: 11px; background: rgba(255,255,255,.035); }}
    .level-summary-row span {{ margin: 0; }}
    .level-summary-row strong {{ font-size: 12px; text-align: right; }}
    .bullish strong, .level-path.bullish strong {{ color: var(--green) !important; }}
    .bearish strong, .level-path.bearish strong {{ color: var(--red) !important; }}
    .no-trade-warning {{ margin-top: 12px !important; border: 1px solid rgba(242, 189, 85, .24) !important; border-radius: 12px !important; background: rgba(242, 189, 85, .08) !important; color: var(--amber) !important; }}

    .key-levels-card {{ margin-top: 16px !important; padding: 22px !important; }}
    .key-levels-grid {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 9px; }}
    .level-core {{ background: rgba(91, 132, 177, .12) !important; }}

    .engine-section {{ padding: 22px !important; }}
    .engine-grid {{ gap: 12px !important; }}
    .engine-score, .engine-counts > div {{ border: 1px solid var(--border) !important; border-radius: 14px !important; background: var(--panel-soft) !important; }}
    .engine-score strong {{ color: var(--text) !important; }}
    .engine-section .note {{ margin: 12px 0 4px; font-size: 11px; }}

    .ai-paper-benchmark {{ padding: 24px !important; }}
    .benchmark-heading {{ margin-bottom: 18px; }}
    .benchmark-focus-grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 9px; }}
    .benchmark-focus-grid .wide {{ grid-column: span 2; }}
    .benchmark-status {{ border: 1px solid var(--border) !important; background: var(--panel-soft) !important; }}
    .benchmark-detail-log {{ margin-top: 16px; border: 1px solid var(--border); border-radius: 15px; overflow: hidden; background: rgba(4, 10, 18, .18); }}
    .benchmark-detail-body {{ padding: 18px; }}
    .benchmark-summary-grid > div,
    .benchmark-position-grid > div,
    .benchmark-equity-panel {{ border: 1px solid var(--border) !important; background: var(--panel-soft) !important; color: var(--text) !important; }}

    .table-wrap {{ border: 1px solid var(--border); border-radius: 14px; overflow: auto; background: rgba(6, 13, 23, .32); }}
    table {{ width: 100%; color: var(--text) !important; border-collapse: collapse; }}
    th {{ background: #17263a !important; color: #b9c8d8 !important; font-size: 11px; letter-spacing: .04em; text-transform: uppercase; }}
    td {{ color: #dce6f0 !important; }}
    th, td {{ padding: 11px 12px !important; border-color: var(--border) !important; }}
    tbody tr:nth-child(even) {{ background: rgba(255,255,255,.025); }}
    tbody tr:hover {{ background: rgba(91, 132, 177, .09); }}
    .engine-group th {{ background: #132236 !important; }}
    .engine-status {{ border-radius: 999px !important; padding: 5px 9px !important; }}
    .engine-status.bullish {{ color: var(--green) !important; background: rgba(56,217,150,.1) !important; }}
    .engine-status.bearish {{ color: var(--red) !important; background: rgba(255,107,122,.1) !important; }}
    .engine-status.neutral {{ color: var(--amber) !important; background: rgba(242,189,85,.1) !important; }}

    .education-box,
    .mtf-card,
    .intraday-midpoint-card,
    .direction-level,
    .alert-pressure-window,
    .confluence-factor,
    .engine-card,
    .breadth-card,
    .stop-education {{
      border: 1px solid var(--border) !important;
      border-radius: 14px !important;
      background: var(--panel-soft) !important;
      color: var(--text) !important;
      box-shadow: none !important;
    }}
    .empty {{ color: var(--muted) !important; background: rgba(255,255,255,.025) !important; border: 1px dashed var(--border) !important; }}
    input, select {{ color: var(--text) !important; background: var(--panel-soft) !important; border-color: var(--border) !important; }}
    .dashboard-footer {{ color: #6f849b; }}

    @media (max-width: 900px) {{
      .dashboard-nav {{ grid-template-columns: 1fr auto; }}
      .dashboard-nav nav {{ grid-column: 1 / -1; grid-row: 2; justify-content: flex-start; overflow-x: auto; padding-bottom: 2px; }}
      .signal-hero {{ grid-template-columns: 1fr !important; }}
      .dashboard-primary-grid {{ grid-template-columns: 1fr; }}
      .benchmark-focus-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
    }}

    @media (max-width: 620px) {{
      main {{ padding: 10px 12px 30px; }}
      .dashboard-nav {{ top: 6px; gap: 10px; padding: 9px 10px 9px 13px; border-radius: 15px; }}
      .dashboard-nav nav a {{ padding: 7px 9px; font-size: 12px; }}
      .signal-hero {{ padding: 21px !important; border-radius: 18px !important; }}
      .signal-hero h1 {{ font-size: 36px !important; }}
      .signal-hero-stats {{ grid-template-columns: 1fr 1fr; }}
      .hero-stat {{ min-height: 88px; padding: 13px; }}
      .hero-stat strong {{ font-size: 24px; }}
      .overview-card, .key-levels-card, .engine-section, .ai-paper-benchmark {{ padding: 17px !important; }}
      .overview-grid, .key-levels-grid, .benchmark-focus-grid {{ grid-template-columns: 1fr 1fr; }}
      .benchmark-focus-grid .wide {{ grid-column: 1 / -1; }}
      .level-summary-row {{ display: block; }}
      .level-summary-row strong {{ display: block; margin-top: 4px; text-align: left; }}
      .detail-content, .benchmark-detail-body {{ padding: 12px !important; }}
      th, td {{ padding: 9px 10px !important; white-space: nowrap; }}
    }}

    @media (max-width: 420px) {{
      .overview-grid, .key-levels-grid, .benchmark-focus-grid {{ grid-template-columns: 1fr; }}
      .benchmark-focus-grid .wide {{ grid-column: auto; }}
      .dashboard-brand span {{ display: none; }}
    }}
</style>
</head>
<body>
  <main id="dashboard-top">
    <header class="dashboard-nav">
      <a class="dashboard-brand" href="#dashboard-top">SPY <span>Signal Lab</span></a>
      <nav aria-label="Dashboard sections">
        <a href="#dashboard-overview">Dashboard</a>
        <a href="#signal-overview">Signal</a>
        <a href="#key-levels-overview">Levels</a>
        <a href="#section-engine-health">Engine</a>
        <a href="#paper-benchmark-overview">Paper</a>
        <a href="#section-recent-signal-history">History</a>
      </nav>
      <button class="refresh-button" id="refresh-button" type="button"
              onclick="refreshDashboard()">
        Refresh
      </button>
    </header>
    <div id="dashboard-content">{dashboard_content}</div>
    <footer class="dashboard-footer">
      <strong>SPY Dashboard
      <b id="footer-dashboard-version">v{escape_value(DASHBOARD_VERSION)}</b></strong>
      Â· Build <span id="footer-build-time">{escape_value(DASHBOARD_BUILD_TIME)}</span>
      Â· <span id="footer-build-source">{escape_value(DASHBOARD_BUILD_SOURCE)}</span>
      <span>Host: <b id="footer-dashboard-hostname">{escape_value(DASHBOARD_HOSTNAME)}</b></span>
      <span>File: <b id="footer-dashboard-file">{escape_value(DASHBOARD_FILE)}</b></span>
    </footer>
  </main>
  <script>
    let dashboardRefreshInProgress = false;
    let selectedMaxRisk = "25";
    let liveLevelSetId = null;
    let previousLiveLevelSetId = null;
    let lastHitBullLevel = 0;
    let lastHitBearLevel = 0;
    let liveLevelHitTimestamps = {{ bull: {{}}, bear: {{}} }};
    let soundAlertsEnabled = localStorage.getItem("spy-dashboard-sound-alerts") === "enabled";
    let audioContext = null;
    let lastTimeDisciplinePhase = sessionStorage.getItem("spy-dashboard-time-phase");
    let serverEasternSeconds = null;
    let serverEasternSyncMs = null;
    let serverEasternWeekday = null;
    const previousLevelLabels = {{}};

    function enableSoundAlerts() {{
      const AudioContextClass = window.AudioContext || window.webkitAudioContext;
      if (!AudioContextClass) return;
      audioContext = audioContext || new AudioContextClass();
      audioContext.resume();
      soundAlertsEnabled = true;
      localStorage.setItem("spy-dashboard-sound-alerts", "enabled");
      const button = document.getElementById("enable-sound-alerts");
      if (button) button.textContent = "Sound Alerts Enabled";
      playDisciplineBeep(1);
    }}

    function playDisciplineBeep(strength) {{
      if (!soundAlertsEnabled) return;
      const AudioContextClass = window.AudioContext || window.webkitAudioContext;
      if (!AudioContextClass) return;
      audioContext = audioContext || new AudioContextClass();
      const start = audioContext.currentTime;
      for (let index = 0; index < strength; index += 1) {{
        const oscillator = audioContext.createOscillator();
        const gain = audioContext.createGain();
        oscillator.frequency.value = 520 + (strength * 110);
        gain.gain.setValueAtTime(0.0001, start + (index * 0.18));
        gain.gain.exponentialRampToValueAtTime(0.18, start + (index * 0.18) + 0.02);
        gain.gain.exponentialRampToValueAtTime(0.0001, start + (index * 0.18) + 0.14);
        oscillator.connect(gain);
        gain.connect(audioContext.destination);
        oscillator.start(start + (index * 0.18));
        oscillator.stop(start + (index * 0.18) + 0.16);
      }}
    }}

    function getNewYorkParts() {{
      if (Number.isFinite(serverEasternSeconds) && Number.isFinite(serverEasternSyncMs)) {{
        const elapsedSeconds = Math.floor((Date.now() - serverEasternSyncMs) / 1000);
        const totalSeconds = ((serverEasternSeconds + elapsedSeconds) % 86400 + 86400) % 86400;
        return {{
          hour: Math.floor(totalSeconds / 3600),
          minute: Math.floor((totalSeconds % 3600) / 60),
          second: totalSeconds % 60,
          weekday: serverEasternWeekday
        }};
      }}
      const parts = new Intl.DateTimeFormat("en-US", {{
        timeZone: "America/New_York",
        hour12: false,
        weekday: "short",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit"
      }}).formatToParts(new Date());
      const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
      const weekdayMap = {{ Mon: 0, Tue: 1, Wed: 2, Thu: 3, Fri: 4, Sat: 5, Sun: 6 }};
      return {{ hour: Number(values.hour) % 24, minute: Number(values.minute), second: Number(values.second), weekday: weekdayMap[values.weekday] }};
    }}

    function updateTimeDiscipline() {{
      const card = document.getElementById("time-discipline-card");
      if (!card) return;
      const title = document.getElementById("time-discipline-title");
      const message = document.getElementById("time-discipline-message");
      const clock = document.getElementById("time-discipline-et");
      const countdown = document.getElementById("no-new-trades-countdown");
      const button = document.getElementById("enable-sound-alerts");
      const now = getNewYorkParts();
      const secondsNow = (now.hour * 3600) + (now.minute * 60) + now.second;
      const noNewTradesSeconds = (15 * 3600) + (45 * 60);
      let phase = "normal";
      let phaseTitle = "REGULAR SESSION";
      let phaseMessage = "Trade only confirmed setups with defined risk.";
      let beepStrength = 0;

      if (now.weekday >= 5 || secondsNow < (9 * 3600) + (30 * 60) || secondsNow >= 16 * 3600) {{
        phase = "closed"; phaseTitle = "MARKET CLOSED"; phaseMessage = "Regular trading session has ended.";
      }} else if (secondsNow >= (15 * 3600) + (55 * 60)) {{
        phase = "close-only"; phaseTitle = "CLOSE / MANAGE ONLY"; phaseMessage = "Do not open new trades."; beepStrength = 3;
      }} else if (secondsNow >= noNewTradesSeconds) {{
        phase = "no-new"; phaseTitle = "NO NEW TRADES"; phaseMessage = "Manage open positions only."; beepStrength = 2;
      }} else if (secondsNow >= 15 * 3600) {{
        phase = "caution"; phaseTitle = "POWER HOUR CAUTION"; phaseMessage = "Only take clean A+ setups."; beepStrength = 1;
      }}

      card.classList.remove("normal", "caution", "no-new", "close-only", "closed");
      card.classList.add(phase);
      title.textContent = phaseTitle;
      message.textContent = phaseMessage;
      clock.textContent = `${{String(now.hour).padStart(2, "0")}}:${{String(now.minute).padStart(2, "0")}}:${{String(now.second).padStart(2, "0")}} ET`;
      const remaining = Math.max(0, noNewTradesSeconds - secondsNow);
      const hours = Math.floor(remaining / 3600);
      const minutes = Math.floor((remaining % 3600) / 60);
      const seconds = remaining % 60;
      countdown.textContent = remaining > 0
        ? `Time until No New Trades: ${{String(hours).padStart(2, "0")}}:${{String(minutes).padStart(2, "0")}}:${{String(seconds).padStart(2, "0")}}`
        : "No New Trades window is active.";
      if (button && soundAlertsEnabled) button.textContent = "Sound Alerts Enabled";

      if (phase !== lastTimeDisciplinePhase) {{
        if (beepStrength) playDisciplineBeep(beepStrength);
        lastTimeDisciplinePhase = phase;
        sessionStorage.setItem("spy-dashboard-time-phase", phase);
      }}
    }}

    function updatePositionPlan() {{
      const plan = document.querySelector(".position-plan[data-risk-per-contract]");
      const selector = document.getElementById("max-risk-selector");
      const output = document.getElementById("estimated-max-contracts");

      if (!plan || !selector || !output) {{
        return;
      }}

      selectedMaxRisk = selector.value;
      const riskPerContract = Number(plan.dataset.riskPerContract);
      const maxRisk = Number(selector.value);

      if (!Number.isFinite(riskPerContract) || riskPerContract <= 0) {{
        output.textContent = "N/A";
        return;
      }}

      output.textContent = String(Math.floor(maxRisk / riskPerContract));
    }}

    function restorePositionPlan() {{
      const selector = document.getElementById("max-risk-selector");

      if (selector) {{
        selector.value = selectedMaxRisk;
      }}

      updatePositionPlan();
    }}

    function sectionStorageKey(sectionId) {{
      return `spy-dashboard-section-${{sectionId}}`;
    }}

    function restoreCollapsibleStates(root = document) {{
      root.querySelectorAll("details[data-persist-id]").forEach((section) => {{
        const savedState = localStorage.getItem(sectionStorageKey(section.dataset.persistId));

        if (savedState === "open") {{
          section.open = true;
        }} else if (savedState === "closed") {{
          section.open = false;
        }}
      }});
    }}

    function syncDashboardContent(content, newHtml) {{
      const incomingContainer = document.createElement("div");
      incomingContainer.innerHTML = newHtml;
      const currentChildren = Array.from(content.children);
      const incomingChildren = Array.from(incomingContainer.children);

      incomingChildren.forEach((incoming, index) => {{
        const sectionId = incoming.dataset ? incoming.dataset.sectionId : "";

        if (incoming.matches("details.detail-section[data-section-id]") && sectionId) {{
          const existing = content.querySelector(
            `details.detail-section[data-section-id="${{sectionId}}"]`
          );

          if (existing) {{
            const existingContent = existing.querySelector(":scope > .detail-content");
            const incomingContent = incoming.querySelector(":scope > .detail-content");

            if (existingContent && incomingContent) {{
              existingContent.innerHTML = incomingContent.innerHTML;
            }}
            return;
          }}
        }}

        const current = currentChildren[index];
        if (current) {{
          current.replaceWith(incoming);
        }} else {{
          content.appendChild(incoming);
        }}
      }});

      currentChildren.slice(incomingChildren.length).forEach((node) => node.remove());
    }}

    document.addEventListener("toggle", (event) => {{
      const section = event.target;

      if (section.matches && section.matches("details[data-persist-id]")) {{
        localStorage.setItem(
          sectionStorageKey(section.dataset.persistId),
          section.open ? "open" : "closed"
        );
      }}
    }}, true);

    function applyLiveLevelStatus(status) {{
      if (!status) {{
        return;
      }}

      const numberValue = (value) => {{
        const match = String(value ?? "").replace(/[$,\s]/g, "").match(/-?\d+(?:\.\d+)?/);
        const parsed = match ? Number.parseFloat(match[0]) : Number.NaN;
        return Number.isFinite(parsed) ? parsed : null;
      }};
      const livePrice = numberValue(status.live_spy_price);
      const bullTrigger = numberValue(status.bull_trigger);
      const bullConfirmation = numberValue(status.bull_confirmation);
      const bullBreakout = numberValue(status.bull_breakout);
      const bearTrigger = numberValue(status.bear_trigger);
      const bearConfirmation = numberValue(status.bear_confirmation);
      const bearBreakdown = numberValue(status.bear_breakdown);
      const nearestSupport = numberValue(status.nearest_support);
      const nearestResistance = numberValue(status.nearest_resistance);
      const dataAge = numberValue(status.data_age_seconds ?? status.data_age);
      const analysisAge = numberValue(status.analysis_age);
      const feedConnected = typeof status.feed_connected === "boolean"
        ? status.feed_connected
        : !(Boolean(status.data_stale) || dataAge === null || dataAge > 180);
      const dataStale = typeof status.data_stale === "boolean"
        ? status.data_stale
        : !feedConnected;
      const feedStatus = feedConnected
        ? "FEED LIVE"
        : "DASHBOARD FEED DISCONNECTED";
      const easternSeconds = numberValue(status.eastern_seconds);
      if (easternSeconds !== null) {{
        serverEasternSeconds = easternSeconds;
        serverEasternSyncMs = Date.now();
        serverEasternWeekday = Number(status.eastern_weekday);
        updateTimeDiscipline();
      }}

      const updateSupportResistance = (levelType, levelValue) => {{
        document.querySelectorAll(`[data-sr-level="${{levelType}}"]`).forEach((element) => {{
          if (levelValue !== null) {{
            element.textContent = `$${{levelValue.toFixed(4)}}`;
          }}
          const isNear = !dataStale
            && livePrice !== null
            && levelValue !== null
            && Math.abs(livePrice - levelValue) <= Math.abs(levelValue) * 0.001;
          element.classList.toggle("near-level", isNear);
        }});
      }};
      updateSupportResistance("support", nearestSupport);
      updateSupportResistance("resistance", nearestResistance);

      if (!dataStale && status.level_set_id !== liveLevelSetId) {{
        previousLiveLevelSetId = status.last_level_set_id || liveLevelSetId;
        liveLevelSetId = status.level_set_id;
        lastHitBullLevel = Number(status.last_hit_bull_level) || 0;
        lastHitBearLevel = Number(status.last_hit_bear_level) || 0;
        liveLevelHitTimestamps = status.level_hit_timestamp || {{ bull: {{}}, bear: {{}} }};
      }} else if (!dataStale) {{
        lastHitBullLevel = Number(status.last_hit_bull_level) || 0;
        lastHitBearLevel = Number(status.last_hit_bear_level) || 0;
        const serverTimestamps = status.level_hit_timestamp || {{ bull: {{}}, bear: {{}} }};
        liveLevelHitTimestamps.bull = {{ ...liveLevelHitTimestamps.bull, ...(serverTimestamps.bull || {{}}) }};
        liveLevelHitTimestamps.bear = {{ ...liveLevelHitTimestamps.bear, ...(serverTimestamps.bear || {{}}) }};
      }}
      if (!dataStale && livePrice !== null) {{
        let observedBullLevel = 0;
        let observedBearLevel = 0;
        if (bullTrigger !== null && livePrice >= bullTrigger) observedBullLevel = 1;
        if (bullConfirmation !== null && livePrice >= bullConfirmation) observedBullLevel = 2;
        if (bullBreakout !== null && livePrice >= bullBreakout) observedBullLevel = 3;
        if (bearTrigger !== null && livePrice <= bearTrigger) observedBearLevel = 1;
        if (bearConfirmation !== null && livePrice <= bearConfirmation) observedBearLevel = 2;
        if (bearBreakdown !== null && livePrice <= bearBreakdown) observedBearLevel = 3;

        const nowSeconds = Date.now() / 1000;
        if (observedBullLevel > lastHitBullLevel) {{
          lastHitBullLevel = observedBullLevel;
          liveLevelHitTimestamps.bull[String(observedBullLevel)] = nowSeconds;
        }}
        if (observedBearLevel > lastHitBearLevel) {{
          lastHitBearLevel = observedBearLevel;
          liveLevelHitTimestamps.bear[String(observedBearLevel)] = nowSeconds;
        }}
      }}
      const nowSeconds = Date.now() / 1000;
      const bullRecentlyHit = lastHitBullLevel > 0 &&
        nowSeconds - Number(liveLevelHitTimestamps.bull[String(lastHitBullLevel)] || 0) < 30;
      const bearRecentlyHit = lastHitBearLevel > 0 &&
        nowSeconds - Number(liveLevelHitTimestamps.bear[String(lastHitBearLevel)] || 0) < 30;

      const states = {{
        bull_trigger: lastHitBullLevel >= 2 ? ["done-bull-level", "DONE âœ…"] : lastHitBullLevel >= 1 ? ["active-bull-level", "HIT"] : ["waiting-level", "WAITING"],
        bull_confirm: lastHitBullLevel >= 3 ? ["done-bull-level", "DONE âœ…"] : lastHitBullLevel >= 2 ? ["active-bull-level", "CONFIRMED"] : ["waiting-level", "WAITING"],
        bull_breakout: lastHitBullLevel >= 3 ? ["active-bull-level", "BREAKOUT"] : ["waiting-level", "WAITING"],
        bear_trigger: lastHitBearLevel >= 2 ? ["done-bear-level", "DONE âœ…"] : lastHitBearLevel >= 1 ? ["active-bear-level", "HIT"] : ["waiting-level", "WAITING"],
        bear_confirm: lastHitBearLevel >= 3 ? ["done-bear-level", "DONE âœ…"] : lastHitBearLevel >= 2 ? ["active-bear-level", "CONFIRMED"] : ["waiting-level", "WAITING"],
        bear_breakdown: lastHitBearLevel >= 3 ? ["active-bear-level", "BREAKDOWN"] : ["waiting-level", "WAITING"]
      }};
      const doneLabel = "DONE " + String.fromCodePoint(0x2705);
      states.bull_trigger = lastHitBullLevel >= 2 ? ["done-bull-level", doneLabel, "level-fade-done"] : lastHitBullLevel >= 1 ? bullRecentlyHit ? ["active-bull-level", "TRIGGER HIT", "level-glow"] : ["done-bull-level", doneLabel, "level-fade-done"] : ["waiting-level", "WAITING", ""];
      states.bull_confirm = lastHitBullLevel >= 3 ? ["done-bull-level", doneLabel, "level-fade-done"] : lastHitBullLevel >= 2 ? bullRecentlyHit ? ["active-bull-level", "CONFIRMED", "level-glow"] : ["done-bull-level", doneLabel, "level-fade-done"] : ["waiting-level", "WAITING", ""];
      states.bull_breakout = lastHitBullLevel >= 3 ? ["active-bull-level", "BREAKOUT ACTIVE", "level-glow"] : ["waiting-level", "WAITING", ""];
      states.bear_trigger = lastHitBearLevel >= 2 ? ["done-bear-level", doneLabel, "level-fade-done"] : lastHitBearLevel >= 1 ? bearRecentlyHit ? ["active-bear-level", "TRIGGER HIT", "level-glow"] : ["done-bear-level", doneLabel, "level-fade-done"] : ["waiting-level", "WAITING", ""];
      states.bear_confirm = lastHitBearLevel >= 3 ? ["done-bear-level", doneLabel, "level-fade-done"] : lastHitBearLevel >= 2 ? bearRecentlyHit ? ["active-bear-level", "CONFIRMED", "level-glow"] : ["done-bear-level", doneLabel, "level-fade-done"] : ["waiting-level", "WAITING", ""];
      states.bear_breakdown = lastHitBearLevel >= 3 ? ["active-bear-level", "BREAKDOWN ACTIVE", "level-glow"] : ["waiting-level", "WAITING", ""];
      if (dataStale && status.states) {{
        Object.entries(status.states).forEach(([key, state]) => {{
          if (states[key]) states[key] = [state.class_name, state.label, ""];
        }});
      }}
      const correctionMode = String(status.correction_mode || "NEUTRAL");
      const correctionSignal = String(status.correction_signal || "WAIT").toUpperCase();
      if (!dataStale && correctionSignal === "CALL" && lastHitBullLevel === 0) {{
        states.bull_trigger = ["active-bull-level", "CORRECTION CALL", "level-glow"];
      }}
      if (!dataStale && correctionSignal === "PUT" && lastHitBearLevel === 0) {{
        states.bear_trigger = ["active-bear-level", "CORRECTION PUT", "level-glow"];
      }}

      const stateClasses = [
        "waiting-level",
        "active-bull-level",
        "done-bull-level",
        "active-bear-level",
        "done-bear-level",
        "level-glow",
        "level-fade-done"
      ];

      const levelElements = {{
        bull_trigger: ["bull-trigger-card", "bull-trigger-status"],
        bull_confirm: ["bull-confirmation-card", "bull-confirmation-status"],
        bull_breakout: ["bull-breakout-card", "bull-breakout-status"],
        bear_trigger: ["bear-trigger-card", "bear-trigger-status"],
        bear_confirm: ["bear-confirmation-card", "bear-confirmation-status"],
        bear_breakdown: ["bear-breakdown-card", "bear-breakdown-status"]
      }};

      Object.entries(states).forEach(([key, state]) => {{
        const elementIds = levelElements[key];
        const row = elementIds ? document.getElementById(elementIds[0]) : null;
        const label = elementIds ? document.getElementById(elementIds[1]) : null;
        if (!row || !label) return;

        row.classList.remove(...stateClasses);
        row.classList.remove("correction-overlay-bull", "correction-overlay-bear");
        row.classList.add(...String(state[0]).split(/\s+/).filter(Boolean));
        if (state[2]) row.classList.add(state[2]);
        if (state[1] === "CORRECTION CALL") row.classList.add("correction-overlay-bull");
        if (state[1] === "CORRECTION PUT") row.classList.add("correction-overlay-bear");
        if (previousLevelLabels[key] !== state[1]) {{
          row.classList.remove("level-pulse");
          void row.offsetWidth;
          if (state[1] !== "WAITING") {{
            row.classList.add("level-pulse");
            window.setTimeout(() => row.classList.remove("level-pulse"), 850);
          }}
          previousLevelLabels[key] = state[1];
        }}
        label.textContent = state[1];
      }});

      document.querySelectorAll('[data-level-status="bull"]').forEach((badge) => {{
        badge.textContent = lastHitBullLevel >= 3 ? "BREAKOUT ACTIVE" : lastHitBullLevel >= 2 ? "CONFIRMED" : lastHitBullLevel >= 1 ? "TRIGGER HIT" : correctionSignal === "CALL" ? "CORRECTION CALL" : "WAITING";
      }});
      document.querySelectorAll('[data-level-status="bear"]').forEach((badge) => {{
        badge.textContent = lastHitBearLevel >= 3 ? "BREAKDOWN ACTIVE" : lastHitBearLevel >= 2 ? "CONFIRMED" : lastHitBearLevel >= 1 ? "TRIGGER HIT" : correctionSignal === "PUT" ? "CORRECTION PUT" : "WAITING";
      }});

      const banner = document.getElementById("live-signal-banner");
      const mode = String(status.banner || "WAIT").toUpperCase();
      const modeText = String(status.banner_text || "WAIT");
      const modeReason = String(status.banner_reason || "");
      if (banner) {{
        const headline = document.getElementById("live-market-phase");
        const recommendation = document.getElementById("live-recommendation");
        const reason = document.getElementById("live-signal-reason");
        if (headline) headline.textContent = mode;
        if (recommendation) recommendation.textContent = `Phase: ${{status.market_phase_display || "Range"}}`;
        if (reason) reason.textContent = modeReason || "Waiting for confirmation.";
        const summary = banner.closest(".sticky-signal-summary");
        if (summary) {{
          summary.classList.remove("call", "put", "wait");
          summary.classList.add(mode.toLowerCase());
        }}
      }}
      const bullishConfluence = Number(status.bullish_confluence_score) || 0;
      const bearishConfluence = Number(status.bearish_confluence_score) || 0;
      const neutralConfluence = Number(status.neutral_confluence_score) || 0;
      const meterValues = {{
        "decision-meter-final-read": status.confluence_final_read || "MIXED / WAIT",
        "decision-meter-advantage": status.current_advantage || "Mixed",
        "decision-meter-a-plus": status.a_plus_setup || "NO",
        "decision-meter-confluence": `${{Number(status.confluence_score) || Math.max(bullishConfluence, bearishConfluence)}} / 11`,
        "decision-meter-bearish": `${{bearishConfluence}} / 11`,
        "decision-meter-neutral": `${{neutralConfluence}} / 11`,
        "decision-meter-bullish": `${{bullishConfluence}} / 11`,
        "decision-meter-reason": modeReason || "No side has enough confluence."
      }};
      Object.entries(meterValues).forEach(([id, value]) => {{
        const target = document.getElementById(id);
        if (target) target.textContent = value;
      }});
      const topConfluenceValues = {{
        "top-confluence-final-read": mode,
        "top-confluence-a-plus": status.a_plus_setup || "NO",
        "top-confluence-bullish": `${{bullishConfluence}} / 11`,
        "top-confluence-bearish": `${{bearishConfluence}} / 11`,
        "top-confluence-neutral": `${{neutralConfluence}} / 11`,
        "top-confluence-reason": modeReason || "No side has enough confluence."
      }};
      Object.entries(topConfluenceValues).forEach(([id, value]) => {{
        const target = document.getElementById(id);
        if (target) target.textContent = value;
      }});
      const pillValues = {{
        "top-regime-pill": status.market_regime || "CHOPPY",
        "top-stability-pill": status.mode_stability || "N/A",
        "top-advantage-pill": status.current_advantage || "Mixed",
        "top-a-plus-pill": status.a_plus_setup || "NO",
        "top-score-pill": `${{Number(status.confluence_score) || Math.max(bullishConfluence, bearishConfluence)}} / 11`
      }};
      Object.entries(pillValues).forEach(([id, value]) => {{
        const target = document.getElementById(id);
        if (target) target.textContent = value;
      }});
      const trendOverridePill = document.getElementById("top-trend-override-pill");
      if (trendOverridePill) {{
        trendOverridePill.textContent = status.trend_override_label || "TREND OVERRIDE ACTIVE";
        trendOverridePill.classList.toggle("visible", Boolean(status.trend_override_active));
      }}
      const topLivePrice = document.getElementById("top-live-spy-price");
      if (topLivePrice && livePrice !== null) topLivePrice.textContent = livePrice.toFixed(4);
      const topFeedStatus = document.getElementById("top-feed-status");
      if (topFeedStatus) topFeedStatus.textContent = feedStatus;
      const topFeedAge = document.getElementById("top-feed-age");
      if (topFeedAge) topFeedAge.textContent = `Feed Age: ${{dataAge === null ? "N/A" : `${{dataAge.toFixed(0)}} sec`}}`;
      const topAnalysisAge = document.getElementById("top-analysis-age");
      if (topAnalysisAge) topAnalysisAge.textContent = `Analysis Age: ${{analysisAge === null ? "N/A" : `${{analysisAge.toFixed(0)}} sec`}}`;
      const topScoreCompact = document.getElementById("top-score-compact");
      if (topScoreCompact) topScoreCompact.textContent = `${{Number(status.confluence_score) || Math.max(bullishConfluence, bearishConfluence)}} / 11`;
      const meterMarker = document.getElementById("decision-meter-marker");
      if (meterMarker) {{
        const position = Math.max(4, Math.min(96, 50 + ((bullishConfluence - bearishConfluence) / 11 * 46)));
        meterMarker.style.left = `${{position}}%`;
      }}
      const meter = document.getElementById("trade-decision-meter");
      if (meter) {{
        meter.classList.remove("bullish", "bearish", "mixed");
        meter.classList.add(mode === "CALL" ? "bullish" : mode === "PUT" ? "bearish" : "mixed");
      }}
      const lastUpdated = document.getElementById("top-last-updated");
      if (lastUpdated) lastUpdated.textContent = status.last_updated || "N/A";
      const buildValues = {{
        "top-dashboard-version": `v${{status.dashboard_version || "N/A"}}`,
        "top-build-source": status.build_source || "N/A",
        "footer-dashboard-version": `v${{status.dashboard_version || "N/A"}}`,
        "footer-build-time": status.dashboard_build_time || status.build_time || "N/A",
        "footer-build-source": status.build_source || "N/A",
        "footer-dashboard-hostname": status.dashboard_hostname || status.build_source || "N/A",
        "footer-dashboard-file": status.dashboard_file || "N/A"
      }};
      Object.entries(buildValues).forEach(([id, value]) => {{
        const target = document.getElementById(id);
        if (target) target.textContent = value;
      }});
      const staleWarning = document.getElementById("top-stale-warning");
      if (staleWarning) {{
        staleWarning.textContent = feedStatus;
        staleWarning.classList.remove("live", "delayed", "disconnected");
        staleWarning.classList.add(feedConnected ? "live" : "disconnected");
        staleWarning.classList.toggle("visible", !feedConnected);
      }}

      const debugValues = {{
        "debug-live-price": livePrice,
        "debug-bull-trigger": bullTrigger,
        "debug-bull-confirmation": bullConfirmation,
        "debug-bull-breakout": bullBreakout,
        "debug-bear-trigger": bearTrigger,
        "debug-bear-confirmation": bearConfirmation,
        "debug-bear-breakdown": bearBreakdown,
        "debug-level-set-id": liveLevelSetId,
        "debug-last-level-set-id": status.last_level_set_id || previousLiveLevelSetId || "N/A",
        "debug-data-age": dataAge === null ? "N/A" : `${{dataAge.toFixed(1)}}s`,
        "debug-level-hit-timestamp": JSON.stringify(liveLevelHitTimestamps),
        "debug-level-hits-file": status.saved_hit_times_file_path || "N/A",
        "debug-last-saved-hit-time": status.last_saved_hit_time || "N/A",
        "debug-first-hit-times": JSON.stringify(status.first_hit_times || {{}}),
        "debug-bull-status": lastHitBullLevel >= 3 ? "BREAKOUT ACTIVE" : lastHitBullLevel >= 2 ? "CONFIRMED" : lastHitBullLevel >= 1 ? "TRIGGER HIT" : correctionSignal === "CALL" ? "CORRECTION CALL" : "WAITING",
        "debug-bear-status": lastHitBearLevel >= 3 ? "BREAKDOWN ACTIVE" : lastHitBearLevel >= 2 ? "CONFIRMED" : lastHitBearLevel >= 1 ? "TRIGGER HIT" : correctionSignal === "PUT" ? "CORRECTION PUT" : "WAITING",
        "debug-bull-trigger-status": states.bull_trigger[1],
        "debug-bull-confirmation-status": states.bull_confirm[1],
        "debug-bull-breakout-status": states.bull_breakout[1],
        "debug-bear-trigger-status": states.bear_trigger[1],
        "debug-bear-confirmation-status": states.bear_confirm[1],
        "debug-bear-breakdown-status": states.bear_breakdown[1],
        "debug-bull-trigger-hit": lastHitBullLevel >= 1 ? "TRUE" : "FALSE",
        "debug-bull-confirmation-hit": lastHitBullLevel >= 2 ? "TRUE" : "FALSE",
        "debug-bull-breakout-hit": lastHitBullLevel >= 3 ? "TRUE" : "FALSE",
        "debug-bear-trigger-hit": lastHitBearLevel >= 1 ? "TRUE" : "FALSE",
        "debug-bear-confirmation-hit": lastHitBearLevel >= 2 ? "TRUE" : "FALSE",
        "debug-bear-breakdown-hit": lastHitBearLevel >= 3 ? "TRUE" : "FALSE",
        "debug-correction-mode": correctionMode,
        "debug-correction-signal": correctionSignal,
        "debug-correction-activation-time": status.correction_activation_time || "N/A",
        "debug-current-banner-reason": status.current_banner_reason || status.banner_reason || "N/A",
        "debug-one-min-trend": status.one_min_trend || "Neutral",
        "debug-vwap-position": status.vwap_position || "Mixed",
        "debug-active-bull-level": status.active_bull_level || states.bull_trigger[1],
        "debug-active-bear-level": status.active_bear_level || states.bear_trigger[1],
        "debug-calculated-status": `Bull: ${{lastHitBullLevel}} | Bear: ${{lastHitBearLevel}} | Banner: ${{mode}}`
      }};
      Object.entries(debugValues).forEach(([id, value]) => {{
        const target = document.getElementById(id);
        if (target) target.textContent = value ?? "N/A";
      }});
      const correctionValues = {{
        "correction-mode": correctionMode,
        "correction-signal": correctionSignal,
        "correction-reason": status.correction_reason || "N/A",
        "correction-activation-time": status.correction_activation_time || "N/A"
      }};
      Object.entries(correctionValues).forEach(([id, value]) => {{
        const target = document.getElementById(id);
        if (target) target.textContent = value;
      }});
      restoreCollapsibleStates();
    }}

    async function refreshLiveLevelStatus() {{
      try {{
        const response = await fetch("/api/status", {{ cache: "no-store" }});
        if (response.ok) {{
          const status = await response.json();
          if (!status.available && !status.feed_connected) {{
            throw new Error(status.error || "Status API unavailable");
          }}
          applyLiveLevelStatus(status);
        }} else {{
          throw new Error("Status API unavailable");
        }}
      }} catch (error) {{
        console.error("Live level status refresh failed", error);
        const staleWarning = document.getElementById("top-stale-warning");
        if (staleWarning) {{
          staleWarning.textContent = "STATUS REFRESH FAILED â€” RETRYING";
          staleWarning.classList.remove("live", "disconnected");
          staleWarning.classList.add("delayed");
          staleWarning.classList.add("visible");
        }}
      }}
    }}

    async function refreshDashboard() {{
      if (dashboardRefreshInProgress) {{
        return;
      }}

      dashboardRefreshInProgress = true;
      const content = document.getElementById("dashboard-content");
      const button = document.getElementById("refresh-button");

      button.textContent = "Refreshing...";
      button.disabled = true;

      try {{
        const response = await fetch("/dashboard-content", {{ cache: "no-store" }});

        if (!response.ok) {{
          throw new Error("Dashboard refresh failed");
        }}

        syncDashboardContent(content, await response.text());
        restoreCollapsibleStates(content);
        restorePositionPlan();
        await refreshLiveLevelStatus();
      }} catch (error) {{
        console.error(error);
      }} finally {{
        button.textContent = "Refresh";
        button.disabled = false;
        dashboardRefreshInProgress = false;
      }}
    }}

    restoreCollapsibleStates();
    restorePositionPlan();
    updateTimeDiscipline();
    refreshLiveLevelStatus();
    window.setInterval(updateTimeDiscipline, 1000);
    window.setInterval(refreshLiveLevelStatus, 1000);
    window.setInterval(refreshDashboard, 5000);
  </script>
</body>
</html>"""


class DashboardHandler(BaseHTTPRequestHandler):
    def write_response(self, page):
        try:
            self.wfile.write(page)
        except (ConnectionAbortedError, BrokenPipeError, ConnectionResetError):
            print("Client disconnected during response.")

    def is_authorized(self):
        if not DASHBOARD_PASSWORD:
            return True

        authorization = self.headers.get("Authorization", "")

        if not authorization.startswith("Basic "):
            return False

        try:
            encoded_credentials = authorization.split(" ", 1)[1]
            decoded_credentials = base64.b64decode(
                encoded_credentials
            ).decode("utf-8")
            username, password = decoded_credentials.split(":", 1)
        except (binascii.Error, ValueError, UnicodeDecodeError):
            return False

        return (
            secrets.compare_digest(username, DASHBOARD_USERNAME)
            and secrets.compare_digest(password, DASHBOARD_PASSWORD)
        )

    def request_authentication(self):
        page = b"Authentication required."
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="SPY Dashboard"')
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(page)))
        self.end_headers()
        self.write_response(page)

    def do_GET(self):
        path = urlsplit(self.path).path

        if path == "/health":
            page = b"OK"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.write_response(page)
            return

        if not self.is_authorized():
            self.request_authentication()
            return

        if path == "/api/status":
            page = json.dumps(get_live_level_status()).encode("utf-8")
            content_type = "application/json; charset=utf-8"
        elif path == "/dashboard-content":
            page = build_dashboard_content().encode("utf-8")
            content_type = "text/html; charset=utf-8"
        else:
            page = build_page().encode("utf-8")
            content_type = "text/html; charset=utf-8"

        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(page)))
        self.end_headers()
        self.write_response(page)
    def do_POST(self):
        parsed = urlsplit(self.path)

        if parsed.path != "/api/push-status":
            self.send_response(404)
            self.end_headers()
            return

        expected_token = os.environ.get("DASHBOARD_UPDATE_TOKEN", "")
        supplied_token = self.headers.get("X-Dashboard-Token", "")

        if expected_token:
            if not secrets.compare_digest(supplied_token, expected_token):
                self.send_response(401)
                self.end_headers()
                self.wfile.write(b"Unauthorized")
                return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(content_length)
            payload = json.loads(raw_body.decode("utf-8"))

            payload["dashboard_received_at"] = datetime.now(
                ZoneInfo("America/New_York")
            ).isoformat()

            target_files = []

            if "LIVE_STATUS_FILE" in globals():
                target_folder = os.path.dirname(LIVE_STATUS_FILE)

                if target_folder:
                    os.makedirs(target_folder, exist_ok=True)

                temp_file = LIVE_STATUS_FILE + ".tmp"

                with open(temp_file, "w", encoding="utf-8") as file:
                    json.dump(payload, file, indent=2)

                os.replace(temp_file, LIVE_STATUS_FILE)

            if "PREDICTION_FILE" in globals():
                prediction_row = payload.get("latest_prediction")

                if not isinstance(prediction_row, dict) or not prediction_row:
                    prediction_row = {
                        key: value
                        for key, value in payload.items()
                        if not isinstance(value, (dict, list))
                    }

                target_folder = os.path.dirname(PREDICTION_FILE)

                if target_folder:
                    os.makedirs(target_folder, exist_ok=True)

                temp_file = PREDICTION_FILE + ".tmp"

                with open(temp_file, "w", encoding="utf-8", newline="") as file:
                    writer = csv.DictWriter(file, fieldnames=list(prediction_row.keys()))
                    writer.writeheader()
                    writer.writerow(prediction_row)

                os.replace(temp_file, PREDICTION_FILE)
            print(
                "Dashboard push received:",
                payload.get("current_spy_price"),
                payload.get("last_update")
            )

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok": true}')

        except Exception as error:
            print("Dashboard push error:", error)
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"Dashboard push failed")


    def log_message(self, format_string, *args):
        return


def main():
    HOST = os.environ.get("DASHBOARD_HOST", "0.0.0.0")
    PORT = int(os.environ.get("PORT", "10000"))

    server = HTTPServer((HOST, PORT), DashboardHandler)

    print(f"SPY dashboard reading: {os.path.abspath(PREDICTION_FILE)}")
    print(f"Open locally: http://localhost:{PORT}")
    print(
        f"Password protection: "
        f"{'enabled' if DASHBOARD_PASSWORD else 'disabled for local access'}"
    )

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopping SPY dashboard...")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()




