import hashlib
import math
import os
import re
import time
import unicodedata

from datetime import date, datetime
from urllib.parse import quote
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv


# 기존 서울 열린데이터광장 API 키를 그대로 사용한다.
load_dotenv()

SEOUL_API_KEY = os.getenv("SEOUL_API_KEY")

SEOUL_CULTURE_API_BASE_URL = (
    "http://openapi.seoul.go.kr:8088"
)
SEOUL_CULTURE_SERVICE_NAME = "culturalEventInfo"
SEOUL_EXHIBITION_CATEGORY = "전시/미술"
SEOUL_FESTIVAL_CATEGORY_PREFIX = "축제"
SEOUL_RECOMMENDABLE_API_CATEGORIES = (
    SEOUL_EXHIBITION_CATEGORY,
    SEOUL_FESTIVAL_CATEGORY_PREFIX,
)

# 전체 데이터는 약 2만 건이므로 추천 요청마다 다시 받지 않는다.
# 프로세스별 메모리 캐시이며 서버 재시작 시 자연스럽게 초기화된다.
SEOUL_CULTURE_CACHE_TTL_SECONDS = 6 * 60 * 60
_recommendable_event_cache = {
    "expires_at": 0.0,
    "rows": None,
}

# 서울시를 충분히 포함하는 1차 좌표 검증 범위다.
# 해외 좌표나 위도/경도가 뒤바뀐 데이터가 거리 계산에 들어오는 것을 막는다.
SEOUL_LATITUDE_RANGE = (37.40, 37.72)
SEOUL_LONGITUDE_RANGE = (126.75, 127.20)

SEOUL_TIMEZONE = ZoneInfo("Asia/Seoul")

OPERATION_DAY_CODES = {
    "월": "MON",
    "화": "TUE",
    "수": "WED",
    "목": "THU",
    "금": "FRI",
    "토": "SAT",
    "일": "SUN",
}
OPERATION_ALL_DAYS = tuple(OPERATION_DAY_CODES.values())

_DAY_TOKEN_PATTERN = r"[월화수목금토일](?:요일)?"
_DAY_EXPRESSION_PATTERN = re.compile(
    rf"(?<![가-힣\d])(?:매주\s*)?(?:"
    rf"평일|주말|매일|연중무휴|"
    rf"{_DAY_TOKEN_PATTERN}(?:"
    rf"\s*(?:-|~|∼|～|–|—|부터)\s*{_DAY_TOKEN_PATTERN}"
    rf"|(?:\s*(?:[,/·.]|및)\s*{_DAY_TOKEN_PATTERN})+"
    rf")?"
    rf")(?![가-힣\d])"
)


def _time_token_pattern(prefix: str):
    return (
        rf"(?P<{prefix}_raw>"
        rf"(?:(?P<{prefix}_ampm>오전|오후)\s*)?"
        rf"(?P<{prefix}_hour>\d{{1,2}})"
        rf"(?:"
        rf":\s*(?P<{prefix}_minute>\d{{1,2}})"
        rf"|시(?:\s*(?P<{prefix}_korean_minute>\d{{1,2}})\s*분?)?"
        rf")"
        rf")"
    )


_TIME_RANGE_PATTERN = re.compile(
    rf"(?<!\d){_time_token_pattern('open')}"
    rf"\s*(?:~|∼|～|-|–|—|부터)\s*"
    rf"{_time_token_pattern('close')}(?:\s*까지)?"
)

_BREAK_TIME_RANGE_PATTERN = re.compile(
    rf"(?:break\s*time|브레이크\s*타임|휴게\s*시간)"
    rf"\s*[:：]?\s*{_time_token_pattern('break_open')}"
    rf"\s*(?:~|∼|～|-|–|—|부터)\s*"
    rf"{_time_token_pattern('break_close')}(?:\s*까지)?",
    re.IGNORECASE,
)

_CLOSING_TIME_OVERRIDE_PATTERN = re.compile(
    rf"(?<!\d){_time_token_pattern('override_close')}"
    rf"\s*까지\s*(?:야간\s*)?(?:개관|운영)"
)

_CLOSED_SIGNALS = (
    "휴무",
    "휴관",
    "운영 안 함",
    "운영안함",
    "쉬는 날",
)

_PARTIAL_OPERATION_SIGNALS = (
    "공휴일",
    "추석",
    "설날",
    "연휴",
    "1월 1일",
    "매월",
    "첫째",
    "둘째",
    "셋째",
    "넷째",
    "마지막",
    "우천",
    "변동",
    "상이",
    "홈페이지",
    "문의",
    "입장 마감",
    "입장마감",
    "매표마감",
    "입장가능",
    "예약",
)


class SeoulCultureAPIError(RuntimeError):
    """서울 문화행사 API 호출 또는 응답 형식 오류."""


def _build_api_url(
    api_key: str,
    start_index: int,
    end_index: int,
    category: str | None,
):
    """서울 열린데이터광장 문화행사 API 요청 URL을 만든다."""

    encoded_key = quote(api_key, safe="")
    url = (
        f"{SEOUL_CULTURE_API_BASE_URL}/"
        f"{encoded_key}/json/"
        f"{SEOUL_CULTURE_SERVICE_NAME}/"
        f"{start_index}/{end_index}/"
    )

    if category is None:
        return url

    encoded_category = quote(category, safe="")
    return f"{url}{encoded_category}/"


def _request_event_page(
    start_index: int,
    end_index: int,
    category: str | None = SEOUL_EXHIBITION_CATEGORY,
    api_key: str | None = None,
    timeout: int = 10,
):
    """문화행사 API의 한 페이지를 조회한다."""

    resolved_api_key = api_key or SEOUL_API_KEY

    if not resolved_api_key:
        raise SeoulCultureAPIError(
            "SEOUL_API_KEY 환경변수가 필요합니다."
        )

    url = _build_api_url(
        api_key=resolved_api_key,
        start_index=start_index,
        end_index=end_index,
        category=category,
    )

    try:
        response = requests.get(
            url,
            timeout=timeout,
        )
        response.raise_for_status()
        data = response.json()

    except (requests.RequestException, ValueError) as exc:
        raise SeoulCultureAPIError(
            "서울 문화행사 API 호출에 실패했습니다."
        ) from exc

    if not isinstance(data, dict):
        raise SeoulCultureAPIError(
            "서울 문화행사 API 응답이 객체 형식이 아닙니다."
        )

    service_data = data.get(
        SEOUL_CULTURE_SERVICE_NAME
    )

    if not isinstance(service_data, dict):
        result = data.get("RESULT", {})
        message = result.get(
            "MESSAGE",
            "문화행사 응답 본문을 찾을 수 없습니다.",
        )
        raise SeoulCultureAPIError(message)

    result = service_data.get("RESULT", {})
    result_code = result.get("CODE")

    if result_code != "INFO-000":
        raise SeoulCultureAPIError(
            result.get(
                "MESSAGE",
                f"서울 문화행사 API 오류: {result_code}",
            )
        )

    rows = service_data.get("row", [])

    if isinstance(rows, dict):
        rows = [rows]

    if not isinstance(rows, list):
        raise SeoulCultureAPIError(
            "서울 문화행사 API row 형식이 올바르지 않습니다."
        )

    return {
        "total_count": int(
            service_data.get("list_total_count", 0)
        ),
        "rows": rows,
    }


def fetch_seoul_culture_events(
    category: str | None = SEOUL_EXHIBITION_CATEGORY,
    page_size: int = 1000,
    api_key: str | None = None,
):
    """
    서울 문화행사를 페이지 끝까지 조회한다.

    category가 None이면 약 2만 건의 전체 데이터를 조회하고,
    문자열을 전달하면 API의 분류 검색 결과를 조회한다.

    서울 API의 날짜 검색 결과만 신뢰하지 않고,
    조회 후 시작일/종료일을 코드에서 다시 검사한다.
    """

    if page_size < 1 or page_size > 1000:
        raise ValueError(
            "page_size는 1 이상 1000 이하여야 합니다."
        )

    all_rows = []
    start_index = 1
    total_count = None

    while total_count is None or start_index <= total_count:
        end_index = start_index + page_size - 1

        page = _request_event_page(
            start_index=start_index,
            end_index=end_index,
            category=category,
            api_key=api_key,
        )

        if total_count is None:
            total_count = page["total_count"]

        rows = page["rows"]

        if not rows:
            break

        all_rows.extend(rows)
        start_index += page_size

    return all_rows


def clear_seoul_culture_cache():
    """테스트나 강제 새로고침을 위해 메모리 캐시를 비운다."""

    _recommendable_event_cache["expires_at"] = 0.0
    _recommendable_event_cache["rows"] = None


def fetch_recommendable_seoul_culture_events(
    page_size: int = 1000,
    api_key: str | None = None,
    use_cache: bool = True,
):
    """
    전체 원본에서 전시/미술과 모든 축제 분류를 골라낸다.

    API URL의 CODENAME 검색 결과가 전체 CSV와 일치하지 않는
    사례가 있어, 전체 데이터를 페이지 조회한 뒤 로컬에서
    카테고리를 판별한다. 약 2만 건을 매 요청마다 다시 받지
    않도록 결과를 6시간 동안 프로세스 메모리에 캐시한다.
    """

    now = time.monotonic()
    cached_rows = _recommendable_event_cache["rows"]

    if (
        use_cache
        and cached_rows is not None
        and now < _recommendable_event_cache["expires_at"]
    ):
        return list(cached_rows)

    all_rows = fetch_seoul_culture_events(
        category=None,
        page_size=page_size,
        api_key=api_key,
    )
    recommendable_rows = [
        event
        for event in all_rows
        if is_recommendable_category(event.get("CODENAME"))
    ]

    if use_cache:
        _recommendable_event_cache["rows"] = list(
            recommendable_rows
        )
        _recommendable_event_cache["expires_at"] = (
            now + SEOUL_CULTURE_CACHE_TTL_SECONDS
        )

    return recommendable_rows


def parse_event_date(value: str | None):
    """서울 API 날짜 문자열을 date로 변환한다."""

    if not value:
        return None

    date_text = str(value).strip()

    for date_format in (
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(
                date_text,
                date_format,
            ).date()

        except ValueError:
            continue

    return None


def _resolve_reference_date(
    reference_date: date | datetime | None,
):
    if reference_date is None:
        return datetime.now(SEOUL_TIMEZONE).date()

    if isinstance(reference_date, datetime):
        return reference_date.date()

    return reference_date


def is_event_active(
    event: dict,
    reference_date: date | datetime | None = None,
):
    """행사가 기준일에 진행 중인지 확인한다."""

    start_date = parse_event_date(
        event.get("STRTDATE")
    )
    end_date = parse_event_date(
        event.get("END_DATE")
    )

    if start_date is None or end_date is None:
        return False

    current_date = _resolve_reference_date(
        reference_date
    )

    return start_date <= current_date <= end_date


def _normalize_text(value):
    """비교용 문자열의 유니코드, 대소문자, 공백을 정리한다."""

    if value is None:
        return ""

    normalized = unicodedata.normalize(
        "NFKC",
        str(value),
    ).lower()

    return re.sub(r"\s+", " ", normalized).strip()


def is_recommendable_category(category: str | None):
    """전시/미술 또는 축제-* 분류인지 확인한다."""

    normalized_category = str(
        category or ""
    ).strip()

    return (
        normalized_category == SEOUL_EXHIBITION_CATEGORY
        or normalized_category.startswith(
            SEOUL_FESTIVAL_CATEGORY_PREFIX
        )
    )


def is_online_only_event(event: dict):
    """
    장소 필드를 중심으로 온라인 전용 행사를 판별한다.

    온라인 예약 후 현장 방문하거나 오프라인 장소가 함께
    명시된 행사는 제외하지 않는다.
    """

    place_text = _normalize_text(
        event.get("PLACE")
    )

    if not place_text:
        return False

    # 예약 방식만 온라인이거나 현장 병행이 명시된 경우는 유지한다.
    if (
        "온라인 예약" in place_text
        or "온라인예약" in place_text
        or "오프라인" in place_text
        or "현장" in place_text
    ):
        return False

    exact_online_places = {
        "온라인",
        "온라인 전시관",
        "온라인전시관",
        "zoom",
        "줌",
        "비대면",
    }

    if place_text in exact_online_places:
        return True

    online_only_signals = (
        "온라인 전용",
        "온라인전용",
        "온라인 전시관",
        "온라인전시관",
        "비대면 전용",
        "비대면전용",
        "zoom",
        "줌",
        "youtube",
        "유튜브",
        "메타버스",
    )

    if any(
        signal in place_text
        for signal in online_only_signals
    ):
        return True

    offline_signals = (
        "미술관",
        "박물관",
        "갤러리",
        "전시장",
        "전시실",
        "문화원",
        "문화회관",
        "아트홀",
        "도서관",
        "센터",
        "공원",
        "광장",
        "거리",
        "일대",
    )

    if any(
        signal in place_text
        for signal in offline_signals
    ):
        return False

    return (
        "온라인" in place_text
        or "비대면" in place_text
    )


def is_restricted_audience(audience: str | None):
    """
    명백하게 특정 대상만 참여 가능한 행사인지 판별한다.

    일반 참여 가능성이 명시되면 제한 키워드가 함께 있어도
    포함하고, 애매한 경우에도 포함한다.
    """

    text = _normalize_text(audience)

    if not text:
        return False

    general_signals = (
        "누구나",
        "일반시민",
        "일반 시민",
        "일반인",
        "시민 누구나",
        "서울시민",
        "전체관람",
        "전체 관람",
        "제한없음",
        "제한 없음",
        "전 연령",
        "전연령",
        "남녀노소",
    )

    if (
        text == "시민"
        or any(signal in text for signal in general_signals)
    ):
        return False

    # 여러 연령이 함께 적힌 경우 사실상 전 연령으로 본다.
    if all(
        age_group in text
        for age_group in (
            "어린이",
            "청소년",
            "성인",
        )
    ):
        return False

    # 비회원도 참여할 수 있다고 명시된 경우 회원 제한이 아니다.
    if "비회원" in text:
        return False

    restricted_patterns = (
        r"^(미취학아동|유아|어린이|청소년|초등학생|중학생|고등학생)$",
        r"(미취학아동|유아|어린이|청소년|초등학생|중학생|고등학생)\s*(만|대상|한정|전용)",
        r"(어린이|유아).*(동반 가족|보호자 동반)",
        r"가족\s*(만|대상|한정|전용)",
        r"보호자\s*동반\s*(필수|대상)",
        r"[가-힣]+구민\s*(만|대상|한정|전용)",
        r"[가-힣]+구\s*주민\s*(만|대상|한정|전용)",
        r"(장애예술인|전공생|관련 종사자)",
        r"(예술인|장애인|관계자)\s*(만|대상|한정|전용)",
        r"(학교|학급|기관)\s*단체",
        r"회원\s*(만|대상|한정|전용)",
        r"(제대군인|보훈대상자|특정 자격 보유자|특정 연령)",
    )

    return any(
        re.search(pattern, text)
        for pattern in restricted_patterns
    )


def _parse_coordinate(value):
    """숫자로 명확하게 표현된 좌표만 허용한다."""

    if value is None:
        return None

    try:
        coordinate = float(str(value).strip())

    except (TypeError, ValueError):
        return None

    if not math.isfinite(coordinate):
        return None

    return coordinate


def is_valid_seoul_coordinate(
    latitude: float | None,
    longitude: float | None,
):
    """좌표가 서울시 1차 검증 범위 안인지 확인한다."""

    if latitude is None or longitude is None:
        return False

    return (
        SEOUL_LATITUDE_RANGE[0]
        <= latitude
        <= SEOUL_LATITUDE_RANGE[1]
        and SEOUL_LONGITUDE_RANGE[0]
        <= longitude
        <= SEOUL_LONGITUDE_RANGE[1]
    )


def is_seoul_location(event: dict):
    """행사 좌표가 서울 1차 검증 범위 안인지 확인한다."""

    latitude = _parse_coordinate(event.get("LAT"))
    longitude = _parse_coordinate(event.get("LOT"))

    return is_valid_seoul_coordinate(
        latitude,
        longitude,
    )


def get_event_exclusion_reason(
    event: dict,
    reference_date: date | datetime | None = None,
    only_active: bool = True,
    require_seoul_coordinate: bool = True,
):
    """추천 후보에서 제외해야 하는 첫 번째 이유를 반환한다."""

    if not isinstance(event, dict):
        return "invalid_event"

    if not is_recommendable_category(
        event.get("CODENAME")
    ):
        return "unsupported_category"

    if not str(event.get("TITLE") or "").strip():
        return "missing_title"

    if only_active and not is_event_active(
        event,
        reference_date=reference_date,
    ):
        return "inactive"

    if is_online_only_event(event):
        return "online_only"

    latitude = _parse_coordinate(event.get("LAT"))
    longitude = _parse_coordinate(event.get("LOT"))

    if latitude is None or longitude is None:
        return "invalid_coordinate"

    if (
        require_seoul_coordinate
        and not is_valid_seoul_coordinate(
            latitude,
            longitude,
        )
    ):
        return "outside_seoul"

    if is_restricted_audience(
        event.get("USE_TRGT")
    ):
        return "restricted_audience"

    return None


def should_include_seoul_culture_event(
    event: dict,
    reference_date: date | datetime | None = None,
):
    """최종 서울 문화행사 수집 기준을 모두 만족하는지 확인한다."""

    return get_event_exclusion_reason(
        event,
        reference_date=reference_date,
        only_active=True,
        require_seoul_coordinate=True,
    ) is None


def _extract_source_id(event: dict):
    """문화포털 상세 URL의 cultcode를 우선 고유 ID로 사용한다."""

    detail_url = event.get("HMPG_ADDR") or ""
    match = re.search(r"[?&]cultcode=([^&]+)", detail_url)

    if match:
        return match.group(1)

    fallback_text = "|".join([
        str(event.get("TITLE") or "").strip(),
        str(event.get("STRTDATE") or "").strip(),
        str(event.get("PLACE") or "").strip(),
    ])

    return hashlib.sha256(
        fallback_text.encode("utf-8")
    ).hexdigest()[:20]


def _normalize_is_free(value: str | None):
    if not value:
        return None

    normalized_value = str(value).strip()

    if normalized_value == "무료":
        return True

    if normalized_value == "유료":
        return False

    return None


def _operation_hours_raw_blocks(value: str | None):
    """운영시간 원문을 내용을 바꾸지 않고 줄 단위 배열로 보존한다."""

    if value is None:
        return []

    raw_text = str(value).strip()

    if not raw_text:
        return []

    blocks = [
        line.strip()
        for line in raw_text.splitlines()
        if line.strip()
    ]

    return blocks or [raw_text]


def _expand_operation_days(expression: str):
    """요일 표현을 MON~SUN 배열로 변환한다."""

    normalized = unicodedata.normalize(
        "NFKC",
        str(expression or ""),
    )
    normalized = re.sub(r"\s+", "", normalized)
    normalized = normalized.replace("요일", "")
    normalized = re.sub(r"^매주", "", normalized)

    aliases = {
        "평일": list(OPERATION_ALL_DAYS[:5]),
        "주말": list(OPERATION_ALL_DAYS[5:]),
        "매일": list(OPERATION_ALL_DAYS),
        "연중무휴": list(OPERATION_ALL_DAYS),
    }

    if normalized in aliases:
        return aliases[normalized]

    day_tokens = re.findall(
        r"[월화수목금토일]",
        normalized,
    )

    if not day_tokens:
        return []

    has_range = bool(
        re.search(r"(?:-|~|∼|～|–|—|부터)", normalized)
    )

    if has_range and len(day_tokens) >= 2:
        day_keys = list(OPERATION_DAY_CODES)
        start_index = day_keys.index(day_tokens[0])
        end_index = day_keys.index(day_tokens[1])
        expanded = []
        index = start_index

        while True:
            expanded.append(
                OPERATION_DAY_CODES[day_keys[index]]
            )

            if index == end_index:
                break

            index = (index + 1) % len(day_keys)

        return expanded

    unique_days = []

    for day_token in day_tokens:
        day_code = OPERATION_DAY_CODES[day_token]

        if day_code not in unique_days:
            unique_days.append(day_code)

    return unique_days


def _normalize_operation_time(match, prefix: str):
    """정규식 시간 그룹을 HH:MM으로 변환한다."""

    hour = int(match.group(f"{prefix}_hour"))
    minute_text = (
        match.group(f"{prefix}_minute")
        or match.group(f"{prefix}_korean_minute")
        or "0"
    )
    minute = int(minute_text)
    ampm = match.group(f"{prefix}_ampm")

    if minute > 59:
        return None

    if ampm:
        if hour < 1 or hour > 12:
            return None

        if ampm == "오전":
            hour = 0 if hour == 12 else hour
        else:
            hour = 12 if hour == 12 else hour + 12

    elif hour > 24 or (hour == 24 and minute != 0):
        return None

    return f"{hour:02d}:{minute:02d}"


def _time_to_minutes(value: str):
    hour, minute = value.split(":")
    return int(hour) * 60 + int(minute)


def _extract_operation_time_ranges(text: str):
    """안전하게 해석 가능한 시작~종료 시간만 반환한다."""

    ranges = []
    rejected_count = 0

    for match in _TIME_RANGE_PATTERN.finditer(text):
        opening_time = _normalize_operation_time(
            match,
            "open",
        )
        closing_time = _normalize_operation_time(
            match,
            "close",
        )

        # "오전 9시~6시"처럼 뒤쪽 오전/오후가 생략된
        # 12시간제 표현은 임의로 추측하지 않는다.
        if (
            match.group("open_ampm")
            and not match.group("close_ampm")
            and int(match.group("close_hour")) <= 12
        ):
            rejected_count += 1
            continue

        if opening_time is None or closing_time is None:
            rejected_count += 1
            continue

        # 자정을 넘기는 운영시간은 현재 목표 구조만으로 종료일을
        # 표현할 수 없으므로 원문만 보존한다.
        if _time_to_minutes(closing_time) <= _time_to_minutes(
            opening_time
        ):
            rejected_count += 1
            continue

        ranges.append((opening_time, closing_time))

    return ranges, rejected_count


def _extract_operation_time_ranges_with_breaks(text: str):
    """휴게시간을 운영시간으로 잘못 넣지 않고 운영 구간을 나눈다."""

    ranges, rejected_count = _extract_operation_time_ranges(text)
    break_ranges = []

    for match in _BREAK_TIME_RANGE_PATTERN.finditer(text):
        opening_time = _normalize_operation_time(
            match,
            "break_open",
        )
        closing_time = _normalize_operation_time(
            match,
            "break_close",
        )

        if (
            opening_time is None
            or closing_time is None
            or _time_to_minutes(closing_time)
            <= _time_to_minutes(opening_time)
        ):
            rejected_count += 1
            continue

        break_ranges.append((opening_time, closing_time))

    if not break_ranges:
        return ranges, rejected_count

    # 전체 운영시간 안에 포함된 휴게시간만 닫힌 구간으로 해석한다.
    opening_ranges = [
        item
        for item in ranges
        if item not in break_ranges
    ]

    for break_open, break_close in break_ranges:
        split_ranges = []

        for opening_time, closing_time in opening_ranges:
            if (
                _time_to_minutes(opening_time)
                < _time_to_minutes(break_open)
                < _time_to_minutes(break_close)
                < _time_to_minutes(closing_time)
            ):
                split_ranges.extend([
                    (opening_time, break_open),
                    (break_close, closing_time),
                ])
            else:
                split_ranges.append(
                    (opening_time, closing_time)
                )

        opening_ranges = split_ranges

    return opening_ranges, rejected_count


def _is_specific_date_day_match(text: str, day_match):
    """9.2(수)처럼 특정 날짜에 붙은 요일인지 확인한다."""

    prefix = text[max(0, day_match.start() - 24):day_match.start()]

    return bool(
        re.search(
            r"\d{1,2}\s*[./-]\s*\d{1,2}\s*\($",
            prefix,
        )
    )


def _operation_days_except(excluded_days):
    excluded = set(excluded_days)
    return [
        day
        for day in OPERATION_ALL_DAYS
        if day not in excluded
    ]


def _has_nonweekly_operation_variants(text: str):
    """현재 요일 스키마로 안전하게 표현할 수 없는 변형인지 확인한다."""

    normalized = re.sub(r"\s+", "", text).lower()

    if "동절기" in normalized:
        return True

    if (
        "주간" in normalized
        and "야간" in normalized
        and "전환" in normalized
    ):
        return True

    if re.search(
        r"\[\d{1,2}-\d{1,2}월\]",
        normalized,
    ):
        return True

    # 전시 자체는 상시 운영이고 프로그램 시간만 따로 적힌 경우,
    # 프로그램 시간을 장소 운영시간으로 사용하지 않는다.
    if (
        "[전시]" in normalized
        and "[프로그램]" in normalized
        and "상시운영" in normalized
    ):
        return True

    return False


def parse_operation_hours(value: str | None):
    """
    서울문화행사 PRO_TIME을 요일별 운영시간으로 변환한다.

    확실하게 해석할 수 없는 내용은 추측하지 않고 원문과
    parsed/partial/unparsed/missing 상태로 남긴다.
    """

    raw_blocks = _operation_hours_raw_blocks(value)

    if not raw_blocks:
        return {
            "raw_text": None,
            "raw_blocks": [],
            "schedule": [],
            "status": "missing",
        }

    raw_text = str(value).strip()
    parse_text = unicodedata.normalize("NFKC", raw_text)

    if _has_nonweekly_operation_variants(parse_text):
        return {
            "raw_text": raw_text,
            "raw_blocks": raw_blocks,
            "schedule": [],
            "status": "unparsed",
        }

    all_day_matches = list(
        _DAY_EXPRESSION_PATTERN.finditer(parse_text)
    )
    specific_date_day_ignored = any(
        _is_specific_date_day_match(parse_text, day_match)
        for day_match in all_day_matches
    )
    day_matches = [
        day_match
        for day_match in all_day_matches
        if not _is_specific_date_day_match(
            parse_text,
            day_match,
        )
    ]
    schedule = []
    unresolved_segment = False
    rejected_range_count = 0

    for index, day_match in enumerate(day_matches):
        segment_end = (
            day_matches[index + 1].start()
            if index + 1 < len(day_matches)
            else len(parse_text)
        )
        segment = parse_text[day_match.start():segment_end]
        days = _expand_operation_days(day_match.group())

        if not days:
            unresolved_segment = True
            continue

        is_closed = any(
            signal in segment
            for signal in _CLOSED_SIGNALS
        )

        if is_closed:
            # "10:00~18:00, 일요일 휴관"처럼 운영시간이 먼저
            # 나오고 첫 요일 정보가 휴무일인 경우, 명시된 휴무일을
            # 제외한 요일에 앞쪽 운영시간을 연결한다.
            if index == 0 and not schedule:
                prefix_ranges, prefix_rejected = (
                    _extract_operation_time_ranges_with_breaks(
                        parse_text[:day_match.start()]
                    )
                )
                rejected_range_count += prefix_rejected
                open_days = _operation_days_except(days)

                for opening_time, closing_time in prefix_ranges:
                    if open_days:
                        schedule.append({
                            "days": open_days,
                            "opening_time": opening_time,
                            "closing_time": closing_time,
                            "closed": False,
                        })

            # "월요일 휴무, 12:00~19:00"처럼 시간이 휴무
            # 표현 뒤에 오는 경우에도 나머지 요일에 연결한다.
            suffix_ranges, suffix_rejected = (
                _extract_operation_time_ranges_with_breaks(
                    segment[day_match.end() - day_match.start():]
                )
            )
            rejected_range_count += suffix_rejected
            open_days = _operation_days_except(days)

            for opening_time, closing_time in suffix_ranges:
                if open_days:
                    schedule.append({
                        "days": open_days,
                        "opening_time": opening_time,
                        "closing_time": closing_time,
                        "closed": False,
                    })

            schedule.append({
                "days": days,
                "opening_time": None,
                "closing_time": None,
                "closed": True,
            })
            continue

        time_ranges, rejected_count = (
            _extract_operation_time_ranges_with_breaks(segment)
        )
        rejected_range_count += rejected_count

        # "10:00~18:00, 매일"처럼 시간이 요일보다 먼저
        # 나온 경우 첫 요일 표현에만 앞쪽 시간을 연결한다.
        if not time_ranges and index == 0:
            prefix_ranges, prefix_rejected = (
                _extract_operation_time_ranges_with_breaks(
                    parse_text[:day_match.start()]
                )
            )
            time_ranges = prefix_ranges
            rejected_range_count += prefix_rejected

        if not time_ranges:
            closing_match = _CLOSING_TIME_OVERRIDE_PATTERN.search(
                segment
            )

            if closing_match:
                closing_time = _normalize_operation_time(
                    closing_match,
                    "override_close",
                )
                base_item = next(
                    (
                        item
                        for item in reversed(schedule)
                        if not item["closed"]
                        and any(
                            day in item["days"]
                            for day in days
                        )
                    ),
                    None,
                )

                if closing_time is not None and base_item:
                    opening_time = base_item["opening_time"]

                    if (
                        _time_to_minutes(closing_time)
                        > _time_to_minutes(opening_time)
                    ):
                        for item in schedule:
                            if not item["closed"]:
                                item["days"] = [
                                    day
                                    for day in item["days"]
                                    if day not in days
                                ]

                        schedule.append({
                            "days": days,
                            "opening_time": opening_time,
                            "closing_time": closing_time,
                            "closed": False,
                        })
                        continue

            unresolved_segment = True
            continue

        for opening_time, closing_time in time_ranges:
            schedule.append({
                "days": days,
                "opening_time": opening_time,
                "closing_time": closing_time,
                "closed": False,
            })

    closed_days = {
        day
        for item in schedule
        if item["closed"]
        for day in item["days"]
    }
    cleaned_schedule = []

    for item in schedule:
        cleaned_item = dict(item)

        if not cleaned_item["closed"]:
            cleaned_item["days"] = [
                day
                for day in cleaned_item["days"]
                if day not in closed_days
            ]

            if not cleaned_item["days"]:
                continue

        if cleaned_item not in cleaned_schedule:
            cleaned_schedule.append(cleaned_item)

    has_partial_signal = any(
        signal in parse_text
        for signal in _PARTIAL_OPERATION_SIGNALS
    )

    if not cleaned_schedule:
        status = "unparsed"
    elif (
        unresolved_segment
        or rejected_range_count > 0
        or has_partial_signal
        or specific_date_day_ignored
        or not any(
            not item["closed"]
            for item in cleaned_schedule
        )
    ):
        status = "partial"
    else:
        status = "parsed"

    return {
        "raw_text": raw_text,
        "raw_blocks": raw_blocks,
        "schedule": cleaned_schedule,
        "status": status,
    }


def normalize_seoul_culture_event(
    event: dict,
    reference_date: date | datetime | None = None,
    only_active: bool = True,
    require_seoul_coordinate: bool = True,
):
    """
    서울 문화행사 한 건을 기존 Kakao/Tour 장소 dict와
    호환되는 내부 장소 형식으로 변환한다.

    사용할 수 없는 데이터는 None을 반환한다.
    """

    exclusion_reason = get_event_exclusion_reason(
        event,
        reference_date=reference_date,
        only_active=only_active,
        require_seoul_coordinate=(
            require_seoul_coordinate
        ),
    )

    if exclusion_reason is not None:
        return None

    name = str(event.get("TITLE") or "").strip()

    latitude = _parse_coordinate(event.get("LAT"))
    longitude = _parse_coordinate(event.get("LOT"))

    start_date = parse_event_date(
        event.get("STRTDATE")
    )
    end_date = parse_event_date(
        event.get("END_DATE")
    )
    venue_name = str(
        event.get("PLACE") or ""
    ).strip() or None

    description_parts = [
        str(event.get("PROGRAM") or "").strip(),
        str(event.get("ETC_DESC") or "").strip(),
    ]
    description = "\n".join(
        part
        for part in description_parts
        if part
    ) or None
    fee_detail = (
        str(event.get("USE_FEE") or "").strip()
        or None
    )
    operation_hours = parse_operation_hours(
        event.get("PRO_TIME")
    )

    return {
        # 기존 Kakao/Tour 공통 필드
        "source": "seoul_culture",
        "source_id": _extract_source_id(event),
        "name": name,
        "latitude": latitude,
        "longitude": longitude,
        "category": "culture",
        "category_detail": event.get("CODENAME"),
        "address": venue_name,
        "distance_m": None,

        # 전시/축제 추천에 필요한 추가 필드
        "venue_name": venue_name,
        "district": (
            str(event.get("GUNAME") or "").strip()
            or None
        ),
        "start_at": (
            start_date.isoformat()
            if start_date
            else None
        ),
        "end_at": (
            end_date.isoformat()
            if end_date
            else None
        ),
        # opening_hours는 기존 연결부와의 호환을 위해 유지한다.
        "opening_hours": operation_hours["raw_text"],
        "operation_hours_raw": operation_hours["raw_blocks"],
        "operation_schedule": operation_hours["schedule"],
        "operation_schedule_status": operation_hours["status"],
        "is_free": _normalize_is_free(
            event.get("IS_FREE")
        ),
        "price_text": fee_detail,
        "fee_detail": fee_detail,
        "image_url": event.get("MAIN_IMG") or None,
        "detail_url": event.get("HMPG_ADDR") or None,
        "official_url": event.get("ORG_LINK") or None,
        "organizer": event.get("ORG_NAME") or None,
        "target_audience": event.get("USE_TRGT") or None,
        "description": description,
        "inquiry": event.get("INQUIRY") or None,
    }


def normalize_seoul_culture_events(
    events: list[dict],
    reference_date: date | datetime | None = None,
    only_active: bool = True,
    require_seoul_coordinate: bool = True,
):
    """문화행사 목록을 정규화하고 처리 건수를 함께 반환한다."""

    normalized_places = []
    excluded_count = 0
    excluded_by_reason = {}

    for event in events:
        exclusion_reason = get_event_exclusion_reason(
            event,
            reference_date=reference_date,
            only_active=only_active,
            require_seoul_coordinate=(
                require_seoul_coordinate
            ),
        )

        if exclusion_reason is not None:
            excluded_count += 1
            excluded_by_reason[exclusion_reason] = (
                excluded_by_reason.get(
                    exclusion_reason,
                    0,
                )
                + 1
            )
            continue

        place = normalize_seoul_culture_event(
            event,
            reference_date=reference_date,
            only_active=only_active,
            require_seoul_coordinate=(
                require_seoul_coordinate
            ),
        )

        if place is None:
            excluded_count += 1
            excluded_by_reason["normalization_failed"] = (
                excluded_by_reason.get(
                    "normalization_failed",
                    0,
                )
                + 1
            )
            continue

        normalized_places.append(place)

    return {
        "places": normalized_places,
        "input_count": len(events),
        "included_count": len(normalized_places),
        "excluded_count": excluded_count,
        "excluded_by_reason": excluded_by_reason,
    }


def calculate_distance_m(
    latitude1: float,
    longitude1: float,
    latitude2: float,
    longitude2: float,
):
    """두 좌표 사이의 Haversine 직선거리를 m 단위로 계산한다."""

    earth_radius_m = 6371000.0

    lat1 = math.radians(latitude1)
    lon1 = math.radians(longitude1)
    lat2 = math.radians(latitude2)
    lon2 = math.radians(longitude2)

    delta_lat = lat2 - lat1
    delta_lon = lon2 - lon1

    haversine_value = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1)
        * math.cos(lat2)
        * math.sin(delta_lon / 2) ** 2
    )

    central_angle = 2 * math.atan2(
        math.sqrt(haversine_value),
        math.sqrt(1 - haversine_value),
    )

    return round(earth_radius_m * central_angle)


def get_current_seoul_culture_report(
    reference_date: date | datetime | None = None,
    api_key: str | None = None,
):
    """전시/축제 수집 결과와 제외 사유별 건수를 반환한다."""

    events = fetch_recommendable_seoul_culture_events(
        api_key=api_key,
    )

    return normalize_seoul_culture_events(
        events,
        reference_date=reference_date,
        only_active=True,
        require_seoul_coordinate=True,
    )


def get_current_seoul_culture_places(
    reference_date: date | datetime | None = None,
    api_key: str | None = None,
):
    """현재 진행 중인 서울 전시/축제 후보를 반환한다."""

    result = get_current_seoul_culture_report(
        reference_date=reference_date,
        api_key=api_key,
    )

    return result["places"]


def get_nearby_current_seoul_culture_places(
    latitude: float,
    longitude: float,
    max_distance_m: int = 2000,
    reference_date: date | datetime | None = None,
    api_key: str | None = None,
):
    """현재 진행 중인 전시/축제 중 반경 안의 후보를 반환한다."""

    places = get_current_seoul_culture_places(
        reference_date=reference_date,
        api_key=api_key,
    )
    nearby_places = []

    for place in places:
        distance_m = calculate_distance_m(
            latitude1=latitude,
            longitude1=longitude,
            latitude2=place["latitude"],
            longitude2=place["longitude"],
        )

        if distance_m > max_distance_m:
            continue

        nearby_place = place.copy()
        nearby_place["distance_m"] = distance_m
        nearby_places.append(nearby_place)

    return sorted(
        nearby_places,
        key=lambda place: place["distance_m"],
    )


def get_current_seoul_exhibitions(
    reference_date: date | datetime | None = None,
    api_key: str | None = None,
):
    """기존 추천 연결부와의 호환을 위해 유지하는 함수다."""

    return get_current_seoul_culture_places(
        reference_date=reference_date,
        api_key=api_key,
    )


def get_nearby_current_exhibitions(
    latitude: float,
    longitude: float,
    max_distance_m: int = 2000,
    reference_date: date | datetime | None = None,
    api_key: str | None = None,
):
    """기존 추천 연결부와의 호환을 위해 유지하는 함수다."""

    return get_nearby_current_seoul_culture_places(
        latitude=latitude,
        longitude=longitude,
        max_distance_m=max_distance_m,
        reference_date=reference_date,
        api_key=api_key,
    )
