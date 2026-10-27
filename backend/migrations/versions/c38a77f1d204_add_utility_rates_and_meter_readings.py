"""add property utility pricing and monthly meter readings

Revision ID: c38a77f1d204
Revises: b7d4a1c3e902
Create Date: 2026-10-27

"""
from alembic import op
import sqlalchemy as sa


revision = "c38a77f1d204"
down_revision = "b7d4a1c3e902"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "property_utility_settings",
        sa.Column("property_id", sa.Integer(), nullable=False),
        sa.Column("water_rate", sa.Numeric(12, 2), nullable=False),
        sa.Column("garbage_fee", sa.Numeric(12, 2), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "water_rate >= 0",
            name="ck_utility_settings_water_rate_nonnegative",
        ),
        sa.CheckConstraint(
            "garbage_fee >= 0",
            name="ck_utility_settings_garbage_fee_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["property_id"], ["properties.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("property_id"),
    )
    op.execute("""
        INSERT INTO property_utility_settings (property_id, water_rate, garbage_fee)
        SELECT id, 180.00, 300.00 FROM properties
        ON CONFLICT (property_id) DO NOTHING
    """)

    op.create_table(
        "water_meter_readings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("unit_id", sa.Integer(), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("previous_reading", sa.Numeric(14, 3), nullable=False),
        sa.Column("current_reading", sa.Numeric(14, 3), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "period_end >= period_start", name="ck_water_reading_period_dates"
        ),
        sa.CheckConstraint(
            "previous_reading >= 0",
            name="ck_water_reading_previous_nonnegative",
        ),
        sa.CheckConstraint(
            "current_reading >= 0",
            name="ck_water_reading_current_nonnegative",
        ),
        sa.CheckConstraint(
            "current_reading >= previous_reading",
            name="ck_water_reading_not_decreasing",
        ),
        sa.ForeignKeyConstraint(["unit_id"], ["units.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "unit_id", "period_start", "period_end",
            name="uq_water_reading_unit_period",
        ),
    )
    op.create_index(
        op.f("ix_water_meter_readings_unit_id"),
        "water_meter_readings",
        ["unit_id"],
        unique=False,
    )


def downgrade():
    op.drop_index(op.f("ix_water_meter_readings_unit_id"), table_name="water_meter_readings")
    op.drop_table("water_meter_readings")
    op.drop_table("property_utility_settings")
