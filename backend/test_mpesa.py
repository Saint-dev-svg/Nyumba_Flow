import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from decimal import Decimal
from threading import Barrier

import pytest
from flask_jwt_extended import create_access_token

from extensions import db
from models import (
    Charge,
    Invoice,
    Lease,
    MpesaCallbackTransaction,
    Payment,
    PaymentAllocation,
    Property,
    PropertyPayBillConfiguration,
    Receipt,
    Tenant,
    Unit,
    User,
)
from test_config import create_test_app


@pytest.fixture
def app():
    return create_test_app()


@pytest.fixture
def cleanup_records(app):
    records = {
        "users": set(),
        "tenants": set(),
        "properties": set(),
        "units": set(),
        "leases": set(),
        "configurations": set(),
        "invoices": set(),
    }
    yield records

    with app.app_context():
        if records["configurations"]:
            MpesaCallbackTransaction.query.filter(
                MpesaCallbackTransaction.paybill_configuration_id.in_(
                    records["configurations"]
                )
            ).delete(synchronize_session=False)
        if records["invoices"]:
            Charge.query.filter(
                Charge.invoice_id.in_(records["invoices"])
            ).delete(synchronize_session=False)
            Invoice.query.filter(Invoice.id.in_(records["invoices"])).delete(
                synchronize_session=False
            )
        if records["configurations"]:
            PropertyPayBillConfiguration.query.filter(
                PropertyPayBillConfiguration.id.in_(records["configurations"])
            ).delete(synchronize_session=False)
        if records["leases"]:
            Lease.query.filter(Lease.id.in_(records["leases"])).delete(
                synchronize_session=False
            )
        if records["units"]:
            Unit.query.filter(Unit.id.in_(records["units"])).delete(
                synchronize_session=False
            )
        if records["properties"]:
            Property.query.filter(Property.id.in_(records["properties"])).delete(
                synchronize_session=False
            )
        if records["tenants"]:
            Tenant.query.filter(Tenant.id.in_(records["tenants"])).delete(
                synchronize_session=False
            )
        if records["users"]:
            User.query.filter(User.id.in_(records["users"])).delete(
                synchronize_session=False
            )
        db.session.commit()


def create_landlord():
    landlord = User(
        full_name="M-Pesa Inbox Test Landlord",
        email=f"mpesa.landlord.{uuid.uuid4().hex}@example.com",
        role="landlord",
    )
    landlord.set_password("SecureMpesaPassword123!")
    db.session.add(landlord)
    db.session.commit()
    return landlord


def create_channel(records, landlord_id, shortcode, unit_number="A1"):
    property_obj = Property(
        owner_id=landlord_id,
        name=f"M-Pesa Test Property {uuid.uuid4().hex}",
        address="Nairobi, Kenya",
    )
    db.session.add(property_obj)
    db.session.flush()
    unit = Unit(
        property_id=property_obj.id,
        unit_number=unit_number,
        bedrooms=1,
        monthly_rent="15000.00",
        is_active=True,
    )
    tenant = Tenant(
        owner_id=landlord_id,
        full_name="M-Pesa Test Tenant",
        email=f"mpesa.tenant.{uuid.uuid4().hex}@example.com",
    )
    db.session.add_all([unit, tenant])
    db.session.flush()
    lease = Lease(
        unit_id=unit.id,
        tenant_id=tenant.id,
        start_date=date.today() - timedelta(days=30),
        end_date=None,
        monthly_rent="15000.00",
        is_active=True,
    )
    configuration = PropertyPayBillConfiguration(
        property_id=property_obj.id,
        business_shortcode=shortcode,
        account_reference_type="unit_number",
        is_active=True,
    )
    db.session.add_all([lease, configuration])
    db.session.commit()
    records["properties"].add(property_obj.id)
    records["units"].add(unit.id)
    records["tenants"].add(tenant.id)
    records["leases"].add(lease.id)
    records["configurations"].add(configuration.id)
    return property_obj, unit, tenant, lease, configuration


@pytest.fixture
def channel(app, cleanup_records):
    with app.app_context():
        landlord = create_landlord()
        cleanup_records["users"].add(landlord.id)
        property_obj, unit, tenant, lease, configuration = create_channel(
            cleanup_records, landlord.id, "600111"
        )
        token = create_access_token(identity=str(landlord.id))
        return {
            "landlord_id": landlord.id,
            "property_id": property_obj.id,
            "unit_id": unit.id,
            "tenant_id": tenant.id,
            "lease_id": lease.id,
            "configuration_id": configuration.id,
            "headers": {"Authorization": f"Bearer {token}"},
        }


def callback_payload(
    *,
    transaction_id="QK123ABC",
    shortcode="600111",
    reference="A1",
    amount="15000.00",
    transaction_time="20261106123000",
    currency=None,
):
    payload = {
        "TransID": transaction_id,
        "TransAmount": amount,
        "BusinessShortCode": shortcode,
        "BillRefNumber": reference,
        "TransTime": transaction_time,
        "TransactionType": "Pay Bill",
        "ThirdPartyTransID": "invoice-ref",
    }
    if currency is not None:
        payload["Currency"] = currency
    return payload


def post_callback(client, configuration_id, payload):
    return client.post(
        f"/api/integrations/daraja/c2b/{configuration_id}/confirmation",
        json=payload,
    )


def test_paybill_configuration_create_retrieve_and_historical_reactivation(
    app, channel, cleanup_records
):
    with app.test_client() as client:
        response = client.get(
            f"/api/properties/{channel['property_id']}/mpesa-paybill",
            headers=channel["headers"],
        )
    assert response.status_code == 200
    result = response.get_json()["configurations"]
    assert len(result) == 1
    assert result[0]["business_shortcode"] == "600111"
    assert result[0]["account_reference_type"] == "unit_number"
    assert "consumer_secret" not in result[0]
    assert result[0]["confirmation_callback_path"].endswith(
        f"/{channel['configuration_id']}/confirmation"
    )

    with app.test_client() as client:
        create_response = client.post(
            f"/api/properties/{channel['property_id']}/mpesa-paybill",
            json={"business_shortcode": "600222"},
            headers=channel["headers"],
        )
    assert create_response.status_code == 201
    new_configuration = create_response.get_json()["configuration"]
    cleanup_records["configurations"].add(new_configuration["id"])
    with app.test_client() as client:
        reactivate_response = client.patch(
            f"/api/properties/{channel['property_id']}/mpesa-paybill/"
            f"{channel['configuration_id']}",
            json={"is_active": True},
            headers=channel["headers"],
        )
    assert reactivate_response.status_code == 200
    with app.app_context():
        old = db.session.get(
            PropertyPayBillConfiguration, channel["configuration_id"]
        )
        new = db.session.get(
            PropertyPayBillConfiguration, new_configuration["id"]
        )
        assert old.is_active is True
        assert new.is_active is False


def test_paybill_configuration_is_scoped_to_owning_landlord(app, channel, cleanup_records):
    with app.app_context():
        other_landlord = create_landlord()
        cleanup_records["users"].add(other_landlord.id)
        other_token = create_access_token(identity=str(other_landlord.id))

    with app.test_client() as client:
        response = client.post(
            f"/api/properties/{channel['property_id']}/mpesa-paybill",
            json={"business_shortcode": "600333"},
            headers={"Authorization": f"Bearer {other_token}"},
        )
    assert response.status_code == 404


def test_properties_have_separate_channels_and_same_unit_numbers_are_scoped(
    app, channel, cleanup_records
):
    with app.app_context():
        _, second_unit, _, second_lease, second_configuration = create_channel(
            cleanup_records, channel["landlord_id"], "600222", unit_number="A1"
        )
        second_unit_id = second_unit.id
        second_lease_id = second_lease.id
        second_configuration_id = second_configuration.id
    with app.test_client() as client:
        first_response = post_callback(
            client,
            channel["configuration_id"],
            callback_payload(transaction_id="QK-FIRST"),
        )
        second_response = post_callback(
            client,
            second_configuration_id,
            callback_payload(transaction_id="QK-SECOND", shortcode="600222"),
        )
    assert first_response.status_code == 200
    assert second_response.status_code == 200
    with app.app_context():
        first = MpesaCallbackTransaction.query.filter_by(
            provider_transaction_id="QK-FIRST"
        ).one()
        second = MpesaCallbackTransaction.query.filter_by(
            provider_transaction_id="QK-SECOND"
        ).one()
        assert first.unit_id == channel["unit_id"]
        assert first.lease_id == channel["lease_id"]
        assert second.unit_id == second_unit_id
        assert second.lease_id == second_lease_id
        assert first.property_id != second.property_id


def test_unknown_shortcode_is_retained_as_exception(app, channel):
    with app.test_client() as client:
        response = post_callback(
            client,
            channel["configuration_id"],
            callback_payload(transaction_id="QK-WRONG-SHORTCODE", shortcode="999999"),
        )
    assert response.status_code == 200
    with app.app_context():
        transaction = MpesaCallbackTransaction.query.filter_by(
            provider_transaction_id="QK-WRONG-SHORTCODE"
        ).one()
        assert transaction.processing_status == "exception"
        assert transaction.property_id == channel["property_id"]
        assert transaction.unit_id is None
        assert transaction.lease_id is None
        assert "does not match" in transaction.exception_reason


def test_unknown_unit_reference_is_retained_as_exception(app, channel):
    with app.test_client() as client:
        response = post_callback(
            client,
            channel["configuration_id"],
            callback_payload(transaction_id="QK-UNKNOWN-UNIT", reference="NO-SUCH-UNIT"),
        )
    assert response.status_code == 200
    with app.app_context():
        transaction = MpesaCallbackTransaction.query.filter_by(
            provider_transaction_id="QK-UNKNOWN-UNIT"
        ).one()
        assert transaction.processing_status == "exception"
        assert transaction.unit_id is None
        assert transaction.lease_id is None
        assert "does not match a unit" in transaction.exception_reason


def test_malformed_callback_is_persisted_without_financial_posting(app, channel):
    with app.app_context():
        payment_count = Payment.query.count()
        receipt_count = Receipt.query.count()
        allocation_count = PaymentAllocation.query.count()

    with app.test_client() as client:
        response = post_callback(
            client,
            channel["configuration_id"],
            {"TransID": "QK-MALFORMED", "TransAmount": "invalid"},
        )
    assert response.status_code == 200
    with app.app_context():
        transaction = MpesaCallbackTransaction.query.filter_by(
            provider_transaction_id="QK-MALFORMED"
        ).one()
        assert transaction.processing_status == "exception"
        assert transaction.amount is None
        assert transaction.exception_reason
        assert Payment.query.count() == payment_count
        assert Receipt.query.count() == receipt_count
        assert PaymentAllocation.query.count() == allocation_count


def test_callback_does_not_change_invoice_or_create_financial_records(
    app, channel, cleanup_records
):
    with app.app_context():
        invoice = Invoice(
            lease_id=channel["lease_id"],
            period_start=date(2026, 11, 1),
            period_end=date(2026, 11, 30),
            due_date=date(2026, 11, 5),
            purpose="rent",
            status="issued",
        )
        db.session.add(invoice)
        db.session.flush()
        charge = Charge(
            invoice_id=invoice.id,
            category="rent",
            description="Monthly rent",
            amount="15000.00",
        )
        db.session.add(charge)
        db.session.commit()
        invoice_id = invoice.id
        cleanup_records["invoices"].add(invoice_id)
        original_status = invoice.status
        original_charge_amount = charge.amount
        original_counts = (
            Payment.query.filter_by(tenant_id=channel["tenant_id"]).count(),
            Receipt.query.join(Payment).filter(
                Payment.tenant_id == channel["tenant_id"]
            ).count(),
            PaymentAllocation.query.join(Payment).filter(
                Payment.tenant_id == channel["tenant_id"]
            ).count(),
        )

    with app.test_client() as client:
        response = post_callback(
            client,
            channel["configuration_id"],
            callback_payload(transaction_id="QK-NO-POSTING", amount="20000.00"),
        )
    assert response.status_code == 200
    with app.app_context():
        invoice = db.session.get(Invoice, invoice_id)
        charge = Charge.query.filter_by(invoice_id=invoice_id).one()
        assert invoice.status == original_status
        assert charge.amount == original_charge_amount
        assert (
            Payment.query.filter_by(tenant_id=channel["tenant_id"]).count(),
            Receipt.query.join(Payment).filter(
                Payment.tenant_id == channel["tenant_id"]
            ).count(),
            PaymentAllocation.query.join(Payment).filter(
                Payment.tenant_id == channel["tenant_id"]
            ).count(),
        ) == original_counts


def test_exact_duplicate_callback_is_idempotent(app, channel):
    payload = callback_payload(transaction_id="QK-DUPLICATE")
    with app.test_client() as client:
        first = post_callback(
            client,
            channel["configuration_id"],
            payload,
        )
        second = post_callback(
            client,
            channel["configuration_id"],
            payload,
        )
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.get_json()["ResultCode"] == 0
    with app.app_context():
        transactions = MpesaCallbackTransaction.query.filter_by(
            provider_transaction_id="QK-DUPLICATE"
        ).all()
        assert len(transactions) == 1
        assert transactions[0].processing_status == "matched"
        assert transactions[0].account_reference == "A1"
        assert transactions[0].amount == Decimal("15000.00")


@pytest.mark.parametrize(
    "changed_field,changed_value",
    [
        ("amount", "1.00"),
        ("reference", "OTHER"),
        ("shortcode", "600999"),
        ("transaction_time", "20261106123100"),
        ("currency", "USD"),
    ],
)
def test_conflicting_duplicate_callback_is_rejected_without_overwriting_original(
    app, channel, changed_field, changed_value
):
    original_payload = callback_payload(transaction_id="QK-CONFLICT")
    changed_payload = callback_payload(
        transaction_id="QK-CONFLICT",
        **{changed_field: changed_value},
    )
    with app.test_client() as client:
        first = post_callback(
            client, channel["configuration_id"], original_payload
        )
        conflict = post_callback(
            client, channel["configuration_id"], changed_payload
        )
    assert first.status_code == 200
    assert conflict.status_code == 200
    assert conflict.get_json() == {
        "ResultCode": 1,
        "ResultDesc": "Conflicting duplicate transaction",
    }

    with app.app_context():
        transactions = MpesaCallbackTransaction.query.filter_by(
            provider_transaction_id="QK-CONFLICT"
        ).all()
        assert len(transactions) == 1
        transaction = transactions[0]
        assert transaction.business_shortcode == "600111"
        assert transaction.account_reference == "A1"
        assert transaction.amount == Decimal("15000.00")
        assert transaction.provider_transaction_at.strftime(
            "%Y%m%d%H%M%S"
        ) == "20261106123000"
        assert transaction.currency == "KES"


def test_concurrent_duplicate_callbacks_create_one_inbox_row(app, channel):
    barrier = Barrier(2)
    url = (
        f"/api/integrations/daraja/c2b/"
        f"{channel['configuration_id']}/confirmation"
    )
    payload = callback_payload(transaction_id="QK-CONCURRENT")

    def deliver():
        barrier.wait(timeout=10)
        with app.test_client() as client:
            return client.post(url, json=payload).status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda _: deliver(), range(2)))
    assert responses == [200, 200]
    with app.app_context():
        assert MpesaCallbackTransaction.query.filter_by(
            provider_transaction_id="QK-CONCURRENT"
        ).count() == 1


def test_malformed_json_is_retained_as_an_exception(app, channel):
    with app.test_client() as client:
        response = client.post(
            f"/api/integrations/daraja/c2b/"
            f"{channel['configuration_id']}/confirmation",
            data="{",
            content_type="application/json",
        )
    assert response.status_code == 200
    with app.app_context():
        transaction = MpesaCallbackTransaction.query.filter_by(
            paybill_configuration_id=channel["configuration_id"],
            provider_transaction_id=None,
        ).one()
        assert transaction.processing_status == "exception"
        assert "JSON object" in transaction.exception_reason


@pytest.mark.parametrize(
    "transaction_id",
    [
        pytest.param(None, id="missing"),
        pytest.param("", id="blank"),
        pytest.param(True, id="wrong-type"),
        pytest.param("T" * 101, id="overlength"),
    ],
)
def test_repeated_callbacks_without_valid_transaction_ids_remain_exceptions(
    app, channel, transaction_id
):
    payload = callback_payload(transaction_id=transaction_id)
    with app.test_client() as client:
        first = post_callback(client, channel["configuration_id"], payload)
        second = post_callback(client, channel["configuration_id"], payload)

    assert first.status_code == 200
    assert second.status_code == 200
    with app.app_context():
        transactions = MpesaCallbackTransaction.query.filter_by(
            paybill_configuration_id=channel["configuration_id"],
            provider_transaction_id=None,
        ).all()
        assert len(transactions) == 2
        assert all(
            transaction.processing_status == "exception"
            and transaction.unit_id is None
            and transaction.lease_id is None
            for transaction in transactions
        )


def test_inactive_paybill_configuration_validation_is_rejected(app, channel):
    with app.app_context():
        configuration = db.session.get(
            PropertyPayBillConfiguration, channel["configuration_id"]
        )
        configuration.is_active = False
        db.session.commit()

    with app.test_client() as client:
        response = client.post(
            f"/api/integrations/daraja/c2b/"
            f"{channel['configuration_id']}/validation",
            json={},
        )

    assert response.status_code == 200
    assert response.get_json() == {
        "ResultCode": 1,
        "ResultDesc": "Inactive configuration",
    }
