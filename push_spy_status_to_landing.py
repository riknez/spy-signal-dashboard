import csv
import json
import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Absolute so this always reads the same file the scanner writes,
# regardless of what folder this pusher was launched from.
LOG_DIR = os.path.join(BASE_DIR, "logs", "spy")

STATUS_FILE = os.path.join(LOG_DIR, "spy_live_status.json")
SCAN_LOG_FILE = os.path.join(LOG_DIR, "spy_options_scan_log.csv")
PREDICTION_FILE = os.path.join(LOG_DIR, "spy_direction_predictions.csv")
MARKET_BREADTH_FILE = os.path.join(LOG_DIR, "spy_market_breadth.csv")
ENGINE_HEALTH_FILE = os.path.join(LOG_DIR, "spy_engine_health.csv")
ALERTS_FILE = os.path.join(LOG_DIR, "spy_options_alerts.csv")
ALERT_RESULTS_FILE = os.path.join(LOG_DIR, "spy_options_alert_results.csv")
ACCURACY_FILE = os.path.join(LOG_DIR, "spy_options_a_plus_results.csv")
PAPER_TRADES_FILE = os.path.join(LOG_DIR, "ai_paper_benchmark_trades.csv")
LEVEL_HITS_FILE = os.path.join(LOG_DIR, "spy_level_hits.json")

DEFAULT_UPDATE_URL = "https://YOUR-SPY-RENDER-URL.onrender.com/api/push-status"

PUSH_EVERY_SECONDS = 3
STALE_AFTER_SECONDS = 180
# spy_dashboard.py's local panels that need more than the single latest
# row (Trend Box, Market Box, SPY Chart, regime detection feeding
# Structure/Level Detail) look back well past the old 50-row window -
# see calculate_daily_midpoint_source/build_trend_box/build_live_chart/
# detect_regime in spy_dashboard.py. This does not change any of that
# logic, only how much of the same data reaches Render.
PREDICTION_HISTORY_LIMIT = 1500
# Matches the regular-session window calculate_daily_midpoint_source
# uses locally (9:30 AM-4:00 PM ET) so "yesterday" means the same thing
# on Render that it means on the local dashboard.
REGULAR_SESSION_START = datetime.min.time().replace(hour=9, minute=30)
REGULAR_SESSION_END = datetime.min.time().replace(hour=16, minute=0)

# Scanning the full predictions file for the previous session is only
# worth doing once per calendar day - it does not change until today
# rolls into tomorrow - so it is cached rather than repeated every
# PUSH_EVERY_SECONDS cycle.
_previous_session_cache_date = None
_previous_session_cache_rows = []


def read_previous_session_rows(path):
    global _previous_session_cache_date, _previous_session_cache_rows

    today_et = datetime.now(ZoneInfo("America/New_York")).date()
    if _previous_session_cache_date == today_et:
        return _previous_session_cache_rows

    print(
        f"Scanning {path} for the previous regular session "
        f"(once per day, cached the rest of today)...",
        flush=True,
    )
    sessions = {}
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as file:
            for row in csv.DictReader(file):
                timestamp_text = row.get("time") or ""
                try:
                    timestamp = datetime.strptime(timestamp_text, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    continue
                if not (REGULAR_SESSION_START <= timestamp.time() <= REGULAR_SESSION_END):
                    continue
                row_date = timestamp.date()
                if row_date >= today_et:
                    continue
                sessions.setdefault(row_date, []).append(row)
    except (OSError, csv.Error) as error:
        print(f"Could not scan {path} for previous session: {error}", flush=True)
        _previous_session_cache_date = today_et
        _previous_session_cache_rows = []
        return []

    if not sessions:
        print("No previous regular-session rows found yet.", flush=True)
        _previous_session_cache_date = today_et
        _previous_session_cache_rows = []
        return []

    previous_date = max(sessions)
    rows = sessions[previous_date]
    print(f"Previous session found: {previous_date} ({len(rows)} rows)", flush=True)
    _previous_session_cache_date = today_et
    _previous_session_cache_rows = rows
    return rows


def load_env_file():
    if not os.path.exists(".env"):
        return

    with open(".env", "r", encoding="utf-8-sig") as file:
        for raw_line in file:
            line = raw_line.strip()

            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def read_json_file(path):
    try:
        with open(path, "r", encoding="utf-8-sig") as file:
            return json.load(file)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        print(f"JSON file is not valid: {path}")
        return {}
    except OSError as error:
        print(f"Could not read JSON file {path}: {error}")
        return {}


def read_last_csv_row(path):
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file)
            last_row = None

            for row in reader:
                last_row = row

            return last_row or {}
    except FileNotFoundError:
        return {}
    except OSError as error:
        print(f"Could not read CSV file {path}: {error}")
        return {}


def read_recent_csv_rows(path, limit=100):
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as file:
            rows = list(csv.DictReader(file))

        return rows[-limit:] if limit > 0 else []
    except FileNotFoundError:
        return []
    except (OSError, UnicodeDecodeError, csv.Error) as error:
        print(f"Could not read CSV file {path}: {error}")
        return []


def read_latest_csv_rows_by_key(path, key):
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as file:
            latest_rows = {}

            for row in csv.DictReader(file):
                row_key = row.get(key)

                if row_key:
                    latest_rows[row_key] = row

            return list(latest_rows.values())
    except FileNotFoundError:
        return []
    except (OSError, csv.Error) as error:
        print(f"Could not read CSV file {path}: {error}")
        return []


def safe_float(value):
    try:
        if value in ("", None, "N/A", "NA", "--"):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def safe_int(value):
    try:
        if value in ("", None, "N/A", "NA", "--"):
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def build_payload():
    now = time.time()

    status = read_json_file(STATUS_FILE)
    if os.path.isfile(STATUS_FILE):
        status_mtime = time.strftime(
            "%Y-%m-%d %H:%M:%S", time.localtime(os.path.getmtime(STATUS_FILE))
        )
    else:
        status_mtime = "FILE NOT FOUND"
    print(f"SPY status file: {STATUS_FILE}", flush=True)
    print(f"SPY status file last write time: {status_mtime}", flush=True)
    print(
        f"SPY last_update being pushed: {status.get('last_update', '(none)')}",
        flush=True,
    )
    scan = read_last_csv_row(SCAN_LOG_FILE)
    prediction = read_last_csv_row(PREDICTION_FILE)
    breadth_rows = read_recent_csv_rows(MARKET_BREADTH_FILE, 25)
    engine_rows = read_recent_csv_rows(ENGINE_HEALTH_FILE, 25)
    prediction_history = read_recent_csv_rows(PREDICTION_FILE, PREDICTION_HISTORY_LIMIT)
    previous_session_rows = read_previous_session_rows(PREDICTION_FILE)
    alert_history = read_recent_csv_rows(ALERTS_FILE, 50)
    alert_result_history = read_recent_csv_rows(ALERT_RESULTS_FILE, 50)
    accuracy_history = read_recent_csv_rows(ACCURACY_FILE, 50)
    paper_trade_history = read_recent_csv_rows(PAPER_TRADES_FILE, 50)
    breadth = breadth_rows[-1] if breadth_rows else {}
    engine = engine_rows[-1] if engine_rows else {}
    alert = read_last_csv_row(ALERTS_FILE)
    level_hits = read_json_file(LEVEL_HITS_FILE)

    update_epoch = safe_float(status.get("update_epoch")) or 0
    is_fresh = update_epoch > 0 and (now - update_epoch) <= STALE_AFTER_SECONDS

    current_spy_price = (
        safe_float(status.get("current_spy_price"))
        or safe_float(prediction.get("spy_price"))
        or safe_float(prediction.get("current_spy_price"))
        or safe_float(scan.get("spy_price"))
        or safe_float(scan.get("current_spy_price"))
    )

    direction = (
        prediction.get("direction")
        or prediction.get("final_decision")
        or prediction.get("signal")
        or prediction.get("decision")
        or scan.get("direction")
        or "WAIT"
    )

    confidence = (
        safe_float(prediction.get("confidence"))
        or safe_float(prediction.get("confidence_score"))
        or safe_float(prediction.get("total_score"))
        or safe_float(scan.get("confidence"))
    )

    market_regime = (
        prediction.get("market_regime")
        or prediction.get("regime")
        or scan.get("market_regime")
        or "--"
    )

    public_message = (
        "SPY scanner is online. Real-time CALL / PUT / WAIT signals are members-only."
        if is_fresh
        else "SPY scanner status is stale or offline. Waiting for a fresh scanner update."
    )

    payload = {
        "scanner_online": is_fresh,
        "scanner_type": "SPY Scanner + Signal Dashboard",
        "last_update": status.get("last_update", ""),
        "update_epoch": update_epoch,
        "current_spy_price": current_spy_price,
        "spy_price": current_spy_price,
        "spy_signal": direction,
        "direction": direction,
        "signal": direction,
        "confidence": confidence,
        "market_regime": market_regime,
        "data_source": status.get("data_source", "--"),
        "public_message": public_message,
        "signal_visibility": "Real-time CALL / PUT / WAIT signals are members-only.",
        "research_verdict": "ACTIVE PAPER TESTING",
        "dashboard_feed_status": "CONNECTED" if is_fresh else "STALE",
        "no_auto_buy": True,
        "no_auto_sell": True,
        "no_broker_connection": True,

        # Full latest rows for Render dashboard sections.
        "latest_status": status,
        "latest_scan": scan,
        "latest_prediction": prediction,
        "latest_market_breadth": breadth,
        "latest_engine_health": engine,
        "latest_market_breadth_rows": breadth_rows,
        "latest_engine_health_rows": engine_rows,
        "latest_prediction_history": prediction_history,
        # Previous trading day's regular-session rows, so Render can
        # compute the same "yesterday" comparisons
        # (calculate_daily_midpoint_source / Market Box) that the local
        # dashboard computes from its own full-history file.
        "latest_prediction_previous_session": previous_session_rows,
        "latest_alert_history": alert_history,
        "latest_alert_result_history": alert_result_history,
        "latest_accuracy_history": accuracy_history,
        "latest_paper_trade_history": paper_trade_history,
        "latest_prediction_history_count": len(prediction_history),
        "latest_prediction_previous_session_count": len(previous_session_rows),
        "latest_alert_history_count": len(alert_history),
        "latest_alert_result_history_count": len(alert_result_history),
        "latest_paper_trade_history_count": len(paper_trade_history),
        "latest_alert": alert,
        "latest_level_hits": level_hits,
    }

    # Also flatten the latest prediction row into the top-level payload.
    # This helps the Render dashboard find whatever field names it already expects.
    for key, value in prediction.items():
        payload.setdefault(key, value)

    for key, value in scan.items():
        payload.setdefault(key, value)
        payload.setdefault(f"scan_{key}", value)

    for key, value in breadth.items():
        payload.setdefault(key, value)
        payload.setdefault(f"breadth_{key}", value)

    for key, value in engine.items():
        payload.setdefault(key, value)
        payload.setdefault(f"engine_{key}", value)

    # Render dashboard aliases.
    # Local scanner uses bullish_/bearish_ names.
    # Render status endpoint expects bull_/bear_ names.
    alias_map = {
        "bull_trigger": "bullish_trigger",
        "bull_confirmation": "bullish_confirmation",
        "bull_breakout": "bullish_breakout",
        "bear_trigger": "bearish_trigger",
        "bear_confirmation": "bearish_confirmation",
        "bear_breakdown": "bearish_breakdown",
        "live_price": "current_spy_price",
        "live_spy_price": "current_spy_price",
        "prediction": "spy_signal",
        "total_score": "total_confidence",
        "market_regime": "regime",
    }

    for render_key, local_key in alias_map.items():
        value = payload.get(local_key)
        if value not in ("", None, "N/A", "NA", "--"):
            payload[render_key] = value

    print(f"Payload keys ({len(payload)}): {sorted(payload.keys())}", flush=True)
    print(
        "Payload row counts: "
        f"prediction_history={len(prediction_history)}, "
        f"previous_session={len(previous_session_rows)}, "
        f"alert_history={len(alert_history)}, "
        f"engine_health_rows={len(engine_rows)}, "
        f"market_breadth_rows={len(breadth_rows)}",
        flush=True,
    )

    return payload


def push_status(payload):
    update_url = (
        os.environ.get("DASHBOARD_UPDATE_URL")
        or os.environ.get("SPY_DASHBOARD_UPDATE_URL")
        or os.environ.get("SCANNER_STATUS_UPDATE_URL")
        or DEFAULT_UPDATE_URL
    ).strip()

    token = (
        os.environ.get("DASHBOARD_UPDATE_TOKEN")
        or os.environ.get("SPY_DASHBOARD_UPDATE_TOKEN")
        or os.environ.get("SCANNER_STATUS_UPDATE_TOKEN")
        or ""
    ).strip()

    if not update_url or "YOUR-SPY-RENDER-URL" in update_url:
        print("ERROR: DASHBOARD_UPDATE_URL is missing or still has placeholder URL.")
        return False

    headers = {
        "Content-Type": "application/json",
        "X-Dashboard-Token": token,
    }

    try:
        response = requests.post(
            update_url,
            headers=headers,
            json=payload,
            timeout=15,
        )
    except requests.RequestException as error:
        print(f"Push failed (no response from Render): {error}", flush=True)
        return False

    print(f"Render response status: {response.status_code}", flush=True)

    if response.status_code == 200:
        print(
            f"Pushed SPY dashboard payload | online={payload['scanner_online']} | "
            f"price={payload['current_spy_price']} | "
            f"signal={payload['spy_signal']} | "
            f"last_update={payload['last_update']}"
        )
        return True

    print(f"Push rejected: {response.status_code} {response.text}")
    return False


def main():
    load_env_file()

    print("SPY DASHBOARD PUSHER")
    print("NO AUTO BUY")
    print("NO AUTO SELL")
    print("NO BROKER CONNECTION")
    print(f"Reading status: {STATUS_FILE}")
    print(f"Reading predictions: {PREDICTION_FILE}")
    print(f"Pushing every {PUSH_EVERY_SECONDS} seconds")
    print("-" * 70)

    while True:
        payload = build_payload()
        push_status(payload)
        time.sleep(PUSH_EVERY_SECONDS)


if __name__ == "__main__":
    main()
