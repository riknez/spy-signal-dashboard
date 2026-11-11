"""NYSE session awareness for the cloud scanner worker.

Uses the official XNYS calendar from `exchange_calendars`, which covers
market holidays, early closes (e.g. 1:00 PM ET the day after Thanksgiving)
and daylight-saving changes. All returned datetimes are timezone-aware
America/New_York.

This module does not touch any signal logic.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import pandas as pd

EASTERN = ZoneInfo("America/New_York")
_CAL = xcals.get_calendar("XNYS")


@dataclass(frozen=True)
class SessionState:
    now: datetime
    is_open: bool
    session_date: str | None      # trading date for the current/most recent session
    open_at: datetime | None
    close_at: datetime | None
    early_close: bool
    next_open: datetime
    label: str                    # "LIVE" or "HISTORICAL"


def _eastern(ts: pd.Timestamp) -> datetime:
    return ts.tz_convert(EASTERN).to_pydatetime()


def session_state(now: datetime | None = None) -> SessionState:
    now = (now or datetime.now(EASTERN)).astimezone(EASTERN)
    ts = pd.Timestamp(now)
    is_open = bool(_CAL.is_open_on_minute(ts.floor("min")))

    day = pd.Timestamp(now.date())
    if _CAL.is_session(day) and now >= _eastern(_CAL.session_open(day)):
        session = day
    else:
        session = _CAL.date_to_session(day, direction="previous")
        if session == day:  # today is a session but it hasn't opened yet
            session = _CAL.previous_session(day)

    open_at = _eastern(_CAL.session_open(session))
    close_at = _eastern(_CAL.session_close(session))
    early_close = close_at.time() < datetime.strptime("16:00", "%H:%M").time()
    next_open = _eastern(_CAL.next_open(ts))

    return SessionState(
        now=now,
        is_open=is_open,
        session_date=session.strftime("%Y-%m-%d"),
        open_at=open_at,
        close_at=close_at,
        early_close=early_close,
        next_open=next_open,
        label="LIVE" if is_open else "HISTORICAL",
    )


def seconds_until_next_open(now: datetime | None = None) -> float:
    state = session_state(now)
    if state.is_open:
        return 0.0
    return max(0.0, (state.next_open - state.now).total_seconds())


if __name__ == "__main__":
    s = session_state()
    print(s)
