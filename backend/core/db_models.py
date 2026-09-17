from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.mysql import BIGINT, TINYINT
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


# 모든 SQLAlchemy DB 모델이 공통으로 상속받을 기본 클래스
class Base(DeclarativeBase):
    pass


# users 테이블과 연결되는 SQLAlchemy 모델
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True),
        primary_key=True,
        autoincrement=True,
    )

    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
    )

    password_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    nickname: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    created_at: Mapped[DateTime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.current_timestamp(),
    )

    updated_at: Mapped[DateTime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.current_timestamp(),
        server_onupdate=func.current_timestamp(),
    )


class UserPreference(Base):
    __tablename__ = "user_preferences"

    id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True),
        primary_key=True,
        autoincrement=True,
    )

    user_id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )

    space_preference: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
    )

    transport_mode: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
    )

    created_at: Mapped[DateTime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.current_timestamp(),
    )

    updated_at: Mapped[DateTime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.current_timestamp(),
        server_onupdate=func.current_timestamp(),
    )

class ActivityCategory(Base):
    __tablename__ = "activity_categories"

    id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True),
        primary_key=True,
        autoincrement=True,
    )

    code: Mapped[str] = mapped_column(
        String(30),
        unique=True,
        nullable=False,
    )

    name: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    is_active: Mapped[bool] = mapped_column(
        nullable=False,
        server_default="1",
    )

    created_at: Mapped[DateTime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.current_timestamp(),
    )

    updated_at: Mapped[DateTime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.current_timestamp(),
        server_onupdate=func.current_timestamp(),
    )


class UserActivityPreference(Base):
    
    __tablename__ = "user_activity_preferences"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "activity_id",
            name="uq_user_activity",
        ),
        CheckConstraint(
            "preference_level BETWEEN 1 AND 5",
            name="chk_preference_level",
        ),
    )    
    id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True),
        primary_key=True,
        autoincrement=True,
    )

    user_id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    activity_id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True),
        ForeignKey("activity_categories.id", ondelete="RESTRICT"),
        nullable=False,
    )

    preference_level: Mapped[int] = mapped_column(
    TINYINT(unsigned=True),
    nullable=False,
)
    created_at: Mapped[DateTime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.current_timestamp(),
    )

    updated_at: Mapped[DateTime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.current_timestamp(),
        server_onupdate=func.current_timestamp(),
    )

    