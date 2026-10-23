"""add tenant ownership

Revision ID: 6ebecef30ed7
Revises: 921e8f93e165
"""

from alembic import op
import sqlalchemy as sa


revision = "6ebecef30ed7"
down_revision = "921e8f93e165"
branch_labels = None
depends_on = None


def upgrade():
    # Add the column as nullable so existing records remain valid.
    with op.batch_alter_table("tenants") as batch_op:
        batch_op.add_column(
            sa.Column("owner_id", sa.Integer(), nullable=True)
        )

    # Backfill existing tenants using their lease -> unit -> property
    # relationships. A tenant with leases owned by multiple landlords
    # cannot be assigned automatically without an explicit business rule.
    connection = op.get_bind()

    conflicting_tenants = connection.execute(
        sa.text("""
            SELECT t.id
            FROM tenants AS t
            JOIN leases AS l ON l.tenant_id = t.id
            JOIN units AS u ON u.id = l.unit_id
            JOIN properties AS p ON p.id = u.property_id
            GROUP BY t.id
            HAVING COUNT(DISTINCT p.owner_id) > 1
        """)
    ).fetchall()

    if conflicting_tenants:
        raise RuntimeError(
            "Some tenants have leases under multiple landlords. "
            "Resolve their ownership before applying this migration. "
            f"Tenant IDs: {[row[0] for row in conflicting_tenants]}"
        )

    connection.execute(
        sa.text("""
            UPDATE tenants AS t
            SET owner_id = (
                SELECT p.owner_id
                FROM leases AS l
                JOIN units AS u ON u.id = l.unit_id
                JOIN properties AS p ON p.id = u.property_id
                WHERE l.tenant_id = t.id
                LIMIT 1
            )
        """)
    )

    # Existing tenants without leases cannot be assigned automatically.
    unassigned_tenants = connection.execute(
        sa.text("SELECT id FROM tenants WHERE owner_id IS NULL")
    ).fetchall()

    if unassigned_tenants:
        raise RuntimeError(
            "Some tenants have no lease and cannot be assigned "
            "automatically. Assign an owner before retrying. "
            f"Tenant IDs: {[row[0] for row in unassigned_tenants]}"
        )

    with op.batch_alter_table("tenants") as batch_op:
        batch_op.alter_column(
            "owner_id",
            existing_type=sa.Integer(),
            nullable=False,
        )
        batch_op.create_index(
            "ix_tenants_owner_id",
            ["owner_id"],
            unique=False,
        )
        batch_op.create_foreign_key(
            "fk_tenants_owner_id_users",
            "users",
            ["owner_id"],
            ["id"],
            ondelete="CASCADE",
        )


def downgrade():
    with op.batch_alter_table("tenants") as batch_op:
        batch_op.drop_constraint(
            "fk_tenants_owner_id_users",
            type_="foreignkey",
        )
        batch_op.drop_index("ix_tenants_owner_id")
        batch_op.drop_column("owner_id")