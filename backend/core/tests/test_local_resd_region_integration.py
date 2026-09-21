import pandas as pd

from models import RecommendRequest
from region_recommendation_service import recommend_regions


def _intent(**overrides):
    intent = {
        "start_location_text": None,
        "target_location_text": None,
        "target_location_scope": None,
        "end_location_text": None,
        "start_time": "12:00",
        "end_time": None,
        "activities": ["cafe"],
        "transport_mode": "auto",
    }
    intent.update(overrides)
    return intent


def _poi(code, score):
    return {
        "AREA_CD": code,
        "AREA_NM": f"POI {code}",
        "CATEGORY": "발달상권",
        "latitude": 37.50 + int(code) / 1000,
        "longitude": 127.00 + int(code) / 1000,
        "food_score": 1,
        "cafe_score": score,
        "drink_score": 1,
        "entertainment_score": 1,
        "walk_score": 1,
        "culture_score": 1,
        "shopping_score": 1,
    }


def _local_candidates(count=25):
    return pd.DataFrame([
        {
            "LOCAL_RESD_CODE": f"L{index:03d}",
            "GU_NM": "테스트구",
            "ADM_NM": f"테스트동{index}",
            "latitude": 37.60 + index / 10_000,
            "longitude": 127.10 + index / 10_000,
            "food_count": index,
            "food_score": 1,
            "cafe_count": index,
            "cafe_score": 5,
            "drink_count": index,
            "drink_score": 1,
            "entertainment_count": index,
            "entertainment_score": 1,
        }
        for index in range(count)
    ])


class FakeD4Adapter:
    def __init__(self):
        self.calls = []

    def predict(self, local_resd, issue_time, expected_arrival_time):
        self.calls.append((local_resd, issue_time, expected_arrival_time))
        if local_resd == "L000":
            return {
                "congestion_source": "ml_relative_population",
                "congestion_status": "provider_unavailable",
                "congestion_score": 3.0,
            }
        return {
            "congestion_source": "ml_relative_population",
            "congestion_status": "ok",
            "congestion_score": 1.0,
            "horizon": 1,
        }


def _recommend(*, local_loader, d4_adapter, activities=("cafe",)):
    pois = [_poi("1", 1), _poi("2", 2), _poi("3", 3)]
    scores = pd.DataFrame(pois)
    return recommend_regions(
        RecommendRequest(
            user_message="카페 추천",
            gps_latitude=37.40,
            gps_longitude=126.90,
        ),
        parse_user_intent_fn=lambda **_: _intent(activities=list(activities)),
        generate_recommendation_message_fn=lambda **_: "추천 설명",
        search_location_fn=lambda _: None,
        get_travel_fn=lambda *_, **__: {"duration_min": 10},
        load_poi_candidates_fn=lambda: [
            {key: value for key, value in poi.items() if not key.endswith("_score")}
            for poi in pois
        ],
        load_poi_activity_scores_fn=lambda: scores,
        get_congestion_data_fn=lambda _: None,
        find_proactive_suggestion_fn=lambda **_: None,
        load_local_resd_candidates_fn=local_loader,
        d4_congestion_adapter=d4_adapter,
    )


def test_local_resd_branch_shortlists_five_and_merges_by_final_score():
    adapter = FakeD4Adapter()
    result = _recommend(
        local_loader=lambda: _local_candidates(),
        d4_adapter=adapter,
    )

    recommendations = result["other_areas"]
    assert len(adapter.calls) == 5
    assert {call[0] for call in adapter.calls}.issubset(
        {f"L{index:03d}" for index in range(20)}
    )
    assert all((call[2] - call[1]).total_seconds() == 600 for call in adapter.calls)
    assert len(recommendations) == 3
    assert all(area["candidate_source"] == "local_resd" for area in recommendations)
    assert recommendations[0]["LOCAL_RESD_CODE"] == "L000"
    assert recommendations[0]["final_score"] >= recommendations[-1]["final_score"]
    assert any(
        area["congestion_status"] == "provider_unavailable"
        for area in recommendations + result["extended_areas"]
    )


def test_unsupported_activity_uses_no_activity_formula_for_local_resd():
    adapter = FakeD4Adapter()
    result = _recommend(
        local_loader=lambda: _local_candidates(5),
        d4_adapter=adapter,
        activities=("walk",),
    )

    local = result["other_areas"][0]
    assert local["activity_match_score"] == 0
    assert round(local["final_score"], 1) == 3.8


def test_poi121_and_local_resd_recommended_candidates_are_merged_by_score():
    result = _recommend(
        local_loader=lambda: _local_candidates(2),
        d4_adapter=FakeD4Adapter(),
    )

    recommendations = result["other_areas"]
    assert [area["candidate_source"] for area in recommendations] == [
        "local_resd", "local_resd", "poi121"
    ]
    assert recommendations[0]["final_score"] >= recommendations[1]["final_score"]
    assert recommendations[1]["final_score"] >= recommendations[2]["final_score"]


def test_local_resd_loader_failure_preserves_poi121_recommendations():
    result = _recommend(
        local_loader=lambda: (_ for _ in ()).throw(OSError("unavailable")),
        d4_adapter=FakeD4Adapter(),
    )

    assert [area["candidate_source"] for area in result["other_areas"]] == [
        "poi121", "poi121", "poi121"
    ]
