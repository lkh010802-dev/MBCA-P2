"""Authenticated user data APIs owned by the extension layer.

The upstream backend stays untouched.  Tables introduced by this layer are
created lazily with ``checkfirst`` so an existing development database can run
the feature without a separate destructive migration step.
"""

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from auth_routes import get_current_user
from database import engine, get_db
from db_models import ExcludedPlace, FavoritePlace, SavedCourse, User, UserInteraction
from models import (
    ExcludedPlaceCreate,
    ExcludedPlaceResponse,
    FavoritePlaceCreate,
    FavoritePlaceResponse,
    PersonalizationProfileResponse,
    SavedCourseCreate,
    SavedCourseResponse,
    UserInteractionCreate,
)
from personalization_service import build_personalization_profile


router = APIRouter()


def ensure_user_data_tables() -> None:
    """Create extension-owned tables before requests begin."""
    SavedCourse.__table__.create(bind=engine, checkfirst=True)
    ExcludedPlace.__table__.create(bind=engine, checkfirst=True)
    FavoritePlace.__table__.create(bind=engine, checkfirst=True)
    UserInteraction.__table__.create(bind=engine, checkfirst=True)


@router.post(
    "/users/me/courses",
    response_model=SavedCourseResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_saved_course(
    request: SavedCourseCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    course = SavedCourse(user_id=user.id, **request.model_dump())
    db.add(course)
    db.commit()
    db.refresh(course)
    return course


@router.get("/users/me/courses", response_model=list[SavedCourseResponse])
def list_saved_courses(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list(
        db.scalars(
            select(SavedCourse)
            .where(SavedCourse.user_id == user.id)
            .order_by(SavedCourse.created_at.desc(), SavedCourse.id.desc())
            .limit(30)
        )
    )


@router.delete(
    "/users/me/courses/{course_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_saved_course(
    course_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    course = db.scalar(
        select(SavedCourse).where(
            SavedCourse.id == course_id,
            SavedCourse.user_id == user.id,
        )
    )
    if course is None:
        raise HTTPException(status_code=404, detail="저장한 코스를 찾지 못했어요.")
    db.delete(course)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/users/me/excluded-places", response_model=list[ExcludedPlaceResponse])
def list_excluded_places(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list(
        db.scalars(
            select(ExcludedPlace)
            .where(ExcludedPlace.user_id == user.id)
            .order_by(ExcludedPlace.created_at.desc(), ExcludedPlace.id.desc())
            .limit(200)
        )
    )


@router.post(
    "/users/me/excluded-places",
    response_model=ExcludedPlaceResponse,
    status_code=status.HTTP_201_CREATED,
)
def exclude_place(
    request: ExcludedPlaceCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    existing = db.scalar(
        select(ExcludedPlace).where(
            ExcludedPlace.user_id == user.id,
            ExcludedPlace.place_key == request.place_key,
        )
    )
    if existing is not None:
        return existing
    item = ExcludedPlace(user_id=user.id, **request.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.delete(
    "/users/me/excluded-places/{place_key}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def restore_excluded_place(
    place_key: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item = db.scalar(
        select(ExcludedPlace).where(
            ExcludedPlace.user_id == user.id,
            ExcludedPlace.place_key == place_key,
        )
    )
    if item is not None:
        db.delete(item)
        db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/users/me/favorite-places", response_model=list[FavoritePlaceResponse])
def list_favorite_places(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list(
        db.scalars(
            select(FavoritePlace)
            .where(FavoritePlace.user_id == user.id)
            .order_by(FavoritePlace.created_at.desc(), FavoritePlace.id.desc())
            .limit(200)
        )
    )


@router.post(
    "/users/me/favorite-places",
    response_model=FavoritePlaceResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_favorite_place(
    request: FavoritePlaceCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # 중복 클릭은 새 행을 만들지 않고 저장된 스냅샷만 최신 정보로 갱신한다.
    item = db.scalar(
        select(FavoritePlace).where(
            FavoritePlace.user_id == user.id,
            FavoritePlace.place_key == request.place_key,
        )
    )
    if item is None:
        item = FavoritePlace(user_id=user.id, **request.model_dump())
        db.add(item)
    else:
        item.place_name = request.place_name
        item.category = request.category
        item.place_data = request.place_data
    db.commit()
    db.refresh(item)
    return item


@router.delete(
    "/users/me/favorite-places/{place_key}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_favorite_place(
    place_key: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item = db.scalar(
        select(FavoritePlace).where(
            FavoritePlace.user_id == user.id,
            FavoritePlace.place_key == place_key,
        )
    )
    if item is not None:
        db.delete(item)
        db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/users/me/interactions", status_code=status.HTTP_204_NO_CONTENT)
def record_user_interaction(
    request: UserInteractionCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    db.add(UserInteraction(user_id=user.id, **request.model_dump()))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/users/me/personalization",
    response_model=PersonalizationProfileResponse,
)
def read_personalization_profile(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return build_personalization_profile(db, user.id)
