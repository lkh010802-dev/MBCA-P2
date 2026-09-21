"""ML-supported administrative-dong candidates and activity scores."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pandas as pd

from activity_score import (
    ACTIVITY_BUSINESS_TYPES,
    aggregate_activity_store_counts,
    convert_counts_to_scores,
    filter_latest_quarter,
    load_store_data,
    merge_activity_store_counts,
)


DEFAULT_SUPPORT_MASTER_FILE = Path(__file__).resolve().parent / "ml" / "d4_direct" / "local_resd_support_master.csv"
DEFAULT_STORE_FILE = Path(__file__).resolve().parent / "data" / "서울시 상권분석서비스(점포-행정동)_2025년.csv"
# 427개 모델 지원 코드 중 좌표가 확정된 행정동만 일반 추천 후보로 사용한다.
EXPECTED_CANDIDATE_COUNT = 421
ACTIVITY_COLUMNS = tuple(ACTIVITY_BUSINESS_TYPES)
OUTPUT_COLUMNS = [
    "LOCAL_RESD_CODE",
    "GU_NM",
    "ADM_NM",
    "latitude",
    "longitude",
    *[
        column
        for activity in ACTIVITY_COLUMNS
        for column in (f"{activity}_count", f"{activity}_score")
    ],
]


class LocalResdCandidateError(RuntimeError):
    """The ML support master or its activity-score join is unusable."""


def _normalize_codes(values: pd.Series) -> pd.Series:
    return values.astype("string").str.strip().str.replace(r"\.0$", "", regex=True)


def load_local_resd_support_candidates(
    support_master_file: str | Path = DEFAULT_SUPPORT_MASTER_FILE,
) -> pd.DataFrame:
    """Load exactly the coordinate-confirmed 421 ML-supported administrative dongs."""
    try:
        support = pd.read_csv(
            support_master_file,
            dtype={"LOCAL_RESD_CODE": "string"},
        )
    except (OSError, ValueError) as exc:
        raise LocalResdCandidateError("ML support master를 읽을 수 없습니다.") from exc

    required = {
        "LOCAL_RESD_CODE", "GU_NM", "ADM_NM", "latitude", "longitude", "status"
    }
    missing = required.difference(support.columns)
    if missing:
        raise LocalResdCandidateError(f"ML support master 필드가 없습니다: {sorted(missing)}")

    support["LOCAL_RESD_CODE"] = _normalize_codes(support["LOCAL_RESD_CODE"])
    support["latitude"] = pd.to_numeric(support["latitude"], errors="coerce")
    support["longitude"] = pd.to_numeric(support["longitude"], errors="coerce")
    # unresolved·ambiguous 좌표는 이동시간 계산이 불가능하므로 후보에서 제외한다.
    candidates = support.loc[
        (support["status"] == "confirmed")
        & support["latitude"].notna()
        & support["longitude"].notna(),
        ["LOCAL_RESD_CODE", "GU_NM", "ADM_NM", "latitude", "longitude"],
    ].copy()

    if candidates["LOCAL_RESD_CODE"].isna().any() or candidates["LOCAL_RESD_CODE"].eq("").any():
        raise LocalResdCandidateError("ML support master 행정동 코드가 올바르지 않습니다.")
    if candidates["LOCAL_RESD_CODE"].duplicated().any():
        raise LocalResdCandidateError("ML support master 행정동 코드가 중복됩니다.")
    if len(candidates) != EXPECTED_CANDIDATE_COUNT:
        raise LocalResdCandidateError(
            f"ML confirmed candidate 수가 올바르지 않습니다: {len(candidates)}"
        )
    return candidates


def _load_local_resd_activity_counts(store_file: str | Path) -> pd.DataFrame:
    # 121 POI와 같은 최신 분기·업종 매핑을 재사용하되, 집계 단위는 행정동이다.
    store = load_store_data(store_file)
    latest = filter_latest_quarter(store)
    counts = merge_activity_store_counts(aggregate_activity_store_counts(latest))
    counts["행정동_코드"] = _normalize_codes(counts["행정동_코드"])
    counts = counts.groupby("행정동_코드", as_index=False)[
        [f"{activity}_count" for activity in ACTIVITY_COLUMNS]
    ].sum()
    return counts


@lru_cache(maxsize=4)
def _load_local_resd_candidates_cached(
    support_master_file: str,
    store_file: str,
) -> pd.DataFrame:
    candidates = load_local_resd_support_candidates(support_master_file)
    counts = _load_local_resd_activity_counts(store_file)
    # 좌표가 확정된 421개와 점포 집계를 일대일로 연결해 누락을 조기에 감지한다.
    merged = candidates.merge(
        counts,
        left_on="LOCAL_RESD_CODE",
        right_on="행정동_코드",
        how="left",
        validate="one_to_one",
    ).drop(columns="행정동_코드")

    count_columns = [f"{activity}_count" for activity in ACTIVITY_COLUMNS]
    if merged[count_columns].isna().all(axis=1).any():
        raise LocalResdCandidateError("ML candidate와 상권 행정동 데이터가 매칭되지 않습니다.")
    merged[count_columns] = merged[count_columns].fillna(0)
    scored = convert_counts_to_scores(merged)
    return scored.loc[:, OUTPUT_COLUMNS]


def load_local_resd_candidates(
    support_master_file: str | Path = DEFAULT_SUPPORT_MASTER_FILE,
    store_file: str | Path = DEFAULT_STORE_FILE,
) -> pd.DataFrame:
    """Return confirmed ML candidates with four activity counts and 1–5 scores."""
    # cache 원본을 호출자가 수정해 이후 추천 요청에 영향을 주지 않도록 깊은 복사본을 반환한다.
    cached = _load_local_resd_candidates_cached(
        str(Path(support_master_file).resolve()),
        str(Path(store_file).resolve()),
    )
    return cached.copy(deep=True)
