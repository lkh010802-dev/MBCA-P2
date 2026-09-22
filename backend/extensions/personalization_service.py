"""행동 이력을 보조 선호도로 바꾸는 작은 집계 계층.

명시적으로 저장한 선호도가 항상 우선이며, 이 모듈의 결과는 사용자가
선호를 지정하지 않은 활동을 정렬할 때만 사용한다.
"""

from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from db_models import UserInteraction


EVENT_WEIGHTS = {
    "place_view": 0.25,
    "place_select": 2.0,
    "favorite": 5.0,
    "hide": -5.0,
    "course_confirm": 4.0,
    "course_open": 2.0,
}


def day_part(hour: int) -> str:
    if hour < 11:
        return "morning"
    if hour < 15:
        return "lunch"
    if hour < 18:
        return "afternoon"
    if hour < 22:
        return "evening"
    return "night"


def _levels(scores: dict[str, float]) -> dict[str, int]:
    """점수가 충분한 활동만 4~5 선호도로 승격해 과학습을 막는다."""
    if not scores:
        return {}
    maximum = max(scores.values(), default=0)
    if maximum <= 0:
        return {}
    return {
        activity: 5 if score >= maximum * 0.75 else 4
        for activity, score in scores.items()
        if score >= 2
    }


def build_personalization_profile(db: Session, user_id: int) -> dict:
    interactions = list(
        db.scalars(
            select(UserInteraction)
            .where(UserInteraction.user_id == user_id)
            .order_by(UserInteraction.created_at.desc(), UserInteraction.id.desc())
            .limit(500)
        )
    )
    activity_scores = defaultdict(float)
    context_scores = defaultdict(lambda: defaultdict(float))
    for item in interactions:
        if not item.category:
            continue
        weight = EVENT_WEIGHTS.get(item.event_type, 0)
        activity_scores[item.category] += weight
        if item.context_hour is not None and item.context_day:
            key = f"{item.context_day}:{day_part(item.context_hour)}"
            context_scores[key][item.category] += weight
    return {
        "activity_preferences": _levels(dict(activity_scores)),
        "context_activity_preferences": {
            key: _levels(dict(scores)) for key, scores in context_scores.items()
        },
        "interaction_count": len(interactions),
    }


def current_context_key(now: datetime | None = None) -> str:
    # 운영 서버는 UTC여도 추천 시간대는 사용자의 서비스 지역(서울)을 따른다.
    current = now or datetime.now(ZoneInfo("Asia/Seoul"))
    day = "weekend" if current.weekday() >= 5 else "weekday"
    return f"{day}:{day_part(current.hour)}"


def merge_behavior_preferences(explicit: dict | None, profile: dict) -> dict:
    """현재 시간대 행동값을 적용하되 사용자가 고른 값은 절대 덮지 않는다."""
    merged = dict(explicit or {})
    learned = dict(profile.get("activity_preferences") or {})
    learned.update(
        profile.get("context_activity_preferences", {}).get(
            current_context_key(),
            {},
        )
    )
    for activity, level in learned.items():
        merged.setdefault(activity, level)
    return merged

