import uuid

from flask_jwt_extended import create_access_token

from extensions import db
from models import Property, Unit
from test_config import create_test_app

from test_properties import create_test_user


def create_test_property(owner_id):
    property_obj = Property(
        owner_id=owner_id,
        name=f"Unit Test Property {uuid.uuid4().hex}",
        address="Rongai, Kenya",
    )
    db.session.add(property_obj)
    db.session.commit()
    return property_obj


def test_create_unit_with_valid_token():
    app = create_test_app()

    with app.app_context():
        user = create_test_user(f"unit.owner.{uuid.uuid4().hex}@example.com")
        property_obj = create_test_property(user.id)
        property_id = property_obj.id
        token = create_access_token(identity=str(user.id))

    with app.test_client() as client:
        response = client.post(
            f"/api/properties/{property_id}/units",
            json={
                "unit_number": "A1",
                "bedrooms": 2,
                "monthly_rent": "15000.00",
            },
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 201
    body = response.get_json()
    assert body["unit"]["unit_number"] == "A1"
    assert body["unit"]["bedrooms"] == 2
    assert body["unit"]["monthly_rent"] == "15000.00"


def test_create_unit_without_token():
    app = create_test_app()

    with app.app_context():
        user = create_test_user(f"unit.no_token.{uuid.uuid4().hex}@example.com")
        property_obj = create_test_property(user.id)
        property_id = property_obj.id

    with app.test_client() as client:
        response = client.post(
            f"/api/properties/{property_id}/units",
            json={
                "unit_number": "A2",
                "bedrooms": 1,
                "monthly_rent": "10000.00",
            },
        )

    assert response.status_code == 401


def test_create_unit_rejects_negative_bedrooms():
    app = create_test_app()

    with app.app_context():
        user = create_test_user(f"unit.bedrooms.{uuid.uuid4().hex}@example.com")
        property_obj = create_test_property(user.id)
        property_id = property_obj.id
        token = create_access_token(identity=str(user.id))

    with app.test_client() as client:
        response = client.post(
            f"/api/properties/{property_id}/units",
            json={
                "unit_number": "A3",
                "bedrooms": -1,
                "monthly_rent": "10000.00",
            },
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 400


def test_create_duplicate_unit_number_returns_conflict():
    app = create_test_app()

    with app.app_context():
        user = create_test_user(f"unit.duplicate.{uuid.uuid4().hex}@example.com")
        property_obj = create_test_property(user.id)
        property_id = property_obj.id
        token = create_access_token(identity=str(user.id))

    payload = {
        "unit_number": "A1",
        "bedrooms": 1,
        "monthly_rent": "12000.00",
    }

    with app.test_client() as client:
        headers = {"Authorization": f"Bearer {token}"}
        first_response = client.post(
            f"/api/properties/{property_id}/units",
            json=payload,
            headers=headers,
        )
        second_response = client.post(
            f"/api/properties/{property_id}/units",
            json=payload,
            headers=headers,
        )

    assert first_response.status_code == 201
    assert second_response.status_code == 409


def test_landlord_cannot_create_unit_in_another_landlords_property():
    app = create_test_app()

    with app.app_context():
        landlord_a = create_test_user(
            f"unit.landlord.a.{uuid.uuid4().hex}@example.com"
        )
        landlord_b = create_test_user(
            f"unit.landlord.b.{uuid.uuid4().hex}@example.com"
        )
        property_b = create_test_property(landlord_b.id)
        property_id = property_b.id
        token_a = create_access_token(identity=str(landlord_a.id))

    with app.test_client() as client:
        response = client.post(
            f"/api/properties/{property_id}/units",
            json={
                "unit_number": "A4",
                "bedrooms": 1,
                "monthly_rent": "10000.00",
            },
            headers={"Authorization": f"Bearer {token_a}"},
        )

    assert response.status_code == 404


def test_list_units_returns_only_units_in_requested_property():
    app = create_test_app()

    with app.app_context():
        user = create_test_user(f"unit.list.{uuid.uuid4().hex}@example.com")
        property_a = create_test_property(user.id)
        property_b = create_test_property(user.id)

        unit_a = Unit(
            property_id=property_a.id,
            unit_number="A1",
            bedrooms=1,
            monthly_rent="10000.00",
        )
        unit_b = Unit(
            property_id=property_b.id,
            unit_number="B1",
            bedrooms=2,
            monthly_rent="15000.00",
        )
        db.session.add_all([unit_a, unit_b])
        db.session.commit()

        property_a_id = property_a.id
        token = create_access_token(identity=str(user.id))

    with app.test_client() as client:
        response = client.get(
            f"/api/properties/{property_a_id}/units",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    body = response.get_json()
    assert body["count"] == 1
    assert body["units"][0]["unit_number"] == "A1"


def test_list_units_requires_authentication():
    app = create_test_app()

    with app.app_context():
        user = create_test_user(f"unit.list.auth.{uuid.uuid4().hex}@example.com")
        property_obj = create_test_property(user.id)
        property_id = property_obj.id

    with app.test_client() as client:
        response = client.get(f"/api/properties/{property_id}/units")

    assert response.status_code == 401