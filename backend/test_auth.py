from app import create_app
from extensions import db
from models import User


def test_register_landlord():
    app = create_app()
    app.config["TESTING"] = True

    with app.test_client() as client:
        response = client.post(
            "/api/auth/register",
            json={
                "full_name": "Test Landlord",
                "email": "test.landlord.10@example.com",
                "password": "SecureTestPassword123!",
            },
        )

        print("Status:", response.status_code)
        print("Response:", response.get_json())

        assert response.status_code == 201

        with app.app_context():
            user = User.query.filter_by(
                email="test.landlord@example.com"
            ).first()

            assert user is not None
            assert user.password_hash != "SecureTestPassword123!"
            assert user.check_password("SecureTestPassword123!")
            assert user.role == "landlord"

            print("Account exists in PostgreSQL.")
            print("Password is hashed correctly.")
            

def test_login_with_correct_credentials():
    app = create_app()
    app.config["TESTING"] = True
    
    with app.test_client() as client:
        #ensure the account exists before attempting login.
        
        with app.app_context():
            existing_user = User.query.filter_by(
                email="login.test.02@example.com"
            ).first()

            if existing_user is None:
                existing_user = User(
                    full_name="Login test Landlord",
                    email="login.test.02@example.com",
                    role="landlord",
                )
                existing_user.set_password("SecureLoginPassword123!")
                db.session.add(existing_user)
                db.session.commit()
        
        response = client.post(
            "/api/auth/login",
            json = {
                "email" : "login.test@example.com",
                "password" : "SecureLoginPassword123!",
            },
        )
        
        assert response.status_code == 200
        
        body = response.get_json()
        assert body["message"] == "Login successful!"
        assert body["user"] ["email"] == "login.test@example.com"
        assert "access_token" in body
        
        print("Login with correct credentials succeeded!")
        
def test_login_with_wrong_password():
    app = create_app()
    app.config["TESTING"] = True
    
    with app.test_client() as client:
        response = client.post(
            "/api/auth/login",
            json = {
                "email" : "login.test@example.com",
                "password" : "secureLoginPassword123!",
            },
        )
        
        assert response.status_code == 401
        assert response.get_json()["error"] == "Invalid email or password!"
        
        print("Incorrect password was rejected!")


def test_me_rejects_request_without_token():
    app = create_app()
    app.config["TESTING"] = True

    with app.test_client() as client:
        response = client.get("/api/auth/me")

        assert response.status_code == 401

        print("Unauthenticated request was rejected.")


def test_me_accepts_valid_token():
    app = create_app()
    app.config["TESTING"] = True

    email = "protected.route.test@example.com"
    password = "SecureProtectedPassword123!"

    with app.app_context():
        user = User.query.filter_by(email=email).first()

        if user is None:
            user = User(
                full_name="Protected Route Test",
                email=email,
                role="landlord",
            )
            user.set_password(password)
            db.session.add(user)
            db.session.commit()

        user_id = user.id

    with app.test_client() as client:
        with app.app_context():
            from flask_jwt_extended import create_access_token
            token = create_access_token(identity=str(user_id))

        response = client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200

        body = response.get_json()
        assert body["user"]["id"] == user_id
        assert body["user"]["email"] == email

        print("Valid token granted access to the current user's profile.")
