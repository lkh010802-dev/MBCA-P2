from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


EXPLICIT_POPUP_RE = re.compile(
    r"팝업|POP[\s-]?UP",
    re.I,
)

HARD_NON_POPUP_RE = re.compile(
    r"사은|상품권|증정\s*기준|증정기준|"
    r"쿠폰|리워드|멤버십|MEMBERSHIP|"
    r"대관|수강신청|대여서비스|공식\s*판매점|"
    r"GIFT\s*CERTIFICATE|COUPON\s*PROMOTION|"
    r"NEW\s*ARRIVALS|프로모션",
    re.I,
)

CULTURAL_NON_POPUP_RE = re.compile(
    r"연극|뮤지컬|특별전|개인전|기획전|상설|"
    r"전시|박람회|야외도서관|기록체험|체험실|"
    r"정원박람회|아쿠아리움|도서관",
    re.I,
)


def _combined_text(row: dict[str, Any]) -> str:
    return " ".join([
        row.get("name") or "",
        row.get("detail_title") or "",
        " ".join(row.get("detail_hashtags") or []),
        row.get("detail_summary") or "",
        row.get("detail_tip") or "",
    ])


def classify_review_item(row: dict[str, Any]) -> tuple[str, list[str]]:
    """
    우선순위:
    1) 명시적 '팝업 / POP-UP' 신호가 있으면 POPUP
    2) 사은/쿠폰/프로모션/판매점 등 명백한 비팝업이면 NON_POPUP
    3) 전시/공연/박람회 등 문화행사면 NON_POPUP
    4) 그 외만 REVIEW

    '전시'가 포함된 브랜드 팝업은 1번 명시적 팝업 신호가 먼저 이긴다.
    """
    text = _combined_text(row)
    reasons: list[str] = []

    if EXPLICIT_POPUP_RE.search(text):
        reasons.append("explicit_popup_signal")
        return "POPUP", reasons

    if HARD_NON_POPUP_RE.search(text):
        reasons.append("hard_non_popup_signal")
        return "NON_POPUP", reasons

    if CULTURAL_NON_POPUP_RE.search(text):
        reasons.append("cultural_non_popup_signal")
        return "NON_POPUP", reasons

    duration = row.get("duration_days")
    if isinstance(duration, int) and duration > 365:
        reasons.append("very_long_duration_without_popup_signal")

    reasons.append("insufficient_evidence")
    return "REVIEW", reasons


def classify_all(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for row in rows:
        label, reasons = classify_review_item(row)
        item = dict(row)
        item["v031_classification"] = label
        item["v031_classification_reasons"] = reasons
        item["include_in_popup_db"] = label == "POPUP"
        result.append(item)
    return result
