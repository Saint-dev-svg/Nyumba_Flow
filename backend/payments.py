from decimal import Decimal, InvalidOperation
from uuid import uuid4

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from extensions import db
from models import (
    Charge,
    Invoice,
    Lease,
    Payment,
    PaymentAllocation,
    Property,
    Receipt,
    Tenant,
    Unit,
    User,
)


payments_bp = Blueprint("payments", __name__, url_prefix="/api/payments")
ZERO = Decimal("0.00")
MAX_AMOUNT = Decimal("9999999999.99")
PAYMENT_METHODS = {"cash", "bank_transfer", "M-pesa", "other"}


def _landlord_id():
    try:
        user_id = int(get_jwt_identity())
    except (TypeError, ValueError):
        return None
    landlord = db.session.get(User, user_id)
    if landlord is None or landlord.role != "landlord":
        return None
    return landlord.id


def _parse_amount(value, field, *, allow_zero=False):
    if value is None or isinstance(value, bool):
        return None, f"{field} must be a valid amount."
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None, f"{field} must be a valid amount."
    if not amount.is_finite() or amount < 0 or (not allow_zero and amount == 0):
        qualifier = "non-negative" if allow_zero else "positive"
        return None, f"{field} must be a finite, {qualifier} amount."
    if amount.as_tuple().exponent < -2:
        return None, f"{field} cannot have more than two decimal places."
    if amount > MAX_AMOUNT:
        return None, f"{field} is too large."
    return amount, None


def _amount_sum(values):
    return sum((Decimal(value) for value in values), ZERO)


def _tenant_to_dict(tenant):
    return {"id": tenant.id, "full_name": tenant.full_name}


def _payment_to_dict(payment):
    allocated = _amount_sum(
        allocation.amount for allocation in payment.allocations
    )
    return {
        "id": payment.id,
        "tenant_id": payment.tenant_id,
        "amount": str(payment.amount),
        "currency": payment.currency,
        "method": payment.method,
        "reference": payment.reference,
        "received_at": payment.received_at.isoformat(),
        "allocated_amount": str(allocated),
        "unallocated_amount": str(Decimal(payment.amount) - allocated),
        "allocations": [
            {
                "charge_id": allocation.charge_id,
                "amount": str(allocation.amount),
            }
            for allocation in sorted(
                payment.allocations,
                key=lambda allocation: allocation.charge_id,
            )
        ],
        "receipt": _receipt_to_dict(payment.receipt) if payment.receipt else None,
    }


def _receipt_to_dict(receipt):
    return {
        "id": receipt.id,
        "receipt_number": receipt.receipt_number,
        "recipient_name": receipt.recipient_name,
        "amount": str(receipt.amount),
        "currency": receipt.currency,
        "issued_at": receipt.issued_at.isoformat(),
    }


def _charge_balance(charge):
    paid = _amount_sum(
        allocation.amount for allocation in charge.allocations
    )
    return paid, Decimal(charge.amount) - paid


def _charge_access_query(landlord_id, tenant_id, charge_ids):
    return (
        Charge.query
        .join(Invoice, Charge.invoice_id == Invoice.id)
        .join(Lease, Invoice.lease_id == Lease.id)
        .join(Unit, Lease.unit_id == Unit.id)
        .join(Property, Unit.property_id == Property.id)
        .join(Tenant, Lease.tenant_id == Tenant.id)
        .filter(
            Charge.id.in_(charge_ids),
            Lease.tenant_id == tenant_id,
            Property.owner_id == landlord_id,
            Tenant.owner_id == landlord_id,
        )
        .order_by(Charge.id)
        .with_for_update()
    )


@payments_bp.post("")
@jwt_required()
def record_payment():
    landlord_id = _landlord_id()
    if landlord_id is None:
        return jsonify({"error": "An authenticated landlord account is required."}), 403

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be valid JSON."}), 400

    tenant_id = data.get("tenant_id")
    if isinstance(tenant_id, bool) or not isinstance(tenant_id, int) or tenant_id <= 0:
        return jsonify({"error": "A valid tenant_id is required."}), 400
    tenant = Tenant.query.filter_by(id=tenant_id, owner_id=landlord_id).first()
    if tenant is None:
        return jsonify({"error": "Tenant not found."}), 404

    amount, error = _parse_amount(data.get("amount"), "amount")
    if error:
        return jsonify({"error": error}), 400

    method = data.get("method")
    if not isinstance(method, str) or method not in PAYMENT_METHODS:
        return jsonify({"error": "method must be cash, bank_transfer, M-pesa, or other."}), 400

    currency = data.get("currency", "KES")
    if not isinstance(currency, str) or len(currency) != 3:
        return jsonify({"error": "currency must contain exactly three characters."}), 400
    currency = currency.upper()

    reference = data.get("reference")
    if reference is not None:
        if not isinstance(reference, str) or len(reference) > 100:
            return jsonify({"error": "reference must be a string of at most 100 characters."}), 400
        reference = reference.strip() or None

    payment = Payment(
        tenant_id=tenant.id,
        amount=amount,
        currency=currency,
        method=method,
        reference=reference,
    )
    receipt = Receipt(
        receipt_number=f"NF-{uuid4().hex.upper()}",
        recipient_name=tenant.full_name,
        amount=amount,
        currency=currency,
    )
    payment.receipt = receipt

    try:
        db.session.add(payment)
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Payment recording failed")
        return jsonify({"error": "Unable to record payment right now."}), 500

    return jsonify({
        "message": "Payment recorded successfully.",
        "payment": _payment_to_dict(payment),
    }), 201


@payments_bp.post("/<int:payment_id>/allocations")
@jwt_required()
def allocate_payment(payment_id):
    landlord_id = _landlord_id()
    if landlord_id is None:
        return jsonify({"error": "An authenticated landlord account is required."}), 403

    payment = (
        Payment.query
        .join(Tenant, Payment.tenant_id == Tenant.id)
        .filter(
            Payment.id == payment_id,
            Tenant.owner_id == landlord_id,
        )
        .with_for_update()
        .first()
    )
    if payment is None:
        return jsonify({"error": "Payment not found."}), 404

    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get("allocations"), list):
        return jsonify({"error": "allocations must be a list."}), 400
    requested = data["allocations"]
    if not requested:
        return jsonify({"error": "At least one allocation is required."}), 400

    requested_by_charge = {}
    for index, item in enumerate(requested):
        field = f"allocations[{index}]"
        if not isinstance(item, dict):
            return jsonify({"error": f"{field} must be an object."}), 400
        charge_id = item.get("charge_id")
        if isinstance(charge_id, bool) or not isinstance(charge_id, int) or charge_id <= 0:
            return jsonify({"error": f"{field}.charge_id must be a positive integer."}), 400
        if charge_id in requested_by_charge:
            return jsonify({"error": "A charge can appear only once per allocation request."}), 400
        amount, error = _parse_amount(item.get("amount"), f"{field}.amount")
        if error:
            return jsonify({"error": error}), 400
        requested_by_charge[charge_id] = amount

    charges = _charge_access_query(
        landlord_id,
        payment.tenant_id,
        list(requested_by_charge),
    ).all()
    charges_by_id = {charge.id: charge for charge in charges}
    if set(charges_by_id) != set(requested_by_charge):
        return jsonify({"error": "One or more charges were not found for this tenant."}), 404

    current_allocated = db.session.query(
        func.coalesce(func.sum(PaymentAllocation.amount), 0)
    ).filter(PaymentAllocation.payment_id == payment.id).scalar()
    current_allocated = Decimal(current_allocated or 0)
    requested_total = _amount_sum(requested_by_charge.values())
    if current_allocated + requested_total > Decimal(payment.amount):
        return jsonify({"error": "Allocations cannot exceed the amount paid."}), 409

    balances_after = {}
    for charge_id, amount in requested_by_charge.items():
        charge = charges_by_id[charge_id]
        paid_on_charge, outstanding = _charge_balance(charge)
        if amount > outstanding:
            return jsonify({
                "error": f"Allocation exceeds the remaining balance for charge {charge_id}.",
                "outstanding_balance": str(outstanding),
            }), 409
        balances_after[charge_id] = (paid_on_charge + amount, outstanding - amount)

    try:
        for charge_id, amount in requested_by_charge.items():
            existing = PaymentAllocation.query.filter_by(
                payment_id=payment.id,
                charge_id=charge_id,
            ).first()
            if existing is None:
                db.session.add(PaymentAllocation(
                    payment_id=payment.id,
                    charge_id=charge_id,
                    amount=amount,
                ))
            else:
                existing.amount = Decimal(existing.amount) + amount
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "The allocation conflicts with an existing payment allocation."}), 409
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Payment allocation failed")
        return jsonify({"error": "Unable to allocate payment right now."}), 500

    return jsonify({
        "message": "Payment allocated successfully.",
        "payment": _payment_to_dict(payment),
        "charge_balances": [
            {
                "charge_id": charge_id,
                "paid_amount": str(balances_after[charge_id][0]),
                "outstanding_balance": str(balances_after[charge_id][1]),
            }
            for charge_id in requested_by_charge
        ],
    }), 200
