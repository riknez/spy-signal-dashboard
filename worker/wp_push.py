"""Push the scanner's latest state to the Argus WordPress plugin.

Replaces push_spy_status_to_landing.py (Render). Differences:
  * Reads only the END of each log file (the old pusher re-read the whole
    1.16 GB predictions file every 3 seconds).
  * Signs every request with HMAC-SHA256 (shared secret, timestamp, body)
    instead of sending a bearer token.
  * Sends a compact, documented payload (schema 1) built for the WordPress
    dashboard. Signal values are copied from the logs, never recomputed.

Environment (.env next to the project, or real env vars):
  ARGUS_SPY_INGEST_URL     https://<site>/wp-json/argus-spy/v1/ingest
  ARGUS_SPY_INGEST_SECRET  same value as the wp-config.php constant
  SPY_LOG_DIR              scanner log folder (default: ./logs/spy)

Usage:  py worker/wp_push.py            (loop, every 3 s)
        py worker/wp_push.py --once     (single push, prints the response)
        py worker/wp_push.py --dry-run  (print payload size, send nothing)
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import hmac
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from market_session import EASTERN, session_state  # noqa: E402

PUSH_EVERY_SECONDS = 3
HISTORY_ROWS = 150          # ~5 minutes at the scanner's 2 s cadence
TABLE_ROWS = 25
SCHEMA = 1

LATEST_FIELDS = [
    "time", "spy_price", "prediction", "confidence", "total_confidence", "reason",
    "regime", "market_phase", "market_structure", "current_advantage",
    "reversal_state", "reversal_reason",
    "vwap", "vwap_position", "vwap_confirmation",
    "opening_range_high", "opening_range_low", "opening_range_position",
    "nearest_support", "support_reason", "nearest_resistance", "resistance_reason",
    "support_distance", "resistance_distance",
    "bullish_trigger", "bullish_confirmation", "bullish_breakout",
    "bearish_trigger", "bearish_confirmation", "bearish_breakdown",
    "invalid_level", "invalidation_reason", "confirmation_needed",
    "mtf_1m_status", "mtf_1m_reason", "mtf_3m_status", "mtf_3m_reason",
    "mtf_5m_status", "mtf_5m_reason", "mtf_overall_signal", "mtf_alignment",
    "trend_score", "momentum_score", "engine_score", "breadth_score",
    "volume_activity_score", "candle_score", "candle_indecision", "last_3_candle_reading",
    "volume_filter", "last_1m_bid_total", "activity_filter",
    "mode_stability", "previous_prediction", "mode_duration_minutes", "signal_flip_count_10m",
    "a_plus_setup", "a_plus_wait_reason", "confluence_score",
    "bullish_confluence_score", "bearish_confluence_score", "confluence_factors",
    "entry", "stop_loss", "target_1", "target_2", "risk_reward",
    "pre_market_bias", "pre_market_confidence", "pre_market_reason",
]


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


def read_header(path: str) -> list[str]:
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        return next(csv.reader([fh.readline()]), [])


def tail_lines(path: str, count: int, block: int = 65536) -> list[str]:
    """Last `count` complete lines of a (possibly huge) text file."""
    with open(path, "rb") as fh:
        fh.seek(0, os.SEEK_END)
        end = fh.tell()
        data = b""
        pos = end
        while pos > 0 and data.count(b"\n") <= count:
            step = min(block, pos)
            pos -= step
            fh.seek(pos)
            data = fh.read(step) + data
    lines = data.decode("utf-8", "replace").splitlines()
    if pos > 0:
        lines = lines[1:]          # first line may be partial
    return lines[-count:]


def tail_rows(path: str, count: int) -> list[dict]:
    if not os.path.exists(path):
        return []
    header = read_header(path)
    rows = []
    for line in tail_lines(path, count + 1):
        if not line.strip():
            continue
        values = next(csv.reader([line]), [])
        if not values or values == header:
            continue
        if header and values[0] == header[0]:
            continue
        rows.append(dict(zip(header, values)))
    return rows[-count:]


def read_json(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def num(value):
    try:
        if value in ("", None, "N/A", "None"):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


ALERT_HEADERS = ["time", "direction", "option_type", "symbol", "spy_price", "spy_change_percent"]


def alert_rows(path: str) -> list[dict]:
    """The existing alerts file still carries an older header line while its
    rows use the scanner's current 6-column layout, so map by position."""
    if not os.path.exists(path):
        return []
    rows = []
    for line in tail_lines(path, TABLE_ROWS + 1):
        values = next(csv.reader([line]), [])
        if len(values) == len(ALERT_HEADERS) and values[2] in ("CALL", "PUT"):
            rows.append(dict(zip(ALERT_HEADERS, values)))
    return rows[-TABLE_ROWS:]


def build_payload() -> dict:
    d = log_dir()
    pred_rows = tail_rows(os.path.join(d, "spy_direction_predictions.csv"), HISTORY_ROWS)
    latest = pred_rows[-1] if pred_rows else {}
    status = read_json(os.path.join(d, "spy_live_status.json"))
    worker = read_json(os.path.join(d, "worker_state.json"))
    perf = read_json(os.path.join(d, "spy_performance_summary.json"))
    state = session_state()

    engine_rows = tail_rows(os.path.join(d, "spy_engine_health.csv"), 40)
    engine = {}
    for row in engine_rows:
        if row.get("ticker"):
            engine[row["ticker"]] = {
                "price": num(row.get("price")),
                "day_change_percent": num(row.get("day_change_percent")),
                "status": row.get("status", ""),
                "time": row.get("time", ""),
            }
    breadth_rows = tail_rows(os.path.join(d, "spy_market_breadth.csv"), 1)

    now = time.time()
    update_epoch = num(status.get("update_epoch")) or 0
    return {
        "schema": SCHEMA,
        "sent_at": now,
        "sent_at_et": datetime.now(EASTERN).isoformat(timespec="seconds"),
        "session": {
            "label": state.label,
            "is_open": state.is_open,
            "session_date": state.session_date,
            "open_at": state.open_at.isoformat() if state.open_at else None,
            "close_at": state.close_at.isoformat() if state.close_at else None,
            "early_close": state.early_close,
            "next_open": state.next_open.isoformat(),
        },
        "scanner": {
            "last_update": status.get("last_update", ""),
            "update_epoch": update_epoch,
            "seconds_since_update": round(now - update_epoch, 1) if update_epoch else None,
            "price_age_seconds": num(status.get("price_age_seconds")),
            "data_source": status.get("data_source", ""),
            "running": bool(worker.get("scanner_running")),
            "restarts_this_session": worker.get("restarts_this_session"),
            "pc_sleep_detected_at": worker.get("pc_sleep_detected_at"),
        },
        "latest": {k: latest.get(k, "") for k in LATEST_FIELDS},
        "history": [
            {
                "t": r.get("time", ""),
                "p": num(r.get("spy_price")),
                "s": r.get("prediction", ""),
                "c": num(r.get("confidence")),
                "v": num(r.get("vwap")),
            }
            for r in pred_rows
        ],
        "engine": engine,
        "breadth": breadth_rows[-1] if breadth_rows else {},
        "alerts": alert_rows(os.path.join(d, "spy_options_alerts.csv")),
        "alert_results": tail_rows(os.path.join(d, "spy_options_alert_results.csv"), TABLE_ROWS),
        "signal_events": tail_rows(os.path.join(d, "spy_signal_events.csv"), TABLE_ROWS),
        "signal_results": tail_rows(os.path.join(d, "spy_signal_results.csv"), TABLE_ROWS),
        "performance": perf,
        "safety": {"no_auto_buy": True, "no_auto_sell": True, "no_broker_connection": True},
    }


def sign(secret: str, timestamp: str, body: bytes) -> str:
    message = timestamp.encode("ascii") + b"." + body
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def push(payload: dict, url: str, secret: str, timeout: float = 10.0):
    body = json.dumps(payload, separators=(",", ":"), default=str).encode("utf-8")
    ts = str(int(time.time()))
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "User-Agent": "argus-spy-pusher/1",
            "X-Argus-Spy-Timestamp": ts,
            "X-Argus-Spy-Signature": sign(secret, ts, body),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read(500).decode("utf-8", "replace"), len(body)
    except urllib.error.HTTPError as err:
        return err.code, err.read(500).decode("utf-8", "replace"), len(body)
    except (urllib.error.URLError, OSError) as err:
        return None, str(err), len(body)


def config() -> tuple[str, str]:
    load_env_file(os.path.join(ROOT, ".env"))
    url = os.environ.get("ARGUS_SPY_INGEST_URL", "").strip()
    secret = os.environ.get("ARGUS_SPY_INGEST_SECRET", "").strip()
    if not url.startswith("https://") and not url.startswith("http://127.0.0.1") and not url.startswith("http://localhost"):
        raise SystemExit("ARGUS_SPY_INGEST_URL must be an https:// URL (or a localhost staging URL).")
    if len(secret) < 32:
        raise SystemExit("ARGUS_SPY_INGEST_SECRET is missing or shorter than 32 characters.")
    return url, secret


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--every", type=float, default=PUSH_EVERY_SECONDS)
    args = ap.parse_args()

    if args.dry_run:
        load_env_file(os.path.join(ROOT, ".env"))
        p = build_payload()
        print(f"payload bytes={len(json.dumps(p, default=str))} history={len(p['history'])} "
              f"signal={p['latest'].get('prediction')} session={p['session']['label']}")
        return

    url, secret = config()
    failures = 0
    while True:
        started = time.time()
        status, text, size = push(build_payload(), url, secret)
        stamp = datetime.now(EASTERN).strftime("%H:%M:%S")
        if status == 200:
            failures = 0
            print(f"{stamp} push ok ({size} bytes)", flush=True)
        else:
            failures += 1
            print(f"{stamp} push FAILED status={status} {text[:200]}", flush=True)
        if args.once:
            sys.exit(0 if status == 200 else 1)
        # back off gently when the site is down; never hammer it
        wait = args.every if failures < 3 else min(60, args.every * failures)
        time.sleep(max(0.5, wait - (time.time() - started)))


if __name__ == "__main__":
    main()
