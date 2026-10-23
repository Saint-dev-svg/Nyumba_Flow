from datetime import date
from decimal import Decimal, InvalidOperation

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import jwt_required
from sqlalchemy import or_
from sqlalchemy.exc import SQLAlchemyError

from extensions import db
from models import Lease, Property, Tenant, Unit
from authorization import get_current_landlord_id


leases_bp = Blueprint("leases", __name__, url_prefix="/api/leases")


def _parse_date(value, field_name, *, optional=False):
    if value is None and optional:
        return None, None
    if not isinstance(value, str):
        return None, f"{field_name} must be a date in YYYY-MM-DD format."
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None, f"{field_name} must be a valid date in YYYY-MM-DD format."
    if parsed.isoformat() != value:
        return None, f"{field_name} must be a date in YYYY-MM-DD format."
    return parsed, None


def _parse_rent(value):
    if value is None or isinstance(value, bool):
        return None, "Agreed monthly rent is required."
    try:
        rent = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None, "Agreed monthly rent must be a valid number."
    if not rent.is_finite() or rent < 0:
        return None, "Agreed monthly rent must be a finite, non-negative amount."
    if rent.as_tuple().exponent < -2:
        return None, "Agreed monthly rent cannot have more than two decimal places."
    if rent > Decimal("9999999999.99"):
        return None, "Agreed monthly rent is too large."
    return rent, None


def _lease_to_dict(lease):
    return {
        "id": lease.id,
        "unit_id": lease.unit_id,
        "tenant_id": lease.tenant_id,
        "start_date": lease.start_date.isoformat(),
        "end_date": lease.end_date.isoformat() if lease.end_date else None,
        "monthly_rent": str(lease.monthly_rent),
        "is_active": lease.is_active,
    }


def _owned_lease_query(landlord_id):
    return (
        Lease.query
        .join(Unit, Lease.unit_id == Unit.id)
        .join(Property, Unit.property_id == Property.id)
        .join(Tenant, Lease.tenant_id == Tenant.id)
        .filter(
            Property.owner_id == landlord_id,
            Tenant.owner_id == landlord_id,
        )
    )


def _find_overlap(lease):
    query = Lease.query.filter(
        Lease.unit_id == lease.unit_id,
        Lease.id != lease.id,
        Lease.is_active.is_(True),
        or_(Lease.end_date.is_(None), Lease.end_date >= lease.start_date),
    )
    if lease.end_date is not None:
        query = query.filter(Lease.start_date <= lease.end_date)
    return query.first()


@leases_bp.post("")
@jwt_required()
def create_lease():
    landlord_id = get_current_landlord_id()
    if landlord_id is None:
        return jsonify({"error": "An authenticated landlord account is required."}), 403

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be valid JSON."}), 400
    if set(data) - {"unit_id", "tenant_id", "start_date", "end_date", "monthly_rent"}:
        return jsonify({"error": "Request contains unsupported fields."}), 400

    unit_id = data.get("unit_id")
    tenant_id = data.get("tenant_id")
    if isinstance(unit_id, bool) or not isinstance(unit_id, int) or unit_id <= 0:
        return jsonify({"error": "Unit ID must be a positive integer."}), 400
    if isinstance(tenant_id, bool) or not isinstance(tenant_id, int) or tenant_id <= 0:
        return jsonify({"error": "Tenant ID must be a positive integer."}), 400

    start_date, error = _parse_date(data.get("start_date"), "Start date")
    if error:
        return jsonify({"error": error}), 400
    end_date, error = _parse_date(data.get("end_date"), "End date", optional=True)
    if error:
        return jsonify({"error": error}), 400
    if end_date is not None and end_date < start_date:
        return jsonify({"error": "End date cannot be before start date."}), 400

    monthly_rent, error = _parse_rent(data.get("monthly_rent"))
    if error:
        return jsonify({"error": error}), 400

    unit = (
        Unit.query
        .join(Property, Unit.property_id == Property.id)
        .filter(Unit.id == unit_id, Property.owner_id == landlord_id)
        .first()
    )
    tenant = Tenant.query.filter_by(id=tenant_id, owner_id=landlord_id).first()
    if unit is None or tenant is None:
        return jsonify({"error": "Unit or tenant not found."}), 404
    if not unit.is_active:
        return jsonify({"error": "An inactive unit cannot be leased."}), 409

    lease = Lease(
        unit_id=unit.id,
        tenant_id=tenant.id,
        start_date=start_date,
        end_date=end_date,
        monthly_rent=monthly_rent,
        is_active=False,
    )
    db.session.add(lease)
    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Lease creation failed")
        return jsonify({"error": "Unable to create lease right now."}), 500

    return jsonify({
        "message": "Lease created successfully. Activate it when it is ready to begin.",
        "lease": _lease_to_dict(lease),
    }), 201


@leases_bp.get("")
@jwt_required()
def list_leases():
    landlord_id = get_current_landlord_id()
    if landlord_id is None:
        return jsonify({"error": "An authenticated landlord account is required."}), 403

    leases = (
        _owned_lease_query(landlord_id)
        .order_by(Lease.start_date.desc(), Lease.id.desc())
        .all()
    )
    return jsonify({
        "leases": [_lease_to_dict(lease) for lease in leases],
        "count": len(leases),
    }), 200


@leases_bp.get("/<int:lease_id>")
@jwt_required()
def get_lease(lease_id):
    landlord_id = get_current_landlord_id()
    if landlord_id is None:
        return jsonify({"error": "An authenticated landlord account is required."}), 403

    lease = _owned_lease_query(landlord_id).filter(Lease.id == lease_id).first()
    if lease is None:
        return jsonify({"error": "Lease not found."}), 404
    return jsonify({"lease": _lease_to_dict(lease)}), 200


@leases_bp.post("/<int:lease_id>/activate")
@jwt_required()
def activate_lease(lease_id):
    landlord_id = get_current_landlord_id()
    if landlord_id is None:
        return jsonify({"error": "An authenticated landlord account is required."}), 403

    lease = _owned_lease_query(landlord_id).filter(Lease.id == lease_id).first()
    if lease is None:
        return jsonify({"error": "Lease not found."}), 404
    if lease.is_active:
        return jsonify({"error": "Lease is already active."}), 409
    if lease.end_date is not None and lease.end_date < date.today():
        return jsonify({"error": "A lease with a past end date cannot be activated."}), 400

    # Serializing state changes on the unit prevents concurrent activations
    # from both passing the overlap check for the same unit.
    unit = Unit.query.filter_by(id=lease.unit_id).with_for_update().first()
    if unit is None or not unit.is_active:
        return jsonify({"error": "The unit is unavailable for leasing."}), 409
    db.session.refresh(lease)
    if lease.is_active:
        return jsonify({"error": "Lease is already active."}), 409
    if _find_overlap(lease) is not None:
        return jsonify({"error": "This lease overlaps another active lease for the unit."}), 409

    lease.is_active = True
    db.session.commit()
    return jsonify({
        "message": "Lease activated successfully.",
        "lease": _lease_to_dict(lease),
    }), 200


@leases_bp.post("/<int:lease_id>/end")
@jwt_required()
def end_lease(lease_id):
    landlord_id = get_current_landlord_id()
    if landlord_id is None:
        return jsonify({"error": "An authenticated landlord account is required."}), 403

    lease = _owned_lease_query(landlord_id).filter(Lease.id == lease_id).first()
    if lease is None:
        return jsonify({"error": "Lease not found."}), 404
    data = request.get_json(silent=True)
    if data is None:
        if request.content_length:
            return jsonify({"error": "Request body must be valid JSON."}), 400
        data = {}
    if not isinstance(data, dict) or set(data) - {"end_date"}:
        return jsonify({"error": "Provide an optional end_date only."}), 400

    effective_end_date = date.today()
    if "end_date" in data:
        effective_end_date, error = _parse_date(data["end_date"], "End date")
        if error:
            return jsonify({"error": error}), 400
    unit = Unit.query.filter_by(id=lease.unit_id).with_for_update().first()
    if unit is None:
        return jsonify({"error": "The unit is unavailable for leasing."}), 409
    db.session.refresh(lease)
    if not lease.is_active:
        return jsonify({"error": "Only an active lease can be ended."}), 409
    if effective_end_date < lease.start_date:
        return jsonify({"error": "End date cannot be before start date."}), 400
    if effective_end_date > date.today():
        return jsonify({"error": "A lease cannot be ended on a future date."}), 400
    if lease.end_date is not None and effective_end_date > lease.end_date:
        return jsonify({"error": "End date cannot be after the scheduled lease end."}), 400

    lease.end_date = effective_end_date
    lease.is_active = False
    db.session.commit()
    return jsonify({
        "message": "Lease ended successfully.",
        "lease": _lease_to_dict(lease),
    }), 200
