import csv
import os
import time
from datetime import datetime, time as clock_time
from zoneinfo import ZoneInfo

import requests


PREDICTION_FILE = os.path.join("logs", "spy", "spy_direction_predictions.csv")

EASTERN_TZ = ZoneInfo("America/New_York")

MARKET_START = clock_time(9, 30)
MARKET_END = clock_time(15, 30)

DEFAULT_MIN_CONFIDENCE = 60
DEFAULT_COOLDOWN_SECONDS = 120

POLL_SECONDS = 5


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


def safe_float(value, default=None):
    try:
        if value in ("", None, "N/A", "NA", "--"):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value, default=0):
    try:
        if value in ("", None, "N/A", "NA", "--"):
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def is_market_alert_window():
    now_et = datetime.now(EASTERN_TZ)

    if now_et.weekday() >= 5:
        return False, now_et, "Weekend"

    current_time = now_et.time()

    if current_time < MARKET_START:
        return False, now_et, "Before 9:30 AM Eastern"

    if current_time > MARKET_END:
        return False, now_et, "After 3:30 PM Eastern"

    return True, now_et, "Market alert window active"


def read_last_prediction():
    try:
        with open(PREDICTION_FILE, "r", encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file)
            last_row = None

            for row in reader:
                last_row = row

            return last_row or {}
    except FileNotFoundError:
        print(f"Prediction file not found: {PREDICTION_FILE}")
        return {}
    except OSError as error:
        print(f"Could not read prediction file: {error}")
        return {}


def get_env_int(name, default):
    return safe_int(os.environ.get(name), default)


def build_signal_key(row):
    return "|".join([
        row.get("time", ""),
        row.get("prediction", ""),
        row.get("spy_price", ""),
        row.get("confidence", ""),
        row.get("bullish_trigger", ""),
        row.get("bearish_trigger", ""),
    ])


def should_send_spy_alert(row, last_signal_key, last_sent_time):
    if not row:
        return False, "No prediction row"

    in_window, now_et, window_reason = is_market_alert_window()

    if not in_window:
        return False, window_reason

    prediction = (row.get("prediction") or "").upper().strip()
    confidence = safe_float(
        row.get("confidence") or row.get("total_confidence"),
        0,
    )

    min_confidence = get_env_int(
        "SPY_TELEGRAM_MIN_CONFIDENCE",
        DEFAULT_MIN_CONFIDENCE,
    )

    cooldown_seconds = get_env_int(
        "SPY_TELEGRAM_COOLDOWN_SECONDS",
        DEFAULT_COOLDOWN_SECONDS,
    )

    if prediction not in ("CALL", "PUT"):
        return False, f"Prediction is {prediction or 'blank'}"

    if confidence < min_confidence:
        return False, f"Confidence {confidence:.0f} below {min_confidence}"

    market_phase = (row.get("market_phase") or "").strip().lower()
    if market_phase == "market closed":
        return False, "Market phase says Market Closed"

    signal_key = build_signal_key(row)

    if signal_key == last_signal_key:
        return False, "Already sent this exact signal"

    now = time.time()

    if last_sent_time and now - last_sent_time < cooldown_seconds:
        seconds_left = int(cooldown_seconds - (now - last_sent_time))
        return False, f"Cooldown active: {seconds_left}s left"

    return True, "Send"


def build_message(row):
    prediction = (row.get("prediction") or "WAIT").upper().strip()
    confidence = safe_float(row.get("confidence") or row.get("total_confidence"), 0)
    spy_price = row.get("spy_price", "N/A")
    regime = row.get("regime") or row.get("market_regime") or "N/A"
    reason = row.get("reason", "N/A")
    vwap_position = row.get("vwap_position", "N/A")
    market_phase = row.get("market_phase", "N/A")

    bullish_trigger = row.get("bullish_trigger", "N/A")
    bullish_confirmation = row.get("bullish_confirmation", "N/A")
    bullish_breakout = row.get("bullish_breakout", "N/A")

    bearish_trigger = row.get("bearish_trigger", "N/A")
    bearish_confirmation = row.get("bearish_confirmation", "N/A")
    bearish_breakdown = row.get("bearish_breakdown", "N/A")

    nearest_support = row.get("nearest_support", "N/A")
    nearest_resistance = row.get("nearest_resistance", "N/A")

    entry = row.get("entry", "")
    stop_loss = row.get("stop_loss", "")
    target_1 = row.get("target_1", "")
    target_2 = row.get("target_2", "")

    now_et = datetime.now(EASTERN_TZ).strftime("%Y-%m-%d %I:%M:%S %p ET")

    if prediction == "CALL":
        level_text = (
            f"CALL levels:\n"
            f"Trigger: {bullish_trigger}\n"
            f"Confirm: {bullish_confirmation}\n"
            f"Breakout: {bullish_breakout}"
        )
    else:
        level_text = (
            f"PUT levels:\n"
            f"Trigger: {bearish_trigger}\n"
            f"Confirm: {bearish_confirmation}\n"
            f"Breakdown: {bearish_breakdown}"
        )

    trade_plan_lines = []
    if entry:
        trade_plan_lines.append(f"Entry: {entry}")
    if stop_loss:
        trade_plan_lines.append(f"Stop: {stop_loss}")
    if target_1:
        trade_plan_lines.append(f"TP1: {target_1}")
    if target_2:
        trade_plan_lines.append(f"TP2: {target_2}")

    trade_plan = "\n".join(trade_plan_lines) if trade_plan_lines else "Trade plan: wait for confirmation."

    return (
        f"SPY {prediction} ALERT\n"
        f"Notifications only. No auto buy. No auto sell.\n\n"
        f"Time: {now_et}\n"
        f"SPY: {spy_price}\n"
        f"Confidence: {confidence:.0f}\n"
        f"Regime: {regime}\n"
        f"Phase: {market_phase}\n"
        f"VWAP: {vwap_position}\n\n"
        f"{level_text}\n\n"
        f"Support: {nearest_support}\n"
        f"Resistance: {nearest_resistance}\n\n"
        f"{trade_plan}\n\n"
        f"Reason:\n{reason[:700]}"
    )


def send_telegram_message(message):
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = (
        os.environ.get("SPY_TELEGRAM_CHAT_ID", "").strip()
        or os.environ.get("TELEGRAM_MEMBER_CHAT_ID", "").strip()
    )

    if not bot_token:
        print("Missing TELEGRAM_BOT_TOKEN in .env")
        return False

    if not chat_id:
        print("Missing SPY_TELEGRAM_CHAT_ID in .env")
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    payload = {
        "chat_id": chat_id,
        "text": message,
        "disable_web_page_preview": True,
    }

    try:
        response = requests.post(url, json=payload, timeout=15)
    except requests.RequestException as error:
        print(f"Telegram send failed: {error}")
        return False

    if response.status_code == 200:
        print("SPY Telegram alert sent")
        return True

    print(f"Telegram send failed: {response.status_code} {response.text}")
    return False


def send_test_message():
    message = (
        "SPY TELEGRAM TEST\n"
        "Notifications only.\n"
        "No auto buy.\n"
        "No auto sell.\n"
        "No broker connection."
    )
    return send_telegram_message(message)


def main():
    load_env_file()

    print("SPY TELEGRAM NOTIFIER")
    print("NO AUTO BUY")
    print("NO AUTO SELL")
    print("NO BROKER CONNECTION")
    print("CALL / PUT notifications only")
    print("Alert window: 9:30 AM - 3:30 PM Eastern")
    print(f"Reading: {PREDICTION_FILE}")
    print("-" * 70)

    import sys

    if "--test" in sys.argv:
        send_test_message()
        return

    last_signal_key = None
    last_sent_time = 0

    while True:
        row = read_last_prediction()
        should_send, reason = should_send_spy_alert(
            row,
            last_signal_key,
            last_sent_time,
        )

        prediction = (row.get("prediction") or "N/A").upper()
        confidence = row.get("confidence") or row.get("total_confidence") or "N/A"
        price = row.get("spy_price") or "N/A"

        if should_send:
            message = build_message(row)

            if send_telegram_message(message):
                last_signal_key = build_signal_key(row)
                last_sent_time = time.time()
        else:
            print(
                f"Waiting | SPY: {price} | Signal: {prediction} | "
                f"Confidence: {confidence} | Reason: {reason}"
            )

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()