from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from extensions import db
from models import Tenant
from authorization import get_current_landlord_id


tenants_bp = Blueprint("tenants", __name__, url_prefix="/api/tenants")

_EDITABLE_FIELDS = {
    "full_name",
    "email",
    "phone_number",
    "national_id_last4",
}


def _tenant_to_dict(tenant):
    return {
        "id": tenant.id,
        "full_name": tenant.full_name,
        "email": tenant.email,
        "phone_number": tenant.phone_number,
        "national_id_last4": tenant.national_id_last4,
        "created_at": tenant.created_at.isoformat(),
    }


def _validate_fields(data, *, partial=False):
    if not isinstance(data, dict):
        return None, "Request body must be valid JSON."

    unknown_fields = set(data) - _EDITABLE_FIELDS
    if unknown_fields:
        return None, "Request contains unsupported fields."
    if partial and not data:
        return None, "At least one tenant field must be provided."

    values = {}
    if not partial or "full_name" in data:
        full_name = data.get("full_name")
        if not isinstance(full_name, str):
            return None, "Full name must be a string."
        full_name = full_name.strip()
        if not full_name or len(full_name) > 120:
            return None, "Full name is required and must be at most 120 characters."
        values["full_name"] = full_name

    if not partial or "email" in data:
        email = data.get("email")
        if not isinstance(email, str):
            return None, "Email must be a string."
        email = email.strip().lower()
        if len(email) > 255 or not email or "@" not in email or any(c.isspace() for c in email):
            return None, "A valid email address is required."
        values["email"] = email

    for field, max_length in (("phone_number", 30), ("national_id_last4", 4)):
        if field not in data:
            if not partial:
                values[field] = None
            continue

        value = data[field]
        if value is None:
            values[field] = None
            continue
        if not isinstance(value, str):
            return None, f"{field.replace('_', ' ').capitalize()} must be a string."

        value = value.strip()
        if not value:
            values[field] = None
        elif field == "phone_number":
            if len(value) > max_length:
                return None, "Phone number must be at most 30 characters."
            values[field] = value
        elif len(value) != 4 or not value.isdigit():
            return None, "National ID last four must contain exactly 4 digits."
        else:
            values[field] = value

    return values, None


def _email_in_use(email, *, excluding_tenant_id=None):
    query = Tenant.query.filter(func.lower(Tenant.email) == email)
    if excluding_tenant_id is not None:
        query = query.filter(Tenant.id != excluding_tenant_id)
    return db.session.query(query.exists()).scalar()


@tenants_bp.post("")
@jwt_required()
def create_tenant():
    landlord_id = get_current_landlord_id()
    if landlord_id is None:
        return jsonify({"error": "An authenticated landlord account is required."}), 403

    values, error = _validate_fields(request.get_json(silent=True))
    if error:
        return jsonify({"error": error}), 400
    if _email_in_use(values["email"]):
        return jsonify({"error": "A tenant with this email already exists."}), 409

    tenant = Tenant(owner_id=landlord_id, **values)
    try:
        db.session.add(tenant)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "A tenant with this email already exists."}), 409

    return jsonify({
        "message": "Tenant created successfully.",
        "tenant": _tenant_to_dict(tenant),
    }), 201


@tenants_bp.get("")
@jwt_required()
def list_tenants():
    landlord_id = get_current_landlord_id()
    if landlord_id is None:
        return jsonify({"error": "An authenticated landlord account is required."}), 403

    tenants = (
        Tenant.query
        .filter_by(owner_id=landlord_id)
        .order_by(Tenant.created_at.desc(), Tenant.id.desc())
        .all()
    )
    return jsonify({
        "tenants": [_tenant_to_dict(tenant) for tenant in tenants],
        "count": len(tenants),
    }), 200


@tenants_bp.get("/<int:tenant_id>")
@jwt_required()
def get_tenant(tenant_id):
    landlord_id = get_current_landlord_id()
    if landlord_id is None:
        return jsonify({"error": "An authenticated landlord account is required."}), 403

    tenant = Tenant.query.filter_by(id=tenant_id, owner_id=landlord_id).first()
    if tenant is None:
        return jsonify({"error": "Tenant not found."}), 404
    return jsonify({"tenant": _tenant_to_dict(tenant)}), 200


@tenants_bp.patch("/<int:tenant_id>")
@jwt_required()
def update_tenant(tenant_id):
    landlord_id = get_current_landlord_id()
    if landlord_id is None:
        return jsonify({"error": "An authenticated landlord account is required."}), 403

    tenant = Tenant.query.filter_by(id=tenant_id, owner_id=landlord_id).first()
    if tenant is None:
        return jsonify({"error": "Tenant not found."}), 404

    values, error = _validate_fields(request.get_json(silent=True), partial=True)
    if error:
        return jsonify({"error": error}), 400
    if "email" in values and _email_in_use(values["email"], excluding_tenant_id=tenant.id):
        return jsonify({"error": "A tenant with this email already exists."}), 409

    for field, value in values.items():
        setattr(tenant, field, value)

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "A tenant with this email already exists."}), 409

    return jsonify({
        "message": "Tenant updated successfully.",
        "tenant": _tenant_to_dict(tenant),
    }), 200
