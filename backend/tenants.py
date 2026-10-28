from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload, selectinload

from extensions import db
from models import Charge, Invoice, Lease, Payment, PaymentAllocation, Property, Tenant, Unit
from authorization import get_current_landlord_id


tenants_bp = Blueprint("tenants", __name__, url_prefix="/api/tenants")

_EDITABLE_FIELDS = {
    "full_name",
    "email",
    "phone_number",
    "national_id_last4",
}
_ZERO = Decimal("0.00")
_STATEMENT_TIMEZONE = ZoneInfo("Africa/Nairobi")
_STATEMENT_PURPOSES = ("rent", "utilities", "other")


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


def _statement_date(value, field):
    if not isinstance(value, str):
        return None, f"{field} must be a valid date in YYYY-MM-DD format."
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None, f"{field} must be a valid date in YYYY-MM-DD format."
    if parsed.isoformat() != value:
        return None, f"{field} must be a valid date in YYYY-MM-DD format."
    return parsed, None


def _statement_window(start_date, end_date):
    start_at = (
        datetime.combine(start_date, time.min, tzinfo=_STATEMENT_TIMEZONE)
        .astimezone(timezone.utc)
        if start_date else None
    )
    end_at = (
        datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=_STATEMENT_TIMEZONE)
        .astimezone(timezone.utc)
        if end_date and end_date < date.max else None
    )
    return start_at, end_at


def _in_statement_period(value, start_at, end_at):
    if value is None:
        return False
    if start_at is not None and value < start_at:
        return False
    if end_at is not None and value >= end_at:
        return False
    return True


def _decimal_sum(values):
    return sum((Decimal(value or 0) for value in values), _ZERO)


def _statement_totals():
    return {purpose: _ZERO for purpose in _STATEMENT_PURPOSES}


def _statement_totals_dict(totals):
    return {
        **{purpose: str(totals[purpose]) for purpose in _STATEMENT_PURPOSES},
        "total": str(_decimal_sum(totals.values())),
    }


@tenants_bp.get("/<int:tenant_id>/statement")
@jwt_required()
def get_tenant_statement(tenant_id):
    landlord_id = get_current_landlord_id()
    if landlord_id is None:
        return jsonify({"error": "An authenticated landlord account is required."}), 403

    tenant = Tenant.query.filter_by(id=tenant_id, owner_id=landlord_id).first()
    if tenant is None:
        return jsonify({"error": "Tenant not found."}), 404

    start_date = end_date = None
    if "start_date" in request.args:
        start_date, error = _statement_date(request.args.get("start_date"), "start_date")
        if error:
            return jsonify({"error": error}), 400
    if "end_date" in request.args:
        end_date, error = _statement_date(request.args.get("end_date"), "end_date")
        if error:
            return jsonify({"error": error}), 400
    if start_date is not None and end_date is not None and start_date > end_date:
        return jsonify({"error": "start_date cannot be later than end_date."}), 400

    start_at, end_at = _statement_window(start_date, end_date)
    tenant_invoices = (
        Invoice.query
        .join(Lease, Invoice.lease_id == Lease.id)
        .join(Unit, Lease.unit_id == Unit.id)
        .join(Property, Unit.property_id == Property.id)
        .join(Tenant, Lease.tenant_id == Tenant.id)
        .filter(
            Tenant.id == tenant.id,
            Tenant.owner_id == landlord_id,
            Property.owner_id == landlord_id,
            Invoice.status == "issued",
        )
        .options(
            selectinload(Invoice.charges).selectinload(Charge.utility_breakdowns),
            selectinload(Invoice.charges)
            .selectinload(Charge.allocations)
            .joinedload(PaymentAllocation.payment)
            .joinedload(Payment.receipt),
            joinedload(Invoice.lease)
            .joinedload(Lease.unit)
            .joinedload(Unit.property),
        )
        .order_by(Invoice.issued_at, Invoice.id)
        .all()
    )

    current_outstanding = _statement_totals()
    billed_during_period = _statement_totals()
    invoice_activity = []
    transactions = []
    valid_allocations = []

    for invoice in tenant_invoices:
        invoice_total = _decimal_sum(charge.amount for charge in invoice.charges)
        invoice_paid = _ZERO
        serialized_charges = []
        invoice_allocations_during_period = _ZERO

        for charge in invoice.charges:
            charge_allocations = [
                allocation
                for allocation in charge.allocations
                if allocation.payment is not None
                and allocation.payment.tenant_id == tenant.id
            ]
            paid = _decimal_sum(allocation.amount for allocation in charge_allocations)
            invoice_paid += paid
            current_outstanding[invoice.purpose] += Decimal(charge.amount) - paid

            period_allocations = [
                allocation for allocation in charge_allocations
                if _in_statement_period(allocation.created_at, start_at, end_at)
            ]
            allocation_sum = _decimal_sum(allocation.amount for allocation in period_allocations)
            invoice_allocations_during_period += allocation_sum
            valid_allocations.extend((invoice, charge, allocation) for allocation in period_allocations)

            serialized_charges.append({
                "id": charge.id,
                "category": charge.category,
                "description": charge.description,
                "amount": str(charge.amount),
                "current_paid_amount": str(paid),
                "current_outstanding_balance": str(Decimal(charge.amount) - paid),
                "allocations_during_period": [
                    {
                        "payment_id": allocation.payment_id,
                        "amount": str(allocation.amount),
                        "allocated_at": allocation.created_at.astimezone(_STATEMENT_TIMEZONE).isoformat(),
                    }
                    for allocation in period_allocations
                ],
                "utility_breakdowns": [
                    {"category": item.category, "amount": str(item.amount)}
                    for item in sorted(charge.utility_breakdowns, key=lambda item: item.category)
                ],
            })

        invoice_in_period = _in_statement_period(invoice.issued_at, start_at, end_at)
        if invoice_in_period:
            billed_during_period[invoice.purpose] += invoice_total
            transactions.extend({
                "event_at": invoice.issued_at.astimezone(_STATEMENT_TIMEZONE).isoformat(),
                "type": "invoice_charge",
                "direction": "debit",
                "invoice_id": invoice.id,
                "payment_id": None,
                "charge_id": charge.id,
                "purpose": invoice.purpose,
                "description": charge.description or f"{charge.category.title()} charge",
                "amount": str(charge.amount),
            } for charge in invoice.charges)

        if invoice_in_period:
            invoice_activity.append({
                "id": invoice.id,
                "purpose": invoice.purpose,
                "status": invoice.status,
                "period_start": invoice.period_start.isoformat(),
                "period_end": invoice.period_end.isoformat(),
                "issued_at": invoice.issued_at.astimezone(_STATEMENT_TIMEZONE).isoformat(),
                "due_date": invoice.due_date.isoformat(),
                "property": {
                    "id": invoice.lease.unit.property.id,
                    "name": invoice.lease.unit.property.name,
                },
                "unit": {
                    "id": invoice.lease.unit.id,
                    "unit_number": invoice.lease.unit.unit_number,
                },
                "total_amount": str(invoice_total),
                "current_paid_amount": str(invoice_paid),
                "current_outstanding_balance": str(invoice_total - invoice_paid),
                "allocations_during_period": str(invoice_allocations_during_period),
                "charges": serialized_charges,
            })

    allocations_during_period = _statement_totals()
    for invoice, charge, allocation in valid_allocations:
        allocations_during_period[invoice.purpose] += Decimal(allocation.amount)
        transactions.append({
            "event_at": allocation.created_at.astimezone(_STATEMENT_TIMEZONE).isoformat(),
            "type": "payment_allocation",
            "direction": "credit",
            "invoice_id": invoice.id,
            "payment_id": allocation.payment_id,
            "charge_id": charge.id,
            "purpose": invoice.purpose,
            "description": charge.description or f"{charge.category.title()} charge payment",
            "amount": str(allocation.amount),
            "payment_reference": allocation.payment.reference,
            "receipt_number": allocation.payment.receipt.receipt_number if allocation.payment.receipt else None,
        })

    payments = (
        Payment.query.filter_by(tenant_id=tenant.id)
        .options(selectinload(Payment.receipt))
        .order_by(Payment.received_at, Payment.id)
        .all()
    )
    payment_allocations = {}
    current_allocated_by_payment = {}
    for invoice, charge, allocation in valid_allocations:
        payment_allocations.setdefault(allocation.payment_id, []).append((invoice, charge, allocation))
    for invoice in tenant_invoices:
        for charge in invoice.charges:
            for allocation in charge.allocations:
                if allocation.payment is not None and allocation.payment.tenant_id == tenant.id:
                    current_allocated_by_payment[allocation.payment_id] = (
                        current_allocated_by_payment.get(allocation.payment_id, _ZERO)
                        + Decimal(allocation.amount)
                    )

    payments_received_during_period = _ZERO
    payment_activity = []
    for payment in payments:
        received_in_period = _in_statement_period(payment.received_at, start_at, end_at)
        period_payment_allocations = payment_allocations.get(payment.id, [])
        allocation_sum = _decimal_sum(item[2].amount for item in period_payment_allocations)
        if received_in_period:
            payments_received_during_period += Decimal(payment.amount)
        if not received_in_period and not period_payment_allocations:
            continue
        payment_activity.append({
            "id": payment.id,
            "received_at": payment.received_at.astimezone(_STATEMENT_TIMEZONE).isoformat(),
            "amount": str(payment.amount),
            "currency": payment.currency,
            "method": payment.method,
            "reference": payment.reference,
            "receipt_number": payment.receipt.receipt_number if payment.receipt else None,
            "allocated_amount_during_period": str(allocation_sum),
            "current_allocated_amount": str(current_allocated_by_payment.get(payment.id, _ZERO)),
            "current_unallocated_amount": str(Decimal(payment.amount) - current_allocated_by_payment.get(payment.id, _ZERO)),
            "allocations": [
                {
                    "invoice_id": invoice.id,
                    "charge_id": charge.id,
                    "purpose": invoice.purpose,
                    "charge_category": charge.category,
                    "description": charge.description,
                    "amount": str(allocation.amount),
                    "allocated_at": allocation.created_at.astimezone(_STATEMENT_TIMEZONE).isoformat(),
                    "invoice_period_start": invoice.period_start.isoformat(),
                    "invoice_period_end": invoice.period_end.isoformat(),
                }
                for invoice, charge, allocation in period_payment_allocations
            ],
        })

    transactions.sort(key=lambda item: (item["event_at"], 0 if item["type"] == "invoice_charge" else 1, item["invoice_id"], item["charge_id"]))

    statement_period = {
        "start_date": start_date.isoformat() if start_date else None,
        "end_date": end_date.isoformat() if end_date else None,
        "includes_all_history": start_date is None and end_date is None,
        "timezone": "Africa/Nairobi",
    }
    return jsonify({
        "tenant": _tenant_to_dict(tenant),
        "statement_period": statement_period,
        "invoices": invoice_activity,
        "payments": payment_activity,
        "transaction_history": transactions,
        "summary": {
            "billed_during_period": _statement_totals_dict(billed_during_period),
            "allocated_during_period": _statement_totals_dict(allocations_during_period),
            "payments_received_during_period": str(payments_received_during_period),
            "current_outstanding_balance": _statement_totals_dict(current_outstanding),
        },
    }), 200


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
