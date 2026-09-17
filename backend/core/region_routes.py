from fastapi import APIRouter, Depends
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from auth_routes import get_optional_current_user
from database import get_db
from db_models import User
from models import RecommendRequest
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
                stored_preferences = load_recommendation_preferences(
                    db,
                    user.id,
                )
            except SQLAlchemyError:
                db.rollback()

        return recommend_handler(
            request,
            stored_preferences=stored_preferences,
        )

    return router
