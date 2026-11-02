import base64
import hashlib
import json
import os
from threading import Lock
from time import monotonic
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


SANDBOX_OAUTH_URL = (
    "https://sandbox.safaricom.co.ke/oauth/v1/generate"
    "?grant_type=client_credentials"
)
REQUEST_TIMEOUT_SECONDS = 10
TOKEN_EXPIRY_SKEW_SECONDS = 60
MAX_RESPONSE_BYTES = 64 * 1024


class DarajaOAuthError(RuntimeError):
    """Base error for Safaricom Daraja OAuth failures."""


class DarajaConfigurationError(DarajaOAuthError):
    """Raised when the required sandbox configuration is unavailable."""


class DarajaAuthenticationError(DarajaOAuthError):
    """Raised when Safaricom rejects the configured client credentials."""


class DarajaRequestError(DarajaOAuthError):
    """Raised when the OAuth endpoint cannot be reached or returns an error."""


class DarajaResponseError(DarajaOAuthError):
    """Raised when the OAuth endpoint response is invalid."""


_token_lock = Lock()
_cached_token = None
_cached_token_expires_at = 0.0
_cached_credential_fingerprint = None


def _read_configuration():
    consumer_key = os.getenv("MPESA_CONSUMER_KEY", "").strip()
    consumer_secret = os.getenv("MPESA_CONSUMER_SECRET", "").strip()
    environment = os.getenv("MPESA_ENVIRONMENT", "sandbox").strip().lower()

    if not consumer_key or not consumer_secret:
        raise DarajaConfigurationError(
            "MPESA_CONSUMER_KEY and MPESA_CONSUMER_SECRET must be configured."
        )
    if environment != "sandbox":
        raise DarajaConfigurationError(
            "The Daraja OAuth client currently supports the sandbox environment only."
        )
    return consumer_key, consumer_secret


def _parse_oauth_response(response_body):
    try:
        payload = json.loads(response_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise DarajaResponseError(
            "Daraja OAuth returned a malformed response."
        ) from None

    if not isinstance(payload, dict):
        raise DarajaResponseError(
            "Daraja OAuth returned a malformed response."
        )

    access_token = payload.get("access_token")
    if not isinstance(access_token, str) or not access_token.strip():
        raise DarajaResponseError(
            "Daraja OAuth response did not contain a valid access token."
        )

    expires_in = payload.get("expires_in")
    if isinstance(expires_in, bool) or not isinstance(expires_in, (str, int)):
        raise DarajaResponseError(
            "Daraja OAuth response did not contain a valid token expiry."
        )
    if isinstance(expires_in, str) and not expires_in.isdigit():
        raise DarajaResponseError(
            "Daraja OAuth response did not contain a valid token expiry."
        )
    try:
        expires_in = int(expires_in)
    except (TypeError, ValueError):
        raise DarajaResponseError(
            "Daraja OAuth response did not contain a valid token expiry."
        ) from None
    if expires_in <= 0:
        raise DarajaResponseError(
            "Daraja OAuth response did not contain a valid token expiry."
        )

    return access_token.strip(), expires_in


def _request_access_token(consumer_key, consumer_secret):
    basic_credentials = base64.b64encode(
        f"{consumer_key}:{consumer_secret}".encode("utf-8")
    ).decode("ascii")
    request = Request(
        SANDBOX_OAUTH_URL,
        headers={"Authorization": f"Basic {basic_credentials}"},
        method="GET",
    )

    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            response_body = response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as error:
        if error.code in (401, 403):
            raise DarajaAuthenticationError(
                "Safaricom rejected the Daraja consumer credentials."
            ) from None
        raise DarajaRequestError(
            f"Daraja OAuth returned HTTP {error.code}."
        ) from None
    except (URLError, TimeoutError, OSError):
        raise DarajaRequestError(
            "Unable to reach the Daraja OAuth endpoint."
        ) from None

    if len(response_body) > MAX_RESPONSE_BYTES:
        raise DarajaResponseError(
            "Daraja OAuth response exceeded the supported size."
        )
    return _parse_oauth_response(response_body)


def get_access_token():
    """Return a cached, unexpired sandbox OAuth token or request a new one."""
    global _cached_token, _cached_token_expires_at
    global _cached_credential_fingerprint

    consumer_key, consumer_secret = _read_configuration()
    credential_fingerprint = hashlib.sha256(
        f"{consumer_key}\0{consumer_secret}".encode("utf-8")
    ).digest()
    with _token_lock:
        now = monotonic()
        if (
            _cached_token
            and credential_fingerprint == _cached_credential_fingerprint
            and now < _cached_token_expires_at
        ):
            return _cached_token

        access_token, expires_in = _request_access_token(
            consumer_key,
            consumer_secret,
        )
        _cached_token = access_token
        _cached_credential_fingerprint = credential_fingerprint
        _cached_token_expires_at = (
            monotonic() + max(0, expires_in - TOKEN_EXPIRY_SKEW_SECONDS)
        )
        return access_token
