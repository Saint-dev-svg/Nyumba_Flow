from datetime import date, timedelta
import uuid

import pytest
from flask_jwt_extended import create_access_token
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from extensions import db
from models import Lease, Property, Tenant, Unit, User
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
    }
    yield records

    with app.app_context():
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


def create_landlord(email=None):
    user = User(
        full_name="Lease API Test Landlord",
        email=email or f"lease.landlord.{uuid.uuid4().hex}@example.com",
        role="landlord",
    )
    user.set_password("SecureLeasePassword123!")
    db.session.add(user)
    db.session.commit()
    return user


def create_unit(owner_id, *, is_active=True):
    property_obj = Property(
        owner_id=owner_id,
        name=f"Lease Test Property {uuid.uuid4().hex}",
        address="Rongai, Kenya",
    )
    db.session.add(property_obj)
    db.session.flush()
    unit = Unit(
        property_id=property_obj.id,
        unit_number=f"U-{uuid.uuid4().hex[:8]}",
        bedrooms=1,
        monthly_rent="15000.00",
        is_active=is_active,
    )
    db.session.add(unit)
    db.session.commit()
    return property_obj, unit


def create_tenant(owner_id):
    tenant = Tenant(
        owner_id=owner_id,
        full_name="Lease Test Tenant",
        email=f"lease.tenant.{uuid.uuid4().hex}@example.com",
    )
    db.session.add(tenant)
    db.session.commit()
    return tenant


def headers_for(user_id):
    token = create_access_token(identity=str(user_id))
    return {"Authorization": f"Bearer {token}"}


def record_owner(records, user, tenant=None, property_obj=None, unit=None):
    records["users"].add(user.id)
    if tenant is not None:
        records["tenants"].add(tenant.id)
    if property_obj is not None:
        records["properties"].add(property_obj.id)
    if unit is not None:
        records["units"].add(unit.id)


def create_draft(client, headers, unit_id, tenant_id, start_date, end_date=None, rent="15000.00"):
    return client.post(
        "/api/leases",
        json={
            "unit_id": unit_id,
            "tenant_id": tenant_id,
            "start_date": start_date,
            "end_date": end_date,
            "monthly_rent": rent,
        },
        headers=headers,
    )


def test_create_and_view_lease_for_owned_property(app, cleanup_records):
    with app.app_context():
        landlord = create_landlord()
        property_obj, unit = create_unit(landlord.id)
        tenant = create_tenant(landlord.id)
        record_owner(cleanup_records, landlord, tenant, property_obj, unit)
        headers = headers_for(landlord.id)

    start = (date.today() + timedelta(days=1)).isoformat()
    with app.test_client() as client:
        response = create_draft(client, headers, unit.id, tenant.id, start)

    assert response.status_code == 201
    lease_data = response.get_json()["lease"]
    assert lease_data["unit_id"] == unit.id
    assert lease_data["tenant_id"] == tenant.id
    assert lease_data["start_date"] == start
    assert lease_data["end_date"] is None
    assert lease_data["monthly_rent"] == "15000.00"
    assert lease_data["is_active"] is False
    cleanup_records["leases"].add(lease_data["id"])

    with app.test_client() as client:
        response = client.get("/api/leases", headers=headers)
        detail = client.get(f"/api/leases/{lease_data['id']}", headers=headers)

    assert response.status_code == 200
    assert response.get_json()["count"] == 1
    assert response.get_json()["leases"][0]["id"] == lease_data["id"]
    assert detail.status_code == 200
    assert detail.get_json()["lease"]["tenant_id"] == tenant.id


def test_create_lease_commit_failure_rolls_back(app, cleanup_records, monkeypatch):
    with app.app_context():
        landlord = create_landlord()
        property_obj, unit = create_unit(landlord.id)
        tenant = create_tenant(landlord.id)
        record_owner(cleanup_records, landlord, tenant, property_obj, unit)
        headers = headers_for(landlord.id)

    rollback_calls = []
    original_rollback = Session.rollback

    def fail_commit(session):
        raise SQLAlchemyError("simulated database commit failure")

    def track_rollback(session):
        rollback_calls.append(True)
        return original_rollback(session)

    monkeypatch.setattr(Session, "commit", fail_commit)
    monkeypatch.setattr(Session, "rollback", track_rollback)

    start = (date.today() + timedelta(days=1)).isoformat()
    with app.test_client() as client:
        response = create_draft(client, headers, unit.id, tenant.id, start)

    assert response.status_code == 500
    assert response.get_json()["error"] == "Unable to create lease right now."
    assert rollback_calls

    with app.app_context():
        assert Lease.query.filter_by(unit_id=unit.id, tenant_id=tenant.id).count() == 0


@pytest.mark.parametrize(
    ("start_date", "end_date", "rent"),
    [
        ("2026-02-30", None, "100.00"),
        ("2026-01-10", "2026-01-09", "100.00"),
        ("2026-01-10", None, "-1.00"),
        ("2026-01-10", None, "1.234"),
        ("2026-01-10", None, True),
    ],
)
def test_create_lease_validates_dates_and_rent(
    app, cleanup_records, start_date, end_date, rent
):
    with app.app_context():
        landlord = create_landlord()
        property_obj, unit = create_unit(landlord.id)
        tenant = create_tenant(landlord.id)
        record_owner(cleanup_records, landlord, tenant, property_obj, unit)
        headers = headers_for(landlord.id)

    with app.test_client() as client:
        response = create_draft(
            client, headers, unit.id, tenant.id, start_date, end_date, rent
        )

    assert response.status_code == 400


def test_create_lease_requires_unit_and_tenant_owned_by_landlord(app, cleanup_records):
    with app.app_context():
        landlord_a = create_landlord()
        landlord_b = create_landlord()
        property_b, unit_b = create_unit(landlord_b.id)
        tenant_b = create_tenant(landlord_b.id)
        property_a, unit_a = create_unit(landlord_a.id)
        tenant_a = create_tenant(landlord_a.id)
        record_owner(cleanup_records, landlord_a, tenant_a, property_a, unit_a)
        record_owner(cleanup_records, landlord_b, tenant_b, property_b, unit_b)
        headers = headers_for(landlord_a.id)

    start = (date.today() + timedelta(days=1)).isoformat()
    with app.test_client() as client:
        foreign_unit = create_draft(
            client, headers, unit_b.id, tenant_a.id, start
        )
        foreign_tenant = create_draft(
            client, headers, unit_a.id, tenant_b.id, start
        )

    assert foreign_unit.status_code == 404
    assert foreign_tenant.status_code == 404


def test_create_lease_rejects_inactive_unit(app, cleanup_records):
    with app.app_context():
        landlord = create_landlord()
        property_obj, unit = create_unit(landlord.id, is_active=False)
        tenant = create_tenant(landlord.id)
        record_owner(cleanup_records, landlord, tenant, property_obj, unit)
        headers = headers_for(landlord.id)

    start = (date.today() + timedelta(days=1)).isoformat()
    with app.test_client() as client:
        response = create_draft(client, headers, unit.id, tenant.id, start)

    assert response.status_code == 409


def test_activation_rejects_unit_that_became_inactive(app, cleanup_records):
    with app.app_context():
        landlord = create_landlord()
        property_obj, unit = create_unit(landlord.id)
        tenant = create_tenant(landlord.id)
        record_owner(cleanup_records, landlord, tenant, property_obj, unit)
        headers = headers_for(landlord.id)

    start = (date.today() + timedelta(days=1)).isoformat()
    with app.test_client() as client:
        response = create_draft(client, headers, unit.id, tenant.id, start)
        lease_id = response.get_json()["lease"]["id"]
        cleanup_records["leases"].add(lease_id)

        with app.app_context():
            Unit.query.filter_by(id=unit.id).update({"is_active": False})
            db.session.commit()

        activation = client.post(
            f"/api/leases/{lease_id}/activate", headers=headers
        )

    assert activation.status_code == 409


def test_active_leases_cannot_overlap_on_same_unit(app, cleanup_records):
    with app.app_context():
        landlord = create_landlord()
        property_obj, unit = create_unit(landlord.id)
        tenant_a = create_tenant(landlord.id)
        tenant_b = create_tenant(landlord.id)
        record_owner(cleanup_records, landlord, tenant_a, property_obj, unit)
        cleanup_records["tenants"].add(tenant_b.id)
        headers = headers_for(landlord.id)

    start_a = date.today() + timedelta(days=10)
    end_a = start_a + timedelta(days=20)
    start_b = end_a
    end_b = start_b + timedelta(days=20)
    with app.test_client() as client:
        first = create_draft(
            client, headers, unit.id, tenant_a.id, start_a.isoformat(), end_a.isoformat()
        )
        second = create_draft(
            client, headers, unit.id, tenant_b.id, start_b.isoformat(), end_b.isoformat()
        )
        first_id = first.get_json()["lease"]["id"]
        second_id = second.get_json()["lease"]["id"]
        cleanup_records["leases"].update({first_id, second_id})
        activation = client.post(f"/api/leases/{first_id}/activate", headers=headers)
        conflict = client.post(f"/api/leases/{second_id}/activate", headers=headers)

    assert first.status_code == 201
    assert second.status_code == 201
    assert activation.status_code == 200
    assert conflict.status_code == 409


def test_reactivating_an_active_lease_returns_conflict(app, cleanup_records):
    with app.app_context():
        landlord = create_landlord()
        property_obj, unit = create_unit(landlord.id)
        tenant = create_tenant(landlord.id)
        record_owner(cleanup_records, landlord, tenant, property_obj, unit)
        headers = headers_for(landlord.id)

    start = (date.today() + timedelta(days=1)).isoformat()
    with app.test_client() as client:
        response = create_draft(client, headers, unit.id, tenant.id, start)
        lease_id = response.get_json()["lease"]["id"]
        cleanup_records["leases"].add(lease_id)
        first_activation = client.post(
            f"/api/leases/{lease_id}/activate", headers=headers
        )
        second_activation = client.post(
            f"/api/leases/{lease_id}/activate", headers=headers
        )

    assert first_activation.status_code == 200
    assert second_activation.status_code == 409


def test_lease_with_past_end_date_cannot_be_activated(app, cleanup_records):
    with app.app_context():
        landlord = create_landlord()
        property_obj, unit = create_unit(landlord.id)
        tenant = create_tenant(landlord.id)
        record_owner(cleanup_records, landlord, tenant, property_obj, unit)
        headers = headers_for(landlord.id)

    start = date.today() - timedelta(days=10)
    end = date.today() - timedelta(days=1)
    with app.test_client() as client:
        response = create_draft(
            client, headers, unit.id, tenant.id, start.isoformat(), end.isoformat()
        )
        lease_id = response.get_json()["lease"]["id"]
        cleanup_records["leases"].add(lease_id)
        activation = client.post(
            f"/api/leases/{lease_id}/activate", headers=headers
        )

    assert response.status_code == 201
    assert activation.status_code == 400


def test_non_overlapping_active_leases_can_share_a_unit_over_time(app, cleanup_records):
    with app.app_context():
        landlord = create_landlord()
        property_obj, unit = create_unit(landlord.id)
        tenants = [create_tenant(landlord.id), create_tenant(landlord.id)]
        record_owner(cleanup_records, landlord, tenants[0], property_obj, unit)
        cleanup_records["tenants"].add(tenants[1].id)
        headers = headers_for(landlord.id)

    start_a = date.today() + timedelta(days=5)
    end_a = start_a + timedelta(days=4)
    start_b = end_a + timedelta(days=1)
    with app.test_client() as client:
        first = create_draft(
            client, headers, unit.id, tenants[0].id, start_a.isoformat(), end_a.isoformat()
        )
        second = create_draft(
            client, headers, unit.id, tenants[1].id, start_b.isoformat()
        )
        first_id = first.get_json()["lease"]["id"]
        second_id = second.get_json()["lease"]["id"]
        cleanup_records["leases"].update({first_id, second_id})
        first_activation = client.post(f"/api/leases/{first_id}/activate", headers=headers)
        second_activation = client.post(f"/api/leases/{second_id}/activate", headers=headers)

    assert first_activation.status_code == 200
    assert second_activation.status_code == 200


def test_ending_lease_deactivates_it_and_releases_unit(app, cleanup_records):
    with app.app_context():
        landlord = create_landlord()
        property_obj, unit = create_unit(landlord.id)
        tenants = [create_tenant(landlord.id), create_tenant(landlord.id)]
        record_owner(cleanup_records, landlord, tenants[0], property_obj, unit)
        cleanup_records["tenants"].add(tenants[1].id)
        headers = headers_for(landlord.id)

    start_a = date.today() - timedelta(days=2)
    start_b = date.today() + timedelta(days=1)
    with app.test_client() as client:
        first = create_draft(client, headers, unit.id, tenants[0].id, start_a.isoformat())
        second = create_draft(client, headers, unit.id, tenants[1].id, start_b.isoformat())
        first_id = first.get_json()["lease"]["id"]
        second_id = second.get_json()["lease"]["id"]
        cleanup_records["leases"].update({first_id, second_id})
        activation = client.post(f"/api/leases/{first_id}/activate", headers=headers)
        ending = client.post(f"/api/leases/{first_id}/end", headers=headers)
        next_activation = client.post(f"/api/leases/{second_id}/activate", headers=headers)

    assert activation.status_code == 200
    assert ending.status_code == 200
    ended_lease = ending.get_json()["lease"]
    assert ended_lease["is_active"] is False
    assert ended_lease["end_date"] == date.today().isoformat()
    assert next_activation.status_code == 200


def test_ending_lease_records_requested_effective_date(app, cleanup_records):
    with app.app_context():
        landlord = create_landlord()
        property_obj, unit = create_unit(landlord.id)
        tenant = create_tenant(landlord.id)
        record_owner(cleanup_records, landlord, tenant, property_obj, unit)
        headers = headers_for(landlord.id)

    start = date.today() - timedelta(days=3)
    effective_end = date.today() - timedelta(days=1)
    with app.test_client() as client:
        response = create_draft(client, headers, unit.id, tenant.id, start.isoformat())
        lease_id = response.get_json()["lease"]["id"]
        cleanup_records["leases"].add(lease_id)
        activation = client.post(f"/api/leases/{lease_id}/activate", headers=headers)
        ending = client.post(
            f"/api/leases/{lease_id}/end",
            json={"end_date": effective_end.isoformat()},
            headers=headers,
        )

    assert activation.status_code == 200
    assert ending.status_code == 200
    assert ending.get_json()["lease"]["end_date"] == effective_end.isoformat()
    assert ending.get_json()["lease"]["is_active"] is False


def test_end_date_before_start_is_rejected_without_ending_lease(app, cleanup_records):
    with app.app_context():
        landlord = create_landlord()
        property_obj, unit = create_unit(landlord.id)
        tenant = create_tenant(landlord.id)
        record_owner(cleanup_records, landlord, tenant, property_obj, unit)
        headers = headers_for(landlord.id)

    start = date.today() + timedelta(days=2)
    with app.test_client() as client:
        response = create_draft(client, headers, unit.id, tenant.id, start.isoformat())
        lease_id = response.get_json()["lease"]["id"]
        cleanup_records["leases"].add(lease_id)
        activation = client.post(f"/api/leases/{lease_id}/activate", headers=headers)
        invalid_end = client.post(
            f"/api/leases/{lease_id}/end",
            json={"end_date": date.today().isoformat()},
            headers=headers,
        )
        detail = client.get(f"/api/leases/{lease_id}", headers=headers)

    assert activation.status_code == 200
    assert invalid_end.status_code == 400
    assert detail.get_json()["lease"]["is_active"] is True


def test_future_end_date_is_rejected_without_ending_lease(app, cleanup_records):
    with app.app_context():
        landlord = create_landlord()
        property_obj, unit = create_unit(landlord.id)
        tenant = create_tenant(landlord.id)
        record_owner(cleanup_records, landlord, tenant, property_obj, unit)
        headers = headers_for(landlord.id)

    start = date.today() - timedelta(days=1)
    with app.test_client() as client:
        response = create_draft(client, headers, unit.id, tenant.id, start.isoformat())
        lease_id = response.get_json()["lease"]["id"]
        cleanup_records["leases"].add(lease_id)
        activation = client.post(f"/api/leases/{lease_id}/activate", headers=headers)
        future_end = client.post(
            f"/api/leases/{lease_id}/end",
            json={"end_date": (date.today() + timedelta(days=1)).isoformat()},
            headers=headers,
        )

    assert activation.status_code == 200
    assert future_end.status_code == 400


def test_malformed_end_date_is_rejected_without_ending_lease(app, cleanup_records):
    with app.app_context():
        landlord = create_landlord()
        property_obj, unit = create_unit(landlord.id)
        tenant = create_tenant(landlord.id)
        record_owner(cleanup_records, landlord, tenant, property_obj, unit)
        headers = headers_for(landlord.id)

    start = date.today() - timedelta(days=1)
    with app.test_client() as client:
        response = create_draft(client, headers, unit.id, tenant.id, start.isoformat())
        lease_id = response.get_json()["lease"]["id"]
        cleanup_records["leases"].add(lease_id)
        activation = client.post(f"/api/leases/{lease_id}/activate", headers=headers)
        invalid_end = client.post(
            f"/api/leases/{lease_id}/end",
            json={"end_date": "not-a-date"},
            headers=headers,
        )

    assert activation.status_code == 200
    assert invalid_end.status_code == 400


def test_other_landlord_cannot_view_activate_or_end_lease(app, cleanup_records):
    with app.app_context():
        owner = create_landlord()
        other = create_landlord()
        property_obj, unit = create_unit(owner.id)
        tenant = create_tenant(owner.id)
        record_owner(cleanup_records, owner, tenant, property_obj, unit)
        cleanup_records["users"].add(other.id)
        owner_headers = headers_for(owner.id)
        other_headers = headers_for(other.id)

    start = (date.today() + timedelta(days=1)).isoformat()
    with app.test_client() as client:
        response = create_draft(client, owner_headers, unit.id, tenant.id, start)
        lease_id = response.get_json()["lease"]["id"]
        cleanup_records["leases"].add(lease_id)
        other_list = client.get("/api/leases", headers=other_headers)
        other_detail = client.get(f"/api/leases/{lease_id}", headers=other_headers)
        other_activate = client.post(
            f"/api/leases/{lease_id}/activate", headers=other_headers
        )
        other_end = client.post(f"/api/leases/{lease_id}/end", headers=other_headers)

    assert other_list.status_code == 200
    assert other_list.get_json()["count"] == 0
    assert other_detail.status_code == 404
    assert other_activate.status_code == 404
    assert other_end.status_code == 404


@pytest.mark.parametrize(
    ("method", "path", "json"),
    [
        ("post", "/api/leases", {}),
        ("get", "/api/leases", None),
        ("get", "/api/leases/1", None),
        ("post", "/api/leases/1/activate", None),
        ("post", "/api/leases/1/end", None),
    ],
)
def test_lease_endpoints_require_authentication(app, method, path, json):
    with app.test_client() as client:
        response = getattr(client, method)(path, json=json)

    assert response.status_code == 401


@pytest.mark.parametrize(
    ("method", "path", "json"),
    [
        ("post", "/api/leases", {}),
        ("get", "/api/leases", None),
        ("get", "/api/leases/1", None),
        ("post", "/api/leases/1/activate", None),
        ("post", "/api/leases/1/end", None),
    ],
)
def test_manager_role_is_rejected_on_lease_endpoints(
    app, cleanup_records, method, path, json
):
    with app.app_context():
        manager = User(
            full_name="Lease API Test Manager",
            email=f"lease.manager.{uuid.uuid4().hex}@example.com",
            role="manager",
        )
        manager.set_password("SecureLeasePassword123!")
        db.session.add(manager)
        db.session.commit()
        cleanup_records["users"].add(manager.id)
        headers = headers_for(manager.id)

    with app.test_client() as client:
        response = getattr(client, method)(path, json=json, headers=headers)

    assert response.status_code == 403
