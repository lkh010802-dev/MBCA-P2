from __future__ import annotations

import pandas as pd
import pytest

import local_resd_candidates
from activity_score import load_poi_activity_scores


def _support_master(path, count: int = 421) -> None:
    rows = [
        {
            "LOCAL_RESD_CODE": f"{11110000 + index}",
            "GU_NM": "테스트구",
            "ADM_NM": f"테스트동{index}",
            "latitude": 37.5 + index / 100_000,
            "longitude": 127.0 + index / 100_000,
            "status": "confirmed",
            "basis": "test",
            "coordinate_base_date": "2026-01-01",
        }
        for index in range(count)
    ]
    pd.DataFrame(rows).to_csv(path, index=False)


def _store_csv(path, *, include_old_quarter: bool = False) -> None:
    rows = []
    for index in range(421):
        for service_name in ("한식음식점", "커피-음료", "호프-간이주점", "PC방"):
            rows.append(
                {
                    "기준_년분기_코드": 20254,
                    "행정동_코드": 11110000 + index,
                    "행정동_코드_명": f"테스트동{index}",
                    "서비스_업종_코드_명": service_name,
                    "점포_수": index + 1,
                }
            )
    if include_old_quarter:
        rows.append(
            {
                "기준_년분기_코드": 20253,
                "행정동_코드": 11110000,
                "행정동_코드_명": "테스트동0",
                "서비스_업종_코드_명": "한식음식점",
                "점포_수": 99_999,
            }
        )
    pd.DataFrame(rows).to_csv(path, index=False, encoding="cp949")


@pytest.fixture(autouse=True)
def clear_cache():
    local_resd_candidates._load_local_resd_candidates_cached.cache_clear()
    yield
    local_resd_candidates._load_local_resd_candidates_cached.cache_clear()


def test_confirmed_candidates_filter_coordinates_and_keep_string_code(tmp_path):
    master = tmp_path / "support.csv"
    _support_master(master, count=424)
    extra = pd.read_csv(master)
    extra.loc[421, "status"] = "ambiguous"
    extra.loc[422, "status"] = "unresolved"
    extra.loc[423, "latitude"] = None
    extra.to_csv(master, index=False)

    candidates = local_resd_candidates.load_local_resd_support_candidates(master)

    assert len(candidates) == 421
    assert str(candidates["LOCAL_RESD_CODE"].dtype) == "string"
    assert candidates[["latitude", "longitude"]].notna().all().all()
    assert not candidates.duplicated("LOCAL_RESD_CODE").any()


def test_local_resd_uses_latest_quarter_and_scores_all_activities(tmp_path):
    master = tmp_path / "support.csv"
    store = tmp_path / "stores.csv"
    _support_master(master)
    _store_csv(store, include_old_quarter=True)

    candidates = local_resd_candidates.load_local_resd_candidates(master, store)

    assert len(candidates) == 421
    assert set(candidates.columns) == set(local_resd_candidates.OUTPUT_COLUMNS)
    for activity in local_resd_candidates.ACTIVITY_COLUMNS:
        assert candidates[f"{activity}_count"].notna().all()
        assert candidates[f"{activity}_score"].between(1, 5).all()
    assert candidates.loc[0, "food_count"] == 1


def test_real_support_master_matches_all_candidates_to_activity_data():
    candidates = local_resd_candidates.load_local_resd_candidates()

    assert len(candidates) == 421
    assert candidates[[f"{activity}_count" for activity in local_resd_candidates.ACTIVITY_COLUMNS]].notna().all().all()


def test_existing_121_activity_score_contract_is_unchanged():
    scores = load_poi_activity_scores()

    assert len(scores) == 121
    assert {"food_score", "cafe_score", "drink_score", "entertainment_score"}.issubset(scores.columns)
