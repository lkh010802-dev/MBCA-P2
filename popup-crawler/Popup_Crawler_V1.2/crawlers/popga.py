from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin, urlparse

try:
    from dotenv import load_dotenv
except ImportError:  # 순수 파서 테스트는 python-dotenv 없이도 실행 가능
    def load_dotenv() -> bool:
        return False


SITE_URL = "https://www.popga.co.kr"
SEOUL_AREA_CODE = "1100000000"
LIST_URL = (
    "https://www.popga.co.kr/list/popup?"
    f"areaCodes%5B0%5D={SEOUL_AREA_CODE}&"
    "periodTypes%5B0%5D=IN_PROGRESS&"
    "periodTypes%5B1%5D=READY&"
    "sorts%5B0%5D.order=activated_at"
)

DATE_RANGE_RE = re.compile(
    r"(?P<sy>\d{2})\.\s*(?P<sm>\d{1,2})\.\s*(?P<sd>\d{1,2})"
    r"\s*-\s*"
    r"(?P<ey>\d{2})\.\s*(?P<em>\d{1,2})\.\s*(?P<ed>\d{1,2})"
)
OPEN_ENDED_DATE_RE = re.compile(
    r"(?P<sy>\d{2})\.\s*(?P<sm>\d{1,2})\.\s*(?P<sd>\d{1,2})"
    r"\s*-\s*추후\s*공지"
)
DETAIL_PATH_RE = re.compile(r"/popup/(?P<source_id>\d+)(?:/|$)")
STATUS_VALUES = {"운영중", "오픈 예정", "종료"}

# 서울 필터가 URL에 명시되어 있으므로 이 목록은 행 제거가 아니라
# 사이트 지역 라벨 변화 탐지용으로만 사용한다.
SEOUL_AREA_HINTS = {
    "서울", "성수", "홍대/신촌", "홍대", "신촌", "여의도",
    "강남/서초", "강남", "서초", "용산", "종로", "잠실", "송파",
    "명동", "을지로", "서울 중구", "중구", "마포", "마포구", "광진구",
    "강서", "강서구", "영등포", "영등포구", "성동", "성동구",
    "종로구", "용산구", "송파구", "서대문", "서대문구",
    "동대문", "동대문구", "노원", "노원구", "은평", "은평구",
    "양천", "양천구", "관악", "관악구", "금천", "금천구",
    "구로", "구로구", "도봉", "도봉구", "강북", "강북구",
    "강동", "강동구",
}


@dataclass
class RawPopgaPopup:
    source: str
    source_id: str
    name_raw: str
    area_raw: str
    period_raw: str
    start_date: str
    end_date: str | None
    source_status: str
    category_raw: str | None
    detail_url: str | None
    image_url: str | None
    source_url: str
    raw_card_text: str
    parse_warnings: list[str]
    crawled_at: str


def _truthy_env(name: str, default: str = "true") -> bool:
    return os.getenv(name, default).strip().lower() not in {
        "0", "false", "no", "off"
    }


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _clean_lines(text: str) -> list[str]:
    return [value for value in (_clean(x) for x in text.splitlines()) if value]


def _stable_id(
    name: str,
    area: str,
    start_date: str,
    end_date: str | None,
) -> str:
    """상세 URL을 못 얻은 fallback 행에만 사용하는 임시 ID."""
    raw = f"{name}|{area}|{start_date}|{end_date}".encode("utf-8")
    return "hash_" + hashlib.sha1(raw).hexdigest()[:16]


def _iso_date(match: re.Match[str], prefix: str) -> str:
    yy = int(match.group(prefix + "y"))
    mm = int(match.group(prefix + "m"))
    dd = int(match.group(prefix + "d"))
    return date(2000 + yy, mm, dd).isoformat()


def _parse_period(text: str) -> tuple[str, str | None] | None:
    match = DATE_RANGE_RE.search(text)
    if match:
        try:
            return _iso_date(match, "s"), _iso_date(match, "e")
        except ValueError:
            return None

    match = OPEN_ENDED_DATE_RE.search(text)
    if not match:
        return None
    try:
        return _iso_date(match, "s"), None
    except ValueError:
        return None


def _is_known_seoul_area(area: str) -> bool:
    area = _clean(area)
    return area in SEOUL_AREA_HINTS or area.startswith("서울")


def _normalize_detail_url(value: str | None) -> str | None:
    if not value:
        return None
    absolute = urljoin(SITE_URL, value.strip())
    parsed = urlparse(absolute)
    if parsed.netloc not in {"popga.co.kr", "www.popga.co.kr"}:
        return None
    match = DETAIL_PATH_RE.search(parsed.path)
    if not match:
        return None
    return f"{SITE_URL}/popup/{match.group('source_id')}"


def _source_id_from_url(detail_url: str | None) -> str | None:
    if not detail_url:
        return None
    match = DETAIL_PATH_RE.search(urlparse(detail_url).path)
    return match.group("source_id") if match else None


def _parse_card_lines(
    lines: list[str],
    *,
    detail_url: str | None,
    image_url: str | None,
    source_url: str,
    raw_card_text: str,
) -> RawPopgaPopup | None:
    status_pos = next(
        (idx for idx, value in enumerate(lines) if value in STATUS_VALUES),
        None,
    )
    if status_pos is None:
        return None

    date_pos = None
    date_pair = None
    for idx in range(status_pos + 1, min(len(lines), status_pos + 10)):
        pair = _parse_period(lines[idx])
        if pair:
            date_pos = idx
            date_pair = pair
            break

    if date_pos is None or date_pair is None or date_pos - status_pos < 3:
        return None

    # 현재 공개 카드의 안정적인 순서: 상태 → 이름 → 지역 → 기간 → 카테고리
    name = lines[date_pos - 2]
    area = lines[date_pos - 1]
    period_raw = lines[date_pos]
    category = lines[date_pos + 1] if date_pos + 1 < len(lines) else None
    start_date, end_date = date_pair
    normalized_detail_url = _normalize_detail_url(detail_url)
    source_id = _source_id_from_url(normalized_detail_url)
    warnings: list[str] = []

    if not source_id:
        source_id = _stable_id(name, area, start_date, end_date)
        warnings.append("detail_url_missing_fallback_id")
    if not _is_known_seoul_area(area):
        warnings.append("unrecognized_seoul_area_label")
    if end_date is None:
        warnings.append("end_date_missing_source_open_ended")
    elif date.fromisoformat(end_date) < date.fromisoformat(start_date):
        warnings.append("invalid_date_range")

    return RawPopgaPopup(
        source="popga",
        source_id=source_id,
        name_raw=name,
        area_raw=area,
        period_raw=period_raw,
        start_date=start_date,
        end_date=end_date,
        source_status=lines[status_pos],
        category_raw=category,
        detail_url=normalized_detail_url,
        image_url=image_url,
        source_url=source_url,
        raw_card_text=raw_card_text,
        parse_warnings=warnings,
        crawled_at=datetime.now().astimezone().isoformat(timespec="seconds"),
    )


def parse_card_blocks(
    blocks: Iterable[dict],
    *,
    source_url: str = LIST_URL,
) -> list[RawPopgaPopup]:
    """Playwright가 보존한 상세 링크별 최소 카드 텍스트를 파싱한다."""
    results: list[RawPopgaPopup] = []
    seen: set[str] = set()

    for block in blocks:
        detail_url = _normalize_detail_url(str(block.get("detail_url") or ""))
        image_url = str(block.get("image_url") or "").strip() or None
        raw_card_text = str(block.get("card_text") or "")
        item = _parse_card_lines(
            _clean_lines(raw_card_text),
            detail_url=detail_url,
            image_url=image_url,
            source_url=source_url,
            raw_card_text=raw_card_text,
        )
        if not item or item.source_id in seen:
            continue
        seen.add(item.source_id)
        results.append(item)

    return results


def parse_list_lines(
    lines: list[str],
    *,
    source_url: str = LIST_URL,
) -> list[RawPopgaPopup]:
    """상세 링크 카드 파싱 실패 시 사용하는 전체 body 텍스트 fallback."""
    cleaned = [_clean(x) for x in lines]
    cleaned = [x for x in cleaned if x]
    results: list[RawPopgaPopup] = []
    seen: set[tuple[str, str, str, str | None]] = set()

    for idx, line in enumerate(cleaned):
        if line not in STATUS_VALUES:
            continue
        window = cleaned[idx : idx + 10]
        item = _parse_card_lines(
            window,
            detail_url=None,
            image_url=None,
            source_url=source_url,
            raw_card_text="\n".join(window),
        )
        if not item:
            continue
        key = (item.name_raw, item.area_raw, item.start_date, item.end_date)
        if key in seen:
            continue
        seen.add(key)
        results.append(item)

    return results


def _collect_card_blocks(page) -> list[dict]:
    """실제 클릭형 카드 ID에서 source_id·원문·대표 이미지를 보존."""
    return page.eval_on_selector_all(
        '[id^="btn-popup-details-"]',
        r"""
        (cards) => cards.map((card) => {
          const match = card.id.match(/^btn-popup-details-(\d+)$/);
          const image = card.querySelector('img');
          return {
            element_id: card.id,
            detail_url: match
              ? `https://www.popga.co.kr/popup/${match[1]}`
              : null,
            card_text: (card.innerText || '').trim(),
            image_url: image ? (image.currentSrc || image.src || null) : null,
          };
        })
        """,
    )


def crawl_popga(
    output_dir: str | Path,
) -> tuple[list[RawPopgaPopup], Path, dict]:
    """공개 서울 목록을 저빈도로 렌더링하고 원문 카드 블록을 보존한다."""
    load_dotenv()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "playwright가 설치되어 있지 않습니다. "
            "`pip install -r requirements.txt` 후 "
            "`python -m playwright install chromium`을 실행하세요."
        ) from exc

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    headless = _truthy_env("POPGA_HEADLESS", "true")
    pause = float(os.getenv("POPGA_SCROLL_PAUSE", "0.8"))
    max_scrolls = int(os.getenv("POPGA_MAX_SCROLLS", "30"))
    blocks_by_url: dict[str, dict] = {}
    scroll_rounds = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page(
            viewport={"width": 1440, "height": 1200},
            locale="ko-KR",
            timezone_id="Asia/Seoul",
        )
        page.goto(LIST_URL, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(1800)

        stable_rounds = 0
        previous_count = -1
        previous_height = -1

        for scroll_rounds in range(1, max_scrolls + 1):
            for block in _collect_card_blocks(page):
                detail_url = _normalize_detail_url(block.get("detail_url"))
                if not detail_url:
                    continue
                candidate = {
                    "detail_url": detail_url,
                    "card_text": str(block.get("card_text") or ""),
                    "image_url": block.get("image_url"),
                }
                previous = blocks_by_url.get(detail_url)
                if (
                    not previous
                    or len(candidate["card_text"]) > len(previous["card_text"])
                    or (not previous.get("image_url") and candidate.get("image_url"))
                ):
                    blocks_by_url[detail_url] = candidate

            current_count = len(blocks_by_url)
            current_height = int(page.evaluate("document.body.scrollHeight"))
            if current_count == previous_count and current_height == previous_height:
                stable_rounds += 1
            else:
                stable_rounds = 0

            if stable_rounds >= 3:
                break
            previous_count = current_count
            previous_height = current_height
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(int(pause * 1000))

        # 마지막 스크롤 직후 로딩된 카드도 한 번 더 수집한다.
        for block in _collect_card_blocks(page):
            detail_url = _normalize_detail_url(block.get("detail_url"))
            if detail_url:
                candidate = {
                    "detail_url": detail_url,
                    "card_text": str(block.get("card_text") or ""),
                    "image_url": block.get("image_url"),
                }
                previous = blocks_by_url.get(detail_url)
                if (
                    not previous
                    or len(candidate["card_text"]) > len(previous["card_text"])
                    or (not previous.get("image_url") and candidate.get("image_url"))
                ):
                    blocks_by_url[detail_url] = candidate

        body_text = page.locator("body").inner_text()
        rendered_html = page.content()
        final_url = page.url
        browser.close()

    html_path = output_dir / "popga_rendered.html"
    text_path = output_dir / "popga_body.txt"
    block_path = output_dir / "raw_card_blocks.jsonl"
    html_path.write_text(rendered_html, encoding="utf-8")
    text_path.write_text(body_text, encoding="utf-8")
    save_dict_jsonl(blocks_by_url.values(), block_path)

    blocks = list(blocks_by_url.values())
    items = parse_card_blocks(blocks, source_url=LIST_URL)
    parser_mode = "detail_control_cards"
    if not items:
        items = parse_list_lines(body_text.splitlines(), source_url=LIST_URL)
        parser_mode = "body_text_fallback"

    diagnostics = {
        "requested_url": LIST_URL,
        "final_url": final_url,
        "seoul_area_code": SEOUL_AREA_CODE,
        "parser_mode": parser_mode,
        "scroll_rounds": scroll_rounds,
        "raw_detail_control_count": len(blocks),
        "parsed_count": len(items),
        "fallback_id_count": sum(x.source_id.startswith("hash_") for x in items),
        "missing_detail_url_count": sum(not x.detail_url for x in items),
        "missing_end_date_count": sum(x.end_date is None for x in items),
        "unrecognized_area_labels": sorted({
            x.area_raw for x in items
            if "unrecognized_seoul_area_label" in x.parse_warnings
        }),
    }
    return items, html_path, diagnostics


def save_dict_jsonl(rows: Iterable[dict], path: str | Path) -> int:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            count += 1
    return count


def save_jsonl(rows: Iterable[RawPopgaPopup], path: str | Path) -> int:
    return save_dict_jsonl((asdict(row) for row in rows), path)
