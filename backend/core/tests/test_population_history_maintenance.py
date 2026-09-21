from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

import population_history
import population_history_maintenance as maintenance


AS_OF_DATE = date(2026, 9, 18)
ELIGIBLE_LATEST = date(2026, 9, 14)


def test_required_dates_use_d4_and_the_eleven_day_window():
    dates = maintenance.required_population_dates(AS_OF_DATE)

    assert len(dates) == 11
    assert dates[0] == date(2026, 9, 4)
    assert dates[-1] == ELIGIBLE_LATEST
    assert max(dates) <= AS_OF_DATE - timedelta(days=4)


def test_missing_dates_are_collected_oldest_first():
    required = maintenance.required_population_dates(AS_OF_DATE)
    existing = {required[0], required[3]}
    calls = []

    result = maintenance.maintain_population_history(
        as_of_date=AS_OF_DATE,
        complete_dates_fn=lambda **kwargs: list(existing),
        update_fn=lambda day, **kwargs: calls.append(day),
    )

    assert result.missing_dates == [day for day in required if day not in existing]
    assert calls == result.missing_dates
    assert result.failed_dates == []


def test_complete_dates_are_skipped():
    required = maintenance.required_population_dates(AS_OF_DATE)
    calls = []

    result = maintenance.maintain_population_history(
        as_of_date=AS_OF_DATE,
        complete_dates_fn=lambda **kwargs: required,
        update_fn=lambda day, **kwargs: calls.append(day),
    )

    assert result.missing_dates == []
    assert calls == []


def test_empty_history_bootstraps_the_full_window():
    calls = []

    result = maintenance.maintain_population_history(
        as_of_date=AS_OF_DATE,
        complete_dates_fn=lambda **kwargs: [],
        update_fn=lambda day, **kwargs: calls.append(day),
    )

    assert result.missing_dates == maintenance.required_population_dates(AS_OF_DATE)
    assert result.collected_dates == result.missing_dates
    assert calls == result.missing_dates


def test_failed_day_does_not_stop_later_days():
    required = maintenance.required_population_dates(AS_OF_DATE)
    failed_day = required[4]
    calls = []

    def update(day, **kwargs):
        calls.append(day)
        if day == failed_day:
            raise population_history.PopulationHistoryError("incomplete")

    result = maintenance.maintain_population_history(
        as_of_date=AS_OF_DATE,
        complete_dates_fn=lambda **kwargs: [],
        update_fn=update,
    )

    assert calls == required
    assert result.failed_dates == [failed_day]
    assert result.collected_dates == [day for day in required if day != failed_day]


def test_failed_day_is_selected_again_on_the_next_run():
    required = maintenance.required_population_dates(AS_OF_DATE)
    failed_day = required[2]
    stored = set()
    should_fail = True

    def update(day, **kwargs):
        nonlocal should_fail
        if day == failed_day and should_fail:
            raise population_history.PopulationHistoryError("incomplete")
        stored.add(day)

    first = maintenance.maintain_population_history(
        as_of_date=AS_OF_DATE,
        complete_dates_fn=lambda **kwargs: list(stored),
        update_fn=update,
    )
    should_fail = False
    second = maintenance.maintain_population_history(
        as_of_date=AS_OF_DATE,
        complete_dates_fn=lambda **kwargs: list(stored),
        update_fn=update,
    )

    assert first.failed_dates == [failed_day]
    assert second.missing_dates == [failed_day]
    assert second.collected_dates == [failed_day]


def test_main_returns_nonzero_when_any_collection_failed(monkeypatch):
    required = maintenance.required_population_dates(AS_OF_DATE)
    monkeypatch.setattr(
        maintenance,
        "maintain_population_history",
        lambda **kwargs: maintenance.MaintenanceResult(
            required_dates=required,
            missing_dates=[required[0]],
            collected_dates=[],
            failed_dates=[required[0]],
        ),
    )

    assert maintenance.main(["--as-of-date", AS_OF_DATE.isoformat()]) == 1


def test_complete_date_helper_excludes_incomplete_days(tmp_path):
    complete_day = date(2026, 9, 12)
    incomplete_day = complete_day + timedelta(days=1)
    valid = population_history.normalize_population_rows(
        [
            {
                "YMD": complete_day.strftime("%Y%m%d"),
                "TT": str(hour),
                "H_DNG_CD": str(11110000 + dong),
                "SPOP": "1.0",
            }
            for hour in range(24)
            for dong in range(427)
        ]
    )
    invalid = valid.iloc[:1].copy()
    invalid["datetime"] = invalid["datetime"] + timedelta(days=1)
    population_history._atomic_write_history(
        pd.concat([valid, invalid], ignore_index=True),
        tmp_path / "population_history.csv",
    )

    assert population_history.get_complete_history_dates(
        history_path=tmp_path / "population_history.csv"
    ) == [complete_day]
