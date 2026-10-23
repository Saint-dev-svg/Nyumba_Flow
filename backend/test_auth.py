import uuid

import pytest
from flask_jwt_extended import create_access_token

from test_config import create_test_app
from extensions import db
from models import User


@pytest.fixture
def app():
    return create_test_app()


@pytest.fixture
def cleanup_users(app):
    emails = set()
    yield emails.add

    with app.app_context():
        User.query.filter(User.email.in_(emails)).delete(synchronize_session=False)
        db.session.commit()


def unique_email(prefix):
    return f"{prefix}.{uuid.uuid4().hex}@example.com"


def create_user(email, password, full_name="Test Landlord"):
    user = User(full_name=full_name, email=email, role="landlord")
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return user


def test_register_landlord(app, cleanup_users):
    email = unique_email("test.landlord")
    cleanup_users(email)

    with app.test_client() as client:
        response = client.post(
            "/api/auth/register",
            json={
                "full_name": "Test Landlord",
                "email": email,
                "password": "SecureTestPassword123!",
            },
        )

    assert response.status_code == 201

    with app.app_context():
        user = User.query.filter_by(email=email).first()

        assert user is not None
        assert user.password_hash != "SecureTestPassword123!"
        assert user.check_password("SecureTestPassword123!")
        assert user.role == "landlord"


def test_login_with_correct_credentials(app, cleanup_users):
    email = unique_email("login.test")
    cleanup_users(email)

    with app.app_context():
        create_user(email, "SecureLoginPassword123!")

    with app.test_client() as client:
        response = client.post(
            "/api/auth/login",
            json={"email": email, "password": "SecureLoginPassword123!"},
        )

    assert response.status_code == 200
    body = response.get_json()
    assert body["message"] == "Login successful!"
    assert body["user"]["email"] == email
    assert "access_token" in body


def test_login_with_wrong_password(app, cleanup_users):
    email = unique_email("login.test")
    cleanup_users(email)

    with app.app_context():
        create_user(email, "SecureLoginPassword123!")

    with app.test_client() as client:
        response = client.post(
            "/api/auth/login",
            json={"email": email, "password": "IncorrectPassword123!"},
        )

    assert response.status_code == 401
    assert response.get_json()["error"] == "Invalid email or password!"


def test_me_rejects_request_without_token(app):
    with app.test_client() as client:
        response = client.get("/api/auth/me")

    assert response.status_code == 401


def test_me_accepts_valid_token(app, cleanup_users):
    email = unique_email("protected.route.test")
    cleanup_users(email)

    with app.app_context():
        user = create_user(email, "SecureProtectedPassword123!")
        user_id = user.id
        token = create_access_token(identity=str(user_id))

    with app.test_client() as client:
        response = client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    body = response.get_json()
    assert body["user"]["id"] == user_id
    assert body["user"]["email"] == email
