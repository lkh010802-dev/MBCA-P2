from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from auth_routes import get_current_user
from database import get_db
from db_models import (
    ActivityCategory,
    User,
    UserActivityPreference,
    UserPreference,
)
from models import UserPreferencesResponse, UserPreferencesUpdateRequest


router = APIRouter()
ACTIVITY_ORDER = (
    "food",
    "cafe",
    "walk",
    "culture",
    "entertainment",
    "shopping",
    "drink",
)


def load_recommendation_preferences(db: Session, user_id: int) -> dict:
    preferences = db.scalar(
        select(UserPreference).where(UserPreference.user_id == user_id)
    )
    activity_rows = db.execute(
        select(UserActivityPreference, ActivityCategory.code)
        .join(
            ActivityCategory,
            UserActivityPreference.activity_id == ActivityCategory.id,
        )
        .where(
            UserActivityPreference.user_id == user_id,
            ActivityCategory.is_active.is_(True),
        )
    ).all()
    activity_rows.sort(key=lambda row: ACTIVITY_ORDER.index(row[1]))

    return {
        "space_preference": (
            preferences.space_preference if preferences is not None else None
        ),
        "transport_mode": (
            preferences.transport_mode if preferences is not None else None
        ),
        "activity_preferences": {
            code: activity.preference_level
            for activity, code in activity_rows
        },
    }


def _read_preferences(db: Session, user_id: int) -> UserPreferencesResponse:
    preferences = load_recommendation_preferences(db, user_id)

    return UserPreferencesResponse(
        space_preference=preferences["space_preference"],
        transport_mode=preferences["transport_mode"],
        activity_preferences=[
            {
                "activity": code,
                "preference_level": level,
            }
            for code, level in preferences["activity_preferences"].items()
        ],
    )


@router.get(
    "/users/me/preferences",
    response_model=UserPreferencesResponse,
)
def get_preferences(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _read_preferences(db, user.id)


@router.put(
    "/users/me/preferences",
    response_model=UserPreferencesResponse,
)
def update_preferences(
    request: UserPreferencesUpdateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        requested_codes = [
            item.activity for item in request.activity_preferences
        ]
        categories = (
            db.scalars(
                select(ActivityCategory).where(
                    ActivityCategory.code.in_(requested_codes)
                )
            ).all()
            if requested_codes
            else []
        )
        categories_by_code = {category.code: category for category in categories}
        if any(
            code not in categories_by_code
            or not categories_by_code[code].is_active
            for code in requested_codes
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="사용할 수 없는 활동 카테고리입니다.",
            )

        basic_fields = {"space_preference", "transport_mode"}
        if request.model_fields_set & basic_fields:
            preferences = db.scalar(
                select(UserPreference).where(UserPreference.user_id == user.id)
            )
            if preferences is None:
                preferences = UserPreference(user_id=user.id)
                db.add(preferences)
            for field in request.model_fields_set & basic_fields:
                setattr(preferences, field, getattr(request, field))

        if requested_codes:
            activity_ids = [categories_by_code[code].id for code in requested_codes]
            existing = db.scalars(
                select(UserActivityPreference).where(
                    UserActivityPreference.user_id == user.id,
                    UserActivityPreference.activity_id.in_(activity_ids),
                )
            ).all()
            existing_by_activity_id = {
                item.activity_id: item for item in existing
            }
            for item in request.activity_preferences:
                category = categories_by_code[item.activity]
                preference = existing_by_activity_id.get(category.id)
                if preference is None:
                    db.add(
                        UserActivityPreference(
                            user_id=user.id,
                            activity_id=category.id,
                            preference_level=item.preference_level,
                        )
                    )
                else:
                    preference.preference_level = item.preference_level

        db.commit()
    except SQLAlchemyError as error:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="취향 정보를 저장하지 못했습니다.",
        ) from error

    return _read_preferences(db, user.id)
