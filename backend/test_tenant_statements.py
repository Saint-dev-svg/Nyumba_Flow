"""Integration tests for tenant account statements."""

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from flask_jwt_extended import create_access_token

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
def records(app):
    created = {key: set() for key in (
        "users", "tenants", "properties", "units", "leases", "invoices", "payments"
    )}
    yield created
    with app.app_context():
        if created["payments"]:
            PaymentAllocation.query.filter(
                PaymentAllocation.payment_id.in_(created["payments"])
            ).delete(synchronize_session=False)
            Receipt.query.filter(Receipt.payment_id.in_(created["payments"])).delete(
                synchronize_session=False
            )
        charge_ids = db.session.query(Charge.id).filter(
            Charge.invoice_id.in_(created["invoices"] or {-1})
        )
        PaymentAllocation.query.filter(
            PaymentAllocation.charge_id.in_(charge_ids)
        ).delete(synchronize_session=False)
        UtilityBreakdown.query.filter(
            UtilityBreakdown.charge_id.in_(charge_ids)
        ).delete(synchronize_session=False)
        Charge.query.filter(Charge.invoice_id.in_(created["invoices"] or {-1})).delete(
            synchronize_session=False
        )
        Invoice.query.filter(Invoice.id.in_(created["invoices"] or {-1})).delete(
            synchronize_session=False
        )
        Payment.query.filter(Payment.id.in_(created["payments"] or {-1})).delete(
            synchronize_session=False
        )
        Lease.query.filter(Lease.id.in_(created["leases"] or {-1})).delete(
            synchronize_session=False
        )
        Unit.query.filter(Unit.id.in_(created["units"] or {-1})).delete(
            synchronize_session=False
        )
        Property.query.filter(Property.id.in_(created["properties"] or {-1})).delete(
            synchronize_session=False
        )
        Tenant.query.filter(Tenant.id.in_(created["tenants"] or {-1})).delete(
            synchronize_session=False
        )
        User.query.filter(User.id.in_(created["users"] or {-1})).delete(
            synchronize_session=False
        )
        db.session.commit()


def _new_user(records, name, role="landlord"):
    user = User(
        full_name=name,
        email=f"{uuid.uuid4().hex}@example.test",
        role=role,
    )
    user.set_password("Statement-Test-Password-123!")
    db.session.add(user)
    db.session.flush()
    records["users"].add(user.id)
    return user


def _new_tenant(records, owner_id, *, name="Statement Tenant"):
    tenant = Tenant(
        owner_id=owner_id,
        full_name=name,
        email=f"{uuid.uuid4().hex}@example.test",
        phone_number="+254700111222",
        national_id_last4="4821",
    )
    db.session.add(tenant)
    db.session.flush()
    records["tenants"].add(tenant.id)
    return tenant


def _new_lease(records, owner_id, tenant):
    property_obj = Property(
        owner_id=owner_id,
        name=f"Statement property {uuid.uuid4().hex[:8]}",
        address="Nairobi, Kenya",
    )
    db.session.add(property_obj)
    db.session.flush()
    unit = Unit(
        property_id=property_obj.id,
        unit_number="A1",
        bedrooms=1,
        monthly_rent=Decimal("100.00"),
        is_active=True,
    )
    db.session.add(unit)
    db.session.flush()
    lease = Lease(
        unit_id=unit.id,
        tenant_id=tenant.id,
        start_date=date(2025, 1, 1),
        monthly_rent=Decimal("100.00"),
        is_active=True,
    )
    db.session.add(lease)
    db.session.flush()
    records["properties"].add(property_obj.id)
    records["units"].add(unit.id)
    records["leases"].add(lease.id)
    return lease


def _new_invoice(records, lease, purpose, status, issued_at, period_start, charges):
    period_end = date(period_start.year, period_start.month, 28)
    invoice = Invoice(
        lease_id=lease.id,
        period_start=period_start,
        period_end=period_end,
        due_date=period_start,
        purpose=purpose,
        status=status,
        issued_at=issued_at,
    )
    for category, amount, description, breakdowns in charges:
        charge = Charge(category=category, amount=Decimal(amount), description=description)
        charge.utility_breakdowns.extend(
            UtilityBreakdown(category=kind, amount=Decimal(value))
            for kind, value in breakdowns
        )
        invoice.charges.append(charge)
    db.session.add(invoice)
    db.session.flush()
    records["invoices"].add(invoice.id)
    return invoice


def _headers(user_id):
    token = create_access_token(identity=str(user_id))
    return {"Authorization": f"Bearer {token}"}


def _statement_fixture(records):
    landlord = _new_user(records, "Statement Landlord")
    tenant = _new_tenant(records, landlord.id)
    lease = _new_lease(records, landlord.id, tenant)
    # Kenya's May 1 starts at 21:00 UTC on April 30; May 31 ends at 20:59:59 UTC.
    may_start = datetime(2025, 4, 30, 21, 0, tzinfo=timezone.utc)
    may_end = datetime(2025, 5, 31, 20, 59, 59, tzinfo=timezone.utc)
    rent = _new_invoice(
        records, lease, "rent", "issued", may_start, date(2025, 5, 1),
        [("rent", "60.00", "Rent part one", []), ("rent", "40.00", "Rent part two", [])],
    )
    utilities = _new_invoice(
        records, lease, "utilities", "issued", may_end, date(2025, 5, 1),
        [("utilities", "30.00", "Water and garbage", [("water", "20.00"), ("garbage", "10.00")])],
    )
    other = _new_invoice(
        records, lease, "other", "issued", datetime(2025, 6, 1, tzinfo=timezone.utc),
        date(2025, 5, 1), [("other", "0.03", "Repair", [])],
    )
    _new_invoice(
        records, lease, "other", "draft", None, date(2025, 7, 1),
        [("other", "900.00", "Draft", [])],
    )
    _new_invoice(
        records, lease, "other", "void", datetime(2025, 5, 20, tzinfo=timezone.utc),
        date(2025, 8, 1), [("other", "800.00", "Void", [])],
    )

    payment = Payment(
        tenant_id=tenant.id,
        amount=Decimal("100.03"),
        currency="KES",
        method="bank_transfer",
        reference="BANK-REF-77",
        received_at=may_end,
    )
    payment.receipt = Receipt(
        receipt_number=f"NF-{uuid.uuid4().hex[:12]}",
        recipient_name=tenant.full_name,
        amount=Decimal("100.03"),
        currency="KES",
    )
    db.session.add(payment)
    db.session.flush()
    records["payments"].add(payment.id)
    rent_charges = rent.charges
    other_charge = other.charges[0]
    db.session.add_all([
        PaymentAllocation(payment_id=payment.id, charge_id=rent_charges[0].id,
                          amount=Decimal("60.00"), created_at=may_start),
        PaymentAllocation(payment_id=payment.id, charge_id=rent_charges[1].id,
                          amount=Decimal("40.00"), created_at=may_end),
        PaymentAllocation(payment_id=payment.id, charge_id=utilities.charges[0].id,
                          amount=Decimal("0.01"), created_at=datetime(2025, 5, 31, 21, 0, tzinfo=timezone.utc)),
        PaymentAllocation(payment_id=payment.id, charge_id=other_charge.id,
                          amount=Decimal("0.02"), created_at=datetime(2025, 6, 1, tzinfo=timezone.utc)),
    ])
    return landlord, tenant, payment


def test_statement_defaults_to_all_available_issued_history_and_summarizes_allocations(app, records):
    with app.app_context():
        landlord, tenant, payment = _statement_fixture(records)
        tenant_id = tenant.id
        tenant_details = {
            "id": tenant.id,
            "full_name": tenant.full_name,
            "email": tenant.email,
            "phone_number": tenant.phone_number,
            "national_id_last4": tenant.national_id_last4,
            "created_at": tenant.created_at.isoformat(),
        }
        payment_id = payment.id
        headers = _headers(landlord.id)
        db.session.commit()

    response = app.test_client().get(f"/api/tenants/{tenant_id}/statement", headers=headers)
    assert response.status_code == 200
    body = response.get_json()
    returned_tenant = body["tenant"]
    assert {key: value for key, value in returned_tenant.items() if key != "created_at"} == {
        key: value for key, value in tenant_details.items() if key != "created_at"
    }
    assert datetime.fromisoformat(returned_tenant["created_at"]) == datetime.fromisoformat(tenant_details["created_at"])
    assert body["statement_period"] == {
        "start_date": None,
        "end_date": None,
        "includes_all_history": True,
        "timezone": "Africa/Nairobi",
    }
    assert [invoice["purpose"] for invoice in body["invoices"]] == ["rent", "utilities", "other"]
    assert len(body["payments"]) == 1
    assert body["payments"][0]["id"] == payment_id
    assert len(body["payments"][0]["allocations"]) == 4
    assert body["summary"]["billed_during_period"] == {
        "rent": "100.00", "utilities": "30.00", "other": "0.03", "total": "130.03"
    }
    assert body["summary"]["allocated_during_period"] == {
        "rent": "100.00", "utilities": "0.01", "other": "0.02", "total": "100.03"
    }
    assert body["summary"]["payments_received_during_period"] == "100.03"
    assert body["summary"]["current_outstanding_balance"] == {
        "rent": "0.00", "utilities": "29.99", "other": "0.01", "total": "30.00"
    }
    assert sum(Decimal(item["amount"]) for item in body["payments"]) == Decimal("100.03")


def test_statement_date_range_uses_inclusive_nairobi_calendar_days(app, records):
    with app.app_context():
        landlord, tenant, _ = _statement_fixture(records)
        tenant_id = tenant.id
        headers = _headers(landlord.id)
        db.session.commit()

    client = app.test_client()
    start_only = client.get(
        f"/api/tenants/{tenant_id}/statement?start_date=2025-05-31", headers=headers
    ).get_json()
    assert [item["purpose"] for item in start_only["invoices"]] == ["utilities", "other"]
    assert start_only["summary"]["allocated_during_period"]["rent"] == "40.00"
    assert start_only["summary"]["allocated_during_period"]["utilities"] == "0.01"
    assert start_only["summary"]["allocated_during_period"]["other"] == "0.02"

    end_only = client.get(
        f"/api/tenants/{tenant_id}/statement?end_date=2025-05-01", headers=headers
    ).get_json()
    assert [item["purpose"] for item in end_only["invoices"]] == ["rent"]
    assert end_only["summary"]["allocated_during_period"]["rent"] == "60.00"

    inclusive = client.get(
        f"/api/tenants/{tenant_id}/statement?start_date=2025-05-01&end_date=2025-05-31",
        headers=headers,
    ).get_json()
    assert [item["purpose"] for item in inclusive["invoices"]] == ["rent", "utilities"]
    assert inclusive["summary"]["allocated_during_period"]["total"] == "100.00"


@pytest.mark.parametrize("query", [
    "start_date=2025-2-01",
    "end_date=2025-05-1",
    "start_date=2025-02-30",
    "start_date=2025-06-01&end_date=2025-05-31",
])
def test_statement_rejects_malformed_dates_and_reversed_ranges(app, records, query):
    with app.app_context():
        landlord = _new_user(records, "Date Validation Landlord")
        tenant = _new_tenant(records, landlord.id)
        tenant_id = tenant.id
        headers = _headers(landlord.id)
        db.session.commit()
    response = app.test_client().get(
        f"/api/tenants/{tenant_id}/statement?{query}", headers=headers
    )
    assert response.status_code == 400
    assert "error" in response.get_json()


def test_statement_empty_tenant_has_zero_financial_summary(app, records):
    with app.app_context():
        landlord = _new_user(records, "Empty Statement Landlord")
        tenant = _new_tenant(records, landlord.id)
        tenant_id = tenant.id
        headers = _headers(landlord.id)
        db.session.commit()
    response = app.test_client().get(f"/api/tenants/{tenant_id}/statement", headers=headers)
    assert response.status_code == 200
    body = response.get_json()
    assert body["invoices"] == []
    assert body["payments"] == []
    assert body["transaction_history"] == []
    assert body["summary"]["billed_during_period"]["total"] == "0.00"
    assert body["summary"]["allocated_during_period"]["total"] == "0.00"
    assert body["summary"]["current_outstanding_balance"]["total"] == "0.00"


def test_statement_is_authenticated_and_tenant_ownership_scoped(app, records):
    with app.app_context():
        landlord = _new_user(records, "Owner Landlord")
        other_landlord = _new_user(records, "Other Landlord")
        manager = _new_user(records, "Statement Manager", role="manager")
        tenant = _new_tenant(records, other_landlord.id, name="Private Tenant")
        tenant_id = tenant.id
        headers = _headers(landlord.id)
        manager_headers = _headers(manager.id)
        db.session.commit()
    client = app.test_client()
    foreign = client.get(f"/api/tenants/{tenant_id}/statement", headers=headers)
    manager_response = client.get(f"/api/tenants/{tenant_id}/statement", headers=manager_headers)
    unauthenticated = client.get(f"/api/tenants/{tenant_id}/statement")
    assert foreign.status_code == 404
    assert foreign.get_json() == {"error": "Tenant not found."}
    assert unauthenticated.status_code == 401
    assert manager_response.status_code == 403
