from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin

import requests
import time
from bs4 import BeautifulSoup, Tag

try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass


SITE_URL = "https://dayforyou.com"
FALLBACK_SITE_URL = "https://www.dayforyou.com"
BASE_URLS = (
    SITE_URL + "/getScheduleList",
    FALLBACK_SITE_URL + "/getScheduleList",
)
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


@dataclass
class RawPopup:
    source: str
    source_id: str
    name_raw: str
    address_raw: str
    start_date: str
    end_date: str
    detail_url: str | None
    image_url: str | None
    source_url: str
    crawled_at: str


def fetch_page(timeout: int = 20, retries: int = 3) -> tuple[str, str]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/151.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
    }

    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        for url in BASE_URLS:
            try:
                response = requests.get(url, headers=headers, timeout=timeout)
                response.raise_for_status()
                if url != BASE_URLS[0]:
                    print(f"    [NETWORK] DayForYou fallback host 사용: {response.url}")
                html = response.content.decode("utf-8", errors="replace")
                return html, response.url
            except requests.RequestException as exc:
                last_error = exc
        if attempt < retries:
            print(f"    [NETWORK] DayForYou 연결 재시도 {attempt}/{retries - 1}")
            time.sleep(float(attempt))

    raise requests.ConnectionError(
        "DayForYou 목록 페이지에 연결할 수 없습니다. "
        f"시도한 주소: {', '.join(BASE_URLS)}"
    ) from last_error


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def extract_title(card: Tag) -> str | None:
    node = card.select_one(".popupTitle")
    if not node:
        return None
    value = clean_text(node.get_text(" ", strip=True))
    return value or None


def extract_location(card: Tag) -> str | None:
    node = card.select_one(".popupLocation")
    if not node:
        return None

    fragment = BeautifulSoup(str(node), "html.parser")
    for button in fragment.select("button.copy_loc_btn, button"):
        button.decompose()

    value = clean_text(fragment.get_text(" ", strip=True))
    value = re.sub(r"\s*복사\s*$", "", value).strip()
    return value or None


def extract_period(card: Tag) -> tuple[str | None, str | None]:
    node = card.select_one(".popupDate")
    if not node:
        return None, None
    dates = DATE_RE.findall(node.get_text(" ", strip=True))
    if len(dates) < 2:
        return None, None
    return dates[0], dates[1]


def extract_source_id(card: Tag) -> str | None:
    match = re.fullmatch(r"schedule_(\d+)", card.get("id", "") or "")
    if match:
        return match.group(1)

    link = card.select_one('a[href*="scheduleSeq="]')
    if link:
        match = re.search(r"scheduleSeq=(\d+)", link.get("href", "") or "")
        if match:
            return match.group(1)

    return None


def extract_detail_url(card: Tag) -> str | None:
    link = card.select_one('a[href*="scheduleSeq="]')
    if not link or not link.get("href"):
        return None
    return urljoin(SITE_URL, link.get("href"))


def extract_image_url(card: Tag) -> str | None:
    image = card.select_one("img.thumbnail_img")
    if not image or not image.get("src"):
        return None
    return urljoin(SITE_URL, image.get("src"))


def is_strict_seoul(address: str) -> bool:
    """
    '중구' 같은 구 이름만으로 서울이라고 판단하지 않는다.
    실제 주소가 서울/서울특별시/서울시로 시작하는 경우만 통과.
    """
    text = address.lstrip("?📍 ").strip()
    return text.startswith(("서울 ", "서울특별시 ", "서울시 "))


def parse_popups(html: str, source_url: str) -> list[RawPopup]:
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select("li.schedule_box")

    results: list[RawPopup] = []
    excluded_non_seoul = 0
    malformed = 0
    crawled_at = datetime.now().astimezone().isoformat(timespec="seconds")

    for card in cards:
        source_id = extract_source_id(card)
        title = extract_title(card)
        address = extract_location(card)
        start_date, end_date = extract_period(card)

        if not all([source_id, title, address, start_date, end_date]):
            malformed += 1
            continue

        if not is_strict_seoul(address):
            excluded_non_seoul += 1
            continue

        results.append(
            RawPopup(
                source="dayforyou",
                source_id=source_id,
                name_raw=title,
                address_raw=address,
                start_date=start_date,
                end_date=end_date,
                detail_url=extract_detail_url(card),
                image_url=extract_image_url(card),
                source_url=source_url,
                crawled_at=crawled_at,
            )
        )

    print(f"    [RAW] 전체 카드: {len(cards)}건")
    print(f"    [RAW] 서울 카드: {len(results)}건")
    print(f"    [RAW] 비서울 제외: {excluded_non_seoul}건")
    print(f"    [RAW] 필수필드 누락: {malformed}건")

    return results


def save_jsonl(items: Iterable[RawPopup], path: str | Path) -> int:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(asdict(item), ensure_ascii=False) + "\n")
            count += 1
    return count
