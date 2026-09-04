from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup


SITE_URL = "https://popply.co.kr"
LIST_URL = f"{SITE_URL}/popup"
DETAIL_RE = re.compile(r"^/popup/(?P<source_id>\d+)$")
DATE_RANGE_RE = re.compile(
    r"(?P<sy>\d{2})\.(?P<sm>\d{1,2})\.(?P<sd>\d{1,2})\s*-\s*"
    r"(?P<ey>\d{2})\.(?P<em>\d{1,2})\.(?P<ed>\d{1,2})"
)
SEOUL_RE = re.compile(r"^서울(?:특별시|시)?(?:\s|$)")
ROAD_LOCATION_RE = re.compile(
    r"^(?P<address>서울(?:특별시|시)?\s+(?:[가-힣]+구\s+)?"
    r"[가-힣A-Za-z0-9·._-]+(?:대로|로|길)\s+\d+(?:-\d+)?)"
    r"(?:\s+(?P<venue>.+))?$"
)


@dataclass
class RawPopplyPopup:
    source: str
    source_id: str
    name_raw: str
    area_raw: str
    period_raw: str
    start_date: str
    end_date: str
    source_status: str
    category_raw: str | None
    detail_url: str
    image_url: str | None
    source_url: str
    raw_card_text: str
    raw_card_html: str
    parse_warnings: list[str]
    crawled_at: str


def _clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _parse_period(value: str) -> tuple[str, str] | None:
    match = DATE_RANGE_RE.search(value)
    if not match:
        return None
    try:
        start = date(
            2000 + int(match.group("sy")),
            int(match.group("sm")),
            int(match.group("sd")),
        )
        end = date(
            2000 + int(match.group("ey")),
            int(match.group("em")),
            int(match.group("ed")),
        )
    except ValueError:
        return None
    return start.isoformat(), end.isoformat()


def _normalize_detail_url(value: str) -> tuple[str, str] | None:
    absolute = urljoin(SITE_URL, value)
    parsed = urlparse(absolute)
    if parsed.netloc not in {"popply.co.kr", "www.popply.co.kr"}:
        return None
    match = DETAIL_RE.match(parsed.path.rstrip("/"))
    if not match:
        return None
    source_id = match.group("source_id")
    return source_id, f"{SITE_URL}/popup/{source_id}"


def parse_list_html(
    html: str,
    *,
    source_status: str,
    crawled_at: str | None = None,
) -> list[RawPopplyPopup]:
    """공개 목록의 실제 카드 DOM만 파싱한다. 서울은 카드 지역 문자열로 재검증한다."""
    soup = BeautifulSoup(html, "html.parser")
    timestamp = crawled_at or datetime.now().astimezone().isoformat(timespec="seconds")
    results: list[RawPopplyPopup] = []
    seen: set[str] = set()

    anchors = soup.select('a[data-track-component="PopupListCardInfo"][href]')
    if not anchors:
        anchors = soup.select('.popup-info-wrap a[href^="/popup/"]')

    for anchor in anchors:
        normalized = _normalize_detail_url(str(anchor.get("href") or ""))
        if not normalized:
            continue
        source_id, detail_url = normalized
        if source_id in seen:
            continue

        name_node = anchor.select_one(".popup-name")
        date_node = anchor.select_one(".popup-date")
        area_node = anchor.select_one(".popup-location")
        category_node = anchor.select_one(".calendar-store-category")
        name = _clean(name_node.get_text(" ", strip=True) if name_node else "")
        period_raw = _clean(date_node.get_text(" ", strip=True) if date_node else "")
        area = _clean(area_node.get_text(" ", strip=True) if area_node else "")
        category = _clean(
            category_node.get_text(" ", strip=True) if category_node else ""
        ) or None
        period = _parse_period(period_raw)
        if not name or not period or not area:
            continue
        # 사이트의 지역 선택값을 맹신하지 않고 실제 카드 지역을 검사한다.
        if not SEOUL_RE.match(area):
            continue

        warnings: list[str] = []
        start_date, end_date = period
        if end_date < start_date:
            warnings.append("invalid_date_range")

        card = anchor.find_parent("li")
        image_anchor = card.select_one("a.popup-img-wrap") if card else None
        image_url = _clean(
            image_anchor.get("data-image") if image_anchor else ""
        ) or None
        results.append(RawPopplyPopup(
            source="popply",
            source_id=source_id,
            name_raw=name,
            area_raw=area,
            period_raw=period_raw,
            start_date=start_date,
            end_date=end_date,
            source_status=source_status,
            category_raw=category,
            detail_url=detail_url,
            image_url=image_url,
            source_url=LIST_URL,
            raw_card_text=anchor.get_text("\n", strip=True),
            raw_card_html=str(card or anchor),
            parse_warnings=warnings,
            crawled_at=timestamp,
        ))
        seen.add(source_id)
    return results


def _card_signature(page, sample_size: int = 6) -> str:
    locator = page.locator('a[data-track-component="PopupListCardInfo"]')
    count = locator.count()
    hrefs: list[str] = []
    for index in range(min(count, sample_size)):
        hrefs.append(str(locator.nth(index).get_attribute("href") or ""))
    return f"{count}|" + "|".join(hrefs)


def _wait_for_card_signature_change(page, before: str, timeout_ms: int = 15_000) -> bool:
    # The filter label can change before the AJAX-rendered cards do. Poll the
    # actual card signature so we never parse the previous status by mistake.
    waited = 0
    while waited < timeout_ms:
        page.wait_for_timeout(350)
        waited += 350
        if _card_signature(page) != before:
            return True
    return False


def _select_status(page, status: str) -> bool:
    current = _clean(page.locator(".popup-list-filter > p").inner_text())
    if status in current:
        return False
    page.locator(".popup-list-filter > p").click()
    options = page.locator(".popuplist-filter-box-up li")
    for index in range(options.count()):
        option = options.nth(index)
        if _clean(option.inner_text()) == status:
            option.click()
            page.wait_for_function(
                "expected => document.querySelector('.popup-list-filter > p')"
                "?.innerText.includes(expected)",
                arg=status,
                timeout=15_000,
            )
            return True
    raise RuntimeError(f"Popply 상태 필터를 찾지 못했습니다: {status}")


def _scroll_until_stable(page, max_rounds: int = 16) -> int:
    stable_rounds = 0
    previous = -1
    for _ in range(max_rounds):
        count = page.locator('a[data-track-component="PopupListCardInfo"]').count()
        if count == previous:
            stable_rounds += 1
        else:
            stable_rounds = 0
        if stable_rounds >= 3:
            return count
        previous = count
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(850)
    return page.locator('a[data-track-component="PopupListCardInfo"]').count()


def _overlap_ratio(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / min(len(left), len(right))


def crawl_popply_lists(
    run_dir: Path,
    *,
    statuses: Iterable[str] = ("진행 중", "오픈 예정"),
    headless: bool | None = None,
) -> tuple[list[RawPopplyPopup], dict]:
    """로그인 없이 공개 렌더링 페이지를 저빈도로 수집한다.

    Popply는 필터 라벨이 먼저 바뀌고 카드 DOM이 늦게 갱신되는 경우가
    있으므로, 상태 간 카드 signature와 source_id overlap을 검증하고
    의심스러우면 해당 상태를 한 번 새로고침/재시도한다.
    """
    from playwright.sync_api import sync_playwright

    if headless is None:
        headless = os.getenv("POPPLY_HEADLESS", "true").lower() not in {
            "0", "false", "no", "off"
        }
    run_dir.mkdir(parents=True, exist_ok=True)
    discovered: list[RawPopplyPopup] = []
    status_counts: dict[str, int] = {}
    rendered_counts: dict[str, int] = {}
    retry_counts: dict[str, int] = {}
    refresh_changed: dict[str, bool] = {}
    overlap_ratios: dict[str, float] = {}
    suspect_statuses: list[str] = []
    previous_status_ids: set[str] = set()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.goto(LIST_URL, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_selector(
            'a[data-track-component="PopupListCardInfo"]', timeout=30_000
        )

        status_list = list(statuses)
        for status_index, status in enumerate(status_list):
            attempts = 0
            rows: list[RawPopplyPopup] = []
            final_overlap = 0.0
            final_refresh_changed = True
            while attempts < 2:
                if attempts:
                    page.goto(LIST_URL, wait_until="domcontentloaded", timeout=60_000)
                    page.wait_for_selector(
                        'a[data-track-component="PopupListCardInfo"]', timeout=30_000
                    )
                before = _card_signature(page)
                changed_filter = _select_status(page, status)
                refreshed = True
                if changed_filter:
                    refreshed = _wait_for_card_signature_change(page, before)
                page.wait_for_timeout(900)
                rendered = _scroll_until_stable(page)
                html = page.content()
                rows = parse_list_html(html, source_status=status)
                ids = {row.source_id for row in rows}
                final_overlap = _overlap_ratio(previous_status_ids, ids)
                final_refresh_changed = refreshed

                # Different statuses should never be mostly the same IDs.
                # If that happens, the label changed but the cards did not.
                suspicious = (
                    status_index > 0
                    and (not refreshed or final_overlap >= 0.50)
                )
                if suspicious and attempts == 0:
                    attempts += 1
                    continue

                rendered_counts[status] = rendered
                slug = "active" if status == "진행 중" else "upcoming"
                (run_dir / f"rendered_list_{slug}.html").write_text(
                    html, encoding="utf-8"
                )
                break

            retry_counts[status] = attempts
            refresh_changed[status] = final_refresh_changed
            overlap_ratios[status] = round(final_overlap, 4)
            ids = {row.source_id for row in rows}
            if status_index > 0 and (not final_refresh_changed or final_overlap >= 0.50):
                suspect_statuses.append(status)
            status_counts[status] = len(rows)
            discovered.extend(rows)
            previous_status_ids = ids
        browser.close()

    unique: dict[str, RawPopplyPopup] = {}
    duplicate_status_ids: list[str] = []
    for item in discovered:
        if item.source_id in unique:
            duplicate_status_ids.append(item.source_id)
            continue
        unique[item.source_id] = item

    diagnostics = {
        "parser_mode": "rendered_public_dom_verified_status_refresh",
        "requested_statuses": status_list,
        "rendered_card_counts": rendered_counts,
        "seoul_parsed_counts": status_counts,
        "unique_seoul_count": len(unique),
        "duplicate_across_status_count": len(set(duplicate_status_ids)),
        "duplicate_across_status_ids": sorted(set(duplicate_status_ids)),
        "status_retry_counts": retry_counts,
        "status_refresh_changed": refresh_changed,
        "status_overlap_ratios": overlap_ratios,
        "status_refresh_suspect_count": len(suspect_statuses),
        "status_refresh_suspect_statuses": suspect_statuses,
        "authentication_used": False,
        "private_api_used": False,
    }
    return list(unique.values()), diagnostics


def save_jsonl(items: Iterable[RawPopplyPopup | dict], path: Path) -> int:
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as handle:
        for item in items:
            row = asdict(item) if isinstance(item, RawPopplyPopup) else item
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            count += 1
    return count
