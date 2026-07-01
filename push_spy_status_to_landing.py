import csv
import json
import os
import time

import requests


LOG_DIR = os.path.join("logs", "spy")

STATUS_FILE = os.path.join(LOG_DIR, "spy_live_status.json")
SCAN_LOG_FILE = os.path.join(LOG_DIR, "spy_options_scan_log.csv")
PREDICTION_FILE = os.path.join(LOG_DIR, "spy_direction_predictions.csv")
MARKET_BREADTH_FILE = os.path.join(LOG_DIR, "spy_market_breadth.csv")
ENGINE_HEALTH_FILE = os.path.join(LOG_DIR, "spy_engine_health.csv")
ALERTS_FILE = os.path.join(LOG_DIR, "spy_options_alerts.csv")
LEVEL_HITS_FILE = os.path.join(LOG_DIR, "spy_level_hits.json")

DEFAULT_UPDATE_URL = "https://YOUR-SPY-RENDER-URL.onrender.com/api/push-status"

PUSH_EVERY_SECONDS = 10
STALE_AFTER_SECONDS = 180


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
    scan = read_last_csv_row(SCAN_LOG_FILE)
    prediction = read_last_csv_row(PREDICTION_FILE)
    breadth = read_last_csv_row(MARKET_BREADTH_FILE)
    engine = read_last_csv_row(ENGINE_HEALTH_FILE)
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
        "latest_alert": alert,
        "latest_level_hits": level_hits,
    }

    # Also flatten the latest prediction row into the top-level payload.
    # This helps the Render dashboard find whatever field names it already expects.
    for key, value in prediction.items():
        payload.setdefault(key, value)

    for key, value in scan.items():
        payload.setdefault(f"scan_{key}", value)

    for key, value in breadth.items():
        payload.setdefault(f"breadth_{key}", value)

    for key, value in engine.items():
        payload.setdefault(f"engine_{key}", value)

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
        print(f"Push failed: {error}")
        return False

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