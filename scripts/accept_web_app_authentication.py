from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Literal, Protocol, TextIO
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.app.services.azure_what_if_evidence import (
    AZURE_PROVIDER_FAMILIES,
    AZURE_RESOURCE_FAMILIES,
    AzureProviderFamily,
    AzureResourceFamily,
    ExpectedWhatIfResource,
    SanitizedWhatIfSummary,
    parse_sanitized_what_if,
)
from src.app.services.daily_azure_environment_rebuild import (
    READINESS_RECEIPT_FILE,
    ConfigValidationError,
    DailyAzureConfig,
    DailyAzureReadinessReceipt,
    daily_azure_readiness_state_path,
    load_daily_azure_config,
    load_matching_daily_azure_readiness_receipt,
)
from src.app.services.web_app_authentication_verification import (
    check_web_app_authentication_contract,
)
from src.app.services.web_app_hosting_contract import (
    ALWAYS_ON_REQUIRED,
    APP_SERVICE_AUTHENTICATION_ANONYMOUS_PATHS,
    BASELINE_APP_SETTINGS,
    app_service_authentication_configuration_valid,
    hosted_verifier_settings_valid,
)
from src.app.services.web_app_configuration_verification import (
    EXPECTED_HEALTH_CHECK_PATH,
    EXPECTED_LINUX_FX_VERSION,
    EXPECTED_STARTUP_COMMAND,
    SITE_CONFIG_QUERY,
)
from src.app.services.web_app_infra_deployment import (
    CommandResult,
    WebAppInfrastructureDeploymentRequest,
    deploy_web_app_infrastructure,
    parse_web_app_infrastructure_what_if,
    validate_web_app_infrastructure_request,
    web_app_infrastructure_deployment_command,
)
from src.app.services.web_app_package import (
    PackageSafetyError,
    authorized_application_artifact_digest,
    build_web_app_package,
    create_package_authorization_session,
)
from src.app.services.web_app_readiness_verification import (
    HttpResponse,
    UrllibWebAppReadinessTransport,
    WebAppReadinessTransport,
    normalize_web_app_base_url,
    verify_web_app_readiness,
)


OPERATION = "accept_web_app_authentication"
DEFAULT_SESSION_FILE = ROOT / ".artifacts/daily-azure-rebuild/current-session.env"
OPERATOR_IDENTIFIER_ENVIRONMENT = {
    "client_application_id": "OPERATOR_ENTRA_APPLICATION_ID",
    "tenant_id": "OPERATOR_ENTRA_TENANT_ID",
}
GUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
)
HEX_64 = re.compile(r"[0-9a-f]{64}")
RUN_EPOCH = re.compile(r"[0-9a-f]{32}")
SAFE_ENVIRONMENT_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}")
SAFE_HOST = re.compile(
    r"[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?"
    r"(?:\.[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?)+"
)
AUTH_QUERY = (
    "{platformEnabled:properties.platform.enabled,"
    "requireAuthentication:properties.globalValidation.requireAuthentication,"
    "unauthenticatedClientAction:properties.globalValidation.unauthenticatedClientAction,"
    "excludedPaths:properties.globalValidation.excludedPaths,"
    "requireHttps:properties.httpSettings.requireHttps,"
    "entraEnabled:properties.identityProviders.azureActiveDirectory.enabled,"
    "clientId:properties.identityProviders.azureActiveDirectory.registration.clientId,"
    "openIdIssuer:properties.identityProviders.azureActiveDirectory.registration.openIdIssuer}"
)
AUTH_FIELDS = {
    "platformEnabled",
    "requireAuthentication",
    "unauthenticatedClientAction",
    "excludedPaths",
    "requireHttps",
    "entraEnabled",
    "clientId",
    "openIdIssuer",
}
WEB_APP_QUERY = (
    "{defaultHostName:defaultHostName,httpsOnly:httpsOnly,id:id,name:name,"
    "resourceGroup:resourceGroup,location:location,kind:kind,"
    "serverFarmId:serverFarmId,tags:tags,identityType:identity.type}"
)
APP_SETTINGS_SNAPSHOT_QUERY = "[].{name:name,value:value}"
SESSION_FIELDS = {
    "AZURE_RESOURCE_GROUP",
    "AZURE_LOCATION",
    "AZURE_REQUESTED_FOUNDRY_ACCOUNT_NAME",
    "AZURE_FOUNDRY_ACCOUNT_NAME",
    "AZURE_FOUNDRY_PROJECT_NAME",
    "AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT",
    "AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT_NAME",
    "AZURE_AI_FOUNDRY_AGENT_NAME",
    "AZURE_AI_FOUNDRY_AGENT_VERSION",
    "AZURE_AI_FOUNDRY_AGENT_ENDPOINT",
    "AZURE_WEB_APP_NAME",
    "AZURE_WEB_APP_ORIGIN",
}

AcceptanceCategory = Literal[
    "success",
    "invalid_configuration",
    "current_generation_invalid",
    "local_contract_invalid",
    "current_environment_verification_failed",
    "current_configuration_ambiguous",
    "authentication_already_enabled",
    "artifact_evidence_invalid",
    "preview_failed",
    "unexpected_preview_changes",
    "operator_declined",
    "approval_evidence_stale",
    "deployment_failed",
    "configuration_verification_failed",
    "anonymous_http_acceptance_failed",
    "hosted_readiness_failed",
    "unexpected_error",
]
AuthenticationPreviewRejectionReason = Literal[
    "preview_command_failed",
    "preview_parse_failed",
    "topology_mismatch",
    "identity_not_proven",
    "action_not_allowed",
]
AuthenticationPreviewAction = Literal[
    "Create",
    "Modify",
    "NoChange",
    "Delete",
    "Ignore",
    "Deploy",
    "Unsupported",
]
AuthenticationConfigurationShapeField = Literal[
    "response",
    "platform_enabled",
    "require_authentication",
    "unauthenticated_client_action",
    "excluded_paths",
    "require_https",
    "entra_enabled",
    "client_id",
    "open_id_issuer",
]
AuthenticationConfigurationShapeReason = Literal[
    "missing",
    "null_not_allowed",
    "wrong_scalar_type",
    "wrong_object_type",
    "wrong_list_type",
    "wrong_list_item_type",
    "unsupported_shape",
]
AuthenticationConfigurationExpectedType = Literal[
    "boolean",
    "string",
    "list",
    "object",
]
AUTHENTICATION_CONFIGURATION_SHAPE_FIELDS = frozenset(
    {
        "response",
        "platform_enabled",
        "require_authentication",
        "unauthenticated_client_action",
        "excluded_paths",
        "require_https",
        "entra_enabled",
        "client_id",
        "open_id_issuer",
    }
)
AUTHENTICATION_CONFIGURATION_SHAPE_REASONS = frozenset(
    {
        "missing",
        "null_not_allowed",
        "wrong_scalar_type",
        "wrong_object_type",
        "wrong_list_type",
        "wrong_list_item_type",
        "unsupported_shape",
    }
)
AUTHENTICATION_CONFIGURATION_EXPECTED_TYPES = frozenset(
    {"boolean", "string", "list", "object"}
)
AUTHENTICATION_CONFIGURATION_FIELD_SPECS: tuple[
    tuple[
        AuthenticationConfigurationShapeField,
        str,
        AuthenticationConfigurationExpectedType,
    ],
    ...,
] = (
    ("platform_enabled", "platformEnabled", "boolean"),
    ("require_authentication", "requireAuthentication", "boolean"),
    (
        "unauthenticated_client_action",
        "unauthenticatedClientAction",
        "string",
    ),
    ("excluded_paths", "excludedPaths", "list"),
    ("require_https", "requireHttps", "boolean"),
    ("entra_enabled", "entraEnabled", "boolean"),
    ("client_id", "clientId", "string"),
    ("open_id_issuer", "openIdIssuer", "string"),
)
AUTHENTICATION_PREVIEW_ACTIONS: tuple[AuthenticationPreviewAction, ...] = (
    "Create",
    "Modify",
    "NoChange",
    "Delete",
    "Ignore",
    "Deploy",
    "Unsupported",
)
AUTHENTICATION_PREVIEW_REJECTION_REASONS = frozenset(
    {
        "preview_command_failed",
        "preview_parse_failed",
        "topology_mismatch",
        "identity_not_proven",
        "action_not_allowed",
    }
)


class AzureCliRunner(Protocol):
    def run(self, args: list[str]) -> CommandResult: ...


@dataclass(frozen=True)
class CurrentGenerationBinding:
    configuration_fingerprint: str = field(repr=False)
    correlation_fingerprint: str = field(repr=False)
    run_epoch: str = field(repr=False)
    resource_group: str = field(repr=False)
    web_app_name: str = field(repr=False)
    hosted_origin: str = field(repr=False)
    current_day_verified: bool


@dataclass(frozen=True)
class AuthenticationAcceptanceRequest:
    subscription_name: str = field(repr=False)
    resource_group: str = field(repr=False)
    location: str
    environment_name: str
    project_name: str
    web_app_name: str = field(repr=False)
    hosted_origin: str = field(repr=False)
    client_application_id: str = field(repr=False)
    tenant_id: str = field(repr=False)
    hosted_verifier_project_endpoint: str = field(repr=False)
    hosted_verifier_stable_agent_endpoint: str = field(repr=False)
    hosted_verifier_agent_name: str
    hosted_verifier_agent_version: str
    hosted_verifier_model_deployment_name: str
    template_file: Path
    generation: CurrentGenerationBinding = field(repr=False)


@dataclass(frozen=True)
class AuthenticationConfigurationEvidence:
    enabled: bool
    fingerprint: str = field(repr=False)
    authentication_required_verified: bool = False
    https_required_verified: bool = False
    unauthenticated_action_verified: bool = False
    anonymous_exclusions_verified: bool = False
    entra_provider_verified: bool = False
    application_binding_verified: bool = False
    tenant_binding_verified: bool = False


@dataclass(frozen=True)
class AuthenticationConfigurationShapeDiagnostic:
    field: AuthenticationConfigurationShapeField
    reason: AuthenticationConfigurationShapeReason
    expected_type: AuthenticationConfigurationExpectedType

    def __post_init__(self) -> None:
        expected_types = {
            field_name: expected_type
            for field_name, _, expected_type in AUTHENTICATION_CONFIGURATION_FIELD_SPECS
        }
        expected_types["response"] = "object"
        if (
            self.field not in AUTHENTICATION_CONFIGURATION_SHAPE_FIELDS
            or self.reason not in AUTHENTICATION_CONFIGURATION_SHAPE_REASONS
            or self.expected_type not in AUTHENTICATION_CONFIGURATION_EXPECTED_TYPES
            or expected_types.get(self.field) != self.expected_type
            or (
                self.field == "response"
                and self.reason not in {"wrong_object_type", "unsupported_shape"}
            )
            or (
                self.field != "response"
                and self.reason in {"wrong_object_type", "unsupported_shape"}
            )
            or (
                self.reason in {"wrong_list_type", "wrong_list_item_type"}
                and self.expected_type != "list"
            )
            or (
                self.reason == "wrong_scalar_type"
                and self.expected_type not in {"boolean", "string"}
            )
        ):
            raise ValueError("Invalid Authentication configuration shape diagnostic.")

    def to_json_dict(self) -> dict[str, str]:
        return {
            "field": self.field,
            "reason": self.reason,
            "expected_type": self.expected_type,
        }


@dataclass(frozen=True)
class CurrentAzureEvidence:
    subscription_id: str = field(repr=False)
    login_endpoint: str = field(repr=False)
    web_app_resource_id: str = field(repr=False)
    hostname: str = field(repr=False)
    configuration: AuthenticationConfigurationEvidence = field(repr=False)
    fingerprint: str = field(repr=False)


@dataclass(frozen=True)
class AuthenticationApprovalSummary:
    current_web_app_verified: bool
    application_identifier_validated: bool
    tenant_identifier_validated: bool
    authentication_enablement_required: bool
    anonymous_readiness_exclusions: int
    unrelated_resource_changes: int


@dataclass(frozen=True)
class PreparedAuthenticationTemplate:
    path: Path = field(repr=False)
    digest: str = field(repr=False)


@dataclass(frozen=True)
class AuthenticationPreviewUnexpectedChangeCount:
    action: AuthenticationPreviewAction
    resource_family: AzureResourceFamily
    provider_family: AzureProviderFamily | None
    count: int

    def __post_init__(self) -> None:
        if (
            self.action not in AUTHENTICATION_PREVIEW_ACTIONS
            or self.resource_family not in AZURE_RESOURCE_FAMILIES
            or (
                self.provider_family is not None
                and self.provider_family not in AZURE_PROVIDER_FAMILIES
            )
            or (self.resource_family != "unknown" and self.provider_family is not None)
            or type(self.count) is not int
            or self.count < 1
        ):
            raise ValueError("Invalid Authentication preview family count.")

    def to_json_dict(self) -> dict[str, object]:
        return {
            "action": self.action,
            "resource_family": self.resource_family,
            "provider_family": self.provider_family,
            "count": self.count,
        }


@dataclass(frozen=True)
class AuthenticationPreviewDiagnostic:
    reason: AuthenticationPreviewRejectionReason
    record_count: int | None = None
    create_count: int | None = None
    modify_count: int | None = None
    no_change_count: int | None = None
    delete_count: int | None = None
    ignore_count: int | None = None
    deploy_count: int | None = None
    unsupported_count: int | None = None
    authentication_resource_count: int | None = None
    unexpected_resource_count: int | None = None
    expected_web_app_relationship_proven: bool = False
    exact_identity_scope_proven: bool = False
    expected_multiplicity_proven: bool = False
    malformed_or_unsupported_evidence_present: bool = False
    authentication_action: AuthenticationPreviewAction | None = None
    unexpected_change_counts: tuple[
        AuthenticationPreviewUnexpectedChangeCount,
        ...,
    ] = ()

    def __post_init__(self) -> None:
        counts = (
            self.record_count,
            self.create_count,
            self.modify_count,
            self.no_change_count,
            self.delete_count,
            self.ignore_count,
            self.deploy_count,
            self.unsupported_count,
            self.authentication_resource_count,
            self.unexpected_resource_count,
        )
        if (
            self.reason not in AUTHENTICATION_PREVIEW_REJECTION_REASONS
            or any(
                value is not None
                and (type(value) is not int or value < 0)
                for value in counts
            )
            or any(
                type(value) is not bool
                for value in (
                    self.expected_web_app_relationship_proven,
                    self.exact_identity_scope_proven,
                    self.expected_multiplicity_proven,
                    self.malformed_or_unsupported_evidence_present,
                )
            )
        ):
            raise ValueError("Invalid Authentication preview diagnostic.")
        if (
            (
                self.authentication_action is not None
                and self.authentication_action not in AUTHENTICATION_PREVIEW_ACTIONS
            )
            or any(
                not isinstance(item, AuthenticationPreviewUnexpectedChangeCount)
                for item in self.unexpected_change_counts
            )
            or len(
                {
                    (item.action, item.resource_family, item.provider_family)
                    for item in self.unexpected_change_counts
                }
            )
            != len(self.unexpected_change_counts)
        ):
            raise ValueError("Invalid Authentication preview classification.")
        action_counts = counts[1:8]
        resource_counts = counts[8:10]
        if self.record_count is None:
            if (
                any(value is not None for value in (*action_counts, *resource_counts))
                or self.authentication_action is not None
                or self.unexpected_change_counts
            ):
                raise ValueError("Unparsed preview diagnostic contains counts.")
        elif (
            any(value is None for value in (*action_counts, *resource_counts))
            or sum(action_counts) != self.record_count
            or sum(resource_counts) != self.record_count
            or (self.authentication_resource_count == 1)
            is not (self.authentication_action is not None)
            or sum(item.count for item in self.unexpected_change_counts)
            != self.unexpected_resource_count
        ):
            raise ValueError("Parsed preview diagnostic counts disagree.")

    def to_json_dict(self) -> dict[str, object]:
        return {
            "reason": self.reason,
            "record_count": self.record_count,
            "create_count": self.create_count,
            "modify_count": self.modify_count,
            "no_change_count": self.no_change_count,
            "delete_count": self.delete_count,
            "ignore_count": self.ignore_count,
            "deploy_count": self.deploy_count,
            "unsupported_count": self.unsupported_count,
            "authentication_resource_count": self.authentication_resource_count,
            "unexpected_resource_count": self.unexpected_resource_count,
            "expected_web_app_relationship_proven": (
                self.expected_web_app_relationship_proven
            ),
            "exact_identity_scope_proven": self.exact_identity_scope_proven,
            "expected_multiplicity_proven": self.expected_multiplicity_proven,
            "malformed_or_unsupported_evidence_present": (
                self.malformed_or_unsupported_evidence_present
            ),
            "authentication_action": self.authentication_action,
            "unexpected_change_counts": [
                item.to_json_dict() for item in self.unexpected_change_counts
            ],
        }


@dataclass(frozen=True)
class AuthenticationPreviewEvaluation:
    accepted_summary: SanitizedWhatIfSummary | None = field(
        default=None,
        repr=False,
    )
    fingerprint: str | None = field(default=None, repr=False)
    diagnostic: AuthenticationPreviewDiagnostic | None = None

    def __post_init__(self) -> None:
        accepted = self.accepted_summary is not None and self.fingerprint is not None
        rejected = (
            self.accepted_summary is None
            and self.fingerprint is None
            and self.diagnostic is not None
        )
        if accepted is rejected or (accepted and self.diagnostic is not None):
            raise ValueError("Invalid Authentication preview evaluation.")


@dataclass(frozen=True)
class AuthenticationAcceptanceResult:
    ok: bool
    category: AcceptanceCategory
    operation: str = OPERATION
    mode: str = "live"
    current_generation_verified: bool = False
    local_contract_validated: bool = False
    current_web_app_verified: bool = False
    current_configuration_evidence_verified: bool = False
    preview_verified: bool = False
    operator_approved: bool = False
    authentication_enabled: bool = False
    entra_provider_verified: bool = False
    tenant_binding_verified: bool = False
    application_binding_verified: bool = False
    unauthenticated_action_verified: bool = False
    anonymous_exclusions_verified: bool = False
    deployment_attempted: bool = False
    deployment_accepted: bool = False
    configuration_verified: bool = False
    anonymous_readiness_routes_verified: bool = False
    protected_routes_verified: bool = False
    hosted_readiness_verified: bool = False
    authenticated_sign_in_verified: bool = False
    azure_operation_attempted: bool = False
    azure_mutation_made: bool | None = False
    preview_diagnostic: AuthenticationPreviewDiagnostic | None = None
    configuration_shape_diagnostic: (
        AuthenticationConfigurationShapeDiagnostic | None
    ) = None
    recommended_next_step: str = (
        "Review the sanitized category before a separate explicit run."
    )

    @classmethod
    def failure(
        cls,
        category: AcceptanceCategory,
        **progress: object,
    ) -> "AuthenticationAcceptanceResult":
        return cls(ok=False, category=category, **progress)

    @classmethod
    def check_success(cls) -> "AuthenticationAcceptanceResult":
        return cls(
            ok=True,
            category="success",
            mode="check",
            current_generation_verified=True,
            local_contract_validated=True,
            recommended_next_step=(
                "Run the supervised live acceptance only for the current READY generation."
            ),
        )

    @classmethod
    def live_success(cls) -> "AuthenticationAcceptanceResult":
        return cls(
            ok=True,
            category="success",
            current_generation_verified=True,
            local_contract_validated=True,
            current_web_app_verified=True,
            current_configuration_evidence_verified=True,
            preview_verified=True,
            operator_approved=True,
            authentication_enabled=True,
            entra_provider_verified=True,
            tenant_binding_verified=True,
            application_binding_verified=True,
            unauthenticated_action_verified=True,
            anonymous_exclusions_verified=True,
            deployment_attempted=True,
            deployment_accepted=True,
            configuration_verified=True,
            anonymous_readiness_routes_verified=True,
            protected_routes_verified=True,
            hosted_readiness_verified=True,
            authenticated_sign_in_verified=False,
            azure_operation_attempted=True,
            azure_mutation_made=True,
            recommended_next_step=(
                "Treat supervised authenticated sign-in as a separate optional proof; "
                "application authorization remains deferred."
            ),
        )

    def to_json_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "ok": self.ok,
            "category": self.category,
            "operation": self.operation,
            "mode": self.mode,
            "current_generation_verified": self.current_generation_verified,
            "local_contract_validated": self.local_contract_validated,
            "current_web_app_verified": self.current_web_app_verified,
            "current_configuration_evidence_verified": (
                self.current_configuration_evidence_verified
            ),
            "preview_verified": self.preview_verified,
            "operator_approved": self.operator_approved,
            "authentication_enabled": self.authentication_enabled,
            "entra_provider_verified": self.entra_provider_verified,
            "tenant_binding_verified": self.tenant_binding_verified,
            "application_binding_verified": self.application_binding_verified,
            "unauthenticated_action_verified": (
                self.unauthenticated_action_verified
            ),
            "anonymous_exclusions_verified": self.anonymous_exclusions_verified,
            "deployment_attempted": self.deployment_attempted,
            "deployment_accepted": self.deployment_accepted,
            "configuration_verified": self.configuration_verified,
            "anonymous_readiness_routes_verified": (
                self.anonymous_readiness_routes_verified
            ),
            "protected_routes_verified": self.protected_routes_verified,
            "hosted_readiness_verified": self.hosted_readiness_verified,
            "authenticated_sign_in_verified": self.authenticated_sign_in_verified,
            "azure_operation_attempted": self.azure_operation_attempted,
            "azure_mutation_made": self.azure_mutation_made,
            "recommended_next_step": self.recommended_next_step,
        }
        if self.preview_diagnostic is not None:
            result["preview_diagnostic"] = self.preview_diagnostic.to_json_dict()
        if self.configuration_shape_diagnostic is not None:
            result["configuration_shape_diagnostic"] = (
                self.configuration_shape_diagnostic.to_json_dict()
            )
        return result


def _fingerprint(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def _generation_valid(binding: object) -> bool:
    if not isinstance(binding, CurrentGenerationBinding):
        return False
    try:
        normalized_origin = normalize_web_app_base_url(binding.hosted_origin)
    except (ValueError, TypeError):
        return False
    return bool(
        HEX_64.fullmatch(binding.configuration_fingerprint)
        and HEX_64.fullmatch(binding.correlation_fingerprint)
        and RUN_EPOCH.fullmatch(binding.run_epoch)
        and binding.resource_group
        and binding.web_app_name
        and binding.current_day_verified is True
        and normalized_origin == binding.hosted_origin
    )


def _infra_request(
    request: AuthenticationAcceptanceRequest,
    mode: str,
) -> WebAppInfrastructureDeploymentRequest:
    return WebAppInfrastructureDeploymentRequest(
        mode=mode,
        resource_group=request.resource_group,
        location=request.location,
        environment_name=request.environment_name,
        project_name=request.project_name,
        web_app_name=request.web_app_name,
        cosmos_database_name="nurse-intake",
        cosmos_container_name="cases",
        template_file=request.template_file,
        enable_app_service_authentication=True,
        app_service_authentication_client_id=request.client_application_id,
        app_service_authentication_tenant_id=request.tenant_id,
        purpose="web_app_authentication",
    )


def check_authentication_acceptance_request(
    request: object,
) -> AuthenticationAcceptanceResult:
    if not isinstance(request, AuthenticationAcceptanceRequest):
        return AuthenticationAcceptanceResult.failure(
            "invalid_configuration",
            mode="check",
        )
    authentication = {
        "mode": "enabled",
        "clientId": request.client_application_id,
        "tenantId": request.tenant_id,
    }
    hosted = {
        "AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT": (
            request.hosted_verifier_project_endpoint
        ),
        "AZURE_AI_FOUNDRY_AGENT_ENDPOINT": (
            request.hosted_verifier_stable_agent_endpoint
        ),
        "AZURE_AI_FOUNDRY_AGENT_NAME": request.hosted_verifier_agent_name,
        "AZURE_AI_FOUNDRY_AGENT_VERSION": request.hosted_verifier_agent_version,
        "AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT_NAME": (
            request.hosted_verifier_model_deployment_name
        ),
    }
    try:
        origin = normalize_web_app_base_url(request.hosted_origin)
    except (ValueError, TypeError):
        origin = None
    if (
        not _generation_valid(request.generation)
        or request.resource_group != request.generation.resource_group
        or request.web_app_name != request.generation.web_app_name
        or request.hosted_origin != request.generation.hosted_origin
        or origin != request.hosted_origin
        or not app_service_authentication_configuration_valid(authentication)
        or not hosted_verifier_settings_valid(hosted)
    ):
        return AuthenticationAcceptanceResult.failure(
            "invalid_configuration",
            mode="check",
        )
    local = check_web_app_authentication_contract(
        authentication,
        template_file=request.template_file,
    )
    infrastructure = validate_web_app_infrastructure_request(
        _infra_request(request, "check")
    )
    if not local.ok or infrastructure is not None:
        return AuthenticationAcceptanceResult.failure(
            "local_contract_invalid",
            mode="check",
            current_generation_verified=True,
        )
    return AuthenticationAcceptanceResult.check_success()


def _parse_json_object(
    value: str,
    expected_fields: set[str],
) -> dict[str, object] | None:
    try:
        payload = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return (
        payload
        if isinstance(payload, dict) and set(payload) == expected_fields
        else None
    )


def _parse_app_settings_snapshot(value: str) -> tuple[tuple[str, str], ...] | None:
    try:
        payload = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, list):
        return None
    settings: dict[str, str] = {}
    for item in payload:
        if (
            not isinstance(item, dict)
            or set(item) != {"name", "value"}
            or not isinstance(item.get("name"), str)
            or not isinstance(item.get("value"), str)
            or item["name"] in settings
        ):
            return None
        settings[item["name"]] = item["value"]
    return tuple(sorted(settings.items()))


def _parse_disabled_authentication_evidence(
    stdout: str,
) -> AuthenticationConfigurationEvidence | None:
    payload = _parse_json_object(stdout, AUTH_FIELDS)
    if payload is None:
        return None
    if all(value is None for value in payload.values()):
        return AuthenticationConfigurationEvidence(
            enabled=False,
            fingerprint=_fingerprint(payload),
        )
    lists_valid = bool(
        isinstance(payload["excludedPaths"], list)
        and all(isinstance(item, str) for item in payload["excludedPaths"])
    )
    scalar_types_valid = bool(
        all(
            payload[name] is None or type(payload[name]) is expected
            for name, expected in (
                ("platformEnabled", bool),
                ("requireAuthentication", bool),
                ("requireHttps", bool),
                ("entraEnabled", bool),
                ("unauthenticatedClientAction", str),
                ("clientId", str),
                ("openIdIssuer", str),
            )
        )
    )
    if not lists_valid or not scalar_types_valid or payload["platformEnabled"] is not False:
        return None
    return AuthenticationConfigurationEvidence(
        enabled=False,
        fingerprint=_fingerprint(payload),
    )


def diagnose_authentication_configuration_shape(
    stdout: str,
) -> AuthenticationConfigurationShapeDiagnostic | None:
    try:
        payload = json.loads(stdout)
    except (TypeError, ValueError, json.JSONDecodeError):
        return AuthenticationConfigurationShapeDiagnostic(
            field="response",
            reason="unsupported_shape",
            expected_type="object",
        )
    if not isinstance(payload, dict):
        return AuthenticationConfigurationShapeDiagnostic(
            field="response",
            reason="wrong_object_type",
            expected_type="object",
        )
    for field_name, projected_name, expected_type in (
        AUTHENTICATION_CONFIGURATION_FIELD_SPECS
    ):
        if projected_name not in payload:
            return AuthenticationConfigurationShapeDiagnostic(
                field=field_name,
                reason="missing",
                expected_type=expected_type,
            )
    if set(payload) != AUTH_FIELDS:
        return AuthenticationConfigurationShapeDiagnostic(
            field="response",
            reason="unsupported_shape",
            expected_type="object",
        )
    for field_name, projected_name, expected_type in (
        AUTHENTICATION_CONFIGURATION_FIELD_SPECS
    ):
        value = payload[projected_name]
        if value is None:
            return AuthenticationConfigurationShapeDiagnostic(
                field=field_name,
                reason="null_not_allowed",
                expected_type=expected_type,
            )
        if expected_type == "list":
            if not isinstance(value, list):
                return AuthenticationConfigurationShapeDiagnostic(
                    field=field_name,
                    reason="wrong_list_type",
                    expected_type=expected_type,
                )
            if any(type(item) is not str for item in value):
                return AuthenticationConfigurationShapeDiagnostic(
                    field=field_name,
                    reason="wrong_list_item_type",
                    expected_type=expected_type,
                )
        elif expected_type == "boolean" and type(value) is not bool:
            return AuthenticationConfigurationShapeDiagnostic(
                field=field_name,
                reason="wrong_scalar_type",
                expected_type=expected_type,
            )
        elif expected_type == "string" and type(value) is not str:
            return AuthenticationConfigurationShapeDiagnostic(
                field=field_name,
                reason="wrong_scalar_type",
                expected_type=expected_type,
            )
    return None


def parse_authentication_configuration_evidence(
    stdout: str,
    *,
    expected_client_id: str,
    expected_tenant_id: str,
    expected_login_endpoint: str,
) -> AuthenticationConfigurationEvidence | None:
    if diagnose_authentication_configuration_shape(stdout) is not None:
        return None
    payload = _parse_json_object(stdout, AUTH_FIELDS)
    if payload is None:
        return None
    expected_issuer = (
        f"{expected_login_endpoint.rstrip('/')}/{expected_tenant_id}/v2.0"
    )
    if payload != {
        "platformEnabled": True,
        "requireAuthentication": True,
        "unauthenticatedClientAction": "Return401",
        "excludedPaths": list(APP_SERVICE_AUTHENTICATION_ANONYMOUS_PATHS),
        "requireHttps": True,
        "entraEnabled": True,
        "clientId": expected_client_id,
        "openIdIssuer": expected_issuer,
    }:
        return None
    return AuthenticationConfigurationEvidence(
        enabled=True,
        fingerprint=_fingerprint(payload),
        authentication_required_verified=True,
        https_required_verified=True,
        unauthenticated_action_verified=True,
        anonymous_exclusions_verified=True,
        entra_provider_verified=True,
        application_binding_verified=True,
        tenant_binding_verified=True,
    )


def _safe_login_endpoint(value: str) -> str | None:
    candidate = value.strip()
    try:
        parsed = urlsplit(candidate)
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme != "https"
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
        or not SAFE_HOST.fullmatch(parsed.hostname.casefold())
    ):
        return None
    return f"https://{parsed.hostname.casefold()}/"


def _read_authentication_stdout(
    runner: AzureCliRunner,
    request: AuthenticationAcceptanceRequest,
) -> str | None:
    outcome = runner.run(
        [
            "az",
            "resource",
            "show",
            "--resource-group",
            request.resource_group,
            "--namespace",
            "Microsoft.Web",
            "--parent",
            f"sites/{request.web_app_name}",
            "--resource-type",
            "config",
            "--name",
            "authsettingsV2",
            "--api-version",
            "2024-04-01",
            "--query",
            AUTH_QUERY,
            "--output",
            "json",
            "--only-show-errors",
        ]
    )
    return outcome.stdout if outcome.return_code == 0 else None


def _read_current_azure_evidence(
    runner: AzureCliRunner,
    request: AuthenticationAcceptanceRequest,
) -> CurrentAzureEvidence | None:
    account = runner.run(
        [
            "az",
            "account",
            "show",
            "--query",
            "{environmentName:environmentName,id:id,name:name,tenantId:tenantId}",
            "--output",
            "json",
            "--only-show-errors",
        ]
    )
    account_payload = (
        _parse_json_object(
            account.stdout,
            {"environmentName", "id", "name", "tenantId"},
        )
        if account.return_code == 0
        else None
    )
    if (
        account_payload is None
        or account_payload["name"] != request.subscription_name
        or account_payload["tenantId"] != request.tenant_id
        or not isinstance(account_payload["id"], str)
        or GUID.fullmatch(account_payload["id"]) is None
        or not isinstance(account_payload["environmentName"], str)
        or SAFE_ENVIRONMENT_NAME.fullmatch(account_payload["environmentName"])
        is None
    ):
        return None
    subscription_id = account_payload["id"]
    environment_name = account_payload["environmentName"]
    assert isinstance(subscription_id, str)
    assert isinstance(environment_name, str)
    cloud = runner.run(
        [
            "az",
            "cloud",
            "show",
            "--name",
            environment_name,
            "--query",
            "endpoints.activeDirectory",
            "--output",
            "tsv",
            "--only-show-errors",
        ]
    )
    login_endpoint = (
        _safe_login_endpoint(cloud.stdout) if cloud.return_code == 0 else None
    )
    if login_endpoint is None:
        return None
    web_app = runner.run(
        [
            "az",
            "webapp",
            "show",
            "--resource-group",
            request.resource_group,
            "--name",
            request.web_app_name,
            "--query",
            WEB_APP_QUERY,
            "--output",
            "json",
            "--only-show-errors",
        ]
    )
    web_payload = (
        _parse_json_object(
            web_app.stdout,
            {
                "defaultHostName",
                "httpsOnly",
                "id",
                "name",
                "resourceGroup",
                "location",
                "kind",
                "serverFarmId",
                "tags",
                "identityType",
            },
        )
        if web_app.return_code == 0
        else None
    )
    if web_payload is None:
        return None
    expected_id = (
        f"/subscriptions/{subscription_id}/resourceGroups/{request.resource_group}/"
        f"providers/Microsoft.Web/sites/{request.web_app_name}"
    )
    hostname = web_payload["defaultHostName"]
    kind = web_payload["kind"]
    location = web_payload["location"]
    server_farm_id = web_payload["serverFarmId"]
    tags = web_payload["tags"]
    if (
        web_payload["httpsOnly"] is not True
        or web_payload["id"] != expected_id
        or web_payload["name"] != request.web_app_name
        or web_payload["resourceGroup"] != request.resource_group
        or not isinstance(hostname, str)
        or SAFE_HOST.fullmatch(hostname.casefold()) is None
        or f"https://{hostname.casefold()}" != request.hosted_origin
        or not isinstance(location, str)
        or not location
        or location != location.strip()
        or not isinstance(kind, str)
        or {part.strip().casefold() for part in kind.split(",")}
        != {"app", "linux"}
        or web_payload["identityType"] != "SystemAssigned"
        or not isinstance(server_farm_id, str)
        or re.fullmatch(
            re.escape(
                f"/subscriptions/{subscription_id}/resourceGroups/"
                f"{request.resource_group}/providers/Microsoft.Web/serverfarms/"
            )
            + r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?",
            server_farm_id,
            re.IGNORECASE,
        )
        is None
        or not isinstance(tags, dict)
        or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in tags.items()
        )
    ):
        return None
    site_config = runner.run(
        [
            "az",
            "webapp",
            "config",
            "show",
            "--resource-group",
            request.resource_group,
            "--name",
            request.web_app_name,
            "--query",
            SITE_CONFIG_QUERY,
            "--output",
            "json",
            "--only-show-errors",
        ]
    )
    site_config_payload = (
        _parse_json_object(
            site_config.stdout,
            {
                "linuxFxVersion",
                "appCommandLine",
                "ftpsState",
                "minTlsVersion",
                "scmMinTlsVersion",
                "healthCheckPath",
                "alwaysOn",
            },
        )
        if site_config.return_code == 0
        else None
    )
    if site_config_payload != {
        "linuxFxVersion": EXPECTED_LINUX_FX_VERSION,
        "appCommandLine": EXPECTED_STARTUP_COMMAND,
        "ftpsState": "Disabled",
        "minTlsVersion": "1.2",
        "scmMinTlsVersion": "1.2",
        "healthCheckPath": EXPECTED_HEALTH_CHECK_PATH,
        "alwaysOn": ALWAYS_ON_REQUIRED,
    }:
        return None
    app_settings = runner.run(
        [
            "az",
            "webapp",
            "config",
            "appsettings",
            "list",
            "--resource-group",
            request.resource_group,
            "--name",
            request.web_app_name,
            "--query",
            APP_SETTINGS_SNAPSHOT_QUERY,
            "--output",
            "json",
            "--only-show-errors",
        ]
    )
    app_settings_snapshot = (
        _parse_app_settings_snapshot(app_settings.stdout)
        if app_settings.return_code == 0
        else None
    )
    expected_settings = {
        **BASELINE_APP_SETTINGS,
        "AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT": (
            request.hosted_verifier_project_endpoint
        ),
        "AZURE_AI_FOUNDRY_AGENT_ENDPOINT": (
            request.hosted_verifier_stable_agent_endpoint
        ),
        "AZURE_AI_FOUNDRY_AGENT_NAME": request.hosted_verifier_agent_name,
        "AZURE_AI_FOUNDRY_AGENT_VERSION": request.hosted_verifier_agent_version,
        "AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT_NAME": (
            request.hosted_verifier_model_deployment_name
        ),
    }
    if app_settings_snapshot != tuple(sorted(expected_settings.items())):
        return None
    authentication_stdout = _read_authentication_stdout(runner, request)
    configuration = (
        _parse_disabled_authentication_evidence(authentication_stdout)
        if authentication_stdout is not None
        else None
    )
    if configuration is None:
        return None
    private_values = {
        "subscription_id": subscription_id,
        "login_endpoint": login_endpoint,
        "web_app_resource_id": expected_id,
        "hostname": hostname.casefold(),
        "web_app": web_payload,
        "site_config": site_config_payload,
        "app_settings": app_settings_snapshot,
        "configuration": configuration.fingerprint,
    }
    return CurrentAzureEvidence(
        subscription_id=subscription_id,
        login_endpoint=login_endpoint,
        web_app_resource_id=expected_id,
        hostname=hostname.casefold(),
        configuration=configuration,
        fingerprint=_fingerprint(private_values),
    )


class _CapturingRunner:
    def __init__(self, runner: AzureCliRunner) -> None:
        self.runner = runner
        self.outcome: CommandResult | None = None

    def run(self, args: list[str]) -> CommandResult:
        self.outcome = self.runner.run(args)
        return self.outcome


def _authentication_preview_diagnostic(
    reason: AuthenticationPreviewRejectionReason,
    parsed: SanitizedWhatIfSummary | None = None,
) -> AuthenticationPreviewDiagnostic:
    if parsed is None:
        return AuthenticationPreviewDiagnostic(
            reason=reason,
            malformed_or_unsupported_evidence_present=(
                reason == "preview_parse_failed"
            ),
        )
    authentication = tuple(
        change
        for change in parsed.changes
        if change.logical_category == "web_app_authentication"
    )
    unexpected_resource_count = len(parsed.changes) - len(authentication)
    expected_multiplicity_proven = bool(
        len(parsed.changes) == 1 and len(authentication) == 1
    )
    unexpected_counts: Counter[
        tuple[
            AuthenticationPreviewAction,
            AzureResourceFamily,
            AzureProviderFamily | None,
        ]
    ] = Counter()
    for change in parsed.changes:
        if change.logical_category == "web_app_authentication":
            continue
        family = (
            "web_site"
            if change.logical_category == "web_app"
            else change.unexpected_resource_family
            if change.unexpected_resource_family in AZURE_RESOURCE_FAMILIES
            else "unknown"
        )
        provider = (
            change.unexpected_resource_provider_family
            if family == "unknown"
            and change.unexpected_resource_provider_family
            in AZURE_PROVIDER_FAMILIES
            else None
        )
        unexpected_counts[(change.action, family, provider)] += 1
    unexpected_change_counts = tuple(
        AuthenticationPreviewUnexpectedChangeCount(
            action=action,
            resource_family=family,
            provider_family=provider,
            count=unexpected_counts[(action, family, provider)],
        )
        for action in AUTHENTICATION_PREVIEW_ACTIONS
        for family in AZURE_RESOURCE_FAMILIES
        for provider in (*AZURE_PROVIDER_FAMILIES, None)
        if unexpected_counts[(action, family, provider)]
    )
    return AuthenticationPreviewDiagnostic(
        reason=reason,
        record_count=len(parsed.changes),
        create_count=parsed.count("Create"),
        modify_count=parsed.count("Modify"),
        no_change_count=parsed.count("NoChange"),
        delete_count=parsed.count("Delete"),
        ignore_count=parsed.count("Ignore"),
        deploy_count=parsed.count("Deploy"),
        unsupported_count=parsed.count("Unsupported"),
        authentication_resource_count=len(authentication),
        unexpected_resource_count=unexpected_resource_count,
        expected_web_app_relationship_proven=bool(
            len(authentication) == 1
            and authentication[0].expected_parent_match
        ),
        exact_identity_scope_proven=bool(
            len(authentication) == 1
            and authentication[0].expected_identity_match
            and authentication[0].expected_scope_match
        ),
        expected_multiplicity_proven=expected_multiplicity_proven,
        malformed_or_unsupported_evidence_present=bool(
            parsed.count("Unsupported")
        ),
        authentication_action=(
            authentication[0].action if len(authentication) == 1 else None
        ),
        unexpected_change_counts=unexpected_change_counts,
    )


def _authentication_preview(
    request: AuthenticationAcceptanceRequest,
    runner: AzureCliRunner,
    deployment_template: PreparedAuthenticationTemplate,
) -> AuthenticationPreviewEvaluation:
    outcome = runner.run(
        _authentication_deployment_command(
            request,
            "what-if",
            deployment_template,
        )
    )
    if outcome.return_code != 0:
        return AuthenticationPreviewEvaluation(
            diagnostic=_authentication_preview_diagnostic(
                "preview_command_failed"
            )
        )
    expected = (
        ExpectedWhatIfResource(
            "Microsoft.Web/sites/config",
            "web_app_authentication",
            request.resource_group,
            (request.web_app_name, "authsettingsV2"),
        ),
    )
    parsed = parse_sanitized_what_if(
        outcome.stdout,
        boundary="web_app_authentication_acceptance",
        expected_resources=expected,
        automatically_approved_actions=frozenset({"Create", "Modify"}),
    )
    if parsed is None:
        return AuthenticationPreviewEvaluation(
            diagnostic=_authentication_preview_diagnostic(
                "preview_parse_failed"
            )
        )
    authentication = tuple(
        change
        for change in parsed.changes
        if change.logical_category == "web_app_authentication"
    )
    infrastructure = parse_web_app_infrastructure_what_if(
        outcome.stdout,
        _infra_request(request, "what-if"),
    )
    accepted = bool(
        infrastructure is not None
        and infrastructure.exact_topology_match
        and parsed.exact_topology_match
        and parsed.all_changes_allowlisted
        and len(parsed.changes) == 1
        and len(authentication) == 1
        and authentication[0].action in {"Create", "Modify"}
        and not parsed.count("Delete")
        and not parsed.count("Unsupported")
    )
    if accepted:
        return AuthenticationPreviewEvaluation(
            accepted_summary=parsed,
            fingerprint=hashlib.sha256(outcome.stdout.encode()).hexdigest(),
        )
    expected_multiplicity = bool(
        len(parsed.changes) != 1 or len(authentication) != 1
    )
    if expected_multiplicity:
        reason: AuthenticationPreviewRejectionReason = "topology_mismatch"
    elif not (
        authentication[0].expected_parent_match
        and authentication[0].expected_identity_match
        and authentication[0].expected_scope_match
    ):
        reason = "identity_not_proven"
    elif (
        authentication[0].action not in {"Create", "Modify"}
        or parsed.count("Delete")
        or parsed.count("Ignore")
        or parsed.count("Unsupported")
    ):
        reason = "action_not_allowed"
    else:
        reason = "topology_mismatch"
    return AuthenticationPreviewEvaluation(
        diagnostic=_authentication_preview_diagnostic(
            reason,
            parsed,
        )
    )


def _authentication_deployment_command(
    request: AuthenticationAcceptanceRequest,
    mode: str,
    deployment_template: PreparedAuthenticationTemplate,
) -> list[str]:
    if deployment_template.path != request.template_file:
        return []
    infrastructure_request = _infra_request(request, mode)
    if mode == "what-if":
        return web_app_infrastructure_deployment_command(
            infrastructure_request,
            what_if_result_format="FullResourcePayloads",
            excluded_what_if_change_types=("Ignore",),
        )
    return web_app_infrastructure_deployment_command(infrastructure_request)


def _prepared_template_valid(
    prepared: object,
) -> bool:
    if not isinstance(prepared, PreparedAuthenticationTemplate):
        return False
    try:
        payload = prepared.path.read_bytes()
    except OSError:
        return False
    return bool(
        prepared.path.is_file()
        and not prepared.path.is_symlink()
        and HEX_64.fullmatch(prepared.digest)
        and hashlib.sha256(payload).hexdigest() == prepared.digest
    )


def prepare_authentication_deployment_template(
    source: Path,
) -> PreparedAuthenticationTemplate | None:
    bicep = Path.home() / ".azure/bin/bicep"
    if not bicep.is_file() or source.name != "web-app-authentication.bicep":
        return None
    try:
        bicep_environment = os.environ.copy()
        bicep_environment["DOTNET_BUNDLE_EXTRACT_BASE_DIR"] = str(
            Path(tempfile.gettempdir()) / "nurse-intake-bicep"
        )
        completed = subprocess.run(
            [str(bicep), "build", str(source), "--stdout"],
            shell=False,
            capture_output=True,
            text=True,
            check=False,
            env=bicep_environment,
        )
    except OSError:
        return None
    if completed.returncode != 0:
        return None
    try:
        compiled = json.loads(completed.stdout)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(compiled, dict):
        return None
    try:
        payload = source.read_bytes()
    except OSError:
        return None
    prepared = PreparedAuthenticationTemplate(
        path=source,
        digest=hashlib.sha256(payload).hexdigest(),
    )
    return prepared if _prepared_template_valid(prepared) else None


def _contract_snapshot(request: AuthenticationAcceptanceRequest) -> str | None:
    try:
        value = request.template_file.read_bytes()
    except OSError:
        return None
    return hashlib.sha256(value).hexdigest()


def _http_authentication_acceptance(
    transport: WebAppReadinessTransport,
) -> tuple[bool, bool]:
    anonymous_verified = False
    protected_verified = False
    try:
        for path in APP_SERVICE_AUTHENTICATION_ANONYMOUS_PATHS:
            if transport.get(path, 5.0).status_code != 200:
                return False, False
        anonymous_verified = True
        for path in ("/demo", "/cases", "/openapi.json"):
            if transport.get(path, 5.0).status_code != 401:
                return anonymous_verified, False
        protected_verified = True
    except Exception:
        return anonymous_verified, protected_verified
    return anonymous_verified, protected_verified


def _hosted_readiness_current(
    request: AuthenticationAcceptanceRequest,
    *,
    artifact_digest: str,
    transport_factory: Callable[[str], WebAppReadinessTransport],
) -> bool:
    readiness = verify_web_app_readiness(
        request.hosted_origin,
        transport_factory=transport_factory,
        expected_application_artifact_digest=artifact_digest,
    )
    return bool(
        readiness.ok
        and readiness.health_verified
        and readiness.version_verified
        and readiness.demo_status_verified
        and readiness.safe_hosted_posture_verified
        and readiness.application_artifact_matches
    )


def accept_web_app_authentication(
    request: AuthenticationAcceptanceRequest,
    *,
    runner: AzureCliRunner,
    current_generation_reader: Callable[[], CurrentGenerationBinding | None],
    approval_callback: Callable[[AuthenticationApprovalSummary], bool],
    artifact_digest_reader: Callable[[], str | None],
    transport_factory: Callable[[str], WebAppReadinessTransport],
    deployment_template: PreparedAuthenticationTemplate,
) -> AuthenticationAcceptanceResult:
    checked = check_authentication_acceptance_request(request)
    if not checked.ok:
        return replace(checked, mode="live")
    progress: dict[str, object] = {
        "current_generation_verified": True,
        "local_contract_validated": True,
    }
    try:
        if not _prepared_template_valid(deployment_template):
            return AuthenticationAcceptanceResult.failure(
                "local_contract_invalid",
                **progress,
            )
        if current_generation_reader() != request.generation:
            return AuthenticationAcceptanceResult.failure(
                "current_generation_invalid",
                **progress,
            )
        current = _read_current_azure_evidence(runner, request)
        progress["azure_operation_attempted"] = True
        if current is None:
            return AuthenticationAcceptanceResult.failure(
                "current_environment_verification_failed",
                **progress,
            )
        progress.update(
            current_web_app_verified=True,
            current_configuration_evidence_verified=True,
        )
        if current.configuration.enabled:
            return AuthenticationAcceptanceResult.failure(
                "authentication_already_enabled",
                **progress,
            )
        artifact_digest = artifact_digest_reader()
        if not isinstance(artifact_digest, str) or HEX_64.fullmatch(artifact_digest) is None:
            return AuthenticationAcceptanceResult.failure(
                "artifact_evidence_invalid",
                **progress,
            )
        if not _hosted_readiness_current(
            request,
            artifact_digest=artifact_digest,
            transport_factory=transport_factory,
        ):
            return AuthenticationAcceptanceResult.failure(
                "current_generation_invalid",
                **progress,
            )
        contract_snapshot = _contract_snapshot(request)
        if contract_snapshot is None:
            return AuthenticationAcceptanceResult.failure(
                "local_contract_invalid",
                **progress,
            )
        preview = _authentication_preview(
            request,
            runner,
            deployment_template,
        )
        if preview.diagnostic is not None:
            return AuthenticationAcceptanceResult.failure(
                "unexpected_preview_changes",
                preview_diagnostic=preview.diagnostic,
                **progress,
            )
        preview_fingerprint = preview.fingerprint
        progress["preview_verified"] = True
        approval = AuthenticationApprovalSummary(
            current_web_app_verified=True,
            application_identifier_validated=True,
            tenant_identifier_validated=True,
            authentication_enablement_required=True,
            anonymous_readiness_exclusions=len(
                APP_SERVICE_AUTHENTICATION_ANONYMOUS_PATHS
            ),
            unrelated_resource_changes=0,
        )
        if not approval_callback(approval):
            return AuthenticationAcceptanceResult.failure(
                "operator_declined",
                **progress,
            )
        progress["operator_approved"] = True
        if (
            current_generation_reader() != request.generation
            or _contract_snapshot(request) != contract_snapshot
            or artifact_digest_reader() != artifact_digest
            or not _prepared_template_valid(deployment_template)
        ):
            return AuthenticationAcceptanceResult.failure(
                "approval_evidence_stale",
                **progress,
            )
        if not _hosted_readiness_current(
            request,
            artifact_digest=artifact_digest,
            transport_factory=transport_factory,
        ):
            return AuthenticationAcceptanceResult.failure(
                "approval_evidence_stale",
                **progress,
            )
        fresh = _read_current_azure_evidence(runner, request)
        if fresh != current:
            return AuthenticationAcceptanceResult.failure(
                "approval_evidence_stale",
                **progress,
            )
        # The preview is intentionally not repeated. Its fingerprint remains bound
        # to the unchanged request, generation, local contract, and current reads.
        if not preview_fingerprint:
            return AuthenticationAcceptanceResult.failure(
                "approval_evidence_stale",
                **progress,
            )
        deployment = runner.run(
            _authentication_deployment_command(
                request,
                "live",
                deployment_template,
            )
        )
        deployment_attempted = True
        deployment_accepted = deployment.return_code == 0
        progress.update(
            deployment_attempted=deployment_attempted,
            deployment_accepted=deployment_accepted,
            azure_mutation_made=True,
        )
        if not deployment_accepted:
            return AuthenticationAcceptanceResult.failure(
                "deployment_failed",
                **progress,
            )
        configured_stdout = _read_authentication_stdout(runner, request)
        shape_diagnostic = (
            diagnose_authentication_configuration_shape(configured_stdout)
            if configured_stdout is not None
            else None
        )
        configured = (
            parse_authentication_configuration_evidence(
                configured_stdout,
                expected_client_id=request.client_application_id,
                expected_tenant_id=request.tenant_id,
                expected_login_endpoint=current.login_endpoint,
            )
            if configured_stdout is not None
            else None
        )
        if configured is None:
            return AuthenticationAcceptanceResult.failure(
                "configuration_verification_failed",
                configuration_shape_diagnostic=shape_diagnostic,
                **progress,
            )
        progress.update(
            authentication_enabled=True,
            entra_provider_verified=configured.entra_provider_verified,
            tenant_binding_verified=configured.tenant_binding_verified,
            application_binding_verified=(
                configured.application_binding_verified
            ),
            unauthenticated_action_verified=(
                configured.unauthenticated_action_verified
            ),
            anonymous_exclusions_verified=(
                configured.anonymous_exclusions_verified
            ),
            configuration_verified=True,
        )
        transport = transport_factory(request.hosted_origin)
        anonymous_verified, protected_verified = _http_authentication_acceptance(
            transport
        )
        progress.update(
            anonymous_readiness_routes_verified=anonymous_verified,
            protected_routes_verified=protected_verified,
        )
        if not anonymous_verified or not protected_verified:
            return AuthenticationAcceptanceResult.failure(
                "anonymous_http_acceptance_failed",
                **progress,
            )
        if not _hosted_readiness_current(
            request,
            artifact_digest=artifact_digest,
            transport_factory=transport_factory,
        ):
            return AuthenticationAcceptanceResult.failure(
                "hosted_readiness_failed",
                **progress,
            )
        return AuthenticationAcceptanceResult.live_success()
    except Exception:
        return AuthenticationAcceptanceResult.failure(
            "unexpected_error",
            **progress,
        )


class SubprocessAzureCliRunner:
    def run(self, args: list[str]) -> CommandResult:
        try:
            completed = subprocess.run(
                args,
                shell=False,
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            return CommandResult(127, "", "")
        return CommandResult(
            completed.returncode,
            completed.stdout,
            completed.stderr,
        )


def _create_azure_cli_runner() -> SubprocessAzureCliRunner:
    return SubprocessAzureCliRunner()


def _read_session_file(path: Path) -> dict[str, str] | None:
    try:
        if path.is_symlink() or not path.is_file():
            return None
        values: dict[str, str] = {}
        for line in path.read_text().splitlines():
            if not line or line.lstrip().startswith("#"):
                continue
            if "=" not in line:
                return None
            name, value = line.split("=", 1)
            if (
                name in values
                or name not in SESSION_FIELDS
                or not value
                or value != value.strip()
                or any(character in value for character in "\x00\r\n\t")
            ):
                return None
            values[name] = value
    except OSError:
        return None
    return values if set(values) == SESSION_FIELDS else None


def _binding(
    receipt: DailyAzureReadinessReceipt,
    session: Mapping[str, str],
    *,
    config: DailyAzureConfig,
    receipt_path: Path,
    session_path: Path,
) -> CurrentGenerationBinding | None:
    if (
        session.get("AZURE_RESOURCE_GROUP") != receipt.resource_group
        or session.get("AZURE_WEB_APP_NAME") != receipt.web_app_name
    ):
        return None
    state_path = daily_azure_readiness_state_path(receipt_path, config)
    try:
        today = datetime.now().astimezone().date()
        current_day_verified = all(
            datetime.fromtimestamp(path.stat().st_mtime).astimezone().date()
            == today
            for path in (receipt_path, state_path, session_path)
        )
    except OSError:
        return None
    binding = CurrentGenerationBinding(
        configuration_fingerprint=receipt.configuration_fingerprint,
        correlation_fingerprint=receipt.correlation_fingerprint,
        run_epoch=receipt.run_epoch,
        resource_group=receipt.resource_group,
        web_app_name=receipt.web_app_name,
        hosted_origin=session["AZURE_WEB_APP_ORIGIN"],
        current_day_verified=current_day_verified,
    )
    return binding if _generation_valid(binding) else None


def _request_from_private_evidence(
    config: DailyAzureConfig,
    receipt: DailyAzureReadinessReceipt,
    session: Mapping[str, str],
    *,
    client_application_id: str,
    tenant_id: str,
    receipt_path: Path = ROOT / READINESS_RECEIPT_FILE,
    session_path: Path = DEFAULT_SESSION_FILE,
) -> AuthenticationAcceptanceRequest | None:
    generation = _binding(
        receipt,
        session,
        config=config,
        receipt_path=receipt_path,
        session_path=session_path,
    )
    if generation is None:
        return None
    request = AuthenticationAcceptanceRequest(
        subscription_name=config.subscription_name,
        resource_group=receipt.resource_group,
        location=config.location,
        environment_name=config.environment_name,
        project_name=config.project_name,
        web_app_name=receipt.web_app_name,
        hosted_origin=generation.hosted_origin,
        client_application_id=client_application_id,
        tenant_id=tenant_id,
        hosted_verifier_project_endpoint=(
            session["AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT"]
        ),
        hosted_verifier_stable_agent_endpoint=(
            session["AZURE_AI_FOUNDRY_AGENT_ENDPOINT"]
        ),
        hosted_verifier_agent_name=session["AZURE_AI_FOUNDRY_AGENT_NAME"],
        hosted_verifier_agent_version=session[
            "AZURE_AI_FOUNDRY_AGENT_VERSION"
        ],
        hosted_verifier_model_deployment_name=session[
            "AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT_NAME"
        ],
        template_file=ROOT / "infra/modules/web-app-authentication.bicep",
        generation=generation,
    )
    return request if check_authentication_acceptance_request(request).ok else None


def _current_artifact_digest() -> str | None:
    session = create_package_authorization_session()
    try:
        package = build_web_app_package(
            ROOT,
            authorization_session=session,
        )
        return authorized_application_artifact_digest(
            package,
            ROOT,
            session,
        )
    except PackageSafetyError:
        return None


def prompt_for_authentication_approval(
    summary: AuthenticationApprovalSummary,
    *,
    input_stream: TextIO | None = None,
    output_stream: TextIO | None = None,
) -> bool:
    source = input_stream or sys.stdin
    destination = output_stream or sys.stderr
    destination.write(
        "APP SERVICE AUTHENTICATION V2\n\n"
        f"Current Web App verified: {'yes' if summary.current_web_app_verified else 'no'}\n"
        "Existing Entra application identifier validated: "
        f"{'yes' if summary.application_identifier_validated else 'no'}\n"
        "Existing tenant identifier validated: "
        f"{'yes' if summary.tenant_identifier_validated else 'no'}\n"
        "Authentication v2 enablement required: "
        f"{'yes' if summary.authentication_enablement_required else 'no'}\n"
        f"Anonymous readiness exclusions: {summary.anonymous_readiness_exclusions}\n"
        f"Unrelated resource changes: {summary.unrelated_resource_changes}\n\n"
        "Proceed? [y/N] "
    )
    destination.flush()
    return source.readline().strip().casefold() in {"y", "yes"}


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Check or supervise the current-generation App Service Authentication "
            "v2 live acceptance boundary."
        )
    )
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--check", action="store_true")
    modes.add_argument("--live", action="store_true")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument(
        "--readiness-receipt",
        type=Path,
        default=ROOT / READINESS_RECEIPT_FILE,
    )
    parser.add_argument(
        "--current-session",
        type=Path,
        default=DEFAULT_SESSION_FILE,
    )
    parser.add_argument("--client-application-id", action="append")
    parser.add_argument("--tenant-id", action="append")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    for attribute, environment_name in OPERATOR_IDENTIFIER_ENVIRONMENT.items():
        values = getattr(args, attribute)
        if values is None:
            setattr(args, attribute, os.environ.get(environment_name))
        elif not isinstance(values, list) or len(values) != 1:
            parser.error(
                f"--{attribute.replace('_', '-')} must be supplied exactly once"
            )
        else:
            setattr(args, attribute, values[0])
    if args.live and not args.json:
        parser.error("--live requires --json")
    return args


def _load_private_request(
    args: argparse.Namespace,
) -> tuple[
    DailyAzureConfig,
    AuthenticationAcceptanceRequest,
] | None:
    try:
        config = load_daily_azure_config(args.config, repository_root=ROOT)
    except ConfigValidationError:
        return None
    receipt = load_matching_daily_azure_readiness_receipt(
        args.readiness_receipt,
        config,
    )
    session = _read_session_file(args.current_session)
    if receipt is None or session is None:
        return None
    request = _request_from_private_evidence(
        config,
        receipt,
        session,
        client_application_id=args.client_application_id,
        tenant_id=args.tenant_id,
        receipt_path=args.readiness_receipt,
        session_path=args.current_session,
    )
    return (config, request) if request is not None else None


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    prepared_template: PreparedAuthenticationTemplate | None = None
    loaded = _load_private_request(args)
    if loaded is None:
        result = AuthenticationAcceptanceResult.failure(
            "invalid_configuration",
            mode="check" if args.check else "live",
        )
    else:
        config, request = loaded
        preflight = check_authentication_acceptance_request(request)
        if not preflight.ok:
            result = replace(
                preflight,
                mode="check" if args.check else "live",
            )
        else:
            prepared_template = prepare_authentication_deployment_template(
                request.template_file
            )
            if prepared_template is None:
                result = AuthenticationAcceptanceResult.failure(
                    "local_contract_invalid",
                    mode="check" if args.check else "live",
                    current_generation_verified=True,
                )
            elif args.check:
                result = preflight
            else:
                def current_generation_reader() -> CurrentGenerationBinding | None:
                    receipt = load_matching_daily_azure_readiness_receipt(
                        args.readiness_receipt,
                        config,
                    )
                    session = _read_session_file(args.current_session)
                    return (
                        _binding(
                            receipt,
                            session,
                            config=config,
                            receipt_path=args.readiness_receipt,
                            session_path=args.current_session,
                        )
                        if receipt is not None and session is not None
                        else None
                    )

                result = accept_web_app_authentication(
                    request,
                    runner=_create_azure_cli_runner(),
                    current_generation_reader=current_generation_reader,
                    approval_callback=prompt_for_authentication_approval,
                    artifact_digest_reader=_current_artifact_digest,
                    transport_factory=UrllibWebAppReadinessTransport,
                    deployment_template=prepared_template,
                )
    if args.json:
        print(json.dumps(result.to_json_dict(), separators=(",", ":"), sort_keys=True))
    else:
        print(result.recommended_next_step)
    return 0 if result.ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
