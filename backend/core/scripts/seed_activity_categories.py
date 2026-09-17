from sqlalchemy import select
from sqlalchemy.orm import Session

from database import SessionLocal
from db_models import ActivityCategory


ACTIVITY_CATEGORIES = (
    ("food", "음식"),
    ("cafe", "카페"),
    ("walk", "산책"),
    ("culture", "문화"),
    ("entertainment", "놀거리"),
    ("shopping", "쇼핑"),
    ("drink", "술"),
)


def seed_activity_categories(db: Session):
    codes = [code for code, _ in ACTIVITY_CATEGORIES]
    existing = {
        category.code: category
        for category in db.scalars(
            select(ActivityCategory).where(ActivityCategory.code.in_(codes))
        ).all()
    }

    for code, name in ACTIVITY_CATEGORIES:
        category = existing.get(code)
        if category is None:
            db.add(ActivityCategory(code=code, name=name, is_active=True))
        else:
            category.name = name
            category.is_active = True

    db.commit()


def main():
    with SessionLocal() as db:
        try:
            seed_activity_categories(db)
        except Exception:
            db.rollback()
            raise
    print("activity_categories seed 완료")


if __name__ == "__main__":
    main()
