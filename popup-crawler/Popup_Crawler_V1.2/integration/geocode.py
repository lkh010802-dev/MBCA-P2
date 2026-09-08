from __future__ import annotations

import json
import math
import os
import re
import tempfile
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from statistics import median
from typing import Any, Iterable

import requests
from dotenv import load_dotenv

from integration.common import extract_address_base, extract_district, normalize_address


ADDRESS_URL = "https://dapi.kakao.com/v2/local/search/address.json"
KEYWORD_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
DEFAULT_CACHE_PATH = Path("data/cache/kakao_geocode_cache.json")
SEOUL_LAT_RANGE = (37.40, 37.72)
SEOUL_LON_RANGE = (126.72, 127.28)
_TOKEN_RE = re.compile(r"[가-힣A-Za-z0-9]+")
SEOUL_DISTRICT_STEMS = {
    "종로": "종로구", "중": "중구", "용산": "용산구", "성동": "성동구",
    "광진": "광진구", "동대문": "동대문구", "중랑": "중랑구", "성북": "성북구",
    "강북": "강북구", "도봉": "도봉구", "노원": "노원구", "은평": "은평구",
    "서대문": "서대문구", "마포": "마포구", "양천": "양천구", "강서": "강서구",
    "구로": "구로구", "금천": "금천구", "영등포": "영등포구", "동작": "동작구",
    "관악": "관악구", "서초": "서초구", "강남": "강남구", "송파": "송파구",
    "강동": "강동구",
}
PLACE_HINT_MARKERS = (
    "몰", "백화점", "센터", "플라자", "타워", "스퀘어", "파크", "마켓",
    "스토어", "아이파크", "코엑스", "더현대", "롯데", "현대", "신세계",
)


@dataclass(frozen=True)
class Coordinate:
    latitude: float
    longitude: float
    method: str
    query: str | None = None
    resolved_address: str | None = None
    kakao_place_id: str | None = None


def _float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def valid_coordinate(latitude: Any, longitude: Any) -> bool:
    lat = _float(latitude)
    lon = _float(longitude)
    if lat is None or lon is None:
        return False
    return (
        SEOUL_LAT_RANGE[0] <= lat <= SEOUL_LAT_RANGE[1]
        and SEOUL_LON_RANGE[0] <= lon <= SEOUL_LON_RANGE[1]
    )


def _coord_from_row(row: dict[str, Any]) -> tuple[float, float] | None:
    if not valid_coordinate(row.get("latitude"), row.get("longitude")):
        return None
    return float(row["latitude"]), float(row["longitude"])


def _haversine_m(left: tuple[float, float], right: tuple[float, float]) -> float:
    lat1, lon1 = map(math.radians, left)
    lat2, lon2 = map(math.radians, right)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    value = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    )
    return 6_371_000 * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


def _load_cache(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {
        str(key): value
        for key, value in payload.items()
        if isinstance(value, dict)
    }


def _save_cache(path: Path, cache: dict[str, dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        tmp_path.write_text(
            json.dumps(cache, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(tmp_path, path)
    finally:
        tmp_path.unlink(missing_ok=True)


def _cache_key(kind: str, query: str) -> str:
    return f"{kind}:{query.strip()}"


def _coordinate_from_cache(value: dict[str, Any]) -> Coordinate | None:
    lat = _float(value.get("latitude"))
    lon = _float(value.get("longitude"))
    if not valid_coordinate(lat, lon):
        return None
    return Coordinate(
        latitude=float(lat),
        longitude=float(lon),
        method=str(value.get("method") or "cache"),
        query=str(value.get("query") or "") or None,
        resolved_address=str(value.get("resolved_address") or "") or None,
        kakao_place_id=str(value.get("kakao_place_id") or "") or None,
    )


def _is_seoul_document(document: dict[str, Any]) -> bool:
    address_name = str(document.get("address_name") or "")
    road_address_name = str(document.get("road_address_name") or "")
    if address_name.startswith("서울") or road_address_name.startswith("서울"):
        return True
    for key in ("address", "road_address"):
        nested = document.get(key)
        if isinstance(nested, dict) and str(nested.get("region_1depth_name") or "").startswith("서울"):
            return True
    return False


def _document_district(document: dict[str, Any]) -> str | None:
    for key in ("road_address_name", "address_name"):
        district = extract_district(document.get(key))
        if district:
            return district
    for key in ("road_address", "address"):
        nested = document.get(key)
        if not isinstance(nested, dict):
            continue
        region = str(nested.get("region_2depth_name") or "").strip()
        if region.endswith("구"):
            return region
    return None


def _text_similarity(left: Any, right: Any) -> float:
    a = "".join(_TOKEN_RE.findall(str(left or "").lower()))
    b = "".join(_TOKEN_RE.findall(str(right or "").lower()))
    if not a or not b:
        return 0.0
    if a in b or b in a:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def _token_overlap(query: str, document: dict[str, Any]) -> float:
    q = {token.lower() for token in _TOKEN_RE.findall(query) if len(token) >= 2}
    text = " ".join(
        str(document.get(key) or "")
        for key in ("place_name", "road_address_name", "address_name")
    )
    d = {token.lower() for token in _TOKEN_RE.findall(text) if len(token) >= 2}
    if not q:
        return 0.0
    return len(q & d) / len(q)


def _infer_district_from_freeform(value: Any) -> str | None:
    text = normalize_address(value) or ""
    if not text:
        return None

    exact = extract_district(text)
    if exact:
        return exact

    # Colloquial source strings often say "서울 용산 아이파크몰" instead of
    # "서울 용산구 ...". Accept a district stem only in a location-like position.
    match = re.match(r"^서울\s+([가-힣]+)(?:\s|$)", text)
    if match and match.group(1) in SEOUL_DISTRICT_STEMS:
        return SEOUL_DISTRICT_STEMS[match.group(1)]

    for tag in re.findall(r"#([가-힣A-Za-z0-9]+)", text):
        for stem, district in SEOUL_DISTRICT_STEMS.items():
            if len(stem) >= 2 and tag.startswith(stem):
                return district
    return None


def _place_hint_queries_from_address(value: Any) -> list[str]:
    text = normalize_address(value) or ""
    if not text:
        return []

    queries: list[str] = []

    # Hashtag-style addresses: keep only tags that look like a real venue.
    # Example: #용산아이파크몰 -> "용산아이파크몰 서울".
    for tag in sorted(re.findall(r"#([가-힣A-Za-z0-9]+)", text), key=len, reverse=True):
        if len(tag) >= 4 and any(marker in tag for marker in PLACE_HINT_MARKERS):
            queries.append(f"{tag} 서울")

    body = re.sub(r"^서울(?:특별시|시)?\s+", "", text).strip()
    if "#" not in body:
        # Drop floor / sub-space suffixes that make Kakao keyword search too specific.
        # Example: "용산 아이파크몰 3F 도파민스테이션" -> "용산 아이파크몰".
        simplified = re.split(
            r"\s+\d+\s*(?:F|f|층)\b|\s*[,/|]\s*",
            body,
            maxsplit=1,
        )[0].strip()
        tokens = simplified.split()
        if 1 <= len(tokens) <= 5 and any(marker in simplified for marker in PLACE_HINT_MARKERS):
            queries.append(f"{simplified} 서울")

    unique: list[str] = []
    seen: set[str] = set()
    for query in queries:
        query = re.sub(r"\s+", " ", query).strip()
        if query and query not in seen:
            seen.add(query)
            unique.append(query)
    return unique


def _repair_location_fields(row: dict[str, Any]) -> None:
    address = normalize_address(row.get("address"))
    if address:
        row["address"] = address

    # Always re-derive from the full address when possible. Old crawler versions
    # could truncate numbered-gil names such as 백제고분로41길.
    derived_base = extract_address_base(address)
    if derived_base:
        row["address_base"] = derived_base
    elif row.get("address_base"):
        row["address_base"] = normalize_address(row.get("address_base"))

    if not str(row.get("district") or "").strip():
        row["district"] = _infer_district_from_freeform(address)


class KakaoGeocoder:
    def __init__(
        self,
        api_key: str,
        *,
        session: requests.Session | None = None,
        timeout: float = 6.0,
    ) -> None:
        self.api_key = api_key.strip()
        self.session = session or requests.Session()
        self.timeout = timeout
        self.api_calls = 0
        self.errors: list[str] = []

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"KakaoAK {self.api_key}"}

    def _get_documents(self, url: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        self.api_calls += 1
        try:
            response = self.session.get(
                url,
                headers=self.headers,
                params=params,
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            self.errors.append(f"{url}: {type(exc).__name__}: {exc}")
            return []
        documents = payload.get("documents") if isinstance(payload, dict) else None
        if not isinstance(documents, list):
            return []
        return [item for item in documents if isinstance(item, dict)]

    def address(self, query: str) -> Coordinate | None:
        documents = self._get_documents(ADDRESS_URL, {"query": query})
        for document in documents:
            lat = _float(document.get("y"))
            lon = _float(document.get("x"))
            if not _is_seoul_document(document) or not valid_coordinate(lat, lon):
                continue
            resolved_address = (
                str(document.get("road_address", {}).get("address_name") or "")
                if isinstance(document.get("road_address"), dict)
                else ""
            ) or str(document.get("address_name") or "")
            return Coordinate(
                latitude=float(lat),
                longitude=float(lon),
                method="kakao_address",
                query=query,
                resolved_address=resolved_address or None,
            )
        return None

    def keyword(self, query: str, *, row: dict[str, Any]) -> Coordinate | None:
        documents = self._get_documents(KEYWORD_URL, {"query": query, "size": 5})
        expected_district = str(row.get("district") or "").strip() or None
        expected_base = str(row.get("address_base") or "").strip() or None
        venue_name = str(row.get("venue_name") or "").strip() or None
        popup_name = str(row.get("name") or "").strip() or None

        ranked: list[tuple[float, dict[str, Any]]] = []
        for index, document in enumerate(documents):
            lat = _float(document.get("y"))
            lon = _float(document.get("x"))
            if not _is_seoul_document(document) or not valid_coordinate(lat, lon):
                continue

            district = _document_district(document)
            if expected_district and district and district != expected_district:
                continue

            road_name = str(document.get("road_address_name") or "")
            candidate_base = extract_address_base(road_name)
            exact_base = bool(expected_base and candidate_base == expected_base)
            venue_similarity = _text_similarity(venue_name, document.get("place_name")) if venue_name else 0.0
            name_similarity = _text_similarity(popup_name, document.get("place_name")) if popup_name else 0.0
            overlap = _token_overlap(query, document)
            query_place_similarity = _text_similarity(query, document.get("place_name"))

            # Strong acceptance paths only. Temporary popup names are often not
            # registered Kakao places, so the address/venue evidence has priority.
            accepted = (
                exact_base
                or venue_similarity >= 0.55
                or (not expected_base and overlap >= 0.45)
                or (not expected_base and query_place_similarity >= 0.55)
                or (not expected_base and name_similarity >= 0.65)
            )
            if not accepted:
                continue

            score = (
                (3.0 if exact_base else 0.0)
                + 1.8 * venue_similarity
                + 1.2 * name_similarity
                + 1.4 * query_place_similarity
                + overlap
                + max(0.0, 0.1 - index * 0.02)
            )
            ranked.append((score, document))

        if not ranked:
            return None
        ranked.sort(key=lambda item: item[0], reverse=True)
        document = ranked[0][1]
        lat = float(document["y"])
        lon = float(document["x"])
        resolved_address = str(document.get("road_address_name") or document.get("address_name") or "")
        return Coordinate(
            latitude=lat,
            longitude=lon,
            method="kakao_keyword",
            query=query,
            resolved_address=resolved_address or None,
            kakao_place_id=str(document.get("id") or "") or None,
        )


def _known_address_coordinates(
    rows: Iterable[dict[str, Any]],
    *,
    max_spread_m: float = 200.0,
) -> dict[str, Coordinate]:
    grouped: dict[str, list[tuple[float, float]]] = {}
    for row in rows:
        base = str(row.get("address_base") or "").strip()
        coord = _coord_from_row(row)
        if base and coord:
            grouped.setdefault(base, []).append(coord)

    result: dict[str, Coordinate] = {}
    for base, coords in grouped.items():
        center = (median([lat for lat, _ in coords]), median([lon for _, lon in coords]))
        spread = max((_haversine_m(center, coord) for coord in coords), default=0.0)
        if spread <= max_spread_m:
            result[base] = Coordinate(
                latitude=center[0],
                longitude=center[1],
                method="same_address_reuse",
                query=base,
                resolved_address=base,
            )
    return result


def _keyword_queries(row: dict[str, Any]) -> list[str]:
    district = str(row.get("district") or "").strip()
    venue = str(row.get("venue_name") or "").strip()
    name = str(row.get("name") or "").strip()
    address = str(row.get("address") or "").strip()
    base = str(row.get("address_base") or "").strip()

    queries: list[str] = []
    if venue:
        queries.append(" ".join(part for part in (venue, district or "서울") if part))

    # Prefer concise place hints before the noisy raw source address.
    queries.extend(_place_hint_queries_from_address(address))

    # If address search returned nothing, Kakao keyword search can still resolve
    # a road address by matching a registered place at the same address.
    if base:
        queries.append(base)
    elif address:
        queries.append(address)

    if name:
        queries.append(" ".join(part for part in (name, district or "서울") if part))

    unique: list[str] = []
    seen: set[str] = set()
    for query in queries:
        query = re.sub(r"\s+", " ", query).strip()
        if query and query not in seen:
            seen.add(query)
            unique.append(query)
    return unique


def _apply_coordinate(row: dict[str, Any], coordinate: Coordinate) -> None:
    row["latitude"] = coordinate.latitude
    row["longitude"] = coordinate.longitude
    row["coordinate_source"] = coordinate.method
    row["coordinate_query"] = coordinate.query
    row["coordinate_resolved_address"] = coordinate.resolved_address
    row["coordinate_kakao_place_id"] = coordinate.kakao_place_id


def enrich_missing_coordinates(
    rows: list[dict[str, Any]],
    *,
    api_key: str | None = None,
    cache_path: str | Path = DEFAULT_CACHE_PATH,
    reference_rows: list[dict[str, Any]] | None = None,
    session: requests.Session | None = None,
    enabled: bool = True,
    use_api: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    """Fill missing Seoul coordinates without overwriting valid source coordinates.

    Order:
      1) keep valid source coordinates
      2) persistent geocode cache
      3) conservative same-address coordinate reuse
      4) Kakao address search using address_base
      5) Kakao keyword fallback using venue/address/name

    The API layer is optional: when no Kakao key exists the function still performs
    cache/same-address reuse and reports the remainder as unresolved.
    """
    copied = [dict(row) for row in rows]
    for row in copied:
        _repair_location_fields(row)
    missing_before = sum(not valid_coordinate(row.get("latitude"), row.get("longitude")) for row in copied)
    if not enabled:
        unresolved = [row for row in copied if not valid_coordinate(row.get("latitude"), row.get("longitude"))]
        return copied, {
            "enabled": False,
            "api_key_present": False,
            "api_enabled": False,
            "total_rows": len(copied),
            "missing_before": missing_before,
            "missing_after": len(unresolved),
            "filled_total": 0,
            "cache_hits": 0,
            "same_address_reused": 0,
            "kakao_address_filled": 0,
            "kakao_keyword_filled": 0,
            "api_calls": 0,
            "api_errors": [],
        }, unresolved

    load_dotenv()
    if use_api:
        api_key = (api_key or os.getenv("KAKAO_REST_API_KEY") or os.getenv("KAKAO_API_KEY") or "").strip()
    else:
        api_key = ""
    cache_path = Path(cache_path)
    cache = _load_cache(cache_path)
    cache_dirty = False

    all_reference = [*copied, *(reference_rows or [])]
    known_by_base = _known_address_coordinates(all_reference)
    geocoder = KakaoGeocoder(api_key, session=session) if api_key else None

    counts = {
        "cache_hits": 0,
        "same_address_reused": 0,
        "kakao_address_filled": 0,
        "kakao_keyword_filled": 0,
    }
    address_attempts: dict[str, Coordinate | None] = {}
    keyword_attempts: dict[str, Coordinate | None] = {}

    for row in copied:
        if valid_coordinate(row.get("latitude"), row.get("longitude")):
            row.setdefault("coordinate_source", "source")
            continue

        base = str(row.get("address_base") or "").strip() or None
        coordinate: Coordinate | None = None

        if base:
            cached = _coordinate_from_cache(cache.get(_cache_key("address", base), {}))
            if cached:
                coordinate = Coordinate(
                    latitude=cached.latitude,
                    longitude=cached.longitude,
                    method="kakao_address_cache",
                    query=base,
                    resolved_address=cached.resolved_address,
                    kakao_place_id=cached.kakao_place_id,
                )
                counts["cache_hits"] += 1

        if coordinate is None and base and base in known_by_base:
            coordinate = known_by_base[base]
            counts["same_address_reused"] += 1

        if coordinate is None and base and geocoder:
            if base not in address_attempts:
                address_attempts[base] = geocoder.address(base)
            coordinate = address_attempts[base]
            if coordinate:
                counts["kakao_address_filled"] += 1
                cache[_cache_key("address", base)] = {
                    "latitude": coordinate.latitude,
                    "longitude": coordinate.longitude,
                    "method": coordinate.method,
                    "query": coordinate.query,
                    "resolved_address": coordinate.resolved_address,
                    "kakao_place_id": coordinate.kakao_place_id,
                }
                cache_dirty = True
                known_by_base[base] = coordinate

        if coordinate is None and geocoder:
            for query in _keyword_queries(row):
                key = _cache_key("keyword", query)
                cached = _coordinate_from_cache(cache.get(key, {}))
                if cached:
                    coordinate = Coordinate(
                        latitude=cached.latitude,
                        longitude=cached.longitude,
                        method="kakao_keyword_cache",
                        query=query,
                        resolved_address=cached.resolved_address,
                        kakao_place_id=cached.kakao_place_id,
                    )
                    counts["cache_hits"] += 1
                    break

                if query not in keyword_attempts:
                    keyword_attempts[query] = geocoder.keyword(query, row=row)
                found = keyword_attempts[query]
                if found:
                    coordinate = found
                    counts["kakao_keyword_filled"] += 1
                    cache[key] = {
                        "latitude": found.latitude,
                        "longitude": found.longitude,
                        "method": found.method,
                        "query": found.query,
                        "resolved_address": found.resolved_address,
                        "kakao_place_id": found.kakao_place_id,
                    }
                    cache_dirty = True
                    break

        if coordinate:
            _apply_coordinate(row, coordinate)
            if base:
                known_by_base.setdefault(base, coordinate)

    if cache_dirty:
        _save_cache(cache_path, cache)

    unresolved: list[dict[str, Any]] = []
    unresolved_reason_counts: dict[str, int] = {}
    for row in copied:
        if valid_coordinate(row.get("latitude"), row.get("longitude")):
            continue
        debug_row = dict(row)
        base = str(row.get("address_base") or "").strip() or None
        keyword_queries = _keyword_queries(row)
        if base:
            reason = "address_and_keyword_no_match"
        elif keyword_queries:
            reason = "keyword_no_match"
        else:
            reason = "no_geocodable_location_hint"
        debug_row["geocode_address_query"] = base
        debug_row["geocode_keyword_queries"] = keyword_queries
        debug_row["geocode_unresolved_reason"] = reason
        unresolved.append(debug_row)
        unresolved_reason_counts[reason] = unresolved_reason_counts.get(reason, 0) + 1

    missing_after = len(unresolved)
    report = {
        "enabled": True,
        "api_key_present": bool(api_key),
        "api_enabled": bool(use_api),
        "cache_path": str(cache_path),
        "total_rows": len(copied),
        "missing_before": missing_before,
        "missing_after": missing_after,
        "filled_total": missing_before - missing_after,
        **counts,
        "api_calls": geocoder.api_calls if geocoder else 0,
        "api_errors": list(geocoder.errors) if geocoder else [],
        "unresolved_reason_counts": unresolved_reason_counts,
    }
    return copied, report, unresolved
