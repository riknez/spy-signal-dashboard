import csv
import json
import os
import time
from collections import deque
from datetime import datetime
from zoneinfo import ZoneInfo

import yfinance as yf


SYMBOL = "SPY"

PRICE_HISTORY = deque(maxlen=300)
BID_VOLUME_HISTORY = deque()
TRADE_ACTIVITY_HISTORY = deque()
SIGNAL_MODE_HISTORY = deque()

TIME_WINDOW_SECONDS = 10
SPY_MOVE_ALERT_PERCENT = 0.06
ALERT_COOLDOWN_SECONDS = 120
CONTINUATION_SECONDS = 2
MIN_CONTINUATION_MOVE = 0.02
TREND_CONFIRM_SECONDS = 30
MIN_TREND_CONFIRM_MOVE = 0.02
OVEREXTENSION_SECONDS = 60
MAX_OVEREXTENSION_MOVE = 0.90

LOG_DIR = "logs/spy"
LOG_FILE = "logs/spy/spy_options_alerts.csv"
SCAN_LOG_FILE = "logs/spy/spy_options_scan_log.csv"
RESULT_LOG_FILE = "logs/spy/spy_options_alert_results.csv"
A_PLUS_RESULT_LOG_FILE = "logs/spy/spy_options_a_plus_results.csv"
PREDICTION_LOG_FILE = "logs/spy/spy_direction_predictions.csv"
ENGINE_HEALTH_LOG_FILE = "logs/spy/spy_engine_health.csv"
MARKET_BREADTH_LOG_FILE = "logs/spy/spy_market_breadth.csv"
LIVE_STATUS_FILE = "logs/spy/spy_live_status.json"
LIVE_STATUS_TEMP_FILE = "logs/spy/spy_live_status.tmp"
MARKET_BREADTH_ETFS = ["SPY", "QQQ", "IWM"]
ENGINE_TICKERS = [
    "NVDA",
    "MSFT",
    "AAPL",
    "AMZN",
    "META",
    "GOOGL",
    "GOOG",
    "AVGO",
    "TSLA",
    "BRK-B",
    "JPM"
]
ENGINE_REFRESH_SECONDS = 60
ENGINE_NEUTRAL_THRESHOLD_PERCENT = 0.05
TRADE_PLAN_LOOKBACK_SECONDS = 60
TRADE_PLAN_MIN_RISK = 0.10
TRADE_PLAN_STRUCTURE_BUFFER = 0.02
MIN_1M_BID_TOTAL = 200
PREDICTION_HEADERS = [
    "time",
    "spy_price",
    "prediction",
    "confidence",
    "reason",
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
    "market_phase",
    "pre_market_bias",
    "pre_market_confidence",
    "pre_market_reason",
    "pre_market_high",
    "pre_market_low",
    "pre_market_spy_move",
    "pre_market_qqq_move",
    "pre_market_volume",
    "pre_market_relative_volume",
    "a_plus_setup",
    "confluence_score",
    "bullish_confluence_score",
    "bearish_confluence_score",
    "a_plus_wait_reason",
    "confluence_factors"
]
RESULT_HEADERS = [
    "time",
    "option_type",
    "entry_spy_price",
    "price_after_30s",
    "price_after_60s",
    "price_after_120s",
    "move_30s",
    "move_60s",
    "move_120s",
    "best_move",
    "worst_move",
    "confirmed_30s",
    "result"
]

last_alert_time = 0
scan_count = 0
threshold_pass_count = 0
continuation_fail_count = 0
trend_fail_count = 0
overextension_fail_count = 0
alert_allowed_count = 0
last_diagnostic_print_time = 0
last_engine_health_time = 0
engine_health_rows = []
engine_score = 0.0
engine_bias = "MIXED"
market_breadth_classification = "Neutral"
last_spy_volume_bar = None
last_spy_volume_value = 0
current_mode_prediction = "WAIT"
last_directional_prediction = None
current_mode_started_at = time.time()
last_stability_candle_key = None
pending_opposite_direction = None
pending_opposite_count = 0
pre_market_open_price = None
pre_market_high = None
pre_market_low = None
pre_market_volume_samples = deque(maxlen=15)
yesterday_midpoint_cache_date = None
yesterday_midpoint_cache_value = None


def resample_completed_candles(completed_one_minute, minutes, count=20):
    timeframe = completed_one_minute.resample(
        f"{minutes}min",
        label="left",
        closed="left"
    ).agg({
        "Open": "first",
        "High": "max",
        "Low": "min",
        "Close": "last",
        "Volume": "count"
    })
    timeframe = timeframe[timeframe["Volume"] >= minutes].dropna()

    return [
        {
            "time": str(candle_time),
            "open": float(row["Open"]),
            "high": float(row["High"]),
            "low": float(row["Low"]),
            "close": float(row["Close"]),
            "completed_epoch": float(candle_time.timestamp()) + (minutes * 60)
        }
        for candle_time, row in timeframe.tail(count).iterrows()
    ]


def get_spy_snapshot():
    ticker = yf.Ticker(SYMBOL)
    data = ticker.history(period="1d", interval="1m", prepost=True)

    if data.empty:
        return (
            None, None, None, [], {}, None, "Mixed",
            None, None, "Inside"
        )

    last_price = data["Close"].iloc[-1]
    try:
        fast_price = ticker.fast_info.get("last_price")
        if fast_price is not None and float(fast_price) > 0:
            last_price = float(fast_price)
    except Exception:
        pass
    last_volume = data["Volume"].iloc[-1]
    last_bar = str(data.index[-1])
    completed_candles = []
    total_volume = float(data["Volume"].sum())
    typical_price = (data["High"] + data["Low"] + data["Close"]) / 3
    vwap = (
        float((typical_price * data["Volume"]).sum() / total_volume)
        if total_volume > 0 else None
    )
    recent_positions = []

    if vwap is not None:
        for close in data["Close"].tail(10):
            if float(close) > vwap:
                recent_positions.append("Above")
            elif float(close) < vwap:
                recent_positions.append("Below")

    vwap_crosses = sum(
        1
        for index in range(1, len(recent_positions))
        if recent_positions[index] != recent_positions[index - 1]
    )

    if vwap is None or vwap_crosses >= 3:
        vwap_position = "Mixed"
    elif float(last_price) > vwap:
        vwap_position = "Above"
    elif float(last_price) < vwap:
        vwap_position = "Below"
    else:
        vwap_position = "Mixed"

    opening_range_rows = []

    for candle_time, row in data.iterrows():
        local_time = candle_time

        try:
            local_time = candle_time.tz_convert("America/New_York")
        except (AttributeError, TypeError):
            pass

        minutes_after_midnight = (local_time.hour * 60) + local_time.minute

        if 570 <= minutes_after_midnight < 575:
            opening_range_rows.append(row)

    if opening_range_rows:
        opening_range_high = max(float(row["High"]) for row in opening_range_rows)
        opening_range_low = min(float(row["Low"]) for row in opening_range_rows)

        if float(last_price) > opening_range_high:
            opening_range_position = "Above"
        elif float(last_price) < opening_range_low:
            opening_range_position = "Below"
        else:
            opening_range_position = "Inside"
    else:
        opening_range_high = None
        opening_range_low = None
        opening_range_position = "Inside"

    completed_one_minute = data.iloc[:-1]
    timeframe_candles = {
        "1m": resample_completed_candles(completed_one_minute, 1),
        "3m": resample_completed_candles(completed_one_minute, 3),
        "5m": resample_completed_candles(completed_one_minute, 5)
    }
    completed_candles = timeframe_candles["5m"]

    return (
        float(last_price),
        float(last_volume),
        last_bar,
        completed_candles,
        timeframe_candles,
        vwap,
        vwap_position,
        opening_range_high,
        opening_range_low,
        opening_range_position
    )


def get_spy_price():
    spy_price, _, _, _, _, _, _, _, _, _ = get_spy_snapshot()
    return spy_price


def get_market_phase():
    eastern_now = datetime.now(ZoneInfo("America/New_York"))
    minutes = eastern_now.hour * 60 + eastern_now.minute
    if 555 <= minutes < 570:
        return "Pre-Market Analysis"
    if 570 <= minutes < 575:
        return "Opening Range"
    if 575 <= minutes < 630:
        return "Opening Momentum"
    if 630 <= minutes < 690:
        return "Caution Window"
    if 690 <= minutes < 900:
        return "Midday Chop"
    if 900 <= minutes < 960:
        return "Power Hour"
    return "Market Closed"


def build_pre_market_analysis(spy_price, spy_bar_volume, vwap, engine_bias,
                              breadth_classification, trend_move, momentum_move):
    global pre_market_open_price, pre_market_high, pre_market_low

    market_phase = get_market_phase()
    if market_phase == "Pre-Market Analysis":
        if pre_market_open_price is None:
            pre_market_open_price = spy_price
        pre_market_high = spy_price if pre_market_high is None else max(pre_market_high, spy_price)
        pre_market_low = spy_price if pre_market_low is None else min(pre_market_low, spy_price)
        pre_market_volume_samples.append(float(spy_bar_volume or 0))

    try:
        qqq_data = yf.Ticker("QQQ").history(period="1d", interval="1m", prepost=True)
        qqq_move = percent_change(
            float(qqq_data["Close"].iloc[-1]),
            float(qqq_data["Close"].iloc[0])
        ) if len(qqq_data) >= 2 else None
    except Exception:
        qqq_move = None

    spy_move = percent_change(spy_price, pre_market_open_price) if pre_market_open_price else 0
    volume = float(spy_bar_volume or 0)
    average_volume = sum(pre_market_volume_samples) / len(pre_market_volume_samples) if pre_market_volume_samples else 0
    relative_volume = volume / average_volume if average_volume > 0 else 0
    bullish_points = 0
    bearish_points = 0
    reasons = []

    evidence = [
        (vwap is not None and spy_price > vwap, vwap is not None and spy_price < vwap, 2, "SPY above VWAP", "SPY below VWAP"),
        (qqq_move is not None and qqq_move > 0, qqq_move is not None and qqq_move < 0, 1, "QQQ strong", "QQQ weak"),
        (engine_bias == "BULLISH", engine_bias == "BEARISH", 2, "Engine Health bullish", "Engine Health bearish"),
        (breadth_classification == "Strong Bullish", breadth_classification == "Strong Bearish", 1, "Market Breadth bullish", "Market Breadth bearish"),
        ((trend_move or 0) > 0, (trend_move or 0) < 0, 1, "Trend positive", "Trend negative"),
        ((momentum_move or 0) > 0, (momentum_move or 0) < 0, 1, "Momentum positive", "Momentum negative")
    ]
    for bullish, bearish, points, bullish_reason, bearish_reason in evidence:
        if bullish:
            bullish_points += points
            reasons.append(bullish_reason)
        elif bearish:
            bearish_points += points
            reasons.append(bearish_reason)
    if relative_volume >= 1:
        reasons.append("Volume above average")

    confidence = min(100, round(max(bullish_points, bearish_points) / 8 * 100))
    bias = "BULLISH" if bullish_points >= bearish_points + 2 else (
        "BEARISH" if bearish_points >= bullish_points + 2 else "NEUTRAL"
    )
    return {
        "market_phase": market_phase,
        "pre_market_bias": bias,
        "pre_market_confidence": confidence,
        "pre_market_reason": "; ".join(reasons[:5]) or "Pre-market evidence is mixed",
        "pre_market_high": pre_market_high,
        "pre_market_low": pre_market_low,
        "pre_market_spy_move": spy_move,
        "pre_market_qqq_move": qqq_move,
        "pre_market_volume": volume,
        "pre_market_relative_volume": relative_volume
    }


def opening_confirmation_ready(timeframe_candles):
    eastern_now = datetime.now(ZoneInfo("America/New_York"))
    minutes = eastern_now.hour * 60 + eastern_now.minute
    if not 570 <= minutes < 575:
        return True
    return any(
        "09:30:" in candle.get("time", "") or "09:31:" in candle.get("time", "")
        for candle in timeframe_candles.get("1m", [])
    )


def update_rolling_bid_volume(now, bar_key, current_volume):
    global last_spy_volume_bar
    global last_spy_volume_value

    if bar_key is not None and current_volume is not None:
        if bar_key != last_spy_volume_bar:
            volume_delta = max(0, current_volume)
            last_spy_volume_bar = bar_key
            last_spy_volume_value = current_volume
        else:
            volume_delta = max(0, current_volume - last_spy_volume_value)
            last_spy_volume_value = current_volume

        if volume_delta > 0:
            BID_VOLUME_HISTORY.append((now, volume_delta))

    while BID_VOLUME_HISTORY and now - BID_VOLUME_HISTORY[0][0] > 60:
        BID_VOLUME_HISTORY.popleft()

    last_1m_bid_total = sum(volume for _, volume in BID_VOLUME_HISTORY)
    last_1m_bid_average = (
        last_1m_bid_total / len(BID_VOLUME_HISTORY)
        if BID_VOLUME_HISTORY else 0
    )
    volume_filter = (
        "PASS" if last_1m_bid_total >= MIN_1M_BID_TOTAL else "FAIL"
    )

    return last_1m_bid_total, last_1m_bid_average, volume_filter


def prune_trade_activity(now):
    while TRADE_ACTIVITY_HISTORY and now - TRADE_ACTIVITY_HISTORY[0][0] > 1800:
        TRADE_ACTIVITY_HISTORY.popleft()


def get_activity_filter(trade_count):
    if trade_count >= 200:
        return "ACTIVE"
    if trade_count >= 50:
        return "NORMAL"
    return "SLOW"


def get_trade_activity_snapshot(now, include_next_event=False):
    prune_trade_activity(now)
    rolling_30m_trade_count = len(TRADE_ACTIVITY_HISTORY)

    if include_next_event:
        rolling_30m_trade_count += 1

    rolling_30m_call_count = sum(
        1 for _, prediction in TRADE_ACTIVITY_HISTORY
        if prediction == "CALL"
    )
    rolling_30m_put_count = sum(
        1 for _, prediction in TRADE_ACTIVITY_HISTORY
        if prediction == "PUT"
    )
    rolling_30m_wait_count = sum(
        1 for _, prediction in TRADE_ACTIVITY_HISTORY
        if prediction == "WAIT"
    )

    return {
        "rolling_30m_trade_count": rolling_30m_trade_count,
        "rolling_30m_call_count": rolling_30m_call_count,
        "rolling_30m_put_count": rolling_30m_put_count,
        "rolling_30m_wait_count": rolling_30m_wait_count,
        "avg_trades_per_min_30m": rolling_30m_trade_count / 30,
        "activity_filter": get_activity_filter(rolling_30m_trade_count)
    }


def record_trade_activity(now, prediction):
    TRADE_ACTIVITY_HISTORY.append((now, prediction))
    return get_trade_activity_snapshot(now)


def get_old_value(history, seconds_ago):
    now = time.time()

    for timestamp, value in history:
        if now - timestamp >= seconds_ago:
            return value

    return None


def get_recent_price_change(history, seconds_ago):
    old_price = get_old_value(history, seconds_ago)
    if old_price is None:
        return None
    current_price = history[-1][1]
    return current_price - old_price


def get_absolute_price_move(history, seconds_ago):
    old_price = get_old_value(history, seconds_ago)
    if old_price is None:
        return None
    current_price = history[-1][1]
    return abs(current_price - old_price)


def format_optional_move(move):
    if move is None:
        return "N/A"

    return f"{move:.4f}"


def format_optional_price(price):
    if price is None:
        return ""

    return f"{price:.4f}"


def format_risk_reward(risk_reward):
    if risk_reward is None:
        return ""

    return f"1:{risk_reward:.2f}"


def percent_change(current_price, old_price):
    return ((current_price - old_price) / old_price) * 100


def ensure_log_dir():
    os.makedirs(LOG_DIR, exist_ok=True)


def save_live_status(spy_price, now):
    ensure_log_dir()
    status = {
        "current_spy_price": round(spy_price, 4),
        "last_update": time.strftime("%Y-%m-%d %H:%M:%S"),
        "update_epoch": now,
        "data_source": "yfinance fast_info + SPY 1m"
    }

    with open(LIVE_STATUS_TEMP_FILE, "w", encoding="utf-8") as file:
        json.dump(status, file)

    os.replace(LIVE_STATUS_TEMP_FILE, LIVE_STATUS_FILE)


def save_scan_row(spy_price, spy_change_percent):
    ensure_log_dir()
    current_time = time.strftime("%Y-%m-%d %H:%M:%S")

    file_exists = False

    try:
        with open(SCAN_LOG_FILE, "r", newline="") as file:
            file_exists = True
    except FileNotFoundError:
        file_exists = False

    with open(SCAN_LOG_FILE, "a", newline="") as file:
        writer = csv.writer(file)

        if not file_exists:
            writer.writerow([
                "time",
                "symbol",
                "spy_price",
                "spy_change_percent"
            ])

        writer.writerow([
            current_time,
            SYMBOL,
            f"{spy_price:.4f}",
            f"{spy_change_percent:.4f}"
        ])


def save_alert(direction, option_type, spy_price, spy_change_percent):
    ensure_log_dir()
    current_time = time.strftime("%Y-%m-%d %H:%M:%S")

    file_exists = False

    try:
        with open(LOG_FILE, "r", newline="") as file:
            file_exists = True
    except FileNotFoundError:
        file_exists = False

    with open(LOG_FILE, "a", newline="") as file:
        writer = csv.writer(file)

        if not file_exists:
            writer.writerow([
                "time",
                "direction",
                "option_type",
                "symbol",
                "spy_price",
                "spy_change_percent"
            ])

        writer.writerow([
            current_time,
            direction,
            option_type,
            SYMBOL,
            f"{spy_price:.4f}",
            f"{spy_change_percent:.4f}"
        ])


def get_engine_status(day_change_percent):
    if day_change_percent > ENGINE_NEUTRAL_THRESHOLD_PERCENT:
        return "Bullish"
    if day_change_percent < -ENGINE_NEUTRAL_THRESHOLD_PERCENT:
        return "Bearish"
    return "Neutral"


def calculate_engine_summary(rows):
    bullish_count = sum(1 for row in rows if row["status"] == "Bullish")
    bearish_count = sum(1 for row in rows if row["status"] == "Bearish")
    total_count = len(rows)

    if not total_count:
        return 0.0, "MIXED"

    score = ((bullish_count - bearish_count) / total_count) * 100

    if score >= 20:
        bias = "BULLISH"
    elif score <= -20:
        bias = "BEARISH"
    else:
        bias = "MIXED"

    return score, bias


def save_engine_health_rows(rows):
    ensure_log_dir()
    current_time = time.strftime("%Y-%m-%d %H:%M:%S")
    file_exists = os.path.exists(ENGINE_HEALTH_LOG_FILE)

    with open(ENGINE_HEALTH_LOG_FILE, "a", newline="") as file:
        writer = csv.writer(file)

        if not file_exists:
            writer.writerow([
                "time",
                "ticker",
                "price",
                "day_change_percent",
                "status"
            ])

        for row in rows:
            writer.writerow([
                current_time,
                row["ticker"],
                f"{row['price']:.4f}",
                f"{row['day_change_percent']:.4f}",
                row["status"]
            ])


def refresh_engine_health():
    rows = []

    for ticker_symbol in ENGINE_TICKERS:
        try:
            data = yf.Ticker(ticker_symbol).history(period="5d", interval="1d")

            if len(data) < 2:
                continue

            price = float(data["Close"].iloc[-1])
            previous_close = float(data["Close"].iloc[-2])
            day_change_percent = percent_change(price, previous_close)
            rows.append({
                "ticker": ticker_symbol,
                "price": price,
                "day_change_percent": day_change_percent,
                "status": get_engine_status(day_change_percent)
            })
        except Exception as error:
            print(f"Could not update engine health for {ticker_symbol}: {error}")

    if rows:
        save_engine_health_rows(rows)

    return rows


def get_daily_market_row(ticker_symbol):
    data = yf.Ticker(ticker_symbol).history(period="5d", interval="1d")

    if len(data) < 2:
        return None

    price = float(data["Close"].iloc[-1])
    previous_close = float(data["Close"].iloc[-2])
    day_change_percent = percent_change(price, previous_close)

    return {
        "ticker": ticker_symbol,
        "price": price,
        "day_change_percent": day_change_percent,
        "status": get_engine_status(day_change_percent)
    }


def calculate_market_breadth(etf_rows, stock_rows):
    advancing = sum(1 for row in stock_rows if row["status"] == "Bullish")
    declining = sum(1 for row in stock_rows if row["status"] == "Bearish")
    neutral = sum(1 for row in stock_rows if row["status"] == "Neutral")
    bullish_etfs = sum(1 for row in etf_rows if row["status"] == "Bullish")
    bearish_etfs = sum(1 for row in etf_rows if row["status"] == "Bearish")
    directional_stocks = advancing + declining
    advance_percent = (
        (advancing / directional_stocks) * 100
        if directional_stocks else 50.0
    )

    if bullish_etfs >= 2 and advance_percent >= 60:
        classification = "Strong Bullish"
    elif bearish_etfs >= 2 and advance_percent <= 40:
        classification = "Strong Bearish"
    else:
        classification = "Neutral"

    return {
        "classification": classification,
        "advancing": advancing,
        "declining": declining,
        "neutral": neutral,
        "advance_percent": advance_percent
    }


def save_market_breadth(etf_rows, breadth):
    ensure_log_dir()
    current_time = time.strftime("%Y-%m-%d %H:%M:%S")
    file_exists = os.path.exists(MARKET_BREADTH_LOG_FILE)
    etf_changes = {
        row["ticker"]: row["day_change_percent"]
        for row in etf_rows
    }

    with open(MARKET_BREADTH_LOG_FILE, "a", newline="") as file:
        writer = csv.writer(file)

        if not file_exists:
            writer.writerow([
                "time",
                "classification",
                "advancing",
                "declining",
                "neutral",
                "advance_percent",
                "spy_change_percent",
                "qqq_change_percent",
                "iwm_change_percent"
            ])

        writer.writerow([
            current_time,
            breadth["classification"],
            breadth["advancing"],
            breadth["declining"],
            breadth["neutral"],
            f"{breadth['advance_percent']:.2f}",
            f"{etf_changes.get('SPY', 0):.4f}",
            f"{etf_changes.get('QQQ', 0):.4f}",
            f"{etf_changes.get('IWM', 0):.4f}"
        ])


def refresh_market_breadth(stock_rows):
    etf_rows = []

    for ticker_symbol in MARKET_BREADTH_ETFS:
        try:
            row = get_daily_market_row(ticker_symbol)

            if row:
                etf_rows.append(row)
        except Exception as error:
            print(f"Could not update market breadth for {ticker_symbol}: {error}")

    if not etf_rows or not stock_rows:
        return None

    breadth = calculate_market_breadth(etf_rows, stock_rows)
    save_market_breadth(etf_rows, breadth)
    return breadth


def generate_trade_plan(history, prediction):
    if prediction not in ("CALL", "PUT") or not history:
        return {
            "entry": None,
            "stop_loss": None,
            "target_1": None,
            "target_2": None,
            "risk_reward": None
        }

    now = time.time()
    recent_prices = [
        price
        for timestamp, price in history
        if now - timestamp <= TRADE_PLAN_LOOKBACK_SECONDS
    ]

    if not recent_prices:
        recent_prices = [history[-1][1]]

    entry = history[-1][1]
    support = min(recent_prices)
    resistance = max(recent_prices)

    if prediction == "CALL":
        stop_loss = min(
            support - TRADE_PLAN_STRUCTURE_BUFFER,
            entry - TRADE_PLAN_MIN_RISK
        )
        risk = entry - stop_loss
        target_1 = max(resistance, entry + risk)
        target_2 = max(entry + (risk * 2), target_1 + risk)
        reward = target_2 - entry
    else:
        stop_loss = max(
            resistance + TRADE_PLAN_STRUCTURE_BUFFER,
            entry + TRADE_PLAN_MIN_RISK
        )
        risk = stop_loss - entry
        target_1 = min(support, entry - risk)
        target_2 = min(entry - (risk * 2), target_1 - risk)
        reward = entry - target_2

    return {
        "entry": entry,
        "stop_loss": stop_loss,
        "target_1": target_1,
        "target_2": target_2,
        "risk_reward": reward / risk if risk > 0 else None
    }


def detect_scanner_regime(history):
    prices = [price for _, price in list(history)[-45:]]

    if len(prices) < 9:
        return "CHOPPY"

    third = len(prices) // 3
    first = prices[:third]
    middle = prices[third:third * 2]
    last = prices[third * 2:]
    average_price = sum(prices) / len(prices)
    range_percent = (
        ((max(prices) - min(prices)) / average_price) * 100
        if average_price else 0
    )
    higher = max(first) < max(middle) < max(last) and min(first) < min(middle) < min(last)
    lower = max(first) > max(middle) > max(last) and min(first) > min(middle) > min(last)
    prior_move = middle[-1] - first[0]
    recent_move = last[-1] - last[0]

    if higher:
        return "TRENDING UP"
    if lower:
        return "TRENDING DOWN"
    if abs(prior_move) > 0.05 and abs(recent_move) < abs(prior_move) * 0.40:
        return "REVERSAL RISK"
    if range_percent <= 0.06:
        return "CHOPPY"
    return "CHOPPY"


def analyze_completed_candles(candles):
    if len(candles) < 3:
        return {
            "bullish_score": 0,
            "bearish_score": 0,
            "candle_score": 0,
            "candle_analysis_score": 0,
            "indecision": True,
            "direction": "Mixed",
            "reason": "fewer than 3 completed candles",
            "reading": "Waiting for three completed 5-minute candles."
        }

    analyzed = []

    for candle in candles[-3:]:
        body_size = abs(candle["close"] - candle["open"])
        candle_range = max(candle["high"] - candle["low"], 0.0001)
        upper_wick = candle["high"] - max(candle["open"], candle["close"])
        lower_wick = min(candle["open"], candle["close"]) - candle["low"]
        close_location = (candle["close"] - candle["low"]) / candle_range
        analyzed.append({
            **candle,
            "body_size": body_size,
            "upper_wick": upper_wick,
            "lower_wick": lower_wick,
            "range": candle_range,
            "bullish": candle["close"] > candle["open"],
            "bearish": candle["close"] < candle["open"],
            "doji": body_size / candle_range <= 0.15,
            "close_location": close_location,
            "buyer_rejection": (
                lower_wick / candle_range >= 0.35
                and close_location >= 0.60
            ),
            "seller_rejection": (
                upper_wick / candle_range >= 0.35
                and close_location <= 0.40
            ),
            "long_both_wicks": (
                upper_wick / candle_range >= 0.30
                and lower_wick / candle_range >= 0.30
            )
        })

    bullish_score = 0
    bearish_score = 0
    bullish_count = sum(1 for candle in analyzed if candle["bullish"])
    bearish_count = sum(1 for candle in analyzed if candle["bearish"])
    closes = [candle["close"] for candle in analyzed]
    bodies = [candle["body_size"] for candle in analyzed]

    if bullish_count == 3:
        bullish_score += 6
    if bearish_count == 3:
        bearish_score += 6
    if bodies[0] < bodies[1] < bodies[2]:
        if analyzed[-1]["bullish"]:
            bullish_score += 4
        elif analyzed[-1]["bearish"]:
            bearish_score += 4
    if closes[0] < closes[1] < closes[2]:
        bullish_score += 5
    if closes[0] > closes[1] > closes[2]:
        bearish_score += 5

    for candle in analyzed:
        close_from_low = (candle["close"] - candle["low"]) / candle["range"]
        close_from_high = (candle["high"] - candle["close"]) / candle["range"]

        if candle["bullish"] and close_from_low >= 0.80:
            bullish_score += 2
        if candle["bearish"] and close_from_high >= 0.80:
            bearish_score += 2

    inside_count = sum(
        1
        for index in range(1, len(analyzed))
        if (
            analyzed[index]["high"] <= analyzed[index - 1]["high"]
            and analyzed[index]["low"] >= analyzed[index - 1]["low"]
        )
    )
    doji_count = sum(1 for candle in analyzed if candle["doji"])
    buyer_rejection_count = sum(
        1 for candle in analyzed if candle["buyer_rejection"]
    )
    seller_rejection_count = sum(
        1 for candle in analyzed if candle["seller_rejection"]
    )
    long_wick_count = sum(
        1 for candle in analyzed if candle["long_both_wicks"]
    )
    mixed_direction = bullish_count > 0 and bearish_count > 0
    indecision = (
        doji_count >= 2
        or long_wick_count >= 2
        or inside_count >= 1
        or mixed_direction
    )
    penalty = (doji_count * 2) + (long_wick_count * 2) + (inside_count * 2)

    if mixed_direction:
        penalty += 4

    bullish_score = max(0, min(20, bullish_score - penalty))
    bearish_score = max(0, min(20, bearish_score - penalty))
    candle_score = max(bullish_score, bearish_score)
    close_description = (
        "latest close near the high"
        if analyzed[-1]["close_location"] >= 0.75
        else "latest close near the low"
        if analyzed[-1]["close_location"] <= 0.25
        else "latest close near the middle"
    )
    reading = (
        f"{bullish_count} bullish and {bearish_count} bearish candles; "
        f"{buyer_rejection_count} buyer rejection and "
        f"{seller_rejection_count} seller rejection candles; "
        f"{doji_count} doji, {inside_count} inside candle; "
        f"{close_description}."
    )

    return {
        "bullish_score": bullish_score,
        "bearish_score": bearish_score,
        "candle_score": candle_score,
        "candle_analysis_score": min(15, round(candle_score * 0.75)),
        "indecision": indecision,
        "direction": (
            "Bullish" if bullish_count == 3
            else "Bearish" if bearish_count == 3
            else "Mixed"
        ),
        "reason": (
            f"bull {bullish_score}, bear {bearish_score}, "
            f"doji {doji_count}, long-wick {long_wick_count}, "
            f"inside {inside_count}, mixed {mixed_direction}"
        ),
        "reading": reading
    }


def classify_market_structure(candles):
    if len(candles) < 3:
        return "Range / chop"

    recent = candles[-3:]
    highs = [candle["high"] for candle in recent]
    lows = [candle["low"] for candle in recent]
    higher_highs = highs[0] < highs[1] < highs[2]
    higher_lows = lows[0] < lows[1] < lows[2]
    lower_highs = highs[0] > highs[1] > highs[2]
    lower_lows = lows[0] > lows[1] > lows[2]

    if higher_highs and higher_lows:
        return "Higher highs and higher lows"
    if lower_highs and lower_lows:
        return "Lower highs and lower lows"
    if higher_highs:
        return "Higher highs without confirmed higher lows"
    if higher_lows:
        return "Higher lows without confirmed higher highs"
    if lower_highs:
        return "Lower highs without confirmed lower lows"
    if lower_lows:
        return "Lower lows without confirmed lower highs"
    return "Range / chop"


def analyze_timeframe(candles, vwap):
    if len(candles) < 3:
        return {
            "status": "Neutral",
            "reason": "Waiting for three completed candles."
        }

    recent = candles[-3:]
    structure = classify_market_structure(recent)
    candle_analysis = analyze_completed_candles(recent)
    latest = recent[-1]
    latest_range = max(latest["high"] - latest["low"], 0.0001)
    upper_wick = latest["high"] - max(latest["open"], latest["close"])
    lower_wick = min(latest["open"], latest["close"]) - latest["low"]
    momentum = recent[-1]["close"] - recent[0]["close"]
    bullish_points = 0
    bearish_points = 0
    evidence = []

    if structure.startswith("Higher"):
        bullish_points += 2
        evidence.append("higher structure")
    elif structure.startswith("Lower"):
        bearish_points += 2
        evidence.append("lower structure")
    else:
        evidence.append("range structure")

    if candle_analysis["bullish_score"] > candle_analysis["bearish_score"]:
        bullish_points += 2
        evidence.append("bullish last-three-candle read")
    elif candle_analysis["bearish_score"] > candle_analysis["bullish_score"]:
        bearish_points += 2
        evidence.append("bearish last-three-candle read")
    else:
        evidence.append("mixed candles")

    if lower_wick / latest_range >= 0.30:
        bullish_points += 1
        evidence.append("lower-wick buyer rejection")
    if upper_wick / latest_range >= 0.30:
        bearish_points += 1
        evidence.append("upper-wick seller rejection")

    if momentum > 0:
        bullish_points += 2
        evidence.append("positive momentum")
    elif momentum < 0:
        bearish_points += 2
        evidence.append("negative momentum")

    if vwap is not None and latest["close"] > vwap:
        bullish_points += 1
        evidence.append("above VWAP")
    elif vwap is not None and latest["close"] < vwap:
        bearish_points += 1
        evidence.append("below VWAP")
    else:
        evidence.append("at VWAP")

    if bullish_points >= bearish_points + 2:
        status = "Bullish"
    elif bearish_points >= bullish_points + 2:
        status = "Bearish"
    else:
        status = "Neutral"

    return {
        "status": status,
        "reason": (
            f"{structure}; {', '.join(evidence)} "
            f"(bull {bullish_points}, bear {bearish_points})."
        )
    }


def build_multi_timeframe_analysis(timeframe_candles, vwap):
    readings = {
        timeframe: analyze_timeframe(timeframe_candles.get(timeframe, []), vwap)
        for timeframe in ("1m", "3m", "5m")
    }
    statuses = [readings[timeframe]["status"] for timeframe in ("1m", "3m", "5m")]
    bullish_count = statuses.count("Bullish")
    bearish_count = statuses.count("Bearish")

    if bullish_count == 3:
        overall_signal = "Strong CALL"
    elif bullish_count == 2:
        overall_signal = "CALL"
    elif bearish_count == 3:
        overall_signal = "Strong PUT"
    elif bearish_count == 2:
        overall_signal = "PUT"
    else:
        overall_signal = "WAIT"

    if len(set(statuses)) == 1:
        alignment = "High Conviction"
    elif len(set(statuses)) == 3:
        alignment = "CHOPPY"
        overall_signal = "WAIT"
    elif statuses[0] == statuses[1]:
        alignment = "Early Warning"
    else:
        alignment = "Mixed"

    return {
        "mtf_1m_status": readings["1m"]["status"],
        "mtf_1m_reason": readings["1m"]["reason"],
        "mtf_3m_status": readings["3m"]["status"],
        "mtf_3m_reason": readings["3m"]["reason"],
        "mtf_5m_status": readings["5m"]["status"],
        "mtf_5m_reason": readings["5m"]["reason"],
        "mtf_overall_signal": overall_signal,
        "mtf_alignment": alignment
    }


def build_confirmation_levels(
    current_price,
    timeframe_candles
):
    timeframe_weights = {"1m": 0.50, "3m": 0.30, "5m": 0.20}
    all_candles = [
        candle
        for timeframe in ("1m", "3m", "5m")
        for candle in timeframe_candles.get(timeframe, [])[-20:]
    ]
    ranges = [
        candle["high"] - candle["low"]
        for candle in all_candles
        if candle["high"] > candle["low"]
    ]
    average_range = sum(ranges) / len(ranges) if ranges else 0.20
    max_distance = current_price * 0.005
    fallback_step = min(
        max_distance / 3,
        max(0.02, average_range * 0.25)
    )

    def ranked_levels(side):
        candidates = {}

        for timeframe in ("1m", "3m", "5m"):
            weight = timeframe_weights[timeframe]
            for candle in timeframe_candles.get(timeframe, [])[-20:]:
                level = candle["high"] if side == "bullish" else candle["low"]
                valid = (
                    current_price < level <= current_price + max_distance
                    if side == "bullish"
                    else current_price - max_distance <= level < current_price
                )
                if not valid:
                    continue

                rounded_level = round(level, 2)
                candidates[rounded_level] = max(
                    weight,
                    candidates.get(rounded_level, 0)
                )

        ranked = sorted(
            candidates.items(),
            key=lambda item: (abs(item[0] - current_price), -item[1])
        )
        return [level for level, _ in ranked[:3]]

    bullish_levels = ranked_levels("bullish")
    bearish_levels = ranked_levels("bearish")

    while len(bullish_levels) < 3:
        base = max(bullish_levels) if bullish_levels else current_price
        next_level = min(current_price + max_distance, base + fallback_step)
        if round(next_level, 2) <= round(base, 2):
            next_level = min(current_price + max_distance, base + 0.01)
        bullish_levels.append(round(next_level, 2))

    while len(bearish_levels) < 3:
        base = min(bearish_levels) if bearish_levels else current_price
        next_level = max(current_price - max_distance, base - fallback_step)
        if round(next_level, 2) >= round(base, 2):
            next_level = max(current_price - max_distance, base - 0.01)
        bearish_levels.append(round(next_level, 2))

    bullish_levels = sorted(set(bullish_levels))
    bearish_levels = sorted(set(bearish_levels), reverse=True)
    while len(bullish_levels) < 3:
        bullish_levels.append(round(bullish_levels[-1] + 0.01, 2))
    while len(bearish_levels) < 3:
        bearish_levels.append(round(bearish_levels[-1] - 0.01, 2))

    levels_corrected = not (
        bullish_levels[0] > current_price
        and bullish_levels[1] > bullish_levels[0]
        and bullish_levels[2] > bullish_levels[1]
        and bearish_levels[0] < current_price
        and bearish_levels[1] < bearish_levels[0]
        and bearish_levels[2] < bearish_levels[1]
        and bullish_levels[1] - bullish_levels[0] >= 0.05
        and bullish_levels[2] - bullish_levels[1] >= 0.05
        and bearish_levels[0] - bearish_levels[1] >= 0.05
        and bearish_levels[1] - bearish_levels[2] >= 0.05
    )

    if levels_corrected:
        bullish_levels = [
            current_price + 0.10,
            current_price + 0.25,
            current_price + 0.50
        ]
        bearish_levels = [
            current_price - 0.10,
            current_price - 0.25,
            current_price - 0.50
        ]

    now_epoch = time.time()
    structure_update_epoch = max(
        (
            candle.get("completed_epoch", now_epoch)
            for candle in all_candles
        ),
        default=now_epoch
    )

    return {
        "bullish_trigger": bullish_levels[0],
        "bullish_confirmation": bullish_levels[1],
        "bullish_breakout": bullish_levels[2],
        "bearish_trigger": bearish_levels[0],
        "bearish_confirmation": bearish_levels[1],
        "bearish_breakdown": bearish_levels[2],
        "level_update_time": time.strftime("%I:%M:%S %p"),
        "structure_update_epoch": structure_update_epoch,
        "level_update_epoch": now_epoch,
        "levels_corrected": "TRUE" if levels_corrected else "FALSE"
    }


def calculate_support_resistance(
    current_price,
    timeframe_candles,
    vwap,
    opening_range_high,
    opening_range_low
):
    max_distance = current_price * 0.005
    timeframe_weights = {"1m": 0.50, "3m": 0.30, "5m": 0.20}
    support_candidates = []
    resistance_candidates = []

    def add_candidate(collection, level, reason, weight=0):
        if level is None or abs(current_price - level) > max_distance:
            return
        collection.append((float(level), reason, weight))

    for timeframe in ("1m", "3m", "5m"):
        candles = timeframe_candles.get(timeframe, [])[-20:]
        weight = timeframe_weights[timeframe]

        for index, candle in enumerate(candles):
            candle_range = max(candle["high"] - candle["low"], 0.0001)
            lower_wick = min(candle["open"], candle["close"]) - candle["low"]
            upper_wick = candle["high"] - max(candle["open"], candle["close"])

            if 0 < index < len(candles) - 1:
                if (
                    candle["low"] <= candles[index - 1]["low"]
                    and candle["low"] <= candles[index + 1]["low"]
                    and candle["low"] < current_price
                ):
                    add_candidate(
                        support_candidates,
                        candle["low"],
                        f"Recent {timeframe} swing low.",
                        weight
                    )
                if (
                    candle["high"] >= candles[index - 1]["high"]
                    and candle["high"] >= candles[index + 1]["high"]
                    and candle["high"] > current_price
                ):
                    add_candidate(
                        resistance_candidates,
                        candle["high"],
                        f"Recent {timeframe} swing high.",
                        weight
                    )

            if lower_wick / candle_range >= 0.30 and candle["low"] < current_price:
                add_candidate(
                    support_candidates,
                    candle["low"],
                    f"Buyers defended this {timeframe} low with lower-wick rejection.",
                    weight
                )
            if upper_wick / candle_range >= 0.30 and candle["high"] > current_price:
                add_candidate(
                    resistance_candidates,
                    candle["high"],
                    f"Sellers rejected this {timeframe} high with an upper wick.",
                    weight
                )

        recent = candles[-3:]
        if len(recent) == 3:
            consolidation_low = min(candle["low"] for candle in recent)
            consolidation_high = max(candle["high"] for candle in recent)
            average_range = sum(
                candle["high"] - candle["low"] for candle in recent
            ) / 3
            consolidation_range = consolidation_high - consolidation_low

            if consolidation_range <= max(average_range * 2, 0.05):
                if consolidation_low < current_price:
                    add_candidate(
                        support_candidates,
                        consolidation_low,
                        f"Lower boundary of the recent {timeframe} consolidation.",
                        weight
                    )
                if consolidation_high > current_price:
                    add_candidate(
                        resistance_candidates,
                        consolidation_high,
                        f"Upper boundary of the recent {timeframe} consolidation.",
                        weight
                    )

    if vwap is not None and current_price > vwap:
        add_candidate(
            support_candidates,
            vwap,
            "VWAP is below price and may act as support.",
            0.25
        )
    elif vwap is not None and current_price < vwap:
        add_candidate(
            resistance_candidates,
            vwap,
            "VWAP is above price and may act as resistance.",
            0.25
        )

    if opening_range_low is not None and opening_range_low < current_price:
        add_candidate(
            support_candidates,
            opening_range_low,
            "Nearby opening-range low.",
            0.20
        )
    if opening_range_high is not None and opening_range_high > current_price:
        add_candidate(
            resistance_candidates,
            opening_range_high,
            "Nearby opening-range high.",
            0.20
        )

    def choose_nearest(candidates, is_support):
        valid = [
            candidate
            for candidate in candidates
            if (
                candidate[0] < current_price
                if is_support else candidate[0] > current_price
            )
        ]
        if not valid:
            return None, "No nearby structure level is available."

        level = min(
            valid,
            key=lambda candidate: (
                abs(current_price - candidate[0]),
                -candidate[2]
            )
        )[0]
        matching_reasons = []
        for candidate_level, reason, _ in valid:
            if abs(candidate_level - level) <= 0.03 and reason not in matching_reasons:
                matching_reasons.append(reason)
        return level, " ".join(matching_reasons[:3])

    nearest_support, support_reason = choose_nearest(support_candidates, True)
    nearest_resistance, resistance_reason = choose_nearest(
        resistance_candidates,
        False
    )

    return {
        "nearest_support": nearest_support,
        "support_reason": support_reason,
        "nearest_resistance": nearest_resistance,
        "resistance_reason": resistance_reason,
        "support_distance": (
            current_price - nearest_support
            if nearest_support is not None else None
        ),
        "resistance_distance": (
            nearest_resistance - current_price
            if nearest_resistance is not None else None
        )
    }


def detect_reversal_state(candles, vwap):
    if len(candles) < 3:
        return {
            "reversal_state": "NO REVERSAL SETUP",
            "reversal_reason": "Waiting for three completed 5-minute candles."
        }

    first, previous, latest = candles[-3:]
    latest_range = max(latest["high"] - latest["low"], 0.0001)
    latest_body = abs(latest["close"] - latest["open"])
    latest_upper_wick = latest["high"] - max(latest["open"], latest["close"])
    latest_lower_wick = min(latest["open"], latest["close"]) - latest["low"]
    latest_bullish = latest["close"] > latest["open"]
    latest_bearish = latest["close"] < latest["open"]
    prior_bearish_context = (
        first["close"] > previous["close"]
        or first["low"] > previous["low"]
        or (first["close"] < first["open"] and previous["close"] < previous["open"])
    )
    prior_bullish_context = (
        first["close"] < previous["close"]
        or first["high"] < previous["high"]
        or (first["close"] > first["open"] and previous["close"] > previous["open"])
    )
    buyer_rejection = (
        latest_lower_wick / latest_range >= 0.30
        and latest["close"] >= latest["low"] + (latest_range * 0.60)
    )
    seller_rejection = (
        latest_upper_wick / latest_range >= 0.30
        and latest["close"] <= latest["low"] + (latest_range * 0.40)
    )
    meaningful_body = latest_body / latest_range >= 0.30
    above_vwap = vwap is not None and latest["close"] > vwap
    below_vwap = vwap is not None and latest["close"] < vwap
    confirmed_bull = (
        prior_bearish_context
        and latest_bullish
        and meaningful_body
        and latest["close"] > previous["high"]
        and latest["low"] > previous["low"]
        and above_vwap
    )
    confirmed_bear = (
        prior_bullish_context
        and latest_bearish
        and meaningful_body
        and latest["close"] < previous["low"]
        and latest["high"] < previous["high"]
        and below_vwap
    )
    potential_bull = (
        prior_bearish_context
        and latest_bullish
        and (buyer_rejection or latest["low"] > previous["low"])
        and latest["close"] <= previous["high"]
    )
    potential_bear = (
        prior_bullish_context
        and latest_bearish
        and (seller_rejection or latest["high"] < previous["high"])
        and latest["close"] >= previous["low"]
    )

    if confirmed_bull:
        return {
            "reversal_state": "CONFIRMED BULL REVERSAL",
            "reversal_reason": (
                f"The completed candle closed above {previous['high']:.2f}, "
                "formed a higher low, and held above VWAP."
            )
        }
    if confirmed_bear:
        return {
            "reversal_state": "CONFIRMED BEAR REVERSAL",
            "reversal_reason": (
                f"The completed candle closed below {previous['low']:.2f}, "
                "formed a lower high, and held below VWAP."
            )
        }
    if potential_bull:
        return {
            "reversal_state": "POTENTIAL BULL REVERSAL",
            "reversal_reason": (
                f"Buyers responded from the low, but confirmation still needs "
                f"a completed close above {previous['high']:.2f}."
            )
        }
    if potential_bear:
        return {
            "reversal_state": "POTENTIAL BEAR REVERSAL",
            "reversal_reason": (
                f"Sellers responded from the high, but confirmation still needs "
                f"a completed close below {previous['low']:.2f}."
            )
        }

    return {
        "reversal_state": "NO REVERSAL SETUP",
        "reversal_reason": (
            "The last completed candle did not establish a clean reversal setup."
        )
    }


def build_chart_reading_analysis(
    current_price,
    candles,
    timeframe_candles,
    prediction,
    vwap,
    vwap_position,
    opening_range_high,
    opening_range_low,
    opening_range_position,
    candle_analysis
):
    if len(candles) < 3:
        return {
            "market_structure": "Range / chop",
            "current_advantage": "Mixed",
            **detect_reversal_state(candles, vwap),
            "confirmation_needed": "Wait for three completed 5-minute candles to define structure.",
            "invalidation_reason": "No clean invalidation level is available yet.",
            "next_candle_bullish_scenario": "A close above the latest candle high would begin building bullish structure.",
            "next_candle_bearish_scenario": "A close below the latest candle low would begin building bearish structure.",
            **build_confirmation_levels(
                current_price,
                timeframe_candles
            ),
            **calculate_support_resistance(
                current_price,
                timeframe_candles,
                vwap,
                opening_range_high,
                opening_range_low
            ),
            "invalidation_level": None
        }

    recent = candles[-3:]
    latest = recent[-1]
    previous = recent[-2]
    market_structure = classify_market_structure(candles)

    bullish_evidence = 0
    bearish_evidence = 0

    if market_structure.startswith("Higher"):
        bullish_evidence += 2
    if market_structure.startswith("Lower"):
        bearish_evidence += 2
    if candle_analysis["direction"] == "Bullish":
        bullish_evidence += 2
    elif candle_analysis["direction"] == "Bearish":
        bearish_evidence += 2
    if vwap_position == "Above":
        bullish_evidence += 1
    elif vwap_position == "Below":
        bearish_evidence += 1
    if opening_range_position == "Above":
        bullish_evidence += 1
    elif opening_range_position == "Below":
        bearish_evidence += 1

    if bullish_evidence > bearish_evidence:
        current_advantage = "Buyers"
    elif bearish_evidence > bullish_evidence:
        current_advantage = "Sellers"
    else:
        current_advantage = "Mixed"

    confirmation_levels = build_confirmation_levels(
        current_price,
        timeframe_candles
    )
    support_resistance = calculate_support_resistance(
        current_price,
        timeframe_candles,
        vwap,
        opening_range_high,
        opening_range_low
    )
    reversal_data = detect_reversal_state(candles, vwap)
    bullish_scenario = (
        f"A move through {confirmation_levels['bullish_trigger']:.2f} is the first "
        f"buyer response. A 5-minute close above "
        f"{confirmation_levels['bullish_confirmation']:.2f} strengthens the bias; "
        f"{confirmation_levels['bullish_breakout']:.2f} is the nearby breakout."
    )
    bearish_scenario = (
        f"A move through {confirmation_levels['bearish_trigger']:.2f} is the first "
        f"seller response. A 5-minute close below "
        f"{confirmation_levels['bearish_confirmation']:.2f} strengthens the bias; "
        f"{confirmation_levels['bearish_breakdown']:.2f} is the nearby breakdown."
    )

    if prediction == "CALL":
        confirmation_needed = (
            f"Hold above VWAP {vwap:.2f} and close above {latest['high']:.2f}."
            if vwap is not None else
            f"Close above {latest['high']:.2f} while preserving the latest higher low."
        )
        invalidation_level = min(latest["low"], previous["low"])
        invalidation_reason = (
            f"A 5-minute close below {invalidation_level:.2f} breaks the bullish "
            "structure and changes the bias."
        )
    elif prediction == "PUT":
        confirmation_needed = (
            f"Hold below VWAP {vwap:.2f} and close below {latest['low']:.2f}."
            if vwap is not None else
            f"Close below {latest['low']:.2f} while preserving the latest lower high."
        )
        invalidation_level = max(latest["high"], previous["high"])
        invalidation_reason = (
            f"A 5-minute close above {invalidation_level:.2f} breaks the bearish "
            "structure and changes the bias."
        )
    else:
        confirmation_needed = (
            f"Wait for a 5-minute close above {latest['high']:.2f} or below "
            f"{latest['low']:.2f}, with VWAP holding on the breakout side."
        )
        invalidation_level = None
        invalidation_reason = (
            "There is no clean invalidation while price remains inside the current range."
        )

    return {
        "market_structure": market_structure,
        "current_advantage": current_advantage,
        **reversal_data,
        "confirmation_needed": confirmation_needed,
        "invalidation_reason": invalidation_reason,
        "next_candle_bullish_scenario": bullish_scenario,
        "next_candle_bearish_scenario": bearish_scenario,
        **confirmation_levels,
        **support_resistance,
        "invalidation_level": invalidation_level
    }


def get_a_plus_trade_risk(market_phase, regime, mode_stability):
    eastern_now = datetime.now(ZoneInfo("America/New_York"))
    minutes = eastern_now.hour * 60 + eastern_now.minute
    if (
        regime == "CHOPPY"
        or mode_stability == "LOW"
        or market_phase in ("Pre-Market Analysis", "Midday Chop", "Market Closed")
        or minutes >= 945
    ):
        return "NO TRADE"
    if market_phase in ("Caution Window", "Afternoon Setup"):
        return "HIGH RISK"
    return "NORMAL"


def get_yesterday_midpoint_direction(spy_price):
    global yesterday_midpoint_cache_date, yesterday_midpoint_cache_value

    today = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
    if yesterday_midpoint_cache_date != today:
        yesterday_midpoint_cache_date = today
        yesterday_midpoint_cache_value = None
        if os.path.exists(PREDICTION_LOG_FILE):
            grouped_prices = {}
            with open(PREDICTION_LOG_FILE, "r", newline="") as file:
                for row in csv.DictReader(file):
                    row_time = row.get("time", "")
                    if len(row_time) < 10 or row_time[:10] >= today:
                        continue
                    try:
                        row_price = float(row.get("spy_price"))
                    except (TypeError, ValueError):
                        continue
                    grouped_prices.setdefault(row_time[:10], []).append(row_price)
            if grouped_prices:
                latest_prior_date = sorted(grouped_prices)[-1]
                prior_prices = grouped_prices[latest_prior_date]
                yesterday_midpoint_cache_value = (
                    max(prior_prices) + min(prior_prices)
                ) / 2

    if yesterday_midpoint_cache_value is None:
        return "NEUTRAL"
    if spy_price > yesterday_midpoint_cache_value + 0.10:
        return "CALL"
    if spy_price < yesterday_midpoint_cache_value - 0.10:
        return "PUT"
    return "NEUTRAL"


def apply_a_plus_setup_filter(
    prediction_data,
    spy_price,
    timeframe_candles,
    engine_bias,
    breadth_classification
):
    candidate = prediction_data.get("prediction", "WAIT")
    regime = prediction_data.get("regime", "CHOPPY")
    market_phase = prediction_data.get("market_phase", "Market Closed")
    trade_risk = get_a_plus_trade_risk(
        market_phase,
        regime,
        prediction_data.get("mode_stability", "LOW")
    )

    def direction_from_text(value):
        text = str(value or "").upper()
        if any(word in text for word in ("BULLISH", "HIGHER", "ABOVE", "BUYERS", "CALL")):
            return "CALL"
        if any(word in text for word in ("BEARISH", "LOWER", "BELOW", "SELLERS", "PUT")):
            return "PUT"
        return "NEUTRAL"

    one_minute = timeframe_candles.get("1m", [])
    five_minute = timeframe_candles.get("5m", [])
    market_box = "NEUTRAL"
    if len(one_minute) >= 4:
        box_source = one_minute[-4:-1]
        box_high = max(candle["high"] for candle in box_source)
        box_low = min(candle["low"] for candle in box_source)
        market_box = "CALL" if spy_price > box_high else (
            "PUT" if spy_price < box_low else "NEUTRAL"
        )

    trend_box = direction_from_text(prediction_data.get("market_structure"))
    if trend_box == "NEUTRAL" and len(five_minute) >= 3:
        box_source = five_minute[-3:]
        midpoint = (
            max(candle["high"] for candle in box_source)
            + min(candle["low"] for candle in box_source)
        ) / 2
        trend_box = "CALL" if spy_price > midpoint else "PUT"

    level_direction = "NEUTRAL"
    if len(five_minute) >= 2:
        latest = five_minute[-1]
        previous = five_minute[-2]
        if latest["close"] > previous["high"]:
            level_direction = "CALL"
        elif latest["close"] < previous["low"]:
            level_direction = "PUT"

    volume_direction = (
        candidate if prediction_data.get("volume_filter") == "PASS"
        and (
            market_phase != "Pre-Market Analysis"
            or prediction_data.get("pre_market_relative_volume", 0) >= 1
        )
        else "NEUTRAL"
    )
    factors = {
        "Market Regime": direction_from_text(regime),
        "VWAP": direction_from_text(prediction_data.get("vwap_position")),
        "Trend Box": trend_box,
        "Market Box": market_box,
        "Yesterday Midpoint": get_yesterday_midpoint_direction(spy_price),
        "Support/Resistance": direction_from_text(
            prediction_data.get("current_advantage")
        ),
        "Bull/Bear Levels": level_direction,
        "Volume/RVOL": volume_direction,
        "Engine Health": direction_from_text(engine_bias),
        "Market Breadth": direction_from_text(breadth_classification),
        "Time of Day Risk": candidate if trade_risk == "NORMAL" else "NEUTRAL"
    }
    bullish_score = sum(value == "CALL" for value in factors.values())
    bearish_score = sum(value == "PUT" for value in factors.values())
    confluence_score = (
        bullish_score if candidate == "CALL"
        else bearish_score if candidate == "PUT"
        else max(bullish_score, bearish_score)
    )
    blockers = []
    if candidate not in ("CALL", "PUT"):
        blockers.append("no confirmed CALL or PUT candidate")
    if regime == "CHOPPY":
        blockers.append("market regime is CHOPPY")
    if trade_risk == "NO TRADE":
        blockers.append("trade risk is NO TRADE")
    if prediction_data.get("total_confidence", 0) < 80:
        blockers.append("confidence below 80")
    if (
        prediction_data.get("vwap_confirmation") != "PASS"
        or (
            candidate in ("CALL", "PUT")
            and factors["VWAP"] != candidate
        )
    ):
        blockers.append("VWAP conflicts")
    if volume_direction == "NEUTRAL":
        blockers.append("volume/RVOL below average")
    if candidate in ("CALL", "PUT") and trend_box not in (candidate, "NEUTRAL"):
        blockers.append("Trend Box conflicts")
    breadth_direction = factors["Market Breadth"]
    if candidate in ("CALL", "PUT") and breadth_direction not in (candidate, "NEUTRAL"):
        blockers.append("Market Breadth conflicts")
    if confluence_score < 8:
        blockers.append(f"only {confluence_score} of 11 factors agree")

    a_plus_setup = not blockers
    prediction_data.update({
        "a_plus_setup": "YES" if a_plus_setup else "NO",
        "confluence_score": confluence_score,
        "bullish_confluence_score": bullish_score,
        "bearish_confluence_score": bearish_score,
        "a_plus_wait_reason": "; ".join(blockers) if blockers else "Eight or more factors align with no hard conflicts.",
        "confluence_factors": "; ".join(
            f"{name}={value}" for name, value in factors.items()
        )
    })
    if not a_plus_setup:
        prediction_data["prediction"] = "WAIT"
        prediction_data["invalid_level"] = None
        prediction_data["reason"] += (
            f"; A+ setup filter forced WAIT: {prediction_data['a_plus_wait_reason']}"
        )
    return prediction_data


def apply_signal_stability(candidate_prediction, completed_candles, now):
    global current_mode_prediction
    global last_directional_prediction
    global current_mode_started_at
    global last_stability_candle_key
    global pending_opposite_direction
    global pending_opposite_count

    previous_prediction = current_mode_prediction
    stable_prediction = candidate_prediction
    latest_candle = completed_candles[-1] if completed_candles else None
    latest_candle_key = latest_candle.get("time") if latest_candle else None
    latest_candle_direction = None

    if latest_candle:
        if latest_candle["close"] > latest_candle["open"]:
            latest_candle_direction = "CALL"
        elif latest_candle["close"] < latest_candle["open"]:
            latest_candle_direction = "PUT"

    is_direct_opposite = (
        last_directional_prediction in ("CALL", "PUT")
        and candidate_prediction in ("CALL", "PUT")
        and candidate_prediction != last_directional_prediction
    )

    if is_direct_opposite:
        if latest_candle_key != last_stability_candle_key:
            last_stability_candle_key = latest_candle_key

            if latest_candle_direction == candidate_prediction:
                if pending_opposite_direction == candidate_prediction:
                    pending_opposite_count += 1
                else:
                    pending_opposite_direction = candidate_prediction
                    pending_opposite_count = 1
            else:
                pending_opposite_direction = None
                pending_opposite_count = 0

        if (
            pending_opposite_direction != candidate_prediction
            or pending_opposite_count < 2
        ):
            stable_prediction = current_mode_prediction
    else:
        pending_opposite_direction = None
        pending_opposite_count = 0

    while SIGNAL_MODE_HISTORY and now - SIGNAL_MODE_HISTORY[0] > 600:
        SIGNAL_MODE_HISTORY.popleft()

    if stable_prediction != current_mode_prediction:
        SIGNAL_MODE_HISTORY.append(now)
        current_mode_prediction = stable_prediction
        current_mode_started_at = now

        if stable_prediction in ("CALL", "PUT"):
            last_directional_prediction = stable_prediction

    while SIGNAL_MODE_HISTORY and now - SIGNAL_MODE_HISTORY[0] > 600:
        SIGNAL_MODE_HISTORY.popleft()

    signal_flip_count_10m = len(SIGNAL_MODE_HISTORY)
    mode_duration_minutes = (now - current_mode_started_at) / 60

    if signal_flip_count_10m >= 3:
        mode_stability = "LOW"
    elif signal_flip_count_10m == 0 and mode_duration_minutes >= 5:
        mode_stability = "HIGH"
    else:
        mode_stability = "MEDIUM"

    return {
        "prediction": stable_prediction,
        "previous_prediction": previous_prediction,
        "mode_duration_minutes": mode_duration_minutes,
        "signal_flip_count_10m": signal_flip_count_10m,
        "mode_stability": mode_stability
    }


def calculate_direction_prediction(
    spy_price,
    spy_change,
    recent_move,
    trend_move,
    current_engine_bias,
    current_breadth,
    last_1m_bid_total,
    last_1m_bid_average,
    volume_filter,
    activity_filter,
    history,
    completed_candles,
    vwap,
    vwap_position,
    opening_range_high,
    opening_range_low,
    opening_range_position
):
    bullish = {"trend": 0, "momentum": 0, "engine": 0, "breadth": 0}
    bearish = {"trend": 0, "momentum": 0, "engine": 0, "breadth": 0}
    reasons = []

    if trend_move is not None:
        if trend_move >= MIN_TREND_CONFIRM_MOVE:
            bullish["trend"] = 20
        elif trend_move > 0:
            bullish["trend"] = 12
        elif trend_move <= -MIN_TREND_CONFIRM_MOVE:
            bearish["trend"] = 20
        elif trend_move < 0:
            bearish["trend"] = 12

    if spy_change >= SPY_MOVE_ALERT_PERCENT:
        bullish["momentum"] += 14
    elif spy_change > 0:
        bullish["momentum"] += 8
    elif spy_change <= -SPY_MOVE_ALERT_PERCENT:
        bearish["momentum"] += 14
    elif spy_change < 0:
        bearish["momentum"] += 8

    if recent_move is not None:
        if recent_move >= MIN_CONTINUATION_MOVE:
            bullish["momentum"] += 6
        elif recent_move <= -MIN_CONTINUATION_MOVE:
            bearish["momentum"] += 6

    bullish["momentum"] = min(20, bullish["momentum"])
    bearish["momentum"] = min(20, bearish["momentum"])

    if current_engine_bias == "BULLISH":
        bullish["engine"] = 20
    elif current_engine_bias == "BEARISH":
        bearish["engine"] = 20
    else:
        bullish["engine"] = 5
        bearish["engine"] = 5

    if current_breadth == "Strong Bullish":
        bullish["breadth"] = 15
    elif current_breadth == "Strong Bearish":
        bearish["breadth"] = 15
    else:
        bullish["breadth"] = 5
        bearish["breadth"] = 5

    volume_activity_score = 0
    if volume_filter == "PASS":
        volume_activity_score = 10

    candle_analysis = analyze_completed_candles(completed_candles)
    market_structure = classify_market_structure(completed_candles)
    bullish_total = (
        sum(bullish.values())
        + volume_activity_score
        + (
            candle_analysis["candle_analysis_score"]
            if candle_analysis["bullish_score"] > candle_analysis["bearish_score"]
            else 0
        )
    )
    bearish_total = (
        sum(bearish.values())
        + volume_activity_score
        + (
            candle_analysis["candle_analysis_score"]
            if candle_analysis["bearish_score"] > candle_analysis["bullish_score"]
            else 0
        )
    )
    if bullish_total > bearish_total:
        direction = "CALL"
        winning_scores = bullish
    elif bearish_total > bullish_total:
        direction = "PUT"
        winning_scores = bearish
    else:
        direction = None
        winning_scores = bullish

    total_confidence = max(bullish_total, bearish_total)
    regime = detect_scanner_regime(history)
    threshold = 55

    if candle_analysis["indecision"]:
        total_confidence = round(total_confidence * 0.80)
        reasons.append("5-minute candle indecision reduced confidence")

    if volume_filter == "FAIL":
        reasons.append("volume filter failed; volume score reduced by 10")

    if activity_filter == "SLOW":
        total_confidence = max(0, total_confidence - 10)
        reasons.append("slow activity; confidence reduced by 10")

    strong_bullish_alignment = (
        vwap_position == "Above"
        and opening_range_position == "Above"
        and candle_analysis["direction"] == "Bullish"
    )
    strong_bearish_alignment = (
        vwap_position == "Below"
        and opening_range_position == "Below"
        and candle_analysis["direction"] == "Bearish"
    )

    if strong_bullish_alignment:
        direction = "CALL"
        winning_scores = bullish
        reasons.append("strong bullish VWAP, opening range, and candle alignment")
    elif strong_bearish_alignment:
        direction = "PUT"
        winning_scores = bearish
        reasons.append("strong bearish VWAP, opening range, and candle alignment")

    if vwap_position == "Mixed":
        regime = "CHOPPY"
        direction = None
        vwap_confirmation = "FAIL"
        reasons.append("price is crossing around VWAP")
    elif (
        (direction == "CALL" and vwap_position == "Above")
        or (direction == "PUT" and vwap_position == "Below")
    ):
        vwap_confirmation = "PASS"
        reasons.append(f"{direction} confirmed by VWAP")
    elif direction:
        vwap_confirmation = "FAIL"
        total_confidence = max(0, total_confidence - 10)
        reasons.append("VWAP confirmation failed; confidence reduced by 10")
    else:
        vwap_confirmation = "FAIL"

    if (
        (direction == "CALL" and opening_range_position == "Above")
        or (direction == "PUT" and opening_range_position == "Below")
    ):
        total_confidence = min(100, total_confidence + 5)
        reasons.append(f"{direction} confirmed by opening range breakout")
    elif opening_range_position == "Inside":
        total_confidence = round(total_confidence * 0.80)
        direction = None
        reasons.append("inside opening range favors wait")
    elif direction:
        total_confidence = max(0, total_confidence - 10)
        reasons.append("opening range confirmation failed; confidence reduced by 10")

    if regime == "CHOPPY" and candle_analysis["direction"] == "Mixed":
        direction = None
        reasons.append("choppy regime with mixed 5-minute candles")

    if len(completed_candles) >= 3:
        latest_candle = completed_candles[-1]
        previous_candle = completed_candles[-2]
        bullish_structure = market_structure == "Higher highs and higher lows"
        bearish_structure = market_structure == "Lower highs and lower lows"
        bullish_close_confirmation = (
            latest_candle["close"] > previous_candle["high"]
        )
        bearish_close_confirmation = (
            latest_candle["close"] < previous_candle["low"]
        )
        bullish_vwap_confirmation = (
            vwap is not None
            and latest_candle["close"] > vwap
        )
        bearish_vwap_confirmation = (
            vwap is not None
            and latest_candle["close"] < vwap
        )

        if direction == "CALL" and not (
            bullish_structure
            and bullish_close_confirmation
            and bullish_vwap_confirmation
        ):
            direction = None
            reasons.append(
                "CALL confirmation incomplete: needs bullish structure, "
                "a close above the prior high, and buyers holding above VWAP"
            )
        elif direction == "PUT" and not (
            bearish_structure
            and bearish_close_confirmation
            and bearish_vwap_confirmation
        ):
            direction = None
            reasons.append(
                "PUT confirmation incomplete: needs bearish structure, "
                "a close below the prior low, and sellers holding below VWAP"
            )
    else:
        direction = None
        reasons.append("waiting for three completed 5-minute candles")

    if market_structure == "Range / chop":
        direction = None
        reasons.append("range structure has no clean directional invalidation")

    if direction and total_confidence >= threshold:
        prediction = direction
        invalid_level = spy_price - 0.20 if prediction == "CALL" else spy_price + 0.20
    else:
        prediction = "WAIT"
        invalid_level = None

    if direction:
        reasons.append(f"{direction} evidence {total_confidence}/100")
    else:
        reasons.append(
            f"no confirmed directional advantage at {total_confidence}/100"
        )
    reasons.append(f"regime {regime}")
    reasons.append(f"candles: {candle_analysis['reason']}")
    if total_confidence < threshold:
        reasons.append(f"confidence below {threshold}")

    if spy_change >= SPY_MOVE_ALERT_PERCENT:
        alert_direction = "CALL"
    elif spy_change <= -SPY_MOVE_ALERT_PERCENT:
        alert_direction = "PUT"
    else:
        alert_direction = "NONE"

    return {
        "prediction": prediction,
        "confidence": total_confidence,
        "total_confidence": total_confidence,
        "reason": "; ".join(reasons),
        "trend_score": winning_scores["trend"],
        "momentum_score": winning_scores["momentum"],
        "engine_score": winning_scores["engine"],
        "breadth_score": winning_scores["breadth"],
        "volume_activity_score": volume_activity_score,
        "candle_score": candle_analysis["candle_score"],
        "candle_analysis_score": candle_analysis["candle_analysis_score"],
        "candle_indecision": (
            "YES" if candle_analysis["indecision"] else "NO"
        ),
        "last_3_candle_reading": candle_analysis["reading"],
        "regime": regime,
        "vwap": vwap,
        "vwap_position": vwap_position,
        "vwap_confirmation": vwap_confirmation,
        "opening_range_high": opening_range_high,
        "opening_range_low": opening_range_low,
        "opening_range_position": opening_range_position,
        "alert_direction": alert_direction,
        "invalid_level": invalid_level,
        "last_1m_bid_total": last_1m_bid_total,
        "last_1m_bid_average": last_1m_bid_average,
        "volume_filter": volume_filter
    }


def ensure_prediction_log_headers():
    if not os.path.exists(PREDICTION_LOG_FILE):
        return

    with open(PREDICTION_LOG_FILE, "r", newline="") as file:
        reader = csv.DictReader(file)
        existing_headers = reader.fieldnames or []

        if existing_headers == PREDICTION_HEADERS:
            return

        rows = list(reader)

    temporary_file = f"{PREDICTION_LOG_FILE}.upgrade.tmp"

    with open(temporary_file, "w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=PREDICTION_HEADERS)
        writer.writeheader()

        for row in rows:
            writer.writerow({
                header: row.get(header, "")
                for header in PREDICTION_HEADERS
            })

    os.replace(temporary_file, PREDICTION_LOG_FILE)


def save_prediction_row(spy_price, prediction_data):
    ensure_log_dir()
    ensure_prediction_log_headers()
    current_time = time.strftime("%Y-%m-%d %H:%M:%S")
    file_exists = os.path.exists(PREDICTION_LOG_FILE)
    invalid_level = prediction_data["invalid_level"]

    with open(PREDICTION_LOG_FILE, "a", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=PREDICTION_HEADERS)

        if not file_exists:
            writer.writeheader()

        writer.writerow({
            "time": current_time,
            "spy_price": f"{spy_price:.4f}",
            "prediction": prediction_data["prediction"],
            "confidence": prediction_data["confidence"],
            "reason": prediction_data["reason"],
            "trend_score": prediction_data["trend_score"],
            "momentum_score": prediction_data["momentum_score"],
            "engine_score": prediction_data["engine_score"],
            "breadth_score": prediction_data["breadth_score"],
            "volume_activity_score": prediction_data["volume_activity_score"],
            "candle_score": prediction_data["candle_score"],
            "candle_analysis_score": prediction_data["candle_analysis_score"],
            "candle_indecision": prediction_data["candle_indecision"],
            "last_3_candle_reading": prediction_data["last_3_candle_reading"],
            "total_confidence": prediction_data["total_confidence"],
            "regime": prediction_data["regime"],
            "previous_prediction": prediction_data["previous_prediction"],
            "mode_duration_minutes": (
                f"{prediction_data['mode_duration_minutes']:.2f}"
            ),
            "signal_flip_count_10m": prediction_data["signal_flip_count_10m"],
            "mode_stability": prediction_data["mode_stability"],
            "vwap": format_optional_price(prediction_data["vwap"]),
            "vwap_position": prediction_data["vwap_position"],
            "vwap_confirmation": prediction_data["vwap_confirmation"],
            "opening_range_high": format_optional_price(
                prediction_data["opening_range_high"]
            ),
            "opening_range_low": format_optional_price(
                prediction_data["opening_range_low"]
            ),
            "opening_range_position": prediction_data[
                "opening_range_position"
            ],
            "market_structure": prediction_data["market_structure"],
            "current_advantage": prediction_data["current_advantage"],
            "reversal_state": prediction_data["reversal_state"],
            "reversal_reason": prediction_data["reversal_reason"],
            "mtf_1m_status": prediction_data["mtf_1m_status"],
            "mtf_1m_reason": prediction_data["mtf_1m_reason"],
            "mtf_3m_status": prediction_data["mtf_3m_status"],
            "mtf_3m_reason": prediction_data["mtf_3m_reason"],
            "mtf_5m_status": prediction_data["mtf_5m_status"],
            "mtf_5m_reason": prediction_data["mtf_5m_reason"],
            "mtf_overall_signal": prediction_data["mtf_overall_signal"],
            "mtf_alignment": prediction_data["mtf_alignment"],
            "confirmation_needed": prediction_data["confirmation_needed"],
            "invalidation_reason": prediction_data["invalidation_reason"],
            "next_candle_bullish_scenario": prediction_data[
                "next_candle_bullish_scenario"
            ],
            "next_candle_bearish_scenario": prediction_data[
                "next_candle_bearish_scenario"
            ],
            "bullish_trigger": format_optional_price(
                prediction_data["bullish_trigger"]
            ),
            "bullish_confirmation": format_optional_price(
                prediction_data["bullish_confirmation"]
            ),
            "bullish_breakout": format_optional_price(
                prediction_data["bullish_breakout"]
            ),
            "bearish_trigger": format_optional_price(
                prediction_data["bearish_trigger"]
            ),
            "bearish_confirmation": format_optional_price(
                prediction_data["bearish_confirmation"]
            ),
            "bearish_breakdown": format_optional_price(
                prediction_data["bearish_breakdown"]
            ),
            "level_update_time": prediction_data["level_update_time"],
            "structure_update_epoch": (
                f"{prediction_data['structure_update_epoch']:.3f}"
            ),
            "level_update_epoch": f"{prediction_data['level_update_epoch']:.3f}",
            "levels_corrected": prediction_data["levels_corrected"],
            "nearest_support": format_optional_price(
                prediction_data["nearest_support"]
            ),
            "support_reason": prediction_data["support_reason"],
            "nearest_resistance": format_optional_price(
                prediction_data["nearest_resistance"]
            ),
            "resistance_reason": prediction_data["resistance_reason"],
            "support_distance": format_optional_price(
                prediction_data["support_distance"]
            ),
            "resistance_distance": format_optional_price(
                prediction_data["resistance_distance"]
            ),
            "alert_direction": prediction_data["alert_direction"],
            "invalid_level": (
                "" if invalid_level is None else f"{invalid_level:.4f}"
            ),
            "entry": format_optional_price(prediction_data["entry"]),
            "stop_loss": format_optional_price(prediction_data["stop_loss"]),
            "target_1": format_optional_price(prediction_data["target_1"]),
            "target_2": format_optional_price(prediction_data["target_2"]),
            "risk_reward": format_risk_reward(prediction_data["risk_reward"]),
            "last_1m_bid_total": f"{prediction_data['last_1m_bid_total']:.0f}",
            "last_1m_bid_average": (
                f"{prediction_data['last_1m_bid_average']:.2f}"
            ),
            "volume_filter": prediction_data["volume_filter"],
            "rolling_30m_trade_count": (
                prediction_data["rolling_30m_trade_count"]
            ),
            "rolling_30m_call_count": prediction_data["rolling_30m_call_count"],
            "rolling_30m_put_count": prediction_data["rolling_30m_put_count"],
            "rolling_30m_wait_count": prediction_data["rolling_30m_wait_count"],
            "avg_trades_per_min_30m": (
                f"{prediction_data['avg_trades_per_min_30m']:.2f}"
            ),
            "activity_filter": prediction_data["activity_filter"],
            "market_phase": prediction_data["market_phase"],
            "pre_market_bias": prediction_data["pre_market_bias"],
            "pre_market_confidence": prediction_data["pre_market_confidence"],
            "pre_market_reason": prediction_data["pre_market_reason"],
            "pre_market_high": format_optional_price(prediction_data["pre_market_high"]),
            "pre_market_low": format_optional_price(prediction_data["pre_market_low"]),
            "pre_market_spy_move": f"{prediction_data['pre_market_spy_move']:.4f}",
            "pre_market_qqq_move": (
                "" if prediction_data["pre_market_qqq_move"] is None
                else f"{prediction_data['pre_market_qqq_move']:.4f}"
            ),
            "pre_market_volume": f"{prediction_data['pre_market_volume']:.0f}",
            "pre_market_relative_volume": f"{prediction_data['pre_market_relative_volume']:.2f}",
            "a_plus_setup": prediction_data["a_plus_setup"],
            "confluence_score": prediction_data["confluence_score"],
            "bullish_confluence_score": prediction_data["bullish_confluence_score"],
            "bearish_confluence_score": prediction_data["bearish_confluence_score"],
            "a_plus_wait_reason": prediction_data["a_plus_wait_reason"],
            "confluence_factors": prediction_data["confluence_factors"]
        })


def get_row_value(row, *field_names):
    for field_name in field_names:
        value = row.get(field_name)
        if value not in (None, ""):
            return value

    return ""


def normalize_result_log_row(row):
    confirmed_30s = get_row_value(row, "confirmed_30s")
    result = get_row_value(row, "result")

    if confirmed_30s in ("WIN", "LOSS", "FLAT") and not result:
        result = confirmed_30s
        confirmed_30s = "N/A"

    if confirmed_30s not in ("CONFIRMED", "NO_CONFIRM", "N/A"):
        confirmed_30s = "N/A"

    return {
        "time": get_row_value(row, "time", "result_time"),
        "option_type": get_row_value(row, "option_type"),
        "entry_spy_price": get_row_value(row, "entry_spy_price"),
        "price_after_30s": get_row_value(row, "price_after_30s", "spy_price_30s"),
        "price_after_60s": get_row_value(row, "price_after_60s", "spy_price_60s"),
        "price_after_120s": get_row_value(row, "price_after_120s", "spy_price_120s"),
        "move_30s": get_row_value(row, "move_30s"),
        "move_60s": get_row_value(row, "move_60s"),
        "move_120s": get_row_value(row, "move_120s"),
        "best_move": get_row_value(row, "best_move"),
        "worst_move": get_row_value(row, "worst_move"),
        "confirmed_30s": confirmed_30s,
        "result": result
    }


def ensure_result_log_file():
    if not os.path.exists(RESULT_LOG_FILE):
        return False

    with open(RESULT_LOG_FILE, "r", newline="") as file:
        reader = csv.DictReader(file)
        fieldnames = reader.fieldnames or []

        if fieldnames == RESULT_HEADERS:
            return True

        rows = list(reader)

    with open(RESULT_LOG_FILE, "w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=RESULT_HEADERS)
        writer.writeheader()

        for row in rows:
            writer.writerow(normalize_result_log_row(row))

    return True


def save_result_row(
    option_type,
    entry_spy_price,
    price_after_30s,
    price_after_60s,
    price_after_120s,
    move_30s,
    move_60s,
    move_120s,
    best_move,
    worst_move,
    confirmed_30s,
    result
):
    ensure_log_dir()
    current_time = time.strftime("%Y-%m-%d %H:%M:%S")
    file_exists = ensure_result_log_file()

    with open(RESULT_LOG_FILE, "a", newline="") as file:
        writer = csv.writer(file)

        if not file_exists:
            writer.writerow(RESULT_HEADERS)

        writer.writerow([
            current_time,
            option_type,
            f"{entry_spy_price:.4f}",
            f"{price_after_30s:.4f}",
            f"{price_after_60s:.4f}",
            f"{price_after_120s:.4f}",
            f"{move_30s:.4f}",
            f"{move_60s:.4f}",
            f"{move_120s:.4f}",
            f"{best_move:.4f}",
            f"{worst_move:.4f}",
            confirmed_30s,
            result
        ])


def save_a_plus_result_row(
    option_type,
    entry_spy_price,
    price_after_30s,
    price_after_60s,
    price_after_120s,
    move_30s,
    move_60s,
    move_120s,
    best_move,
    worst_move,
    confirmed_30s,
    result
):
    file_exists = os.path.exists(A_PLUS_RESULT_LOG_FILE)
    with open(A_PLUS_RESULT_LOG_FILE, "a", newline="") as file:
        writer = csv.writer(file)
        if not file_exists:
            writer.writerow(RESULT_HEADERS)
        writer.writerow([
            time.strftime("%Y-%m-%d %H:%M:%S"),
            option_type,
            f"{entry_spy_price:.4f}",
            f"{price_after_30s:.4f}",
            f"{price_after_60s:.4f}",
            f"{price_after_120s:.4f}",
            f"{move_30s:.4f}",
            f"{move_60s:.4f}",
            f"{move_120s:.4f}",
            f"{best_move:.4f}",
            f"{worst_move:.4f}",
            confirmed_30s,
            result
        ])


def get_directional_move(option_type, entry_spy_price, current_spy_price):
    if option_type == "CALL":
        return current_spy_price - entry_spy_price

    return entry_spy_price - current_spy_price


def get_result_label(best_move, worst_move):
    if best_move >= 0.20:
        return "WIN"

    if worst_move <= -0.20:
        return "LOSS"

    return "FLAT"


def get_confirmation_label(option_type, entry_spy_price, spy_price_30s):
    if option_type == "CALL" and spy_price_30s > entry_spy_price:
        return "CONFIRMED"

    if option_type == "PUT" and spy_price_30s < entry_spy_price:
        return "CONFIRMED"

    return "NO_CONFIRM"


def track_alert_result(option_type, entry_spy_price, a_plus_setup="YES"):
    time.sleep(30)
    spy_price_30s = get_spy_price()

    time.sleep(30)
    spy_price_60s = get_spy_price()

    time.sleep(60)
    spy_price_120s = get_spy_price()

    if spy_price_30s is None or spy_price_60s is None or spy_price_120s is None:
        print("Could not track SPY alert result. Missing follow-up price.")
        return

    move_30s = get_directional_move(option_type, entry_spy_price, spy_price_30s)
    move_60s = get_directional_move(option_type, entry_spy_price, spy_price_60s)
    move_120s = get_directional_move(option_type, entry_spy_price, spy_price_120s)
    best_move = max(move_30s, move_60s, move_120s)
    worst_move = min(move_30s, move_60s, move_120s)
    confirmed_30s = get_confirmation_label(
        option_type,
        entry_spy_price,
        spy_price_30s
    )
    result = get_result_label(best_move, worst_move)

    save_result_row(
        option_type,
        entry_spy_price,
        spy_price_30s,
        spy_price_60s,
        spy_price_120s,
        move_30s,
        move_60s,
        move_120s,
        best_move,
        worst_move,
        confirmed_30s,
        result
    )
    if a_plus_setup == "YES":
        save_a_plus_result_row(
            option_type,
            entry_spy_price,
            spy_price_30s,
            spy_price_60s,
            spy_price_120s,
            move_30s,
            move_60s,
            move_120s,
            best_move,
            worst_move,
            confirmed_30s,
            result
        )

    print(
        f"Tracked {option_type} result | "
        f"30s: {move_30s:+.4f} | "
        f"60s: {move_60s:+.4f} | "
        f"120s: {move_120s:+.4f} | "
        f"Best: {best_move:+.4f} | "
        f"Worst: {worst_move:+.4f} | "
        f"30s confirmation: {confirmed_30s} | "
        f"{result}"
    )


ensure_log_dir()

print("Starting SPY options alert scanner...")
print("Watching SPY movement for CALL / PUT paper alerts.")
print("Paper testing only. No real-money trading.")
print("-" * 70)

while True:
    try:
        now = time.time()

        (
            spy_price,
            spy_bar_volume,
            spy_bar_key,
            completed_candles,
            timeframe_candles,
            vwap,
            vwap_position,
            opening_range_high,
            opening_range_low,
            opening_range_position
        ) = (
            get_spy_snapshot()
        )

        if spy_price is None:
            print("Could not get SPY price. Retrying...")
            time.sleep(5)
            continue

        save_live_status(spy_price, now)

        last_1m_bid_total, last_1m_bid_average, volume_filter = (
            update_rolling_bid_volume(
                now,
                spy_bar_key,
                spy_bar_volume
            )
        )
        PRICE_HISTORY.append((now, spy_price))

        old_spy_price = get_old_value(PRICE_HISTORY, TIME_WINDOW_SECONDS)

        if old_spy_price is None:
            print(
                f"SPY: ${spy_price:.2f} | "
                f"collecting {TIME_WINDOW_SECONDS}s history..."
            )
            time.sleep(2)
            continue

        spy_change = percent_change(spy_price, old_spy_price)
        scan_count += 1

        if (
            spy_change >= SPY_MOVE_ALERT_PERCENT
            or spy_change <= -SPY_MOVE_ALERT_PERCENT
        ):
            threshold_pass_count += 1

        print(
            f"SPY: ${spy_price:.2f} | "
            f"SPY {TIME_WINDOW_SECONDS}s: {spy_change:+.4f}%"
        )

        save_scan_row(spy_price, spy_change)

        if now - last_engine_health_time >= ENGINE_REFRESH_SECONDS:
            refreshed_engine_rows = refresh_engine_health()

            if refreshed_engine_rows:
                engine_health_rows = refreshed_engine_rows
                engine_score, engine_bias = calculate_engine_summary(
                    engine_health_rows
                )
                market_breadth = refresh_market_breadth(engine_health_rows)
                print(
                    f"SPY Engine Health: {engine_bias} | "
                    f"score {engine_score:+.1f}%"
                )
                if market_breadth:
                    market_breadth_classification = market_breadth[
                        "classification"
                    ]
                    print(
                        f"Market Breadth: {market_breadth['classification']} | "
                        f"Advancing {market_breadth['advancing']} | "
                        f"Declining {market_breadth['declining']}"
                    )

            last_engine_health_time = now

        prediction_recent_move = get_recent_price_change(
            PRICE_HISTORY,
            CONTINUATION_SECONDS
        )
        prediction_trend_move = get_recent_price_change(
            PRICE_HISTORY,
            TREND_CONFIRM_SECONDS
        )
        upcoming_activity = get_trade_activity_snapshot(
            now,
            include_next_event=True
        )
        prediction_data = calculate_direction_prediction(
            spy_price,
            spy_change,
            prediction_recent_move,
            prediction_trend_move,
            engine_bias,
            market_breadth_classification,
            last_1m_bid_total,
            last_1m_bid_average,
            volume_filter,
            upcoming_activity["activity_filter"],
            PRICE_HISTORY,
            completed_candles,
            vwap,
            vwap_position,
            opening_range_high,
            opening_range_low,
            opening_range_position
        )
        prediction_data.update(build_pre_market_analysis(
            spy_price,
            spy_bar_volume,
            vwap,
            engine_bias,
            market_breadth_classification,
            prediction_trend_move,
            prediction_recent_move
        ))
        if not opening_confirmation_ready(timeframe_candles):
            prediction_data["prediction"] = "WAIT"
            prediction_data["reason"] += (
                "; waiting for the first completed 1-minute candle after market open"
            )
        stability_data = apply_signal_stability(
            prediction_data["prediction"],
            completed_candles,
            now
        )
        prediction_data.update(stability_data)
        if prediction_data["prediction"] == "CALL":
            prediction_data["invalid_level"] = spy_price - 0.20
        elif prediction_data["prediction"] == "PUT":
            prediction_data["invalid_level"] = spy_price + 0.20
        else:
            prediction_data["invalid_level"] = None
        if prediction_data["mode_stability"] == "LOW":
            prediction_data["reason"] += "; unstable signal forces wait"
        chart_reading = build_chart_reading_analysis(
            spy_price,
            completed_candles,
            timeframe_candles,
            prediction_data["prediction"],
            vwap,
            vwap_position,
            opening_range_high,
            opening_range_low,
            opening_range_position,
            analyze_completed_candles(completed_candles)
        )
        prediction_data.update(chart_reading)
        prediction_data.update(
            build_multi_timeframe_analysis(timeframe_candles, vwap)
        )
        prediction_data["invalid_level"] = chart_reading["invalidation_level"]
        prediction_data = apply_a_plus_setup_filter(
            prediction_data,
            spy_price,
            timeframe_candles,
            engine_bias,
            market_breadth_classification
        )
        prediction_data.update(
            record_trade_activity(now, prediction_data["prediction"])
        )
        prediction_data.update(
            generate_trade_plan(PRICE_HISTORY, prediction_data["prediction"])
        )
        save_prediction_row(spy_price, prediction_data)

        if now - last_diagnostic_print_time >= 60:
            print()
            print("FILTER DIAGNOSTICS")
            print(f"Scans: {scan_count}")
            print(f"Threshold passes: {threshold_pass_count}")
            print(f"Continuation fails: {continuation_fail_count}")
            print(f"Trend fails: {trend_fail_count}")
            print(f"Overextension fails: {overextension_fail_count}")
            print(f"Alerts allowed: {alert_allowed_count}")
            print()
            last_diagnostic_print_time = now

        current_alert_time = time.time()

        alerts_allowed_by_phase = (
            prediction_data["market_phase"] != "Pre-Market Analysis"
            and opening_confirmation_ready(timeframe_candles)
            and prediction_data["a_plus_setup"] == "YES"
        )

        if (
            current_alert_time - last_alert_time >= ALERT_COOLDOWN_SECONDS
            and alerts_allowed_by_phase
        ):

            recent_move = get_recent_price_change(PRICE_HISTORY, CONTINUATION_SECONDS)

            if (
                spy_change >= SPY_MOVE_ALERT_PERCENT
                and prediction_data["prediction"] == "CALL"
            ):
                if recent_move is None or recent_move < MIN_CONTINUATION_MOVE:
                    continuation_fail_count += 1
                    time.sleep(2)
                    continue

                trend_move = get_recent_price_change(
                    PRICE_HISTORY,
                    TREND_CONFIRM_SECONDS
                )

                if (
                    trend_move is None
                    or trend_move < MIN_TREND_CONFIRM_MOVE
                ):
                    trend_fail_count += 1
                    time.sleep(2)
                    continue

                overextension_move = get_absolute_price_move(
                    PRICE_HISTORY,
                    OVEREXTENSION_SECONDS
                )

                if (
                    overextension_move is not None
                    and overextension_move > MAX_OVEREXTENSION_MOVE
                ):
                    overextension_fail_count += 1
                    print(
                        f"Skipping overextended move... "
                        f"{OVEREXTENSION_SECONDS}s move: {overextension_move:.4f}"
                    )
                    time.sleep(2)
                    continue

                print()
                print("POSSIBLE SPY CALL ALERT")
                print(f"SPY moved UP: {spy_change:.4f}% in {TIME_WINDOW_SECONDS} seconds")
                print(f"Recent move: {recent_move:+.4f} in {CONTINUATION_SECONDS} seconds")
                print(f"Trend move: {trend_move:+.4f} in {TREND_CONFIRM_SECONDS} seconds")
                print(
                    f"Overextension move: {format_optional_move(overextension_move)} "
                    f"in {OVEREXTENSION_SECONDS} seconds"
                )
                print(f"SPY price: ${spy_price:.2f}")
                print("Manual check: look at near-the-money CALL options in Webull.")
                print("Paper test only.")
                print()

                save_alert(
                    "UP",
                    "CALL",
                    spy_price,
                    spy_change
                )

                alert_allowed_count += 1
                last_alert_time = time.time()

                track_alert_result("CALL", spy_price, "YES")

                last_alert_time = time.time()

            elif (
                spy_change <= -SPY_MOVE_ALERT_PERCENT
                and prediction_data["prediction"] == "PUT"
            ):
                if recent_move is None or recent_move > -MIN_CONTINUATION_MOVE:
                    continuation_fail_count += 1
                    time.sleep(2)
                    continue

                trend_move = get_recent_price_change(
                    PRICE_HISTORY,
                    TREND_CONFIRM_SECONDS
                )

                if (
                    trend_move is None
                    or trend_move > -MIN_TREND_CONFIRM_MOVE
                ):
                    trend_fail_count += 1
                    time.sleep(2)
                    continue

                overextension_move = get_absolute_price_move(
                    PRICE_HISTORY,
                    OVEREXTENSION_SECONDS
                )

                if (
                    overextension_move is not None
                    and overextension_move > MAX_OVEREXTENSION_MOVE
                ):
                    overextension_fail_count += 1
                    print(
                        f"Skipping overextended move... "
                        f"{OVEREXTENSION_SECONDS}s move: {overextension_move:.4f}"
                    )
                    time.sleep(2)
                    continue

                print()
                print("POSSIBLE SPY PUT ALERT")
                print(f"SPY moved DOWN: {spy_change:.4f}% in {TIME_WINDOW_SECONDS} seconds")
                print(f"Recent move: {recent_move:+.4f} in {CONTINUATION_SECONDS} seconds")
                print(f"Trend move: {trend_move:+.4f} in {TREND_CONFIRM_SECONDS} seconds")
                print(
                    f"Overextension move: {format_optional_move(overextension_move)} "
                    f"in {OVEREXTENSION_SECONDS} seconds"
                )
                print(f"SPY price: ${spy_price:.2f}")
                print("Manual check: look at near-the-money PUT options in Webull.")
                print("Paper test only.")
                print()

                save_alert(
                    "DOWN",
                    "PUT",
                    spy_price,
                    spy_change
                )

                alert_allowed_count += 1
                last_alert_time = time.time()

                track_alert_result("PUT", spy_price, "YES")

                last_alert_time = time.time()

        time.sleep(2)

    except Exception as error:
        print("Error:", error)
        print("Waiting 5 seconds before retrying...")
        time.sleep(5)
