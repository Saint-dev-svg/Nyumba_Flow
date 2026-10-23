import uuid

import pytest
from flask_jwt_extended import create_access_token

from extensions import db
from models import Tenant, User
from test_config import create_test_app


@pytest.fixture
def app():
    return create_test_app()


@pytest.fixture
def cleanup_records(app):
    user_emails = set()
    tenant_emails = set()
    yield {"users": user_emails, "tenants": tenant_emails}

    with app.app_context():
        Tenant.query.filter(Tenant.email.in_(tenant_emails)).delete(
            synchronize_session=False
        )
        User.query.filter(User.email.in_(user_emails)).delete(
            synchronize_session=False
        )
        db.session.commit()


def unique_email(prefix):
    return f"{prefix}.{uuid.uuid4().hex}@example.com"


def make_landlord(email, role="landlord"):
    user = User(full_name="Tenant API Test User", email=email, role=role)
    user.set_password("SecureTenantPassword123!")
    db.session.add(user)
    db.session.commit()
    return user


def auth_headers(user_id):
    token = create_access_token(identity=str(user_id))
    return {"Authorization": f"Bearer {token}"}


def tenant_payload(email=None):
    return {
        "full_name": "Amina Njeri",
        "email": email or unique_email("tenant"),
        "phone_number": "+254700123456",
        "national_id_last4": "4821",
    }


def create_tenant(app, owner_id, email):
    tenant = Tenant(
        owner_id=owner_id,
        full_name="Existing Tenant",
        email=email,
    )
    db.session.add(tenant)
    db.session.commit()
    return tenant


def test_register_tenant_under_authenticated_landlord(app, cleanup_records):
    user_email = unique_email("landlord")
    cleanup_records["users"].add(user_email)
    payload = tenant_payload()
    cleanup_records["tenants"].add(payload["email"])

    with app.app_context():
        landlord = make_landlord(user_email)
        headers = auth_headers(landlord.id)

    with app.test_client() as client:
        response = client.post("/api/tenants", json=payload, headers=headers)

    assert response.status_code == 201
    body = response.get_json()
    assert body["tenant"]["email"] == payload["email"]
    assert body["tenant"]["full_name"] == payload["full_name"]

    with app.app_context():
        tenant = Tenant.query.filter_by(email=payload["email"]).one()
        assert tenant.owner_id == landlord.id


def test_list_tenants_returns_only_current_landlords_records(app, cleanup_records):
    email_a = unique_email("landlord.a")
    email_b = unique_email("landlord.b")
    tenant_a_email = unique_email("tenant.a")
    tenant_b_email = unique_email("tenant.b")
    cleanup_records["users"].update({email_a, email_b})
    cleanup_records["tenants"].update({tenant_a_email, tenant_b_email})

    with app.app_context():
        landlord_a = make_landlord(email_a)
        landlord_b = make_landlord(email_b)
        create_tenant(app, landlord_a.id, tenant_a_email)
        create_tenant(app, landlord_b.id, tenant_b_email)
        headers = auth_headers(landlord_a.id)

    with app.test_client() as client:
        response = client.get("/api/tenants", headers=headers)

    assert response.status_code == 200
    body = response.get_json()
    returned_emails = {tenant["email"] for tenant in body["tenants"]}
    assert tenant_a_email in returned_emails
    assert tenant_b_email not in returned_emails
    assert body["count"] == len(body["tenants"])


def test_get_and_update_tenant_require_ownership(app, cleanup_records):
    owner_email = unique_email("owner")
    other_email = unique_email("other.landlord")
    tenant_email = unique_email("tenant.record")
    cleanup_records["users"].update({owner_email, other_email})
    cleanup_records["tenants"].add(tenant_email)

    with app.app_context():
        owner = make_landlord(owner_email)
        other_landlord = make_landlord(other_email)
        tenant = create_tenant(app, owner.id, tenant_email)
        tenant_id = tenant.id
        owner_headers = auth_headers(owner.id)
        other_headers = auth_headers(other_landlord.id)

    with app.test_client() as client:
        get_response = client.get(f"/api/tenants/{tenant_id}", headers=owner_headers)
        update_response = client.patch(
            f"/api/tenants/{tenant_id}",
            json={"full_name": "Amina Updated"},
            headers=owner_headers,
        )
        foreign_get = client.get(f"/api/tenants/{tenant_id}", headers=other_headers)
        foreign_update = client.patch(
            f"/api/tenants/{tenant_id}",
            json={"full_name": "Unauthorized Change"},
            headers=other_headers,
        )

    assert get_response.status_code == 200
    assert get_response.get_json()["tenant"]["email"] == tenant_email
    assert update_response.status_code == 200
    assert update_response.get_json()["tenant"]["full_name"] == "Amina Updated"
    assert foreign_get.status_code == 404
    assert foreign_update.status_code == 404


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {"email": "tenant@example.com"},
        {"full_name": "Amina", "email": "not-an-email"},
        {
            "full_name": "Amina",
            "email": "tenant@example.com",
            "national_id_last4": "12x4",
        },
        {"full_name": "A" * 121, "email": "tenant@example.com"},
        {"full_name": "Amina", "email": "tenant@example.com", "owner_id": 1},
    ],
)
def test_register_tenant_validates_payload(app, cleanup_records, payload):
    user_email = unique_email("landlord")
    cleanup_records["users"].add(user_email)

    with app.app_context():
        landlord = make_landlord(user_email)
        headers = auth_headers(landlord.id)

    with app.test_client() as client:
        response = client.post("/api/tenants", json=payload, headers=headers)

    assert response.status_code == 400


def test_duplicate_tenant_email_returns_conflict_across_landlords(app, cleanup_records):
    first_email = unique_email("landlord.one")
    second_email = unique_email("landlord.two")
    tenant_email = unique_email("duplicate.tenant")
    cleanup_records["users"].update({first_email, second_email})
    cleanup_records["tenants"].add(tenant_email)

    with app.app_context():
        first_landlord = make_landlord(first_email)
        second_landlord = make_landlord(second_email)
        first_headers = auth_headers(first_landlord.id)
        second_headers = auth_headers(second_landlord.id)

    payload = tenant_payload(tenant_email)
    duplicate_payload = tenant_payload(tenant_email.upper())
    with app.test_client() as client:
        first_response = client.post(
            "/api/tenants", json=payload, headers=first_headers
        )
        duplicate_response = client.post(
            "/api/tenants", json=duplicate_payload, headers=second_headers
        )

    assert first_response.status_code == 201
    assert duplicate_response.status_code == 409


def test_update_rejects_duplicate_tenant_email(app, cleanup_records):
    landlord_email = unique_email("landlord")
    first_tenant_email = unique_email("tenant.first")
    second_tenant_email = unique_email("tenant.second")
    cleanup_records["users"].add(landlord_email)
    cleanup_records["tenants"].update({first_tenant_email, second_tenant_email})

    with app.app_context():
        landlord = make_landlord(landlord_email)
        first_tenant = create_tenant(app, landlord.id, first_tenant_email)
        create_tenant(app, landlord.id, second_tenant_email)
        headers = auth_headers(landlord.id)
        first_tenant_id = first_tenant.id

    with app.test_client() as client:
        response = client.patch(
            f"/api/tenants/{first_tenant_id}",
            json={"email": second_tenant_email.upper()},
            headers=headers,
        )

    assert response.status_code == 409


@pytest.mark.parametrize(
    ("method", "path", "json"),
    [
        ("post", "/api/tenants", {"full_name": "Amina", "email": "a@example.com"}),
        ("get", "/api/tenants", None),
        ("get", "/api/tenants/1", None),
        ("patch", "/api/tenants/1", {"full_name": "Amina"}),
    ],
)
def test_tenant_endpoints_require_authentication(app, method, path, json):
    with app.test_client() as client:
        response = getattr(client, method)(path, json=json)

    assert response.status_code == 401


def test_non_landlord_cannot_manage_tenants(app, cleanup_records):
    manager_email = unique_email("manager")
    cleanup_records["users"].add(manager_email)

    with app.app_context():
        manager = make_landlord(manager_email, role="manager")
        headers = auth_headers(manager.id)

    with app.test_client() as client:
        response = client.get("/api/tenants", headers=headers)

    assert response.status_code == 403
