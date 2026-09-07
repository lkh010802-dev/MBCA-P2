from __future__ import annotations

import csv
import json
import math
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


# Popup source category -> backend activity category.
# Keep this deliberately small/deterministic. The original popup category is
# always preserved in category_detail.
DIRECT_CATEGORY_MAP: dict[str, str] = {
    "F&B": "food",
    "푸드/음료": "food",
    "콘텐츠/문화": "culture",
    "애니/캐릭터": "entertainment",
    "엔터테인먼트": "entertainment",
    "연예/크리에이터": "entertainment",
    "연예인/셀럽": "entertainment",
    "디지털/게임/e스포츠": "entertainment",
    "캐릭터/IP": "entertainment",
    "여행/레저/스포츠": "entertainment",
    "키즈/반려동물": "entertainment",
    "패션": "shopping",
    "라이프스타일": "shopping",
    "뷰티/헬스": "shopping",
    "뷰티": "shopping",
    "문구/아트": "shopping",
    "패밀리/라이프": "shopping",
    "브랜드/캠페인": "shopping",
    "인테리어/리빙": "shopping",
    "디지털/테크": "shopping",
}

_KEYWORD_CATEGORY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("cafe", ("카페", "cafe", "coffee", "커피")),
    ("food", ("f&b", "음식", "푸드", "디저트", "베이커리", "도넛", "타르트", "고로케", "식품", "음료")),
    ("culture", ("전시", "미술", "갤러리", "museum", "exhibition", "아트페어")),
    ("entertainment", ("애니", "캐릭터", "k-pop", "kpop", "게임", "e스포츠", "이스포츠", "체험", "방탈출", "공연", "스포츠")),
    ("shopping", ("패션", "뷰티", "리빙", "문구", "쇼룸", "popup store", "pop-up store", "팝업스토어")),
)


def _blank_to_none(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped if stripped else None
    return value


def _json_cell(value: Any, default: Any) -> Any:
    value = _blank_to_none(value)
    if value is None:
        return default
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _float_or_none(value: Any) -> float | None:
    value = _blank_to_none(value)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _bool_or_none(value: Any) -> bool | None:
    value = _blank_to_none(value)
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n"}:
        return False
    return None


def infer_backend_category(row: dict[str, Any]) -> str:
    """Map crawler popup categories to the backend activity enum.

    The mapper is intentionally deterministic and conservative. If the crawler
    has no category, a few high-signal keywords are checked. Physical popup
    stores default to shopping rather than invoking an LLM.
    """
    detail = str(_blank_to_none(row.get("category")) or "")
    if detail in DIRECT_CATEGORY_MAP:
        return DIRECT_CATEGORY_MAP[detail]

    categories = _json_cell(row.get("categories"), [])
    tags = _json_cell(row.get("tags"), [])
    parts: list[str] = [
        detail,
        str(_blank_to_none(row.get("name")) or ""),
        str(_blank_to_none(row.get("description")) or ""),
    ]
    if isinstance(categories, list):
        parts.extend(str(x) for x in categories)
    if isinstance(tags, list):
        parts.extend(str(x) for x in tags)
    haystack = " ".join(parts).lower()

    for backend_category, keywords in _KEYWORD_CATEGORY_RULES:
        if any(keyword.lower() in haystack for keyword in keywords):
            return backend_category
    return "shopping"


def haversine_distance_m(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> int:
    radius_m = 6_371_000.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = (
        math.sin(dp / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return round(radius_m * c)


def normalize_popup_row(
    row: dict[str, Any],
    *,
    center_latitude: float | None = None,
    center_longitude: float | None = None,
) -> dict[str, Any] | None:
    """Convert one crawler CSV row to the backend's common place dict shape.

    `opening_time` / `closing_time` intentionally use the crawler's
    `today_opening_time` / `today_closing_time` because this file is generated
    daily. Full weekday detail remains available in `operation_schedule`.
    """
    latitude = _float_or_none(row.get("latitude"))
    longitude = _float_or_none(row.get("longitude"))
    name = _blank_to_none(row.get("name"))
    popup_id = _blank_to_none(row.get("popup_id"))
    if latitude is None or longitude is None or not name or not popup_id:
        return None

    distance_m: int | None = None
    if center_latitude is not None and center_longitude is not None:
        distance_m = haversine_distance_m(
            float(center_latitude),
            float(center_longitude),
            latitude,
            longitude,
        )

    original_category = _blank_to_none(row.get("category"))
    operation_schedule = _json_cell(row.get("operation_schedule"), [])
    categories = _json_cell(row.get("categories"), [])
    tags = _json_cell(row.get("tags"), [])

    return {
        # Same common core used by Kakao / Tour normalizers.
        "source": "popup",
        "source_id": str(popup_id),
        "name": str(name),
        "latitude": latitude,
        "longitude": longitude,
        "category": infer_backend_category(row),
        "category_detail": original_category,
        "hub_rank": None,
        "address": _blank_to_none(row.get("address")),
        "distance_m": distance_m,

        # Popup-specific fields that backend may use later.
        "start_date": _blank_to_none(row.get("start_date")),
        "end_date": _blank_to_none(row.get("end_date")),
        "status": _blank_to_none(row.get("status")),
        "venue_name": _blank_to_none(row.get("venue_name")),
        "opening_time": _blank_to_none(row.get("today_opening_time")),
        "closing_time": _blank_to_none(row.get("today_closing_time")),
        "closed": _bool_or_none(row.get("today_closed")),
        "operation_schedule": operation_schedule if isinstance(operation_schedule, list) else [],
        "description": _blank_to_none(row.get("description")),
        "image_url": _blank_to_none(row.get("image_url")),
        "detail_url": _blank_to_none(row.get("detail_url")),
        "official_url": _blank_to_none(row.get("official_url")),
        "reservation_url": _blank_to_none(row.get("reservation_url")),
        "popup_categories": categories if isinstance(categories, list) else [],
        "tags": tags if isinstance(tags, list) else [],
        "confidence": _float_or_none(row.get("confidence")),
    }


def load_popup_places(
    csv_path: str | Path,
    *,
    center_latitude: float | None = None,
    center_longitude: float | None = None,
    radius_m: int | None = None,
    activities: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    """Read a daily popup CSV and return backend-ready popup place dicts.

    If a center coordinate is supplied, distance_m is calculated at runtime.
    `radius_m` is applied only when a center coordinate is also supplied.
    `activities` optionally filters to backend activity categories.
    """
    path = Path(csv_path)
    allowed = {str(x) for x in activities or [] if str(x)}
    places: list[dict[str, Any]] = []

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            place = normalize_popup_row(
                dict(row),
                center_latitude=center_latitude,
                center_longitude=center_longitude,
            )
            if place is None:
                continue
            if allowed and place["category"] not in allowed:
                continue
            if radius_m is not None and place["distance_m"] is not None:
                if place["distance_m"] > radius_m:
                    continue
            places.append(place)

    return places


def find_latest_popup_csv(output_dir: str | Path) -> Path:
    output_dir = Path(output_dir)
    candidates = sorted(
        output_dir.glob("*_popup.csv"),
        key=lambda p: (p.stat().st_mtime, p.name),
        reverse=True,
    )
    if not candidates:
        raise FileNotFoundError(f"popup CSV not found under: {output_dir}")
    return candidates[0]


def _atomic_json_dump(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp_path, path)
    finally:
        tmp_path.unlink(missing_ok=True)


def export_backend_json(
    csv_path: str | Path,
    output_path: str | Path,
    *,
    latest_path: str | Path | None = None,
) -> dict[str, Any]:
    csv_path = Path(csv_path)
    output_path = Path(output_path)
    places = load_popup_places(csv_path)
    _atomic_json_dump(output_path, places)
    if latest_path is not None:
        _atomic_json_dump(Path(latest_path), places)

    opening_count = sum(
        1 for item in places
        if item.get("opening_time") is not None and item.get("closing_time") is not None
    )
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_csv": str(csv_path),
        "output_json": str(output_path),
        "count": len(places),
        "today_hours_count": opening_count,
        "today_hours_missing_count": len(places) - opening_count,
    }
