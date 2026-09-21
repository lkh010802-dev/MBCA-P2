from fastapi import APIRouter, Depends
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from auth_routes import get_optional_current_user
from database import get_db
from db_models import User
from models import RecommendRequest
from preference_routes import load_recommendation_preferences


# 지역 추천 핵심 함수를 주입받아 라우터와 서비스 계층의 결합도를 낮춘다.
def create_region_router(recommend_handler):
    router = APIRouter()

    @router.post("/recommend")
    def recommend_endpoint(
        request: RecommendRequest,
        user: User | None = Depends(get_optional_current_user),
        db: Session = Depends(get_db),
    ):
        # 비로그인 사용자는 저장 취향 없이 추천하고, 로그인 사용자만 DB 취향을 불러온다.
        stored_preferences = None
        if user is not None:
            try:
                stored_preferences = load_recommendation_preferences(
                    db,
                    user.id,
                )
            except SQLAlchemyError:
                # 취향 조회 실패가 전체 추천 실패로 번지지 않도록 롤백 후 기본 추천을 계속한다.
                db.rollback()

        return recommend_handler(
            request,
            stored_preferences=stored_preferences,
        )

    return router
