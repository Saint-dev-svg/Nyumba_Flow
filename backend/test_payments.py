import uuid
from datetime import date, timedelta

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


def create_issued_invoice(client, headers, lease_id, *, period_start="2026-10-01"):
    period_end = date.fromisoformat(period_start) + timedelta(days=30)
    response = client.post(
        "/api/invoices",
        json={
            "lease_id": lease_id,
            "period_start": period_start,
            "period_end": period_end.isoformat(),
            "due_date": period_start,
            "charges": [
                {"category": "rent", "amount": "8000.00", "description": "Rent"},
                {
                    "category": "utilities",
                    "amount": "700.00",
                    "description": "Water and garbage",
                    "utility_breakdowns": [
                        {"category": "water", "amount": "450.00"},
                        {"category": "garbage", "amount": "250.00"},
                    ],
                },
            ],
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
        utilities_charge = next(
            c for c in invoice["charges"] if c["category"] == "utilities"
        )
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

    invoice_data = invoice_response.get_json()["invoice"]
    assert invoice_data["total_amount"] == "8700.00"
    assert invoice_data["paid_amount"] == "1500.00"
    assert invoice_data["outstanding_balance"] == "7200.00"


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

