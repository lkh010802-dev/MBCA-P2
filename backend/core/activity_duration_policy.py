# 활동별 최소·기본·최대 체류시간 기준. 별도 지정이 없으면 default 값을 코스 계산에 사용한다.
ACTIVITY_DURATION_POLICIES = {
    "food": {"min": 50, "default": 60, "max": 70},
    "cafe": {"min": 30, "default": 45, "max": 60},
    "walk": {"min": 30, "default": 45, "max": 60},
    "culture": {"min": 60, "default": 90, "max": 120},
    "entertainment": {"min": 60, "default": 90, "max": 120},
    "shopping": {"min": 45, "default": 60, "max": 75},
    "drink": {"min": 75, "default": 90, "max": 120},
}


def get_activity_duration_policy(activity: str) -> dict[str, int]:
    try:
        return ACTIVITY_DURATION_POLICIES[activity].copy()
    except KeyError as error:
        raise ValueError(f"지원하지 않는 activity입니다: {activity}") from error


def determine_stay_duration(
    activity: str,
    specified_duration_minutes: int | None = None,
) -> int:
    # 사용자가 체류시간을 직접 지정한 경우 우선 사용하고, 없으면 활동별 기본값을 적용한다.
    policy = get_activity_duration_policy(activity)
    return (
        specified_duration_minutes
        if specified_duration_minutes is not None
        else policy["default"]
    )
