from flask import Blueprint, request, jsonify
from sqlalchemy import func
from flask_jwt_extended import (
    create_access_token, jwt_required, get_jwt_identity,
)

from extensions import db
from models import User


auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")


@auth_bp.post("/register")
def register():
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be valid JSON!"}), 400

    full_name = data.get("full_name")
    email = data.get("email")
    password = data.get("password")
    role = data.get("role", "landlord")

    if not all(isinstance(value, str) for value in (full_name, email, password, role)):
        return jsonify({
            "error": "Full name, email, password, and role must be strings."
        }), 400

    full_name = full_name.strip()
    email = email.strip().lower()
    role = role.strip().lower()

    if not full_name or len(full_name) > 120:
        return jsonify({
            "error": "Full name is required and must be at most 120 characters!"
        }), 400

    if not email or len(email) > 255 or "@" not in email:
        return jsonify({"error": "A valid email address is required!"}), 400

    if len(password) < 12 or len(password) > 128:
        return jsonify({
            "error": "Password must be between 12 and 128 characters."
        }), 400

    if role not in {"landlord", "manager"}:
        return jsonify({"error": "Invalid role!"}), 400

    # A public registration endpoint must never let someone grant themselves
    # manager privileges. Manager accounts will be provisioned by an authorized
    # landlord through a separate workflow.
    if role != "landlord":
        return jsonify({
            "error": "Manager accounts must be created by an authorized landlord!"
        }), 403

    existing_user = db.session.query(User.id).filter(
        func.lower(User.email) == email
    ).first()

    if existing_user:
        return jsonify({"error": "An account with this email already exists!"}), 409

    user = User(
        full_name=full_name,
        email=email,
        role="landlord",
    )
    user.set_password(password)

    try:
        db.session.add(user)
        db.session.commit()
    except Exception:
        db.session.rollback()
        auth_bp.logger.exception("Account registration failed")
        return jsonify({"error": "Unable to create account right now!"}), 500

    access_token = create_access_token(identity=str(user.id))

    return jsonify({
        "message": "Account created successfully.",
        "user": {
            "id": user.id,
            "full_name": user.full_name,
            "email": user.email,
            "role": user.role,
        },
        "access_token": access_token,
    }), 201
    

@auth_bp.post("/login")
def login():
    data = request.get_json(silent = True)
    
    if not isinstance(data, dict):
        return jsonify(
            {
                "error" : "Request body must be valid JSON!"
            }
        ), 400
        
    email = data.get("email")
    password = data.get("password")
        
    if not isinstance(email, str) or not isinstance(password, str):
        return jsonify(
            {
                "error" : "Email and password are required!"
            }
        ), 400
        
    email = email.strip().lower()
    
    if not email or not password:
        return jsonify(
            {
                "error" : "Email and password are required!"
            }
        ), 400
        
    user = User.query.filter(
        func.lower(User.email) == email
    ).first()
    
    if user is None or not user.check_password(password):
        return jsonify(
            {
                "error" : "Invalid email or password!"
            }
        ), 401
        
    access_token = create_access_token(identity=str(user.id))
    
    return jsonify(
        {
            "message" : "Login successful!", 
            "user" : {
                "id" : user.id,
                "full_name" : user.full_name,
                "email" : user.email,
                "role" : user.role,
            },
            "access_token" : access_token
        }
    ), 200
        
    

@auth_bp.get("/me")
@jwt_required()
def get_current_user():
    user_id = get_jwt_identity()

    user = db.session.get(User, int(user_id))

    if user is None:
        return jsonify({"error": "User account not found."}), 404

    return jsonify({
        "user": {
            "id": user.id,
            "full_name": user.full_name,
            "email": user.email,
            "role": user.role,
        }
    }), 200

        
    