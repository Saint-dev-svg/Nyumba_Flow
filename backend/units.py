from decimal import Decimal, InvalidOperation

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required
from sqlalchemy.exc import IntegrityError

from authorization import get_current_landlord_id
from extensions import db
from models import Property, Unit


units_bp = Blueprint(
    "units",
    __name__,
    url_prefix="/api/properties/<int:property_id>/units",
)


def unit_to_dict(unit):
    """Convert a Unit model instance into a JSON-safe dictionary."""
    return {
        "id": unit.id,
        "property_id": unit.property_id,
        "unit_number": unit.unit_number,
        "bedrooms": unit.bedrooms,
        "monthly_rent": str(unit.monthly_rent),
        "is_active": unit.is_active,
    }


def get_owned_property(property_id, owner_id):
    """Return the property only if it belongs to the current landlord."""
    return Property.query.filter_by(
        id=property_id,
        owner_id=owner_id,
    ).first()


@units_bp.post("")
@jwt_required()
def create_unit(property_id):
    owner_id = get_current_landlord_id()
    if owner_id is None:
        return jsonify({
            "error": "An authenticated landlord account is required."
        }), 403

    property_obj = get_owned_property(property_id, owner_id)

    if property_obj is None:
        return jsonify({"error": "Property not found."}), 404

    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be valid JSON."}), 400

    unit_number = data.get("unit_number")
    bedrooms = data.get("bedrooms", 1)
    monthly_rent = data.get("monthly_rent")

    if not isinstance(unit_number, str):
        return jsonify({"error": "Unit number must be a string."}), 400

    unit_number = unit_number.strip()

    if not unit_number or len(unit_number) > 50:
        return jsonify({
            "error": "Unit number is required and must be at most 50 characters."
        }), 400

    if isinstance(bedrooms, bool) or not isinstance(bedrooms, int):
        return jsonify({"error": "Bedrooms must be a whole number."}), 400

    if bedrooms < 0:
        return jsonify({"error": "Bedrooms cannot be negative."}), 400

    if monthly_rent is None or isinstance(monthly_rent, bool):
        return jsonify({"error": "Monthly rent is required."}), 400

    try:
        rent = Decimal(str(monthly_rent))
    except (InvalidOperation, ValueError):
        return jsonify({"error": "Monthly rent must be a valid number."}), 400

    if not rent.is_finite() or rent < 0:
        return jsonify({
            "error": "Monthly rent must be a finite, non-negative amount."
        }), 400

    if rent.as_tuple().exponent < -2:
        return jsonify({
            "error": "Monthly rent cannot have more than two decimal places."
        }), 400

    if rent > Decimal("9999999999.99"):
        return jsonify({"error": "Monthly rent is too large."}), 400

    unit = Unit(
        property_id=property_obj.id,
        unit_number=unit_number,
        bedrooms=bedrooms,
        monthly_rent=rent,
    )

    try:
        db.session.add(unit)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({
            "error": "A unit with this number already exists in this property."
        }), 409

    return jsonify({
        "message": "Unit created successfully.",
        "unit": unit_to_dict(unit),
    }), 201


@units_bp.get("")
@jwt_required()
def list_units(property_id):
    owner_id = get_current_landlord_id()
    if owner_id is None:
        return jsonify({
            "error": "An authenticated landlord account is required."
        }), 403

    property_obj = get_owned_property(property_id, owner_id)

    if property_obj is None:
        return jsonify({"error": "Property not found."}), 404

    units = (
        Unit.query
        .filter_by(property_id=property_obj.id)
        .order_by(Unit.unit_number.asc(), Unit.id.asc())
        .all()
    )

    return jsonify({
        "units": [unit_to_dict(unit) for unit in units],
        "count": len(units),
    }), 200
