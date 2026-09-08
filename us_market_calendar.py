"""US equity sessions, including holidays, DST and early closes (offline calendar)."""
from datetime import datetime, timezone
from functools import lru_cache

import exchange_calendars as xcals
import pandas as pd

SOURCE_URL = "https://www.nasdaq.com/market-activity/stock-market-holiday-schedule"
PUBLICATION_GRACE_MINUTES = 30


def utc_now(now=None):
    value = pd.Timestamp(now if now is not None else datetime.now(timezone.utc))
    return value.tz_localize("UTC") if value.tzinfo is None else value.tz_convert("UTC")


@lru_cache(maxsize=8)
def calendar(start_year, end_year):
    return xcals.get_calendar("XNYS", start=f"{start_year}-01-01", end=f"{end_year}-12-31")


def completed_daily_rows(stamps, closes, now=None):
    """Ignore intraday/holiday bars; close time comes from the session, not +6.5h."""
    current = utc_now(now)
    if not stamps:
        return []
    times = pd.to_datetime(stamps, unit="s", utc=True)
    dates = times.tz_convert("America/New_York").strftime("%Y-%m-%d")
    cal = calendar(min(times.year)-1, max(current.year, max(times.year))+1)
    rows = []
    for day, price in zip(dates, closes):
        if day in cal.schedule.index and cal.schedule.loc[day, "close"] <= current:
            rows.append((day, price))
    return rows


def market_context(asof, now=None):
    current = utc_now(now)
    today = current.tz_convert("America/New_York").date()
    asof = pd.Timestamp(asof).normalize().tz_localize(None)
    cal = calendar(min(asof.year, today.year)-1, today.year+1)
    schedule = cal.schedule
    completed = schedule[schedule["close"] <= current]
    expected = schedule[schedule["close"] + pd.Timedelta(minutes=PUBLICATION_GRACE_MINUTES) <= current]
    latest = completed.index[-1]
    missing = len(expected.loc[(expected.index > asof)])
    pending = bool(asof < latest and missing == 0)
    upcoming = schedule[schedule["close"] > current]
    next_session = upcoming.iloc[0]
    current_session = schedule.loc[str(today)] if str(today) in schedule.index else None
    state = ("holiday" if today.weekday() < 5 else "weekend") if current_session is None else (
        "premarket" if current < current_session["open"] else
        "open" if current < current_session["close"] else "closed")
    # Send a bounded schedule so static Pages can update its status as time passes.
    start = pd.Timestamp(today) - pd.Timedelta(days=40)
    end = pd.Timestamp(today) + pd.Timedelta(days=35)
    selected = schedule.loc[start:end]
    holidays = cal.regular_holidays.holidays(start=start, end=end, return_name=True)
    closures = []
    for day in pd.date_range(start, end):
        if day not in selected.index:
            reason = "周末休市" if day.weekday() >= 5 else str(holidays.get(day, "美股节假日休市"))
            closures.append({"date": day.strftime("%Y-%m-%d"), "reason": reason})
    return {
        "checked_at": current.isoformat(), "market_state": state,
        "latest_completed_session": latest.strftime("%Y-%m-%d"),
        "expected_asof": expected.index[-1].strftime("%Y-%m-%d"),
        "missing_sessions": missing, "publication_pending": pending,
        "next_close_beijing": next_session["close"].tz_convert("Asia/Shanghai").strftime("%Y-%m-%d %H:%M"),
        "source_url": SOURCE_URL,
        "calendar": {
            "valid_from": start.strftime("%Y-%m-%d"), "valid_until": end.strftime("%Y-%m-%d"),
            "grace_minutes": PUBLICATION_GRACE_MINUTES,
            "sessions": [{"date": day.strftime("%Y-%m-%d"), "open": row["open"].isoformat(),
                          "close": row["close"].isoformat()} for day,row in selected.iterrows()],
            "closures": closures,
        },
    }
