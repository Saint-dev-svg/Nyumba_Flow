"""PostgreSQL integration coverage for the invoice-purpose migration."""

import importlib.util
import uuid
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from extensions import db
from test_config import create_test_app


MIGRATION_PATH = (
    Path(__file__).parent
    / "migrations"
    / "versions"
    / "b7d4a1c3e902_add_invoice_purpose.py"
)
SPEC = importlib.util.spec_from_file_location("invoice_purpose_migration", MIGRATION_PATH)
INVOICE_PURPOSE_MIGRATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INVOICE_PURPOSE_MIGRATION)


@pytest.fixture
def migration_schema():
    """Use a disposable schema isolated from application and dev data."""
    app = create_test_app()
    schema = f"invoice_migration_test_{uuid.uuid4().hex}"
    with app.app_context():
        engine = db.engine
        with engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        try:
            yield engine, schema
        finally:
            with engine.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()


def run_migration(connection, migration):
    with Operations.context(MigrationContext.configure(connection)):
        migration()


def test_invoice_purpose_upgrade_backfill_coexistence_and_safe_downgrade(
    migration_schema,
):
    engine, schema = migration_schema
    with engine.begin() as connection:
        connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
        connection.execute(text("""
            CREATE TABLE invoices (
                id INTEGER PRIMARY KEY,
                lease_id INTEGER NOT NULL,
                period_start DATE NOT NULL,
                period_end DATE NOT NULL,
                due_date DATE NOT NULL,
                status VARCHAR(20) NOT NULL,
                issued_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL,
                CONSTRAINT uq_invoice_lease_period
                    UNIQUE (lease_id, period_start, period_end)
            )
        """))
        connection.execute(text("""
            CREATE TABLE charges (
                id INTEGER PRIMARY KEY,
                invoice_id INTEGER NOT NULL REFERENCES invoices(id),
                category VARCHAR(20) NOT NULL
            )
        """))
        connection.execute(text("""
            INSERT INTO invoices
                (id, lease_id, period_start, period_end, due_date, status, created_at)
            VALUES
                (1, 11, '2026-01-01', '2026-01-31', '2026-01-01', 'issued', now()),
                (2, 12, '2026-01-01', '2026-01-31', '2026-01-01', 'draft', now()),
                (3, 13, '2026-01-01', '2026-01-31', '2026-01-01', 'draft', now()),
                (4, 14, '2026-01-01', '2026-01-31', '2026-01-01', 'draft', now())
        """))
        connection.execute(text("""
            INSERT INTO charges (id, invoice_id, category)
            VALUES (1, 1, 'rent'), (2, 1, 'rent'), (3, 2, 'utilities'),
                   (4, 3, 'rent'), (5, 3, 'utilities')
        """))

        # This exercises the migration against the prior invoice schema and
        # backfills single-purpose, mixed-purpose, and empty invoices.
        run_migration(connection, INVOICE_PURPOSE_MIGRATION.upgrade)
        purposes = dict(connection.execute(text(
            "SELECT id, purpose FROM invoices ORDER BY id"
        )).all())
        assert purposes == {1: "rent", 2: "utilities", 3: "other", 4: "other"}

        # The upgraded constraint allows rent and utilities for the same
        # lease and period, while rejecting another invoice of either purpose.
        connection.execute(text("""
            INSERT INTO invoices
                (id, lease_id, period_start, period_end, due_date, status, created_at, purpose)
            VALUES
                (5, 15, '2026-02-01', '2026-02-28', '2026-02-01', 'draft', now(), 'rent'),
                (6, 15, '2026-02-01', '2026-02-28', '2026-02-01', 'draft', now(), 'utilities')
        """))
        with pytest.raises(IntegrityError):
            with connection.begin_nested():
                connection.execute(text("""
                    INSERT INTO invoices
                        (id, lease_id, period_start, period_end, due_date, status, created_at, purpose)
                    VALUES
                        (7, 15, '2026-02-01', '2026-02-28', '2026-02-01', 'draft', now(), 'rent')
                """))

        with pytest.raises(RuntimeError, match="Cannot downgrade invoice purpose"):
            run_migration(connection, INVOICE_PURPOSE_MIGRATION.downgrade)

        # The guard runs before schema changes; invoice records and the new
        # purpose column/constraint remain available after refusal.
        assert connection.execute(text(
            "SELECT COUNT(*) FROM invoices WHERE lease_id = 15"
        )).scalar_one() == 2
        assert connection.execute(text(
            "SELECT purpose FROM invoices WHERE id = 6"
        )).scalar_one() == "utilities"
        assert connection.execute(text("""
            SELECT COUNT(*) FROM information_schema.columns
             WHERE table_schema = :schema AND table_name = 'invoices'
               AND column_name = 'purpose'
        """), {"schema": schema}).scalar_one() == 1
