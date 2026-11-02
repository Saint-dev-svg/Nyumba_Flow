import base64
import json
from urllib.error import HTTPError, URLError

import pytest

import mpesa_oauth


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return exc_type is None and exc_value is None and traceback is None

    def read(self, size=-1):
        return self.body[:size]


@pytest.fixture(autouse=True)
def clear_token_cache(monkeypatch):
    monkeypatch.setattr(mpesa_oauth, "_cached_token", None)
    monkeypatch.setattr(mpesa_oauth, "_cached_token_expires_at", 0.0)
    monkeypatch.setattr(mpesa_oauth, "_cached_credential_fingerprint", None)


def set_valid_credentials(monkeypatch):
    monkeypatch.setenv("MPESA_CONSUMER_KEY", "test-consumer-key")
    monkeypatch.setenv("MPESA_CONSUMER_SECRET", "test-consumer-secret")
    monkeypatch.setenv("MPESA_ENVIRONMENT", "sandbox")


def test_success_uses_http_basic_and_caches_token(monkeypatch):
    set_valid_credentials(monkeypatch)
    calls = []

    def fake_urlopen(request, timeout):
        calls.append((request, timeout))
        return FakeResponse(json.dumps({
            "access_token": "test-token-not-a-real-credential",
            "expires_in": "3600",
        }).encode("utf-8"))

    monkeypatch.setattr(mpesa_oauth, "urlopen", fake_urlopen)

    first_token = mpesa_oauth.get_access_token()
    second_token = mpesa_oauth.get_access_token()

    assert first_token == "test-token-not-a-real-credential"
    assert second_token == first_token
    assert len(calls) == 1
    request, timeout = calls[0]
    assert request.full_url == mpesa_oauth.SANDBOX_OAUTH_URL
    assert request.get_method() == "GET"
    encoded_credentials = request.get_header("Authorization").removeprefix("Basic ")
    assert base64.b64decode(encoded_credentials).decode("utf-8") == (
        "test-consumer-key:test-consumer-secret"
    )
    assert timeout == mpesa_oauth.REQUEST_TIMEOUT_SECONDS


def test_expired_token_is_requested_again(monkeypatch):
    set_valid_credentials(monkeypatch)
    tokens = iter(("expired-test-token", "fresh-test-token"))
    calls = []

    def fake_urlopen(request, timeout):
        calls.append((request, timeout))
        return FakeResponse(json.dumps({
            "access_token": next(tokens),
            "expires_in": 60,
        }).encode("utf-8"))

    monkeypatch.setattr(mpesa_oauth, "urlopen", fake_urlopen)

    assert mpesa_oauth.get_access_token() == "expired-test-token"
    assert mpesa_oauth.get_access_token() == "fresh-test-token"
    assert len(calls) == 2
    assert all(timeout == mpesa_oauth.REQUEST_TIMEOUT_SECONDS for _, timeout in calls)


def test_credential_change_does_not_reuse_cached_token(monkeypatch):
    set_valid_credentials(monkeypatch)
    tokens = iter(("first-test-token", "second-test-token"))

    def fake_urlopen(request, timeout):
        assert request.full_url == mpesa_oauth.SANDBOX_OAUTH_URL
        assert timeout == mpesa_oauth.REQUEST_TIMEOUT_SECONDS
        return FakeResponse(json.dumps({
            "access_token": next(tokens),
            "expires_in": "3600",
        }).encode("utf-8"))

    monkeypatch.setattr(mpesa_oauth, "urlopen", fake_urlopen)

    assert mpesa_oauth.get_access_token() == "first-test-token"
    monkeypatch.setenv("MPESA_CONSUMER_SECRET", "rotated-test-secret")
    assert mpesa_oauth.get_access_token() == "second-test-token"


def test_missing_credentials_fail_without_request(monkeypatch):
    monkeypatch.delenv("MPESA_CONSUMER_KEY", raising=False)
    monkeypatch.delenv("MPESA_CONSUMER_SECRET", raising=False)
    urlopen_called = False

    def fake_urlopen(request, timeout):
        assert request.full_url == mpesa_oauth.SANDBOX_OAUTH_URL
        assert timeout == mpesa_oauth.REQUEST_TIMEOUT_SECONDS
        nonlocal urlopen_called
        urlopen_called = True
        raise AssertionError("No request should be sent without credentials.")

    monkeypatch.setattr(mpesa_oauth, "urlopen", fake_urlopen)

    with pytest.raises(mpesa_oauth.DarajaConfigurationError):
        mpesa_oauth.get_access_token()
    assert not urlopen_called


def test_non_sandbox_environment_is_rejected(monkeypatch):
    set_valid_credentials(monkeypatch)
    monkeypatch.setenv("MPESA_ENVIRONMENT", "production")

    with pytest.raises(mpesa_oauth.DarajaConfigurationError):
        mpesa_oauth.get_access_token()


def test_invalid_credentials_raise_safe_authentication_error(monkeypatch):
    set_valid_credentials(monkeypatch)

    def fake_urlopen(request, timeout):
        assert timeout == mpesa_oauth.REQUEST_TIMEOUT_SECONDS
        raise HTTPError(request.full_url, 401, "Unauthorized", {}, None)

    monkeypatch.setattr(mpesa_oauth, "urlopen", fake_urlopen)

    with pytest.raises(mpesa_oauth.DarajaAuthenticationError) as error:
        mpesa_oauth.get_access_token()
    assert "test-consumer-secret" not in str(error.value)


@pytest.mark.parametrize(
    "response_body",
    [
        b"not-json",
        b'{"expires_in": "3600"}',
        b'{"access_token": "test-token", "expires_in": "never"}',
        b'{"access_token": "test-token", "expires_in": 0}',
    ],
)
def test_malformed_oauth_responses_are_rejected(monkeypatch, response_body):
    set_valid_credentials(monkeypatch)
    def fake_urlopen(request, timeout):
        assert request.full_url == mpesa_oauth.SANDBOX_OAUTH_URL
        assert timeout == mpesa_oauth.REQUEST_TIMEOUT_SECONDS
        return FakeResponse(response_body)

    monkeypatch.setattr(mpesa_oauth, "urlopen", fake_urlopen)

    with pytest.raises(mpesa_oauth.DarajaResponseError):
        mpesa_oauth.get_access_token()


@pytest.mark.parametrize(
    "network_error",
    [
        URLError("network unavailable"),
        TimeoutError("request timed out"),
    ],
)
def test_network_errors_raise_safe_request_error(monkeypatch, network_error):
    set_valid_credentials(monkeypatch)

    def fake_urlopen(request, timeout):
        assert request.full_url == mpesa_oauth.SANDBOX_OAUTH_URL
        assert timeout == mpesa_oauth.REQUEST_TIMEOUT_SECONDS
        raise network_error

    monkeypatch.setattr(mpesa_oauth, "urlopen", fake_urlopen)

    with pytest.raises(mpesa_oauth.DarajaRequestError):
        mpesa_oauth.get_access_token()


def test_other_http_errors_are_reported_without_response_body(monkeypatch):
    set_valid_credentials(monkeypatch)

    def fake_urlopen(request, timeout):
        assert timeout == mpesa_oauth.REQUEST_TIMEOUT_SECONDS
        raise HTTPError(request.full_url, 500, "Internal Error", {}, None)

    monkeypatch.setattr(mpesa_oauth, "urlopen", fake_urlopen)

    with pytest.raises(mpesa_oauth.DarajaRequestError) as error:
        mpesa_oauth.get_access_token()
    assert "HTTP 500" in str(error.value)
