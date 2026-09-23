"""Create durable plan records with ownership, leases and workflow version.

Revision ID: 0001_plan_ownership
Revises:
Create Date: 2026-09-23
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0001_plan_ownership"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "trip_plans" not in inspector.get_table_names():
        op.create_table(
            "trip_plans",
            sa.Column("id", sa.String(length=32), primary_key=True),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("request_json", sa.Text(), nullable=False),
            sa.Column("plan_json", sa.Text(), nullable=True),
            sa.Column("error_code", sa.String(length=64), nullable=True),
            sa.Column("owner_token_hash", sa.String(length=64), nullable=True),
            sa.Column("lease_owner", sa.String(length=32), nullable=True),
            sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
            sa.Column(
                "workflow_version",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("1"),
            ),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_trip_plans_status", "trip_plans", ["status"])
        op.create_index("ix_trip_plans_updated_at", "trip_plans", ["updated_at"])
        return

    columns = {column["name"] for column in inspector.get_columns("trip_plans")}
    additions = (
        ("owner_token_hash", sa.Column("owner_token_hash", sa.String(length=64), nullable=True)),
        ("lease_owner", sa.Column("lease_owner", sa.String(length=32), nullable=True)),
        ("lease_expires_at", sa.Column("lease_expires_at", sa.DateTime(), nullable=True)),
        (
            "workflow_version",
            sa.Column(
                "workflow_version",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("1"),
            ),
        ),
    )
    for name, column in additions:
        if name not in columns:
            op.add_column("trip_plans", column)

    indexes = {index["name"] for index in inspector.get_indexes("trip_plans")}
    if "ix_trip_plans_status" not in indexes:
        op.create_index("ix_trip_plans_status", "trip_plans", ["status"])
    if "ix_trip_plans_updated_at" not in indexes:
        op.create_index("ix_trip_plans_updated_at", "trip_plans", ["updated_at"])


def downgrade() -> None:
    op.drop_table("trip_plans")
