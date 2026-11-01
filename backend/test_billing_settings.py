
"""API tests for landlord billing settings."""

import uuid

import pytest
from flask_jwt_extended import create_access_token

from extensions import db
from models import User, LandlordBillingSettings
from test_config import create_test_app


@pytest.fixture
def app():
    return create_test_app()


@pytest.fixture
def cleanup_users(app):
    user_ids = set()

    yield user_ids

    with app.app_context():
        if user_ids:
            LandlordBillingSettings.query.filter(
                LandlordBillingSettings.landlord_id.in_(user_ids)
            ).delete(synchronize_session=False)

            User.query.filter(
                User.id.in_(user_ids)
            ).delete(synchronize_session=False)

            db.session.commit()


def create_landlord():
    user = User(
        full_name="Billing Settings Test Landlord",
        email=f"billing.{uuid.uuid4().hex}@example.com",
        role="landlord",
    )
    user.set_password("SecureBillingPassword123!")

    db.session.add(user)
    db.session.commit()

    return user


def auth_headers(user_id):
    token = create_access_token(identity=str(user_id))
    return {"Authorization": f"Bearer {token}"}


def test_get_settings_requires_authentication(app):
    with app.test_client() as client:
        response = client.get("/api/billing-settings")

    assert response.status_code == 401


def test_get_settings_creates_default_settings(app, cleanup_users):
    with app.app_context():
        landlord = create_landlord()
        cleanup_users.add(landlord.id)

        with app.test_client() as client:
            response = client.get(
                "/api/billing-settings",
                headers=auth_headers(landlord.id),
            )

        assert response.status_code == 200
        assert response.get_json() == {
            "rent_due_day": 1,
            "utilities_due_day": 1,
        }

        settings = LandlordBillingSettings.query.filter_by(
            landlord_id=landlord.id
        ).first()

        assert settings is not None


def test_update_both_due_days(app, cleanup_users):
    with app.app_context():
        landlord = create_landlord()
        cleanup_users.add(landlord.id)

        with app.test_client() as client:
            response = client.put(
                "/api/billing-settings",
                headers=auth_headers(landlord.id),
                json={
                    "rent_due_day": 5,
                    "utilities_due_day": 10,
                },
            )

            assert response.status_code == 200
            assert response.get_json()["rent_due_day"] == 5
            assert response.get_json()["utilities_due_day"] == 10

            get_response = client.get(
                "/api/billing-settings",
                headers=auth_headers(landlord.id),
            )

            assert get_response.get_json() == {
                "rent_due_day": 5,
                "utilities_due_day": 10,
            }


def test_partial_update_preserves_other_setting(app, cleanup_users):
    with app.app_context():
        landlord = create_landlord()
        cleanup_users.add(landlord.id)

        with app.test_client() as client:
            client.put(
                "/api/billing-settings",
                headers=auth_headers(landlord.id),
                json={
                    "rent_due_day": 7,
                    "utilities_due_day": 12,
                },
            )

            response = client.put(
                "/api/billing-settings",
                headers=auth_headers(landlord.id),
                json={"rent_due_day": 15},
            )

            assert response.status_code == 200
            assert response.get_json()["rent_due_day"] == 15
            assert response.get_json()["utilities_due_day"] == 12


@pytest.mark.parametrize(
    "field,value",
    [
        ("rent_due_day", 0),
        ("rent_due_day", 29),
        ("rent_due_day", True),
        ("rent_due_day", 5.5),
        ("rent_due_day", "5"),
        ("utilities_due_day", 0),
        ("utilities_due_day", 29),
        ("utilities_due_day", False),
        ("utilities_due_day", 10.5),
        ("utilities_due_day", "10"),
    ],
)
def test_update_rejects_invalid_due_days(app, cleanup_users, field, value):
    with app.app_context():
        landlord = create_landlord()
        cleanup_users.add(landlord.id)

        with app.test_client() as client:
            response = client.put(
                "/api/billing-settings",
                headers=auth_headers(landlord.id),
                json={field: value},
            )

        assert response.status_code == 400


def test_update_rejects_unknown_fields(app, cleanup_users):
    with app.app_context():
        landlord = create_landlord()
        cleanup_users.add(landlord.id)

        with app.test_client() as client:
            response = client.put(
                "/api/billing-settings",
                headers=auth_headers(landlord.id),
                json={
                    "rent_due_day": 5,
                    "water_due_day": 10,
                },
            )

        assert response.status_code == 400


def test_update_rejects_empty_json(app, cleanup_users):
    with app.app_context():
        landlord = create_landlord()
        cleanup_users.add(landlord.id)

        with app.test_client() as client:
            response = client.put(
                "/api/billing-settings",
                headers=auth_headers(landlord.id),
                json={},
            )

        assert response.status_code == 400


def test_landlords_have_independent_settings(app, cleanup_users):
    with app.app_context():
        landlord_one = create_landlord()
        landlord_two = create_landlord()

        cleanup_users.update({
            landlord_one.id,
            landlord_two.id,
        })

        with app.test_client() as client:
            client.put(
                "/api/billing-settings",
                headers=auth_headers(landlord_one.id),
                json={
                    "rent_due_day": 5,
                    "utilities_due_day": 8,
                },
            )

            client.put(
                "/api/billing-settings",
                headers=auth_headers(landlord_two.id),
                json={
                    "rent_due_day": 15,
                    "utilities_due_day": 20,
                },
            )

            first_response = client.get(
                "/api/billing-settings",
                headers=auth_headers(landlord_one.id),
            )

            second_response = client.get(
                "/api/billing-settings",
                headers=auth_headers(landlord_two.id),
            )

        assert first_response.get_json() == {
            "rent_due_day": 5,
            "utilities_due_day": 8,
        }

        assert second_response.get_json() == {
            "rent_due_day": 15,
            "utilities_due_day": 20,
        }
