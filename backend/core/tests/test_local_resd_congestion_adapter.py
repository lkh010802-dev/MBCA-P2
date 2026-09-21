from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import pytest

from local_resd_congestion_adapter import (
    D4DirectCongestionAdapter,
    ML_CONGESTION_SOURCE,
    NEUTRAL_CONGESTION_SCORE,
    select_d4_horizon,
)


ISSUE_TIME = datetime(2026, 9, 12, 10, 0)


class FakeProvider:
    def __init__(self, result: dict | None = None, error: Exception | None = None):
        self.result = result or {
            "status": "ok",
            "forecasts": [
                {
                    "horizon_hours": horizon,
                    "p0": 0.1,
                    "p1": 0.2,
                    "p2": 0.3,
                    "p3": 0.4,
                    "relative_congestion_index": 2.0,
                }
                for horizon in range(1, 7)
            ],
        }
        self.error = error
        self.calls = 0

    def predict(self, local_resd, issue_time, population):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result


@pytest.fixture
def population():
    return pd.DataFrame(
        {
            "datetime": [ISSUE_TIME - timedelta(hours=96)],
            "행정동코드": ["11110515"],
            "생활인구합계": [100.0],
        }
    )


@pytest.mark.parametrize(
    ("minutes", "horizon"),
    [
        (1, 1), (60, 1), (61, 2), (120, 2), (121, 3), (180, 3),
        (181, 4), (240, 4), (241, 5), (300, 5), (301, 6), (360, 6),
    ],
)
def test_select_d4_horizon_uses_ceiling_boundaries(minutes, horizon):
    assert select_d4_horizon(ISSUE_TIME, ISSUE_TIME + timedelta(minutes=minutes)) == horizon


@pytest.mark.parametrize("minutes", [0, -1, 361])
def test_select_d4_horizon_rejects_non_positive_and_over_six_hours(minutes):
    assert select_d4_horizon(ISSUE_TIME, ISSUE_TIME + timedelta(minutes=minutes)) is None


def test_success_returns_probability_weighted_score_and_diagnostics(population):
    provider = FakeProvider()
    adapter = D4DirectCongestionAdapter(provider=provider)

    result = adapter.predict("11110515", ISSUE_TIME, ISSUE_TIME + timedelta(minutes=61), population)

    assert result["congestion_source"] == ML_CONGESTION_SOURCE
    assert result["congestion_status"] == "ok"
    assert result["horizon"] == 2
    assert result["congestion_score"] == pytest.approx(2.3)
    assert 1 <= result["congestion_score"] <= 5
    assert provider.calls == 1


@pytest.mark.parametrize(
    "result,status",
    [
        ({"status": "unsupported_region"}, "unsupported_region"),
        ({"status": "insufficient_history"}, "insufficient_history"),
        ({"status": "population_source_failure"}, "population_source_failure"),
        ({"status": "inference_failure"}, "inference_failure"),
        ({"status": "ok", "forecasts": [{"horizon_hours": 1}]}, "malformed_provider_output"),
        ({"status": "ok", "forecasts": [{"horizon_hours": 1, "p0": 1.2, "p1": 0, "p2": 0, "p3": 0, "relative_congestion_index": 0}]}, "malformed_provider_output"),
    ],
)
def test_provider_failures_and_malformed_probabilities_use_neutral_fallback(population, result, status):
    adapter = D4DirectCongestionAdapter(provider=FakeProvider(result=result))

    response = adapter.predict("11110515", ISSUE_TIME, ISSUE_TIME + timedelta(hours=1), population)

    assert response["congestion_source"] == ML_CONGESTION_SOURCE
    assert response["congestion_status"] == status
    assert response["congestion_score"] == NEUTRAL_CONGESTION_SCORE


def test_inference_exception_and_population_loader_failure_use_neutral_fallback(population):
    failed_inference = D4DirectCongestionAdapter(provider=FakeProvider(error=RuntimeError("failed")))
    response = failed_inference.predict("11110515", ISSUE_TIME, ISSUE_TIME + timedelta(hours=1), population)
    assert response["congestion_status"] == "inference_failure"
    assert response["congestion_score"] == NEUTRAL_CONGESTION_SCORE

    def failed_loader(_issue_time):
        raise ValueError("history failure")

    failed_loader_adapter = D4DirectCongestionAdapter(
        provider=FakeProvider(), population_loader=failed_loader
    )
    response = failed_loader_adapter.predict("11110515", ISSUE_TIME, ISSUE_TIME + timedelta(hours=1))
    assert response["congestion_status"] == "population_source_failure"
    assert response["congestion_score"] == NEUTRAL_CONGESTION_SCORE


def test_invalid_arrival_does_not_call_provider(population):
    provider = FakeProvider()
    response = D4DirectCongestionAdapter(provider=provider).predict(
        "11110515", ISSUE_TIME, ISSUE_TIME, population
    )

    assert response["congestion_status"] == "arrival_not_after_issue_time"
    assert response["congestion_score"] == NEUTRAL_CONGESTION_SCORE
    assert provider.calls == 0


def test_invalid_arrival_datetime_does_not_call_provider(population):
    provider = FakeProvider()
    response = D4DirectCongestionAdapter(provider=provider).predict(
        "11110515", ISSUE_TIME, "invalid-datetime", population
    )

    assert response["congestion_status"] == "invalid_arrival_time"
    assert response["congestion_score"] == NEUTRAL_CONGESTION_SCORE
    assert provider.calls == 0


def test_provider_and_population_loader_share_hour_floored_issue_time():
    issue_time = datetime(2026, 9, 17, 15, 19)
    expected_arrival_time = datetime(2026, 9, 17, 15, 40)
    loader_calls = []

    class CapturingProvider(FakeProvider):
        def predict(self, local_resd, model_issue_time, population):
            self.model_issue_time = model_issue_time
            return super().predict(local_resd, model_issue_time, population)

    def loader(model_issue_time):
        loader_calls.append(model_issue_time)
        return pd.DataFrame()

    provider = CapturingProvider()
    result = D4DirectCongestionAdapter(
        provider=provider,
        population_loader=loader,
    ).predict("11110515", issue_time, expected_arrival_time)

    expected_model_issue_time = pd.Timestamp("2026-09-17 15:00:00")
    assert loader_calls == [expected_model_issue_time]
    assert provider.model_issue_time == expected_model_issue_time
    assert result["horizon"] == 1


def test_aware_issue_time_keeps_seoul_clock_time_and_becomes_naive_for_model():
    issue_time = pd.Timestamp("2026-09-17T15:28:00+09:00")
    expected_arrival_time = pd.Timestamp("2026-09-17T15:49:00+09:00")
    loader_calls = []

    class CapturingProvider(FakeProvider):
        def predict(self, local_resd, model_issue_time, population):
            self.model_issue_time = model_issue_time
            return super().predict(local_resd, model_issue_time, population)

    def loader(model_issue_time):
        loader_calls.append(model_issue_time)
        return pd.DataFrame()

    provider = CapturingProvider()
    result = D4DirectCongestionAdapter(
        provider=provider,
        population_loader=loader,
    ).predict("11110515", issue_time, expected_arrival_time)

    expected_model_issue_time = pd.Timestamp("2026-09-17 15:00:00")
    assert loader_calls == [expected_model_issue_time]
    assert provider.model_issue_time == expected_model_issue_time
    assert provider.model_issue_time.tzinfo is None
    assert result["horizon"] == 1
