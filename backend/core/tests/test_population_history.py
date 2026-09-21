from __future__ import annotations

from datetime import date, datetime

import pandas as pd
import pytest
import requests

import population_history


DAY = date(2026, 9, 12)


def _raw_day(day: date = DAY) -> list[dict[str, str]]:
    return [
        {
            "YMD": day.strftime("%Y%m%d"),
            "TT": str(hour),
            "H_DNG_CD": f" {11110000 + dong} ",
            "SPOP": str(float(hour * 1000 + dong)),
        }
        for hour in range(24)
        for dong in range(427)
    ]


def _normalized_day(day: date = DAY) -> pd.DataFrame:
    return population_history.normalize_population_rows(_raw_day(day))


class _Response:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


def test_normalize_api_rows_parses_datetime_strips_code_and_converts_population():
    frame = population_history.normalize_population_rows(
        [{"YMD": "20260912", "TT": "3", "H_DNG_CD": " 11110515 ", "SPOP": "12.5"}]
    )

    assert frame.loc[0, "datetime"] == pd.Timestamp("2026-09-12 03:00:00")
    assert frame.loc[0, "행정동코드"] == "11110515"
    assert frame.loc[0, "생활인구합계"] == 12.5
    assert pd.api.types.is_numeric_dtype(frame["생활인구합계"])


def test_fetch_population_day_reads_all_1000_row_pages():
    rows = _raw_day()
    calls: list[tuple[int, int]] = []

    def fake_get(url: str, timeout: int):
        parts = url.rsplit("/", 3)
        start, end = int(parts[1]), int(parts[2])
        calls.append((start, end))
        return _Response(
            {
                population_history.SEOUL_POPULATION_SERVICE: {
                    "list_total_count": len(rows),
                    "row": rows[start - 1 : end],
                }
            }
        )

    frame = population_history.fetch_population_day(DAY, api_key="test-key", http_get=fake_get)

    assert len(frame) == 10_248
    assert len(calls) == 11
    assert calls[0] == (1, 1000)
    assert calls[-1] == (10_001, 11_000)


def test_daily_validation_rejects_duplicate_datetime_and_dong():
    frame = _normalized_day()
    duplicate = pd.concat([frame, frame.iloc[[0]]], ignore_index=True)

    with pytest.raises(population_history.PopulationHistoryError, match="중복"):
        population_history.validate_daily_population(duplicate, DAY)


def test_daily_validation_rejects_incomplete_rows():
    with pytest.raises(population_history.PopulationHistoryError, match="행 수"):
        population_history.validate_daily_population(_normalized_day().iloc[:-1], DAY)


def test_daily_validation_rejects_wrong_dong_count():
    frame = _normalized_day()
    frame.loc[frame.index[0], "행정동코드"] = frame.loc[frame.index[1], "행정동코드"]

    with pytest.raises(population_history.PopulationHistoryError, match="행정동"):
        population_history.validate_daily_population(frame, DAY)


def test_daily_validation_rejects_missing_hour():
    frame = _normalized_day()
    frame.loc[frame["datetime"].dt.hour == 23, "datetime"] = pd.Timestamp("2026-09-12 22:00")

    with pytest.raises(population_history.PopulationHistoryError, match="중복|시간"):
        population_history.validate_daily_population(frame, DAY)


def test_update_writes_valid_day_and_is_idempotent(tmp_path, monkeypatch):
    history_path = tmp_path / "population_history.csv"
    frame = _normalized_day()
    monkeypatch.setattr(population_history, "fetch_population_day", lambda *args, **kwargs: frame)

    first = population_history.update_population_history(DAY, history_path=history_path)
    second = population_history.update_population_history(DAY, history_path=history_path)

    assert history_path.exists()
    assert len(first) == 10_248
    assert len(second) == 10_248
    assert not second.duplicated(["datetime", "행정동코드"]).any()


def test_update_adds_a_new_day_incrementally(tmp_path, monkeypatch):
    history_path = tmp_path / "population_history.csv"
    next_day = date(2026, 9, 13)
    frames = {DAY: _normalized_day(DAY), next_day: _normalized_day(next_day)}
    monkeypatch.setattr(
        population_history,
        "fetch_population_day",
        lambda collected_day, **kwargs: frames[pd.Timestamp(collected_day).date()],
    )

    population_history.update_population_history(DAY, history_path=history_path)
    history = population_history.update_population_history(next_day, history_path=history_path)

    assert len(history) == 20_496
    assert history["datetime"].dt.normalize().nunique() == 2


def test_failed_collection_preserves_existing_history(tmp_path, monkeypatch):
    history_path = tmp_path / "population_history.csv"
    existing = _normalized_day()
    population_history._atomic_write_history(existing, history_path)
    original = history_path.read_bytes()

    def fail(*args, **kwargs):
        raise population_history.PopulationHistoryError("API 실패")

    monkeypatch.setattr(population_history, "fetch_population_day", fail)
    with pytest.raises(population_history.PopulationHistoryError, match="API 실패"):
        population_history.update_population_history(date(2026, 9, 13), history_path=history_path)

    assert history_path.read_bytes() == original


def test_loader_returns_provider_schema_and_issue_time_lags(tmp_path):
    history_path = tmp_path / "population_history.csv"
    issue = pd.Timestamp("2026-09-20 10:00:00")
    frame = pd.DataFrame(
        {
            "datetime": [
                issue - pd.Timedelta(hours=96),
                issue - pd.Timedelta(hours=168),
                issue - pd.Timedelta(hours=336),
                issue - pd.Timedelta(hours=1),
            ],
            "행정동코드": ["11110515"] * 4,
            "생활인구합계": [1.0, 2.0, 3.0, 4.0],
        }
    )
    population_history._atomic_write_history(frame, history_path)

    loaded = population_history.load_population_history(issue, history_path=history_path)

    assert list(loaded.columns) == population_history.REQUIRED_HISTORY_COLUMNS
    assert len(loaded) == 3
    assert pd.api.types.is_datetime64_any_dtype(loaded["datetime"])
    assert str(loaded["행정동코드"].dtype) == "string"
    assert pd.api.types.is_numeric_dtype(loaded["생활인구합계"])


def test_loader_floors_minute_issue_time_before_selecting_d4_lags(tmp_path):
    history_path = tmp_path / "population_history.csv"
    issue = pd.Timestamp("2026-09-17 15:10:00")
    expected_times = [
        pd.Timestamp("2026-09-03 15:00:00"),
        pd.Timestamp("2026-09-10 15:00:00"),
        pd.Timestamp("2026-09-13 15:00:00"),
    ]
    population_history._atomic_write_history(
        pd.DataFrame(
            {
                "datetime": expected_times,
                "행정동코드": ["11110515"] * 3,
                "생활인구합계": [1.0, 2.0, 3.0],
            }
        ),
        history_path,
    )

    loaded = population_history.load_population_history(issue, history_path=history_path)

    assert loaded["datetime"].tolist() == expected_times


def test_api_failure_does_not_print_api_key(capsys):
    def fail(*args, **kwargs):
        raise requests.Timeout("timeout")

    with pytest.raises(population_history.PopulationHistoryError):
        population_history.fetch_population_day(DAY, api_key="secret-value", http_get=fail)

    captured = capsys.readouterr()
    assert "secret-value" not in captured.out
    assert "secret-value" not in captured.err
