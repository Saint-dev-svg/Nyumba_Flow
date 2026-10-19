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
    full_name = db.Column(db.String(120), nullable = False)
    email = db.Column(db.String(255), unique = True, nullable = False, index = True)
    phone_number = db.Column(db.String(30), nullable = True, index = True)
    national_id_last4 = db.Column(db.String(4), nullable = True)
    created_at = db.Column(db.DateTime(timezone = True), nullable = False, default = lambda: datetime.now(timezone.utc),)
    
    leases = db.relationship("Lease", back_populates = "tenant")
    
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
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    unit = db.relationship("Unit", back_populates="leases")
    tenant = db.relationship("Tenant", back_populates="leases")

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