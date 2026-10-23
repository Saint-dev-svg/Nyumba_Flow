"""API contract tests for invoice and charge management."""

import uuid
from datetime import date, timedelta

import pytest
from flask_jwt_extended import create_access_token

from extensions import db
from models import (
    Charge,
    Invoice,
    Lease,
    Property,
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
    }
    yield records

    with app.app_context():
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
    user = User(
        full_name="Invoice API Test Landlord",
        email=f"invoice.landlord.{uuid.uuid4().hex}@example.com",
        role="landlord",
    )
    user.set_password("SecureInvoicePassword123!")
    db.session.add(user)
    db.session.commit()
    return user


def create_active_lease(owner_id, *, active=True):
    property_obj = Property(
        owner_id=owner_id,
        name=f"Invoice Test Property {uuid.uuid4().hex}",
        address="Rongai, Kenya",
    )
    db.session.add(property_obj)
    db.session.flush()

    unit = Unit(
        property_id=property_obj.id,
        unit_number=f"I-{uuid.uuid4().hex[:8]}",
        bedrooms=1,
        monthly_rent="15000.00",
        is_active=True,
    )
    tenant = Tenant(
        owner_id=owner_id,
        full_name="Invoice Test Tenant",
        email=f"invoice.tenant.{uuid.uuid4().hex}@example.com",
    )
    db.session.add_all([unit, tenant])
    db.session.flush()

    lease = Lease(
        unit_id=unit.id,
        tenant_id=tenant.id,
        start_date=date.today() - timedelta(days=30),
        end_date=None,
        monthly_rent="15000.00",
        is_active=active,
    )
    db.session.add(lease)
    db.session.commit()
    return property_obj, unit, tenant, lease


def record_setup(records, landlord, property_obj, unit, tenant, lease):
    records["users"].add(landlord.id)
    records["properties"].add(property_obj.id)
    records["units"].add(unit.id)
    records["tenants"].add(tenant.id)
    records["leases"].add(lease.id)


def auth_headers(user_id):
    token = create_access_token(identity=str(user_id))
    return {"Authorization": f"Bearer {token}"}


def invoice_payload(lease_id, *, period_start="2026-10-01", period_end="2026-10-31"):
    return {
        "lease_id": lease_id,
        "period_start": period_start,
        "period_end": period_end,
        "due_date": "2026-10-05",
        "charges": [
            {
                "category": "rent",
                "amount": "15000.00",
                "description": "October rent",
            }
        ],
    }


def create_invoice(client, headers, lease_id, **period):
    return client.post(
        "/api/invoices",
        json=invoice_payload(lease_id, **period),
        headers=headers,
    )


def test_create_invoice_with_charges_for_active_owned_lease(app, cleanup_records):
    with app.app_context():
        landlord = create_landlord()
        property_obj, unit, tenant, lease = create_active_lease(landlord.id)
        record_setup(cleanup_records, landlord, property_obj, unit, tenant, lease)
        lease_id = lease.id
        headers = auth_headers(landlord.id)

    with app.test_client() as client:
        response = create_invoice(client, headers, lease_id)

    assert response.status_code == 201
    invoice_data = response.get_json()["invoice"]
    assert invoice_data["lease_id"] == lease_id
    assert invoice_data["period_start"] == "2026-10-01"
    assert invoice_data["period_end"] == "2026-10-31"
    assert invoice_data["status"] == "draft"
    assert len(invoice_data["charges"]) == 1
    assert invoice_data["charges"][0]["category"] == "rent"
    assert invoice_data["charges"][0]["amount"] == "15000.00"
    cleanup_records["invoices"].add(invoice_data["id"])


def test_invoice_creation_requires_an_active_lease(app, cleanup_records):
    with app.app_context():
        landlord = create_landlord()
        property_obj, unit, tenant, lease = create_active_lease(
            landlord.id, active=False
        )
        record_setup(cleanup_records, landlord, property_obj, unit, tenant, lease)
        lease_id = lease.id
        headers = auth_headers(landlord.id)

    with app.test_client() as client:
        response = create_invoice(client, headers, lease_id)

    assert response.status_code == 409


def test_duplicate_billing_period_for_lease_is_rejected(app, cleanup_records):
    with app.app_context():
        landlord = create_landlord()
        property_obj, unit, tenant, lease = create_active_lease(landlord.id)
        record_setup(cleanup_records, landlord, property_obj, unit, tenant, lease)
        lease_id = lease.id
        headers = auth_headers(landlord.id)

    with app.test_client() as client:
        first = create_invoice(client, headers, lease_id)
        assert first.status_code == 201
        cleanup_records["invoices"].add(first.get_json()["invoice"]["id"])
        duplicate = create_invoice(client, headers, lease_id)

    assert duplicate.status_code == 409


def test_landlord_can_only_create_and_list_their_own_invoices(app, cleanup_records):
    with app.app_context():
        landlord_a = create_landlord()
        property_a, unit_a, tenant_a, lease_a = create_active_lease(landlord_a.id)
        record_setup(cleanup_records, landlord_a, property_a, unit_a, tenant_a, lease_a)
        lease_a_id = lease_a.id

        landlord_b = create_landlord()
        property_b, unit_b, tenant_b, lease_b = create_active_lease(landlord_b.id)
        record_setup(cleanup_records, landlord_b, property_b, unit_b, tenant_b, lease_b)
        lease_b_id = lease_b.id
        landlord_a_id = landlord_a.id

        headers_a = auth_headers(landlord_a_id)
        headers_b = auth_headers(landlord_b.id)

    with app.test_client() as client:
        invoice_a = create_invoice(client, headers_a, lease_a_id)
        assert invoice_a.status_code == 201
        cleanup_records["invoices"].add(invoice_a.get_json()["invoice"]["id"])

        invoice_b = create_invoice(client, headers_b, lease_b_id)
        assert invoice_b.status_code == 201
        cleanup_records["invoices"].add(invoice_b.get_json()["invoice"]["id"])

        foreign_lease = create_invoice(client, headers_a, lease_b_id)
        listed = client.get("/api/invoices", headers=headers_a)

    assert foreign_lease.status_code == 404
    assert listed.status_code == 200
    body = listed.get_json()
    assert body["count"] == 1
    assert len(body["invoices"]) == 1
    assert body["invoices"][0]["lease_id"] == lease_a_id


def test_landlord_can_issue_their_draft_invoice(app, cleanup_records):
    with app.app_context():
        landlord = create_landlord()
        property_obj, unit, tenant, lease = create_active_lease(landlord.id)
        record_setup(cleanup_records, landlord, property_obj, unit, tenant, lease)
        lease_id = lease.id
        headers = auth_headers(landlord.id)

    with app.test_client() as client:
        created = create_invoice(client, headers, lease_id)
        assert created.status_code == 201
        invoice_id = created.get_json()["invoice"]["id"]
        cleanup_records["invoices"].add(invoice_id)
        issued = client.post(
            f"/api/invoices/{invoice_id}/issue",
            headers=headers,
        )

    assert issued.status_code == 200
    invoice_data = issued.get_json()["invoice"]
    assert invoice_data["id"] == invoice_id
    assert invoice_data["status"] == "issued"
    assert invoice_data["issued_at"] is not None


@pytest.mark.parametrize("status", ["issued", "void"])
def test_non_draft_invoice_cannot_be_issued(app, cleanup_records, status):
    with app.app_context():
        landlord = create_landlord()
        property_obj, unit, tenant, lease = create_active_lease(landlord.id)
        record_setup(cleanup_records, landlord, property_obj, unit, tenant, lease)
        lease_id = lease.id
        headers = auth_headers(landlord.id)

    with app.test_client() as client:
        created = create_invoice(client, headers, lease_id)
        assert created.status_code == 201
        invoice_id = created.get_json()["invoice"]["id"]
        cleanup_records["invoices"].add(invoice_id)

        if status == "issued":
            first_issue = client.post(
                f"/api/invoices/{invoice_id}/issue",
                headers=headers,
            )
            assert first_issue.status_code == 200
        else:
            with app.app_context():
                invoice = db.session.get(Invoice, invoice_id)
                invoice.status = "void"
                db.session.commit()

        repeated_issue = client.post(
            f"/api/invoices/{invoice_id}/issue",
            headers=headers,
        )

    assert repeated_issue.status_code == 409


def test_other_landlord_cannot_issue_invoice(app, cleanup_records):
    with app.app_context():
        owner = create_landlord()
        property_obj, unit, tenant, lease = create_active_lease(owner.id)
        record_setup(cleanup_records, owner, property_obj, unit, tenant, lease)
        lease_id = lease.id

        other_landlord = create_landlord()
        other_landlord_id = other_landlord.id
        owner_headers = auth_headers(owner.id)
        other_headers = auth_headers(other_landlord_id)

    with app.test_client() as client:
        created = create_invoice(client, owner_headers, lease_id)
        assert created.status_code == 201
        invoice_id = created.get_json()["invoice"]["id"]
        cleanup_records["invoices"].add(invoice_id)

        response = client.post(
            f"/api/invoices/{invoice_id}/issue",
            headers=other_headers,
        )

    assert response.status_code == 404


def test_landlord_can_retrieve_their_own_invoice(app, cleanup_records):
    with app.app_context():
        landlord = create_landlord()
        property_obj, unit, tenant, lease = create_active_lease(landlord.id)
        record_setup(cleanup_records, landlord, property_obj, unit, tenant, lease)
        lease_id = lease.id
        headers = auth_headers(landlord.id)

    with app.test_client() as client:
        created = create_invoice(client, headers, lease_id)
        assert created.status_code == 201

        invoice = created.get_json()["invoice"]
        invoice_id = invoice["id"]
        cleanup_records["invoices"].add(invoice_id)

        response = client.get(
            f"/api/invoices/{invoice_id}",
            headers=headers,
        )

    assert response.status_code == 200
    body = response.get_json()["invoice"]
    assert body["id"] == invoice_id
    assert body["lease_id"] == lease_id
    assert body["status"] == "draft"
    assert len(body["charges"]) == 1


def test_landlord_cannot_retrieve_another_landlords_invoice(
    app, cleanup_records
):
    with app.app_context():
        landlord_a = create_landlord()
        property_a, unit_a, tenant_a, lease_a = create_active_lease(
            landlord_a.id
        )
        record_setup(
            cleanup_records, landlord_a, property_a, unit_a, tenant_a, lease_a
        )
        lease_a_id = lease_a.id
        headers_a = auth_headers(landlord_a.id)

        landlord_b = create_landlord()
        property_b, unit_b, tenant_b, lease_b = create_active_lease(
            landlord_b.id
        )
        record_setup(
            cleanup_records, landlord_b, property_b, unit_b, tenant_b, lease_b
        )
        lease_b_id = lease_b.id
        headers_b = auth_headers(landlord_b.id)

    with app.test_client() as client:
        created = create_invoice(client, headers_b, lease_b_id)
        assert created.status_code == 201
        invoice_id = created.get_json()["invoice"]["id"]
        cleanup_records["invoices"].add(invoice_id)

        response = client.get(
            f"/api/invoices/{invoice_id}",
            headers=headers_a,
        )

    assert response.status_code == 404

def test_retrieving_nonexistent_invoice_returns_404(app):
    with app.app_context():
        landlord = create_landlord()
        headers = auth_headers(landlord.id)

    with app.test_client() as client:
        response = client.get(
            "/api/invoices/999999999",
            headers=headers,
        )

    assert response.status_code == 404
