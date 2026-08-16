from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal

from src.app.services.web_app_readiness_verification import (
    normalize_web_app_base_url,
)


InteractiveAcceptanceCategory = Literal[
    "interactive_acceptance_contract_valid",
    "authenticated_application_access_verified",
    "interactive_sign_in_cancelled",
    "interactive_sign_in_failed",
    "authenticated_application_access_failed",
    "authenticated_acceptance_blocked",
]
InteractiveOutcome = Literal[
    "verified",
    "cancelled",
    "sign_in_failed",
    "access_failed",
]

OPERATION = "accept_web_app_authenticated_access"
FIXED_PROTECTED_METHOD = "GET"
FIXED_PROTECTED_ROUTE = "/demo"


@dataclass(frozen=True)
class InteractiveAuthenticationEvidence:
    hosted_origin: str = field(repr=False)
    ready_current: bool
    exact_web_app_artifact_current: bool
    authentication_configuration_current: bool
    runtime_perimeter_current: bool


@dataclass(frozen=True)
class InteractiveAuthenticationPrompt:
    target_url: str = field(repr=False)
    method: str = FIXED_PROTECTED_METHOD
    route: str = FIXED_PROTECTED_ROUTE
    ready_current: bool = True
    authentication_configuration_current: bool = True
    runtime_perimeter_current: bool = True


@dataclass(frozen=True)
class AuthenticatedAccessAcceptanceResult:
    ok: bool
    mode: Literal["check", "live"]
    category: InteractiveAcceptanceCategory
    reason: str | None = None
    interactive_sign_in_attempts: int = 0
    authenticated_protected_get_attempts: int = 0
    operator_confirmed_interactive_evidence: bool = False
    authenticated_demo_verified: bool = False
    application_mutations: int = 0
    retries: bool = False

    def to_json_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "ok": self.ok,
            "mode": self.mode,
            "operation": OPERATION,
            "category": self.category,
            "interactive_sign_in_attempts": self.interactive_sign_in_attempts,
            "automated_credential_entry": False,
            "credentials_captured": False,
            "tokens_serialized": False,
            "cookies_serialized": False,
            "identity_claims_serialized": False,
            "authenticated_protected_get_attempts": (
                self.authenticated_protected_get_attempts
            ),
            "operator_confirmed_interactive_evidence": (
                self.operator_confirmed_interactive_evidence
            ),
            "authenticated_demo_verified": self.authenticated_demo_verified,
            "fixed_protected_method": FIXED_PROTECTED_METHOD,
            "fixed_protected_route": FIXED_PROTECTED_ROUTE,
            "application_mutations": self.application_mutations,
            "azure_mutations": 0,
            "retries": self.retries,
        }
        if self.reason is not None:
            result["reason"] = self.reason
        return result


def check_authenticated_access_acceptance_contract(
) -> AuthenticatedAccessAcceptanceResult:
    valid = bool(
        FIXED_PROTECTED_METHOD == "GET"
        and FIXED_PROTECTED_ROUTE == "/demo"
        and not any(
            marker in FIXED_PROTECTED_ROUTE
            for marker in ("intake", "seed", "reset", "review", "notification")
        )
    )
    if not valid:
        return AuthenticatedAccessAcceptanceResult(
            ok=False,
            mode="check",
            category="authenticated_acceptance_blocked",
            reason="authentication_evidence_invalid",
        )
    return AuthenticatedAccessAcceptanceResult(
        ok=True,
        mode="check",
        category="interactive_acceptance_contract_valid",
    )


def _evidence_valid(evidence: object) -> bool:
    if not isinstance(evidence, InteractiveAuthenticationEvidence):
        return False
    if not all(
        value is True
        for value in (
            evidence.ready_current,
            evidence.exact_web_app_artifact_current,
            evidence.authentication_configuration_current,
            evidence.runtime_perimeter_current,
        )
    ):
        return False
    try:
        return normalize_web_app_base_url(evidence.hosted_origin) == (
            evidence.hosted_origin
        )
    except (TypeError, ValueError):
        return False


def accept_authenticated_application_access(
    evidence: InteractiveAuthenticationEvidence | None,
    *,
    operator_checkpoint: Callable[
        [InteractiveAuthenticationPrompt], InteractiveOutcome
    ],
) -> AuthenticatedAccessAcceptanceResult:
    if not _evidence_valid(evidence):
        return AuthenticatedAccessAcceptanceResult(
            ok=False,
            mode="live",
            category="authenticated_acceptance_blocked",
            reason="authentication_evidence_invalid",
        )
    assert evidence is not None
    prompt = InteractiveAuthenticationPrompt(
        target_url=f"{evidence.hosted_origin}{FIXED_PROTECTED_ROUTE}",
    )
    try:
        outcome = operator_checkpoint(prompt)
    except Exception:
        outcome = "sign_in_failed"
    if outcome == "verified":
        return AuthenticatedAccessAcceptanceResult(
            ok=True,
            mode="live",
            category="authenticated_application_access_verified",
            interactive_sign_in_attempts=1,
            authenticated_protected_get_attempts=1,
            operator_confirmed_interactive_evidence=True,
            authenticated_demo_verified=True,
        )
    if outcome == "cancelled":
        return AuthenticatedAccessAcceptanceResult(
            ok=False,
            mode="live",
            category="interactive_sign_in_cancelled",
            interactive_sign_in_attempts=1,
        )
    if outcome == "access_failed":
        return AuthenticatedAccessAcceptanceResult(
            ok=False,
            mode="live",
            category="authenticated_application_access_failed",
            interactive_sign_in_attempts=1,
            authenticated_protected_get_attempts=1,
        )
    return AuthenticatedAccessAcceptanceResult(
        ok=False,
        mode="live",
        category="interactive_sign_in_failed",
        interactive_sign_in_attempts=1,
    )
