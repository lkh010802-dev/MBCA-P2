from __future__ import annotations

import re
import shutil
import time
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from crawlers.popply import ROAD_LOCATION_RE, SEOUL_RE, _clean, _parse_period


OFFLINE_POPUP_MARKER_RE = re.compile(
    r"(?:\[?\s*OFFLINE\s+POP[\s-]?UP\s*\]?|오프라인\s*(?:팝업|POP[\s-]?UP))",
    re.I,
)
EXPLICIT_DATE_RANGE_RE = re.compile(
    r"(?P<sy>20\d{2}|\d{2})[.\-/](?P<sm>\d{1,2})[.\-/](?P<sd>\d{1,2})"
    r"(?:\([^)]*\))?(?:\s+\d{1,2}:\d{2})?\s*"
    r"(?:~|–|—|-)\s*"
    r"(?P<ey>20\d{2}|\d{2})[.\-/](?P<em>\d{1,2})[.\-/](?P<ed>\d{1,2})",
    re.I,
)


def extract_explicit_offline_period(description: str | None) -> tuple[str, str] | None:
    """설명에 OFFLINE POP-UP이라고 명시된 경우에만 물리 행사 기간을 읽는다."""
    text = str(description or "")
    marker = OFFLINE_POPUP_MARKER_RE.search(text)
    if not marker:
        return None
    # 온라인/오프라인 기간이 함께 있을 때 marker 뒤의 첫 날짜쌍만 사용한다.
    match = EXPLICIT_DATE_RANGE_RE.search(text[marker.end():marker.end() + 700])
    if not match:
        return None

    def year(value: str) -> int:
        number = int(value)
        return number if number >= 2000 else 2000 + number

    try:
        start = date(year(match.group("sy")), int(match.group("sm")), int(match.group("sd")))
        end = date(year(match.group("ey")), int(match.group("em")), int(match.group("ed")))
    except ValueError:
        return None
    if end < start:
        return None
    return start.isoformat(), end.isoformat()


def _empty(source_id: str, detail_url: str) -> dict:
    return {
        "source": "popply",
        "source_id": str(source_id),
        "detail_url": detail_url,
        "fetch_ok": True,
        "http_status": 200,
        "parse_source": "rendered_public_dom",
        "title_detail": None,
        "category_detail": None,
        "period_raw_detail": None,
        "start_date_detail": None,
        "end_date_detail": None,
        "physical_start_date": None,
        "physical_end_date": None,
        "physical_period_source": None,
        "location_raw": None,
        "address": None,
        "address_base": None,
        "venue_name": None,
        "district": None,
        "description_raw": None,
        "notice_raw": None,
        "operation_hours_raw": [],
        "tags_raw": [],
        "website_raw": {},
        "reservation_info_present": False,
        "reservation_required": None,
        "reservation_url": None,
        "amenities_raw": [],
        "image_urls": [],
        "main_image_url": None,
        "copyright_warning_present": False,
        "parse_warnings": [],
    }


def _location_parts(value: str) -> tuple[str | None, str | None, str | None]:
    location = _clean(value)
    match = ROAD_LOCATION_RE.match(location)
    if not match:
        return None, None, None
    address = re.sub(r"^서울(?:특별시|시)\s+", "서울 ", match.group("address"))
    district_match = re.match(r"^서울\s+([가-힣]+구)\b", address)
    return address, _clean(match.group("venue")) or None, (
        district_match.group(1) if district_match else None
    )


def parse_detail_html(
    html: str,
    *,
    source_id: str,
    detail_url: str,
    http_status: int | None = 200,
) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    record = _empty(str(source_id), detail_url)
    record["http_status"] = http_status
    title_wrap = soup.select_one(".popupdetail-title-info")

    if title_wrap:
        title = title_wrap.select_one("h1.tit")
        category = title_wrap.select_one(".calendar-store-category")
        period_node = title_wrap.select_one(".date")
        location_node = title_wrap.select_one(".location")
        record["title_detail"] = _clean(title.get_text(" ", strip=True) if title else "") or None
        record["category_detail"] = _clean(category.get_text(" ", strip=True) if category else "") or None
        record["period_raw_detail"] = _clean(period_node.get_text(" ", strip=True) if period_node else "") or None
        period = _parse_period(record["period_raw_detail"] or "")
        if period:
            record["start_date_detail"], record["end_date_detail"] = period
        if location_node:
            for button in location_node.select("button"):
                button.decompose()
            record["location_raw"] = _clean(location_node.get_text(" ", strip=True)) or None
            address, venue, district = _location_parts(record["location_raw"] or "")
            record["address"] = address
            record["address_base"] = address
            record["venue_name"] = venue
            record["district"] = district
        record["tags_raw"] = [
            _clean(node.get("data-track-value") or node.get_text(" ", strip=True))
            for node in title_wrap.select(".search-box-inner li")
            if _clean(node.get("data-track-value") or node.get_text(" ", strip=True))
        ]

    description = soup.select_one(".popupdetail-info-inner")
    if description:
        record["description_raw"] = description.get_text("\n", strip=True) or None
        offline_period = extract_explicit_offline_period(record["description_raw"])
        if offline_period:
            record["physical_start_date"], record["physical_end_date"] = offline_period
            record["physical_period_source"] = "description_explicit_offline_popup"
            if offline_period != (
                record.get("start_date_detail"), record.get("end_date_detail")
            ):
                record["parse_warnings"].append(
                    "source_header_offline_period_conflict"
                )
    notice = soup.select_one(".popupdetail-caution .session-content")
    if notice:
        record["notice_raw"] = notice.get_text("\n", strip=True) or None

    for item in soup.select(".working-hours__item"):
        value = _clean(item.get_text(" ", strip=True))
        if value:
            record["operation_hours_raw"].append(value)

    for link in soup.select(".popupdetail-link a[href]"):
        href = _clean(link.get("href"))
        label = _clean(link.get_text(" ", strip=True)) or f"link_{len(record['website_raw']) + 1}"
        parsed = urlparse(href)
        if parsed.scheme in {"http", "https"}:
            record["website_raw"][label] = href
            if "예약" in label:
                record["reservation_url"] = href

    active_amenities: list[str] = []
    for item in soup.select(".popupdetail-icon-area li"):
        # 현재 공개 DOM은 비활성 항목에 class="false"를 준다.
        if "false" in (item.get("class") or []):
            continue
        label = _clean(item.get_text(" ", strip=True))
        if label:
            active_amenities.append(label)
    record["amenities_raw"] = active_amenities
    record["reservation_info_present"] = bool(
        "사전예약" in active_amenities or record["reservation_url"]
    )

    image = soup.select_one('meta[property="og:image"], meta[name="og:image"]')
    if image and _clean(image.get("content")):
        record["main_image_url"] = _clean(image.get("content"))
        record["image_urls"] = [record["main_image_url"]]

    record["copyright_warning_present"] = bool(
        soup.select_one(".popupdetail-warning-text")
    )
    if not record["title_detail"]:
        record["parse_warnings"].append("title_missing")
    if not record["address"]:
        record["parse_warnings"].append("road_address_missing")
    elif not SEOUL_RE.match(record["address"]):
        record["parse_warnings"].append("non_seoul_detail_address")
    if not record["description_raw"]:
        record["parse_warnings"].append("description_missing")
    if not record["start_date_detail"] or not record["end_date_detail"]:
        record["parse_warnings"].append("date_missing")
    elif date.fromisoformat(record["end_date_detail"]) < date.fromisoformat(
        record["start_date_detail"]
    ):
        record["parse_warnings"].append("invalid_date_range")
    return record



def core_detail_complete(record: dict) -> bool:
    """Daily master에 쓸 수 있는 Popply 핵심 상세 필드가 모두 채워졌는지 확인한다."""
    if not record.get("fetch_ok"):
        return False
    if not record.get("title_detail"):
        return False
    if not record.get("start_date_detail") or not record.get("end_date_detail"):
        return False
    if not record.get("address"):
        return False
    return True


def _cache_identity_matches(row: dict, record: dict) -> bool:
    if not core_detail_complete(record):
        return False
    if str(record.get("start_date_detail")) != str(row.get("start_date")):
        return False
    if str(record.get("end_date_detail")) != str(row.get("end_date")):
        return False
    current_title = _clean(row.get("name") or row.get("name_raw") or "")
    detail_title = _clean(record.get("title_detail") or "")
    return bool(current_title and detail_title and current_title == detail_title)


def _read_valid_cached_record(
    row: dict,
    *,
    cache_dirs: list[Path],
    cache_max_age_hours: float,
) -> tuple[dict | None, Path | None, float | None]:
    source_id = str(row["source_id"])
    detail_url = str(row["detail_url"])
    for cache_dir in cache_dirs:
        path = cache_dir / f"{source_id}.html"
        if not path.exists() or path.stat().st_size <= 1000:
            continue
        age_hours = max(0.0, (time.time() - path.stat().st_mtime) / 3600.0)
        if age_hours > max(0.0, cache_max_age_hours):
            continue
        html = path.read_text(encoding="utf-8", errors="replace")
        record = parse_detail_html(
            html, source_id=source_id, detail_url=detail_url, http_status=200
        )
        if _cache_identity_matches(row, record):
            return record, path, age_hours
    return None, None, None


def _wait_for_core_detail(page, *, timeout_ms: int = 8_000) -> None:
    page.wait_for_function(
        """() => {
          const root = document.querySelector('.popupdetail-title-info');
          if (!root) return false;
          const title = root.querySelector('h1.tit')?.textContent?.trim();
          const period = root.querySelector('.date')?.textContent?.trim();
          const location = root.querySelector('.location')?.textContent?.trim();
          return Boolean(title && period && location);
        }""",
        timeout=timeout_ms,
    )

def _recover_cache_after_live_error(
    row: dict,
    *,
    cache_dirs: list[Path],
    cache_max_age_hours: float,
    html_path: Path,
    live_attempts: int,
) -> dict | None:
    """네트워크/timeout 자체가 난 경우에도 현재 목록 identity와 일치하는 valid cache로 복구한다."""
    cached, cached_path, age_hours = _read_valid_cached_record(
        row, cache_dirs=cache_dirs, cache_max_age_hours=cache_max_age_hours
    )
    if cached is None or cached_path is None:
        return None
    shutil.copy2(cached_path, html_path)
    cached["fetched_from_cache"] = True
    cached["cache_recovered_after_live_failure"] = True
    cached["live_attempt_count"] = live_attempts
    cached["core_detail_complete"] = True
    cached["cache_age_hours"] = age_hours
    return cached


def fetch_details(
    rows: list[dict],
    html_dir: Path,
    *,
    delay_ms: int = 700,
    settle_ms: int = 250,
    headless: bool = True,
    cache_dirs: list[Path] | None = None,
    cache_ids: set[str] | None = None,
    cache_max_age_hours: float = 54.0,
) -> list[dict]:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright

    html_dir.mkdir(parents=True, exist_ok=True)
    cache_ids = {str(x) for x in (cache_ids or set())}
    cache_dirs = [Path(x) for x in (cache_dirs or []) if Path(x).exists()]
    results: list[dict] = []
    total = len(rows)
    started = time.monotonic()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        context = browser.new_context(viewport={"width": 1440, "height": 1000})

        # 상세 텍스트 파싱에 불필요한 무거운 리소스만 차단한다. JS/XHR/document는 유지한다.
        def route_handler(route):
            if route.request.resource_type in {"image", "media", "font"}:
                route.abort()
            else:
                route.continue_()

        context.route("**/*", route_handler)
        page = context.new_page()

        for index, row in enumerate(rows, start=1):
            source_id = str(row["source_id"])
            detail_url = str(row["detail_url"])
            html_path = html_dir / f"{source_id}.html"
            elapsed = time.monotonic() - started
            print(
                f"    [POPPLY DETAIL {index}/{total} | {index / max(total, 1):.0%} | "
                f"elapsed {elapsed:.0f}s] {source_id}",
                end="",
                flush=True,
            )

            # 변경 없는 ACTIVE는 valid cache를 우선 사용한다. 직전 run의 HTML이
            # hydration 이전 skeleton이면 자동으로 건너뛰고 더 이전 valid cache까지 찾는다.
            if source_id in cache_ids and cache_dirs:
                cached, cached_path, age_hours = _read_valid_cached_record(
                    row, cache_dirs=cache_dirs, cache_max_age_hours=cache_max_age_hours
                )
                if cached is not None and cached_path is not None:
                    shutil.copy2(cached_path, html_path)
                    cached["fetched_from_cache"] = True
                    cached["cache_recovered_after_live_failure"] = False
                    cached["core_detail_complete"] = True
                    results.append(cached)
                    print(f" - cache/valid ({age_hours:.1f}h)", flush=True)
                    continue

            response = None
            record = None
            candidate = None
            live_attempts = 0
            try:
                for attempt in (1, 2):
                    live_attempts = attempt
                    if attempt == 1:
                        response = page.goto(
                            detail_url, wait_until="domcontentloaded", timeout=60_000
                        )
                    else:
                        response = page.reload(wait_until="domcontentloaded", timeout=60_000)
                    page.wait_for_selector(".popupdetail-title-info", timeout=30_000)
                    try:
                        _wait_for_core_detail(page, timeout_ms=8_000 if attempt == 1 else 12_000)
                    except PlaywrightTimeoutError:
                        # wrapper만 먼저 생기는 hydration 지연이 있으므로 content를 파싱해
                        # 실제 핵심 필드가 들어왔는지 아래에서 다시 확인한다.
                        pass
                    if settle_ms:
                        page.wait_for_timeout(max(0, settle_ms if attempt == 1 else max(settle_ms, 500)))
                    html = page.content()
                    candidate = parse_detail_html(
                        html,
                        source_id=source_id,
                        detail_url=detail_url,
                        http_status=response.status if response else None,
                    )
                    if core_detail_complete(candidate):
                        html_path.write_text(html, encoding="utf-8")
                        record = candidate
                        break

                if record is None:
                    # live가 hydration skeleton만 준 경우, 최근 run들에서 현재 목록의
                    # 이름/날짜와 일치하는 valid HTML을 복구용으로 사용한다.
                    cached, cached_path, age_hours = _read_valid_cached_record(
                        row, cache_dirs=cache_dirs, cache_max_age_hours=cache_max_age_hours
                    )
                    if cached is not None and cached_path is not None:
                        shutil.copy2(cached_path, html_path)
                        cached["fetched_from_cache"] = True
                        cached["cache_recovered_after_live_failure"] = True
                        cached["live_attempt_count"] = live_attempts
                        cached["core_detail_complete"] = True
                        record = cached
                        print(f" - live incomplete -> cache recovery ({age_hours:.1f}h)", flush=True)
                    else:
                        record = candidate if candidate is not None else _empty(source_id, detail_url)
                        record["fetch_ok"] = False
                        record["fetched_from_cache"] = False
                        record["cache_recovered_after_live_failure"] = False
                        record["core_detail_complete"] = False
                        record["live_attempt_count"] = live_attempts
                        warnings = list(record.get("parse_warnings") or [])
                        if "core_detail_incomplete_after_retry" not in warnings:
                            warnings.append("core_detail_incomplete_after_retry")
                        record["parse_warnings"] = warnings
                        print(" - core detail incomplete", flush=True)
                else:
                    record["fetched_from_cache"] = False
                    record["cache_recovered_after_live_failure"] = False
                    record["core_detail_complete"] = True
                    record["live_attempt_count"] = live_attempts
                    print(" - ok", flush=True)
            except PlaywrightTimeoutError:
                record = _recover_cache_after_live_error(
                    row,
                    cache_dirs=cache_dirs,
                    cache_max_age_hours=cache_max_age_hours,
                    html_path=html_path,
                    live_attempts=live_attempts,
                )
                if record is not None:
                    print(" - timeout -> cache recovery", flush=True)
                else:
                    record = _empty(source_id, detail_url)
                    record.update({
                        "fetch_ok": False,
                        "http_status": None,
                        "parse_warnings": ["detail_timeout"],
                        "fetched_from_cache": False,
                        "cache_recovered_after_live_failure": False,
                        "core_detail_complete": False,
                        "live_attempt_count": live_attempts,
                    })
                    print(" - timeout", flush=True)
            except Exception as exc:
                record = _recover_cache_after_live_error(
                    row,
                    cache_dirs=cache_dirs,
                    cache_max_age_hours=cache_max_age_hours,
                    html_path=html_path,
                    live_attempts=live_attempts,
                )
                if record is not None:
                    print(f" - {type(exc).__name__} -> cache recovery", flush=True)
                else:
                    record = _empty(source_id, detail_url)
                    record.update({
                        "fetch_ok": False,
                        "http_status": None,
                        "parse_warnings": [f"detail_error:{type(exc).__name__}"],
                        "fetched_from_cache": False,
                        "cache_recovered_after_live_failure": False,
                        "core_detail_complete": False,
                        "live_attempt_count": live_attempts,
                    })
                    print(f" - fail ({type(exc).__name__})", flush=True)
            results.append(record)
            if index < total and delay_ms:
                page.wait_for_timeout(max(0, delay_ms))
        context.close()
        browser.close()
    return results

