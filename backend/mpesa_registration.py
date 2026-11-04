import base64
import json
import logging
import os
import re
import socket
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from mpesa_oauth import DarajaOAuthError, get_access_token_with_source


SANDBOX_REGISTER_URL = (
    "https://sandbox.safaricom.co.ke/mpesa/c2b/v1/registerurl"
)
REQUEST_TIMEOUT_SECONDS = 10
MAX_RESPONSE_BYTES = 64 * 1024
RESPONSE_TYPE = "Completed"
RESTRICTED_CALLBACK_URL_TERMS = (
    "M-PESA",
    "mpesa",
    "Safaricom",
    "exe",
    "exec",
    "cmd",
    "sql",
    "query",
)
logger = logging.getLogger(__name__)


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(
        self, request, file_pointer, code, message, headers, new_url
    ):
        return None


def urlopen(request, timeout):
    return build_opener(_NoRedirectHandler).open(request, timeout=timeout)


class DarajaRegistrationError(RuntimeError):
    """Base error for safe Daraja C2B registration failures."""


class DarajaRegistrationConfigurationError(DarajaRegistrationError):
    """Raised when sandbox or callback URL configuration is invalid."""


class DarajaRegistrationAuthenticationError(DarajaRegistrationError):
    """Raised when OAuth authentication fails."""


class DarajaRegistrationRequestError(DarajaRegistrationError):
    """Raised when Safaricom rejects or cannot process the request."""

    def __init__(
        self,
        message,
        provider_http_status=None,
        provider_error_code=None,
        provider_message=None,
        provider_request_id=None,
    ):
        super().__init__(message)
        self.provider_http_status = provider_http_status
        self.provider_error_code = provider_error_code
        self.provider_message = provider_message
        self.provider_request_id = provider_request_id


class DarajaRegistrationTimeoutError(DarajaRegistrationRequestError):
    """Raised when the Safaricom registration request times out."""


class DarajaRegistrationResponseError(DarajaRegistrationError):
    """Raised when Safaricom returns an invalid response."""


def _callback_urls(configuration_id, base_url=None):
    if base_url is None:
        base_url = os.getenv("MPESA_CALLBACK_BASE_URL", "")
    if not isinstance(base_url, str) or not base_url.strip():
        raise DarajaRegistrationConfigurationError(
            "MPESA_CALLBACK_BASE_URL must be configured."
        )

    base_url = base_url.strip()
    try:
        parsed = urlsplit(base_url)
        port = parsed.port
    except ValueError:
        raise DarajaRegistrationConfigurationError(
            "MPESA_CALLBACK_BASE_URL is invalid."
        ) from None

    if (
        parsed.scheme.lower() != "https"
        or not parsed.netloc
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or "?" in base_url
        or parsed.fragment
        or "#" in base_url
        or "%" in parsed.netloc
        or "\\" in parsed.netloc
        or any(character.isspace() or ord(character) < 32 for character in base_url)
        or (port is not None and not 1 <= port <= 65535)
    ):
        raise DarajaRegistrationConfigurationError(
            "MPESA_CALLBACK_BASE_URL must be an absolute HTTPS URL "
            "without credentials, query strings, or fragments."
        )

    callback_root = (
        f"{base_url.rstrip('/')}/api/integrations/daraja/c2b/{configuration_id}"
    )
    return (
        f"{callback_root}/validation",
        f"{callback_root}/confirmation",
    )


def _validate_callback_urls(validation_url, confirmation_url):
    for callback_url in (validation_url, confirmation_url):
        normalized_url = callback_url.casefold()
        if any(
            term.casefold() in normalized_url
            for term in RESTRICTED_CALLBACK_URL_TERMS
        ):
            raise DarajaRegistrationConfigurationError(
                "A callback URL contains a restricted keyword."
            )


def _sanitize_provider_error_value(value, max_length, sensitive_values):
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        return None

    text = "".join(
        character if character.isprintable() else " "
        for character in str(value)
    )
    text = " ".join(text.split())
    text = re.sub(
        r"\b(?:bearer|basic)\s+[^\s,;]+",
        "[redacted]",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\b(?:consumer[_ ]?(?:key|secret)|access[_ ]?token|"
        r"security[_ ]?credential|password|authorization)\b"
        r"(?:\s*[:=]\s*|\s+)[^\s,;]+",
        "[redacted]",
        text,
        flags=re.IGNORECASE,
    )
    for sensitive_value in sorted(set(sensitive_values), key=len, reverse=True):
        if sensitive_value:
            text = re.sub(
                re.escape(sensitive_value),
                "[redacted]",
                text,
                flags=re.IGNORECASE,
            )
    text = text[:max_length].strip()
    return text or None


def _provider_http_error_details(response_body, configuration, access_token):
    if not response_body or len(response_body) > MAX_RESPONSE_BYTES:
        return None, None, None
    try:
        payload = json.loads(response_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, None, None

    approved_fields = {"errorCode", "errorMessage", "requestId"}
    if (
        not isinstance(payload, dict)
        or not payload
        or not set(payload).issubset(approved_fields)
    ):
        return None, None, None

    error_code = payload.get("errorCode")
    error_message = payload.get("errorMessage")
    request_id = payload.get("requestId")
    if (
        ("errorCode" in payload and (
            not isinstance(error_code, (str, int))
            or isinstance(error_code, bool)
        ))
        or ("errorMessage" in payload and not isinstance(error_message, str))
        or ("requestId" in payload and not isinstance(request_id, (str, int)))
        or isinstance(request_id, bool)
    ):
        return None, None, None

    sensitive_values = _diagnostic_sensitive_values(
        configuration, access_token
    )

    sanitized_code = (
        _sanitize_provider_error_value(error_code, 64, sensitive_values)
        if error_code is not None
        else None
    )
    sanitized_message = (
        _sanitize_provider_error_value(error_message, 240, sensitive_values)
        if error_message is not None
        else None
    )
    sanitized_request_id = (
        _sanitize_provider_error_value(request_id, 128, sensitive_values)
        if request_id is not None
        else None
    )
    if (
        sanitized_code is None
        and sanitized_message is None
        and sanitized_request_id is None
    ):
        return None, None, None
    return sanitized_code, sanitized_message, sanitized_request_id


def _diagnostic_sensitive_values(configuration, access_token):
    sensitive_values = [
        str(configuration.business_shortcode or ""),
        access_token or "",
        os.getenv("MPESA_CONSUMER_KEY", ""),
        os.getenv("MPESA_CONSUMER_SECRET", ""),
    ]
    consumer_key, consumer_secret = sensitive_values[-2:]
    if consumer_key and consumer_secret:
        basic_credentials = base64.b64encode(
            f"{consumer_key}:{consumer_secret}".encode("utf-8")
        ).decode("ascii")
        sensitive_values.extend(
            (f"Basic {basic_credentials}", basic_credentials)
        )
    return sensitive_values


def _callback_location(callback_url):
    parsed = urlsplit(callback_url)
    return {"hostname": parsed.hostname, "path": parsed.path}


def _mask_shortcode(shortcode):
    visible_length = min(3, max(0, len(shortcode) - 1))
    masked_length = len(shortcode) - visible_length
    visible_suffix = shortcode[-visible_length:] if visible_length else ""
    return "*" * masked_length + visible_suffix


def _registration_diagnostics(configuration):
    environment = os.getenv("MPESA_ENVIRONMENT", "").strip().lower()
    if environment not in {"sandbox", "production"}:
        environment = "unset" if not environment else "other"

    shortcode = str(getattr(configuration, "business_shortcode", "") or "")
    masked_shortcode = _mask_shortcode(shortcode) if shortcode else None
    return {
        "event": "daraja_c2b_registration",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "environment": environment,
        "shortcode": masked_shortcode,
        "response_type": RESPONSE_TYPE,
        "validation_callback": None,
        "confirmation_callback": None,
        "oauth_status": "not_attempted",
        "oauth_token_source": None,
        "provider_http_status": None,
        "provider_error_code": None,
        "provider_message": None,
        "provider_request_id": None,
        "outcome": "failed",
        "failure_category": "unexpected_failure",
    }


def _provider_response_diagnostic_fields(
    response_body, configuration, access_token
):
    try:
        payload = json.loads(response_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, None, None
    if not isinstance(payload, dict):
        return None, None, None

    sensitive_values = _diagnostic_sensitive_values(
        configuration, access_token
    )
    code = payload.get("errorCode", payload.get("ResponseCode"))
    message = payload.get("errorMessage", payload.get("ResponseDescription"))
    request_id = payload.get("requestId")
    return (
        _sanitize_provider_error_value(code, 64, sensitive_values),
        _sanitize_provider_error_value(message, 240, sensitive_values),
        _sanitize_provider_error_value(request_id, 128, sensitive_values),
    )


def _log_registration_diagnostics(diagnostics):
    logger.info(
        "%s",
        json.dumps(diagnostics, separators=(",", ":"), sort_keys=True),
    )


def _provider_response(response_body):
    if len(response_body) > MAX_RESPONSE_BYTES:
        raise DarajaRegistrationResponseError(
            "Safaricom returned an oversized registration response."
        )
    try:
        payload = json.loads(response_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise DarajaRegistrationResponseError(
            "Safaricom returned a malformed registration response."
        ) from None
    if not isinstance(payload, dict):
        raise DarajaRegistrationResponseError(
            "Safaricom returned a malformed registration response."
        )

    response_code = payload.get("ResponseCode")
    error_code = payload.get("errorCode")
    if "ResponseCode" in payload and (
        isinstance(response_code, bool)
        or not isinstance(response_code, (str, int))
        or len(str(response_code)) > 100
    ):
        raise DarajaRegistrationResponseError(
            "Safaricom returned a malformed registration response."
        )
    if "errorCode" in payload and (
        isinstance(error_code, bool)
        or not isinstance(error_code, (str, int))
        or len(str(error_code)) > 100
    ):
        raise DarajaRegistrationResponseError(
            "Safaricom returned a malformed registration response."
        )
    error_message = payload.get("errorMessage")
    if error_message is not None and (
        not isinstance(error_message, str) or len(error_message) > 1000
    ):
        raise DarajaRegistrationResponseError(
            "Safaricom returned a malformed registration response."
        )
    has_error_message = bool(error_message and error_message.strip())
    has_result_details = any(
        isinstance(payload.get(field), str) and payload[field].strip()
        for field in (
            "ResponseDescription",
            "ConversationID",
            "OriginatorConversationID",
            "OriginatorCoversationID",
            "errorMessage",
        )
    )
    if not has_result_details and response_code is None and error_code is None:
        raise DarajaRegistrationResponseError(
            "Safaricom returned a malformed registration response."
        )

    code = (
        str(response_code if response_code is not None else error_code)
        if response_code is not None or error_code is not None
        else None
    )
    succeeded = (
        error_code is None
        and not has_error_message
        and response_code in (None, 0, "0")
    )
    return succeeded, code


def _perform_registration(configuration, diagnostics):
    """Register a property's C2B URLs with Daraja sandbox."""
    environment = os.getenv("MPESA_ENVIRONMENT", "").strip().lower()
    if environment != "sandbox":
        raise DarajaRegistrationConfigurationError(
            "C2B URL registration is sandbox-only; MPESA_ENVIRONMENT must be "
            "set to sandbox."
        )

    validation_url, confirmation_url = _callback_urls(configuration.id)
    _validate_callback_urls(validation_url, confirmation_url)
    diagnostics["validation_callback"] = _callback_location(validation_url)
    diagnostics["confirmation_callback"] = _callback_location(
        confirmation_url
    )
    payload = {
        "ShortCode": configuration.business_shortcode,
        "ResponseType": RESPONSE_TYPE,
        "ValidationURL": validation_url,
        "ConfirmationURL": confirmation_url,
    }

    try:
        diagnostics["oauth_status"] = "attempted"
        access_token, token_source = get_access_token_with_source()
        diagnostics["oauth_status"] = "succeeded"
        diagnostics["oauth_token_source"] = token_source
    except DarajaOAuthError:
        diagnostics["oauth_status"] = "failed"
        raise DarajaRegistrationAuthenticationError(
            "Daraja sandbox authentication failed."
        ) from None

    request = Request(
        SANDBOX_REGISTER_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            diagnostics["provider_http_status"] = getattr(
                response, "status", None
            )
            response_body = response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as error:
        diagnostics["provider_http_status"] = error.code
        try:
            error_body = error.read(MAX_RESPONSE_BYTES + 1)
        except (OSError, ValueError):
            error_body = b""
        finally:
            error.close()
        (
            provider_error_code,
            provider_message,
            provider_request_id,
        ) = _provider_http_error_details(error_body, configuration, access_token)
        diagnostics["provider_error_code"] = provider_error_code
        diagnostics["provider_message"] = provider_message
        diagnostics["provider_request_id"] = provider_request_id
        diagnostics["failure_category"] = "provider_http_error"
        raise DarajaRegistrationRequestError(
            f"Safaricom returned HTTP {error.code} during URL registration.",
            provider_http_status=error.code,
            provider_error_code=provider_error_code,
            provider_message=provider_message,
            provider_request_id=provider_request_id,
        ) from None
    except (TimeoutError, socket.timeout):
        raise DarajaRegistrationTimeoutError(
            "Safaricom URL registration timed out."
        ) from None
    except URLError as error:
        if isinstance(error.reason, (TimeoutError, socket.timeout)):
            raise DarajaRegistrationTimeoutError(
                "Safaricom URL registration timed out."
            ) from None
        raise DarajaRegistrationRequestError(
            "Unable to reach the Safaricom URL registration endpoint."
        ) from None
    except OSError:
        raise DarajaRegistrationRequestError(
            "Unable to reach the Safaricom URL registration endpoint."
        ) from None

    succeeded, response_code = _provider_response(response_body)
    (
        diagnostics["provider_error_code"],
        diagnostics["provider_message"],
        diagnostics["provider_request_id"],
    ) = _provider_response_diagnostic_fields(
        response_body, configuration, access_token
    )
    if succeeded:
        diagnostics["outcome"] = "succeeded"
        diagnostics["failure_category"] = None
    else:
        diagnostics["failure_category"] = "provider_rejected"
    message = (
        "Safaricom accepted the callback URL registration."
        if succeeded
        else "Safaricom did not accept the callback URL registration."
    )
    return {
        "success": succeeded,
        "environment": "sandbox",
        "configuration_id": configuration.id,
        "business_shortcode": configuration.business_shortcode,
        "validation_url": validation_url,
        "confirmation_url": confirmation_url,
        "provider_response_code": response_code,
        "message": message,
    }


def register_c2b_urls(configuration):
    """Register C2B URLs and log sanitized diagnostics for each attempt."""
    diagnostics = _registration_diagnostics(configuration)
    try:
        return _perform_registration(configuration, diagnostics)
    except DarajaRegistrationConfigurationError:
        diagnostics["failure_category"] = "configuration"
        raise
    except DarajaRegistrationAuthenticationError:
        diagnostics["failure_category"] = "oauth"
        raise
    except DarajaRegistrationTimeoutError:
        diagnostics["failure_category"] = "timeout"
        raise
    except DarajaRegistrationRequestError:
        if diagnostics["failure_category"] == "unexpected_failure":
            diagnostics["failure_category"] = "request"
        raise
    except DarajaRegistrationResponseError:
        diagnostics["failure_category"] = "invalid_provider_response"
        raise
    finally:
        _log_registration_diagnostics(diagnostics)
