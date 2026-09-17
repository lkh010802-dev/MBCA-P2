from datetime import datetime, timedelta
import re
from zoneinfo import ZoneInfo

from models import RecommendRequest, StructuredConditions


def extract_explicit_current_location(user_message: str | None):
    """LLM이 놓친 현재·미래의 명시적 출발지를 보수적으로 복구한다."""
    if not user_message:
        return None
    normalized = " ".join(user_message.strip().split())
    generic_location_words = {"위치", "현재위치", "주변", "근처", "여기"}
    patterns = (
        r"^([가-힣A-Za-z0-9·._-]+(?:역|터미널|공항|공원|광장|시장|백화점|대학교|대학|병원|동|구))\s*(?:인데|이고)",
        r"(?:지금|현재)\s+([가-힣A-Za-z0-9·._-]+(?:역|터미널|공항|공원|광장|시장|백화점|대학교|대학|병원|동|구))\s*(?:인데|이고|에서|이야|입니다|예요|에 있어|에 있음)",
        r"(?:지금|현재)\s+([가-힣A-Za-z0-9·._-]{2,20})\s*(?:인데|이고|에서|이야|입니다|예요|에 있어|에 있음)",
        r"([가-힣A-Za-z0-9·._-]+(?:역|터미널|공항|공원|광장|시장|백화점|대학교|대학|병원|동|구))\s*(?:에|에서)\s*있(?:을|는|어|습니다|음)(?:\s*거|\s*꺼|거|꺼)?(?:야|예요|에요|입니다)?",
    )
    for pattern in patterns:
        match = re.search(pattern, normalized)
        if match:
            location = match.group(1).strip()
            # "현재 위치에서"는 장소명이 아니라 GPS 사용 지시다. 넓은 보정식이
            # 이를 문자 그대로 "위치"라는 장소로 복구하지 않도록 제외한다.
            if location in generic_location_words:
                continue
            return location
    return None


def extract_explicit_activity_location(user_message: str | None):
    """'신림역에서 쉬고 싶다'처럼 활동이 벌어질 지역을 복구한다."""
    if not user_message:
        return None
    normalized = " ".join(user_message.strip().split())
    match = re.search(
        r"(?:^|\s)([가-힣A-Za-z0-9·._-]+(?:역|터미널|공항|공원|광장|시장|백화점|대학교|대학|병원|동|구))에서\s+.*(?:쉬|먹|마시|보|놀|걷|산책|카페|전시|문화)",
        normalized,
    )
    return match.group(1).strip() if match else None


def extract_explicit_end_location(user_message: str | None):
    """'8시까지 신림 가기 전에'처럼 원문에 직접 쓴 다음 목적지를 복구한다."""
    if not user_message:
        return None
    normalized = " ".join(user_message.strip().split())
    patterns = (
        r"(?:\d{1,2}\s*시(?:\s*\d{1,2}\s*분)?까지\s+)([가-힣A-Za-z0-9·._-]{2,20}(?:역|터미널|공항|공원|광장|시장|백화점|대학교|대학|병원|동|구)?)\s*(?:에|으로)?\s*(?:가|도착)(?:기|해야|려고)",
        r"([가-힣A-Za-z0-9·._-]{2,20}(?:역|터미널|공항|공원|광장|시장|백화점|대학교|대학|병원|동|구)?)\s*(?:에|으로)?\s*(?:가|도착)기\s*전에",
    )
    for pattern in patterns:
        match = re.search(pattern, normalized)
        if match:
            return match.group(1).strip()
    return None


def extract_explicit_duration_minutes(user_message: str | None):
    """LLM이 놓친 '한 3시간?', '2시간 정도' 같은 총 여유시간을 복구한다."""
    if not user_message:
        return None
    normalized = " ".join(user_message.strip().split())
    word_numbers = {"한": 1, "두": 2, "세": 3, "네": 4}
    hour_match = re.search(r"(?:한\s*)?(\d{1,2}|한|두|세|네)\s*시간", normalized)
    minute_match = re.search(r"(\d{1,3})\s*분(?:\s*(?:정도|쯤|가량))?", normalized)
    if not hour_match and not minute_match:
        return None
    hours = 0
    if hour_match:
        raw_hours = hour_match.group(1)
        hours = word_numbers.get(raw_hours, int(raw_hours) if raw_hours.isdigit() else 0)
    minutes = int(minute_match.group(1)) if minute_match else 0
    total = hours * 60 + minutes
    return total if 0 < total <= 24 * 60 else None


def infer_activity_sequence(user_message: str | None, activities: list[str] | None):
    """LLM 결과와 원문을 병합해 순서가 필요한 활동 계획을 만든다."""
    normalized = " ".join((user_message or "").strip().split())
    resolved = list(dict.fromkeys(activities or []))
    if not normalized:
        return resolved

    culture_focused = bool(re.search(
        r"(?:전시(?:회)?|미술관|박물관|갤러리|공연|문화생활|문화s*활동)",
        normalized,
    ))
    explicit_food = bool(re.search(r"(?:밥|식사|맛집|먹(?:고|기|을|으))", normalized))
    explicit_cafe = bool(re.search(r"(?:카페|커피|차\s*마시|디저트)", normalized))
    explicit_walk = bool(re.search(r"(?:산책|걷고|걷기|걸으)", normalized))

    # 전시가 핵심인 문장을 LLM이 '나들이'로 넓혀 식당·카페를 같은 비중으로
    # 반환하더라도 사용자가 직접 말하지 않은 보조 활동은 제거한다.
    if culture_focused:
        resolved = ["culture"]
        if explicit_cafe:
            resolved.append("cafe")
        if explicit_walk:
            resolved.append("walk")
        if explicit_food:
            resolved.append("food")

    meal_then_rest = bool(re.search(
        r"(?:밥|식사|음식|맛집|먹).{0,20}(?:먹고|먹은\s*(?:후|뒤)|후|뒤|다음|나서|고).{0,20}(?:쉬|휴식|카페|커피)",
        normalized,
    ))
    explicitly_rejects_cafe = bool(re.search(
        r"(?:카페|커피).{0,8}(?:싫|안\s*가|제외|말고)",
        normalized,
    ))
    rests_elsewhere = bool(re.search(
        r"(?:집|숙소|호텔).{0,8}(?:에서|가서).{0,8}(?:쉬|휴식)",
        normalized,
    ))

    if meal_then_rest and not explicitly_rejects_cafe and not rests_elsewhere:
        if "food" not in resolved:
            resolved.insert(0, "food")
        if "cafe" not in resolved:
            food_index = resolved.index("food")
            resolved.insert(food_index + 1, "cafe")

    # 문장에 두 가지 이상의 활동을 직접 적었다면 LLM의 배열 순서보다
    # 사용자가 말한 순서를 우선한다. 예: "카페 갔다가 전시"는 cafe → culture.
    activity_patterns = {
        "food": r"(?:밥|식사|맛집|먹)",
        "cafe": r"(?:카페|커피|디저트)",
        "culture": r"(?:전시(?:회)?|미술관|박물관|갤러리|공연|문화생활|문화\s*활동)",
        "walk": r"(?:산책|걷고|걷기|걸으)",
        "entertainment": r"(?:놀거리|놀고|게임|오락)",
        "shopping": r"(?:쇼핑|구경)",
        "drink": r"(?:술|맥주|와인|바\b)",
    }
    mentioned = []
    for activity, pattern in activity_patterns.items():
        match = re.search(pattern, normalized)
        if match and activity in resolved:
            mentioned.append((match.start(), activity))
    if len(mentioned) >= 2:
        ordered = [activity for _, activity in sorted(mentioned)]
        resolved = ordered + [activity for activity in resolved if activity not in ordered]
    return resolved


def requests_nearby(user_message: str | None) -> bool:
    """사용자가 이동 부담이 작은 주변 탐색을 명시했는지 반환한다."""
    return bool(re.search(
        r"(?:이\s*주변|주변|근처|가까운\s*곳|멀리\s*말고)",
        user_message or "",
    ))


def allows_mountain_activity(user_message: str | None, activities: list[str] | None) -> bool:
    """산·정상 후보는 사용자가 등산 의도를 직접 보인 경우에만 허용한다."""
    return bool(re.search(
        r"(?:등산|산행|트레킹|정상|관악산|북한산|남산\s*오르)",
        user_message or "",
    )) or "hiking" in (activities or [])


# 1. 실제 추천 계산에 사용할 시작 위치 결정
def resolve_start_location(
    request: RecommendRequest,
    conditions: StructuredConditions
):
    """
    추천이 시작되는 위치를 결정한다.

    우선순위:
    1. 사용자가 별도의 시작 위치를 말한 경우 → 해당 위치 사용
    2. 별도 시작 위치가 없고 GPS가 있는 경우 → 현재 GPS 사용
    3. GPS가 없지만 활동 지역이 명시된 경우 → 활동 지역에서 시작
    4. 모두 없는 경우 → missing
    """

    # 구조화 결과보다 원문에 명시된 현재 장소를 먼저 복구한다. 기존 프롬프트가
    # "지금 X"를 GPS 표현으로 보아 null을 반환해도 GPS 없는 요청이 실패하지 않는다.
    # 원문에 "지금 신림역인데"처럼 명시된 장소가 있으면 LLM이 다른 역을
    # 구조화했거나 GPS가 부정확하더라도 사용자의 직접 표현을 최우선으로 쓴다.
    # "신림역에서 쉬고 싶다"는 활동 목적지 표현이다. GPS가 있으면 실제
    # 출발지는 GPS로 유지하고, 신림역은 target_location으로 넘긴다.
    activity_location = extract_explicit_activity_location(request.user_message)
    if activity_location is not None and request.gps_latitude is not None and request.gps_longitude is not None:
        return {
            "source": "gps",
            "location_text": None,
            "latitude": request.gps_latitude,
            "longitude": request.gps_longitude,
        }

    explicit_location = extract_explicit_current_location(request.user_message)
    if explicit_location is not None:
        return {
            "source": "text",
            "location_text": explicit_location,
            "latitude": None,
            "longitude": None,
        }

    # 사용자가 별도의 시작 위치를 말한 경우
    if conditions.start_location_text is not None:
        return {
            "source": "text",
            "location_text": conditions.start_location_text,
            "latitude": None,
            "longitude": None
        }

    # 별도 시작 위치가 없고 GPS가 있는 경우
    if (
        request.gps_latitude is not None
        and request.gps_longitude is not None
    ):
        return {
            "source": "gps",
            "location_text": None,
            "latitude": request.gps_latitude,
            "longitude": request.gps_longitude
        }

    # "신림역에서 3시간 전시회 보고 싶어"처럼 활동 지역만 명시된
    # 요청은 그 지역에 도착해 있다고 보는 것이 자연스럽다. GPS가 없을 때만
    # target을 시작 기준으로 재사용하며, GPS가 있으면 실제 현재 위치를 우선한다.
    if conditions.target_location_text is not None:
        return {
            "source": "text",
            "location_text": conditions.target_location_text,
            "latitude": None,
            "longitude": None,
            "derived_from_target": True,
        }

    # 시작 위치를 판단할 수 없는 경우
    return {
        "source": "missing",
        "location_text": None,
        "latitude": None,
        "longitude": None
    }
# 2. 사용자가 실제로 활동하고 싶은 목적 지역 결정
def resolve_target_location(
    conditions: StructuredConditions
):
    """
    사용자가 이번 추천 활동을 하고 싶다고 지정한 지역을 결정한다.

    예:
    "오늘 강남에서 2~3시간 놀 거야"
    → target_location_text = "강남"

    "홍대에서 놀다가 7시에 잠실 가야 해"
    → target_location_text = "홍대"

    사용자가 활동 지역을 따로 지정하지 않았다면
    target_location은 없는 것으로 처리한다.
    """

    # 사용자가 활동할 지역을 직접 지정한 경우
    if conditions.target_location_text is not None:
        return {
            "source": "text",
            "location_text": conditions.target_location_text,
            "latitude": None,
            "longitude": None
        }

    # 활동 지역을 따로 지정하지 않은 경우
    return {
        "source": "missing",
        "location_text": None,
        "latitude": None,
        "longitude": None
    }

# 3. 추천 계산에 사용할 시작시간 결정
def resolve_start_time(
    conditions: StructuredConditions
):
    """
    사용자가 시작시간을 직접 말하면 해당 시간을 사용하고,
    별도 시작시간이 없으면 현재 한국 시간을 사용한다.
    """

    # 사용자가 시작시간을 직접 말한 경우
    if conditions.start_time is not None:
        return {
            "source": "text",
            "start_time": conditions.start_time
        }

    # 별도 시작시간이 없으면 현재 한국 시간 사용
    current_time = datetime.now(
        ZoneInfo("Asia/Seoul")
    ).strftime("%H:%M")

    return {
        "source": "current",
        "start_time": current_time
    }


# 4. 다음 일정 위치 결정
def resolve_end_location(
    conditions: StructuredConditions
):
    """
    사용자가 다음 일정 위치를 말한 경우 해당 위치를 사용한다.

    다음 일정이 없는 사용자를 허용하기 위해
    종료 위치는 필수값으로 두지 않는다.
    """

    # 다음 일정 위치를 사용자가 말한 경우
    if conditions.end_location_text is not None:
        return {
            "source": "text",
            "location_text": conditions.end_location_text,
            "latitude": None,
            "longitude": None
        }

    # 다음 일정 위치가 없는 경우
    return {
        "source": "none",
        "location_text": None,
        "latitude": None,
        "longitude": None
    }


# 5. 종료시간 또는 다음 일정시간 결정
def resolve_end_time(
    conditions: StructuredConditions
):
    """
    사용자가 종료시간 또는 다음 일정시간을 말한 경우
    해당 시간을 사용한다.

    종료시간이 없는 사용자도 추천 요청이 가능하다.
    """

    if conditions.end_time is not None:
        return {
            "source": "text",
            "end_time": conditions.end_time
        }

    return {
        "source": "none",
        "end_time": None
    }


# 6. HH:MM 형태의 시간을 실제 datetime으로 변환
def resolve_datetimes(
    start_time: dict,
    end_time: dict
):
    """
    시작시간과 종료시간을 실제 datetime 객체로 변환한다.

    날짜는 현재 한국 날짜를 기준으로 사용한다.

    예:
    17:00 → 오늘 17:00
    21:00 → 오늘 21:00

    종료시간이 시작시간보다 같거나 이른 경우에는
    자정을 넘긴 일정으로 보고 종료 날짜를 다음 날로 처리한다.

    예:
    시작 23:00
    종료 01:00

    → 오늘 23:00 ~ 다음 날 01:00
    """

    now = datetime.now(
        ZoneInfo("Asia/Seoul")
    )

    # 시작시간을 오늘 날짜의 datetime으로 변환
    start_datetime = datetime.strptime(
        start_time["start_time"],
        "%H:%M"
    ).replace(
        year=now.year,
        month=now.month,
        day=now.day,
        tzinfo=ZoneInfo("Asia/Seoul")
    )

    # 종료시간이 없는 경우
    if end_time["end_time"] is None:
        return {
            "start_datetime": start_datetime,
            "end_datetime": None
        }

    # 종료시간을 오늘 날짜의 datetime으로 변환
    end_datetime = datetime.strptime(
        end_time["end_time"],
        "%H:%M"
    ).replace(
        year=now.year,
        month=now.month,
        day=now.day,
        tzinfo=ZoneInfo("Asia/Seoul")
    )

    # 종료시간이 시작시간보다 같거나 이르면
    # 자정을 넘어간 것으로 처리
    if end_datetime <= start_datetime:
        end_datetime += timedelta(days=1)

    return {
        "start_datetime": start_datetime,
        "end_datetime": end_datetime
    }


# 7. 사용 가능한 전체 시간 계산
def calculate_time_window(
    resolved_datetimes: dict
):
    """
    시작시간부터 종료시간까지의 전체 가용시간을
    분 단위로 계산한다.

    예:
    17:00 ~ 21:00
    → 240분

    종료시간이 없으면 전체 시간창을 계산할 수 없으므로
    None을 반환한다.
    """

    start_datetime = resolved_datetimes[
        "start_datetime"
    ]

    end_datetime = resolved_datetimes[
        "end_datetime"
    ]

    # 종료시간이 없는 경우
    if end_datetime is None:
        return {
            "time_window_minutes": None
        }

    # 시작시간부터 종료시간까지의 전체 시간 계산
    time_window_minutes = int(
        (
            end_datetime
            - start_datetime
        ).total_seconds()
        / 60
    )

    return {
        "time_window_minutes":
            time_window_minutes
    }

def calculate_candidate_arrival_time(
    start_datetime,
    travel_minutes
):
    return start_datetime + timedelta(minutes=travel_minutes)
