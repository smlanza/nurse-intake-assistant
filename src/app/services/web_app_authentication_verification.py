from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from src.app.services.web_app_hosting_contract import (
    APP_SERVICE_AUTHENTICATION_ANONYMOUS_PATHS,
    app_service_authentication_configuration_valid,
)
from src.app.services.web_app_infra_deployment import (
    web_app_authentication_local_contract_valid,
)


AuthenticationVerificationCategory = Literal[
    "success",
    "configuration_invalid",
    "local_contract_invalid",
]

MESSAGES: dict[AuthenticationVerificationCategory, str] = {
    "success": "App Service Authentication contract verification completed.",
    "configuration_invalid": (
        "The expected App Service Authentication configuration is invalid."
    ),
    "local_contract_invalid": (
        "The local App Service Authentication infrastructure contract is invalid."
    ),
}


@dataclass(frozen=True)
class WebAppAuthenticationVerificationResult:
    ok: bool
    category: AuthenticationVerificationCategory
    mode: str
    operation: str
    message: str
    local_contract_validated: bool
    azure_request_attempted: bool
    authentication_state_verified: bool
    authentication_v2_enabled: bool
    microsoft_entra_provider_verified: bool
    authentication_required_verified: bool
    https_required_verified: bool
    anonymous_exclusions_verified: bool
    client_application_identity_configuration_verified: bool
    recommended_next_step: str

    def to_json_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "category": self.category,
            "mode": self.mode,
            "operation": self.operation,
            "message": self.message,
            "local_contract_validated": self.local_contract_validated,
            "azure_request_attempted": self.azure_request_attempted,
            "authentication_state_verified": self.authentication_state_verified,
            "authentication_v2_enabled": self.authentication_v2_enabled,
            "microsoft_entra_provider_verified": (
                self.microsoft_entra_provider_verified
            ),
            "authentication_required_verified": (
                self.authentication_required_verified
            ),
            "https_required_verified": self.https_required_verified,
            "anonymous_exclusions_verified": self.anonymous_exclusions_verified,
            "client_application_identity_configuration_verified": (
                self.client_application_identity_configuration_verified
            ),
            "recommended_next_step": self.recommended_next_step,
        }


def _result(
    category: AuthenticationVerificationCategory,
    *,
    enabled: bool = False,
    local_contract_validated: bool = False,
) -> WebAppAuthenticationVerificationResult:
    ok = category == "success"
    enabled_proofs = ok and enabled
    return WebAppAuthenticationVerificationResult(
        ok=ok,
        category=category,
        mode="check",
        operation="verify_web_app_authentication",
        message=MESSAGES[category],
        local_contract_validated=local_contract_validated,
        azure_request_attempted=False,
        authentication_state_verified=ok,
        authentication_v2_enabled=enabled_proofs,
        microsoft_entra_provider_verified=enabled_proofs,
        authentication_required_verified=enabled_proofs,
        https_required_verified=enabled_proofs,
        anonymous_exclusions_verified=enabled_proofs,
        client_application_identity_configuration_verified=enabled_proofs,
        recommended_next_step=(
            "Keep authentication disabled until a separate supervised live acceptance."
            if ok and not enabled
            else (
                "Review the offline proof before a separate supervised live acceptance."
                if ok
                else "Restore the exact disabled or enabled local authentication contract."
            )
        ),
    )


def check_web_app_authentication_contract(
    configuration: Mapping[str, object],
    *,
    template_file: Path | None = None,
) -> WebAppAuthenticationVerificationResult:
    """Verify the local opt-in Authentication v2 contract without an Azure call."""

    if not app_service_authentication_configuration_valid(configuration):
        return _result("configuration_invalid")
    module = template_file or (
        Path(__file__).resolve().parents[3]
        / "infra/modules/web-app-authentication.bicep"
    )
    if not web_app_authentication_local_contract_valid(module):
        return _result("local_contract_invalid")
    enabled = configuration["mode"] == "enabled"
    if enabled and APP_SERVICE_AUTHENTICATION_ANONYMOUS_PATHS != (
        "/health",
        "/version",
        "/demo/status",
    ):
        return _result(
            "local_contract_invalid",
            local_contract_validated=True,
        )
    return _result(
        "success",
        enabled=enabled,
        local_contract_validated=True,
    )
