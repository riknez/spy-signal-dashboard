import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "worker"))
from market_session import EASTERN, session_state, seconds_until_next_open  # noqa: E402


def et(*args):
    return datetime(*args, tzinfo=EASTERN)


def test_regular_day_open_and_close():
    assert session_state(et(2026, 11, 11, 9, 29)).is_open is False
    assert session_state(et(2026, 11, 11, 9, 30)).is_open is True
    assert session_state(et(2026, 11, 11, 15, 59)).is_open is True
    assert session_state(et(2026, 11, 11, 16, 0)).is_open is False


def test_thanksgiving_closed_and_retains_previous_session():
    s = session_state(et(2026, 11, 26, 12, 0))
    assert s.is_open is False
    assert s.label == "HISTORICAL"
    assert s.session_date == "2026-11-25"
    assert s.next_open == et(2026, 11, 27, 9, 30)


def test_early_close_day_after_thanksgiving():
    assert session_state(et(2026, 11, 27, 12, 59)).is_open is True
    s = session_state(et(2026, 11, 27, 13, 0))
    assert s.is_open is False
    assert s.early_close is True
    assert s.close_at == et(2026, 11, 27, 13, 0)


def test_christmas_eve_early_close_and_christmas_closed():
    assert session_state(et(2026, 12, 24, 13, 5)).is_open is False
    assert session_state(et(2026, 12, 25, 11, 0)).is_open is False


def test_weekend_and_premarket_point_to_previous_session():
    sat = session_state(et(2026, 11, 14, 10, 0))
    assert sat.is_open is False and sat.session_date == "2026-11-13"
    pre = session_state(et(2026, 11, 16, 8, 0))
    assert pre.session_date == "2026-11-13"
    assert pre.next_open == et(2026, 11, 16, 9, 30)


def test_dst_transition_open_stays_930_eastern():
    # DST ends Nov 1 2026; UTC open shifts from 13:30 to 14:30 automatically.
    before = session_state(et(2026, 10, 30, 10, 0))
    after = session_state(et(2026, 11, 2, 10, 0))
    assert before.open_at.hour == after.open_at.hour == 9
    assert before.open_at.utcoffset() != after.open_at.utcoffset()


def test_seconds_until_open():
    assert seconds_until_next_open(et(2026, 11, 11, 10, 0)) == 0
    assert seconds_until_next_open(et(2026, 11, 11, 9, 0)) == 1800
