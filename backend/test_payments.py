import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from decimal import Decimal
from threading import Barrier
from time import monotonic, sleep

import pytest
from flask_jwt_extended import create_access_token
from sqlalchemy import text

from extensions import db
from models import (
    Charge,
    Invoice,
    Lease,
    Payment,
    PaymentAllocation,
    Property,
    Receipt,
    Tenant,
    Unit,
    User,
    UtilityBreakdown,
)
from test_config import create_test_app


@pytest.fixture
def app():
    return create_test_app()


@pytest.fixture
def cleanup_records(app):
    records = {
        "users": set(),
        "tenants": set(),
        "properties": set(),
        "units": set(),
        "leases": set(),
        "invoices": set(),
        "payments": set(),
    }
    yield records

    with app.app_context():
        if records["payments"]:
            PaymentAllocation.query.filter(
                PaymentAllocation.payment_id.in_(records["payments"])
            ).delete(synchronize_session=False)
            Receipt.query.filter(
                Receipt.payment_id.in_(records["payments"])
            ).delete(synchronize_session=False)
            Payment.query.filter(
                Payment.id.in_(records["payments"])
            ).delete(synchronize_session=False)
        if records["invoices"]:
            charge_ids = db.session.query(Charge.id).filter(
                Charge.invoice_id.in_(records["invoices"])
            )
            UtilityBreakdown.query.filter(
                UtilityBreakdown.charge_id.in_(charge_ids)
            ).delete(synchronize_session=False)
            Charge.query.filter(
                Charge.invoice_id.in_(records["invoices"])
            ).delete(synchronize_session=False)
            Invoice.query.filter(
                Invoice.id.in_(records["invoices"])
            ).delete(synchronize_session=False)
        if records["leases"]:
            Lease.query.filter(Lease.id.in_(records["leases"])).delete(
                synchronize_session=False
            )
        if records["units"]:
            Unit.query.filter(Unit.id.in_(records["units"])).delete(
                synchronize_session=False
            )
        if records["properties"]:
            Property.query.filter(Property.id.in_(records["properties"])).delete(
                synchronize_session=False
            )
        if records["tenants"]:
            Tenant.query.filter(Tenant.id.in_(records["tenants"])).delete(
                synchronize_session=False
            )
        if records["users"]:
            User.query.filter(User.id.in_(records["users"])).delete(
                synchronize_session=False
            )
        db.session.commit()


def create_landlord():
    landlord = User(
        full_name="Payment API Test Landlord",
        email=f"payment.landlord.{uuid.uuid4().hex}@example.com",
        role="landlord",
    )
    landlord.set_password("SecurePaymentPassword123!")
    db.session.add(landlord)
    db.session.commit()
    return landlord


def create_tenant(owner_id):
    tenant = Tenant(
        owner_id=owner_id,
        full_name="Payment API Test Tenant",
        email=f"payment.tenant.{uuid.uuid4().hex}@example.com",
    )
    db.session.add(tenant)
    db.session.commit()
    return tenant


def create_active_lease(owner_id, tenant):
    property_obj = Property(
        owner_id=owner_id,
        name=f"Payment Test Property {uuid.uuid4().hex}",
        address="Rongai, Kenya",
    )
    db.session.add(property_obj)
    db.session.flush()
    unit = Unit(
        property_id=property_obj.id,
        unit_number=f"P-{uuid.uuid4().hex[:8]}",
        bedrooms=1,
        monthly_rent="8000.00",
        is_active=True,
    )
    db.session.add(unit)
    db.session.flush()
    lease = Lease(
        unit_id=unit.id,
        tenant_id=tenant.id,
        start_date=date.today() - timedelta(days=30),
        end_date=None,
        monthly_rent="8000.00",
        is_active=True,
    )
    db.session.add(lease)
    db.session.commit()
    return property_obj, unit, lease


def record_setup(records, landlord, tenant, property_obj=None, unit=None, lease=None):
    records["users"].add(landlord.id)
    records["tenants"].add(tenant.id)
    if property_obj is not None:
        records["properties"].add(property_obj.id)
    if unit is not None:
        records["units"].add(unit.id)
    if lease is not None:
        records["leases"].add(lease.id)


def auth_headers(user_id):
    token = create_access_token(identity=str(user_id))
    return {"Authorization": f"Bearer {token}"}


def create_issued_invoice(
    client, headers, lease_id, *, period_start="2026-10-01", purpose="rent"
):
    period_end = date.fromisoformat(period_start) + timedelta(days=30)
    if purpose == "utilities":
        charges = [{
            "category": "utilities",
            "amount": "700.00",
            "description": "Water and garbage",
            "utility_breakdowns": [
                {"category": "water", "amount": "450.00"},
                {"category": "garbage", "amount": "250.00"},
            ],
        }]
    else:
        charges = [{"category": "rent", "amount": "8000.00", "description": "Rent"}]
    response = client.post(
        "/api/invoices",
        json={
            "lease_id": lease_id,
            "purpose": purpose,
            "period_start": period_start,
            "period_end": period_end.isoformat(),
            "due_date": period_start,
            "charges": charges,
        },
        headers=headers,
    )
    assert response.status_code == 201
    invoice = response.get_json()["invoice"]
    issue_response = client.post(
        f"/api/invoices/{invoice['id']}/issue",
        headers=headers,
    )
    assert issue_response.status_code == 200
    return invoice


def record_payment(client, headers, tenant_id, amount="1000.00"):
    return client.post(
        "/api/payments",
        json={
            "tenant_id": tenant_id,
            "amount": amount,
            "method": "cash",
            "reference": "cash-test-001",
        },
        headers=headers,
    )


def _run_competing_allocations(app, headers, payment_allocations, lock_table, lock_id):
    """Hold one target row until both independent request transactions are queued."""
    barrier = Barrier(len(payment_allocations) + 1)
    with app.app_context():
        engine = db.engine
    blocker = engine.connect()
    blocker_transaction = blocker.begin()
    futures = []
    executor = ThreadPoolExecutor(max_workers=len(payment_allocations))
    try:
        blocker.execute(
            text(f"SELECT id FROM {lock_table} WHERE id = :row_id FOR UPDATE"),
            {"row_id": lock_id},
        ).one()

        def post_allocation(payment_id, allocations):
            barrier.wait(timeout=10)
            with app.test_client() as client:
                return client.post(
                    f"/api/payments/{payment_id}/allocations",
                    json={"allocations": allocations},
                    headers=headers,
                )

        for payment_id, allocations in payment_allocations:
            futures.append(executor.submit(post_allocation, payment_id, allocations))
        barrier.wait(timeout=10)

        deadline = monotonic() + 15
        while monotonic() < deadline:
            with engine.connect() as monitor:
                waiting_requests = monitor.execute(text("""
                    SELECT count(*)
                    FROM pg_stat_activity
                    WHERE datname = current_database()
                      AND state = 'active'
                      AND wait_event_type = 'Lock'
                      AND query ILIKE '%FOR UPDATE%'
                """)).scalar_one()
            if waiting_requests >= len(payment_allocations):
                break
            if any(future.done() for future in futures):
                raise AssertionError("A competing request finished before reaching the locked row.")
            sleep(0.02)
        else:
            raise AssertionError(
                f"Expected {len(payment_allocations)} PostgreSQL lock waits; "
                f"observed {waiting_requests}."
            )

        blocker_transaction.commit()
        return [future.result(timeout=15) for future in futures]
    finally:
        if blocker_transaction.is_active:
            blocker_transaction.rollback()
        blocker.close()
        executor.shutdown(wait=True, cancel_futures=True)


def test_record_payment_creates_receipt_for_owned_tenant(app, cleanup_records):
    with app.app_context():
        landlord = create_landlord()
        tenant = create_tenant(landlord.id)
        record_setup(cleanup_records, landlord, tenant)
        landlord_id, tenant_id = landlord.id, tenant.id
        headers = auth_headers(landlord_id)

    with app.test_client() as client:
        response = record_payment(client, headers, tenant_id, "2500.00")

    assert response.status_code == 201
    body = response.get_json()["payment"]
    cleanup_records["payments"].add(body["id"])
    assert body["tenant_id"] == tenant_id
    assert body["amount"] == "2500.00"
    assert body["allocated_amount"] == "0.00"
    assert body["unallocated_amount"] == "2500.00"
    assert body["receipt"]["recipient_name"] == "Payment API Test Tenant"
    assert body["receipt"]["amount"] == "2500.00"
    assert body["receipt"]["receipt_number"].startswith("NF-")


def test_record_payment_rejects_non_kes_without_persisting_records(app, cleanup_records):
    with app.app_context():
        landlord = create_landlord()
        tenant = create_tenant(landlord.id)
        record_setup(cleanup_records, landlord, tenant)
        landlord_id, tenant_id = landlord.id, tenant.id
        headers = auth_headers(landlord_id)
        payments_before = Payment.query.filter_by(tenant_id=tenant_id).count()
        receipts_before = Receipt.query.join(Payment).filter(
            Payment.tenant_id == tenant_id
        ).count()

    with app.test_client() as client:
        response = client.post(
            "/api/payments",
            json={
                "tenant_id": tenant_id,
                "amount": "125.00",
                "currency": "USD",
                "method": "cash",
            },
            headers=headers,
        )

    assert response.status_code == 400
    assert response.get_json() == {"error": "Only KES payments are supported."}
    with app.app_context():
        assert Payment.query.filter_by(tenant_id=tenant_id).count() == payments_before
        assert Receipt.query.join(Payment).filter(
            Payment.tenant_id == tenant_id
        ).count() == receipts_before
        assert PaymentAllocation.query.join(Payment).filter(
            Payment.tenant_id == tenant_id
        ).count() == 0


def test_allocation_rejects_existing_non_kes_payment(app, cleanup_records):
    with app.app_context():
        landlord = create_landlord()
        tenant = create_tenant(landlord.id)
        property_obj, unit, lease = create_active_lease(landlord.id, tenant)
        record_setup(cleanup_records, landlord, tenant, property_obj, unit, lease)
        landlord_id, tenant_id, lease_id = landlord.id, tenant.id, lease.id
        headers = auth_headers(landlord_id)

    with app.test_client() as client:
        invoice = create_issued_invoice(client, headers, lease_id)
        cleanup_records["invoices"].add(invoice["id"])
        charge_id = invoice["charges"][0]["id"]

    with app.app_context():
        payment = Payment(
            tenant_id=tenant_id,
            amount=Decimal("125.00"),
            currency="USD",
            method="cash",
        )
        db.session.add(payment)
        db.session.commit()
        payment_id = payment.id
        cleanup_records["payments"].add(payment_id)
        assert PaymentAllocation.query.filter_by(payment_id=payment_id).count() == 0

    with app.test_client() as client:
        response = client.post(
            f"/api/payments/{payment_id}/allocations",
            json={"allocations": [{"charge_id": charge_id, "amount": "25.00"}]},
            headers=headers,
        )

    assert response.status_code == 409
    assert response.get_json() == {"error": "Only KES payments can be allocated."}
    with app.app_context():
        assert PaymentAllocation.query.filter_by(payment_id=payment_id).count() == 0


def test_payment_allocates_partially_and_returns_decimal_balances(app, cleanup_records):
    with app.app_context():
        landlord = create_landlord()
        tenant = create_tenant(landlord.id)
        property_obj, unit, lease = create_active_lease(landlord.id, tenant)
        record_setup(cleanup_records, landlord, tenant, property_obj, unit, lease)
        landlord_id, tenant_id, lease_id = landlord.id, tenant.id, lease.id
        headers = auth_headers(landlord_id)

    with app.test_client() as client:
        invoice = create_issued_invoice(client, headers, lease_id)
        cleanup_records["invoices"].add(invoice["id"])
        rent_charge = next(c for c in invoice["charges"] if c["category"] == "rent")
        utilities_invoice = create_issued_invoice(
            client, headers, lease_id, purpose="utilities"
        )
        cleanup_records["invoices"].add(utilities_invoice["id"])
        utilities_charge = utilities_invoice["charges"][0]
        payment_response = record_payment(client, headers, tenant_id, "1500.00")
        assert payment_response.status_code == 201
        payment = payment_response.get_json()["payment"]
        cleanup_records["payments"].add(payment["id"])

        allocated = client.post(
            f"/api/payments/{payment['id']}/allocations",
            json={
                "allocations": [
                    {"charge_id": rent_charge["id"], "amount": "1200.00"},
                    {"charge_id": utilities_charge["id"], "amount": "300.00"},
                ]
            },
            headers=headers,
        )

        invoice_response = client.get(
            f"/api/invoices/{invoice['id']}",
            headers=headers,
        )
        utilities_response = client.get(
            f"/api/invoices/{utilities_invoice['id']}", headers=headers
        )

    assert allocated.status_code == 200
    result = allocated.get_json()
    assert result["payment"]["allocated_amount"] == "1500.00"
    assert result["payment"]["unallocated_amount"] == "0.00"
    balances = {row["charge_id"]: row for row in result["charge_balances"]}
    rent_balance = balances[rent_charge["id"]]
    assert rent_balance["paid_amount"] == "1200.00"
    assert rent_balance["outstanding_balance"] == "6800.00"
    utilities_balance = balances[utilities_charge["id"]]
    assert utilities_balance["paid_amount"] == "300.00"
    assert utilities_balance["outstanding_balance"] == "400.00"

    rent_invoice_data = invoice_response.get_json()["invoice"]
    utilities_invoice_data = utilities_response.get_json()["invoice"]
    assert rent_invoice_data["total_amount"] == "8000.00"
    assert rent_invoice_data["paid_amount"] == "1200.00"
    assert rent_invoice_data["outstanding_balance"] == "6800.00"
    assert utilities_invoice_data["total_amount"] == "700.00"
    assert utilities_invoice_data["paid_amount"] == "300.00"
    assert utilities_invoice_data["outstanding_balance"] == "400.00"


def test_allocations_cannot_exceed_payment_amount(app, cleanup_records):
    with app.app_context():
        landlord = create_landlord()
        tenant = create_tenant(landlord.id)
        property_obj, unit, lease = create_active_lease(landlord.id, tenant)
        record_setup(cleanup_records, landlord, tenant, property_obj, unit, lease)
        landlord_id, tenant_id, lease_id = landlord.id, tenant.id, lease.id
        headers = auth_headers(landlord_id)

    with app.test_client() as client:
        invoice = create_issued_invoice(client, headers, lease_id)
        cleanup_records["invoices"].add(invoice["id"])
        rent_charge = next(c for c in invoice["charges"] if c["category"] == "rent")
        payment_response = record_payment(client, headers, tenant_id, "700.00")
        assert payment_response.status_code == 201
        payment = payment_response.get_json()["payment"]
        cleanup_records["payments"].add(payment["id"])

        response = client.post(
            f"/api/payments/{payment['id']}/allocations",
            json={"allocations": [{"charge_id": rent_charge["id"], "amount": "700.01"}]},
            headers=headers,
        )
        valid_after_rejection = client.post(
            f"/api/payments/{payment['id']}/allocations",
            json={"allocations": [{"charge_id": rent_charge["id"], "amount": "700.00"}]},
            headers=headers,
        )

    assert response.status_code == 409
    assert valid_after_rejection.status_code == 200


def test_allocations_cannot_exceed_charge_outstanding_balance(app, cleanup_records):
    with app.app_context():
        landlord = create_landlord()
        tenant = create_tenant(landlord.id)
        property_obj, unit, lease = create_active_lease(landlord.id, tenant)
        record_setup(cleanup_records, landlord, tenant, property_obj, unit, lease)
        landlord_id, tenant_id, lease_id = landlord.id, tenant.id, lease.id
        headers = auth_headers(landlord_id)

    with app.test_client() as client:
        invoice = create_issued_invoice(client, headers, lease_id)
        cleanup_records["invoices"].add(invoice["id"])
        rent_charge = next(c for c in invoice["charges"] if c["category"] == "rent")
        first_payment_response = record_payment(client, headers, tenant_id, "5000.00")
        second_payment_response = record_payment(client, headers, tenant_id, "5000.00")
        first_payment = first_payment_response.get_json()["payment"]
        second_payment = second_payment_response.get_json()["payment"]
        cleanup_records["payments"].update({first_payment["id"], second_payment["id"]})

        first_allocation = client.post(
            f"/api/payments/{first_payment['id']}/allocations",
            json={"allocations": [{"charge_id": rent_charge["id"], "amount": "5000.00"}]},
            headers=headers,
        )
        over_balance = client.post(
            f"/api/payments/{second_payment['id']}/allocations",
            json={"allocations": [{"charge_id": rent_charge["id"], "amount": "4000.01"}]},
            headers=headers,
        )

    assert first_allocation.status_code == 200
    assert over_balance.status_code == 409
    assert over_balance.get_json()["outstanding_balance"] == "3000.00"


@pytest.mark.parametrize("invoice_status", ["draft", "void"])
def test_allocations_reject_non_issued_invoice_charges(
    app, cleanup_records, invoice_status
):
    with app.app_context():
        landlord = create_landlord()
        tenant = create_tenant(landlord.id)
        property_obj, unit, lease = create_active_lease(landlord.id, tenant)
        record_setup(cleanup_records, landlord, tenant, property_obj, unit, lease)
        landlord_id, tenant_id, lease_id = landlord.id, tenant.id, lease.id
        headers = auth_headers(landlord_id)

    with app.test_client() as client:
        invoice = create_issued_invoice(client, headers, lease_id)
        cleanup_records["invoices"].add(invoice["id"])
        with app.app_context():
            db_invoice = db.session.get(Invoice, invoice["id"])
            db_invoice.status = invoice_status
            db.session.commit()

        charge = next(item for item in invoice["charges"] if item["category"] == "rent")
        recorded = record_payment(client, headers, tenant_id, "1000.00")
        assert recorded.status_code == 201
        payment = recorded.get_json()["payment"]
        cleanup_records["payments"].add(payment["id"])

        response = client.post(
            f"/api/payments/{payment['id']}/allocations",
            json={"allocations": [{"charge_id": charge["id"], "amount": "500.00"}]},
            headers=headers,
        )

    assert response.status_code == 404
    assert response.get_json()["error"] == "One or more charges were not found for this tenant."


def test_concurrent_allocations_cannot_exceed_payment_balance(app, cleanup_records):
    with app.app_context():
        landlord = create_landlord()
        tenant = create_tenant(landlord.id)
        property_obj, unit, lease = create_active_lease(landlord.id, tenant)
        record_setup(cleanup_records, landlord, tenant, property_obj, unit, lease)
        landlord_id, tenant_id, lease_id = landlord.id, tenant.id, lease.id
        headers = auth_headers(landlord_id)

    with app.test_client() as client:
        invoice = create_issued_invoice(client, headers, lease_id)
        cleanup_records["invoices"].add(invoice["id"])
        utilities_invoice = create_issued_invoice(
            client, headers, lease_id, purpose="utilities"
        )
        cleanup_records["invoices"].add(utilities_invoice["id"])
        rent = invoice["charges"][0]
        utilities = utilities_invoice["charges"][0]
        recorded = record_payment(client, headers, tenant_id, "1000.00")
        assert recorded.status_code == 201
        payment_id = recorded.get_json()["payment"]["id"]
        cleanup_records["payments"].add(payment_id)

    results = _run_competing_allocations(
        app,
        headers,
        [
            (payment_id, [{"charge_id": rent["id"], "amount": "700.00"}]),
            (payment_id, [{"charge_id": utilities["id"], "amount": "700.00"}]),
        ],
        "payments",
        payment_id,
    )

    assert sorted(response.status_code for response in results) == [200, 409]
    with app.app_context():
        allocated = sum(
            (Decimal(row.amount) for row in PaymentAllocation.query.filter_by(
                payment_id=payment_id
            ).all()),
            Decimal("0.00"),
        )
    assert allocated <= Decimal("1000.00")


def test_concurrent_allocations_cannot_exceed_charge_balance(app, cleanup_records):
    with app.app_context():
        landlord = create_landlord()
        tenant = create_tenant(landlord.id)
        property_obj, unit, lease = create_active_lease(landlord.id, tenant)
        record_setup(cleanup_records, landlord, tenant, property_obj, unit, lease)
        landlord_id, tenant_id, lease_id = landlord.id, tenant.id, lease.id
        headers = auth_headers(landlord_id)

    with app.test_client() as client:
        invoice = create_issued_invoice(client, headers, lease_id)
        cleanup_records["invoices"].add(invoice["id"])
        rent = next(charge for charge in invoice["charges"] if charge["category"] == "rent")

        initial_payment = record_payment(client, headers, tenant_id, "7500.00")
        assert initial_payment.status_code == 201
        initial_id = initial_payment.get_json()["payment"]["id"]
        cleanup_records["payments"].add(initial_id)
        initial_allocation = client.post(
            f"/api/payments/{initial_id}/allocations",
            json={"allocations": [{"charge_id": rent["id"], "amount": "7500.00"}]},
            headers=headers,
        )
        assert initial_allocation.status_code == 200

        competing_payment_ids = []
        for _ in range(2):
            recorded = record_payment(client, headers, tenant_id, "1000.00")
            assert recorded.status_code == 201
            competing_payment_ids.append(recorded.get_json()["payment"]["id"])
        cleanup_records["payments"].update(competing_payment_ids)

    results = _run_competing_allocations(
        app,
        headers,
        [
            (payment_id, [{"charge_id": rent["id"], "amount": "400.00"}])
            for payment_id in competing_payment_ids
        ],
        "charges",
        rent["id"],
    )

    assert sorted(response.status_code for response in results) == [200, 409]
    with app.app_context():
        charge = db.session.get(Charge, rent["id"])
        allocated = sum(
            (Decimal(row.amount) for row in PaymentAllocation.query.filter_by(
                charge_id=rent["id"]
            ).all()),
            Decimal("0.00"),
        )
        charge_amount = Decimal(charge.amount)
    assert allocated <= charge_amount


def test_landlord_cannot_record_or_allocate_for_another_landlord(app, cleanup_records):
    with app.app_context():
        landlord_a = create_landlord()
        tenant_a = create_tenant(landlord_a.id)
        record_setup(cleanup_records, landlord_a, tenant_a)
        landlord_b = create_landlord()
        tenant_b = create_tenant(landlord_b.id)
        property_b, unit_b, lease_b = create_active_lease(landlord_b.id, tenant_b)
        record_setup(cleanup_records, landlord_b, tenant_b, property_b, unit_b, lease_b)
        landlord_a_id, landlord_b_id = landlord_a.id, landlord_b.id
        tenant_a_id, tenant_b_id, lease_b_id = tenant_a.id, tenant_b.id, lease_b.id
        headers_a, headers_b = auth_headers(landlord_a_id), auth_headers(landlord_b_id)

    with app.test_client() as client:
        foreign_tenant_payment = record_payment(client, headers_a, tenant_b_id)
        invoice_b = create_issued_invoice(client, headers_b, lease_b_id)
        cleanup_records["invoices"].add(invoice_b["id"])
        payment_a_response = record_payment(client, headers_a, tenant_a_id, "1000.00")
        payment_a = payment_a_response.get_json()["payment"]
        cleanup_records["payments"].add(payment_a["id"])
        foreign_charge_allocation = client.post(
            f"/api/payments/{payment_a['id']}/allocations",
            json={
                "allocations": [
                    {"charge_id": invoice_b["charges"][0]["id"], "amount": "500.00"}
                ]
            },
            headers=headers_a,
        )

    assert foreign_tenant_payment.status_code == 404
    assert foreign_charge_allocation.status_code == 404


def test_list_payments_returns_only_landlords_payments_newest_first(
    app, cleanup_records
):
    with app.app_context():
        landlord_a = create_landlord()
        tenant_a1 = create_tenant(landlord_a.id)
        tenant_a2 = create_tenant(landlord_a.id)
        record_setup(cleanup_records, landlord_a, tenant_a1)
        record_setup(cleanup_records, landlord_a, tenant_a2)
        landlord_b = create_landlord()
        tenant_b = create_tenant(landlord_b.id)
        record_setup(cleanup_records, landlord_b, tenant_b)
        landlord_a_id, landlord_b_id = landlord_a.id, landlord_b.id
        tenant_a1_id, tenant_a2_id, tenant_b_id = tenant_a1.id, tenant_a2.id, tenant_b.id
        headers_a, headers_b = auth_headers(landlord_a_id), auth_headers(landlord_b_id)

    with app.test_client() as client:
        first = record_payment(client, headers_a, tenant_a1_id, "900.00")
        second = record_payment(client, headers_a, tenant_a2_id, "1200.00")
        foreign = record_payment(client, headers_b, tenant_b_id, "500.00")
        assert first.status_code == second.status_code == foreign.status_code == 201
        first_payment = first.get_json()["payment"]
        second_payment = second.get_json()["payment"]
        foreign_payment = foreign.get_json()["payment"]
        cleanup_records["payments"].update({
            first_payment["id"], second_payment["id"], foreign_payment["id"]
        })

        response = client.get("/api/payments", headers=headers_a)

    assert response.status_code == 200
    body = response.get_json()
    assert body["count"] == 2
    payments = body["payments"]
    assert {payment["tenant_id"] for payment in payments} == {tenant_a1_id, tenant_a2_id}
    assert all(payment["tenant"]["full_name"] == "Payment API Test Tenant" for payment in payments)
    assert all("receipt" in payment for payment in payments)
    assert all("allocations" in payment for payment in payments)

    expected = sorted(
        [first_payment, second_payment],
        key=lambda payment: (
            datetime.fromisoformat(payment["received_at"]),
            payment["id"],
        ),
        reverse=True,
    )
    assert [payment["id"] for payment in payments] == [
        payment["id"] for payment in expected
    ]


def test_empty_payment_history_returns_empty_list(app, cleanup_records):
    with app.app_context():
        landlord = create_landlord()
        record_setup(cleanup_records, landlord, create_tenant(landlord.id))
        headers = auth_headers(landlord.id)

    with app.test_client() as client:
        response = client.get("/api/payments", headers=headers)

    assert response.status_code == 200
    assert response.get_json() == {"payments": [], "count": 0}


def test_get_payment_returns_details_and_allocation_history(app, cleanup_records):
    with app.app_context():
        landlord = create_landlord()
        tenant = create_tenant(landlord.id)
        property_obj, unit, lease = create_active_lease(landlord.id, tenant)
        record_setup(cleanup_records, landlord, tenant, property_obj, unit, lease)
        landlord_id, tenant_id, lease_id = landlord.id, tenant.id, lease.id
        headers = auth_headers(landlord_id)

    with app.test_client() as client:
        invoice = create_issued_invoice(client, headers, lease_id)
        cleanup_records["invoices"].add(invoice["id"])
        charge = next(item for item in invoice["charges"] if item["category"] == "rent")
        recorded = record_payment(client, headers, tenant_id, "1500.00")
        assert recorded.status_code == 201
        payment = recorded.get_json()["payment"]
        cleanup_records["payments"].add(payment["id"])

        allocation = client.post(
            f"/api/payments/{payment['id']}/allocations",
            json={"allocations": [{"charge_id": charge["id"], "amount": "500.00"}]},
            headers=headers,
        )
        assert allocation.status_code == 200
        response = client.get(f"/api/payments/{payment['id']}", headers=headers)

    assert response.status_code == 200
    body = response.get_json()["payment"]
    assert body["id"] == payment["id"]
    assert body["tenant_id"] == tenant_id
    assert body["tenant"]["full_name"] == "Payment API Test Tenant"
    assert body["amount"] == "1500.00"
    assert body["allocated_amount"] == "500.00"
    assert body["unallocated_amount"] == "1000.00"
    assert body["allocations"][0]["charge_id"] == charge["id"]
    assert body["allocations"][0]["charge_category"] == "rent"
    assert body["allocations"][0]["invoice_id"] == invoice["id"]
    assert body["receipt"]["receipt_number"] == payment["receipt"]["receipt_number"]


def test_get_payment_receipt_returns_receipt_and_payment_details(app, cleanup_records):
    with app.app_context():
        landlord = create_landlord()
        tenant = create_tenant(landlord.id)
        record_setup(cleanup_records, landlord, tenant)
        landlord_id, tenant_id = landlord.id, tenant.id
        headers = auth_headers(landlord_id)

    with app.test_client() as client:
        recorded = record_payment(client, headers, tenant_id, "2600.00")
        assert recorded.status_code == 201
        payment = recorded.get_json()["payment"]
        cleanup_records["payments"].add(payment["id"])

        response = client.get(
            f"/api/payments/{payment['id']}/receipt",
            headers=headers,
        )

    assert response.status_code == 200
    body = response.get_json()
    receipt = body["receipt"]
    assert receipt["receipt_number"] == payment["receipt"]["receipt_number"]
    assert receipt["recipient_name"] == "Payment API Test Tenant"
    assert receipt["amount"] == "2600.00"
    assert receipt["currency"] == "KES"
    assert receipt["issued_at"]
    assert body["payment"]["id"] == payment["id"]
    assert body["payment"]["tenant"]["id"] == tenant_id
    assert body["payment"]["method"] == "cash"


def test_nonexistent_payment_and_receipt_return_404(app, cleanup_records):
    with app.app_context():
        landlord = create_landlord()
        record_setup(cleanup_records, landlord, create_tenant(landlord.id))
        headers = auth_headers(landlord.id)

    with app.test_client() as client:
        detail = client.get("/api/payments/999999999", headers=headers)
        receipt = client.get("/api/payments/999999999/receipt", headers=headers)

    assert detail.status_code == 404
    assert receipt.status_code == 404


def test_other_landlord_cannot_access_payment_or_receipt(app, cleanup_records):
    with app.app_context():
        owner = create_landlord()
        tenant = create_tenant(owner.id)
        record_setup(cleanup_records, owner, tenant)
        other = create_landlord()
        owner_headers, other_headers = auth_headers(owner.id), auth_headers(other.id)
        tenant_id = tenant.id
        record_setup(cleanup_records, other, create_tenant(other.id))

    with app.test_client() as client:
        recorded = record_payment(client, owner_headers, tenant_id, "800.00")
        assert recorded.status_code == 201
        payment = recorded.get_json()["payment"]
        cleanup_records["payments"].add(payment["id"])

        detail = client.get(
            f"/api/payments/{payment['id']}",
            headers=other_headers,
        )
        receipt = client.get(
            f"/api/payments/{payment['id']}/receipt",
            headers=other_headers,
        )

    assert detail.status_code == 404
    assert receipt.status_code == 404


@pytest.mark.parametrize(
    "path",
    ["/api/payments", "/api/payments/1", "/api/payments/1/receipt"],
)
def test_payment_history_and_receipt_routes_require_authentication(app, path):
    with app.test_client() as client:
        response = client.get(path)

    assert response.status_code == 401


def test_missing_receipt_returns_404(app, cleanup_records):
    with app.app_context():
        landlord = create_landlord()
        tenant = create_tenant(landlord.id)
        record_setup(cleanup_records, landlord, tenant)
        payment = Payment(
            tenant_id=tenant.id,
            amount="500.00",
            currency="KES",
            method="cash",
        )
        db.session.add(payment)
        db.session.commit()
        payment_id = payment.id
        cleanup_records["payments"].add(payment_id)
        headers = auth_headers(landlord.id)

    with app.test_client() as client:
        response = client.get(
            f"/api/payments/{payment_id}/receipt",
            headers=headers,
        )

    assert response.status_code == 404


def test_manager_is_forbidden_from_payment_management_routes(app, cleanup_records):
    with app.app_context():
        manager = User(
            full_name="Payment API Test Manager",
            email=f"payment.manager.{uuid.uuid4().hex}@example.com",
            role="manager",
        )
        manager.set_password("SecurePaymentManagerPassword123!")
        db.session.add(manager)
        db.session.commit()
        cleanup_records["users"].add(manager.id)
        headers = auth_headers(manager.id)

    with app.test_client() as client:
        responses = [
            client.post(
                "/api/payments",
                json={"tenant_id": 1, "amount": "100.00", "method": "cash"},
                headers=headers,
            ),
            client.get("/api/payments", headers=headers),
            client.get("/api/payments/1", headers=headers),
            client.get("/api/payments/1/receipt", headers=headers),
            client.post(
                "/api/payments/1/allocations",
                json={"allocations": []},
                headers=headers,
            ),
        ]

    assert [response.status_code for response in responses] == [403] * 5

