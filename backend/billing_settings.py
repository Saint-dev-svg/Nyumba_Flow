
from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required
from sqlalchemy.exc import IntegrityError

from extensions import db
from authorization import get_current_landlord_id
from models import LandlordBillingSettings


billing_settings_bp = Blueprint(
    "billing_settings",
    __name__,
    url_prefix="/api/billing-settings",
)


def get_or_create_landlord_billing_settings(landlord_id, *, lock=False):
    settings_query = LandlordBillingSettings.query.filter_by(
        landlord_id=landlord_id
    )
    if lock:
        settings_query = settings_query.with_for_update()
    settings = settings_query.first()

    if settings is None:
        try:
            with db.session.begin_nested():
                settings = LandlordBillingSettings(
                    landlord_id=landlord_id,
                    rent_due_day=1,
                    utilities_due_day=1,
                )
                db.session.add(settings)
                db.session.flush()
        except IntegrityError:
            settings_query = LandlordBillingSettings.query.filter_by(
                landlord_id=landlord_id
            )
            if lock:
                settings_query = settings_query.with_for_update()
            settings = settings_query.first()
            if settings is None:
                raise

    return settings


@billing_settings_bp.get("")
@jwt_required()
def get_billing_settings():
    landlord_id = get_current_landlord_id()

    if landlord_id is None:
        return jsonify({
            "error": "An authenticated landlord account is required."
        }), 403

    settings = get_or_create_landlord_billing_settings(landlord_id)
    db.session.commit()

    return jsonify({
        "rent_due_day": settings.rent_due_day,
        "utilities_due_day": settings.utilities_due_day,
    }), 200


@billing_settings_bp.put("")
@jwt_required()
def update_billing_settings():
    landlord_id = get_current_landlord_id()

    if landlord_id is None:
        return jsonify({
            "error": "An authenticated landlord account is required."
        }), 403

    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be valid JSON."}), 400

    allowed_fields = {"rent_due_day", "utilities_due_day"}

    if not data or set(data.keys()) - allowed_fields:
        return jsonify({"error": "Invalid or missing billing settings."}), 400

    for field in allowed_fields.intersection(data.keys()):
        value = data[field]

        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 28:
            return jsonify({
                "error": f"{field} must be a whole number between 1 and 28."
            }), 400

    settings = get_or_create_landlord_billing_settings(landlord_id, lock=True)

    if "rent_due_day" in data:
        settings.rent_due_day = data["rent_due_day"]

    if "utilities_due_day" in data:
        settings.utilities_due_day = data["utilities_due_day"]

    db.session.commit()

    return jsonify({
        "message": "Billing settings updated successfully.",
        "rent_due_day": settings.rent_due_day,
        "utilities_due_day": settings.utilities_due_day,
    }), 200
