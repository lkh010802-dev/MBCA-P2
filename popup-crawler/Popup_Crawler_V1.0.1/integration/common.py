from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo


SEOUL_TZ = ZoneInfo("Asia/Seoul")
DISTRICT_RE = re.compile(r"^서울(?:특별시|시)?\s+([가-힣]+구)\b")
ROAD_ADDRESS_RE = re.compile(
    r"^(서울)\s+(?:(?P<district>[가-힣]+구)\s+)?"
    r"(?P<road>[가-힣A-Za-z0-9·._-]+(?:대로|로|길))\s+"
    r"(?P<number>\d+(?:-\d+)?)"
)
# Some sources render numbered-gil road names as "백제고분로 41길 24".
# The space before 41 is display noise: the actual road name is 백제고분로41길.
NUMBERED_GIL_SPACING_RE = re.compile(
    r"(?P<road>[가-힣A-Za-z0-9·._-]+(?:대로|로))\s+"
    r"(?P<branch>\d+)\s*길(?=\s+\d+(?:-\d+)?)"
)


def clean_text(value: object) -> str | None:
    if value is None:
        return None
    text = unicodedata.normalize("NFKC", str(value))
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def normalize_address(value: object) -> str | None:
    text = clean_text(value)
    if not text:
        return None
    text = re.sub(r"^서울특별시\s+", "서울 ", text)
    text = re.sub(r"^서울시\s+", "서울 ", text)
    text = NUMBERED_GIL_SPACING_RE.sub(
        lambda match: f"{match.group('road')}{match.group('branch')}길",
        text,
    )
    return text


def extract_address_base(value: object) -> str | None:
    text = normalize_address(value)
    if not text:
        return None
    match = ROAD_ADDRESS_RE.search(text)
    if not match:
        return None
    district = match.group("district")
    district_text = f" {district}" if district else ""
    return f"서울{district_text} {match.group('road')} {match.group('number')}"


def extract_district(value: object) -> str | None:
    text = normalize_address(value)
    if not text:
        return None
    match = DISTRICT_RE.search(text)
    return match.group(1) if match else None


def derive_status(
    start_date: str,
    end_date: str | None,
    *,
    today: date,
) -> str:
    start = date.fromisoformat(start_date)
    if today < start:
        return "UPCOMING"
    if end_date is None:
        return "ACTIVE"
    end = date.fromisoformat(end_date)
    if today > end:
        return "ENDED"
    return "ACTIVE"


def duration_days(row: dict[str, Any]) -> int | None:
    if not row.get("start_date") or not row.get("end_date"):
        return None
    start = date.fromisoformat(str(row["start_date"]))
    end = date.fromisoformat(str(row["end_date"]))
    return (end - start).days + 1


def _source_snapshot(row: dict[str, Any]) -> dict[str, Any]:
    """Keep structured source evidence without duplicating huge rendered HTML.

    Full raw HTML remains preserved in each source run directory. Integration
    outputs only need a compact audit snapshot.
    """
    excluded = {"raw_card_html", "rendered_html", "html"}
    return {key: value for key, value in row.items() if key not in excluded}


def _base_common(
    row: dict[str, Any],
    *,
    today: date,
) -> dict[str, Any]:
    source = str(row["source"])
    source_id = str(row["source_id"])
    address = normalize_address(row.get("address"))
    # Re-derive from the full address first. This repairs legacy/source values
    # that were truncated by an older address_base regex.
    address_base = extract_address_base(address) or normalize_address(row.get("address_base"))
    district = clean_text(row.get("district")) or extract_district(address)
    start_date = str(row["start_date"])
    end_date = str(row["end_date"]) if row.get("end_date") else None
    crawled_at = clean_text(row.get("crawled_at"))

    return {
        "record_id": f"{source}:{source_id}",
        "source": source,
        "source_id": source_id,
        "name": clean_text(row.get("name")) or clean_text(row.get("name_raw")),
        "name_raw": clean_text(row.get("name_raw")) or clean_text(row.get("name")),
        "brand": None,
        "category": clean_text(row.get("category")),
        "categories": list(row.get("categories") or []),
        "start_date": start_date,
        "end_date": end_date,
        "status": derive_status(start_date, end_date, today=today),
        "venue_name": clean_text(row.get("venue_name")),
        "address": address,
        "address_base": address_base,
        "district": district,
        "latitude": row.get("latitude"),
        "longitude": row.get("longitude"),
        "description": clean_text(row.get("description")),
        "reservation_required": row.get("reservation_required"),
        "reservation_url": clean_text(row.get("reservation_url")),
        "detail_url": clean_text(row.get("detail_url")),
        "official_url": clean_text(row.get("official_url")),
        "source_url": clean_text(row.get("source_url")),
        "image_url": clean_text(row.get("image_url")),
        "tags": list(row.get("tags") or []),
        "first_seen_at": crawled_at,
        "last_seen_at": crawled_at,
        "last_verified_at": crawled_at,
        "source_record_raw": _source_snapshot(row),
    }


def common_from_popga(
    row: dict[str, Any],
    *,
    today: date,
) -> dict[str, Any]:
    item = _base_common(row, today=today)
    item.update({
        "event_type_raw": clean_text(row.get("event_type_raw")),
        "description": clean_text(row.get("description")),
        "venue_name": clean_text(row.get("venue_name")),
        "operation_hours": list(row.get("operation_hours") or row.get("operation_hours_raw") or []),
        "benefits": list(row.get("benefits") or []),
        "website_links": dict(row.get("website_links") or {}),
        "detail_parse_warnings": list(row.get("detail_parse_warnings") or []),
    })
    return item


def common_from_dayforyou(
    row: dict[str, Any],
    *,
    today: date,
) -> dict[str, Any]:
    item = _base_common(row, today=today)
    detail_address = normalize_address(row.get("detail_address"))
    if not item["address"] and detail_address:
        item["address"] = detail_address
    if not item["address_base"]:
        item["address_base"] = extract_address_base(item["address"])
    if not item["district"]:
        item["district"] = extract_district(item["address"])
    item.update({
        "description": clean_text(row.get("detail_summary")),
        "tags": list(row.get("detail_hashtags") or []),
        "event_type_raw": None,
        "operation_hours": list(row.get("operation_hours") or row.get("operation_hours_raw") or []),
        "benefits": [],
        "website_links": {},
        "detail_parse_warnings": list(row.get("detail_parse_warnings") or []),
    })
    return item


def common_from_popply(
    row: dict[str, Any],
    *,
    today: date,
) -> dict[str, Any]:
    item = _base_common(row, today=today)
    item.update({
        "description": clean_text(row.get("description")),
        "venue_name": clean_text(row.get("venue_name")),
        "event_type_raw": clean_text(row.get("event_type_raw")),
        "source_status_raw": clean_text(row.get("source_status")),
        "operation_hours": list(row.get("operation_hours") or row.get("operation_hours_raw") or []),
        "benefits": [],
        "website_links": dict(row.get("website_links") or {}),
        "detail_parse_warnings": list(row.get("detail_parse_warnings") or []),
    })
    return item


def common_records(
    popga_rows: list[dict[str, Any]],
    dayforyou_rows: list[dict[str, Any]],
    popply_rows: list[dict[str, Any]] | None = None,
    *,
    today: date | None = None,
) -> list[dict[str, Any]]:
    if today is None:
        today = datetime.now(SEOUL_TZ).date()
    return [
        *(common_from_popga(row, today=today) for row in popga_rows),
        *(common_from_dayforyou(row, today=today) for row in dayforyou_rows),
        *(common_from_popply(row, today=today) for row in (popply_rows or [])),
    ]
