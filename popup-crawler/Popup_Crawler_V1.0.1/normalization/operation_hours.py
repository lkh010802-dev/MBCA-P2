from __future__ import annotations

import re
from collections import defaultdict
from datetime import date
from typing import Any, Iterable

DAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
KOR_DAY = {
    "월": "MON", "화": "TUE", "수": "WED", "목": "THU",
    "금": "FRI", "토": "SAT", "일": "SUN",
}
ENG_DAY = {
    "MON": "MON", "MONDAY": "MON",
    "TUE": "TUE", "TUES": "TUE", "TUESDAY": "TUE",
    "WED": "WED", "WEDNESDAY": "WED",
    "THU": "THU", "THUR": "THU", "THURS": "THU", "THURSDAY": "THU",
    "FRI": "FRI", "FRIDAY": "FRI",
    "SAT": "SAT", "SATURDAY": "SAT",
    "SUN": "SUN", "SUNDAY": "SUN",
}
DAY_INDEX = {day: index for index, day in enumerate(DAYS)}
TIME_TOKEN = r"(?:[01]?\d|2[0-3]):[0-5]\d|24:00"
TIME_RE = re.compile(rf"(?<!\d)({TIME_TOKEN})\s*[~～\-–—]\s*({TIME_TOKEN})(?!\d)")
CLOSED_RE = re.compile(r"휴무|휴뮤|휴점|정기휴일|closed?|close\b", re.I)

_ENG_DAY_TOKEN = r"(?:MON(?:DAY)?|TUE(?:S|SDAY)?|WED(?:NESDAY)?|THU(?:R|RS|RSDAY)?|FRI(?:DAY)?|SAT(?:URDAY)?|SUN(?:DAY)?)"
_KOR_DAY_TOKEN = r"(?:[월화수목금토일](?:요일)?)"
_DAYISH_PREFIX = rf"(?:매일|평일|주말|{_KOR_DAY_TOKEN}(?:\s*[~\-/,·]\s*{_KOR_DAY_TOKEN})*|{_ENG_DAY_TOKEN}(?:\s*[~\-/,]\s*{_ENG_DAY_TOKEN})*)"


def _clean(value: Any) -> str:
    text = str(value or "")
    text = text.replace("\u00a0", " ").replace("～", "~").replace("–", "-").replace("—", "-")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _expand_range(start: str, end: str) -> list[str]:
    a = DAY_INDEX[start]
    b = DAY_INDEX[end]
    if a <= b:
        return DAYS[a:b + 1]
    return DAYS[a:] + DAYS[:b + 1]


def _unique(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _eng_day(token: str) -> str | None:
    return ENG_DAY.get(token.upper().replace(".", ""))


def _extract_days(
    text: str,
    *,
    weekday_excludes_friday: bool = False,
) -> tuple[list[str], list[str]]:
    compact = re.sub(r"\s+", "", text)
    special_days: list[str] = []
    if "공휴일" in compact or re.search(r"PUBLIC\s*HOLIDAY|HOLIDAY", text, re.I):
        special_days.append("PUBLIC_HOLIDAY")

    if any(token in compact for token in ("매일", "월~일", "월-일", "월요일~일요일", "월요일-일요일")):
        return DAYS.copy(), special_days
    if re.search(r"\bDAILY\b|EVERY\s*DAY", text, re.I):
        return DAYS.copy(), special_days
    if "평일" in compact:
        # Department-store feeds often publish ``평일 ... , 금~일 ...``.
        # In that context Friday has its own explicitly published schedule, so
        # interpreting 평일 as MON-FRI creates a false duplicate Friday window.
        return (DAYS[:4] if weekday_excludes_friday else DAYS[:5]), special_days
    if "주말" in compact:
        return DAYS[5:], special_days
    if re.search(r"\bWEEKDAYS?\b", text, re.I):
        return (DAYS[:4] if weekday_excludes_friday else DAYS[:5]), special_days
    if re.search(r"\bWEEKENDS?\b", text, re.I):
        return DAYS[5:], special_days

    found: list[str] = []
    for match in re.finditer(r"([월화수목금토일])(?:요일)?\s*[~\-]\s*([월화수목금토일])(?:요일)?", text):
        found.extend(_expand_range(KOR_DAY[match.group(1)], KOR_DAY[match.group(2)]))

    scrubbed = re.sub(r"([월화수목금토일])(?:요일)?\s*[~\-]\s*([월화수목금토일])(?:요일)?", " ", text)
    for token in re.findall(r"([월화수목금토일])(?:요일)?", scrubbed):
        found.append(KOR_DAY[token])

    # English weekday/range support, e.g. ``MON-FRI,SUN`` / ``SAT``.
    eng_range_re = re.compile(rf"({_ENG_DAY_TOKEN})\s*[~\-]\s*({_ENG_DAY_TOKEN})", re.I)
    for match in eng_range_re.finditer(text):
        start = _eng_day(match.group(1))
        end = _eng_day(match.group(2))
        if start and end:
            found.extend(_expand_range(start, end))

    eng_scrubbed = eng_range_re.sub(" ", text)
    for token in re.findall(_ENG_DAY_TOKEN, eng_scrubbed, re.I):
        day = _eng_day(token)
        if day:
            found.append(day)

    return _unique(found), special_days


def _extract_closed_days(text: str) -> list[str]:
    """Extract weekdays explicitly attached to a closed/holiday marker.

    Examples:
      - ``매주 일요일 휴무`` -> ["SUN"]
      - ``Sun, Mon close`` -> ["SUN", "MON"]

    The search is intentionally local to each close marker so unrelated weekday
    schedules elsewhere in the same line are not treated as closed.
    """
    found: list[str] = []
    for match in CLOSED_RE.finditer(text):
        prefix = text[max(0, match.start() - 80):match.start()]
        # Parenthetical closures should use only the current parenthesis tail.
        if "(" in prefix and prefix.rfind("(") > prefix.rfind(")"):
            prefix = prefix[prefix.rfind("(") + 1:]
        else:
            # If an active time range precedes the closure, discard everything
            # through the last clock token so active weekday prefixes do not
            # leak into the closed-day set.
            clocks = list(re.finditer(rf"(?<!\d){TIME_TOKEN}(?!\d)", prefix))
            if clocks:
                prefix = prefix[clocks[-1].end():]
        prefix = re.split(r"[|;)]", prefix)[-1]
        prefix = re.split(r"\s{2,}", prefix)[-1]
        days, _special = _extract_days(prefix)
        found.extend(days)
    return _unique(found)


def _repair_obvious_time_typos(text: str) -> str:
    """Repair only low-risk clock typos before structured parsing.

    Examples seen in DayForYou:
      - ``10:0``   -> ``10:00``
      - ``22:000`` -> ``22:00``

    Three-plus digit minutes are repaired only when the extra suffix is all
    zeros and the first two digits form a valid minute. Other malformed values
    remain untouched instead of being guessed.
    """
    def repl(match: re.Match[str]) -> str:
        hour_text, minute_text = match.group(1), match.group(2)
        hour = int(hour_text)
        minute = minute_text
        if hour > 24:
            return match.group(0)
        if len(minute) == 1:
            minute = "0" + minute
        elif len(minute) > 2:
            first_two, suffix = minute[:2], minute[2:]
            if int(first_two) <= 59 and suffix and set(suffix) == {"0"}:
                minute = first_two
            else:
                return match.group(0)
        if int(minute) > 59:
            return match.group(0)
        if hour == 24 and minute != "00":
            return match.group(0)
        return f"{hour:02d}:{minute}"

    return re.sub(r"(?<!\d)(\d{1,2}):(\d{1,4})(?!\d)", repl, text)


def _time_ranges(text: str) -> list[tuple[str, str]]:
    text = _repair_obvious_time_typos(text)
    result: list[tuple[str, str]] = []
    for match in TIME_RE.finditer(text):
        result.append((match.group(1).zfill(5), match.group(2).zfill(5)))
    if result:
        return result

    # DayForYou occasionally drops the range separator entirely, e.g.
    # ``시간 : 10:30 22:00``. Treat whitespace as a range separator only when
    # the whole value contains exactly two clock tokens. Session/performance
    # lists with three or more times therefore remain unparsed.
    tokens = re.findall(rf"(?<!\d)({TIME_TOKEN})(?!\d)", text)
    if len(tokens) == 2:
        spaced = re.search(
            rf"(?<!\d)({TIME_TOKEN})\s+({TIME_TOKEN})(?!\d)",
            text,
        )
        if spaced:
            return [(spaced.group(1).zfill(5), spaced.group(2).zfill(5))]
    return []


def _explicit_day_time_segments(text: str) -> list[str]:
    """Find adjacent day+time schedules even when the source omitted separators.

    Example: ``월-목 10:00 ~ 20:00 금-일 10:00 ~ 20:30``.
    """
    loose_time = r"(?:[0-2]?\d):\d{1,4}"
    range_text = rf"{loose_time}\s*[~～\-–—]\s*{loose_time}"
    pattern = re.compile(rf"({_DAYISH_PREFIX})\s*[:：]?\s*({range_text})", re.I)
    matches = [match.group(0).strip() for match in pattern.finditer(text)]
    return matches if len(matches) >= 2 else []


def _split_segments(text: str) -> list[str]:
    # Strong separators first. Pipe is common in English venue hours.
    for separator in (r"\s*[|;]\s*",):
        parts = [part.strip() for part in re.split(separator, text) if part.strip()]
        useful = [part for part in parts if _time_ranges(part) or CLOSED_RE.search(part)]
        if len(useful) >= 2:
            return useful

    # Slash can be either a schedule separator or part of the day expression
    # itself (``금~일/공휴일``). Never split the latter.
    if not re.search(r"[월화수목금토일](?:요일)?\s*/\s*공휴일", text):
        parts = [part.strip() for part in re.split(r"\s*/\s*", text) if part.strip()]
        useful = [part for part in parts if _time_ranges(part) or CLOSED_RE.search(part)]
        if len(useful) >= 2:
            return useful

    # Comma only counts as a schedule separator when multiple comma-separated
    # parts independently contain a time/closed marker. This preserves English
    # day lists such as ``MON-FRI,SUN 12:00-21:30``.
    # Do not split commas inside an English/Korean closed-day parenthesis such
    # as ``11:00-18:00 (Sun, Mon close)``.
    if not re.search(r"\([^)]*(?:휴무|휴뮤|휴점|정기휴일|closed?|close\b)[^)]*\)", text, re.I):
        parts = [part.strip() for part in re.split(r"\s*,\s*", text) if part.strip()]
        useful = [part for part in parts if _time_ranges(part) or CLOSED_RE.search(part)]
        if len(useful) >= 2:
            return useful

    explicit = _explicit_day_time_segments(text)
    if explicit:
        return explicit

    return [text]


def _derive_uniform_legacy_pair(schedule: list[dict[str, Any]]) -> tuple[str | None, str | None]:
    """Return a legacy flat pair only when it is globally unambiguous.

    This helper exists only for backwards compatibility with direct parser
    callers. Backend/master data must use ``operation_schedule`` instead.
    A flat pair is safe only when all seven ordinary weekdays are covered by
    exactly one identical active window and there is no explicit closed day.
    """
    if not schedule or any(item.get("closed") for item in schedule):
        return None, None

    active = [
        item for item in schedule
        if item.get("opening_time") and item.get("closing_time")
    ]
    if not active:
        return None, None

    per_day: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for item in active:
        window = (str(item["opening_time"]), str(item["closing_time"]))
        for day in item.get("days") or []:
            if day in DAYS:
                per_day[day].add(window)

    if set(per_day) != set(DAYS):
        return None, None
    if any(len(windows) != 1 for windows in per_day.values()):
        return None, None

    windows = {next(iter(per_day[day])) for day in DAYS}
    if len(windows) != 1:
        return None, None
    return next(iter(windows))


def resolve_schedule_for_day(
    schedule: list[dict[str, Any]],
    day: str,
) -> dict[str, Any]:
    """Resolve the exact schedule for one weekday without widening hours.

    ``today_opening_time`` / ``today_closing_time`` are populated only when
    the selected weekday has exactly one active time window. Split-session
    days stay null at the scalar level and remain fully represented in
    ``today_schedule``. ``today_closed`` is True only for an explicit closure,
    False only when an active window exists, and None when unknown/conflicting.
    """
    day = str(day or "").upper()
    if day not in DAYS:
        raise ValueError(f"unsupported weekday: {day!r}")

    matching = [
        dict(item) for item in schedule
        if day in (item.get("days") or [])
    ]
    active = [
        item for item in matching
        if not item.get("closed")
        and item.get("opening_time")
        and item.get("closing_time")
    ]
    closed = [item for item in matching if item.get("closed")]

    opening_time: str | None = None
    closing_time: str | None = None
    today_closed: bool | None

    if active and not closed:
        today_closed = False
        if len(active) == 1:
            opening_time = str(active[0]["opening_time"])
            closing_time = str(active[0]["closing_time"])
    elif closed and not active:
        today_closed = True
    else:
        # No published schedule for this weekday, or conflicting active/closed
        # records. Do not guess.
        today_closed = None

    return {
        "today_day": day,
        "today_schedule": matching,
        "today_opening_time": opening_time,
        "today_closing_time": closing_time,
        "today_closed": today_closed,
    }


def resolve_schedule_for_date(
    schedule: list[dict[str, Any]],
    target_date: date,
) -> dict[str, Any]:
    return resolve_schedule_for_day(schedule, DAYS[target_date.weekday()])


def parse_operation_schedule(raw_values: Any) -> tuple[list[dict[str, Any]], str | None, str | None]:
    if raw_values in (None, "", [], ()):  # common empty shapes
        return [], None, None
    if isinstance(raw_values, str):
        values = [raw_values]
    else:
        values = [str(value) for value in raw_values if value not in (None, "")]

    schedule: list[dict[str, Any]] = []
    inherited_days: list[str] | None = None
    inherited_special: list[str] | None = None

    combined_values = " | ".join(_clean(value) for value in values)
    global_closed_days = _extract_closed_days(combined_values)
    global_weekday_excludes_friday = bool(
        "평일" in combined_values
        and re.search(r"금(?:요일)?\s*[~\-]\s*일(?:요일)?", combined_values)
    )

    for raw in values:
        text = _clean(raw)
        if not text or re.search(r"추후\s*공지|미정|TBD", text, re.I):
            continue

        # If Friday-Sunday is explicitly separated, ``평일`` in the same source
        # line means Monday-Thursday for this schedule.
        weekday_excludes_friday = global_weekday_excludes_friday or bool(
            re.search(r"평일.*금(?:요일)?\s*[~\-]\s*일(?:요일)?", text)
            or re.search(r"금(?:요일)?\s*[~\-]\s*일(?:요일)?.*평일", text)
            or re.search(r"WEEKDAYS?.*FRI(?:DAY)?\s*[~\-]\s*SUN(?:DAY)?", text, re.I)
        )

        segments = _split_segments(text)
        for segment in segments:
            days, special_days = _extract_days(
                segment,
                weekday_excludes_friday=weekday_excludes_friday,
            )
            if days:
                inherited_days = days
                inherited_special = special_days
            elif inherited_days:
                days = inherited_days.copy()
                special_days = list(inherited_special or [])

            closed_marker = bool(CLOSED_RE.search(segment))
            closed_days = _extract_closed_days(segment)
            ranges = _time_ranges(segment)

            # A mixed expression such as ``11:00-18:00 (Sun, Mon close)``
            # publishes both an active window and explicit closed weekdays.
            if ranges:
                # Weekdays mentioned after the time range often belong only to
                # a closed-day suffix (``11:00-18:00 (Sun, Mon close)``).
                # Derive active weekdays from the prefix before the first clock
                # whenever possible, then apply explicit closure exceptions.
                first_clock = re.search(rf"(?<!\d){TIME_TOKEN}(?!\d)", segment)
                prefix_text = segment[:first_clock.start()] if first_clock else segment
                prefix_days, _prefix_special = _extract_days(
                    prefix_text,
                    weekday_excludes_friday=weekday_excludes_friday,
                )

                if prefix_days:
                    active_days = list(prefix_days)
                elif closed_days or global_closed_days:
                    active_days = [day for day in DAYS if day not in set(global_closed_days or closed_days)]
                else:
                    active_days = list(days or DAYS)

                if closed_days:
                    active_days = [day for day in active_days if day not in set(closed_days)]

                for open_time, close_time in ranges:
                    if active_days:
                        item = {
                            "days": active_days,
                            "opening_time": open_time,
                            "closing_time": close_time,
                            "closed": False,
                        }
                        if special_days:
                            item["special_days"] = special_days
                        schedule.append(item)

                if closed_marker and closed_days:
                    schedule.append({
                        "days": closed_days,
                        "opening_time": None,
                        "closing_time": None,
                        "closed": True,
                    })
                continue

            if closed_marker:
                item: dict[str, Any] = {
                    "days": closed_days or days or [],
                    "opening_time": None,
                    "closing_time": None,
                    "closed": True,
                }
                if special_days:
                    item["special_days"] = special_days
                schedule.append(item)
                continue

    # Ensure all explicitly published closed weekdays survive segmentation.
    if global_closed_days:
        schedule.append({
            "days": global_closed_days,
            "opening_time": None,
            "closing_time": None,
            "closed": True,
        })

    # De-duplicate structurally identical entries while preserving order.
    deduped: list[dict[str, Any]] = []
    seen: set[tuple] = set()
    for item in schedule:
        key = (
            tuple(item.get("days") or []),
            item.get("opening_time"),
            item.get("closing_time"),
            bool(item.get("closed")),
            tuple(item.get("special_days") or []),
        )
        if key not in seen:
            seen.add(key)
            deduped.append(item)

    legacy_opening, legacy_closing = _derive_uniform_legacy_pair(deduped)
    return deduped, legacy_opening, legacy_closing


def operation_fields(raw_values: Any) -> dict[str, Any]:
    if raw_values in (None, "", [], ()):
        raw: list[str] = []
    elif isinstance(raw_values, str):
        raw = [_clean(raw_values)] if _clean(raw_values) else []
    else:
        raw = [_clean(value) for value in raw_values if _clean(value)]

    schedule, _legacy_opening, _legacy_closing = parse_operation_schedule(raw)
    return {
        "operation_hours_raw": raw,
        "operation_schedule": schedule,
    }
