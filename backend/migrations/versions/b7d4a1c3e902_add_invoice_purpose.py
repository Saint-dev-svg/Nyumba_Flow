"""add invoice purpose and scope billing-period uniqueness

Revision ID: b7d4a1c3e902
Revises: f02e0fa5f956
Create Date: 2026-10-27

"""
from alembic import op
import sqlalchemy as sa


revision = "b7d4a1c3e902"
down_revision = "f02e0fa5f956"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("invoices", sa.Column("purpose", sa.String(length=20), nullable=True))
    op.execute("""
        UPDATE invoices AS invoice
           SET purpose = CASE
               WHEN (SELECT COUNT(DISTINCT charge.category)
                       FROM charges AS charge
                      WHERE charge.invoice_id = invoice.id) = 1
                AND EXISTS (SELECT 1 FROM charges AS charge
                             WHERE charge.invoice_id = invoice.id
                               AND charge.category = 'rent')
                   THEN 'rent'
               WHEN (SELECT COUNT(DISTINCT charge.category)
                       FROM charges AS charge
                      WHERE charge.invoice_id = invoice.id) = 1
                AND EXISTS (SELECT 1 FROM charges AS charge
                             WHERE charge.invoice_id = invoice.id
                               AND charge.category = 'utilities')
                   THEN 'utilities'
               ELSE 'other'
           END
    """)
    op.alter_column("invoices", "purpose", nullable=False)
    op.drop_constraint("uq_invoice_lease_period", "invoices", type_="unique")
    op.create_check_constraint(
        "ck_invoice_purpose",
        "invoices",
        "purpose IN ('rent', 'utilities', 'other')",
    )
    op.create_unique_constraint(
        "uq_invoice_lease_period_purpose",
        "invoices",
        ["lease_id", "period_start", "period_end", "purpose"],
    )


def downgrade():
    connection = op.get_bind()
    # Keep writes from introducing a conflict between this check and the
    # schema change. Downgrades should run with the application stopped, but
    # the table lock also makes the preflight safe if a writer is still active.
    connection.execute(sa.text("LOCK TABLE invoices IN ACCESS EXCLUSIVE MODE"))
    coexistence = connection.execute(sa.text("""
        SELECT lease_id, period_start, period_end
          FROM invoices
         GROUP BY lease_id, period_start, period_end
        HAVING COUNT(*) > 1
         LIMIT 1
    """)).first()
    if coexistence is not None:
        raise RuntimeError(
            "Cannot downgrade invoice purpose while multiple invoices exist "
            "for the same lease and billing period. The downgrade would need "
            "to delete, merge, or reclassify valid invoice records. Keep this "
            "migration applied and back up the database before attempting "
            "any manual rollback."
        )

    op.drop_constraint("uq_invoice_lease_period_purpose", "invoices", type_="unique")
    op.drop_constraint("ck_invoice_purpose", "invoices", type_="check")
    op.drop_column("invoices", "purpose")
    op.create_unique_constraint(
        "uq_invoice_lease_period",
        "invoices",
        ["lease_id", "period_start", "period_end"],
    )
