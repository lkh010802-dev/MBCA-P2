from __future__ import annotations

import re
from typing import Any

from integration.common import duration_days


EXPLICIT_POPUP_RE = re.compile(r"팝업|POP[\s-]?UP", re.I)
CULTURAL_EVENT_TITLE_RE = re.compile(
    r"콘서트|뮤지컬|연극|공연|페스티벌|축제|박람회|문화주간|"
    r"특별전|개인전|기획전|전시|아트페어|festival|展",
    re.I,
)
# STORE로 잘못 태깅된 복합 행사에서 설명 속 서브 팝업 한 문구가 전체 행사를
# POPUP으로 끌어올리는 것을 막기 위한 강한 title negative. '전시'는 제외한다.
# 실제 Popga에는 '기븐 전시', LG전자 브랜드 전시처럼 제목은 전시여도
# 상세가 명시적으로 Pop Up Shop/전시 팝업인 유효 팝업이 존재한다.
STRONG_CULTURAL_TITLE_RE = re.compile(
    r"콘서트|뮤지컬|연극|공연|페스티벌|축제|박람회|문화주간|아트페어|festival",
    re.I,
)
PROMOTION_TITLE_RE = re.compile(
    r"후기\s*이벤트|할인\s*이벤트|초대\s*이벤트|체험\s*이벤트|"
    r"쿠폰|리워드|멤버십|프로모션",
    re.I,
)
TEMPORARY_FORMAT_RE = re.compile(
    r"콜라보\s*카페|생일\s*카페|컨셉\s*스토어|콘셉트\s*스토어|"
    r"출장점|\b페어\b|마켓|쇼룸|안테나\s*숍",
    re.I,
)
PERMANENT_OPENING_RE = re.compile(
    r"상설|상시\s*운영|오픈\s*이벤트|신규\s*오픈|그랜드\s*오픈|"
    r"플래그십|플래그쉽",
    re.I,
)
PERMANENT_STORE_RE = re.compile(r"굿즈\s*스토어|플래그십\s*스토어|본매장|상설\s*매장", re.I)
IMMERSIVE_PERFORMANCE_RE = re.compile(r"체험극|공포\s*체험|몰입형\s*(?:공연|체험극)", re.I)
GENERIC_EVENT_RE = re.compile(r"이벤트", re.I)
BENEFIT_ONLY_RE = re.compile(
    r"무료|선물|리뷰|만족도|증정|할인|쿠폰|오픈\s*기념",
    re.I,
)
DAYFORYOU_CLASS_ACTIVITY_RE = re.compile(
    r"발레|댄스\s*클래스|원데이\s*클래스|\bclass\b|강좌|워크숍|워크샵",
    re.I,
)
DAYFORYOU_STAGE_EVENT_RE = re.compile(
    r"위클리\s*라이징\s*케이팝\s*스타|라이징\s*K[- ]?POP\s*스타",
    re.I,
)
BROKEN_TITLE_PREFIX_RE = re.compile(r"^\s*(?:장소|주소|기간|일시)\s*[:：]", re.I)
CULTURAL_NON_POPUP_CATEGORIES = {"전시", "페스티벌"}


def _result(
    row: dict[str, Any],
    classification: str,
    reason: str,
    confidence: float,
) -> dict[str, Any]:
    item = dict(row)
    item["classification"] = classification
    item["classification_reasons"] = [reason]
    item["classification_confidence"] = confidence
    return item


def _tag_text(row: dict[str, Any]) -> str:
    return " ".join(str(x or "") for x in (row.get("tags") or []))


def classify_popga(row: dict[str, Any]) -> dict[str, Any]:
    """Popga origin type and visible detail evidence only."""
    name = str(row.get("name") or "")
    description = str(row.get("description") or "")
    event_type = str(row.get("event_type_raw") or "")
    days = duration_days(row)

    # 제목 자체의 팝업 명시는 가장 강한 positive. 반면 설명 본문에 다른
    # 서브 팝업이 언급되는 페스티벌까지 전체 POPUP으로 올리지는 않는다.
    if EXPLICIT_POPUP_RE.search(name):
        return _result(row, "POPUP", "explicit_popup_title_signal", 0.99)

    if event_type in {"FESTIVAL", "EXHIBITION", "EVENT"}:
        return _result(
            row,
            "NON_POPUP",
            f"explicit_non_store_type_{event_type.lower()}",
            0.98,
        )

    if PROMOTION_TITLE_RE.search(name):
        return _result(row, "NON_POPUP", "promotion_title", 0.98)

    # STORE 타입이어도 제목 자체가 페스티벌/공연/박람회라면, 설명에
    # 서브 프로그램으로 '팝업'이 한 번 언급돼도 전체 이벤트를 POPUP으로 보지 않는다.
    if STRONG_CULTURAL_TITLE_RE.search(name):
        if not (
            TEMPORARY_FORMAT_RE.search(name)
            and days is not None
            and days <= 120
        ):
            return _result(row, "NON_POPUP", "cultural_event_title", 0.97)

    # 반대로 '전시/특별전/展'이라는 제목만으로는 STORE 타입을 바로 제외하지 않는다.
    # 상세가 실제 Pop Up Shop/전시 팝업이라고 명시하면 그 근거를 우선한다.
    if EXPLICIT_POPUP_RE.search(description):
        return _result(row, "POPUP", "explicit_popup_description_signal", 0.98)

    if CULTURAL_EVENT_TITLE_RE.search(name):
        if not (
            TEMPORARY_FORMAT_RE.search(name)
            and days is not None
            and days <= 120
        ):
            return _result(row, "NON_POPUP", "cultural_event_title", 0.97)

    if PERMANENT_OPENING_RE.search(f"{name} {description}") and days is None:
        return _result(row, "NON_POPUP", "open_ended_permanent_opening", 0.97)

    if GENERIC_EVENT_RE.search(name) and BENEFIT_ONLY_RE.search(description):
        return _result(row, "NON_POPUP", "benefit_only_event", 0.96)

    if event_type == "STORE" and days is not None and days <= 120:
        return _result(row, "POPUP", "temporary_store_prior", 0.9)

    if (
        event_type == "STORE"
        and TEMPORARY_FORMAT_RE.search(name)
        and days is not None
        and days <= 180
    ):
        return _result(row, "POPUP", "temporary_commerce_format", 0.88)

    return _result(row, "REVIEW", "insufficient_deterministic_evidence", 0.0)


def classify_dayforyou_final(row: dict[str, Any]) -> dict[str, Any]:
    """Reapply hard negatives before canonical inclusion."""
    name = str(row.get("name") or "")
    raw = row.get("source_record_raw") or {}
    detail_text = " ".join([
        str(raw.get("detail_title") or ""),
        str(raw.get("detail_summary") or ""),
    ])

    if BROKEN_TITLE_PREFIX_RE.search(name):
        return _result(row, "INSUFFICIENT_DATA", "broken_operational_title", 0.99)
    if EXPLICIT_POPUP_RE.search(name) or EXPLICIT_POPUP_RE.search(detail_text):
        return _result(row, "POPUP", "explicit_popup_signal", 0.99)
    if PROMOTION_TITLE_RE.search(name):
        return _result(row, "NON_POPUP", "promotion_title", 0.98)
    if CULTURAL_EVENT_TITLE_RE.search(name):
        return _result(row, "NON_POPUP", "cultural_event_title", 0.97)
    if DAYFORYOU_CLASS_ACTIVITY_RE.search(name):
        return _result(row, "NON_POPUP", "class_or_lesson_title", 0.98)
    if DAYFORYOU_STAGE_EVENT_RE.search(name):
        return _result(row, "NON_POPUP", "stage_or_music_event_title", 0.98)

    return _result(row, "POPUP", "dayforyou_final_db_prior", 0.9)


def classify_popply(row: dict[str, Any]) -> dict[str, Any]:
    """Popply also contains permanent stores/exhibitions, so reclassify."""
    name = str(row.get("name") or "")
    description = str(row.get("description") or "")
    category = str(row.get("category") or "")
    tags = _tag_text(row)
    days = duration_days(row)
    combined = f"{name} {description}"

    # Explicit popup wording in title/body is the strongest positive signal.
    if EXPLICIT_POPUP_RE.search(name) or EXPLICIT_POPUP_RE.search(description):
        return _result(row, "POPUP", "explicit_popup_signal", 0.99)

    # Hard negatives must run before SEO/detail-tag evidence.
    if PROMOTION_TITLE_RE.search(name):
        return _result(row, "NON_POPUP", "promotion_title", 0.98)

    if IMMERSIVE_PERFORMANCE_RE.search(description):
        return _result(row, "NON_POPUP", "immersive_performance", 0.98)

    if category in CULTURAL_NON_POPUP_CATEGORIES or CULTURAL_EVENT_TITLE_RE.search(name):
        return _result(row, "NON_POPUP", "cultural_event_title_or_category", 0.97)

    if PERMANENT_OPENING_RE.search(combined):
        return _result(row, "NON_POPUP", "explicit_permanent_format", 0.98)

    if (
        PERMANENT_STORE_RE.search(combined)
        and (days is None or days > 180)
    ):
        return _result(row, "NON_POPUP", "long_running_store_format", 0.97)

    if GENERIC_EVENT_RE.search(name) and BENEFIT_ONLY_RE.search(description):
        return _result(row, "NON_POPUP", "benefit_only_event", 0.96)

    # Missing body + long/open-ended period is not enough evidence either way,
    # even if source tags contain generic 'popup' SEO labels.
    if not description.strip() and (days is None or days > 180):
        return _result(row, "INSUFFICIENT_DATA", "detail_description_missing", 0.99)

    # Detail tags can be useful when the event itself is short/medium-lived.
    if (
        EXPLICIT_POPUP_RE.search(tags)
        and days is not None
        and days <= 180
    ):
        return _result(row, "POPUP", "explicit_popup_tag_signal", 0.96)

    if (
        TEMPORARY_FORMAT_RE.search(combined)
        and days is not None
        and days <= 180
    ):
        return _result(row, "POPUP", "temporary_commerce_format", 0.94)

    return _result(row, "REVIEW", "insufficient_deterministic_evidence", 0.0)


def classify_records(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for row in rows:
        if row.get("source") == "popga":
            result.append(classify_popga(row))
        elif row.get("source") == "dayforyou":
            result.append(classify_dayforyou_final(row))
        elif row.get("source") == "popply":
            result.append(classify_popply(row))
        else:
            result.append(_result(row, "REVIEW", "unsupported_source", 0.0))
    return result
