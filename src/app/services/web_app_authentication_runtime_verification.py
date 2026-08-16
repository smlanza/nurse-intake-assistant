from __future__ import annotations

from dataclasses import dataclass, replace
import json
from typing import Callable, Literal

from src.app.services.web_app_hosting_contract import (
    APP_SERVICE_AUTHENTICATION_ANONYMOUS_PATHS,
)
from src.app.services.web_app_readiness_verification import (
    DEFAULT_TIMEOUT_SECONDS,
    WebAppReadinessTransport,
    _demo_status_contract_valid,
    _health_contract_valid,
    _safe_hosted_posture,
    _version_contract_valid,
    normalize_web_app_base_url,
)


RuntimeCategory = Literal[
    "runtime_contract_valid",
    "authentication_perimeter_verified",
    "anonymous_route_acceptance_failed",
    "protected_route_acceptance_failed",
    "safe_runtime_verification_blocked",
]
RuntimeReason = Literal[
    "readiness_evidence_invalid",
    "transport_failed",
    "anonymous_route_unavailable",
    "malformed_response",
    "response_contract_mismatch",
    "protected_route_not_401",
]
RuntimeMode = Literal["check", "live"]

OPERATION = "verify_web_app_authentication_runtime"
ANONYMOUS_PATHS = APP_SERVICE_AUTHENTICATION_ANONYMOUS_PATHS
PROTECTED_PATHS = ("/demo", "/cases", "/docs", "/openapi.json")
_ROUTE_NAMES = {
    "/health": "health",
    "/version": "version",
    "/demo/status": "demo_status",
    "/demo": "demo",
    "/cases": "cases",
    "/docs": "docs",
    "/openapi.json": "openapi",
}
_ANONYMOUS_VALIDATORS = {
    "/health": _health_contract_valid,
    "/version": _version_contract_valid,
    "/demo/status": lambda payload: (
        _demo_status_contract_valid(payload) and _safe_hosted_posture(payload)
    ),
}


@dataclass(frozen=True)
class RuntimeAuthenticationEvidence:
    hosted_origin: str
    ready_current: bool
    exact_web_app_current: bool
    artifact_readiness_current: bool
    authentication_configuration_current: bool


@dataclass(frozen=True)
class AuthenticationRuntimeVerificationResult:
    ok: bool
    mode: RuntimeMode
    category: RuntimeCategory
    reason: RuntimeReason | None = None
    route: str | None = None
    runtime_verification_attempted: bool = False
    anonymous_gets_attempted: int = 0
    protected_gets_attempted: int = 0
    anonymous_health_verified: bool = False
    anonymous_version_verified: bool = False
    anonymous_demo_status_verified: bool = False
    protected_demo_verified: bool = False
    protected_cases_verified: bool = False
    protected_docs_verified: bool = False
    protected_openapi_verified: bool = False
    authentication_perimeter_verified: bool = False

    def to_json_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "ok": self.ok,
            "mode": self.mode,
            "operation": OPERATION,
            "category": self.category,
            "runtime_verification_attempted": (
                self.runtime_verification_attempted
            ),
            "anonymous_gets_attempted": self.anonymous_gets_attempted,
            "protected_gets_attempted": self.protected_gets_attempted,
            "anonymous_health_verified": self.anonymous_health_verified,
            "anonymous_version_verified": self.anonymous_version_verified,
            "anonymous_demo_status_verified": (
                self.anonymous_demo_status_verified
            ),
            "protected_demo_verified": self.protected_demo_verified,
            "protected_cases_verified": self.protected_cases_verified,
            "protected_docs_verified": self.protected_docs_verified,
            "protected_openapi_verified": self.protected_openapi_verified,
            "authentication_perimeter_verified": (
                self.authentication_perimeter_verified
            ),
            "credentials_used": False,
            "cookies_used": False,
            "redirect_following": False,
            "retries": False,
            "azure_mutation_made": False,
            "application_mutation_made": False,
            "interactive_sign_in": False,
        }
        if self.reason is not None:
            result["reason"] = self.reason
        if self.route is not None:
            result["route"] = self.route
        return result


def check_web_app_authentication_runtime_contract(
) -> AuthenticationRuntimeVerificationResult:
    valid = bool(
        ANONYMOUS_PATHS == ("/health", "/version", "/demo/status")
        and PROTECTED_PATHS
        == ("/demo", "/cases", "/docs", "/openapi.json")
        and set(ANONYMOUS_PATHS).isdisjoint(PROTECTED_PATHS)
        and set(_ROUTE_NAMES) == {*ANONYMOUS_PATHS, *PROTECTED_PATHS}
        and set(_ANONYMOUS_VALIDATORS) == set(ANONYMOUS_PATHS)
    )
    if not valid:
        return AuthenticationRuntimeVerificationResult(
            ok=False,
            mode="check",
            category="safe_runtime_verification_blocked",
            reason="readiness_evidence_invalid",
        )
    return AuthenticationRuntimeVerificationResult(
        ok=True,
        mode="check",
        category="runtime_contract_valid",
    )


def _evidence_valid(evidence: object) -> bool:
    if not isinstance(evidence, RuntimeAuthenticationEvidence):
        return False
    if not all(
        value is True
        for value in (
            evidence.ready_current,
            evidence.exact_web_app_current,
            evidence.artifact_readiness_current,
            evidence.authentication_configuration_current,
        )
    ):
        return False
    try:
        return normalize_web_app_base_url(evidence.hosted_origin) == (
            evidence.hosted_origin
        )
    except (TypeError, ValueError):
        return False


def _failure(
    category: RuntimeCategory,
    reason: RuntimeReason,
    *,
    route: str | None = None,
    progress: AuthenticationRuntimeVerificationResult | None = None,
) -> AuthenticationRuntimeVerificationResult:
    if progress is None:
        return AuthenticationRuntimeVerificationResult(
            ok=False,
            mode="live",
            category=category,
            reason=reason,
            route=route,
        )
    return replace(
        progress,
        ok=False,
        category=category,
        reason=reason,
        route=route,
        authentication_perimeter_verified=False,
    )


def verify_web_app_authentication_runtime(
    evidence: RuntimeAuthenticationEvidence | None,
    *,
    transport_factory: Callable[[str], WebAppReadinessTransport],
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> AuthenticationRuntimeVerificationResult:
    if not _evidence_valid(evidence):
        return _failure(
            "safe_runtime_verification_blocked",
            "readiness_evidence_invalid",
        )
    assert evidence is not None
    try:
        transport = transport_factory(evidence.hosted_origin)
    except Exception:
        return _failure(
            "safe_runtime_verification_blocked",
            "transport_failed",
        )

    progress = AuthenticationRuntimeVerificationResult(
        ok=False,
        mode="live",
        category="safe_runtime_verification_blocked",
        runtime_verification_attempted=True,
    )
    anonymous_fields = {
        "/health": "anonymous_health_verified",
        "/version": "anonymous_version_verified",
        "/demo/status": "anonymous_demo_status_verified",
    }
    protected_fields = {
        "/demo": "protected_demo_verified",
        "/cases": "protected_cases_verified",
        "/docs": "protected_docs_verified",
        "/openapi.json": "protected_openapi_verified",
    }

    for path in ANONYMOUS_PATHS:
        progress = replace(
            progress,
            anonymous_gets_attempted=progress.anonymous_gets_attempted + 1,
        )
        try:
            response = transport.get(path, timeout_seconds)
        except Exception:
            return _failure(
                "anonymous_route_acceptance_failed",
                "transport_failed",
                route=_ROUTE_NAMES[path],
                progress=progress,
            )
        if response.status_code != 200:
            return _failure(
                "anonymous_route_acceptance_failed",
                "anonymous_route_unavailable",
                route=_ROUTE_NAMES[path],
                progress=progress,
            )
        try:
            payload = json.loads(response.body)
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
            return _failure(
                "anonymous_route_acceptance_failed",
                "malformed_response",
                route=_ROUTE_NAMES[path],
                progress=progress,
            )
        if not _ANONYMOUS_VALIDATORS[path](payload):
            return _failure(
                "anonymous_route_acceptance_failed",
                "response_contract_mismatch",
                route=_ROUTE_NAMES[path],
                progress=progress,
            )
        progress = replace(progress, **{anonymous_fields[path]: True})

    for path in PROTECTED_PATHS:
        progress = replace(
            progress,
            protected_gets_attempted=progress.protected_gets_attempted + 1,
        )
        try:
            response = transport.get(path, timeout_seconds)
        except Exception:
            return _failure(
                "protected_route_acceptance_failed",
                "transport_failed",
                route=_ROUTE_NAMES[path],
                progress=progress,
            )
        if response.status_code != 401:
            return _failure(
                "protected_route_acceptance_failed",
                "protected_route_not_401",
                route=_ROUTE_NAMES[path],
                progress=progress,
            )
        progress = replace(progress, **{protected_fields[path]: True})

    return replace(
        progress,
        ok=True,
        category="authentication_perimeter_verified",
        authentication_perimeter_verified=True,
    )
