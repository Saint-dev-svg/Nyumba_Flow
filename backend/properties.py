
from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required
from sqlalchemy.exc import IntegrityError

from extensions import db
from models import Property


properties_bp = Blueprint(
    "properties",
    __name__,
    url_prefix="/api/properties",
)


def property_to_dict(property):
    """Convert a Property model instance into a JSON-safe dictionary."""
    return {
        "id": property.id,
        "name": property.name,
        "address": property.address,
        "created_at": property.created_at.isoformat(),
    }


@properties_bp.post("")
@jwt_required()
def create_property():
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be valid JSON."}), 400

    name = data.get("name")
    address = data.get("address")

    if not isinstance(name, str) or not isinstance(address, str):
        return jsonify({"error": "Name and address must be strings."}), 400

    name = name.strip()
    address = address.strip()

    if not name or len(name) > 150:
        return jsonify({
            "error": "Property name is required and must be at most 150 characters."
        }), 400

    if not address or len(address) > 255:
        return jsonify({
            "error": "Property address is required and must be at most 255 characters."
        }), 400

    owner_id = int(get_jwt_identity())

    property = Property(
        owner_id=owner_id,
        name=name,
        address=address,
    )

    try:
        db.session.add(property)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({
            "error": "You already have a property with this name."
        }), 409

    return jsonify({
        "message": "Property created successfully.",
        "property": property_to_dict(property),
    }), 201


@properties_bp.get("")
@jwt_required()
def list_properties():
    owner_id = int(get_jwt_identity())

    properties = (
        Property.query
        .filter_by(owner_id=owner_id)
        .order_by(Property.created_at.desc(), Property.id.desc())
        .all()
    )

    return jsonify({
        "properties": [
            property_to_dict(property)
            for property in properties
        ],
        "count": len(properties),
    }), 200
