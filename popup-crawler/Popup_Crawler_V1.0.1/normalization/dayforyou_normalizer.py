from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, asdict
from datetime import date, datetime
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

from crawlers.dayforyou import RawPopup


SEOUL_TZ = ZoneInfo("Asia/Seoul")

DISTRICT_RE = re.compile(r"^서울\s+([가-힣]+구)\b")
ROAD_ADDRESS_RE = re.compile(
    r"^(서울)\s+"
    r"(?:(?P<district>[가-힣]+구)\s+)?"
    r"(?P<road>[가-힣A-Za-z0-9·._-]+(?:대로|로|길))\s+"
    r"(?P<number>\d+(?:-\d+)?)"
)
NUMBERED_GIL_SPACING_RE = re.compile(
    r"(?P<road>[가-힣A-Za-z0-9·._-]+(?:대로|로))\s+"
    r"(?P<branch>\d+)\s*길(?=\s+\d+(?:-\d+)?)"
)

TITLE_ADDRESS_RE = re.compile(
    r"^[?📍]*서울(?:특별시|시)?\s+"
    r"(?:[가-힣]+구\b|[가-힣A-Za-z0-9]+(?:대로|로|길)\s*\d*)"
)

EMOJI_RE = re.compile(
    r"[\U0001F300-\U0001FAFF\u2600-\u27BF]"
)

NON_POPUP_EVENT_KEYWORDS = (
    "연극",
    "뮤지컬",
    "공연",
    "[상설]",
    "상설 전시",
    "기록체험",
)


@dataclass
class NormalizedPopup:
    source: str
    source_id: str

    name_raw: str
    name: str

    address_raw: str
    address: str
    address_base: str | None
    district: str | None

    start_date: str
    end_date: str
    duration_days: int
    status: str

    popup_likelihood: str
    popup_rule_score: int
    popup_rule_reasons: list[str]

    data_quality_score: int
    needs_data_review: bool
    data_review_reasons: list[str]

    llm_review_candidate: bool

    detail_url: str | None
    image_url: str | None
    source_url: str
    crawled_at: str
    normalized_at: str


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def normalize_name(value: str) -> str:
    value = normalize_text(value)
    value = re.sub(r"^[?📍\s]+", "", value)
    value = re.sub(r"^\[\s*\]\s*", "", value)
    return value.strip()


def normalize_address(value: str) -> str:
    value = normalize_text(value)
    value = re.sub(r"\s*복사\s*$", "", value).strip()
    value = re.sub(r"^서울특별시\s+", "서울 ", value)
    value = re.sub(r"^서울시\s+", "서울 ", value)
    value = re.sub(r"^[?📍\s]+", "", value)
    value = NUMBERED_GIL_SPACING_RE.sub(
        lambda match: f"{match.group('road')}{match.group('branch')}길",
        value,
    )
    return value.strip()


def extract_district(address: str) -> str | None:
    match = DISTRICT_RE.search(address)
    return match.group(1) if match else None


def extract_base_address(address: str) -> str | None:
    """
    지저분한 설명이 주소 뒤에 붙어 있어도
    '서울 + 구 + 도로명 + 건물번호'까지만 안전하게 뽑는다.
    """
    match = ROAD_ADDRESS_RE.search(address)
    if not match:
        return None

    district = match.group("district")
    road = match.group("road")
    number = match.group("number")

    if district:
        return f"서울 {district} {road} {number}"
    return f"서울 {road} {number}"


def derive_status(start_date: str, end_date: str, today: date | None = None) -> str:
    if today is None:
        today = datetime.now(SEOUL_TZ).date()

    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)

    if today < start:
        return "UPCOMING"
    if today > end:
        return "ENDED"
    return "OPEN"


def evaluate_data_quality(
    name_raw: str,
    name: str,
    address: str,
    start_date: str,
    end_date: str,
) -> tuple[int, list[str]]:
    score = 100
    reasons: list[str] = []

    if extract_district(address) is None:
        score -= 20
        reasons.append("district_missing")

    if TITLE_ADDRESS_RE.search(normalize_text(name_raw)):
        score -= 40
        reasons.append("title_looks_like_address")

    if "방문 전 운영시간" in name or "예약 여부를 확인" in name:
        score -= 30
        reasons.append("title_operational_notice")

    if len(address) > 85:
        score -= 10
        reasons.append("address_long")

    if EMOJI_RE.search(address):
        score -= 15
        reasons.append("address_has_emoji")

    # 주소 칸 뒤에 홍보문구가 붙은 것으로 의심되는 강한 신호만 사용
    if (
        " 내가 또 " in address
        or "[OPEN]" in address.upper()
        or "콜라보 카페" in address
        or "🫧" in address
        or "🥷" in address
    ):
        score -= 15
        reasons.append("address_possible_promo_text")

    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    if end < start:
        score -= 50
        reasons.append("invalid_date_range")

    return max(0, score), reasons


def evaluate_popup_likelihood(
    name: str,
    address: str,
    start_date: str,
    end_date: str,
) -> tuple[str, int, list[str]]:
    """
    LLM을 호출하기 전에 규칙으로 '팝업일 가능성'을 분류한다.
    이 점수는 진실 판정이 아니라 LLM 검토 대상을 줄이기 위한 후보 점수다.
    """
    score = 1  # 데이포유가 팝업 전문 소스라는 약한 prior
    reasons: list[str] = []

    upper_name = name.upper()
    upper_address = address.upper()

    if any(token in upper_name for token in ("팝업", "POP-UP", "POP UP", "POPUP")):
        score += 3
        reasons.append("title_popup_keyword")

    if "NOW OPEN" in upper_name or " OPEN" in upper_name:
        score += 1
        reasons.append("title_open_keyword")

    if any(token in upper_address for token in ("팝업", "POP-UP", "POPUP")):
        score += 1
        reasons.append("address_popup_keyword")

    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    duration_days = (end - start).days + 1

    if duration_days <= 120:
        score += 1
        reasons.append("short_duration")

    if duration_days > 365:
        score -= 2
        reasons.append("very_long_duration")

    if any(keyword in name for keyword in NON_POPUP_EVENT_KEYWORDS):
        score -= 2
        reasons.append("nonpopup_event_keyword")

    if score >= 4:
        label = "STRONG_POPUP"
    elif score >= 2:
        label = "LIKELY_POPUP"
    else:
        label = "AMBIGUOUS"

    return label, score, reasons


def normalize_popup(raw: RawPopup) -> NormalizedPopup:
    name = normalize_name(raw.name_raw)
    address = normalize_address(raw.address_raw)

    start = date.fromisoformat(raw.start_date)
    end = date.fromisoformat(raw.end_date)
    duration_days = (end - start).days + 1

    data_quality_score, data_review_reasons = evaluate_data_quality(
        name_raw=raw.name_raw,
        name=name,
        address=address,
        start_date=raw.start_date,
        end_date=raw.end_date,
    )

    popup_likelihood, popup_rule_score, popup_rule_reasons = evaluate_popup_likelihood(
        name=name,
        address=address,
        start_date=raw.start_date,
        end_date=raw.end_date,
    )

    needs_data_review = data_quality_score < 90
    llm_review_candidate = (
        needs_data_review
        or popup_likelihood == "AMBIGUOUS"
    )

    return NormalizedPopup(
        source=raw.source,
        source_id=raw.source_id,
        name_raw=raw.name_raw,
        name=name,
        address_raw=raw.address_raw,
        address=address,
        address_base=extract_base_address(address),
        district=extract_district(address),
        start_date=raw.start_date,
        end_date=raw.end_date,
        duration_days=duration_days,
        status=derive_status(raw.start_date, raw.end_date),
        popup_likelihood=popup_likelihood,
        popup_rule_score=popup_rule_score,
        popup_rule_reasons=popup_rule_reasons,
        data_quality_score=data_quality_score,
        needs_data_review=needs_data_review,
        data_review_reasons=data_review_reasons,
        llm_review_candidate=llm_review_candidate,
        detail_url=raw.detail_url,
        image_url=raw.image_url,
        source_url=raw.source_url,
        crawled_at=raw.crawled_at,
        normalized_at=datetime.now(SEOUL_TZ).isoformat(timespec="seconds"),
    )


def normalize_all(items: Iterable[RawPopup]) -> list[NormalizedPopup]:
    return [normalize_popup(item) for item in items]


def save_jsonl(items: Iterable[NormalizedPopup], path: str | Path) -> int:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    count = 0
    with path.open("w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(asdict(item), ensure_ascii=False) + "\n")
            count += 1

    return count


def save_review_jsonl(items: Iterable[NormalizedPopup], path: str | Path) -> int:
    selected = [item for item in items if item.llm_review_candidate]
    return save_jsonl(selected, path)


def build_report(items: list[NormalizedPopup]) -> dict:
    def count_by(field: str) -> dict[str, int]:
        result: dict[str, int] = {}
        for item in items:
            key = str(getattr(item, field))
            result[key] = result.get(key, 0) + 1
        return dict(sorted(result.items()))

    data_review_count = sum(item.needs_data_review for item in items)
    ambiguous_count = sum(item.popup_likelihood == "AMBIGUOUS" for item in items)
    llm_candidate_count = sum(item.llm_review_candidate for item in items)

    reason_counts: dict[str, int] = {}
    popup_reason_counts: dict[str, int] = {}

    for item in items:
        for reason in item.data_review_reasons:
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
        for reason in item.popup_rule_reasons:
            popup_reason_counts[reason] = popup_reason_counts.get(reason, 0) + 1

    return {
        "total_normalized": len(items),
        "status_counts": count_by("status"),
        "district_counts": count_by("district"),
        "popup_likelihood_counts": count_by("popup_likelihood"),
        "data_review_count": data_review_count,
        "data_review_rate": round(data_review_count / len(items), 4) if items else 0,
        "ambiguous_popup_count": ambiguous_count,
        "ambiguous_popup_rate": round(ambiguous_count / len(items), 4) if items else 0,
        "llm_review_candidate_count": llm_candidate_count,
        "llm_review_candidate_rate": round(llm_candidate_count / len(items), 4) if items else 0,
        "fully_rule_processed_count": len(items) - llm_candidate_count,
        "fully_rule_processed_rate": round(
            (len(items) - llm_candidate_count) / len(items), 4
        ) if items else 0,
        "data_review_reason_counts": dict(
            sorted(reason_counts.items(), key=lambda x: (-x[1], x[0]))
        ),
        "popup_rule_reason_counts": dict(
            sorted(popup_reason_counts.items(), key=lambda x: (-x[1], x[0]))
        ),
        "generated_at": datetime.now(SEOUL_TZ).isoformat(timespec="seconds"),
    }


def save_report(report: dict, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
