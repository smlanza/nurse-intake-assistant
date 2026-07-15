from dataclasses import dataclass
import json
from typing import Callable, Literal, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


ReadinessCategory = Literal[
    "success",
    "missing_configuration",
    "invalid_configuration",
    "http_request_failed",
    "unexpected_http_status",
    "malformed_json",
    "response_contract_mismatch",
    "unsafe_hosted_posture",
    "unexpected_error",
]
ReadinessMode = Literal["check", "live"]
DEFAULT_TIMEOUT_SECONDS = 5.0
READINESS_OPERATION = "verify_web_app_readiness"
CHECK_SUCCESS_MESSAGE = "Web App readiness configuration check completed."
LIVE_SUCCESS_MESSAGE = "Hosted Web App readiness verification completed."
FAILURE_MESSAGES: dict[ReadinessCategory, str] = {
    "success": LIVE_SUCCESS_MESSAGE,
    "missing_configuration": "Web App readiness configuration is missing.",
    "invalid_configuration": "Web App readiness configuration is invalid.",
    "http_request_failed": "Hosted readiness request failed.",
    "unexpected_http_status": "Hosted endpoint returned an unexpected HTTP status.",
    "malformed_json": "Hosted endpoint returned malformed JSON.",
    "response_contract_mismatch": (
        "Hosted endpoint response did not match the expected contract."
    ),
    "unsafe_hosted_posture": (
        "Hosted application did not report the required safe mock posture."
    ),
    "unexpected_error": "Hosted readiness verification did not complete.",
}
CHECK_NEXT_STEP = (
    "Run the separate --live --json readiness verification only after reviewing "
    "infrastructure and code deployment-request acceptance."
)
LIVE_NEXT_STEP = (
    "Review the sanitized readiness result before any separate RBAC, managed-identity, "
    "Foundry verification, or invocation stage."
)
FAILURE_NEXT_STEP = (
    "Review the sanitized failure category before explicitly running verification again."
)


class MissingBaseUrlError(ValueError):
    pass


class HttpRequestError(Exception):
    pass


@dataclass(frozen=True)
class HttpResponse:
    status_code: int
    body: bytes


class WebAppReadinessTransport(Protocol):
    def get(self, path: str, timeout_seconds: float) -> HttpResponse: ...


@dataclass(frozen=True)
class WebAppReadinessVerificationResult:
    ok: bool
    mode: ReadinessMode
    operation: str
    category: ReadinessCategory
    message: str
    base_url_valid: bool
    hosted_request_attempted: bool
    health_verified: bool
    version_verified: bool
    demo_status_verified: bool
    safe_hosted_posture_verified: bool
    recommended_next_step: str

    @classmethod
    def success(cls, mode: ReadinessMode) -> "WebAppReadinessVerificationResult":
        live = mode == "live"
        return cls(
            ok=True,
            mode=mode,
            operation=READINESS_OPERATION,
            category="success",
            message=LIVE_SUCCESS_MESSAGE if live else CHECK_SUCCESS_MESSAGE,
            base_url_valid=True,
            hosted_request_attempted=live,
            health_verified=live,
            version_verified=live,
            demo_status_verified=live,
            safe_hosted_posture_verified=live,
            recommended_next_step=LIVE_NEXT_STEP if live else CHECK_NEXT_STEP,
        )

    @classmethod
    def failure(
        cls,
        mode: ReadinessMode,
        category: ReadinessCategory,
        *,
        base_url_valid: bool = False,
        hosted_request_attempted: bool = False,
        health_verified: bool = False,
        version_verified: bool = False,
        demo_status_verified: bool = False,
    ) -> "WebAppReadinessVerificationResult":
        return cls(
            ok=False,
            mode=mode,
            operation=READINESS_OPERATION,
            category=category,
            message=FAILURE_MESSAGES[category],
            base_url_valid=base_url_valid,
            hosted_request_attempted=hosted_request_attempted,
            health_verified=health_verified,
            version_verified=version_verified,
            demo_status_verified=demo_status_verified,
            safe_hosted_posture_verified=False,
            recommended_next_step=FAILURE_NEXT_STEP,
        )

    def to_json_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "mode": self.mode,
            "operation": self.operation,
            "category": self.category,
            "message": self.message,
            "base_url_valid": self.base_url_valid,
            "hosted_request_attempted": self.hosted_request_attempted,
            "health_verified": self.health_verified,
            "version_verified": self.version_verified,
            "demo_status_verified": self.demo_status_verified,
            "safe_hosted_posture_verified": self.safe_hosted_posture_verified,
            "recommended_next_step": self.recommended_next_step,
        }


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(
        self,
        request,
        file_pointer,
        code,
        message,
        headers,
        new_url,
    ) -> None:
        return None


class UrllibWebAppReadinessTransport:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url
        self._opener = build_opener(_NoRedirectHandler())

    def get(self, path: str, timeout_seconds: float) -> HttpResponse:
        request = Request(
            f"{self.base_url}{path}",
            headers={"Accept": "application/json"},
            method="GET",
        )
        try:
            with self._opener.open(request, timeout=timeout_seconds) as response:
                return HttpResponse(
                    status_code=response.status,
                    body=response.read(),
                )
        except HTTPError as error:
            return HttpResponse(status_code=error.code, body=b"")
        except (URLError, TimeoutError, OSError) as error:
            raise HttpRequestError() from error


def normalize_web_app_base_url(base_url: str | None) -> str:
    value = "" if base_url is None else base_url.strip()
    if not value:
        raise MissingBaseUrlError()

    parsed = urlsplit(value)
    if (
        parsed.scheme.lower() != "https"
        or not parsed.netloc
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ValueError()

    try:
        port = parsed.port
    except ValueError:
        raise ValueError() from None

    hostname = parsed.hostname.lower()
    if any(character.isspace() for character in hostname):
        raise ValueError()
    host = f"[{hostname}]" if ":" in hostname else hostname
    if port is not None:
        host = f"{host}:{port}"
    return f"https://{host}"


def check_web_app_readiness_configuration(
    base_url: str | None,
) -> WebAppReadinessVerificationResult:
    try:
        normalize_web_app_base_url(base_url)
    except MissingBaseUrlError:
        return WebAppReadinessVerificationResult.failure(
            "check",
            "missing_configuration",
        )
    except ValueError:
        return WebAppReadinessVerificationResult.failure(
            "check",
            "invalid_configuration",
        )
    return WebAppReadinessVerificationResult.success("check")


def verify_web_app_readiness(
    base_url: str | None,
    *,
    transport_factory: Callable[[str], WebAppReadinessTransport],
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> WebAppReadinessVerificationResult:
    try:
        normalized_base_url = normalize_web_app_base_url(base_url)
    except MissingBaseUrlError:
        return WebAppReadinessVerificationResult.failure(
            "live",
            "missing_configuration",
        )
    except ValueError:
        return WebAppReadinessVerificationResult.failure(
            "live",
            "invalid_configuration",
        )

    try:
        transport = transport_factory(normalized_base_url)
    except Exception:
        return WebAppReadinessVerificationResult.failure(
            "live",
            "unexpected_error",
            base_url_valid=True,
        )

    progress = {
        "base_url_valid": True,
        "hosted_request_attempted": False,
        "health_verified": False,
        "version_verified": False,
        "demo_status_verified": False,
    }
    validators = (
        ("/health", _health_contract_valid, "health_verified"),
        ("/version", _version_contract_valid, "version_verified"),
        ("/demo/status", _demo_status_contract_valid, "demo_status_verified"),
    )

    for path, validator, progress_field in validators:
        progress["hosted_request_attempted"] = True
        try:
            response = transport.get(path, timeout_seconds)
        except HttpRequestError:
            return WebAppReadinessVerificationResult.failure(
                "live",
                "http_request_failed",
                **progress,
            )
        except Exception:
            return WebAppReadinessVerificationResult.failure(
                "live",
                "unexpected_error",
                **progress,
            )

        if response.status_code != 200:
            return WebAppReadinessVerificationResult.failure(
                "live",
                "unexpected_http_status",
                **progress,
            )
        try:
            payload = json.loads(response.body)
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
            return WebAppReadinessVerificationResult.failure(
                "live",
                "malformed_json",
                **progress,
            )
        if not validator(payload):
            return WebAppReadinessVerificationResult.failure(
                "live",
                "response_contract_mismatch",
                **progress,
            )
        progress[progress_field] = True

        if path == "/demo/status" and not _safe_hosted_posture(payload):
            return WebAppReadinessVerificationResult.failure(
                "live",
                "unsafe_hosted_posture",
                **progress,
            )

    return WebAppReadinessVerificationResult.success("live")


def _health_contract_valid(payload: object) -> bool:
    return bool(
        isinstance(payload, dict)
        and payload.get("status") == "ok"
        and payload.get("service") == "nurse-intake-assistant"
    )


def _version_contract_valid(payload: object) -> bool:
    if not isinstance(payload, dict):
        return False
    version = payload.get("version")
    environment = payload.get("environment")
    return bool(
        payload.get("service") == "nurse-intake-assistant"
        and isinstance(version, str)
        and version
        and isinstance(environment, str)
        and environment
    )


def _demo_status_contract_valid(payload: object) -> bool:
    if not isinstance(payload, dict):
        return False
    string_fields = {
        "appMode",
        "aiProvider",
        "speechProvider",
        "emailProvider",
        "smsProvider",
        "agentProvider",
        "safetyBoundary",
    }
    boolean_fields = {
        "demoModeReady",
        "notificationsSuppressed",
        "safeForLocalDemo",
    }
    if not all(isinstance(payload.get(field), str) for field in string_fields):
        return False
    if not all(isinstance(payload.get(field), bool) for field in boolean_fields):
        return False
    if not _string_list(payload.get("warnings")):
        return False
    return _agent_status_contract_valid(payload.get("agentStatus")) and (
        _agent_provider_status_contract_valid(payload.get("agentProviderStatus"))
    )


def _agent_status_contract_valid(payload: object) -> bool:
    return bool(
        isinstance(payload, dict)
        and isinstance(payload.get("provider"), str)
        and isinstance(payload.get("ready"), bool)
        and isinstance(payload.get("mode"), str)
        and _string_list(payload.get("missingSettings"))
    )


def _agent_provider_status_contract_valid(payload: object) -> bool:
    if not isinstance(payload, dict):
        return False
    manual_command = payload.get("manualValidationCommand")
    return bool(
        isinstance(payload.get("provider"), str)
        and isinstance(payload.get("configured"), bool)
        and isinstance(payload.get("liveValidation"), str)
        and isinstance(payload.get("manualValidationAvailable"), bool)
        and (manual_command is None or isinstance(manual_command, str))
        and _string_list(payload.get("missingSettings"))
        and _string_list(payload.get("warnings"))
    )


def _string_list(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _safe_hosted_posture(payload: object) -> bool:
    if not isinstance(payload, dict):
        return False
    agent_status = payload.get("agentStatus")
    agent_provider_status = payload.get("agentProviderStatus")
    return bool(
        payload.get("demoModeReady") is True
        and payload.get("appMode") == "mock"
        and payload.get("aiProvider") == "mock"
        and payload.get("speechProvider") == "mock"
        and payload.get("emailProvider") == "mock"
        and payload.get("smsProvider") == "mock"
        and payload.get("agentProvider") == "mock"
        and payload.get("notificationsSuppressed") is True
        and payload.get("safeForLocalDemo") is True
        and payload.get("warnings") == []
        and isinstance(agent_status, dict)
        and agent_status.get("provider") == "mock"
        and agent_status.get("ready") is True
        and agent_status.get("mode") == "mock"
        and agent_status.get("missingSettings") == []
        and isinstance(agent_provider_status, dict)
        and agent_provider_status.get("provider") == "mock"
        and agent_provider_status.get("configured") is True
        and agent_provider_status.get("liveValidation") == "not_attempted"
        and agent_provider_status.get("manualValidationAvailable") is False
        and agent_provider_status.get("manualValidationCommand") is None
        and agent_provider_status.get("missingSettings") == []
        and agent_provider_status.get("warnings") == []
    )
