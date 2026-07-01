import json
import os
import time

import requests


STATUS_FILE = os.path.join("logs", "spy", "spy_live_status.json")
DEFAULT_UPDATE_URL = "https://latency-scanner-landing.onrender.com/api/scanner-status/update"
PUSH_EVERY_SECONDS = 30
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
        print(f"Status file not found: {path}")
        return {}
    except json.JSONDecodeError:
        print(f"Status file is not valid JSON: {path}")
        return {}
    except OSError as error:
        print(f"Could not read status file: {error}")
        return {}


def build_payload(status):
    now = time.time()

    try:
        update_epoch = float(status.get("update_epoch", 0))
    except (TypeError, ValueError):
        update_epoch = 0

    is_fresh = update_epoch > 0 and (now - update_epoch) <= STALE_AFTER_SECONDS

    try:
        current_spy_price = float(status.get("current_spy_price"))
    except (TypeError, ValueError):
        current_spy_price = None

    if is_fresh:
        public_message = "SPY scanner is online. Real-time CALL / PUT / WAIT signals are members-only."
    else:
        public_message = "SPY scanner status is stale or offline. Waiting for a fresh scanner update."

    return {
        "scanner_online": is_fresh,
        "scanner_type": "SPY Scanner + Signal Dashboard",
        "last_update": status.get("last_update", ""),
        "current_spy_price": current_spy_price,
        "spy_signal": "MEMBERS",
        "confidence": None,
        "market_regime": "--",
        "data_source": status.get("data_source", "--"),
        "public_message": public_message,
        "signal_visibility": "Real-time CALL / PUT / WAIT signals are members-only.",
        "research_verdict": "ACTIVE PAPER TESTING",
    }


def push_status(payload):
    update_url = os.environ.get("SCANNER_STATUS_UPDATE_URL", DEFAULT_UPDATE_URL).strip()
    token = os.environ.get("SCANNER_STATUS_UPDATE_TOKEN", "").strip()

    if not token:
        print("Missing SCANNER_STATUS_UPDATE_TOKEN in .env")
        return False

    headers = {
        "Content-Type": "application/json",
        "X-Scanner-Token": token,
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
            f"Pushed SPY status | online={payload['scanner_online']} | "
            f"price={payload['current_spy_price']} | "
            f"last_update={payload['last_update']}"
        )
        return True

    print(f"Push rejected: {response.status_code} {response.text}")
    return False


def main():
    load_env_file()

    print("SPY STATUS PUSHER")
    print("NO AUTO BUY")
    print("NO AUTO SELL")
    print("NO BROKER CONNECTION")
    print(f"Reading: {STATUS_FILE}")
    print(f"Pushing every {PUSH_EVERY_SECONDS} seconds")
    print("-" * 70)

    while True:
        status = read_json_file(STATUS_FILE)
        payload = build_payload(status)
        push_status(payload)
        time.sleep(PUSH_EVERY_SECONDS)


if __name__ == "__main__":
    main()