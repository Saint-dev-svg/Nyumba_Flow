"""add payment allocation idempotency records

Revision ID: 8a6e2d4c1f90
Revises: 3d7c2a91e4bf
Create Date: 2026-11-04

"""
from alembic import op
import sqlalchemy as sa


revision = "8a6e2d4c1f90"
down_revision = "3d7c2a91e4bf"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "payment_allocation_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("payment_id", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("response_payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["payment_id"],
            ["payments.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "payment_id",
            "idempotency_key",
            name="uq_payment_allocation_request_key",
        ),
    )
    op.create_index(
        op.f("ix_payment_allocation_requests_payment_id"),
        "payment_allocation_requests",
        ["payment_id"],
        unique=False,
    )


def downgrade():
    op.drop_index(
        op.f("ix_payment_allocation_requests_payment_id"),
        table_name="payment_allocation_requests",
    )
    op.drop_table("payment_allocation_requests")
