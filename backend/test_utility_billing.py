"""Integration tests for property utility settings and monthly draft generation."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from decimal import Decimal
from threading import Barrier

import pytest
from flask_jwt_extended import create_access_token

from extensions import db
from models import (
    Charge,
    Invoice,
    Lease,
    PaymentAllocation,
    Property,
    PropertyUtilitySettings,
    Tenant,
    Unit,
    User,
    UtilityBreakdown,
    WaterMeterReading,
)
from test_config import create_test_app


@pytest.fixture
def app():
    return create_test_app()


@pytest.fixture
def cleanup_records(app):
    records = {"users": set(), "tenants": set(), "properties": set(), "units": set(), "leases": set()}
    yield records
    with app.app_context():
        lease_ids = set(records["leases"])
        if lease_ids:
            invoice_ids = [row[0] for row in db.session.query(Invoice.id).filter(
                Invoice.lease_id.in_(lease_ids)
            ).all()]
            if invoice_ids:
                charge_ids = [row[0] for row in db.session.query(Charge.id).filter(
                    Charge.invoice_id.in_(invoice_ids)
                ).all()]
                if charge_ids:
                    UtilityBreakdown.query.filter(
                        UtilityBreakdown.charge_id.in_(charge_ids)
                    ).delete(synchronize_session=False)
                    PaymentAllocation.query.filter(
                        PaymentAllocation.charge_id.in_(charge_ids)
                    ).delete(synchronize_session=False)
                    Charge.query.filter(Charge.id.in_(charge_ids)).delete(
                        synchronize_session=False
                    )
                Invoice.query.filter(Invoice.id.in_(invoice_ids)).delete(
                    synchronize_session=False
                )
            WaterMeterReading.query.filter(
                WaterMeterReading.unit_id.in_(records["units"] or {-1})
            ).delete(synchronize_session=False)
            Lease.query.filter(Lease.id.in_(lease_ids)).delete(synchronize_session=False)
        if records["units"]:
            Unit.query.filter(Unit.id.in_(records["units"])).delete(synchronize_session=False)
        if records["properties"]:
            PropertyUtilitySettings.query.filter(
                PropertyUtilitySettings.property_id.in_(records["properties"])
            ).delete(synchronize_session=False)
            Property.query.filter(Property.id.in_(records["properties"])).delete(
                synchronize_session=False
            )
        if records["tenants"]:
            Tenant.query.filter(Tenant.id.in_(records["tenants"])).delete(synchronize_session=False)
        if records["users"]:
            User.query.filter(User.id.in_(records["users"])).delete(synchronize_session=False)
        db.session.commit()


def create_setup(records, *, active=True, unit_active=True):
    landlord = User(
        full_name="Utility Billing Landlord",
        email=f"utility.landlord.{uuid.uuid4().hex}@example.com",
        role="landlord",
    )
    landlord.set_password("SecureUtilityPassword123!")
    db.session.add(landlord)
    db.session.flush()
    property_obj = Property(
        owner_id=landlord.id,
        name=f"Utility Property {uuid.uuid4().hex}",
        address="Nairobi, Kenya",
    )
    tenant = Tenant(
        owner_id=landlord.id,
        full_name="Utility Billing Tenant",
        email=f"utility.tenant.{uuid.uuid4().hex}@example.com",
    )
    db.session.add_all([property_obj, tenant])
    db.session.flush()
    unit = Unit(
        property_id=property_obj.id,
        unit_number=f"U-{uuid.uuid4().hex[:8]}",
        bedrooms=1,
        monthly_rent=Decimal("14000.00"),
        is_active=unit_active,
    )
    db.session.add(unit)
    db.session.flush()
    lease = Lease(
        unit_id=unit.id,
        tenant_id=tenant.id,
        start_date=date(2020, 1, 1),
        end_date=None,
        monthly_rent=Decimal("15000.00"),
        is_active=active,
    )
    db.session.add(lease)
    db.session.commit()
    records["users"].add(landlord.id)
    records["tenants"].add(tenant.id)
    records["properties"].add(property_obj.id)
    records["units"].add(unit.id)
    records["leases"].add(lease.id)
    return landlord.id, property_obj.id, tenant.id, unit.id, lease.id


def headers_for(user_id):
    token = create_access_token(identity=str(user_id))
    return {"Authorization": f"Bearer {token}"}


def save_reading(client, headers, property_id, unit_id, month="2028-02", previous="10.000", current="12.500"):
    return client.put(
        f"/api/properties/{property_id}/units/{unit_id}/water-reading",
        json={
            "billing_month": month,
            "previous_reading": previous,
            "current_reading": current,
        },
        headers=headers,
    )


def test_meter_reading_upserts_and_lists_once_per_unit_month(app, cleanup_records):
    with app.app_context():
        landlord_id, property_id, _, unit_id, _ = create_setup(cleanup_records)
        headers = headers_for(landlord_id)

    with app.test_client() as client:
        first = save_reading(client, headers, property_id, unit_id)
        first_id = first.get_json()["reading"]["id"]
        updated = save_reading(
            client, headers, property_id, unit_id, previous="10.250", current="12.750"
        )
        listed = client.get(
            f"/api/properties/{property_id}/water-readings?billing_month=2028-02",
            headers=headers,
        )

    assert first.status_code == updated.status_code == 200
    assert updated.get_json()["reading"]["id"] == first_id
    assert updated.get_json()["reading"]["current_reading"] == "12.750"
    assert listed.status_code == 200
    assert listed.get_json()["count"] == 1


def test_reading_validation_rejects_negative_and_decreasing_values(app, cleanup_records):
    with app.app_context():
        landlord_id, property_id, _, unit_id, _ = create_setup(cleanup_records)
        headers = headers_for(landlord_id)

    with app.test_client() as client:
        decreasing = save_reading(client, headers, property_id, unit_id, previous="20", current="19")
        negative = save_reading(client, headers, property_id, unit_id, previous="-1", current="0")
        too_precise = save_reading(client, headers, property_id, unit_id, previous="1.0001", current="2")

    assert decreasing.status_code == negative.status_code == too_precise.status_code == 400
    assert "less than" in decreasing.get_json()["error"]


def test_utility_rates_are_property_scoped_and_updates_persist(app, cleanup_records):
    with app.app_context():
        landlord_id, property_id, _, _, _ = create_setup(cleanup_records)
        headers = headers_for(landlord_id)

    with app.test_client() as client:
        defaults = client.get(f"/api/properties/{property_id}/utility-settings", headers=headers)
        changed = client.patch(
            f"/api/properties/{property_id}/utility-settings",
            json={"water_rate": "181.25", "garbage_fee": "325.00"},
            headers=headers,
        )
        reread = client.get(f"/api/properties/{property_id}/utility-settings", headers=headers)

    assert defaults.get_json()["settings"]["water_rate"] == "180.00"
    assert defaults.get_json()["settings"]["garbage_fee"] == "300.00"
    assert changed.status_code == reread.status_code == 200
    assert reread.get_json()["settings"]["water_rate"] == "181.25"
    assert reread.get_json()["settings"]["garbage_fee"] == "325.00"


def test_missing_reading_skips_both_invoices_and_retry_creates_drafts_once(app, cleanup_records):
    with app.app_context():
        landlord_id, property_id, _, unit_id, lease_id = create_setup(cleanup_records)
        headers = headers_for(landlord_id)

    with app.test_client() as client:
        missing = client.post(
            "/api/invoices/generate-monthly",
            json={"billing_month": "2028-02"},
            headers=headers,
        )
        save_reading(
            client, headers, property_id, unit_id,
            previous="100.125", current="102.625",
        )
        generated = client.post(
            "/api/invoices/generate-monthly",
            json={"billing_month": "2028-02"},
            headers=headers,
        )
        retried = client.post(
            "/api/invoices/generate-monthly",
            json={"billing_month": "2028-02"},
            headers=headers,
        )

    missing_body = missing.get_json()
    created_body = generated.get_json()
    retry_body = retried.get_json()
    assert missing.status_code == 200
    assert missing_body["created_count"] == 0
    assert missing_body["needs_readings"][0]["reason"] == "missing"
    assert created_body["created_count"] == 2
    assert created_body["already_existing_count"] == 0
    assert retry_body["created_count"] == 0
    assert retry_body["already_existing_count"] == 2
    assert {entry["purpose"] for entry in created_body["created_invoices"]} == {"rent", "utilities"}
    with app.app_context():
        invoices = Invoice.query.filter_by(lease_id=lease_id).order_by(Invoice.purpose).all()
        assert len(invoices) == 2
        assert all(invoice.status == "draft" for invoice in invoices)
        utilities = next(invoice for invoice in invoices if invoice.purpose == "utilities")
        utility_charge = utilities.charges[0]
        assert Decimal(utility_charge.amount) == Decimal("750.00")
        assert {row.category: Decimal(row.amount) for row in utility_charge.utility_breakdowns} == {
            "water": Decimal("450.00"),
            "garbage": Decimal("300.00"),
        }


def test_new_property_receives_default_utility_rates(app, cleanup_records):
    with app.app_context():
        landlord_id, _, _, _, _ = create_setup(cleanup_records)
        headers = headers_for(landlord_id)

    with app.test_client() as client:
        created = client.post(
            "/api/properties",
            json={"name": f"New Utility Property {uuid.uuid4().hex}", "address": "Kisumu, Kenya"},
            headers=headers,
        )
        property_id = created.get_json()["property"]["id"]
        cleanup_records["properties"].add(property_id)
        settings = client.get(
            f"/api/properties/{property_id}/utility-settings", headers=headers
        )

    assert created.status_code == 201
    assert settings.status_code == 200
    assert settings.get_json()["settings"]["water_rate"] == "180.00"
    assert settings.get_json()["settings"]["garbage_fee"] == "300.00"


def test_generation_uses_exact_february_period_decimal_water_and_garbage_fee(app, cleanup_records):
    with app.app_context():
        landlord_id, property_id, _, unit_id, lease_id = create_setup(cleanup_records)
        headers = headers_for(landlord_id)

    with app.test_client() as client:
        client.patch(
            f"/api/properties/{property_id}/utility-settings",
            json={"water_rate": "181.25", "garbage_fee": "325.00"},
            headers=headers,
        )
        save_reading(
            client, headers, property_id, unit_id,
            month="2028-02", previous="10.125", current="12.625",
        )
        response = client.post(
            "/api/invoices/generate-monthly",
            json={"billing_month": "2028-02"},
            headers=headers,
        )
        attempted_change = save_reading(
            client, headers, property_id, unit_id,
            month="2028-02", previous="10.125", current="13.000",
        )

    assert response.status_code == 200
    assert attempted_change.status_code == 409
    body = response.get_json()
    assert body["period_start"] == "2028-02-01"
    assert body["period_end"] == "2028-02-29"
    assert body["due_date"] == "2028-02-01"
    with app.app_context():
        invoices = {item.purpose: item for item in Invoice.query.filter_by(lease_id=lease_id).all()}
        assert invoices["rent"].period_start == date(2028, 2, 1)
        assert invoices["rent"].period_end == date(2028, 2, 29)
        assert invoices["rent"].due_date == date(2028, 2, 1)
        assert invoices["rent"].status == invoices["utilities"].status == "draft"
        rent_charge = invoices["rent"].charges[0]
        utilities_charge = invoices["utilities"].charges[0]
        assert Decimal(rent_charge.amount) == Decimal("15000.00")
        assert Decimal(utilities_charge.amount) == Decimal("778.13")
        breakdowns = {item.category: Decimal(item.amount) for item in utilities_charge.utility_breakdowns}
        assert breakdowns == {"water": Decimal("453.13"), "garbage": Decimal("325.00")}
        assert sum(breakdowns.values()) == Decimal(utilities_charge.amount)


def test_non_leap_february_uses_twenty_eight_calendar_days(app, cleanup_records):
    with app.app_context():
        landlord_id, _, _, _, _ = create_setup(cleanup_records, active=False)
        headers = headers_for(landlord_id)

    with app.test_client() as client:
        response = client.post(
            "/api/invoices/generate-monthly",
            json={"billing_month": "2027-02"},
            headers=headers,
        )

    assert response.status_code == 200
    assert response.get_json()["period_start"] == "2027-02-01"
    assert response.get_json()["period_end"] == "2027-02-28"


def test_generation_excludes_inactive_unit_or_lease(app, cleanup_records):
    with app.app_context():
        landlord_id, _, _, _, _ = create_setup(
            cleanup_records, active=False, unit_active=False
        )
        headers = headers_for(landlord_id)

    with app.test_client() as client:
        response = client.post(
            "/api/invoices/generate-monthly",
            json={"billing_month": "2028-02"},
            headers=headers,
        )

    assert response.status_code == 200
    assert response.get_json()["created_count"] == 0
    assert response.get_json()["needs_reading_count"] == 0


def test_utility_endpoints_enforce_ownership_and_landlord_role(app, cleanup_records):
    with app.app_context():
        landlord_id, property_id, _, unit_id, _ = create_setup(cleanup_records)
        other = User(
            full_name="Other Utility Landlord",
            email=f"utility.other.{uuid.uuid4().hex}@example.com",
            role="landlord",
        )
        other.set_password("SecureOtherPassword123!")
        manager = User(
            full_name="Utility Manager",
            email=f"utility.manager.{uuid.uuid4().hex}@example.com",
            role="manager",
        )
        manager.set_password("SecureManagerPassword123!")
        db.session.add_all([other, manager])
        db.session.commit()
        foreign_property = Property(
            owner_id=other.id,
            name=f"Foreign utility property {uuid.uuid4().hex}",
            address="Mombasa, Kenya",
        )
        db.session.add(foreign_property)
        db.session.flush()
        foreign_unit = Unit(
            property_id=foreign_property.id,
            unit_number=f"X-{uuid.uuid4().hex[:8]}",
            bedrooms=1,
            monthly_rent=Decimal("9000.00"),
        )
        db.session.add(foreign_unit)
        db.session.commit()
        cleanup_records["users"].update({other.id, manager.id})
        cleanup_records["properties"].add(foreign_property.id)
        cleanup_records["units"].add(foreign_unit.id)
        landlord_headers = headers_for(landlord_id)
        other_headers = headers_for(other.id)
        manager_headers = headers_for(manager.id)

    with app.test_client() as client:
        foreign = client.get(
            f"/api/properties/{property_id}/utility-settings", headers=other_headers
        )
        forbidden = client.post(
            "/api/invoices/generate-monthly",
            json={"billing_month": "2028-02"}, headers=manager_headers,
        )
        foreign_unit = client.put(
            f"/api/properties/{property_id}/units/{foreign_unit.id}/water-reading",
            json={"billing_month": "2028-02", "previous_reading": "1", "current_reading": "2"},
            headers=landlord_headers,
        )
        foreign_generation = client.post(
            "/api/invoices/generate-monthly",
            json={"billing_month": "2028-02"},
            headers=other_headers,
        )

    assert foreign.status_code == 404
    assert forbidden.status_code == 403
    assert foreign_unit.status_code == 404
    assert foreign_generation.status_code == 200
    assert foreign_generation.get_json()["created_count"] == 0


def test_concurrent_generation_creates_one_draft_pair(app, cleanup_records):
    with app.app_context():
        landlord_id, property_id, _, unit_id, lease_id = create_setup(cleanup_records)
        headers = headers_for(landlord_id)
    with app.test_client() as client:
        reading = save_reading(client, headers, property_id, unit_id)
        assert reading.status_code == 200

    barrier = Barrier(3)
    executor = ThreadPoolExecutor(max_workers=2)
    try:
        def generate():
            barrier.wait(timeout=15)
            with app.test_client() as client:
                return client.post(
                    "/api/invoices/generate-monthly",
                    json={"billing_month": "2028-02"},
                    headers=headers,
                )

        futures = [executor.submit(generate) for _ in range(2)]
        barrier.wait(timeout=15)
        responses = [future.result(timeout=30) for future in futures]
    finally:
        executor.shutdown(wait=True, cancel_futures=True)

    assert [response.status_code for response in responses] == [200, 200]
    assert sorted(response.get_json()["created_count"] for response in responses) == [0, 2]
    assert sorted(response.get_json()["already_existing_count"] for response in responses) == [0, 2]
    with app.app_context():
        purposes = [row[0] for row in db.session.query(Invoice.purpose).filter_by(lease_id=lease_id).all()]
    assert sorted(purposes) == ["rent", "utilities"]
