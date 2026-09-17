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
    policy = get_activity_duration_policy(activity)
    return (
        specified_duration_minutes
        if specified_duration_minutes is not None
        else policy["default"]
    )
