"""Maintain the D-4 living-population history required by the provider."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from population_history import (
    DEFAULT_HISTORY_PATH,
    PopulationHistoryError,
    get_complete_history_dates,
    update_population_history,
)


POPULATION_PUBLICATION_LAG_DAYS = 4
D4_HISTORY_WINDOW_DAYS = 11
SEOUL_TIMEZONE = ZoneInfo("Asia/Seoul")


@dataclass(frozen=True)
class MaintenanceResult:
    required_dates: list[date]
    missing_dates: list[date]
    collected_dates: list[date]
    failed_dates: list[date]


def required_population_dates(as_of_date: date | None = None) -> list[date]:
    """Return the D-4 eligible 11-day window in oldest-first order."""
    as_of_date = as_of_date or datetime.now(SEOUL_TIMEZONE).date()
    eligible_latest = as_of_date - timedelta(days=POPULATION_PUBLICATION_LAG_DAYS)
    required_start = eligible_latest - timedelta(days=D4_HISTORY_WINDOW_DAYS - 1)
    return [
        required_start + timedelta(days=offset)
        for offset in range(D4_HISTORY_WINDOW_DAYS)
    ]


def maintain_population_history(
    *,
    as_of_date: date | None = None,
    history_path: str | Path = DEFAULT_HISTORY_PATH,
    complete_dates_fn: Callable[..., list[date]] = get_complete_history_dates,
    update_fn: Callable[..., object] = update_population_history,
) -> MaintenanceResult:
    """Collect only missing complete days; failures remain eligible for the next run."""
    required_dates = required_population_dates(as_of_date)
    complete_dates = set(complete_dates_fn(history_path=history_path))
    missing_dates = [day for day in required_dates if day not in complete_dates]
    collected_dates = []
    failed_dates = []

    for day in missing_dates:
        try:
            update_fn(day, history_path=history_path)
        except PopulationHistoryError:
            failed_dates.append(day)
        else:
            collected_dates.append(day)

    return MaintenanceResult(
        required_dates=required_dates,
        missing_dates=missing_dates,
        collected_dates=collected_dates,
        failed_dates=failed_dates,
    )


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("YYYY-MM-DD 형식이 필요합니다.") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="D-4 생활인구 history 누락일 보충")
    parser.add_argument("--as-of-date", type=_parse_date)
    parser.add_argument("--history-path", default=str(DEFAULT_HISTORY_PATH))
    args = parser.parse_args(argv)

    result = maintain_population_history(
        as_of_date=args.as_of_date,
        history_path=args.history_path,
    )
    print(
        "생활인구 history 유지보수: "
        f"missing={len(result.missing_dates)} "
        f"collected={len(result.collected_dates)} "
        f"failed={len(result.failed_dates)}"
    )
    if result.failed_dates:
        print("실패 날짜: " + ", ".join(day.isoformat() for day in result.failed_dates))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
