from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from extensions import db
from models import Charge, Invoice, Lease, Property, Tenant, Unit, User, UtilityBreakdown


invoices_bp = Blueprint("invoices", __name__, url_prefix="/api/invoices")


def _landlord_id():
    try:
        user_id = int(get_jwt_identity())
    except (TypeError, ValueError):
        return None

    landlord = db.session.get(User, user_id)
    if landlord is None or landlord.role != "landlord":
        return None
    return landlord.id


def _parse_date(value, field_name):
    if not isinstance(value, str):
        return None, f"{field_name} must be a date in YYYY-MM-DD format."
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None, f"{field_name} must be a valid date in YYYY-MM-DD format."
    if parsed.isoformat() != value:
        return None, f"{field_name} must be a date in YYYY-MM-DD format."
    return parsed, None


def _parse_amount(value, field_name):
    if value is None or isinstance(value, bool):
        return None, f"{field_name} must be a non-negative amount."
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None, f"{field_name} must be a valid amount."
    if not amount.is_finite() or amount < 0:
        return None, f"{field_name} must be a finite, non-negative amount."
    if amount.as_tuple().exponent < -2:
        return None, f"{field_name} cannot have more than two decimal places."
    if amount > Decimal("9999999999.99"):
        return None, f"{field_name} is too large."
    return amount, None


def _owned_leases(landlord_id):
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


def _owned_invoices(landlord_id):
    return (
        Invoice.query
        .join(Lease, Invoice.lease_id == Lease.id)
        .join(Unit, Lease.unit_id == Unit.id)
        .join(Property, Unit.property_id == Property.id)
        .join(Tenant, Lease.tenant_id == Tenant.id)
        .filter(
            Property.owner_id == landlord_id,
            Tenant.owner_id == landlord_id,
        )
    )


def _invoice_to_dict(invoice):
    charge_balances = []
    for charge in invoice.charges:
        paid_amount = sum(
            (Decimal(allocation.amount) for allocation in charge.allocations),
            Decimal("0.00"),
        )
        charge_balances.append((charge, paid_amount, Decimal(charge.amount) - paid_amount))

    total_amount = sum(
        (Decimal(charge.amount) for charge, _, _ in charge_balances),
        Decimal("0.00"),
    )
    total_paid = sum(
        (paid for _, paid, _ in charge_balances),
        Decimal("0.00"),
    )
    return {
        "id": invoice.id,
        "lease_id": invoice.lease_id,
        "period_start": invoice.period_start.isoformat(),
        "period_end": invoice.period_end.isoformat(),
        "due_date": invoice.due_date.isoformat(),
        "status": invoice.status,
        "issued_at": invoice.issued_at.isoformat() if invoice.issued_at else None,
        "total_amount": str(total_amount),
        "paid_amount": str(total_paid),
        "outstanding_balance": str(total_amount - total_paid),
        "charges": [
            {
                "id": charge.id,
                "category": charge.category,
                "description": charge.description,
                "amount": str(charge.amount),
                "paid_amount": str(paid_amount),
                "outstanding_balance": str(outstanding),
                "utility_breakdowns": [
                    {
                        "category": breakdown.category,
                        "amount": str(breakdown.amount),
                    }
                    for breakdown in sorted(
                        charge.utility_breakdowns,
                        key=lambda item: item.category,
                    )
                ],
            }
            for charge, paid_amount, outstanding in charge_balances
        ],
    }


def _parse_charges(raw_charges):
    if not isinstance(raw_charges, list) or not raw_charges:
        return None, "At least one invoice charge is required."

    parsed_charges = []
    for index, raw_charge in enumerate(raw_charges):
        field = f"charges[{index}]"
        if not isinstance(raw_charge, dict):
            return None, f"{field} must be an object."

        category = raw_charge.get("category")
        if category not in {"rent", "utilities", "other"}:
            return None, f"{field}.category must be rent, utilities, or other."

        amount, error = _parse_amount(raw_charge.get("amount"), f"{field}.amount")
        if error:
            return None, error

        description = raw_charge.get("description")
        if description is not None and not isinstance(description, str):
            return None, f"{field}.description must be a string."
        if isinstance(description, str) and len(description) > 255:
            return None, f"{field}.description must be at most 255 characters."

        raw_breakdowns = raw_charge.get("utility_breakdowns", [])
        if category == "utilities":
            if not isinstance(raw_breakdowns, list) or len(raw_breakdowns) != 2:
                return None, f"{field} must include water and garbage breakdowns."
            breakdowns = {}
            breakdown_total = Decimal("0.00")
            for breakdown in raw_breakdowns:
                if not isinstance(breakdown, dict):
                    return None, f"{field}.utility_breakdowns entries must be objects."
                breakdown_category = breakdown.get("category")
                if breakdown_category not in {"water", "garbage"}:
                    return None, f"{field} breakdown category must be water or garbage."
                if breakdown_category in breakdowns:
                    return None, f"{field} cannot repeat a utility breakdown category."
                breakdown_amount, error = _parse_amount(
                    breakdown.get("amount"),
                    f"{field}.{breakdown_category}",
                )
                if error:
                    return None, error
                breakdowns[breakdown_category] = breakdown_amount
                breakdown_total += breakdown_amount
            if set(breakdowns) != {"water", "garbage"}:
                return None, f"{field} must include water and garbage breakdowns."
            if breakdown_total != amount:
                return None, f"{field} utility breakdowns must total the utilities charge."
        else:
            if raw_breakdowns:
                return None, f"{field} can only include utility breakdowns for utilities."
            breakdowns = {}

        parsed_charges.append({
            "category": category,
            "amount": amount,
            "description": description,
            "utility_breakdowns": breakdowns,
        })

    return parsed_charges, None


@invoices_bp.post("")
@jwt_required()
def create_invoice():
    landlord_id = _landlord_id()
    if landlord_id is None:
        return jsonify({"error": "An authenticated landlord account is required."}), 403

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be valid JSON."}), 400

    lease_id = data.get("lease_id")
    if isinstance(lease_id, bool) or not isinstance(lease_id, int) or lease_id <= 0:
        return jsonify({"error": "A valid lease_id is required."}), 400

    lease = _owned_leases(landlord_id).filter(Lease.id == lease_id).first()
    if lease is None:
        return jsonify({"error": "Lease not found."}), 404
    if not lease.is_active:
        return jsonify({"error": "Invoices can only be created for active leases."}), 409

    period_start, error = _parse_date(data.get("period_start"), "period_start")
    if error:
        return jsonify({"error": error}), 400
    period_end, error = _parse_date(data.get("period_end"), "period_end")
    if error:
        return jsonify({"error": error}), 400
    due_date, error = _parse_date(data.get("due_date"), "due_date")
    if error:
        return jsonify({"error": error}), 400
    if period_end < period_start:
        return jsonify({"error": "period_end cannot be before period_start."}), 400

    charges, error = _parse_charges(data.get("charges"))
    if error:
        return jsonify({"error": error}), 400

    duplicate = Invoice.query.filter_by(
        lease_id=lease.id,
        period_start=period_start,
        period_end=period_end,
    ).first()
    if duplicate is not None:
        return jsonify({"error": "An invoice already exists for this lease and period."}), 409

    invoice = Invoice(
        lease_id=lease.id,
        period_start=period_start,
        period_end=period_end,
        due_date=due_date,
    )
    for charge_data in charges:
        charge = Charge(
            category=charge_data["category"],
            description=charge_data["description"],
            amount=charge_data["amount"],
        )
        for category, amount in charge_data["utility_breakdowns"].items():
            charge.utility_breakdowns.append(
                UtilityBreakdown(category=category, amount=amount)
            )
        invoice.charges.append(charge)

    try:
        db.session.add(invoice)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "An invoice already exists for this lease and period."}), 409
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Invoice creation failed")
        return jsonify({"error": "Unable to create invoice right now."}), 500

    return jsonify({
        "message": "Invoice created successfully.",
        "invoice": _invoice_to_dict(invoice),
    }), 201


@invoices_bp.get("")
@jwt_required()
def list_invoices():
    landlord_id = _landlord_id()
    if landlord_id is None:
        return jsonify({"error": "An authenticated landlord account is required."}), 403

    invoices = (
        _owned_invoices(landlord_id)
        .order_by(
            Invoice.period_start.desc(),
            Invoice.id.desc(),
        )
        .all()
    )
    return jsonify({
        "invoices": [_invoice_to_dict(invoice) for invoice in invoices],
        "count": len(invoices),
    }), 200


@invoices_bp.post("/<int:invoice_id>/issue")
@jwt_required()
def issue_invoice(invoice_id):
    landlord_id = _landlord_id()
    if landlord_id is None:
        return jsonify({"error": "An authenticated landlord account is required."}), 403

    invoice = _owned_invoices(landlord_id).filter(Invoice.id == invoice_id).first()
    if invoice is None:
        return jsonify({"error": "Invoice not found."}), 404
    if invoice.status != "draft":
        return jsonify({"error": "Only draft invoices can be issued."}), 409

    invoice.status = "issued"
    invoice.issued_at = datetime.now(timezone.utc)
    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Invoice issuance failed")
        return jsonify({"error": "Unable to issue invoice right now."}), 500

    return jsonify({
        "message": "Invoice issued successfully.",
        "invoice": _invoice_to_dict(invoice),
    }), 200


@invoices_bp.get("/<int:invoice_id>")
@jwt_required()
def get_invoice(invoice_id):
    landlord_id = _landlord_id()
    if landlord_id is None:
        return jsonify({
            "error": "An authenticated landlord account is required."
        }), 403

    invoice = (
        Invoice.query
        .join(Lease, Invoice.lease_id == Lease.id)
        .join(Unit, Lease.unit_id == Unit.id)
        .join(Property, Unit.property_id == Property.id)
        .join(Tenant, Lease.tenant_id == Tenant.id)
        .filter(
            Invoice.id == invoice_id,
            Property.owner_id == landlord_id,
            Tenant.owner_id == landlord_id,
        )
        .first()
    )

    if invoice is None:
        return jsonify({"error": "Invoice not found."}), 404

    return jsonify({
        "invoice": _invoice_to_dict(invoice)
    }), 200
