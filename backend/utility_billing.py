import calendar
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import jwt_required
from sqlalchemy import or_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from authorization import get_current_landlord_id
from extensions import db
from invoices import _invoice_to_dict
from models import (
    Charge,
    Invoice,
    Lease,
    Property,
    PropertyUtilitySettings,
    Tenant,
    Unit,
    UtilityBreakdown,
    WaterMeterReading,
)


utility_billing_bp = Blueprint("utility_billing", __name__, url_prefix="/api")
DEFAULT_WATER_RATE = Decimal("180.00")
DEFAULT_GARBAGE_FEE = Decimal("300.00")
CENT = Decimal("0.01")
MAX_MONEY = Decimal("9999999999.99")
MAX_READING = Decimal("99999999999.999")


def _owned_property(property_id, landlord_id):
    return Property.query.filter_by(id=property_id, owner_id=landlord_id).first()


def _period_from_month(value):
    if not isinstance(value, str) or len(value) != 7:
        return None, None, "billing_month must use YYYY-MM format."
    try:
        year, month = (int(part) for part in value.split("-"))
        first = date(year, month, 1)
    except (TypeError, ValueError):
        return None, None, "billing_month must be a valid month in YYYY-MM format."
    if first.strftime("%Y-%m") != value:
        return None, None, "billing_month must use YYYY-MM format."
    last = date(year, month, calendar.monthrange(year, month)[1])
    return first, last, None


def _parse_decimal(value, field, *, places, maximum):
    if not isinstance(value, str):
        return None, f"{field} must be entered as a decimal string."
    try:
        amount = Decimal(value)
    except (InvalidOperation, ValueError):
        return None, f"{field} must be a valid number."
    if not amount.is_finite() or amount < 0:
        return None, f"{field} must be finite and non-negative."
    if amount.as_tuple().exponent < -places:
        return None, f"{field} cannot have more than {places} decimal places."
    if amount > maximum:
        return None, f"{field} is too large."
    return amount, None


def _ensure_settings(property_id):
    stmt = pg_insert(PropertyUtilitySettings).values(
        property_id=property_id,
        water_rate=DEFAULT_WATER_RATE,
        garbage_fee=DEFAULT_GARBAGE_FEE,
        updated_at=datetime.now(timezone.utc),
    ).on_conflict_do_nothing(index_elements=["property_id"])
    db.session.execute(stmt)
    db.session.commit()
    return db.session.get(PropertyUtilitySettings, property_id)


def _settings_to_dict(settings):
    return {
        "property_id": settings.property_id,
        "water_rate": str(settings.water_rate),
        "garbage_fee": str(settings.garbage_fee),
        "updated_at": settings.updated_at.isoformat(),
    }


def _reading_to_dict(reading, unit=None):
    return {
        "id": reading.id,
        "unit_id": reading.unit_id,
        "unit_number": unit.unit_number if unit else None,
        "period_start": reading.period_start.isoformat(),
        "period_end": reading.period_end.isoformat(),
        "previous_reading": str(reading.previous_reading),
        "current_reading": str(reading.current_reading),
    }


@utility_billing_bp.get("/properties/<int:property_id>/utility-settings")
@jwt_required()
def get_utility_settings(property_id):
    landlord_id = get_current_landlord_id()
    if landlord_id is None:
        return jsonify({"error": "An authenticated landlord account is required."}), 403
    property_obj = _owned_property(property_id, landlord_id)
    if property_obj is None:
        return jsonify({"error": "Property not found."}), 404
    settings = _ensure_settings(property_obj.id)
    return jsonify({"settings": _settings_to_dict(settings)}), 200


@utility_billing_bp.patch("/properties/<int:property_id>/utility-settings")
@jwt_required()
def update_utility_settings(property_id):
    landlord_id = get_current_landlord_id()
    if landlord_id is None:
        return jsonify({"error": "An authenticated landlord account is required."}), 403
    property_obj = _owned_property(property_id, landlord_id)
    if property_obj is None:
        return jsonify({"error": "Property not found."}), 404
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not data:
        return jsonify({"error": "Provide at least one utility rate to update."}), 400
    if set(data) - {"water_rate", "garbage_fee"}:
        return jsonify({"error": "Request contains unsupported fields."}), 400

    parsed = {}
    for field in ("water_rate", "garbage_fee"):
        if field in data:
            value, error = _parse_decimal(
                data[field], field, places=2, maximum=MAX_MONEY
            )
            if error:
                return jsonify({"error": error}), 400
            parsed[field] = value

    try:
        settings = _ensure_settings(property_obj.id)
        for field, value in parsed.items():
            setattr(settings, field, value)
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Utility settings update failed")
        return jsonify({"error": "Unable to update utility rates right now."}), 500
    return jsonify({"settings": _settings_to_dict(settings)}), 200


@utility_billing_bp.get("/properties/<int:property_id>/water-readings")
@jwt_required()
def list_water_readings(property_id):
    landlord_id = get_current_landlord_id()
    if landlord_id is None:
        return jsonify({"error": "An authenticated landlord account is required."}), 403
    property_obj = _owned_property(property_id, landlord_id)
    if property_obj is None:
        return jsonify({"error": "Property not found."}), 404
    billing_month = request.args.get("billing_month")
    start, end, error = _period_from_month(billing_month)
    if error:
        return jsonify({"error": error}), 400
    rows = (
        db.session.query(WaterMeterReading, Unit)
        .join(Unit, Unit.id == WaterMeterReading.unit_id)
        .filter(
            Unit.property_id == property_obj.id,
            WaterMeterReading.period_start == start,
            WaterMeterReading.period_end == end,
        )
        .order_by(Unit.unit_number.asc(), Unit.id.asc())
        .all()
    )
    return jsonify({
        "billing_month": billing_month,
        "readings": [_reading_to_dict(reading, unit) for reading, unit in rows],
        "count": len(rows),
    }), 200


@utility_billing_bp.put(
    "/properties/<int:property_id>/units/<int:unit_id>/water-reading"
)
@jwt_required()
def save_water_reading(property_id, unit_id):
    landlord_id = get_current_landlord_id()
    if landlord_id is None:
        return jsonify({"error": "An authenticated landlord account is required."}), 403
    property_obj = _owned_property(property_id, landlord_id)
    if property_obj is None:
        return jsonify({"error": "Property not found."}), 404
    unit = Unit.query.filter_by(id=unit_id, property_id=property_obj.id).with_for_update().first()
    if unit is None:
        return jsonify({"error": "Unit not found."}), 404
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or set(data) != {
        "billing_month", "previous_reading", "current_reading"
    }:
        return jsonify({"error": "billing_month, previous_reading, and current_reading are required."}), 400
    start, end, error = _period_from_month(data.get("billing_month"))
    if error:
        return jsonify({"error": error}), 400
    previous, error = _parse_decimal(
        data.get("previous_reading"), "previous_reading", places=3,
        maximum=MAX_READING,
    )
    if error:
        return jsonify({"error": error}), 400
    current, error = _parse_decimal(
        data.get("current_reading"), "current_reading", places=3,
        maximum=MAX_READING,
    )
    if error:
        return jsonify({"error": error}), 400
    if current < previous:
        return jsonify({
            "error": f"Current reading cannot be less than the previous reading for unit {unit.unit_number}."
        }), 400

    active_lease_ids = [lease.id for lease in Lease.query.filter_by(unit_id=unit.id).all()]
    locked_invoice = Invoice.query.filter(
        Invoice.lease_id.in_(active_lease_ids or [-1]),
        Invoice.period_start == start,
        Invoice.period_end == end,
    ).first()
    if locked_invoice is not None:
        return jsonify({"error": "Meter readings cannot be changed after an invoice exists for this billing period."}), 409

    stmt = pg_insert(WaterMeterReading).values(
        unit_id=unit.id,
        period_start=start,
        period_end=end,
        previous_reading=previous,
        current_reading=current,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    ).on_conflict_do_update(
        index_elements=["unit_id", "period_start", "period_end"],
        set_={
            "previous_reading": previous,
            "current_reading": current,
            "updated_at": datetime.now(timezone.utc),
        },
    )
    try:
        db.session.execute(stmt)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "Unable to save this meter reading."}), 409
    reading = WaterMeterReading.query.filter_by(
        unit_id=unit.id, period_start=start, period_end=end
    ).one()
    return jsonify({"reading": _reading_to_dict(reading, unit)}), 200


def _owned_active_leases(landlord_id, start, end):
    return (
        Lease.query
        .join(Unit, Lease.unit_id == Unit.id)
        .join(Property, Unit.property_id == Property.id)
        .join(Tenant, Lease.tenant_id == Tenant.id)
        .filter(
            Property.owner_id == landlord_id,
            Tenant.owner_id == landlord_id,
            Unit.is_active.is_(True),
            Lease.is_active.is_(True),
            Lease.start_date <= end,
            or_(Lease.end_date.is_(None), Lease.end_date >= start),
        )
        .order_by(Lease.id.asc())
        .all()
    )


@utility_billing_bp.post("/invoices/generate-monthly")
@jwt_required()
def generate_monthly_drafts():
    landlord_id = get_current_landlord_id()
    if landlord_id is None:
        return jsonify({"error": "An authenticated landlord account is required."}), 403
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be valid JSON."}), 400
    start, end, error = _period_from_month(data.get("billing_month"))
    if error:
        return jsonify({"error": error}), 400
    due_date = start
    created = []
    existing = []
    needs_readings = []

    leases = _owned_active_leases(landlord_id, start, end)
    for lease in leases:
        unit = lease.unit
        property_obj = unit.property
        _ensure_settings(property_obj.id)
        unit = Unit.query.filter_by(id=unit.id).with_for_update().populate_existing().one()
        settings = PropertyUtilitySettings.query.filter_by(
            property_id=property_obj.id
        ).with_for_update().one()
        existing_by_purpose = {
            invoice.purpose: invoice
            for invoice in Invoice.query.filter_by(
                lease_id=lease.id, period_start=start, period_end=end
            ).all()
        }
        missing_purposes = {
            purpose for purpose in ("rent", "utilities")
            if purpose not in existing_by_purpose
        }
        if not missing_purposes:
            existing.extend({
                "id": existing_by_purpose[purpose].id,
                "lease_id": lease.id,
                "unit_id": unit.id,
                "purpose": purpose,
            } for purpose in ("rent", "utilities"))
            db.session.commit()
            continue

        reading = None
        water_amount = None
        utility_total = None
        if "utilities" in missing_purposes:
            reading = WaterMeterReading.query.filter_by(
                unit_id=unit.id, period_start=start, period_end=end
            ).first()
            reason = None
            if reading is None:
                reason = "missing"
            elif reading.previous_reading < 0 or reading.current_reading < reading.previous_reading:
                reason = "invalid"
            if reason:
                needs_readings.append({
                    "lease_id": lease.id,
                    "tenant_id": lease.tenant_id,
                    "tenant_name": lease.tenant.full_name,
                    "property_id": property_obj.id,
                    "property_name": property_obj.name,
                    "unit_id": unit.id,
                    "unit_number": unit.unit_number,
                    "reason": reason,
                })
                existing.extend({
                    "id": existing_by_purpose[purpose].id,
                    "lease_id": lease.id,
                    "unit_id": unit.id,
                    "purpose": purpose,
                } for purpose in existing_by_purpose)
                db.session.commit()
                continue
            consumption = Decimal(reading.current_reading) - Decimal(reading.previous_reading)
            water_amount = (consumption * Decimal(settings.water_rate)).quantize(
                CENT, rounding=ROUND_HALF_UP
            )
            if water_amount > MAX_MONEY:
                needs_readings.append({
                    "lease_id": lease.id,
                    "tenant_id": lease.tenant_id,
                    "tenant_name": lease.tenant.full_name,
                    "property_id": property_obj.id,
                    "property_name": property_obj.name,
                    "unit_id": unit.id,
                    "unit_number": unit.unit_number,
                    "reason": "water_charge_too_large",
                })
                existing.extend({
                    "id": invoice.id,
                    "lease_id": lease.id,
                    "unit_id": unit.id,
                    "purpose": purpose,
                } for purpose, invoice in existing_by_purpose.items())
                db.session.commit()
                continue
            utility_total = water_amount + Decimal(settings.garbage_fee)
            if utility_total > MAX_MONEY:
                needs_readings.append({
                    "lease_id": lease.id,
                    "tenant_id": lease.tenant_id,
                    "tenant_name": lease.tenant.full_name,
                    "property_id": property_obj.id,
                    "property_name": property_obj.name,
                    "unit_id": unit.id,
                    "unit_number": unit.unit_number,
                    "reason": "utilities_charge_too_large",
                })
                existing.extend({
                    "id": invoice.id,
                    "lease_id": lease.id,
                    "unit_id": unit.id,
                    "purpose": purpose,
                } for purpose, invoice in existing_by_purpose.items())
                db.session.commit()
                continue

        invoices_to_create = []
        if "rent" in missing_purposes:
            rent_invoice = Invoice(
                lease_id=lease.id,
                period_start=start,
                period_end=end,
                due_date=due_date,
                purpose="rent",
            )
            rent_invoice.charges.append(Charge(
                category="rent",
                description="Monthly rent",
                amount=Decimal(lease.monthly_rent),
            ))
            invoices_to_create.append(rent_invoice)
        if "utilities" in missing_purposes:
            utility_charge = Charge(
                category="utilities",
                description="Water and garbage",
                amount=utility_total,
            )
            utility_charge.utility_breakdowns.extend([
                UtilityBreakdown(category="water", amount=water_amount),
                UtilityBreakdown(category="garbage", amount=Decimal(settings.garbage_fee)),
            ])
            utility_invoice = Invoice(
                lease_id=lease.id,
                period_start=start,
                period_end=end,
                due_date=due_date,
                purpose="utilities",
            )
            utility_invoice.charges.append(utility_charge)
            invoices_to_create.append(utility_invoice)

        try:
            db.session.add_all(invoices_to_create)
            db.session.commit()
            for invoice in invoices_to_create:
                created.append({
                    "id": invoice.id,
                    "lease_id": lease.id,
                    "unit_id": unit.id,
                    "purpose": invoice.purpose,
                    "total_amount": _invoice_to_dict(invoice)["total_amount"],
                })
            for purpose, invoice in existing_by_purpose.items():
                existing.append({
                    "id": invoice.id,
                    "lease_id": lease.id,
                    "unit_id": unit.id,
                    "purpose": purpose,
                })
        except IntegrityError:
            db.session.rollback()
            # The purpose-scoped unique key is the final guard when another
            # monthly generation request creates these invoices concurrently.
            raced = Invoice.query.filter_by(
                lease_id=lease.id, period_start=start, period_end=end
            ).all()
            existing.extend({
                "id": invoice.id,
                "lease_id": lease.id,
                "unit_id": unit.id,
                "purpose": invoice.purpose,
            } for invoice in raced)
        except SQLAlchemyError:
            db.session.rollback()
            current_app.logger.exception("Monthly invoice generation failed for lease %s", lease.id)
            return jsonify({"error": "Unable to generate monthly drafts right now."}), 500

    return jsonify({
        "message": "Monthly draft generation completed.",
        "billing_month": data["billing_month"],
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "due_date": due_date.isoformat(),
        "created_invoices": created,
        "already_existing": existing,
        "needs_readings": needs_readings,
        "created_count": len(created),
        "already_existing_count": len(existing),
        "needs_reading_count": len(needs_readings),
    }), 200
