from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from models import RecommendRequest, StructuredConditions


TIME_PERIOD_RANGES = {
    "morning": (6 * 60, 11 * 60),
    "lunch": (11 * 60, 15 * 60),
    "evening": (18 * 60, 24 * 60),
    "am": (6 * 60, 12 * 60),
    "pm": (12 * 60, 22 * 60),
}


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
    3. 둘 다 없는 경우 → missing
    """

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
    conditions: StructuredConditions,
    current_datetime: datetime | None = None,
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

    now = (
        current_datetime or datetime.now(ZoneInfo("Asia/Seoul"))
    ).astimezone(ZoneInfo("Asia/Seoul"))

    if conditions.start_time_period is not None:
        period_start, period_end = TIME_PERIOD_RANGES[
            conditions.start_time_period
        ]
        current_minutes = now.hour * 60 + now.minute

        if current_minutes < period_start:
            return {
                "source": "period",
                "start_time": f"{period_start // 60:02d}:00",
            }

        if current_minutes < period_end:
            return {
                "source": "period",
                "start_time": now.strftime("%H:%M"),
            }

    # 별도 시작시간이 없거나 오늘의 시간대가 이미 지났으면 현재 시간 사용
    current_time = now.strftime("%H:%M")

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
    end_time: dict,
    current_datetime: datetime | None = None,
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

    now = (
        current_datetime or datetime.now(ZoneInfo("Asia/Seoul"))
    ).astimezone(ZoneInfo("Asia/Seoul"))

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
