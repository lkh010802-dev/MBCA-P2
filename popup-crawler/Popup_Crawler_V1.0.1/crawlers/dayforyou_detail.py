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
    """Conservative fallback for hours embedded in the content body.

    The source occasionally omits/mangles the dedicated ``시간 :`` field while
    the post body still publishes venue hours. Recovery stays intentionally
    narrow: strong operating markers, a commerce/exhibition context, or a
    unique address-matched venue window are required. Session/performance lists
    are not converted into opening hours.
    """
    text = re.sub(r"\s+", " ", content_text or "").strip()
    if not text:
        return []

    loose_time = r"(?:[0-2]?\d):\d{1,3}"
    range_text = rf"{loose_time}\s*[~～\-–—]\s*{loose_time}"
    range_re = re.compile(range_text)
    clock_re = re.compile(rf"(?<!\d){loose_time}(?!\d)")
    marker_re = re.compile(
        r"(?:🕒|⏰|팝업\s*운영|운영\s*시간|영업\s*시간|오픈\s*시간|관람\s*시간|OPEN\s*:?|시간\s*[:：])",
        re.I,
    )
    commerce_re = re.compile(
        r"(?:팝업|POP[- ]?UP|POPUP|STORE|매장|콜라보\s*카페|카페|CAFE|전시|EXHIBITION|갤러리|GALLERY)",
        re.I,
    )
    session_re = re.compile(r"(?:영재교실|수업|강의|회차|공연|상영|일시|타임테이블)", re.I)

    def closure_values(scope: str) -> list[str]:
        results: list[str] = []
        patterns = [
            r"((?:매주\s*)?(?:[월화수목금토일](?:요일)?)(?:\s*[,/·]\s*[월화수목금토일](?:요일)?)*\s*(?:휴무|휴뮤|휴점|정기휴일))",
            r"((?:MON(?:DAY)?|TUE(?:S|SDAY)?|WED(?:NESDAY)?|THU(?:R|RS|RSDAY)?|FRI(?:DAY)?|SAT(?:URDAY)?|SUN(?:DAY)?)(?:\s*[,/]\s*(?:MON(?:DAY)?|TUE(?:S|SDAY)?|WED(?:NESDAY)?|THU(?:R|RS|RSDAY)?|FRI(?:DAY)?|SAT(?:URDAY)?|SUN(?:DAY)?))*\s*(?:CLOSE|CLOSED))",
        ]
        seen: set[str] = set()
        for pattern in patterns:
            for match in re.finditer(pattern, scope, re.I):
                value = re.sub(r"\s+", " ", match.group(1)).strip(" ()")
                if value and value not in seen:
                    seen.add(value)
                    results.append(value)
        return results

    def with_closures(values: list[str], scope: str) -> list[str]:
        out = list(values)
        seen = set(out)
        for value in closure_values(scope):
            if value not in seen:
                seen.add(value)
                out.append(value)
        return out

    hint_tokens = _address_tokens(address_hint)

    # Separator-less source typo: ``14:00 22:00`` / ``시간: 10:30 22:00``.
    # Exactly two clocks are required, which excludes performance/session lists.
    standard_ranges = list(range_re.finditer(text))
    if not standard_ranges:
        clocks = list(clock_re.finditer(text))
        spaced = re.search(rf"(?<!\d)({loose_time})\s+({loose_time})(?!\d)", text)
        overlap = len(hint_tokens & _address_tokens(text)) if hint_tokens else 0
        if len(clocks) == 2 and spaced:
            strong = bool(marker_re.search(text)) or bool(commerce_re.search(text) and overlap >= 2)
            if strong and not (session_re.search(text) and not marker_re.search(text)):
                return [re.sub(r"\s+", " ", spaced.group(0)).strip()]
        return []

    # Split primarily by explicit venue markers. Keep ``주소:`` inside a block
    # because it helps address matching.
    blocks = [
        part.strip()
        for part in re.split(r"(?=(?:📍|\b장소\s*[:：]))", text)
        if part.strip()
    ]
    timed_blocks = [block for block in blocks if range_re.search(block)]
    if not timed_blocks:
        return []

    selected: str | None = None
    selected_by_address = False
    if hint_tokens:
        scored: list[tuple[int, int, str]] = []
        for block in timed_blocks:
            overlap = hint_tokens & _address_tokens(block)
            scored.append((len(overlap), len(block), block))
        scored.sort(reverse=True)
        if scored and scored[0][0] >= 2:
            if len(scored) == 1 or scored[0][0] > scored[1][0]:
                selected = scored[0][2]
                selected_by_address = True

    if selected is None and len(timed_blocks) == 1:
        selected = timed_blocks[0]
    if selected is None:
        return []

    # Some multi-venue posts omit explicit venue separators. Score local
    # context around each range against the current record address and accept a
    # uniquely best range only. This recovers e.g. the Shincheon branch from a
    # Shincheon+Yongsan roundup without importing Yongsan hours.
    selected_ranges = list(range_re.finditer(selected))
    if hint_tokens and len(selected_ranges) >= 2 and len(timed_blocks) == 1:
        local_scores: list[tuple[int, int, re.Match[str]]] = []
        for idx, match in enumerate(selected_ranges):
            left = 0
            right = len(selected)
            if idx > 0:
                prev = selected_ranges[idx - 1]
                left = (prev.end() + match.start()) // 2
            if idx + 1 < len(selected_ranges):
                nxt = selected_ranges[idx + 1]
                right = (match.end() + nxt.start()) // 2
            context = selected[left:right]
            score = len(hint_tokens & _address_tokens(context))
            local_scores.append((score, -idx, match))
        ranked = sorted(local_scores, reverse=True)
        if ranked and ranked[0][0] >= 2 and (len(ranked) == 1 or ranked[0][0] > ranked[1][0]):
            match = ranked[0][2]
            return with_closures([re.sub(r"\s+", " ", match.group(0)).strip()], selected)

    explicit_marker = bool(marker_re.search(selected))
    plain_time_label = bool(re.search(r"(?:^|\s)시간\s*[:：]", selected, re.I))
    commerce_signal = bool(commerce_re.search(selected))
    session_signal = bool(session_re.search(selected))

    results: list[str] = []
    seen: set[str] = set()

    # Prefer explicit weekday + time patterns.
    day_prefix = r"(?:매일|평일|주말|매주\s*(?:[월화수목금토일](?:요일)?)(?:\s*[/,·]\s*[월화수목금토일](?:요일)?)*|(?:[월화수목금토일](?:요일)?)(?:\s*[~\-/,·]\s*[월화수목금토일](?:요일)?)*|(?:MON|TUE|WED|THU|FRI|SAT|SUN)(?:\s*[~\-/,]\s*(?:MON|TUE|WED|THU|FRI|SAT|SUN))*)"
    for match in re.finditer(rf"({day_prefix}\s*[:：|]?\s*{range_text})", selected, re.I):
        value = re.sub(r"\s+", " ", match.group(1)).strip(" -|·")
        if value and value not in seen:
            seen.add(value)
            results.append(value)

    if results and (explicit_marker or commerce_signal) and not (session_signal and not explicit_marker and not commerce_signal):
        return with_closures(results, selected)

    # Prefer a specifically labelled operating range (``팝업 운영``, ``Open``,
    # clock icon, etc.) over other ranges such as experience/class hours.
    marker = re.search(
        rf"(?:🕒|⏰|팝업\s*운영|운영\s*시간|영업\s*시간|오픈\s*시간|관람\s*시간|OPEN\s*:?|시간\s*[:：])\s*[:：]?\s*({range_text})",
        selected,
        re.I,
    )
    if marker:
        value = re.sub(r"\s+", " ", marker.group(1)).strip()
        return with_closures([value], selected)

    # A plain ``시간:`` in body text can describe a class/session. Accept only
    # when address selection is strong and there is exactly one range.
    if selected_by_address and plain_time_label and len(selected_ranges) == 1 and not session_signal:
        return with_closures([selected_ranges[0].group(0).strip()], selected)

    # Finally, a unique range inside a popup/store/cafe/exhibition body is a
    # strong operating-hours signal. Extra scalar clocks (e.g. last order or
    # press-open time) do not invalidate the unique range itself.
    if commerce_signal and len(selected_ranges) == 1 and not session_signal:
        return with_closures([selected_ranges[0].group(0).strip()], selected)

    return []

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
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.split("__DFY_BR__")]
    lines = [line for line in lines if line]

    results: list[str] = []
    seen: set[str] = set()
    content_parts: list[str] = []
    content_started = False

    loose_time = r"(?:[0-2]?\d):\d{1,3}"
    time_range = re.compile(rf"{loose_time}\s*[~～\-–—]\s*{loose_time}")
    spaced_pair = re.compile(rf"(?<!\d)({loose_time})\s+({loose_time})(?!\d)")
    section_stop = re.compile(r"(?:^|\s)(?:콘텐츠|대기정보|예약정보|해시태그)\s*[:：]?")

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

        explicit_label = bool(
            "⏰" in line
            or re.search(
                r"(?:^|\s)(?:팝업\s*운영|운영\s*시간|영업\s*시간|오픈\s*시간|관람\s*시간|시간)\s*[:：]?",
                line,
                re.I,
            )
        )
        has_standard_range = bool(time_range.search(line))
        clock_tokens = re.findall(rf"(?<!\d){loose_time}(?!\d)", line)
        has_safe_spaced_pair = bool(explicit_label and len(clock_tokens) == 2 and spaced_pair.search(line))

        if not has_standard_range and not has_safe_spaced_pair:
            continue

        if not (
            explicit_label
            or re.search(r"^(?:매일|평일|주말|매주|월|화|수|목|금|토|일|MON|TUE|WED|THU|FRI|SAT|SUN)", line, re.I)
        ):
            continue

        value = re.sub(r"^.*?⏰\s*", "", line).strip() if "⏰" in line else line
        label_match = re.search(
            r"(?:팝업\s*운영|운영\s*시간|영업\s*시간|오픈\s*시간|관람\s*시간|시간)\s*[:：]?\s*",
            value,
            flags=re.I,
        )
        if label_match:
            value = value[label_match.end():]
        value = value.strip(" -|·")
        if value and value not in seen:
            seen.add(value)
            results.append(value)

    if results:
        return results

    fallback_text = " ".join(content_parts) if content_parts else " ".join(lines)
    return _fallback_hours_from_content(fallback_text, address_hint)

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

        if cache_path.exists() and cache_path.stat().st_size > 200:
            html = cache_path.read_text(encoding="utf-8", errors="replace")
            results.append(
                parse_detail_html(
                    html,
                    source_id,
                    detail_url,
                    fetched_from_cache=True,
                )
            )
            print(" - cache/reparsed")
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
