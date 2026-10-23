from test_config import create_test_app
from extensions import db
from models import User, Property
from flask_jwt_extended import create_access_token
import uuid


def create_test_user(email, *, role="landlord"):
    user = User.query.filter_by(email=email).first()

    if user is None:
        user = User(
            full_name="Property Test Landlord",
            email=email,
            role=role,
        )
        user.set_password("SecurePropertyPassword123!")
        db.session.add(user)
        db.session.commit()

    return user


def test_create_property_with_valid_token():
    app = create_test_app()
    email = "property.create.test@example.com"

    with app.app_context():
        user = create_test_user(email)
        token = create_access_token(identity=str(user.id))

    with app.test_client() as client:
        response = client.post(
            "/api/properties",
            json={
                "name": f"Sunrise Apartments Test {uuid.uuid4().hex}",
                "address": "Rongai, Kenya",
            },
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 201

    body = response.get_json()
    assert body["property"]["name"].startswith("Sunrise Apartments Test ")
    assert body["property"]["address"] == "Rongai, Kenya"
    assert body["property"]["id"] is not None


def test_create_property_without_token():
    app = create_test_app()
    with app.test_client() as client:
        response = client.post(
            "/api/properties",
            json={
                "name": "Unauthorized Property",
                "address": "Rongai, Kenya",
            },
        )

    assert response.status_code == 401


def test_create_property_rejects_missing_fields():
    app = create_test_app()
    with app.app_context():
        user = create_test_user("property.validation.test@example.com")
        token = create_access_token(identity=str(user.id))

    with app.test_client() as client:
        response = client.post(
            "/api/properties",
            json={"name": "", "address": "Rongai, Kenya"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 400


def test_create_duplicate_property_name_returns_conflict():
    app = create_test_app()
    email = "property.duplicate.test@example.com"

    with app.app_context():
        user = create_test_user(email)
        token = create_access_token(identity=str(user.id))

    payload = {
        "name": f"Duplicate Test Apartments {uuid.uuid4().hex}",
        "address": "Rongai, Kenya",
    }

    with app.test_client() as client:
        headers = {"Authorization": f"Bearer {token}"}

        first_response = client.post(
            "/api/properties", json=payload, headers=headers
        )
        second_response = client.post(
            "/api/properties", json=payload, headers=headers
        )

    assert first_response.status_code == 201
    assert second_response.status_code == 409


def test_list_properties_returns_only_current_landlords_properties():
    app = create_test_app()
    with app.app_context():
        landlord_a = create_test_user("property.list.a@example.com")
        landlord_b = create_test_user("property.list.b@example.com")

        property_a = Property.query.filter_by(
            owner_id=landlord_a.id,
            name="Landlord A Test Property",
        ).first()

        if property_a is None:
            property_a = Property(
                owner_id=landlord_a.id,
                name="Landlord A Test Property",
                address="Rongai, Kenya",
            )
            db.session.add(property_a)

        property_b = Property.query.filter_by(
            owner_id=landlord_b.id,
            name="Landlord B Test Property",
        ).first()

        if property_b is None:
            property_b = Property(
                owner_id=landlord_b.id,
                name="Landlord B Test Property",
                address="Kajiado, Kenya",
            )
            db.session.add(property_b)

        db.session.commit()
        token = create_access_token(identity=str(landlord_a.id))

    with app.test_client() as client:
        response = client.get(
            "/api/properties",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200

    body = response.get_json()
    returned_names = [item["name"] for item in body["properties"]]

    assert "Landlord A Test Property" in returned_names
    assert "Landlord B Test Property" not in returned_names
    assert body["count"] == len(body["properties"])


def test_list_properties_requires_authentication():
    app = create_test_app()
    with app.test_client() as client:
        response = client.get("/api/properties")

    assert response.status_code == 401


def test_manager_cannot_create_or_list_properties():
    app = create_test_app()
    email = f"property.manager.{uuid.uuid4().hex}@example.com"

    with app.app_context():
        manager = create_test_user(email, role="manager")
        manager_id = manager.id
        token = create_access_token(identity=str(manager_id))

    headers = {"Authorization": f"Bearer {token}"}
    with app.test_client() as client:
        create_response = client.post(
            "/api/properties",
            json={"name": "Manager Property", "address": "Rongai, Kenya"},
            headers=headers,
        )
        list_response = client.get("/api/properties", headers=headers)

    assert create_response.status_code == 403
    assert list_response.status_code == 403

    with app.app_context():
        manager = db.session.get(User, manager_id)
        db.session.delete(manager)
        db.session.commit()
