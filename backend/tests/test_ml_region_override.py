import inspect
from datetime import datetime

import run  # noqa: F401 - configure extension-first imports like production

from region_recommendation_service import (
    _evaluate_local_resd_candidates,
    _load_local_resd_candidate_records,
    _rotate_auto_course_candidates,
    _select_local_resd_api_candidates,
    recommend_regions,
)


class FakeAdapter:
    def __init__(self):
        self.calls = []

    def predict(self, code, issue_time, arrival_time):
        self.calls.append((code, issue_time, arrival_time))
        return {
            "congestion_source": "ml_relative_population",
            "congestion_status": "ok",
            "congestion_score": 4.0,
        }


def candidate(index, food_score=3):
    return {
        "LOCAL_RESD_CODE": str(100 + index),
        "GU_NM": "관악구",
        "ADM_NM": f"행정동{index}",
        "latitude": 37.48 + index * 0.001,
        "longitude": 126.92 + index * 0.001,
        "food_score": food_score,
        "cafe_score": 3,
        "drink_score": 3,
        "entertainment_score": 3,
    }


def test_override_accepts_koala_11_ml_dependencies():
    parameters = inspect.signature(recommend_regions).parameters
    assert "load_local_resd_candidates_fn" in parameters
    assert "d4_congestion_adapter" in parameters


def test_optional_candidate_load_failure_keeps_poi_fallback():
    assert _load_local_resd_candidate_records(lambda: (_ for _ in ()).throw(OSError())) == []


def test_local_candidates_are_bounded_and_tagged():
    selected, supported = _select_local_resd_api_candidates(
        [candidate(index, food_score=index) for index in range(1, 8)],
        start_location={"x": 126.92, "y": 37.48},
        end_location=None,
        activities=["food", "walk"],
        activity_preferences={"food": 5},
    )

    assert supported == ["food"]
    assert len(selected) == 5
    assert all(item["candidate_source"] == "local_resd" for item in selected)
    assert all(item["AREA_NM"] == item["ADM_NM"] for item in selected)


def test_local_candidate_uses_d4_score_and_time_contract():
    adapter = FakeAdapter()
    selected, supported = _select_local_resd_api_candidates(
        [candidate(1, food_score=5)],
        start_location={"x": 126.92, "y": 37.48},
        end_location=None,
        activities=["food"],
        activity_preferences={},
    )

    recommended, extended = _evaluate_local_resd_candidates(
        selected,
        start_location={"x": 126.92, "y": 37.48},
        end_location=None,
        start_datetime=datetime.fromisoformat("2026-09-21T12:00:00+09:00"),
        available_time_minutes=120,
        desired_stay_minutes=60,
        transport_mode="public_transit",
        supported_activities=supported,
        get_travel_fn=lambda *args, **kwargs: {
            "duration_min": 10,
            "mode": kwargs["transport_mode"],
        },
        d4_congestion_adapter=adapter,
    )

    assert not extended
    assert len(recommended) == 1
    assert recommended[0]["available_stay_minutes"] == 100
    assert recommended[0]["congestion_source"] == "ml_relative_population"
    assert recommended[0]["start_to_candidate_transport"]["duration_min"] == 10
    assert adapter.calls[0][0] == "101"


def test_repeated_auto_course_rotates_only_within_quality_pool():
    candidates = [
        {"AREA_NM": f"area-{index}", "final_score": 5.0 - index * 0.1}
        for index in range(6)
    ]
    first = _rotate_auto_course_candidates(
        candidates, rotation_key=("rotation-test",), limit=3
    )
    second = _rotate_auto_course_candidates(
        candidates, rotation_key=("rotation-test",), limit=3
    )

    assert [item["AREA_NM"] for item in first[:3]] != [
        item["AREA_NM"] for item in second[:3]
    ]
    assert all(item["final_score"] >= 4.25 for item in first[:3] + second[:3])
