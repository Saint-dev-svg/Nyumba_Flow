from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import jwt_required
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from authorization import get_current_landlord_id
from extensions import db
from mpesa_registration import (
    DarajaRegistrationAuthenticationError,
    DarajaRegistrationConfigurationError,
    DarajaRegistrationRequestError,
    DarajaRegistrationResponseError,
    DarajaRegistrationTimeoutError,
    register_c2b_urls,
)
from models import (
    Lease,
    MpesaCallbackTransaction,
    Property,
    PropertyPayBillConfiguration,
    Unit,
)


mpesa_bp = Blueprint("mpesa", __name__)
MAX_AMOUNT = Decimal("9999999999.99")
KENYA_TIMEZONE = timezone(timedelta(hours=3))


def _owned_property(property_id, landlord_id, *, lock=False):
    query = Property.query.filter_by(id=property_id, owner_id=landlord_id)
    if lock:
        query = query.with_for_update()
    return query.first()


def _configuration_dict(configuration):
    return {
        "id": configuration.id,
        "property_id": configuration.property_id,
        "business_shortcode": configuration.business_shortcode,
        "account_reference_type": configuration.account_reference_type,
        "is_active": configuration.is_active,
        "created_at": configuration.created_at.isoformat(),
        "updated_at": configuration.updated_at.isoformat(),
        "confirmation_callback_path": (
            f"/api/integrations/daraja/c2b/"
            f"{configuration.id}/confirmation"
        ),
        "validation_callback_path": (
            f"/api/integrations/daraja/c2b/"
            f"{configuration.id}/validation"
        ),
    }


def _transaction_dict(transaction):
    return {
        "id": transaction.id,
        "provider": transaction.provider,
        "provider_transaction_id": transaction.provider_transaction_id,
        "business_shortcode": transaction.business_shortcode,
        "account_reference": transaction.account_reference,
        "amount": (
            str(transaction.amount) if transaction.amount is not None else None
        ),
        "currency": transaction.currency,
        "provider_transaction_at": (
            transaction.provider_transaction_at.isoformat()
            if transaction.provider_transaction_at
            else None
        ),
        "processing_status": transaction.processing_status,
        "verification_status": "unverified",
        "property_id": transaction.property_id,
        "property_name": (
            transaction.property.name if transaction.property else None
        ),
        "unit_id": transaction.unit_id,
        "unit_number": (
            transaction.unit.unit_number if transaction.unit else None
        ),
        "lease_id": transaction.lease_id,
        "exception_reason": transaction.exception_reason,
        "metadata": transaction.provider_metadata,
        "received_at": transaction.received_at.isoformat(),
        "updated_at": transaction.updated_at.isoformat(),
        "processed_at": (
            transaction.processed_at.isoformat()
            if transaction.processed_at
            else None
        ),
    }


def _provider_text(value, field, max_length, errors, *, numeric_only=False):
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        errors.append(f"{field} is missing or invalid.")
        return None
    result = str(value).strip()
    if not result:
        errors.append(f"{field} is missing or invalid.")
        return None
    if len(result) > max_length:
        errors.append(f"{field} exceeds the supported length.")
        return None
    if numeric_only and not all("0" <= character <= "9" for character in result):
        errors.append(f"{field} must contain digits only.")
    return result


def _provider_amount(value, errors):
    if isinstance(value, bool) or value is None:
        errors.append("Transaction amount is missing or invalid.")
        return None
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        errors.append("Transaction amount is missing or invalid.")
        return None
    if not amount.is_finite() or amount <= 0 or amount > MAX_AMOUNT:
        errors.append("Transaction amount is outside the supported range.")
        return None
    try:
        amount_with_two_decimals = amount.quantize(Decimal("0.01"))
    except InvalidOperation:
        errors.append("Transaction amount has unsupported precision.")
        return None
    if amount != amount_with_two_decimals:
        errors.append("Transaction amount has more than two decimal places.")
        return None
    return amount


def _provider_timestamp(value, errors):
    if isinstance(value, int) and not isinstance(value, bool):
        value = str(value)
    if (
        not isinstance(value, str)
        or len(value) != 14
        or not all("0" <= character <= "9" for character in value)
    ):
        errors.append("Transaction timestamp is missing or invalid.")
        return None
    try:
        return datetime.strptime(value, "%Y%m%d%H%M%S").replace(
            tzinfo=KENYA_TIMEZONE
        )
    except ValueError:
        errors.append("Transaction timestamp is missing or invalid.")
        return None


def _callback_metadata(payload):
    if not isinstance(payload, dict):
        return None
    allowed_fields = ("TransactionType", "InvoiceNumber", "ThirdPartyTransID")
    values = {}
    for field in allowed_fields:
        value = payload.get(field)
        if isinstance(value, (str, int)) and not isinstance(value, bool):
            text_value = str(value).strip()
            if text_value:
                values[field] = text_value[:100]
    return values or None


def _callback_payload():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return None
    body = payload.get("Body")
    if isinstance(body, dict):
        stk_callback = body.get("stkCallback")
        if isinstance(stk_callback, dict):
            return None
        c2b = body.get("C2BPaymentConfirmation")
        if isinstance(c2b, dict):
            return c2b
    return payload


def _persist_callback(configuration, payload):
    errors = []
    if not isinstance(payload, dict):
        payload = {}
        errors.append("Callback body must be a JSON object.")

    transaction_id = _provider_text(
        payload.get("TransID"), "Provider transaction ID", 100, errors
    )
    shortcode = _provider_text(
        payload.get("BusinessShortCode"),
        "Receiving PayBill",
        20,
        errors,
        numeric_only=True,
    )
    reference = _provider_text(
        payload.get("BillRefNumber"), "Account reference", 100, errors
    )
    amount = _provider_amount(payload.get("TransAmount"), errors)
    provider_timestamp = _provider_timestamp(payload.get("TransTime"), errors)

    currency_value = payload.get("Currency", "KES")
    currency = None
    if isinstance(currency_value, str):
        normalized_currency = currency_value.strip().upper()
        if len(normalized_currency) == 3:
            currency = normalized_currency
        else:
            errors.append("Currency is missing or invalid.")
    else:
        errors.append("Currency is missing or invalid.")
    if currency is not None and currency != "KES":
        errors.append("Only KES transactions are supported.")

    property_obj = configuration.property
    unit = None
    lease = None
    if not configuration.is_active:
        errors.append("The receiving PayBill configuration is inactive.")
    if shortcode is not None and shortcode != configuration.business_shortcode:
        errors.append("Callback PayBill does not match this configured channel.")

    if (
        shortcode == configuration.business_shortcode
        and reference
        and reference.strip()
        and len(reference) <= 100
    ):
        unit = Unit.query.filter_by(
            property_id=configuration.property_id,
            unit_number=reference,
        ).first()
        if unit is None:
            errors.append("Account reference does not match a unit in this property.")
        elif not unit.is_active:
            errors.append("The referenced unit is inactive.")
        else:
            active_leases = Lease.query.filter_by(
                unit_id=unit.id,
                is_active=True,
            ).all()
            if len(active_leases) == 1:
                lease = active_leases[0]
            elif not active_leases:
                errors.append("No active lease exists for the referenced unit.")
            else:
                errors.append("Multiple active leases exist for the referenced unit.")

    transaction = MpesaCallbackTransaction(
        paybill_configuration_id=configuration.id,
        provider="safaricom",
        provider_transaction_id=transaction_id,
        business_shortcode=shortcode,
        account_reference=reference,
        amount=amount,
        currency=currency,
        provider_transaction_at=provider_timestamp,
        provider_metadata=_callback_metadata(payload),
        processing_status="exception",
        property_id=property_obj.id,
        unit_id=unit.id if unit else None,
        lease_id=lease.id if lease else None,
        exception_reason=" ".join(dict.fromkeys(errors)) or None,
    )
    if not errors:
        transaction.processing_status = "matched"

    db.session.add(transaction)
    try:
        db.session.commit()
        return transaction, False
    except IntegrityError:
        db.session.rollback()
        if transaction_id:
            existing = MpesaCallbackTransaction.query.filter_by(
                provider="safaricom",
                provider_transaction_id=transaction_id,
            ).first()
            if existing is not None:
                return existing, True
        raise


@mpesa_bp.get("/api/properties/<int:property_id>/mpesa-paybill")
@jwt_required()
def get_paybill_configuration(property_id):
    landlord_id = get_current_landlord_id()
    if landlord_id is None:
        return jsonify({"error": "An authenticated landlord account is required."}), 403
    if _owned_property(property_id, landlord_id) is None:
        return jsonify({"error": "Property not found."}), 404

    configurations = (
        PropertyPayBillConfiguration.query
        .filter_by(property_id=property_id)
        .order_by(PropertyPayBillConfiguration.created_at.desc())
        .all()
    )
    return jsonify({
        "configurations": [
            _configuration_dict(configuration)
            for configuration in configurations
        ],
    }), 200


@mpesa_bp.post("/api/properties/<int:property_id>/mpesa-paybill")
@jwt_required()
def create_paybill_configuration(property_id):
    landlord_id = get_current_landlord_id()
    if landlord_id is None:
        return jsonify({"error": "An authenticated landlord account is required."}), 403
    property_obj = _owned_property(property_id, landlord_id, lock=True)
    if property_obj is None:
        return jsonify({"error": "Property not found."}), 404

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be valid JSON."}), 400
    shortcode = data.get("business_shortcode")
    if not isinstance(shortcode, str):
        return jsonify({"error": "PayBill number must be a string."}), 400
    shortcode = shortcode.strip()
    if (
        not shortcode
        or len(shortcode) > 20
        or not all("0" <= character <= "9" for character in shortcode)
    ):
        return jsonify({
            "error": "PayBill number must contain 1 to 20 digits."
        }), 400

    existing = PropertyPayBillConfiguration.query.filter_by(
        business_shortcode=shortcode
    ).first()
    if existing is not None:
        if existing.property_id == property_id:
            return jsonify({
                "error": "This PayBill is already in this property's configuration history."
            }), 409
        return jsonify({
            "error": "This PayBill is already associated with another property."
        }), 409

    PropertyPayBillConfiguration.query.filter_by(
        property_id=property_id,
        is_active=True,
    ).update({"is_active": False}, synchronize_session=False)
    configuration = PropertyPayBillConfiguration(
        property_id=property_id,
        business_shortcode=shortcode,
        account_reference_type="unit_number",
        is_active=True,
    )
    db.session.add(configuration)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({
            "error": "The PayBill configuration conflicts with an existing channel."
        }), 409

    return jsonify({
        "configuration": _configuration_dict(configuration),
    }), 201


@mpesa_bp.patch(
    "/api/properties/<int:property_id>/mpesa-paybill/<int:configuration_id>"
)
@jwt_required()
def update_paybill_configuration(property_id, configuration_id):
    landlord_id = get_current_landlord_id()
    if landlord_id is None:
        return jsonify({"error": "An authenticated landlord account is required."}), 403
    property_obj = _owned_property(property_id, landlord_id, lock=True)
    if property_obj is None:
        return jsonify({"error": "Property not found."}), 404

    configuration = PropertyPayBillConfiguration.query.filter_by(
        id=configuration_id,
        property_id=property_id,
    ).first()
    if configuration is None:
        return jsonify({"error": "PayBill configuration not found."}), 404
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get("is_active"), bool):
        return jsonify({"error": "is_active must be a boolean."}), 400

    if data["is_active"]:
        PropertyPayBillConfiguration.query.filter(
            PropertyPayBillConfiguration.property_id == property_id,
            PropertyPayBillConfiguration.id != configuration_id,
            PropertyPayBillConfiguration.is_active.is_(True),
        ).update({"is_active": False}, synchronize_session=False)
    configuration.is_active = data["is_active"]
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "Unable to update this PayBill configuration."}), 409

    return jsonify({
        "configuration": _configuration_dict(configuration),
    }), 200


@mpesa_bp.post(
    "/api/properties/<int:property_id>/mpesa-paybill/"
    "<int:configuration_id>/register-url"
)
@jwt_required()
def register_paybill_urls(property_id, configuration_id):
    landlord_id = get_current_landlord_id()
    if landlord_id is None:
        return jsonify({"error": "An authenticated landlord account is required."}), 403

    configuration = (
        PropertyPayBillConfiguration.query
        .join(Property)
        .filter(
            PropertyPayBillConfiguration.id == configuration_id,
            PropertyPayBillConfiguration.property_id == property_id,
            Property.owner_id == landlord_id,
        )
        .first()
    )
    if configuration is None:
        return jsonify({"error": "PayBill configuration not found."}), 404
    if not configuration.is_active:
        return jsonify({"error": "Inactive PayBill configurations cannot be registered."}), 409

    try:
        result = register_c2b_urls(configuration)
    except DarajaRegistrationConfigurationError as error:
        return jsonify({"success": False, "error": str(error)}), 400
    except DarajaRegistrationAuthenticationError as error:
        return jsonify({"success": False, "error": str(error)}), 502
    except DarajaRegistrationTimeoutError as error:
        return jsonify({"success": False, "error": str(error)}), 504
    except DarajaRegistrationRequestError as error:
        return jsonify({
            "success": False,
            "error": str(error),
            "provider_http_status": error.provider_http_status,
            "provider_error_code": error.provider_error_code,
            "provider_message": error.provider_message,
        }), 502
    except DarajaRegistrationResponseError as error:
        return jsonify({"success": False, "error": str(error)}), 502

    return jsonify(result), 200 if result["success"] else 502


@mpesa_bp.post(
    "/api/integrations/daraja/c2b/<int:configuration_id>/validation"
)
def daraja_c2b_validation(configuration_id):
    configuration = db.session.get(
        PropertyPayBillConfiguration, configuration_id
    )
    if configuration is None:
        return jsonify({"ResultCode": 1, "ResultDesc": "Unknown configuration"}), 404
    # Validation does not verify a payment or post financial records.
    return jsonify({"ResultCode": 0, "ResultDesc": "Accepted"}), 200


@mpesa_bp.post(
    "/api/integrations/daraja/c2b/<int:configuration_id>/confirmation"
)
def daraja_c2b_confirmation(configuration_id):
    configuration = db.session.get(
        PropertyPayBillConfiguration, configuration_id
    )
    if configuration is None:
        return jsonify({"ResultCode": 1, "ResultDesc": "Unknown configuration"}), 404

    payload = _callback_payload()
    try:
        _persist_callback(configuration, payload)
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.error("Unable to persist a Daraja callback inbox entry.")
        return jsonify({
            "ResultCode": 1,
            "ResultDesc": "Temporary processing error",
        }), 500

    return jsonify({"ResultCode": 0, "ResultDesc": "Accepted"}), 200


@mpesa_bp.get("/api/mpesa/transactions")
@jwt_required()
def list_mpesa_transactions():
    landlord_id = get_current_landlord_id()
    if landlord_id is None:
        return jsonify({"error": "An authenticated landlord account is required."}), 403

    query = (
        MpesaCallbackTransaction.query
        .join(
            PropertyPayBillConfiguration,
            MpesaCallbackTransaction.paybill_configuration_id
            == PropertyPayBillConfiguration.id,
        )
        .filter(PropertyPayBillConfiguration.property.has(owner_id=landlord_id))
    )
    status = request.args.get("status")
    if status:
        if status not in {"received", "matched", "exception", "processed"}:
            return jsonify({"error": "Unsupported transaction status."}), 400
        query = query.filter_by(processing_status=status)

    transactions = (
        query
        .order_by(
            MpesaCallbackTransaction.received_at.desc(),
            MpesaCallbackTransaction.id.desc(),
        )
        .limit(200)
        .all()
    )
    return jsonify({
        "transactions": [
            _transaction_dict(transaction)
            for transaction in transactions
        ],
        "count": len(transactions),
    }), 200


@mpesa_bp.get("/api/mpesa/transactions/<int:transaction_id>")
@jwt_required()
def get_mpesa_transaction(transaction_id):
    landlord_id = get_current_landlord_id()
    if landlord_id is None:
        return jsonify({"error": "An authenticated landlord account is required."}), 403
    transaction = (
        MpesaCallbackTransaction.query
        .join(
            PropertyPayBillConfiguration,
            MpesaCallbackTransaction.paybill_configuration_id
            == PropertyPayBillConfiguration.id,
        )
        .filter(
            MpesaCallbackTransaction.id == transaction_id,
            PropertyPayBillConfiguration.property.has(owner_id=landlord_id),
        )
        .first()
    )
    if transaction is None:
        return jsonify({"error": "M-Pesa transaction not found."}), 404
    return jsonify({"transaction": _transaction_dict(transaction)}), 200
