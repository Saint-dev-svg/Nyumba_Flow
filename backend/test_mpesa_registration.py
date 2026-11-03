import json
import uuid
from io import BytesIO
from urllib.error import HTTPError, URLError

import pytest
from flask_jwt_extended import create_access_token

import mpesa_oauth
import mpesa_registration
from extensions import db
from models import Property, PropertyPayBillConfiguration, User
from test_config import create_test_app


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return exc_type is None and exc_value is None and traceback is None

    def read(self, size=-1):
        return self.body[:size]


@pytest.fixture
def app():
    return create_test_app()


@pytest.fixture
def registration_setup(app):
    with app.app_context():
        landlord = User(
            full_name="Daraja Registration Landlord",
            email=f"daraja.landlord.{uuid.uuid4().hex}@example.com",
            role="landlord",
        )
        landlord.set_password("SecureDarajaPassword123!")
        manager = User(
            full_name="Daraja Registration Manager",
            email=f"daraja.manager.{uuid.uuid4().hex}@example.com",
            role="manager",
        )
        manager.set_password("SecureDarajaPassword123!")
        other_landlord = User(
            full_name="Other Daraja Landlord",
            email=f"daraja.other.{uuid.uuid4().hex}@example.com",
            role="landlord",
        )
        other_landlord.set_password("SecureDarajaPassword123!")
        db.session.add_all([landlord, manager, other_landlord])
        db.session.flush()

        property_obj = Property(
            owner_id=landlord.id,
            name=f"Daraja Property {uuid.uuid4().hex}",
            address="Nairobi, Kenya",
        )
        other_property = Property(
            owner_id=other_landlord.id,
            name=f"Other Daraja Property {uuid.uuid4().hex}",
            address="Nairobi, Kenya",
        )
        db.session.add_all([property_obj, other_property])
        db.session.flush()

        configuration = PropertyPayBillConfiguration(
            property_id=property_obj.id,
            business_shortcode=f"{uuid.uuid4().int % 10**12:012d}",
            account_reference_type="unit_number",
            is_active=True,
        )
        other_configuration = PropertyPayBillConfiguration(
            property_id=other_property.id,
            business_shortcode=f"{uuid.uuid4().int % 10**12:012d}",
            account_reference_type="unit_number",
            is_active=True,
        )
        db.session.add_all([configuration, other_configuration])
        db.session.commit()

        data = {
            "landlord_id": landlord.id,
            "manager_id": manager.id,
            "other_landlord_id": other_landlord.id,
            "property_id": property_obj.id,
            "configuration_id": configuration.id,
            "other_property_id": other_property.id,
            "other_configuration_id": other_configuration.id,
            "shortcode": configuration.business_shortcode,
            "landlord_headers": {
                "Authorization": f"Bearer {create_access_token(str(landlord.id))}"
            },
            "manager_headers": {
                "Authorization": f"Bearer {create_access_token(str(manager.id))}"
            },
            "other_landlord_headers": {
                "Authorization": (
                    f"Bearer {create_access_token(str(other_landlord.id))}"
                )
            },
        }

    yield data

    with app.app_context():
        PropertyPayBillConfiguration.query.filter(
            PropertyPayBillConfiguration.id.in_(
                [data["configuration_id"], data["other_configuration_id"]]
            )
        ).delete(synchronize_session=False)
        Property.query.filter(
            Property.id.in_([data["property_id"], data["other_property_id"]])
        ).delete(synchronize_session=False)
        User.query.filter(
            User.id.in_(
                [
                    data["landlord_id"],
                    data["manager_id"],
                    data["other_landlord_id"],
                ]
            )
        ).delete(synchronize_session=False)
        db.session.commit()


def registration_path(setup):
    return (
        f"/api/properties/{setup['property_id']}/mpesa-paybill/"
        f"{setup['configuration_id']}/register-url"
    )


def set_sandbox(monkeypatch):
    monkeypatch.setenv("MPESA_ENVIRONMENT", "sandbox")
    monkeypatch.setenv(
        "MPESA_CALLBACK_BASE_URL", "https://nyumbaflow.example.test"
    )


def mock_oauth(monkeypatch):
    monkeypatch.setattr(
        mpesa_registration,
        "get_access_token",
        lambda: "mocked-access-token",
    )


def test_success_registers_exact_sandbox_request(monkeypatch, app, registration_setup):
    set_sandbox(monkeypatch)
    mock_oauth(monkeypatch)
    calls = []

    def fake_urlopen(request, timeout):
        calls.append((request, timeout))
        return FakeResponse(json.dumps({
            "ConversationID": "mock-conversation-id",
            "OriginatorCoversationID": "mock-originator-id",
            "ResponseDescription": "successfully queued request",
        }).encode("utf-8"))

    monkeypatch.setattr(mpesa_registration, "urlopen", fake_urlopen)
    with app.test_client() as client:
        response = client.post(
            registration_path(registration_setup),
            headers=registration_setup["landlord_headers"],
        )

    assert response.status_code == 200
    result = response.get_json()
    assert result["success"] is True
    assert result["environment"] == "sandbox"
    assert result["business_shortcode"] == registration_setup["shortcode"]
    assert len(calls) == 1
    request, timeout = calls[0]
    assert request.full_url == mpesa_registration.SANDBOX_REGISTER_URL
    assert request.get_method() == "POST"
    assert request.get_header("Authorization") == "Bearer mocked-access-token"
    assert request.get_header("Content-type") == "application/json"
    assert request.get_header("Accept") == "application/json"
    assert timeout == mpesa_registration.REQUEST_TIMEOUT_SECONDS
    assert json.loads(request.data.decode("utf-8")) == {
        "ShortCode": registration_setup["shortcode"],
        "ResponseType": "Completed",
        "ValidationURL": (
            "https://nyumbaflow.example.test/api/integrations/daraja/c2b/"
            f"{registration_setup['configuration_id']}/validation"
        ),
        "ConfirmationURL": (
            "https://nyumbaflow.example.test/api/integrations/daraja/c2b/"
            f"{registration_setup['configuration_id']}/confirmation"
        ),
    }


@pytest.mark.parametrize(
    "term",
    ["M-PESA", "mpesa", "Safaricom", "exe", "exec", "cmd", "sql", "query"],
)
@pytest.mark.parametrize("location", ["hostname", "base_path"])
def test_restricted_callback_keyword_is_rejected_without_request(
    monkeypatch, app, registration_setup, term, location
):
    set_sandbox(monkeypatch)
    if location == "hostname":
        base_url = f"https://{term}.example.test"
    else:
        base_url = f"https://example.test/{term}/gateway"
    monkeypatch.setenv("MPESA_CALLBACK_BASE_URL", base_url)
    mock_oauth(monkeypatch)
    request_sent = False

    def fake_urlopen(request, timeout):
        nonlocal request_sent
        request_sent = True
        raise AssertionError("Rejected callback URLs must not send HTTP.")

    monkeypatch.setattr(mpesa_registration, "urlopen", fake_urlopen)
    with app.test_client() as client:
        response = client.post(
            registration_path(registration_setup),
            headers=registration_setup["landlord_headers"],
        )

    assert response.status_code == 400
    assert response.get_json()["error"] == (
        "A callback URL contains a restricted keyword."
    )
    assert not request_sent


@pytest.mark.parametrize(
    "term",
    ["M-pEsA", "MpEsA", "sAfArIcOm", "eXe", "ExEc", "CmD", "sQl", "QuErY"],
)
def test_restricted_callback_keyword_matching_is_case_insensitive(
    monkeypatch, app, registration_setup, term
):
    set_sandbox(monkeypatch)
    monkeypatch.setenv(
        "MPESA_CALLBACK_BASE_URL", f"https://example.test/gateway/{term}"
    )
    mock_oauth(monkeypatch)
    request_sent = False

    def fake_urlopen(request, timeout):
        nonlocal request_sent
        request_sent = True
        raise AssertionError("Rejected callback URLs must not send HTTP.")

    monkeypatch.setattr(mpesa_registration, "urlopen", fake_urlopen)
    with app.test_client() as client:
        response = client.post(
            registration_path(registration_setup),
            headers=registration_setup["landlord_headers"],
        )

    assert response.status_code == 400
    assert not request_sent


@pytest.mark.parametrize("restricted_callback", ["validation", "confirmation"])
def test_each_generated_callback_url_is_checked(
    monkeypatch, app, registration_setup, restricted_callback
):
    set_sandbox(monkeypatch)
    mock_oauth(monkeypatch)
    callback_urls = {
        "validation": "https://example.test/api/c2b/validation",
        "confirmation": "https://example.test/api/c2b/confirmation",
    }
    callback_urls[restricted_callback] = (
        f"https://example.test/api/{'M-PESA'}/"
        f"{restricted_callback}"
    )
    monkeypatch.setattr(
        mpesa_registration,
        "_callback_urls",
        lambda configuration_id: (
            callback_urls["validation"],
            callback_urls["confirmation"],
        ),
    )
    request_sent = False

    def fake_urlopen(request, timeout):
        nonlocal request_sent
        request_sent = True
        raise AssertionError("Rejected callback URLs must not send HTTP.")

    monkeypatch.setattr(mpesa_registration, "urlopen", fake_urlopen)
    with app.test_client() as client:
        response = client.post(
            registration_path(registration_setup),
            headers=registration_setup["landlord_headers"],
        )

    assert response.status_code == 400
    assert not request_sent


def test_oauth_failure_is_sanitized(monkeypatch, app, registration_setup):
    set_sandbox(monkeypatch)
    monkeypatch.setattr(
        mpesa_registration,
        "get_access_token",
        lambda: (_ for _ in ()).throw(
            mpesa_oauth.DarajaAuthenticationError("rejected credentials")
        ),
    )
    with app.test_client() as client:
        response = client.post(
            registration_path(registration_setup),
            headers=registration_setup["landlord_headers"],
        )
    assert response.status_code == 502
    assert response.get_json()["success"] is False
    assert "rejected credentials" not in response.get_data(as_text=True)
    assert "access_token" not in response.get_data(as_text=True)


@pytest.mark.parametrize("status_code", [400, 401, 403, 500])
def test_provider_http_error_includes_sanitized_details(
    monkeypatch, app, registration_setup, status_code
):
    set_sandbox(monkeypatch)
    mock_oauth(monkeypatch)

    def fake_urlopen(request, timeout):
        body = json.dumps({
            "errorCode": "REGISTRATION_FAILED",
            "errorMessage": "The registration request was rejected.",
            "requestId": "request-123456",
        }).encode("utf-8")
        raise HTTPError(
            request.full_url,
            status_code,
            "Provider error",
            {},
            BytesIO(body),
        )

    monkeypatch.setattr(mpesa_registration, "urlopen", fake_urlopen)
    with app.test_client() as client:
        response = client.post(
            registration_path(registration_setup),
            headers=registration_setup["landlord_headers"],
        )
    assert response.status_code == 502
    result = response.get_json()
    assert result["success"] is False
    assert result["error"] == (
        f"Safaricom returned HTTP {status_code} during URL registration."
    )
    assert result["provider_http_status"] == status_code
    assert result["provider_error_code"] == "REGISTRATION_FAILED"
    assert result["provider_message"] == "The registration request was rejected."
    assert result["provider_request_id"] == "request-123456"


@pytest.mark.parametrize("body", [b"not-json", b"", b"[]", b'{"detail":"internal"}'])
def test_provider_http_error_with_unusable_body_falls_back_to_generic_error(
    monkeypatch, app, registration_setup, body
):
    set_sandbox(monkeypatch)
    mock_oauth(monkeypatch)

    def fake_urlopen(request, timeout):
        raise HTTPError(
            request.full_url,
            500,
            "Provider error",
            {},
            BytesIO(body),
        )

    monkeypatch.setattr(mpesa_registration, "urlopen", fake_urlopen)
    with app.test_client() as client:
        response = client.post(
            registration_path(registration_setup),
            headers=registration_setup["landlord_headers"],
        )

    result = response.get_json()
    assert response.status_code == 502
    assert result["error"] == "Safaricom returned HTTP 500 during URL registration."
    assert result["provider_http_status"] == 500
    assert result["provider_error_code"] is None
    assert result["provider_message"] is None
    assert result["provider_request_id"] is None


def test_provider_http_error_redacts_sensitive_values(
    monkeypatch, app, registration_setup
):
    set_sandbox(monkeypatch)
    token = "test-oauth-token-do-not-return"
    consumer_key = "test-consumer-key-do-not-return"
    consumer_secret = "test-consumer-secret-do-not-return"
    monkeypatch.setenv("MPESA_CONSUMER_KEY", consumer_key)
    monkeypatch.setenv("MPESA_CONSUMER_SECRET", consumer_secret)
    monkeypatch.setattr(
        mpesa_registration, "get_access_token", lambda: token
    )
    message = (
        f"Rejected {consumer_key} {consumer_secret} {token} "
        f"{registration_setup['shortcode']} Bearer {token}"
    )

    def fake_urlopen(request, timeout):
        body = json.dumps({
            "errorCode": "REGISTRATION_FAILED",
            "errorMessage": message,
            "requestId": (
                f"request-{consumer_key}-{consumer_secret}-{token}-"
                f"{registration_setup['shortcode']}"
            ),
        }).encode("utf-8")
        raise HTTPError(
            request.full_url,
            500,
            "Provider error",
            {},
            BytesIO(body),
        )

    monkeypatch.setattr(mpesa_registration, "urlopen", fake_urlopen)
    with app.test_client() as client:
        response = client.post(
            registration_path(registration_setup),
            headers=registration_setup["landlord_headers"],
        )

    response_text = response.get_data(as_text=True)
    for sensitive_value in (
        consumer_key,
        consumer_secret,
        token,
        registration_setup["shortcode"],
        "Bearer ",
    ):
        assert sensitive_value not in response_text
    assert "[redacted]" in response.get_json()["provider_message"]
    request_id = response.get_json()["provider_request_id"]
    assert len(request_id) <= 128
    assert "[redacted]" in request_id


def test_provider_request_id_is_bounded(monkeypatch, app, registration_setup):
    set_sandbox(monkeypatch)
    mock_oauth(monkeypatch)

    def fake_urlopen(request, timeout):
        body = json.dumps({
            "requestId": "r" * 200,
        }).encode("utf-8")
        raise HTTPError(
            request.full_url,
            500,
            "Provider error",
            {},
            BytesIO(body),
        )

    monkeypatch.setattr(mpesa_registration, "urlopen", fake_urlopen)
    with app.test_client() as client:
        response = client.post(
            registration_path(registration_setup),
            headers=registration_setup["landlord_headers"],
        )

    assert response.status_code == 502
    assert response.get_json()["provider_request_id"] == "r" * 128


def test_provider_http_error_with_sensitive_fields_uses_generic_error(
    monkeypatch, app, registration_setup
):
    set_sandbox(monkeypatch)
    mock_oauth(monkeypatch)

    def fake_urlopen(request, timeout):
        body = json.dumps({
            "errorCode": "REGISTRATION_FAILED",
            "errorMessage": "Request failed.",
            "requestId": "request-123456",
            "consumerSecret": "must-not-be-returned",
            "access_token": "must-not-be-returned",
        }).encode("utf-8")
        raise HTTPError(
            request.full_url,
            500,
            "Provider error",
            {},
            BytesIO(body),
        )

    monkeypatch.setattr(mpesa_registration, "urlopen", fake_urlopen)
    with app.test_client() as client:
        response = client.post(
            registration_path(registration_setup),
            headers=registration_setup["landlord_headers"],
        )

    result = response.get_json()
    assert result["provider_error_code"] is None
    assert result["provider_message"] is None
    assert result["provider_request_id"] is None
    assert "must-not-be-returned" not in response.get_data(as_text=True)


def test_registration_timeout_is_reported(monkeypatch, app, registration_setup):
    set_sandbox(monkeypatch)
    mock_oauth(monkeypatch)
    monkeypatch.setattr(
        mpesa_registration,
        "urlopen",
        lambda request, timeout: (_ for _ in ()).throw(TimeoutError()),
    )
    with app.test_client() as client:
        response = client.post(
            registration_path(registration_setup),
            headers=registration_setup["landlord_headers"],
        )
    assert response.status_code == 504
    assert "timed out" in response.get_json()["error"]


def test_wrapped_network_timeout_is_reported(monkeypatch, app, registration_setup):
    set_sandbox(monkeypatch)
    mock_oauth(monkeypatch)
    monkeypatch.setattr(
        mpesa_registration,
        "urlopen",
        lambda request, timeout: (_ for _ in ()).throw(
            URLError(TimeoutError())
        ),
    )
    with app.test_client() as client:
        response = client.post(
            registration_path(registration_setup),
            headers=registration_setup["landlord_headers"],
        )
    assert response.status_code == 504
    assert "timed out" in response.get_json()["error"]


def test_network_failure_is_reported(monkeypatch, app, registration_setup):
    set_sandbox(monkeypatch)
    mock_oauth(monkeypatch)
    monkeypatch.setattr(
        mpesa_registration,
        "urlopen",
        lambda request, timeout: (_ for _ in ()).throw(
            URLError("network unavailable")
        ),
    )
    with app.test_client() as client:
        response = client.post(
            registration_path(registration_setup),
            headers=registration_setup["landlord_headers"],
        )
    assert response.status_code == 502
    assert "Unable to reach" in response.get_json()["error"]


@pytest.mark.parametrize("body", [b"not-json", b"[]", b"{}"])
def test_malformed_provider_response_is_rejected(
    monkeypatch, app, registration_setup, body
):
    set_sandbox(monkeypatch)
    mock_oauth(monkeypatch)
    monkeypatch.setattr(
        mpesa_registration,
        "urlopen",
        lambda request, timeout: FakeResponse(body),
    )
    with app.test_client() as client:
        response = client.post(
            registration_path(registration_setup),
            headers=registration_setup["landlord_headers"],
        )
    assert response.status_code == 502
    assert response.get_json()["success"] is False


def test_missing_callback_base_url_fails_before_network(
    monkeypatch, app, registration_setup
):
    monkeypatch.setenv("MPESA_ENVIRONMENT", "sandbox")
    monkeypatch.delenv("MPESA_CALLBACK_BASE_URL", raising=False)
    mock_oauth(monkeypatch)
    urlopen_called = False

    def fake_urlopen(request, timeout):
        nonlocal urlopen_called
        urlopen_called = True
        raise AssertionError("Invalid callback configuration must not send HTTP.")

    monkeypatch.setattr(mpesa_registration, "urlopen", fake_urlopen)
    with app.test_client() as client:
        response = client.post(
            registration_path(registration_setup),
            headers=registration_setup["landlord_headers"],
        )
    assert response.status_code == 400
    assert not urlopen_called


@pytest.mark.parametrize(
    "base_url",
    [
        "localhost:5000",
        "ftp://example.test",
        "https://user:password@example.test",
        "https://example.test?tenant=1",
        "https://example.test#fragment",
        "https://example.test:99999",
    ],
)
def test_invalid_callback_base_url_is_rejected(
    monkeypatch, app, registration_setup, base_url
):
    monkeypatch.setenv("MPESA_ENVIRONMENT", "sandbox")
    monkeypatch.setenv("MPESA_CALLBACK_BASE_URL", base_url)
    mock_oauth(monkeypatch)
    with app.test_client() as client:
        response = client.post(
            registration_path(registration_setup),
            headers=registration_setup["landlord_headers"],
        )
    assert response.status_code == 400
    assert "MPESA_CALLBACK_BASE_URL" in response.get_json()["error"]


@pytest.mark.parametrize("environment", ["production", ""])
def test_non_sandbox_environment_is_rejected(
    monkeypatch, app, registration_setup, environment
):
    monkeypatch.setenv("MPESA_ENVIRONMENT", environment)
    monkeypatch.setenv(
        "MPESA_CALLBACK_BASE_URL", "https://nyumbaflow.example.test"
    )
    mock_oauth(monkeypatch)
    request_sent = False

    def fake_urlopen(request, timeout):
        nonlocal request_sent
        request_sent = True
        raise AssertionError("Non-sandbox registration must not send HTTP.")

    monkeypatch.setattr(mpesa_registration, "urlopen", fake_urlopen)
    with app.test_client() as client:
        response = client.post(
            registration_path(registration_setup),
            headers=registration_setup["landlord_headers"],
        )
    assert response.status_code == 400
    assert "sandbox-only" in response.get_json()["error"]
    assert not request_sent


def test_unauthenticated_request_is_rejected(monkeypatch, app, registration_setup):
    set_sandbox(monkeypatch)
    urlopen_called = False

    def fake_urlopen(request, timeout):
        nonlocal urlopen_called
        urlopen_called = True
        raise AssertionError("Unauthenticated requests must not send HTTP.")

    monkeypatch.setattr(mpesa_registration, "urlopen", fake_urlopen)
    with app.test_client() as client:
        response = client.post(registration_path(registration_setup))
    assert response.status_code == 401
    assert not urlopen_called


def test_non_landlord_request_is_rejected(monkeypatch, app, registration_setup):
    set_sandbox(monkeypatch)
    urlopen_called = False

    def fake_urlopen(request, timeout):
        nonlocal urlopen_called
        urlopen_called = True
        raise AssertionError("Non-landlords must not send HTTP.")

    monkeypatch.setattr(mpesa_registration, "urlopen", fake_urlopen)
    with app.test_client() as client:
        response = client.post(
            registration_path(registration_setup),
            headers=registration_setup["manager_headers"],
        )
    assert response.status_code == 403
    assert not urlopen_called


def test_landlord_cannot_register_another_landlords_configuration(
    monkeypatch, app, registration_setup
):
    set_sandbox(monkeypatch)
    urlopen_called = False

    def fake_urlopen(request, timeout):
        nonlocal urlopen_called
        urlopen_called = True
        raise AssertionError("Foreign configurations must not send HTTP.")

    monkeypatch.setattr(mpesa_registration, "urlopen", fake_urlopen)
    path = (
        f"/api/properties/{registration_setup['property_id']}/mpesa-paybill/"
        f"{registration_setup['other_configuration_id']}/register-url"
    )
    with app.test_client() as client:
        response = client.post(
            path,
            headers=registration_setup["landlord_headers"],
        )
    assert response.status_code == 404
    assert not urlopen_called


def test_inactive_configuration_cannot_be_registered(
    monkeypatch, app, registration_setup
):
    set_sandbox(monkeypatch)
    with app.app_context():
        configuration = db.session.get(
            PropertyPayBillConfiguration,
            registration_setup["configuration_id"],
        )
        configuration.is_active = False
        db.session.commit()

    urlopen_called = False

    def fake_urlopen(request, timeout):
        nonlocal urlopen_called
        urlopen_called = True
        raise AssertionError("Inactive configurations must not send HTTP.")

    monkeypatch.setattr(mpesa_registration, "urlopen", fake_urlopen)
    with app.test_client() as client:
        response = client.post(
            registration_path(registration_setup),
            headers=registration_setup["landlord_headers"],
        )
    assert response.status_code == 409
    assert not urlopen_called


def test_provider_rejection_returns_sanitized_failure(
    monkeypatch, app, registration_setup
):
    set_sandbox(monkeypatch)
    mock_oauth(monkeypatch)
    monkeypatch.setattr(
        mpesa_registration,
        "urlopen",
        lambda request, timeout: FakeResponse(json.dumps({
            "ResponseCode": "1",
            "ResponseDescription": "provider details are not returned",
        }).encode("utf-8")),
    )
    with app.test_client() as client:
        response = client.post(
            registration_path(registration_setup),
            headers=registration_setup["landlord_headers"],
        )
    assert response.status_code == 502
    assert response.get_json()["success"] is False
    assert response.get_json()["provider_response_code"] == "1"
    assert "provider details" not in response.get_data(as_text=True)


def test_provider_error_message_is_not_reported_as_success(
    monkeypatch, app, registration_setup
):
    set_sandbox(monkeypatch)
    mock_oauth(monkeypatch)
    monkeypatch.setattr(
        mpesa_registration,
        "urlopen",
        lambda request, timeout: FakeResponse(json.dumps({
            "errorMessage": "registration rejected",
        }).encode("utf-8")),
    )
    with app.test_client() as client:
        response = client.post(
            registration_path(registration_setup),
            headers=registration_setup["landlord_headers"],
        )
    assert response.status_code == 502
    assert response.get_json()["success"] is False
    assert response.get_json()["provider_response_code"] is None
