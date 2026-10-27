"""Integration tests for landlord financial reporting."""

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
    PropertyUtilitySettings,
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
def report_records(app):
    records = {"users": [], "tenants": [], "properties": [], "units": [], "leases": [], "invoices": [], "payments": []}
    yield records
    with app.app_context():
        invoice_ids = records["invoices"] or [-1]
        charge_ids = [row[0] for row in db.session.query(Charge.id).filter(
            Charge.invoice_id.in_(invoice_ids)
        ).all()]
        if charge_ids:
            PaymentAllocation.query.filter(PaymentAllocation.charge_id.in_(charge_ids)).delete(
                synchronize_session=False
            )
            UtilityBreakdown.query.filter(UtilityBreakdown.charge_id.in_(charge_ids)).delete(
                synchronize_session=False
            )
        if records["payments"]:
            PaymentAllocation.query.filter(PaymentAllocation.payment_id.in_(records["payments"])).delete(
                synchronize_session=False
            )
        if charge_ids:
            Charge.query.filter(Charge.id.in_(charge_ids)).delete(synchronize_session=False)
        if records["invoices"]:
            Invoice.query.filter(Invoice.id.in_(records["invoices"])).delete(synchronize_session=False)
        if records["payments"]:
            Payment.query.filter(Payment.id.in_(records["payments"])).delete(synchronize_session=False)
        if records["leases"]:
            Lease.query.filter(Lease.id.in_(records["leases"])).delete(synchronize_session=False)
        if records["units"]:
            Unit.query.filter(Unit.id.in_(records["units"])).delete(synchronize_session=False)
        if records["properties"]:
            PropertyUtilitySettings.query.filter(
                PropertyUtilitySettings.property_id.in_(records["properties"])
            ).delete(synchronize_session=False)
            Property.query.filter(Property.id.in_(records["properties"])).delete(synchronize_session=False)
        if records["tenants"]:
            Tenant.query.filter(Tenant.id.in_(records["tenants"])).delete(synchronize_session=False)
        if records["users"]:
            User.query.filter(User.id.in_(records["users"])).delete(synchronize_session=False)
        db.session.commit()


def _landlord(name, records):
    user = User(
        full_name=name,
        email=f"{uuid.uuid4().hex}@example.test",
        role="landlord",
    )
    user.set_password("Report-Test-Password-123!")
    db.session.add(user)
    db.session.flush()
    records["users"].append(user.id)
    return user


def _lease(owner_id, name, records):
    property_obj = Property(
        owner_id=owner_id,
        name=f"{name}-{uuid.uuid4().hex[:8]}",
        address="Nairobi, Kenya",
    )
    tenant = Tenant(
        owner_id=owner_id,
        full_name=f"Tenant {name}",
        email=f"{uuid.uuid4().hex}@example.test",
    )
    db.session.add_all([property_obj, tenant])
    db.session.flush()
    unit = Unit(
        property_id=property_obj.id,
        unit_number="A1",
        bedrooms=1,
        monthly_rent=Decimal("1000.00"),
        is_active=True,
    )
    db.session.add(unit)
    db.session.flush()
    lease = Lease(
        unit_id=unit.id,
        tenant_id=tenant.id,
        start_date=date(2024, 1, 1),
        monthly_rent=Decimal("1000.00"),
        is_active=True,
    )
    db.session.add(lease)
    db.session.flush()
    records["properties"].append(property_obj.id)
    records["tenants"].append(tenant.id)
    records["units"].append(unit.id)
    records["leases"].append(lease.id)
    return property_obj, tenant, lease


def _invoice(lease, purpose, status, issued_at, amount, records, *, breakdowns=None,
             period_start=None, period_end=None):
    invoice = Invoice(
        lease_id=lease.id,
        period_start=period_start or date(2025, 5, 1),
        period_end=period_end or date(2025, 5, 31),
        due_date=date(2025, 5, 5),
        purpose=purpose,
        status=status,
        issued_at=issued_at,
    )
    invoice.charges.append(Charge(category=purpose, amount=Decimal(amount)))
    db.session.add(invoice)
    db.session.flush()
    charge = invoice.charges[0]
    for category, breakdown_amount in (breakdowns or {}).items():
        charge.utility_breakdowns.append(UtilityBreakdown(
            category=category,
            amount=Decimal(breakdown_amount),
        ))
    records["invoices"].append(invoice.id)
    return invoice, charge


def _auth_header(user_id):
    token = create_access_token(identity=str(user_id))
    return {"Authorization": f"Bearer {token}"}


def test_financial_report_separates_monthly_activity_from_current_balances(app, report_records):
    with app.app_context():
        landlord = _landlord("Report landlord", report_records)
        property_obj, tenant, lease = _lease(landlord.id, "Home", report_records)
        second_property, _, second_lease = _lease(landlord.id, "Annex", report_records)
        # 21:30 UTC is 00:30 on May 1 in Nairobi, so this belongs to May there.
        may = datetime(2025, 4, 30, 21, 30, tzinfo=timezone.utc)
        rent_invoice, rent_charge = _invoice(lease, "rent", "issued", may, "1000.00", report_records)
        utilities_invoice, utilities_charge = _invoice(
            lease, "utilities", "issued", may, "300.00", report_records,
            breakdowns={"water": "200.00", "garbage": "100.00"},
        )
        old_invoice, old_charge = _invoice(
            lease, "rent", "issued", datetime(2025, 4, 12, tzinfo=timezone.utc),
            "500.00", report_records, period_start=date(2025, 4, 1),
            period_end=date(2025, 4, 30),
        )
        _invoice(lease, "other", "draft", None, "900.00", report_records,
                 period_start=date(2025, 7, 1), period_end=date(2025, 7, 31))
        _invoice(lease, "other", "void", may, "800.00", report_records,
                 period_start=date(2025, 8, 1), period_end=date(2025, 8, 31))
        _invoice(lease, "other", "issued", may, "0.03", report_records)
        _invoice(second_lease, "rent", "issued", may, "0.07", report_records)
        payment = Payment(
            tenant_id=tenant.id,
            amount=Decimal("700.00"),
            currency="KES",
            method="cash",
            received_at=datetime(2025, 5, 20, tzinfo=timezone.utc),
        )
        db.session.add(payment)
        db.session.flush()
        report_records["payments"].append(payment.id)
        db.session.add_all([
            PaymentAllocation(payment_id=payment.id, charge_id=rent_charge.id,
                              amount=Decimal("400.00"), created_at=may),
            PaymentAllocation(payment_id=payment.id, charge_id=utilities_charge.id,
                              amount=Decimal("100.00"), created_at=datetime(2025, 6, 1, tzinfo=timezone.utc)),
            PaymentAllocation(payment_id=payment.id, charge_id=old_charge.id,
                              amount=Decimal("200.00"), created_at=may),
        ])
        db.session.commit()
        headers = _auth_header(landlord.id)
        property_id = property_obj.id
        second_property_id = second_property.id
        second_property_name = second_property.name

    client = app.test_client()
    response = client.get("/api/reports/financial?month=2025-05", headers=headers)
    assert response.status_code == 200
    data = response.get_json()
    assert data["billed_during_month"] == {"rent": "1000.07", "utilities": "300.00", "other": "0.03", "total": "1300.10"}
    assert data["allocations_received_during_month"] == {"rent": "600.00", "utilities": "0.00", "other": "0.00", "total": "600.00"}
    assert data["current_paid_on_invoices_issued_during_month"] == {"rent": "400.00", "utilities": "100.00", "other": "0.00", "total": "500.00"}
    assert data["outstanding_current_issued_invoices"] == {"rent": "900.07", "utilities": "200.00", "other": "0.03", "total": "1100.10"}
    assert data["utility_breakdown_billed_during_month"] == {"water": "200.00", "garbage": "100.00"}
    assert data["timezone"] == "Africa/Nairobi"
    assert data["property_breakdown"] == [{
        "property_id": second_property_id,
        "property_name": second_property_name,
        "billed_during_month": {"rent": "0.07", "utilities": "0.00", "other": "0.00", "total": "0.07"},
        "allocations_received_during_month": {"rent": "0.00", "utilities": "0.00", "other": "0.00", "total": "0.00"},
        "outstanding_current_issued_invoices": {"rent": "0.07", "utilities": "0.00", "other": "0.00", "total": "0.07"},
        "utility_breakdown_billed_during_month": {"water": "0.00", "garbage": "0.00"},
    }, {
        "property_id": property_id,
        "property_name": property_obj.name,
        "billed_during_month": {"rent": "1000.00", "utilities": "300.00", "other": "0.03", "total": "1300.03"},
        "allocations_received_during_month": {"rent": "600.00", "utilities": "0.00", "other": "0.00", "total": "600.00"},
        "outstanding_current_issued_invoices": {"rent": "900.00", "utilities": "200.00", "other": "0.03", "total": "1100.03"},
        "utility_breakdown_billed_during_month": {"water": "200.00", "garbage": "100.00"},
    }]
    assert data["collection_rates_percent"]["rent"]["current_paid_on_invoices_issued_in_month"]["rate"] == "40.00"
    assert data["collection_rates_percent"]["other"]["allocations_received_during_month"]["rate"] == "0.00"

    filtered = client.get(
        f"/api/reports/financial?month=2025-05&property_id={property_id}",
        headers=headers,
    )
    assert filtered.status_code == 200
    assert filtered.get_json()["billed_during_month"]["rent"] == "1000.00"


def test_financial_report_empty_month_returns_zero_totals_without_division_error(app, report_records):
    with app.app_context():
        landlord = _landlord("Empty report landlord", report_records)
        headers = _auth_header(landlord.id)
        db.session.commit()
    response = app.test_client().get("/api/reports/financial?month=2025-05", headers=headers)
    assert response.status_code == 200
    data = response.get_json()
    assert data["billed_during_month"] == {"rent": "0.00", "utilities": "0.00", "other": "0.00", "total": "0.00"}
    assert data["outstanding_current_issued_invoices"] == {"rent": "0.00", "utilities": "0.00", "other": "0.00", "total": "0.00"}
    assert data["collection_rates_percent"]["rent"]["current_paid_on_invoices_issued_in_month"]["rate"] is None


@pytest.mark.parametrize("month", [None, "2025-5", "2025-13", "foo"])
def test_financial_report_rejects_invalid_month(app, report_records, month):
    with app.app_context():
        landlord = _landlord("Invalid report landlord", report_records)
        headers = _auth_header(landlord.id)
        db.session.commit()
    path = "/api/reports/financial" if month is None else f"/api/reports/financial?month={month}"
    response = app.test_client().get(path, headers=headers)
    assert response.status_code == 400


def test_financial_report_rejects_invalid_and_foreign_property_filters(app, report_records):
    with app.app_context():
        landlord = _landlord("Property report landlord", report_records)
        foreign_landlord = _landlord("Foreign report landlord", report_records)
        property_obj, _, _ = _lease(foreign_landlord.id, "Foreign", report_records)
        token_headers = _auth_header(landlord.id)
        foreign_property_id = property_obj.id
        db.session.commit()
    client = app.test_client()
    invalid = client.get("/api/reports/financial?month=2025-05&property_id=nope", headers=token_headers)
    assert invalid.status_code == 400
    foreign = client.get(
        f"/api/reports/financial?month=2025-05&property_id={foreign_property_id}",
        headers=token_headers,
    )
    assert foreign.status_code == 404


def test_financial_report_requires_landlord_and_hides_other_landlord_data(app, report_records):
    with app.app_context():
        landlord = _landlord("Scoped report landlord", report_records)
        foreign_landlord = _landlord("Other report landlord", report_records)
        _, _, lease = _lease(foreign_landlord.id, "Private", report_records)
        _invoice(lease, "rent", "issued", datetime(2025, 5, 12, tzinfo=timezone.utc),
                 "1234.56", report_records)
        headers = _auth_header(landlord.id)
        db.session.commit()
    response = app.test_client().get("/api/reports/financial?month=2025-05", headers=headers)
    assert response.status_code == 200
    assert response.get_json()["billed_during_month"]["rent"] == "0.00"
    assert response.get_json()["property_breakdown"] == []
    unauthenticated = app.test_client().get("/api/reports/financial?month=2025-05")
    assert unauthenticated.status_code == 401
