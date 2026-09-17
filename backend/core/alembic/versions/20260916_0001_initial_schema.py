"""Create the current KOALA user and preference schema."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "20260916_0001"
down_revision = None
branch_labels = None
depends_on = None

_timestamp = sa.text("CURRENT_TIMESTAMP")
_timestamp_on_update = sa.text(
    "CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"
)


def _timestamps():
    return (
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=_timestamp,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=_timestamp_on_update,
        ),
    )


def upgrade():
    op.create_table(
        "users",
        sa.Column(
            "id",
            mysql.BIGINT(unsigned=True),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("nickname", sa.String(50), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email", name="email"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_table(
        "activity_categories",
        sa.Column(
            "id",
            mysql.BIGINT(unsigned=True),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("code", sa.String(30), nullable=False),
        sa.Column("name", sa.String(50), nullable=False),
        sa.Column(
            "is_active",
            mysql.TINYINT(display_width=1),
            nullable=False,
            server_default=sa.text("1"),
        ),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="code"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_table(
        "user_preferences",
        sa.Column(
            "id",
            mysql.BIGINT(unsigned=True),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("user_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("space_preference", sa.String(20), nullable=True),
        sa.Column("transport_mode", sa.String(30), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_user_preferences_user",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="user_id"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_table(
        "user_activity_preferences",
        sa.Column(
            "id",
            mysql.BIGINT(unsigned=True),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("user_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("activity_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column(
            "preference_level",
            mysql.TINYINT(unsigned=True),
            nullable=False,
        ),
        *_timestamps(),
        sa.CheckConstraint(
            "preference_level BETWEEN 1 AND 5",
            name="chk_preference_level",
        ),
        sa.ForeignKeyConstraint(
            ["activity_id"],
            ["activity_categories.id"],
            name="fk_user_activity_preferences_activity",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_user_activity_preferences_user",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "activity_id",
            name="uq_user_activity",
        ),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )


def downgrade():
    op.drop_table("user_activity_preferences")
    op.drop_table("user_preferences")
    op.drop_table("activity_categories")
    op.drop_table("users")
