"""add property PayBill channels and Daraja callback inbox

Revision ID: 3d7c2a91e4bf
Revises: b55e9612ce8c
Create Date: 2026-11-06 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "3d7c2a91e4bf"
down_revision = "b55e9612ce8c"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "property_paybill_configurations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("property_id", sa.Integer(), nullable=False),
        sa.Column("business_shortcode", sa.String(length=20), nullable=False),
        sa.Column(
            "account_reference_type",
            sa.String(length=20),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.CheckConstraint(
            "account_reference_type = 'unit_number'",
            name="ck_paybill_account_reference_type",
        ),
        sa.ForeignKeyConstraint(
            ["property_id"],
            ["properties.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "business_shortcode",
            name="uq_property_paybill_shortcode",
        ),
    )
    op.create_index(
        "ix_property_paybill_configurations_property_id",
        "property_paybill_configurations",
        ["property_id"],
        unique=False,
    )
    op.create_index(
        "uq_paybill_active_property",
        "property_paybill_configurations",
        ["property_id"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )

    op.create_table(
        "mpesa_callback_transactions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("paybill_configuration_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=30), nullable=False),
        sa.Column("provider_transaction_id", sa.String(length=100), nullable=True),
        sa.Column("business_shortcode", sa.String(length=20), nullable=True),
        sa.Column("account_reference", sa.String(length=100), nullable=True),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column(
            "provider_transaction_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("processing_status", sa.String(length=20), nullable=False),
        sa.Column("property_id", sa.Integer(), nullable=True),
        sa.Column("unit_id", sa.Integer(), nullable=True),
        sa.Column("lease_id", sa.Integer(), nullable=True),
        sa.Column("exception_reason", sa.Text(), nullable=True),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "processing_status IN ('received', 'matched', 'exception', 'processed')",
            name="ck_mpesa_callback_processing_status",
        ),
        sa.CheckConstraint(
            "amount IS NULL OR amount > 0",
            name="ck_mpesa_callback_amount_positive",
        ),
        sa.CheckConstraint(
            "currency IS NULL OR length(currency) = 3",
            name="ck_mpesa_callback_currency_length",
        ),
        sa.ForeignKeyConstraint(
            ["paybill_configuration_id"],
            ["property_paybill_configurations.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["property_id"],
            ["properties.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["unit_id"],
            ["units.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["lease_id"],
            ["leases.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider",
            "provider_transaction_id",
            name="uq_mpesa_callback_provider_transaction",
        ),
    )
    op.create_index(
        "ix_mpesa_callback_transactions_paybill_configuration_id",
        "mpesa_callback_transactions",
        ["paybill_configuration_id"],
        unique=False,
    )
    op.create_index(
        "ix_mpesa_callback_transactions_property_id",
        "mpesa_callback_transactions",
        ["property_id"],
        unique=False,
    )
    op.create_index(
        "ix_mpesa_callback_transactions_unit_id",
        "mpesa_callback_transactions",
        ["unit_id"],
        unique=False,
    )
    op.create_index(
        "ix_mpesa_callback_transactions_lease_id",
        "mpesa_callback_transactions",
        ["lease_id"],
        unique=False,
    )
    op.create_index(
        "ix_mpesa_callback_status_received",
        "mpesa_callback_transactions",
        ["processing_status", "received_at"],
        unique=False,
    )


def downgrade():
    op.drop_index(
        "ix_mpesa_callback_status_received",
        table_name="mpesa_callback_transactions",
    )
    op.drop_index(
        "ix_mpesa_callback_transactions_lease_id",
        table_name="mpesa_callback_transactions",
    )
    op.drop_index(
        "ix_mpesa_callback_transactions_unit_id",
        table_name="mpesa_callback_transactions",
    )
    op.drop_index(
        "ix_mpesa_callback_transactions_property_id",
        table_name="mpesa_callback_transactions",
    )
    op.drop_index(
        "ix_mpesa_callback_transactions_paybill_configuration_id",
        table_name="mpesa_callback_transactions",
    )
    op.drop_table("mpesa_callback_transactions")
    op.drop_index(
        "uq_paybill_active_property",
        table_name="property_paybill_configurations",
    )
    op.drop_index(
        "ix_property_paybill_configurations_property_id",
        table_name="property_paybill_configurations",
    )
    op.drop_table("property_paybill_configurations")
