from datetime import datetime, timezone
from email.policy import default

from sqlalchemy import CheckConstraint, UniqueConstraint
from werkzeug.security import generate_password_hash, check_password_hash

from extensions import db

class User(db.Model):
    __tablename__ = "users"
    
    id = db.Column(db.Integer, primary_key = True)
    full_name = db.Column(db.String(120), nullable = False)
    email = db.Column(db.String(255), unique = True, nullable = False, index = True)
    password_hash = db.Column(db.String(255), nullable = False)
    role = db.Column(db.String(20), nullable = False, default = "landlord")
    created_at = db.Column(db.DateTime(timezone = True), nullable = False, default = lambda: datetime.now(timezone.utc),)
    tenants = db.relationship("Tenant", back_populates = "owner", cascade = "all, delete-orphan",)
    
    __table_args__ = (
        CheckConstraint(
            "role IN ('landlord', 'manager')",
            name = "ck_users_role",
        ),
    )
    
    properties = db.relationship(
        "Property",
        back_populates = "owner", 
        cascade = "all, delete-orphan",
    )
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
        
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    
    
class Property(db.Model):
    __tablename__ = "properties"
    
    id = db.Column(db.Integer, primary_key = True)
    owner_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete = "CASCADE"), nullable = False, index = True,)
    name = db.Column(db.String(150), nullable = False)
    address = db.Column(db.String(255), nullable = False)
    created_at = db.Column(db.DateTime(timezone = True), nullable = False, default = lambda: datetime.now(timezone.utc),)
    
    owner = db.relationship("User", back_populates = "properties")
    units = db.relationship("Unit", back_populates = "property", cascade = "all, delete-orphan",)
    
    __table_args__ = (
            UniqueConstraint(
                "owner_id", "name",
                name = "uq_property_owner_name"
            ),
        )
    

class Unit(db.Model):
    __tablename__ = "units"
    
    id = db.Column(db.Integer, primary_key = True)
    property_id = db.Column(db.Integer, db.ForeignKey("properties.id", ondelete = "CASCADE"), nullable = False, index = True,)
    unit_number = db.Column(db.String(50), nullable = False)
    bedrooms = db.Column(db.Integer, nullable = False, default = 1)
    monthly_rent = db.Column(db.Numeric(12, 2), nullable = False)
    is_active = db.Column(db.Boolean, nullable = False, default = True)
    
    property = db.relationship("Property", back_populates = "units")
    leases = db.relationship("Lease", back_populates = "unit")
    
    __table_args__ = (
                UniqueConstraint(
                    "property_id", "unit_number",
                    name = "uq_unit_property_number"
                ),
                CheckConstraint(
                    "bedrooms >= 0",
                    name = "ck_unit_bedrooms_non_negative"
                ),
                CheckConstraint(
                    "monthly_rent >= 0",
                    name = "ck_unit_monthly_rent_non_negative"
                ),
            )


class Tenant(db.Model):
    __tablename__ = "tenants"
    
    id = db.Column(db.Integer, primary_key = True)
    owner_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete = "CASCADE"), nullable = False, index = True,)
    full_name = db.Column(db.String(120), nullable = False)
    email = db.Column(db.String(255), unique = True, nullable = False, index = True)
    phone_number = db.Column(db.String(30), nullable = True, index = True)
    national_id_last4 = db.Column(db.String(4), nullable = True)
    created_at = db.Column(db.DateTime(timezone = True), nullable = False, default = lambda: datetime.now(timezone.utc),)
    
    leases = db.relationship("Lease", back_populates = "tenant")
    payments = db.relationship("Payment", back_populates="tenant")
    owner = db.relationship("User", back_populates = "tenants")
    
class Lease(db.Model):
    __tablename__ = "leases"

    id = db.Column(db.Integer, primary_key=True)

    unit_id = db.Column(
        db.Integer,
        db.ForeignKey("units.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    # Connects each lease to the tenant occupying the unit.
    tenant_id = db.Column(
        db.Integer,
        db.ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=True)
    monthly_rent = db.Column(db.Numeric(12, 2), nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=False)

    unit = db.relationship("Unit", back_populates="leases")
    tenant = db.relationship("Tenant", back_populates="leases")
    invoices = db.relationship("Invoice", back_populates="lease")

    __table_args__ = (
        CheckConstraint(
            "end_date IS NULL OR end_date >= start_date",
            name="ck_lease_dates",
        ),
        CheckConstraint(
            "monthly_rent >= 0",
            name="ck_lease_rent_nonnegative",
        ),
    )


class Invoice(db.Model):
    """A bill for one lease and one billing period."""

    __tablename__ = "invoices"

    id = db.Column(db.Integer, primary_key=True)
    lease_id = db.Column(
        db.Integer,
        db.ForeignKey("leases.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    period_start = db.Column(db.Date, nullable=False)
    period_end = db.Column(db.Date, nullable=False)
    due_date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="draft")
    issued_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    lease = db.relationship("Lease", back_populates="invoices")
    charges = db.relationship("Charge", back_populates="invoice")

    __table_args__ = (
        UniqueConstraint(
            "lease_id",
            "period_start",
            "period_end",
            name="uq_invoice_lease_period",
        ),
        CheckConstraint(
            "period_end >= period_start",
            name="ck_invoice_period_dates",
        ),
        CheckConstraint(
            "status IN ('draft', 'issued', 'void')",
            name="ck_invoice_status",
        ),
    )


class Charge(db.Model):
    """A separately itemized amount on an invoice."""

    __tablename__ = "charges"

    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(
        db.Integer,
        db.ForeignKey("invoices.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    category = db.Column(db.String(20), nullable=False)
    description = db.Column(db.String(255), nullable=True)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    invoice = db.relationship("Invoice", back_populates="charges")
    allocations = db.relationship("PaymentAllocation", back_populates="charge")
    utility_breakdowns = db.relationship(
        "UtilityBreakdown",
        back_populates="charge",
    )

    __table_args__ = (
        CheckConstraint(
            "category IN ('rent', 'utilities', 'other')",
            name="ck_charge_category",
        ),
        CheckConstraint("amount >= 0", name="ck_charge_amount_nonnegative"),
    )


class UtilityBreakdown(db.Model):
    """Water and garbage components of one combined utilities charge."""

    __tablename__ = "utility_breakdowns"

    id = db.Column(db.Integer, primary_key=True)
    charge_id = db.Column(
        db.Integer,
        db.ForeignKey("charges.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    category = db.Column(db.String(20), nullable=False)
    amount = db.Column(db.Numeric(12, 2), nullable=False)

    charge = db.relationship("Charge", back_populates="utility_breakdowns")

    __table_args__ = (
        UniqueConstraint(
            "charge_id",
            "category",
            name="uq_utility_breakdown_category",
        ),
        CheckConstraint(
            "category IN ('water', 'garbage')",
            name="ck_utility_breakdown_category",
        ),
        CheckConstraint(
            "amount >= 0",
            name="ck_utility_breakdown_amount_nonnegative",
        ),
    )


class Payment(db.Model):
    """A confirmed payment received from a tenant."""

    __tablename__ = "payments"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(
        db.Integer,
        db.ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    currency = db.Column(db.String(3), nullable=False, default="KES")
    method = db.Column(db.String(20), nullable=False)
    reference = db.Column(db.String(100), nullable=True)
    received_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    tenant = db.relationship("Tenant", back_populates="payments")
    allocations = db.relationship("PaymentAllocation", back_populates="payment")
    receipt = db.relationship("Receipt", back_populates="payment", uselist=False)
    provider_attempts = db.relationship(
        "PaymentAttempt",
        back_populates="payment",
    )

    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_payment_amount_positive"),
        CheckConstraint(
            "method IN ('cash', 'bank_transfer', 'M-pesa', 'other')",
            name="ck_payment_method",
        ),
        CheckConstraint("length(currency) = 3", name="ck_payment_currency_length"),
    )


class PaymentAllocation(db.Model):
    """The portion of a payment applied to one invoice charge."""

    __tablename__ = "payment_allocations"

    id = db.Column(db.Integer, primary_key=True)
    payment_id = db.Column(
        db.Integer,
        db.ForeignKey("payments.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    charge_id = db.Column(
        db.Integer,
        db.ForeignKey("charges.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    payment = db.relationship("Payment", back_populates="allocations")
    charge = db.relationship("Charge", back_populates="allocations")

    __table_args__ = (
        UniqueConstraint(
            "payment_id",
            "charge_id",
            name="uq_payment_allocation_charge",
        ),
        CheckConstraint("amount > 0", name="ck_payment_allocation_positive"),
    )


class Receipt(db.Model):
    """An issued receipt snapshot for a confirmed payment."""

    __tablename__ = "receipts"

    id = db.Column(db.Integer, primary_key=True)
    payment_id = db.Column(
        db.Integer,
        db.ForeignKey("payments.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    receipt_number = db.Column(db.String(50), nullable=False, unique=True)
    recipient_name = db.Column(db.String(120), nullable=False)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    currency = db.Column(db.String(3), nullable=False)
    details = db.Column(db.JSON, nullable=True)
    issued_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    payment = db.relationship("Payment", back_populates="receipt")

    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_receipt_amount_positive"),
        CheckConstraint("length(currency) = 3", name="ck_receipt_currency_length"),
    )


class PaymentAttempt(db.Model):
    """A provider attempt, including pending or failed M-Pesa requests."""

    __tablename__ = "payment_attempts"

    id = db.Column(db.Integer, primary_key=True)
    payment_id = db.Column(
        db.Integer,
        db.ForeignKey("payments.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    provider = db.Column(db.String(30), nullable=False)
    checkout_request_id = db.Column(db.String(100), nullable=True)
    merchant_request_id = db.Column(db.String(100), nullable=True)
    provider_transaction_id = db.Column(db.String(100), nullable=True)
    phone_number = db.Column(db.String(30), nullable=True)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="initiated")
    result_code = db.Column(db.String(50), nullable=True)
    result_description = db.Column(db.String(255), nullable=True)
    callback_payload = db.Column(db.JSON, nullable=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    payment = db.relationship("Payment", back_populates="provider_attempts")

    __table_args__ = (
        UniqueConstraint(
            "provider",
            "checkout_request_id",
            name="uq_payment_attempt_provider_checkout",
        ),
        UniqueConstraint(
            "provider",
            "provider_transaction_id",
            name="uq_payment_attempt_provider_transaction",
        ),
        CheckConstraint("amount > 0", name="ck_payment_attempt_amount_positive"),
        CheckConstraint(
            "status IN ('initiated', 'pending', 'succeeded', 'failed', 'cancelled')",
            name="ck_payment_attempt_status",
        ),
        CheckConstraint(
            "status != 'succeeded' OR payment_id IS NOT NULL",
            name="ck_successful_attempt_has_payment",
        ),
    )
