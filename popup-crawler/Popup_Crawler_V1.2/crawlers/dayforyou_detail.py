from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass


SITE_URL = "https://dayforyou.com"
FALLBACK_SITE_URL = "https://www.dayforyou.com"
DETAIL_URL = SITE_URL + "/getDetail?scheduleSeq={source_id}"
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


@dataclass
class DetailRecord:
    source: str
    source_id: str
    detail_url: str
    title_detail: str | None
    start_date_detail: str | None
    end_date_detail: str | None
    address_detail: str | None
    hashtags: list[str]
    tip_text: str | None
    summary_text: str | None
    official_url: str | None
    operation_hours_raw: list[str]
    fetch_ok: bool
    http_status: int | None
    parse_warnings: list[str]
    fetched_from_cache: bool


def _clean_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _text_of(soup: BeautifulSoup, selector: str) -> str | None:
    node = soup.select_one(selector)
    if not node:
        return None
    value = _clean_text(node.get_text(" ", strip=True))
    return value or None


def _extract_title(soup: BeautifulSoup) -> str | None:
    value = _text_of(soup, "#schedule_title")
    if value:
        return value

    if soup.title:
        value = _clean_text(soup.title.get_text(" ", strip=True))
        value = re.sub(r"\s*-\s*데이포유\s*$", "", value).strip()
        return value or None

    return None


def _extract_period(soup: BeautifulSoup) -> tuple[str | None, str | None]:
    value = _text_of(soup, ".schedule_date")
    if not value:
        return None, None

    dates = DATE_RE.findall(value)
    if len(dates) >= 2:
        return dates[0], dates[1]
    return None, None


def _extract_address(soup: BeautifulSoup) -> str | None:
    """
    실제 DOM:
      <div id="schedule_location">
        서울 ...
        <button onclick="copyLocation('서울 ...')">복사</button>
        ...
      </div>

    v0.3은 copyLocation(event,'주소')만 가정해서 64건 모두 address_missing이 났다.
    v0.3.1은 #schedule_location 자체를 직접 읽는다.
    """
    node = soup.select_one("#schedule_location")
    if not node:
        return None

    fragment = BeautifulSoup(str(node), "html.parser")

    for tag in fragment.select("button, a, i, img"):
        tag.decompose()

    value = _clean_text(fragment.get_text(" ", strip=True))
    value = re.sub(r"\s*복사\s*$", "", value).strip()

    if value:
        return value

    # fallback: onclick의 copyLocation('주소')
    button = node.select_one("button.copy_loc_btn")
    if button:
        onclick = button.get("onclick", "") or ""
        match = re.search(
            r"copyLocation\s*\(\s*['\"](?P<loc>.*?)['\"]\s*\)",
            onclick,
            flags=re.S,
        )
        if match:
            return _clean_text(match.group("loc"))

    return None


def _extract_hashtags(soup: BeautifulSoup) -> list[str]:
    container = soup.select_one(".hashtag-container")
    if not container:
        return []

    tags = []
    seen = set()

    # 실제 HTML에는 .hashtag 요소들이 존재.
    nodes = container.select(".hashtag")
    if nodes:
        values = [_clean_text(n.get_text(" ", strip=True)) for n in nodes]
    else:
        values = re.findall(
            r"#[0-9A-Za-z가-힣_]+",
            container.get_text(" ", strip=True),
        )

    for value in values:
        if not value:
            continue
        if not value.startswith("#"):
            value = "#" + value.lstrip("#")
        if value not in seen:
            seen.add(value)
            tags.append(value)

    return tags


def _extract_summary(soup: BeautifulSoup) -> str | None:
    return _text_of(soup, "#schedule_comment")


def _extract_tip(soup: BeautifulSoup) -> str | None:
    return _text_of(soup, ".schedule_detail")



def _address_tokens(value: str | None) -> set[str]:
    text = _clean_text(value)
    if not text:
        return set()
    tokens = {
        token.lower()
        for token in re.findall(r"[0-9A-Za-z가-힣]{2,}", text)
        if len(token) >= 2
    }
    stop = {
        "서울", "서울특별시", "대한민국", "지하", "지상", "건물", "매장",
        "팝업", "팝업스토어", "popup", "store",
    }
    return {token for token in tokens if token not in stop}


def _fallback_hours_from_content(content_text: str, address_hint: str | None) -> list[str]:
    """Conservative fallback for operating hours embedded in content.

    Recover only when there is useful evidence:
    - explicit popup/store operating marker
    - address-local range in a multi-venue post
    - address-matched range with a closed-day suffix
    - existing explicit operating/time labels

    Unlabelled session/performance time lists remain excluded.
    """
    text = re.sub(r"\s+", " ", content_text or "").strip()
    if not text:
        return []

    loose_time = r"(?:[0-2]?\d):\d{1,3}"
    range_text = rf"{loose_time}\s*[~～\-–—]\s*{loose_time}"
    range_matches = list(re.finditer(range_text, text, re.I))
    if not range_matches:
        return []

    # Strongest body signal:
    # "팝업 운영 10:30 - 22:00" must beat unrelated experience/session hours.
    popup_operation = re.search(
        rf"(?:팝업|POP\s*[-–—]?\s*UP)\s*"
        rf"(?:스토어\s*)?운영(?:\s*시간)?\s*[:：]?\s*"
        rf"({range_text})",
        text,
        re.I,
    )
    if popup_operation:
        return [re.sub(r"\s+", " ", popup_operation.group(1)).strip()]

    hint_tokens = _address_tokens(address_hint)

    # Multi-venue text sometimes has no 📍/장소 markers at all.
    # In that case, compare the text immediately preceding each time range
    # with the current record's address/venue tokens.
    #
    # But when the text already contains an explicit operating-hours label,
    # keep processing the whole selected block so weekday schedules such as
    # "평일 ... / 주말 ..." are preserved together.
    has_explicit_hours_label = bool(
        re.search(
            r"(?:운영\s*시간|영업\s*시간|오픈\s*시간|시간)\s*[:：]",
            text,
            re.I,
        )
    )

    if (
        hint_tokens
        and len(range_matches) > 1
        and not has_explicit_hours_label
    ):
        scored = []
        previous_end = 0

        for index, match in enumerate(range_matches):
            local_before = text[previous_end:match.start()]
            local_tokens = _address_tokens(local_before)
            overlap = hint_tokens & local_tokens

            strong_overlap = {
                token
                for token in overlap
                if len(token) >= 3 and not token.isdigit()
            }

            scored.append((
                len(strong_overlap),
                len(overlap),
                -index,
                match,
            ))
            previous_end = match.end()

        scored.sort(
            key=lambda item: (item[0], item[1], item[2]),
            reverse=True,
        )

        if scored and scored[0][0] >= 1:
            best_score = scored[0][:2]
            second_score = scored[1][:2] if len(scored) > 1 else (-1, -1)

            if best_score > second_score:
                value = re.sub(
                    r"\s+",
                    " ",
                    scored[0][3].group(0),
                ).strip()
                return [value]

    # Split primarily by explicit venue markers.
    blocks = [
        part.strip()
        for part in re.split(r"(?=(?:📍|\b장소\s*[:：]))", text)
        if part.strip()
    ]

    timed_blocks = [
        block for block in blocks
        if re.search(range_text, block, re.I)
    ]

    if not timed_blocks:
        return []

    selected: str | None = None
    selected_by_address = False

    if hint_tokens:
        scored_blocks: list[tuple[int, int, str]] = []

        for block in timed_blocks:
            block_tokens = _address_tokens(block)
            overlap = hint_tokens & block_tokens
            scored_blocks.append((len(overlap), len(block), block))

        scored_blocks.sort(reverse=True)

        if scored_blocks and scored_blocks[0][0] >= 2:
            if (
                len(scored_blocks) == 1
                or scored_blocks[0][0] > scored_blocks[1][0]
            ):
                selected = scored_blocks[0][2]
                selected_by_address = True

    if selected is None and len(timed_blocks) == 1:
        selected = timed_blocks[0]

    if selected is None:
        return []

    explicit_marker = bool(
        re.search(
            r"(?:🕒|⏰|운영\s*시간|영업\s*시간|오픈\s*시간)",
            selected,
            re.I,
        )
    )

    plain_time_label = bool(
        re.search(r"(?:^|\s)시간\s*[:：]", selected, re.I)
    )

    # English gallery-style exception:
    # 11:00-18:00 (Sun, Mon close)
    close_match = re.search(
        r"((?:(?:MON|TUE|WED|THU|FRI|SAT|SUN)\s*,\s*)*"
        r"(?:MON|TUE|WED|THU|FRI|SAT|SUN)\s+"
        r"(?:close|closed))",
        selected,
        re.I,
    )

    # Stay conservative. Do not accept an arbitrary content clock.
    if not explicit_marker and not (
        selected_by_address and plain_time_label
    ) and not (
        selected_by_address and close_match
    ):
        return []

    results: list[str] = []
    seen: set[str] = set()

    day_prefix = (
        r"(?:매일|평일|주말|"
        r"(?:[월화수목금토일](?:요일)?)"
        r"(?:\s*[~\-/,·]\s*[월화수목금토일](?:요일)?)*|"
        r"(?:MON|TUE|WED|THU|FRI|SAT|SUN)"
        r"(?:\s*[~\-/,]\s*"
        r"(?:MON|TUE|WED|THU|FRI|SAT|SUN))*)"
    )

    for match in re.finditer(
        rf"({day_prefix}\s*[:：]?\s*{range_text})",
        selected,
        re.I,
    ):
        value = re.sub(r"\s+", " ", match.group(1)).strip(" -|·")
        if value and value not in seen:
            seen.add(value)
            results.append(value)

    if not results:
        marker = re.search(
            rf"(?:🕒|⏰|시간\s*[:：])\s*({range_text})",
            selected,
            re.I,
        )
        if marker:
            value = re.sub(r"\s+", " ", marker.group(1)).strip()
            if value not in seen:
                seen.add(value)
                results.append(value)

    # Gallery-style body with the current address and a close-day suffix.
    if not results and selected_by_address and close_match:
        selected_ranges = list(
            re.finditer(range_text, selected, re.I)
        )

        if len(selected_ranges) == 1:
            value = re.sub(
                r"\s+",
                " ",
                selected_ranges[0].group(0),
            ).strip()
            seen.add(value)
            results.append(value)

    if results and close_match:
        close_value = re.sub(
            r"\s+",
            " ",
            close_match.group(1),
        ).strip()

        if close_value and close_value not in seen:
            results.append(close_value)

    return results


def _extract_operation_hours(soup: BeautifulSoup, address_hint: str | None = None) -> list[str]:
    """Extract published operating-time text from DayForYou detail DOM.

    Primary extraction stops permanently at the content-body section so class
    sessions, reservation slots, event times, etc. cannot leak into store hours.
    If the dedicated time field is missing, a conservative address-aware
    fallback can recover hours embedded in the source post itself.
    """
    node = soup.select_one(".schedule_detail")
    if not node:
        return []

    fragment = BeautifulSoup(str(node), "html.parser")
    br_token = " __DFY_BR__ "

    for br in fragment.find_all("br"):
        br.replace_with(br_token)

    text = fragment.get_text(" ", strip=True).replace("\u00a0", " ")
    lines = [
        re.sub(r"\s+", " ", line).strip()
        for line in text.split("__DFY_BR__")
    ]
    lines = [line for line in lines if line]

    results: list[str] = []
    seen: set[str] = set()
    content_parts: list[str] = []
    content_started = False

    loose_time = r"(?:[0-2]?\d):\d{1,3}"
    range_text = rf"{loose_time}\s*[~～\-–—]\s*{loose_time}"
    time_range = re.compile(range_text)

    # Some source pages contain:
    # "시간 : 10:30 22:00"
    # with the separator accidentally missing.
    labelled_clock_pair = re.compile(
        rf"(?:운영\s*시간|영업\s*시간|오픈\s*시간|시간)"
        rf"\s*[:：]\s*"
        rf"({loose_time}\s+{loose_time})",
        re.I,
    )

    labelled_range = re.compile(
        rf"(?:운영\s*시간|영업\s*시간|오픈\s*시간|시간)"
        rf"\s*[:：]\s*"
        rf"({range_text})",
        re.I,
    )

    popup_operation = re.compile(
        rf"(?:팝업|POP\s*[-–—]?\s*UP)\s*"
        rf"(?:스토어\s*)?운영(?:\s*시간)?\s*[:：]?\s*"
        rf"({range_text})",
        re.I,
    )

    section_stop = re.compile(
        r"(?:^|\s)(?:콘텐츠|대기정보|예약정보|해시태그)\s*[:：]?"
    )

    for line in lines:
        if content_started:
            content_parts.append(line)
            continue

        stop = section_stop.search(line)

        if stop:
            prefix = line[:stop.start()].strip()
            suffix = line[stop.end():].strip()

            if suffix:
                content_parts.append(suffix)

            content_started = True
            line = prefix

        if not line:
            continue

        # Preserve the full schedule after an explicit label.
        # Example:
        #   시간 : 평일 10:30~20:00, 금~일/공휴일 10:30~20:30
        # becomes:
        #   평일 10:30~20:00, 금~일/공휴일 10:30~20:30
        explicit_label_match = re.search(
            r"(?:^|\s)(?:운영\s*시간|영업\s*시간|오픈\s*시간|시간)"
            r"\s*[:：]\s*(.+)$",
            line,
            re.I,
        )

        if explicit_label_match:
            payload = explicit_label_match.group(1).strip()

            payload = re.split(
                r"\s+(?:콘텐츠|대기정보|예약정보|해시태그)\s*[:：]",
                payload,
                maxsplit=1,
                flags=re.I,
            )[0].strip()

            if time_range.search(payload):
                if payload not in seen:
                    seen.add(payload)
                    results.append(payload)
                continue

            if re.fullmatch(
                rf"{loose_time}\s+{loose_time}",
                payload,
                re.I,
            ):
                if payload not in seen:
                    seen.add(payload)
                    results.append(payload)
                continue

        labelled_range_match = labelled_range.search(line)
        labelled_pair_match = labelled_clock_pair.search(line)
        popup_operation_match = popup_operation.search(line)
        normal_range_match = time_range.search(line)

        if not (
            labelled_range_match
            or labelled_pair_match
            or popup_operation_match
            or normal_range_match
        ):
            continue

        valid_signal = (
            "⏰" in line
            or labelled_range_match is not None
            or labelled_pair_match is not None
            or popup_operation_match is not None
            or re.search(
                r"^(?:매일|평일|주말|매주|월|화|수|목|금|토|일|"
                r"MON|TUE|WED|THU|FRI|SAT|SUN)",
                line,
                re.I,
            )
        )

        if not valid_signal:
            continue

        if labelled_range_match:
            value = labelled_range_match.group(1)
        elif labelled_pair_match:
            value = labelled_pair_match.group(1)
        elif popup_operation_match:
            value = popup_operation_match.group(1)
        elif "⏰" in line:
            value = re.sub(r"^.*?⏰\s*", "", line).strip()
        else:
            value = line

        value = value.strip(" -|·")

        if value and value not in seen:
            seen.add(value)
            results.append(value)

    if results:
        return results

    # Some records contain only free-form detail text without an explicit
    # "콘텐츠:" section marker. In that case the conservative fallback still
    # needs to inspect the original detail lines.
    fallback_text = (
        " ".join(content_parts)
        if content_parts
        else " ".join(lines)
    )

    return _fallback_hours_from_content(
        fallback_text,
        address_hint,
    )


def _extract_official_url(soup: BeautifulSoup) -> str | None:
    node = soup.select_one("#schedule_homepage")
    if not node:
        return None

    href = (node.get("href") or "").strip()
    if not href:
        return None

    return urljoin(SITE_URL, href)


def parse_detail_html(
    html: str,
    source_id: str,
    detail_url: str,
    *,
    http_status: int | None = 200,
    fetched_from_cache: bool = False,
) -> DetailRecord:
    soup = BeautifulSoup(html, "html.parser")
    warnings: list[str] = []

    title = _extract_title(soup)
    start_date, end_date = _extract_period(soup)
    address = _extract_address(soup)
    hashtags = _extract_hashtags(soup)
    summary = _extract_summary(soup)
    tip = _extract_tip(soup)
    official_url = _extract_official_url(soup)
    operation_hours_raw = _extract_operation_hours(soup, address_hint=address)

    if not title:
        warnings.append("title_missing")
    if not start_date or not end_date:
        warnings.append("period_missing")
    if not address:
        warnings.append("address_missing")
    if not hashtags:
        warnings.append("hashtags_missing")
    if not summary and not tip:
        warnings.append("detail_text_sparse")

    return DetailRecord(
        source="dayforyou",
        source_id=str(source_id),
        detail_url=detail_url,
        title_detail=title,
        start_date_detail=start_date,
        end_date_detail=end_date,
        address_detail=address,
        hashtags=hashtags,
        tip_text=tip,
        summary_text=summary,
        official_url=official_url,
        operation_hours_raw=operation_hours_raw,
        fetch_ok=True,
        http_status=http_status,
        parse_warnings=warnings,
        fetched_from_cache=fetched_from_cache,
    )


def _failed_record(
    source_id: str,
    detail_url: str,
    status: int | None,
    warning: str,
) -> DetailRecord:
    return DetailRecord(
        source="dayforyou",
        source_id=str(source_id),
        detail_url=detail_url,
        title_detail=None,
        start_date_detail=None,
        end_date_detail=None,
        address_detail=None,
        hashtags=[],
        tip_text=None,
        summary_text=None,
        official_url=None,
        operation_hours_raw=[],
        fetch_ok=False,
        http_status=status,
        parse_warnings=[warning],
        fetched_from_cache=False,
    )


def _detail_url_candidates(detail_url: str, source_id: str) -> list[str]:
    candidates = [detail_url]
    if "www.dayforyou.com" in detail_url:
        candidates.append(detail_url.replace("https://www.dayforyou.com", SITE_URL, 1))
    elif "dayforyou.com" in detail_url:
        candidates.append(detail_url.replace("https://dayforyou.com", FALLBACK_SITE_URL, 1))
    else:
        candidates.extend([
            DETAIL_URL.format(source_id=source_id),
            FALLBACK_SITE_URL + f"/getDetail?scheduleSeq={source_id}",
        ])
    return list(dict.fromkeys(candidates))


def fetch_details(
    review_items: list[dict],
    cache_dir: str | Path = "data/detail_html",
    *,
    delay_seconds: float | None = None,
    timeout: int = 20,
    retries: int = 2,
    cache_max_age_hours: float = 54.0,
) -> list[DetailRecord]:
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    if delay_seconds is None:
        delay_seconds = float(os.getenv("DETAIL_REQUEST_DELAY", "0.5"))

    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/151.0 Safari/537.36"
        ),
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
        "Referer": SITE_URL + "/getScheduleList",
    })

    results: list[DetailRecord] = []
    total = len(review_items)

    for index, item in enumerate(review_items, start=1):
        source_id = str(item["source_id"])
        detail_url = item.get("detail_url") or DETAIL_URL.format(source_id=source_id)
        cache_path = cache_dir / f"{source_id}.html"

        print(f"    [DETAIL {index}/{total}] {source_id}", end="")

        if cache_path.exists() and cache_path.stat().st_size > 200 and cache_max_age_hours > 0:
            age_hours = max(0.0, (time.time() - cache_path.stat().st_mtime) / 3600.0)
            if age_hours <= cache_max_age_hours:
                html = cache_path.read_text(encoding="utf-8", errors="replace")
                results.append(
                    parse_detail_html(
                        html,
                        source_id,
                        detail_url,
                        fetched_from_cache=True,
                    )
                )
                print(f" - cache/reparsed ({age_hours:.1f}h)")
                continue

        last_error = None
        last_status = None

        success = False
        candidates = _detail_url_candidates(detail_url, source_id)
        for attempt in range(1, retries + 1):
            for candidate_url in candidates:
                try:
                    response = session.get(candidate_url, timeout=timeout)
                    last_status = response.status_code

                    if response.status_code == 200:
                        html = response.content.decode("utf-8", errors="replace")
                        cache_path.write_text(html, encoding="utf-8")
                        results.append(
                            parse_detail_html(
                                html,
                                source_id,
                                response.url or candidate_url,
                                http_status=response.status_code,
                            )
                        )
                        print(" - ok")
                        last_error = None
                        success = True
                        break

                    last_error = f"http_{response.status_code}"
                except requests.RequestException as exc:
                    last_error = exc.__class__.__name__
            if success:
                break
            if attempt < retries:
                time.sleep(1.0 * attempt)

        if last_error:
            results.append(
                _failed_record(source_id, detail_url, last_status, last_error)
            )
            print(f" - fail ({last_error})")

        time.sleep(max(0.0, delay_seconds))

    return results


def save_detail_jsonl(
    records: Iterable[DetailRecord],
    path: str | Path,
) -> int:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    count = 0
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")
            count += 1
    return count
