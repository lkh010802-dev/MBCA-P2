from __future__ import annotations

import json
import os
import re
import shutil
import time
from datetime import date, datetime
from pathlib import Path
from typing import Iterable


NEXT_PUSH_RE = re.compile(
    r"<script(?:\s[^>]*)?>\s*self\.__next_f\.push\((.*?)\)\s*</script>",
    flags=re.IGNORECASE | re.DOTALL,
)
DISTRICT_RE = re.compile(r"^서울(?:특별시|시)?\s+([가-힣]+구)\b")
SEOUL_ADDRESS_RE = re.compile(r"^서울(?:특별시|시)?(?:\s|$)")
DISPLAY_PERIOD_RE = re.compile(
    r"(?P<sy>\d{2})\.(?P<sm>\d{1,2})\.(?P<sd>\d{1,2})"
    r"(?:\([^)]+\))?\s*-\s*"
    r"(?:(?P<ey>\d{2})\.)?(?P<em>\d{1,2})\.(?P<ed>\d{1,2})"
    r"(?:\([^)]+\))?"
)
OPEN_ENDED_DISPLAY_RE = re.compile(
    r"(?P<sy>\d{2})\.(?P<sm>\d{1,2})\.(?P<sd>\d{1,2})"
    r"(?:\([^)]+\))?\s*-\s*추후\s*공지"
)


def _clean(value: object) -> str | None:
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text or None


def _extract_district(address: str | None) -> str | None:
    if not address:
        return None
    match = DISTRICT_RE.search(address)
    return match.group(1) if match else None


def _walk(value: object) -> Iterable[dict]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def extract_embedded_popup_payload(
    html: str,
    *,
    expected_source_id: str | None = None,
) -> dict | None:
    """공개 상세 HTML의 Next.js hydration 데이터에서 popup-info를 찾는다."""
    expected = str(expected_source_id) if expected_source_id is not None else None

    for match in NEXT_PUSH_RE.finditer(html):
        try:
            outer = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if not (
            isinstance(outer, list)
            and len(outer) >= 2
            and isinstance(outer[1], str)
        ):
            continue

        for line in outer[1].splitlines():
            if ":" not in line:
                continue
            _, payload_text = line.split(":", 1)
            if not payload_text.startswith(("[", "{")):
                continue
            try:
                flight_value = json.loads(payload_text)
            except json.JSONDecodeError:
                continue

            for candidate in _walk(flight_value):
                if not (
                    candidate.get("id") is not None
                    and candidate.get("title")
                    and candidate.get("openDate")
                ):
                    continue
                if expected is not None and str(candidate.get("id")) != expected:
                    continue
                return candidate

    return None


def _empty_record(source_id: str, detail_url: str) -> dict:
    return {
        "source": "popga",
        "source_id": str(source_id),
        "detail_url": detail_url,
        "fetch_ok": True,
        "http_status": 200,
        "parse_source": None,
        "event_type_raw": None,
        "title_detail": None,
        "subtitle_detail": None,
        "description_raw": None,
        "ai_summary_raw": None,
        "categories_raw": [],
        "tags_raw": [],
        "period_type_raw": None,
        "start_date_detail": None,
        "end_date_detail": None,
        "operation_hours_raw": [],
        "address_raw": None,
        "road_address": None,
        "address_detail_raw": None,
        "venue_name": None,
        "district": None,
        "latitude": None,
        "longitude": None,
        "website_raw": {},
        "benefits_raw": [],
        "benefits_nonempty": [],
        "additional_information_raw": None,
        "notice_raw": None,
        "age_restriction_type_raw": None,
        "age_restriction_min_age_raw": None,
        "reservation_info_present": False,
        "reservation_required": None,
        "reservation_open_at": None,
        "reservation_close_at": None,
        "reservation_url": None,
        "is_popga_reservation": False,
        "files_raw": [],
        "image_urls": [],
        "main_image_url": None,
        "source_created_at": None,
        "source_updated_at": None,
        "parse_warnings": [],
        "source_payload_raw": None,
        "fetched_from_cache": False,
    }


def _record_from_payload(
    payload: dict,
    *,
    source_id: str,
    detail_url: str,
) -> dict:
    record = _empty_record(source_id, detail_url)
    benefits_raw = [x for x in (payload.get("benefits") or []) if isinstance(x, dict)]
    benefits_nonempty = [
        {"key": _clean(x.get("key")), "value": str(x.get("value") or "").strip()}
        for x in benefits_raw
        if str(x.get("value") or "").strip()
    ]
    files_raw = [x for x in (payload.get("files") or []) if isinstance(x, dict)]
    files_sorted = sorted(files_raw, key=lambda x: int(x.get("sequence") or 0))
    image_urls = [
        str(x["path"]).strip()
        for x in files_sorted
        if str(x.get("path") or "").strip()
    ]
    website = payload.get("website") if isinstance(payload.get("website"), dict) else {}
    reservation_open = payload.get("preReservationStartedAt")
    reservation_close = payload.get("preReservationEndedAt")
    reservation_url = payload.get("preReservationLink")
    is_popga_reservation = bool(payload.get("isPopgaReservation"))
    address_raw = _clean(payload.get("address"))
    road_address = _clean(payload.get("roadAddress"))
    used_address_fallback = False
    if not road_address and address_raw and SEOUL_ADDRESS_RE.search(address_raw):
        road_address = address_raw
        used_address_fallback = True
    address_detail = _clean(payload.get("addressDetail"))

    record.update({
        "parse_source": "nextjs_embedded_data",
        "event_type_raw": _clean(payload.get("type")),
        "title_detail": _clean(payload.get("title")),
        "subtitle_detail": _clean(payload.get("subTitle")),
        "description_raw": str(payload.get("content") or "").strip() or None,
        "ai_summary_raw": str(payload.get("aiSupplement") or "").strip() or None,
        "categories_raw": [
            dict(x) for x in (payload.get("categories") or []) if isinstance(x, dict)
        ],
        "tags_raw": [str(x) for x in (payload.get("tags") or [])],
        "period_type_raw": _clean(payload.get("periodType")),
        "start_date_detail": _clean(payload.get("openDate")),
        "end_date_detail": _clean(payload.get("closeDate")),
        "operation_hours_raw": [
            str(x).strip() for x in (payload.get("operationTime") or []) if str(x).strip()
        ],
        "address_raw": address_raw,
        "road_address": road_address,
        "address_detail_raw": address_detail,
        "venue_name": address_detail,
        "district": _extract_district(road_address),
        "latitude": payload.get("latitude"),
        "longitude": payload.get("longitude"),
        "website_raw": dict(website),
        "benefits_raw": [dict(x) for x in benefits_raw],
        "benefits_nonempty": benefits_nonempty,
        "additional_information_raw": str(
            payload.get("additionalInformation") or ""
        ).strip() or None,
        "notice_raw": str(payload.get("notice") or "").strip() or None,
        "age_restriction_type_raw": _clean(payload.get("ageRestrictionType")),
        "age_restriction_min_age_raw": payload.get("ageRestrictionMinAge"),
        "reservation_info_present": bool(
            reservation_open
            or reservation_close
            or reservation_url
            or is_popga_reservation
        ),
        # 예약 정보가 있다는 사실만으로 방문 예약이 필수라고 추론하지 않는다.
        "reservation_required": None,
        "reservation_open_at": reservation_open,
        "reservation_close_at": reservation_close,
        "reservation_url": reservation_url,
        "is_popga_reservation": is_popga_reservation,
        "files_raw": [dict(x) for x in files_raw],
        "image_urls": image_urls,
        "main_image_url": image_urls[0] if image_urls else None,
        "source_created_at": _clean(payload.get("createdAt")),
        "source_updated_at": _clean(payload.get("lastUpdatedAt")),
        "source_payload_raw": payload,
    })

    if str(payload.get("id")) != str(source_id):
        record["parse_warnings"].append("source_id_mismatch")
    if used_address_fallback:
        record["parse_warnings"].append("road_address_missing_used_address_fallback")
    elif not record["road_address"]:
        record["parse_warnings"].append("road_address_missing")
    if not record["description_raw"]:
        record["parse_warnings"].append("description_missing")
    if not record["end_date_detail"]:
        record["parse_warnings"].append("end_date_missing_source_open_ended")
    elif (
        record["start_date_detail"]
        and record["end_date_detail"] < record["start_date_detail"]
    ):
        record["parse_warnings"].append("invalid_date_range")

    return record


def _parse_display_period(value: str) -> tuple[str | None, str | None]:
    match = DISPLAY_PERIOD_RE.search(value)
    if match:
        try:
            sy = 2000 + int(match.group("sy"))
            ey = 2000 + int(match.group("ey")) if match.group("ey") else sy
            start = date(sy, int(match.group("sm")), int(match.group("sd"))).isoformat()
            end = date(ey, int(match.group("em")), int(match.group("ed"))).isoformat()
            return start, end
        except ValueError:
            return None, None

    match = OPEN_ENDED_DISPLAY_RE.search(value)
    if match:
        try:
            start = date(
                2000 + int(match.group("sy")),
                int(match.group("sm")),
                int(match.group("sd")),
            ).isoformat()
            return start, None
        except ValueError:
            return None, None
    return None, None


def _record_from_dom(
    html: str,
    *,
    source_id: str,
    detail_url: str,
) -> dict:
    from bs4 import BeautifulSoup

    record = _empty_record(source_id, detail_url)
    record["parse_source"] = "dom_fallback"
    record["parse_warnings"].append("embedded_data_missing_dom_fallback")
    soup = BeautifulSoup(html, "html.parser")

    title = soup.find("h1")
    record["title_detail"] = _clean(title.get_text(" ", strip=True)) if title else None

    def heading(text: str):
        return next(
            (
                node for node in soup.find_all(["h2", "h3"])
                if _clean(node.get_text(" ", strip=True)) == text
            ),
            None,
        )

    location_heading = heading("위치")
    if location_heading and location_heading.parent:
        values = [
            _clean(x.get_text(" ", strip=True))
            for x in location_heading.parent.find_all("p")
        ]
        values = [x for x in values if x]
        if values:
            record["road_address"] = values[0]
            record["address_raw"] = values[0]
            record["district"] = _extract_district(values[0])
        if len(values) >= 2:
            record["address_detail_raw"] = values[1]
            record["venue_name"] = values[1]

    schedule_heading = heading("일정")
    if schedule_heading and schedule_heading.parent and schedule_heading.parent.parent:
        values = [
            _clean(x.get_text(" ", strip=True))
            for x in schedule_heading.parent.parent.find_all("p")
        ]
        values = [x for x in values if x]
        if values:
            start, end = _parse_display_period(values[0])
            record["start_date_detail"] = start
            record["end_date_detail"] = end
            record["operation_hours_raw"] = values[1:]
            if start and end and end < start:
                record["parse_warnings"].append("invalid_date_range")

    intro_heading = heading("팝업 소개")
    if intro_heading:
        sibling = intro_heading.find_next_sibling("div")
        if sibling:
            record["description_raw"] = sibling.get_text("\n", strip=True) or None

    channel_heading = heading("채널")
    if channel_heading and channel_heading.parent:
        record["website_raw"] = {
            str(x.get("aria-label") or f"link_{idx}"): str(x.get("href"))
            for idx, x in enumerate(channel_heading.parent.find_all("a"), start=1)
            if x.get("href")
        }

    reservation_heading = heading("사전 예약")
    if reservation_heading and reservation_heading.parent and reservation_heading.parent.parent:
        value = reservation_heading.parent.parent.find("p")
        record["reservation_info_present"] = True
        record["reservation_open_at"] = (
            _clean(value.get_text(" ", strip=True)) if value else None
        )

    if not record["road_address"]:
        record["parse_warnings"].append("road_address_missing")
    if not record["description_raw"]:
        record["parse_warnings"].append("description_missing")
    return record


def parse_detail_html(
    html: str,
    source_id: str,
    detail_url: str,
    *,
    http_status: int | None = 200,
    fetched_from_cache: bool = False,
) -> dict:
    payload = extract_embedded_popup_payload(
        html,
        expected_source_id=str(source_id),
    )
    if payload is not None:
        record = _record_from_payload(
            payload,
            source_id=str(source_id),
            detail_url=detail_url,
        )
    else:
        record = _record_from_dom(
            html,
            source_id=str(source_id),
            detail_url=detail_url,
        )
    record["http_status"] = http_status
    record["fetched_from_cache"] = fetched_from_cache
    return record


def _failed_record(
    source_id: str,
    detail_url: str,
    *,
    http_status: int | None,
    warning: str,
) -> dict:
    record = _empty_record(str(source_id), detail_url)
    record["fetch_ok"] = False
    record["http_status"] = http_status
    record["parse_warnings"] = [warning]
    return record


def fetch_details(
    items: list[dict],
    html_dir: str | Path,
    *,
    delay_seconds: float | None = None,
    timeout: int = 30,
    retries: int = 2,
    cache_dir: str | Path | None = None,
    cache_ids: set[str] | None = None,
    cache_max_age_hours: float = 54.0,
) -> list[dict]:
    """공개 상세 URL을 순차·저빈도로 요청한다.

    이전 실행의 HTML은 목록 핵심 필드가 그대로인 ACTIVE 레코드에 한해 제한적으로
    재사용할 수 있다. copy2로 원본 mtime을 보존해 TTL이 무한 연장되지 않게 한다.
    """
    import requests

    try:
        import truststore
        truststore.inject_into_ssl()
    except ImportError:
        pass

    html_dir = Path(html_dir)
    html_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = Path(cache_dir) if cache_dir else None
    cache_ids = {str(x) for x in (cache_ids or set())}
    if delay_seconds is None:
        delay_seconds = float(os.getenv("POPGA_DETAIL_REQUEST_DELAY", "0.5"))

    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
        "Referer": "https://www.popga.co.kr/list/popup",
    })

    results: list[dict] = []
    total = len(items)
    for index, item in enumerate(items, start=1):
        source_id = str(item["source_id"])
        detail_url = str(item["detail_url"])
        html_path = html_dir / f"{source_id}.html"
        print(f"    [POPGA DETAIL {index}/{total}] {source_id}", end="")

        if html_path.exists() and html_path.stat().st_size > 1000:
            html = html_path.read_text(encoding="utf-8", errors="replace")
            results.append(
                parse_detail_html(
                    html,
                    source_id,
                    detail_url,
                    fetched_from_cache=True,
                )
            )
            print(" - cache/current")
            continue

        previous_html = cache_dir / f"{source_id}.html" if cache_dir else None
        if (
            source_id in cache_ids
            and previous_html is not None
            and previous_html.exists()
            and previous_html.stat().st_size > 1000
        ):
            age_hours = max(0.0, (time.time() - previous_html.stat().st_mtime) / 3600.0)
            if age_hours <= max(0.0, cache_max_age_hours):
                shutil.copy2(previous_html, html_path)
                html = previous_html.read_text(encoding="utf-8", errors="replace")
                results.append(
                    parse_detail_html(
                        html,
                        source_id,
                        detail_url,
                        fetched_from_cache=True,
                    )
                )
                print(f" - cache/previous ({age_hours:.1f}h)")
                continue

        last_warning = "detail_fetch_failed"
        last_status = None
        completed = False
        for attempt in range(1, retries + 1):
            try:
                response = session.get(detail_url, timeout=timeout)
                last_status = response.status_code
                if response.status_code == 200:
                    html = response.content.decode("utf-8", errors="replace")
                    html_path.write_text(html, encoding="utf-8")
                    results.append(
                        parse_detail_html(
                            html,
                            source_id,
                            detail_url,
                            http_status=response.status_code,
                        )
                    )
                    print(" - ok")
                    completed = True
                    break
                last_warning = f"http_{response.status_code}"
            except requests.RequestException as exc:
                last_warning = exc.__class__.__name__
            if attempt < retries:
                time.sleep(float(attempt))

        if not completed:
            results.append(
                _failed_record(
                    source_id,
                    detail_url,
                    http_status=last_status,
                    warning=last_warning,
                )
            )
            print(f" - fail ({last_warning})")

        if index < total:
            time.sleep(max(0.0, delay_seconds))

    return results


def save_jsonl(rows: Iterable[dict], path: str | Path) -> int:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            count += 1
    return count
