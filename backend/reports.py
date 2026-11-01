"""Landlord-scoped financial reporting endpoints."""

from datetime import date, datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy import func, text

from authorization import get_current_landlord_id
from extensions import db
from models import (
    Charge,
    Invoice,
    Lease,
    Payment,
    PaymentAllocation,
    Property,
    Tenant,
    Unit,
    UtilityBreakdown,
)


reports_bp = Blueprint("reports", __name__, url_prefix="/api/reports")
ZERO = Decimal("0.00")
PURPOSES = ("rent", "utilities", "other")
BUSINESS_TIMEZONE = ZoneInfo("Africa/Nairobi")


@reports_bp.before_request
def use_consistent_read_snapshot():
    # Reporting runs several aggregate queries. A repeatable, read-only
    # transaction keeps every metric on the same PostgreSQL snapshot.
    # Some requests can leave an open transaction on the shared Flask-SQLAlchemy
    # session, so reset it before setting the isolation level for this request.
    session = db.session()
    if session.in_transaction():
        session.rollback()

    session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))


def _parse_month(value):
    if not isinstance(value, str) or len(value) != 7 or value[4] != "-":
        return None
    try:
        parsed = date.fromisoformat(f"{value}-01")
    except ValueError:
        return None
    if parsed.strftime("%Y-%m") != value:
        return None
    start_local = datetime(parsed.year, parsed.month, 1, tzinfo=BUSINESS_TIMEZONE)
    if parsed.month == 12:
        end_local = datetime(parsed.year + 1, 1, 1, tzinfo=BUSINESS_TIMEZONE)
    else:
        end_local = datetime(parsed.year, parsed.month + 1, 1, tzinfo=BUSINESS_TIMEZONE)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def _money(value):
    return format(Decimal(value or 0).quantize(Decimal("0.01")), "f")


def _purpose_totals(rows):
    totals = {purpose: ZERO for purpose in PURPOSES}
    for purpose, amount in rows:
        if purpose in totals:
            totals[purpose] = Decimal(amount or 0)
    return totals


def _serialize_totals(totals):
    return {
        **{purpose: _money(totals[purpose]) for purpose in PURPOSES},
        "total": _money(sum((totals[purpose] for purpose in PURPOSES), ZERO)),
    }


def _valid_allocation_totals(landlord_id, property_id=None):
    """Aggregate allocations that match the invoice's tenant and owner."""
    query = (
        db.session.query(
            PaymentAllocation.charge_id.label("charge_id"),
            func.sum(PaymentAllocation.amount).label("paid"),
        )
        .join(Payment, PaymentAllocation.payment_id == Payment.id)
        .join(Tenant, Payment.tenant_id == Tenant.id)
        .join(Charge, PaymentAllocation.charge_id == Charge.id)
        .join(Invoice, Charge.invoice_id == Invoice.id)
        .join(Lease, Invoice.lease_id == Lease.id)
        .join(Unit, Lease.unit_id == Unit.id)
        .join(Property, Unit.property_id == Property.id)
        .filter(
            Payment.tenant_id == Lease.tenant_id,
            Property.owner_id == landlord_id,
            Tenant.owner_id == landlord_id,
        )
    )
    if property_id is not None:
        query = query.filter(Property.id == property_id)
    return query.group_by(PaymentAllocation.charge_id).subquery()


@reports_bp.get("/financial")
@jwt_required()
def financial_report():
    landlord_id = get_current_landlord_id()
    if landlord_id is None:
        return jsonify({"error": "An authenticated landlord account is required."}), 403

    period = _parse_month(request.args.get("month"))
    if period is None:
        return jsonify({"error": "month must be a valid month in YYYY-MM format."}), 400
    month_start, month_end = period

    raw_property_id = request.args.get("property_id")
    property_id = None
    if raw_property_id is not None:
        try:
            property_id = int(raw_property_id)
        except (TypeError, ValueError):
            return jsonify({"error": "property_id must be a positive integer."}), 400
        if property_id <= 0:
            return jsonify({"error": "property_id must be a positive integer."}), 400
        owned_property = Property.query.filter_by(
            id=property_id,
            owner_id=landlord_id,
        ).first()
        if owned_property is None:
            return jsonify({"error": "Property not found."}), 404

    billed_rows = (
        db.session.query(Invoice.purpose, func.coalesce(func.sum(Charge.amount), 0))
        .select_from(Invoice)
        .join(Lease, Invoice.lease_id == Lease.id)
        .join(Unit, Lease.unit_id == Unit.id)
        .join(Property, Unit.property_id == Property.id)
        .join(Tenant, Lease.tenant_id == Tenant.id)
        .join(Charge, Charge.invoice_id == Invoice.id)
        .filter(
            Property.owner_id == landlord_id,
            Tenant.owner_id == landlord_id,
            Invoice.status == "issued",
            Invoice.issued_at >= month_start,
            Invoice.issued_at < month_end,
        )
    )
    if property_id is not None:
        billed_rows = billed_rows.filter(Property.id == property_id)
    billed = _purpose_totals(billed_rows.group_by(Invoice.purpose).all())

    valid_allocations = _valid_allocation_totals(landlord_id, property_id)
    outstanding_rows = (
        db.session.query(
            Invoice.purpose,
            func.coalesce(
                func.sum(Charge.amount - func.coalesce(valid_allocations.c.paid, 0)),
                0,
            ),
        )
        .select_from(Invoice)
        .join(Lease, Invoice.lease_id == Lease.id)
        .join(Unit, Lease.unit_id == Unit.id)
        .join(Property, Unit.property_id == Property.id)
        .join(Tenant, Lease.tenant_id == Tenant.id)
        .join(Charge, Charge.invoice_id == Invoice.id)
        .outerjoin(
            valid_allocations,
            valid_allocations.c.charge_id == Charge.id,
        )
        .filter(
            Property.owner_id == landlord_id,
            Tenant.owner_id == landlord_id,
            Invoice.status == "issued",
        )
    )
    if property_id is not None:
        outstanding_rows = outstanding_rows.filter(Property.id == property_id)
    outstanding = _purpose_totals(outstanding_rows.group_by(Invoice.purpose).all())

    allocation_rows = (
        db.session.query(
            Invoice.purpose,
            func.coalesce(func.sum(PaymentAllocation.amount), 0),
        )
        .select_from(PaymentAllocation)
        .join(Payment, PaymentAllocation.payment_id == Payment.id)
        .join(Charge, PaymentAllocation.charge_id == Charge.id)
        .join(Invoice, Charge.invoice_id == Invoice.id)
        .join(Lease, Invoice.lease_id == Lease.id)
        .join(Unit, Lease.unit_id == Unit.id)
        .join(Property, Unit.property_id == Property.id)
        .join(Tenant, Lease.tenant_id == Tenant.id)
        .filter(
            Payment.tenant_id == Lease.tenant_id,
            Property.owner_id == landlord_id,
            Tenant.owner_id == landlord_id,
            Invoice.status == "issued",
            PaymentAllocation.created_at >= month_start,
            PaymentAllocation.created_at < month_end,
        )
    )
    if property_id is not None:
        allocation_rows = allocation_rows.filter(Property.id == property_id)
    allocations_received = _purpose_totals(
        allocation_rows.group_by(Invoice.purpose).all()
    )

    cohort_paid_rows = (
        db.session.query(
            Invoice.purpose,
            func.coalesce(func.sum(PaymentAllocation.amount), 0),
        )
        .select_from(PaymentAllocation)
        .join(Payment, PaymentAllocation.payment_id == Payment.id)
        .join(Charge, PaymentAllocation.charge_id == Charge.id)
        .join(Invoice, Charge.invoice_id == Invoice.id)
        .join(Lease, Invoice.lease_id == Lease.id)
        .join(Unit, Lease.unit_id == Unit.id)
        .join(Property, Unit.property_id == Property.id)
        .join(Tenant, Lease.tenant_id == Tenant.id)
        .filter(
            Payment.tenant_id == Lease.tenant_id,
            Property.owner_id == landlord_id,
            Tenant.owner_id == landlord_id,
            Invoice.status == "issued",
            Invoice.issued_at >= month_start,
            Invoice.issued_at < month_end,
        )
    )
    if property_id is not None:
        cohort_paid_rows = cohort_paid_rows.filter(Property.id == property_id)
    cohort_paid = _purpose_totals(cohort_paid_rows.group_by(Invoice.purpose).all())

    breakdown_rows = (
        db.session.query(
            UtilityBreakdown.category,
            func.coalesce(func.sum(UtilityBreakdown.amount), 0),
        )
        .select_from(UtilityBreakdown)
        .join(Charge, UtilityBreakdown.charge_id == Charge.id)
        .join(Invoice, Charge.invoice_id == Invoice.id)
        .join(Lease, Invoice.lease_id == Lease.id)
        .join(Unit, Lease.unit_id == Unit.id)
        .join(Property, Unit.property_id == Property.id)
        .join(Tenant, Lease.tenant_id == Tenant.id)
        .filter(
            Property.owner_id == landlord_id,
            Tenant.owner_id == landlord_id,
            Invoice.status == "issued",
            Invoice.purpose == "utilities",
            Invoice.issued_at >= month_start,
            Invoice.issued_at < month_end,
        )
    )
    if property_id is not None:
        breakdown_rows = breakdown_rows.filter(Property.id == property_id)
    breakdowns = {"water": ZERO, "garbage": ZERO}
    for category, amount in breakdown_rows.group_by(UtilityBreakdown.category).all():
        if category in breakdowns:
            breakdowns[category] = Decimal(amount or 0)

    property_rows = Property.query.filter_by(owner_id=landlord_id)
    if property_id is not None:
        property_rows = property_rows.filter(Property.id == property_id)
    properties = property_rows.order_by(Property.name, Property.id).all()
    property_totals = {
        prop.id: {
            "id": prop.id,
            "name": prop.name,
            "billed": {purpose: ZERO for purpose in PURPOSES},
            "allocations": {purpose: ZERO for purpose in PURPOSES},
            "outstanding": {purpose: ZERO for purpose in PURPOSES},
            "utilities": {"water": ZERO, "garbage": ZERO},
        }
        for prop in properties
    }

    property_billed_rows = (
        db.session.query(Property.id, Invoice.purpose, func.coalesce(func.sum(Charge.amount), 0))
        .select_from(Invoice)
        .join(Lease, Invoice.lease_id == Lease.id)
        .join(Unit, Lease.unit_id == Unit.id)
        .join(Property, Unit.property_id == Property.id)
        .join(Tenant, Lease.tenant_id == Tenant.id)
        .join(Charge, Charge.invoice_id == Invoice.id)
        .filter(
            Property.owner_id == landlord_id,
            Tenant.owner_id == landlord_id,
            Invoice.status == "issued",
            Invoice.issued_at >= month_start,
            Invoice.issued_at < month_end,
        )
    )
    if property_id is not None:
        property_billed_rows = property_billed_rows.filter(Property.id == property_id)
    for prop_id, purpose, amount in property_billed_rows.group_by(Property.id, Invoice.purpose).all():
        property_totals[prop_id]["billed"][purpose] = Decimal(amount or 0)

    property_allocations_rows = (
        db.session.query(
            Property.id,
            Invoice.purpose,
            func.coalesce(func.sum(PaymentAllocation.amount), 0),
        )
        .select_from(PaymentAllocation)
        .join(Payment, PaymentAllocation.payment_id == Payment.id)
        .join(Charge, PaymentAllocation.charge_id == Charge.id)
        .join(Invoice, Charge.invoice_id == Invoice.id)
        .join(Lease, Invoice.lease_id == Lease.id)
        .join(Unit, Lease.unit_id == Unit.id)
        .join(Property, Unit.property_id == Property.id)
        .join(Tenant, Lease.tenant_id == Tenant.id)
        .filter(
            Payment.tenant_id == Lease.tenant_id,
            Property.owner_id == landlord_id,
            Tenant.owner_id == landlord_id,
            Invoice.status == "issued",
            PaymentAllocation.created_at >= month_start,
            PaymentAllocation.created_at < month_end,
        )
    )
    if property_id is not None:
        property_allocations_rows = property_allocations_rows.filter(Property.id == property_id)
    for prop_id, purpose, amount in property_allocations_rows.group_by(Property.id, Invoice.purpose).all():
        property_totals[prop_id]["allocations"][purpose] = Decimal(amount or 0)

    property_valid_allocations = _valid_allocation_totals(landlord_id, property_id)
    property_outstanding_rows = (
        db.session.query(
            Property.id,
            Invoice.purpose,
            func.coalesce(
                func.sum(Charge.amount - func.coalesce(property_valid_allocations.c.paid, 0)),
                0,
            ),
        )
        .select_from(Invoice)
        .join(Lease, Invoice.lease_id == Lease.id)
        .join(Unit, Lease.unit_id == Unit.id)
        .join(Property, Unit.property_id == Property.id)
        .join(Tenant, Lease.tenant_id == Tenant.id)
        .join(Charge, Charge.invoice_id == Invoice.id)
        .outerjoin(property_valid_allocations, property_valid_allocations.c.charge_id == Charge.id)
        .filter(
            Property.owner_id == landlord_id,
            Tenant.owner_id == landlord_id,
            Invoice.status == "issued",
        )
    )
    if property_id is not None:
        property_outstanding_rows = property_outstanding_rows.filter(Property.id == property_id)
    for prop_id, purpose, amount in property_outstanding_rows.group_by(Property.id, Invoice.purpose).all():
        property_totals[prop_id]["outstanding"][purpose] = Decimal(amount or 0)

    property_breakdown_rows = (
        db.session.query(Property.id, UtilityBreakdown.category, func.coalesce(func.sum(UtilityBreakdown.amount), 0))
        .select_from(UtilityBreakdown)
        .join(Charge, UtilityBreakdown.charge_id == Charge.id)
        .join(Invoice, Charge.invoice_id == Invoice.id)
        .join(Lease, Invoice.lease_id == Lease.id)
        .join(Unit, Lease.unit_id == Unit.id)
        .join(Property, Unit.property_id == Property.id)
        .join(Tenant, Lease.tenant_id == Tenant.id)
        .filter(
            Property.owner_id == landlord_id,
            Tenant.owner_id == landlord_id,
            Invoice.status == "issued",
            Invoice.purpose == "utilities",
            Invoice.issued_at >= month_start,
            Invoice.issued_at < month_end,
        )
    )
    if property_id is not None:
        property_breakdown_rows = property_breakdown_rows.filter(Property.id == property_id)
    for prop_id, category, amount in property_breakdown_rows.group_by(Property.id, UtilityBreakdown.category).all():
        if category in {"water", "garbage"}:
            property_totals[prop_id]["utilities"][category] = Decimal(amount or 0)

    property_breakdown = [
        {
            "property_id": prop_id,
            "property_name": data["name"],
            "billed_during_month": _serialize_totals(data["billed"]),
            "allocations_received_during_month": _serialize_totals(data["allocations"]),
            "outstanding_current_issued_invoices": _serialize_totals(data["outstanding"]),
            "utility_breakdown_billed_during_month": {
                "water": _money(data["utilities"]["water"]),
                "garbage": _money(data["utilities"]["garbage"]),
            },
        }
        for prop_id, data in property_totals.items()
    ]

    rates = {}
    rate_totals = {
        "billed": sum((billed[purpose] for purpose in PURPOSES), ZERO),
        "cohort_paid": sum((cohort_paid[purpose] for purpose in PURPOSES), ZERO),
        "allocations_received": sum((allocations_received[purpose] for purpose in PURPOSES), ZERO),
    }
    for purpose in (*PURPOSES, "total"):
        if purpose == "total":
            denominator = rate_totals["billed"]
            cohort_amount = rate_totals["cohort_paid"]
            allocation_amount = rate_totals["allocations_received"]
        else:
            denominator = billed[purpose]
            cohort_amount = cohort_paid[purpose]
            allocation_amount = allocations_received[purpose]
        rates[purpose] = {
            "current_paid_on_invoices_issued_in_month": {
                "numerator": _money(cohort_amount),
                "denominator": _money(denominator),
                "rate": (
                    str((cohort_amount / denominator * 100).quantize(Decimal("0.01")))
                    if denominator else None
                ),
            },
            "allocations_received_during_month": {
                "numerator": _money(allocation_amount),
                "denominator": _money(denominator),
                "rate": (
                    str((allocation_amount / denominator * 100).quantize(Decimal("0.01")))
                    if denominator else None
                ),
            },
        }

    return jsonify({
        "month": request.args["month"],
        "timezone": "Africa/Nairobi",
        "currency": "KES",
        "property_id": property_id,
        "outstanding_as_of": datetime.now(timezone.utc).isoformat(),
        "definitions": {
            "billed_during_month": "Charges on invoices issued during the selected Africa/Nairobi calendar month; draft and void invoices are excluded.",
            "allocations_received_during_month": "Valid allocations created during the selected Africa/Nairobi calendar month, including allocations applied to older invoices.",
            "current_paid_on_invoices_issued_during_month": "Current valid allocations on invoices issued during the selected month, regardless of when those allocations were created.",
            "outstanding_current_issued_invoices": "Current charge balances on all issued invoices as of outstanding_as_of, including invoices issued before the selected month.",
            "collection_rates_percent": {
                "current_paid_on_invoices_issued_in_month": "For each purpose, current valid allocations to issued invoices issued during the selected month divided by that purpose's billed_during_month amount.",
                "allocations_received_during_month": "For each purpose, valid allocations created during the selected month (including allocations against older invoices) divided by that purpose's billed_during_month amount.",
                "total": "The corresponding numerator and denominator are summed across rent, utilities, and other before division.",
                "zero_denominator": "The rate is null when billed_during_month is zero. The allocations_received_during_month rate can exceed 100% when arrears are collected.",
            },
        },
        "billed_during_month": _serialize_totals(billed),
        "allocations_received_during_month": _serialize_totals(allocations_received),
        "current_paid_on_invoices_issued_during_month": _serialize_totals(cohort_paid),
        "outstanding_current_issued_invoices": _serialize_totals(outstanding),
        "utility_breakdown_billed_during_month": {
            "water": _money(breakdowns["water"]),
            "garbage": _money(breakdowns["garbage"]),
        },
        "collection_rates_percent": rates,
        "property_breakdown": property_breakdown,
    }), 200


@reports_bp.get("/arrears")
@jwt_required()
def arrears_report():
    """Return overdue invoice balances for the authenticated landlord."""
    landlord_id = get_jwt_identity()

    try:
        landlord_id = int(landlord_id)
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid authenticated user."}), 401

    raw_property_id = request.args.get("property_id")
    property_id = None

    if raw_property_id is not None:
        try:
            property_id = int(raw_property_id)
        except (TypeError, ValueError):
            return jsonify({"error": "property_id must be a positive integer."}), 400

        if property_id <= 0:
            return jsonify({"error": "property_id must be a positive integer."}), 400

        owned_property = Property.query.filter_by(
            id=property_id,
            owner_id=landlord_id,
        ).first()

        if owned_property is None:
            return jsonify({"error": "Property not found."}), 404

    today = datetime.now(BUSINESS_TIMEZONE).date()
    valid_allocations = _valid_allocation_totals(landlord_id, property_id)

    rows = (
        db.session.query(
            Invoice.id.label("invoice_id"),
            Invoice.period_start,
            Invoice.period_end,
            Invoice.due_date,
            Invoice.purpose,
            Tenant.id.label("tenant_id"),
            Tenant.full_name.label("tenant_name"),
            Property.id.label("property_id"),
            Property.name.label("property_name"),
            Unit.id.label("unit_id"),
            Unit.unit_number,
            Charge.id.label("charge_id"),
            Charge.amount.label("charge_amount"),
            func.coalesce(valid_allocations.c.paid, 0).label("paid_amount"),
        )
        .select_from(Invoice)
        .join(Lease, Invoice.lease_id == Lease.id)
        .join(Unit, Lease.unit_id == Unit.id)
        .join(Property, Unit.property_id == Property.id)
        .join(Tenant, Lease.tenant_id == Tenant.id)
        .join(Charge, Charge.invoice_id == Invoice.id)
        .outerjoin(valid_allocations, valid_allocations.c.charge_id == Charge.id)
        .filter(
            Property.owner_id == landlord_id,
            Tenant.owner_id == landlord_id,
            Invoice.status == "issued",
            Invoice.due_date < today,
        )
    )

    if property_id is not None:
        rows = rows.filter(Property.id == property_id)

    invoice_records = {}

    for row in rows.order_by(Invoice.due_date, Tenant.full_name, Invoice.id).all():
        invoice = invoice_records.setdefault(
            row.invoice_id,
            {
                "invoice_id": row.invoice_id,
                "tenant_id": row.tenant_id,
                "tenant_name": row.tenant_name,
                "property_id": row.property_id,
                "property_name": row.property_name,
                "unit_id": row.unit_id,
                "unit_number": row.unit_number,
                "purpose": row.purpose,
                "period_start": row.period_start.isoformat(),
                "period_end": row.period_end.isoformat(),
                "due_date": row.due_date.isoformat(),
                "days_overdue": (today - row.due_date).days,
                "total_amount": ZERO,
                "paid_amount": ZERO,
                "outstanding_balance": ZERO,
            },
        )

        charge_amount = Decimal(row.charge_amount or 0)
        paid_amount = Decimal(row.paid_amount or 0)
        invoice["total_amount"] += charge_amount
        invoice["paid_amount"] += paid_amount
        invoice["outstanding_balance"] += charge_amount - paid_amount

    invoices = []
    tenant_totals = {}

    for invoice in invoice_records.values():
        if invoice["outstanding_balance"] <= ZERO:
            continue

        for key in ("total_amount", "paid_amount", "outstanding_balance"):
            invoice[key] = _money(invoice[key])

        invoices.append(invoice)

        tenant = tenant_totals.setdefault(
            invoice["tenant_id"],
            {
                "tenant_id": invoice["tenant_id"],
                "tenant_name": invoice["tenant_name"],
                "invoice_count": 0,
                "outstanding_balance": ZERO,
                "oldest_due_date": invoice["due_date"],
                "maximum_days_overdue": invoice["days_overdue"],
            },
        )

        tenant["invoice_count"] += 1
        tenant["outstanding_balance"] += Decimal(invoice["outstanding_balance"])
        tenant["maximum_days_overdue"] = max(
            tenant["maximum_days_overdue"],
            invoice["days_overdue"],
        )
        tenant["oldest_due_date"] = min(
            tenant["oldest_due_date"],
            invoice["due_date"],
        )

    tenant_rows = []
    for tenant in tenant_totals.values():
        tenant["outstanding_balance"] = _money(tenant["outstanding_balance"])
        tenant_rows.append(tenant)

    tenant_rows.sort(
        key=lambda tenant: Decimal(tenant["outstanding_balance"]),
        reverse=True,
    )

    total_overdue = sum(
        (Decimal(invoice["outstanding_balance"]) for invoice in invoices),
        ZERO,
    )

    return jsonify({
        "as_of_date": today.isoformat(),
        "timezone": "Africa/Nairobi",
        "currency": "KES",
        "property_id": property_id,
        "summary": {
            "total_overdue": _money(total_overdue),
            "overdue_invoice_count": len(invoices),
            "overdue_tenant_count": len(tenant_rows),
        },
        "tenants": tenant_rows,
        "invoices": invoices,
    }), 200
