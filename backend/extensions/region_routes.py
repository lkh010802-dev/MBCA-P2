"""로그인 사용자의 명시적·행동 기반 선호를 지역 추천에 연결한다.

동일한 이름의 Core 라우터를 Extensions 경로에서 Override한다. 원형 Core를
수정하지 않아 백엔드 업데이트 시 충돌 범위를 이 파일 하나로 제한한다.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from auth_routes import get_optional_current_user
from database import get_db
from db_models import User
from models import RecommendRequest
from personalization_service import (
    build_personalization_profile,
    merge_behavior_preferences,
)
from preference_routes import load_recommendation_preferences


def create_region_router(recommend_handler):
    router = APIRouter()

    @router.post("/recommend")
    def recommend_endpoint(
        request: RecommendRequest,
        user: User | None = Depends(get_optional_current_user),
        db: Session = Depends(get_db),
    ):
        stored_preferences = None
        if user is not None:
            try:
                stored_preferences = load_recommendation_preferences(db, user.id) or {}
                profile = build_personalization_profile(db, user.id)
                # 체크박스로 고른 명시적 취향이 행동 추론보다 항상 우선한다.
                stored_preferences["activity_preferences"] = (
                    merge_behavior_preferences(
                        stored_preferences.get("activity_preferences"),
                        profile,
                    )
                )
            except SQLAlchemyError:
                # 개인화 저장소 장애가 핵심 추천 자체를 중단시키면 안 된다.
                db.rollback()
                stored_preferences = None

        return recommend_handler(request, stored_preferences=stored_preferences)

    return router

