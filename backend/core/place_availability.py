import math
import re

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo


SEOUL_TIMEZONE = ZoneInfo("Asia/Seoul")
DAY_CODES = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
TIME_PATTERN = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


def _result(status, arrival_at, opening_at=None, closing_at=None):
    remaining_minutes = None
    if status == "open":
        remaining_minutes = int(
            (closing_at - arrival_at).total_seconds() // 60
        )

    return {
        "status": status,
        "arrival_at": arrival_at,
        "opening_at": opening_at,
        "closing_at": closing_at,
        "remaining_minutes": remaining_minutes,
    }


def _parse_date(value):
    if value is None:
        return None, True

    if not isinstance(value, str):
        return None, False

    try:
        return date.fromisoformat(value), True
    except ValueError:
        return None, False


def _parse_time(value, allow_24=False):
    if value == "24:00" and allow_24:
        return 24 * 60

    if not isinstance(value, str) or not TIME_PATTERN.fullmatch(value):
        return None

    parsed = time.fromisoformat(value)
    return parsed.hour * 60 + parsed.minute


def _build_schedule(schedule, arrival_date, start_at, end_at):
    intervals = []
    exact_closed_days = set()
    special_days = set()
    invalid = False

    for item in schedule:
        if not isinstance(item, dict):
            invalid = True
            continue

        days = item.get("days")
        closed = item.get("closed")

        if (
            not isinstance(days, list)
            or not days
            or any(day not in DAY_CODES for day in days)
            or not isinstance(closed, bool)
        ):
            invalid = True
            continue

        matching_dates = [
            candidate_date
            for candidate_date in (arrival_date - timedelta(days=1), arrival_date)
            if DAY_CODES[candidate_date.weekday()] in days
        ]

        if item.get("special_days"):
            special_days.update(matching_dates)
            continue

        if closed:
            if item.get("opening_time") is not None or item.get("closing_time") is not None:
                invalid = True
            exact_closed_days.update(matching_dates)
            continue

        opening_minutes = _parse_time(item.get("opening_time"))
        closing_minutes = _parse_time(item.get("closing_time"), allow_24=True)
        closes_next_day = item.get("closes_next_day", False)

        if (
            opening_minutes is None
            or closing_minutes is None
            or opening_minutes == closing_minutes
            or not isinstance(closes_next_day, bool)
            or (closing_minutes < opening_minutes and not closes_next_day)
            or (closing_minutes >= opening_minutes and closes_next_day)
        ):
            invalid = True
            continue

        for opening_date in matching_dates:
            if start_at is not None and opening_date < start_at:
                continue
            if end_at is not None and opening_date > end_at:
                continue

            opening_at = datetime.combine(
                opening_date,
                time.min,
                tzinfo=SEOUL_TIMEZONE,
            ) + timedelta(minutes=opening_minutes)
            closing_at = datetime.combine(
                opening_date,
                time.min,
                tzinfo=SEOUL_TIMEZONE,
            ) + timedelta(minutes=closing_minutes)

            if closes_next_day:
                closing_at += timedelta(days=1)

            intervals.append((opening_date, opening_at, closing_at))

    open_days = {opening_date for opening_date, _, _ in intervals}
    if open_days.intersection(exact_closed_days):
        invalid = True

    return intervals, exact_closed_days, special_days, invalid


def evaluate_place_availability(
    place: dict,
    current_datetime: datetime,
    travel_minutes: int | float,
) -> dict:
    """실제 이동 후 도착시각을 기준으로 장소 운영 가능 여부를 계산한다."""

    if not isinstance(current_datetime, datetime) or current_datetime.utcoffset() is None:
        raise ValueError("current_datetime은 timezone-aware datetime이어야 합니다.")

    if (
        isinstance(travel_minutes, bool)
        or not isinstance(travel_minutes, (int, float))
        or not math.isfinite(travel_minutes)
        or travel_minutes < 0
    ):
        raise ValueError("travel_minutes는 0 이상의 유한한 숫자여야 합니다.")

    arrival_at = (
        current_datetime.astimezone(SEOUL_TIMEZONE)
        + timedelta(minutes=travel_minutes)
    )
    arrival_date = arrival_at.date()
    start_at, valid_start = _parse_date(place.get("start_at"))
    end_at, valid_end = _parse_date(place.get("end_at"))

    if not valid_start or not valid_end or (
        start_at is not None and end_at is not None and start_at > end_at
    ):
        return _result("unknown", arrival_at)

    if start_at is not None and arrival_date < start_at:
        return _result("event_not_started", arrival_at)

    schedule_status = place.get("operation_schedule_status")
    schedule = place.get("operation_schedule")

    if schedule_status != "parsed" or not isinstance(schedule, list) or not schedule:
        if end_at is not None and arrival_date > end_at:
            return _result("event_ended", arrival_at)
        return _result("unknown", arrival_at)

    intervals, closed_days, special_days, invalid = _build_schedule(
        schedule,
        arrival_date,
        start_at,
        end_at,
    )

    if invalid:
        return _result("unknown", arrival_at)

    active_intervals = [
        interval
        for interval in intervals
        if interval[1] <= arrival_at < interval[2]
    ]

    if active_intervals:
        opening_at = min(interval[1] for interval in active_intervals)
        closing_at = max(interval[2] for interval in active_intervals)
        return _result("open", arrival_at, opening_at, closing_at)

    if end_at is not None and arrival_date > end_at:
        if any(arrival_at == interval[2] for interval in intervals):
            return _result("closed", arrival_at)
        return _result("event_ended", arrival_at)

    future_intervals = sorted(
        (
            interval
            for interval in intervals
            if interval[0] == arrival_date and interval[1] > arrival_at
        ),
        key=lambda interval: interval[1],
    )

    if future_intervals:
        if arrival_date in special_days:
            return _result("unknown", arrival_at)
        _, opening_at, closing_at = future_intervals[0]
        return _result("not_yet_open", arrival_at, opening_at, closing_at)

    if arrival_date in special_days:
        return _result("unknown", arrival_at)

    if arrival_date in closed_days or intervals:
        return _result("closed", arrival_at)

    return _result("closed", arrival_at)
