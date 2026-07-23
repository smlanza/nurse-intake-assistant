from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Literal, Protocol
from uuid import UUID, uuid5

from src.app.services.azure_what_if_evidence import (
    SanitizedWhatIfChange,
    SanitizedWhatIfSummary,
    ExpectedWhatIfResource,
    normalize_sanitized_what_if_payload,
)


DeploymentMode = Literal["check", "what-if", "live"]
PreviewTopology = Literal[
    "exact_create",
    "expected_ignore_plus_unsupported",
]
SafeWhatIfAction = Literal[
    "Create",
    "Modify",
    "Delete",
    "Ignore",
    "NoChange",
    "Deploy",
    "Unsupported",
    "Replacement",
    "unknown",
]
SafeWhatIfResourceType = Literal[
    "role_assignment",
    "nested_deployment",
    "foundry_account",
    "foundry_project",
    "web_app",
    "app_service_plan",
    "other_known",
    "unidentified",
]
WhatIfFailureReason = Literal[
    "invalid_json",
    "payload_not_object",
    "changes_missing",
    "changes_not_list",
    "change_record_not_object",
    "unknown_action",
    "resource_id_missing",
    "resource_id_malformed",
    "resource_type_missing",
    "resource_type_mismatch",
    "expected_assignment_missing",
    "expected_assignment_duplicate",
    "unexpected_record",
    "ignore_set_incomplete",
    "ignore_set_has_extra_record",
    "create_properties_missing",
    "principal_evidence_missing",
    "principal_evidence_mismatch",
    "role_evidence_missing",
    "role_evidence_mismatch",
    "assignment_identity_mismatch",
    "assignment_parent_mismatch",
    "assignment_scope_mismatch",
    "create_topology_mismatch",
    "unsupported_topology_mismatch",
    "unsupported_principal_evidence_malformed",
    "unsupported_principal_evidence_mismatch",
    "unsupported_role_evidence_malformed",
    "unsupported_role_evidence_mismatch",
    "unsupported_assignment_evidence_malformed",
    "diagnostic_generation_failed",
    "no_supported_topology_matched",
]
DeploymentCategory = Literal[
    "success",
    "invalid_request",
    "template_contract_invalid",
    "azure_cli_unavailable",
    "what_if_failed",
    "what_if_parse_failed",
    "deployment_failed",
    "unexpected_error",
]

ROOT = Path(__file__).resolve().parents[3]
EXPECTED_TEMPLATE = ROOT / "infra/foundry-agent-consumer-rbac.bicep"
EXPECTED_MODULE = ROOT / "infra/modules/foundry-agent-consumer-rbac.bicep"
DEPLOYMENT_NAME = "foundry-agent-consumer-rbac"
CONSUMER_ROLE_GUID = "eed3b665-ab3a-47b6-8f48-c9382fb1dad6"
ROLE_ASSIGNMENT_RESOURCE_TYPE = "Microsoft.Authorization/roleAssignments"
_ARM_GUID_NAMESPACE = UUID("11fb06fb-712d-4ddd-98c7-e71bbd588830")
_DAILY_ENVIRONMENT_NAME = "daily"
_DAILY_PROJECT_NAME = "nurse-intake"
_DAILY_COSMOS_DATABASE_NAME = "nurse-intake"
_DAILY_COSMOS_CONTAINER_NAME = "cases"
_MAX_DIAGNOSTIC_RECORD_SHAPES = 20
_SAFE_ACTIONS: tuple[SafeWhatIfAction, ...] = (
    "Create",
    "Modify",
    "Delete",
    "Ignore",
    "NoChange",
    "Deploy",
    "Unsupported",
    "Replacement",
    "unknown",
)
_SAFE_RESOURCE_TYPES: tuple[SafeWhatIfResourceType, ...] = (
    "role_assignment",
    "nested_deployment",
    "foundry_account",
    "foundry_project",
    "web_app",
    "app_service_plan",
    "other_known",
    "unidentified",
)
_FAILURE_REASON_ORDER: tuple[WhatIfFailureReason, ...] = (
    "invalid_json",
    "payload_not_object",
    "changes_missing",
    "changes_not_list",
    "change_record_not_object",
    "unknown_action",
    "resource_id_missing",
    "resource_id_malformed",
    "resource_type_missing",
    "resource_type_mismatch",
    "expected_assignment_missing",
    "expected_assignment_duplicate",
    "unexpected_record",
    "ignore_set_incomplete",
    "ignore_set_has_extra_record",
    "create_properties_missing",
    "principal_evidence_missing",
    "principal_evidence_mismatch",
    "role_evidence_missing",
    "role_evidence_mismatch",
    "assignment_identity_mismatch",
    "assignment_parent_mismatch",
    "assignment_scope_mismatch",
    "create_topology_mismatch",
    "unsupported_topology_mismatch",
    "unsupported_principal_evidence_malformed",
    "unsupported_principal_evidence_mismatch",
    "unsupported_role_evidence_malformed",
    "unsupported_role_evidence_mismatch",
    "unsupported_assignment_evidence_malformed",
    "diagnostic_generation_failed",
    "no_supported_topology_matched",
)

_SUCCESS_MESSAGES = {
    "check": "Local RBAC deployment validation passed; no Azure operation was attempted.",
    "what-if": "Azure RBAC deployment preview completed and sanitized counts were parsed.",
    "live": "Azure accepted the RBAC deployment request; separate verification is required.",
}
_FAILURE_MESSAGES: dict[DeploymentCategory, str] = {
    "success": "",
    "invalid_request": "The RBAC deployment request is invalid.",
    "template_contract_invalid": "The expected RBAC Bicep contract is invalid.",
    "azure_cli_unavailable": "Azure CLI is unavailable.",
    "what_if_failed": "The Azure RBAC deployment preview failed.",
    "what_if_parse_failed": "The Azure RBAC preview could not be summarized safely.",
    "deployment_failed": "The Azure RBAC deployment request failed.",
    "unexpected_error": "The RBAC deployment operation did not complete.",
}
_FAILURE_NEXT_STEP = "Review the sanitized category and local inputs before retrying."


@dataclass(frozen=True)
class CommandResult:
    return_code: int
    stdout: str
    stderr: str


class AzureCliRunner(Protocol):
    def run(self, args: list[str]) -> CommandResult: ...


@dataclass(frozen=True)
class FoundryAgentConsumerRbacDeploymentRequest:
    mode: str
    resource_group: str
    web_app_name: str
    foundry_account_name: str
    foundry_project_name: str
    template_file: Path
    approved_evidence: "FoundryAgentConsumerRbacDeploymentEvidence | None" = None


@dataclass(frozen=True)
class FoundryAgentConsumerRbacDeploymentEvidence:
    subscription_id: str
    foundry_project_resource_id: str
    web_app_principal_id: str
    role_definition_id: str
    role_assignment_name: str
    deployment_name: str


def deterministic_role_assignment_name(
    project_resource_id: str,
    principal_id: str,
    role_definition_id: str,
) -> str:
    """Match ARM/Bicep guid(scope, principal, role) deterministically."""
    return str(
        uuid5(
            _ARM_GUID_NAMESPACE,
            "-".join((project_resource_id, principal_id, role_definition_id)),
        )
    )


@dataclass(frozen=True)
class WhatIfSummary:
    preview_topology: PreviewTopology
    assignment_contents_proved: bool
    create_count: int
    modify_count: int
    no_change_count: int
    delete_count: int
    ignore_count: int
    deploy_count: int
    unsupported_count: int
    change_evidence: tuple[SanitizedWhatIfChange, ...]


@dataclass(frozen=True)
class WhatIfRecordShape:
    ordinal: int
    action: SafeWhatIfAction
    safe_resource_type: SafeWhatIfResourceType
    resource_id_present: bool
    resource_id_shape_valid: bool
    resource_type_present: bool
    after_present: bool
    properties_present: bool
    principal_id_present: bool
    role_definition_id_present: bool
    expected_resource_match: bool
    expected_parent_match: bool
    expected_scope_match: bool
    expected_identity_match: bool

    def __post_init__(self) -> None:
        if (
            type(self.ordinal) is not int
            or self.ordinal < 1
            or self.action not in _SAFE_ACTIONS
            or self.safe_resource_type not in _SAFE_RESOURCE_TYPES
            or any(
                type(value) is not bool
                for value in (
                    self.resource_id_present,
                    self.resource_id_shape_valid,
                    self.resource_type_present,
                    self.after_present,
                    self.properties_present,
                    self.principal_id_present,
                    self.role_definition_id_present,
                    self.expected_resource_match,
                    self.expected_parent_match,
                    self.expected_scope_match,
                    self.expected_identity_match,
                )
            )
        ):
            raise ValueError("invalid sanitized what-if record shape")

    def to_json_dict(self) -> dict[str, object]:
        return {
            "ordinal": self.ordinal,
            "action": self.action,
            "safe_resource_type": self.safe_resource_type,
            "resource_id_present": self.resource_id_present,
            "resource_id_shape_valid": self.resource_id_shape_valid,
            "resource_type_present": self.resource_type_present,
            "after_present": self.after_present,
            "properties_present": self.properties_present,
            "principal_id_present": self.principal_id_present,
            "role_definition_id_present": self.role_definition_id_present,
            "expected_resource_match": self.expected_resource_match,
            "expected_parent_match": self.expected_parent_match,
            "expected_scope_match": self.expected_scope_match,
            "expected_identity_match": self.expected_identity_match,
        }


@dataclass(frozen=True)
class WhatIfDiagnostic:
    payload_is_object: bool
    changes_present: bool
    changes_is_list: bool
    change_record_count: int | None
    action_counts: tuple[tuple[SafeWhatIfAction, int], ...]
    resource_type_counts: tuple[tuple[SafeWhatIfResourceType, int], ...]
    record_shapes: tuple[WhatIfRecordShape, ...]
    record_shapes_truncated: bool
    resembles_exact_create: bool
    resembles_expected_ignore_plus_unsupported: bool
    failure_reasons: tuple[WhatIfFailureReason, ...]

    def __post_init__(self) -> None:
        action_keys = tuple(key for key, _ in self.action_counts)
        resource_keys = tuple(key for key, _ in self.resource_type_counts)
        ordered_reasons = tuple(
            reason
            for reason in _FAILURE_REASON_ORDER
            if reason in self.failure_reasons
        )
        count_valid = bool(
            (
                self.change_record_count is None
                or (
                    type(self.change_record_count) is int
                    and self.change_record_count >= 0
                )
            )
            and all(
                type(count) is int and count >= 0
                for _, count in (
                    *self.action_counts,
                    *self.resource_type_counts,
                )
            )
        )
        list_shape_valid = bool(
            (
                self.changes_is_list
                and type(self.change_record_count) is int
                and len(self.record_shapes)
                == min(self.change_record_count, _MAX_DIAGNOSTIC_RECORD_SHAPES)
                and self.record_shapes_truncated
                is (
                    self.change_record_count
                    > _MAX_DIAGNOSTIC_RECORD_SHAPES
                )
                and sum(count for _, count in self.action_counts)
                == self.change_record_count
                and sum(count for _, count in self.resource_type_counts)
                == self.change_record_count
            )
            or (
                not self.changes_is_list
                and self.change_record_count is None
                and not self.record_shapes
                and self.record_shapes_truncated is False
                and all(count == 0 for _, count in self.action_counts)
                and all(count == 0 for _, count in self.resource_type_counts)
            )
        )
        if (
            any(
                type(value) is not bool
                for value in (
                    self.payload_is_object,
                    self.changes_present,
                    self.changes_is_list,
                    self.record_shapes_truncated,
                    self.resembles_exact_create,
                    self.resembles_expected_ignore_plus_unsupported,
                )
            )
            or self.changes_present and not self.payload_is_object
            or self.changes_is_list and not self.changes_present
            or not count_valid
            or action_keys != _SAFE_ACTIONS
            or resource_keys != _SAFE_RESOURCE_TYPES
            or type(self.record_shapes) is not tuple
            or any(
                not isinstance(record, WhatIfRecordShape)
                for record in self.record_shapes
            )
            or tuple(record.ordinal for record in self.record_shapes)
            != tuple(range(1, len(self.record_shapes) + 1))
            or not list_shape_valid
            or type(self.failure_reasons) is not tuple
            or len(set(self.failure_reasons)) != len(self.failure_reasons)
            or ordered_reasons != self.failure_reasons
        ):
            raise ValueError("invalid sanitized what-if diagnostic")

    def to_json_dict(self) -> dict[str, object]:
        return {
            "payload_is_object": self.payload_is_object,
            "changes_present": self.changes_present,
            "changes_is_list": self.changes_is_list,
            "change_record_count": self.change_record_count,
            "action_counts": dict(self.action_counts),
            "resource_type_counts": dict(self.resource_type_counts),
            "record_shapes": [
                record.to_json_dict() for record in self.record_shapes
            ],
            "record_shapes_truncated": self.record_shapes_truncated,
            "resembles_exact_create": self.resembles_exact_create,
            "resembles_expected_ignore_plus_unsupported": (
                self.resembles_expected_ignore_plus_unsupported
            ),
            "failure_reasons": list(self.failure_reasons),
        }


@dataclass(frozen=True)
class _NormalizedWhatIfRecord:
    shape: WhatIfRecordShape
    record_is_object: bool
    action_is_supported: bool
    action_is_canonical: bool
    assignment_resource_id_match: bool
    assignment_resource_type_match: bool
    assignment_parent_match: bool
    assignment_scope_match: bool
    canonical_resource_type_present: bool
    resource_type_consistent: bool
    expected_ignore_index: int | None
    expected_ignore_resource_type_match: bool
    create_values_match: bool
    principal_value_match: bool
    role_value_match: bool
    principal_value_is_none: bool
    role_value_is_none: bool
    after_value_valid: bool
    properties_value_valid: bool
    principal_value_malformed: bool
    role_value_malformed: bool
    unsupported_values_compatible: bool


@dataclass(frozen=True)
class _WhatIfParseOutcome:
    summary: WhatIfSummary | None
    diagnostic: WhatIfDiagnostic | None


@dataclass(frozen=True)
class FoundryAgentConsumerRbacDeploymentResult:
    ok: bool
    operation: str
    mode: str
    category: DeploymentCategory
    message: str
    template_valid: bool
    azure_operation_attempted: bool
    deployment_request_accepted: bool
    create_count: int | None
    modify_count: int | None
    no_change_count: int | None
    delete_count: int | None
    ignore_count: int | None
    deploy_count: int | None
    unsupported_count: int | None
    preview_topology: PreviewTopology | None
    assignment_contents_proved: bool | None
    delete_review_required: bool
    manual_review_required: bool
    recommended_next_step: str
    change_evidence: tuple[SanitizedWhatIfChange, ...]
    what_if_diagnostic: WhatIfDiagnostic | None

    def to_json_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "ok": self.ok,
            "operation": self.operation,
            "mode": self.mode,
            "category": self.category,
            "message": self.message,
            "template_valid": self.template_valid,
            "azure_operation_attempted": self.azure_operation_attempted,
            "deployment_request_accepted": self.deployment_request_accepted,
            "create_count": self.create_count,
            "modify_count": self.modify_count,
            "no_change_count": self.no_change_count,
            "delete_count": self.delete_count,
            "ignore_count": self.ignore_count,
            "deploy_count": self.deploy_count,
            "unsupported_count": self.unsupported_count,
            "preview_topology": self.preview_topology,
            "assignment_contents_proved": self.assignment_contents_proved,
            "delete_review_required": self.delete_review_required,
            "manual_review_required": self.manual_review_required,
            "recommended_next_step": self.recommended_next_step,
            "change_evidence": [
                change.to_json_dict() for change in self.change_evidence
            ],
        }
        if self.what_if_diagnostic is not None:
            result["what_if_diagnostic"] = (
                self.what_if_diagnostic.to_json_dict()
            )
        return result


def _result(
    request: FoundryAgentConsumerRbacDeploymentRequest,
    category: DeploymentCategory,
    *,
    ok: bool = False,
    template_valid: bool = False,
    azure_operation_attempted: bool = False,
    deployment_request_accepted: bool = False,
    summary: WhatIfSummary | None = None,
    what_if_diagnostic: WhatIfDiagnostic | None = None,
    recommended_next_step: str = _FAILURE_NEXT_STEP,
) -> FoundryAgentConsumerRbacDeploymentResult:
    mode = request.mode if request.mode in {"check", "what-if", "live"} else "invalid"
    message = (
        _SUCCESS_MESSAGES[mode]
        if category == "success" and mode in _SUCCESS_MESSAGES
        else _FAILURE_MESSAGES[category]
    )
    return FoundryAgentConsumerRbacDeploymentResult(
        ok=ok,
        operation="deploy_foundry_agent_consumer_rbac",
        mode=mode,
        category=category,
        message=message,
        template_valid=template_valid,
        azure_operation_attempted=azure_operation_attempted,
        deployment_request_accepted=deployment_request_accepted,
        create_count=summary.create_count if summary else None,
        modify_count=summary.modify_count if summary else None,
        no_change_count=summary.no_change_count if summary else None,
        delete_count=summary.delete_count if summary else None,
        ignore_count=summary.ignore_count if summary else None,
        deploy_count=summary.deploy_count if summary else None,
        unsupported_count=summary.unsupported_count if summary else None,
        preview_topology=summary.preview_topology if summary else None,
        assignment_contents_proved=(
            summary.assignment_contents_proved if summary else None
        ),
        delete_review_required=bool(summary and summary.delete_count),
        manual_review_required=bool(
            summary
            and (
                summary.delete_count
                or summary.deploy_count
                or summary.unsupported_count
                or not all(
                    change.approved_boundary for change in summary.change_evidence
                )
            )
        ),
        recommended_next_step=recommended_next_step,
        change_evidence=summary.change_evidence if summary else (),
        what_if_diagnostic=what_if_diagnostic,
    )


def _safe_resource_group(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and value == value.strip()
        and len(value) <= 90
        and not value.startswith("-")
        and not value.endswith(".")
        and re.fullmatch(r"[A-Za-z0-9_.()\-]+", value) is not None
    )


def _safe_resource_name(value: object, *, minimum: int, maximum: int) -> bool:
    return (
        isinstance(value, str)
        and value == value.strip()
        and minimum <= len(value) <= maximum
        and not value.startswith("-")
        and re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9_-]*[A-Za-z0-9])?", value)
        is not None
    )


def _request_arguments_valid(
    request: FoundryAgentConsumerRbacDeploymentRequest,
) -> bool:
    if not (
        request.mode in {"check", "what-if", "live"}
        and _safe_resource_group(request.resource_group)
        and _safe_resource_name(request.web_app_name, minimum=2, maximum=60)
        and _safe_resource_name(request.foundry_account_name, minimum=2, maximum=64)
        and _safe_resource_name(request.foundry_project_name, minimum=2, maximum=64)
    ):
        return False
    if request.mode == "check":
        return True
    evidence = request.approved_evidence
    if evidence is None:
        return False
    project_match = re.fullmatch(
        r"/subscriptions/([^/]+)/resourceGroups/([^/]+)/providers/"
        r"Microsoft\.CognitiveServices/accounts/([^/]+)/projects/([^/]+)",
        evidence.foundry_project_resource_id,
        flags=re.IGNORECASE,
    )
    if project_match is None:
        return False
    subscription_id, resource_group, account_name, project_name = project_match.groups()
    expected_role_id = (
        f"/subscriptions/{subscription_id}/providers/"
        f"Microsoft.Authorization/roleDefinitions/{CONSUMER_ROLE_GUID}"
    )
    return all(
        (
            evidence.subscription_id.casefold() == subscription_id.casefold(),
            request.resource_group.casefold() == resource_group.casefold(),
            request.foundry_account_name.casefold() == account_name.casefold(),
            request.foundry_project_name.casefold() == project_name.casefold(),
            evidence.role_definition_id.casefold() == expected_role_id.casefold(),
            evidence.deployment_name == DEPLOYMENT_NAME,
            evidence.web_app_principal_id == evidence.web_app_principal_id.strip(),
            bool(evidence.web_app_principal_id),
            evidence.role_assignment_name
            == deterministic_role_assignment_name(
                evidence.foundry_project_resource_id,
                evidence.web_app_principal_id,
                evidence.role_definition_id,
            ),
        )
    )


def _strip_bicep_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return re.sub(r"//.*?$", "", text, flags=re.MULTILINE)


def _template_contract_valid(template_file: Path) -> bool:
    try:
        if template_file.resolve(strict=True) != EXPECTED_TEMPLATE.resolve(strict=True):
            return False
        if EXPECTED_MODULE.resolve(strict=True).parent != template_file.parent.resolve(
            strict=True
        ) / "modules":
            return False
        entry_point = _strip_bicep_comments(template_file.read_text())
        module = _strip_bicep_comments(EXPECTED_MODULE.read_text())
    except (OSError, RuntimeError):
        return False

    parameters = re.findall(r"^\s*param\s+(\w+)\s+string\s*$", entry_point, re.MULTILINE)
    if parameters != [
        "webAppName",
        "foundryAccountName",
        "foundryProjectName",
        "approvedWebAppPrincipalId",
        "approvedFoundryProjectResourceId",
        "approvedRoleAssignmentName",
    ]:
        return False

    entry_contract = (
        r"^\s*targetScope\s*=\s*'resourceGroup'\s*$",
        r"resource\s+webApp\s+'Microsoft\.Web/sites@2024-04-01'\s+existing\s*=",
        r"module\s+foundryAgentConsumerRbac\s+'modules/foundry-agent-consumer-rbac\.bicep'\s*=",
        r"webAppPrincipalId\s*:\s*webApp\.identity\.principalId\s*==\s*approvedWebAppPrincipalId\s*\?\s*approvedWebAppPrincipalId\s*:\s*''",
        r"approvedFoundryProjectResourceId\s*:\s*foundryProject\.id\s*==\s*approvedFoundryProjectResourceId\s*\?\s*approvedFoundryProjectResourceId\s*:\s*''",
        r"approvedRoleAssignmentName\s*:\s*approvedRoleAssignmentName",
    )
    module_contract = (
        r"^\s*targetScope\s*=\s*'resourceGroup'\s*$",
        rf"foundryAgentConsumerRoleDefinitionGuid\s*=\s*'{CONSUMER_ROLE_GUID}'",
        r"resource\s+foundryAccount\s+'Microsoft\.CognitiveServices/accounts@2025-06-01'\s+existing\s*=",
        r"resource\s+foundryProject\s+'Microsoft\.CognitiveServices/accounts/projects@2025-06-01'\s+existing\s*=",
        r"parent\s*:\s*foundryAccount",
        r"name\s*:\s*foundryProjectName",
        r"resource\s+foundryAgentConsumerRoleAssignment\s+'Microsoft\.Authorization/roleAssignments@2022-04-01'\s*=",
        r"var\s+computedRoleAssignmentName\s*=\s*guid\(\s*foundryProject\.id,\s*webAppPrincipalId,\s*foundryAgentConsumerRoleDefinitionId\s*\)",
        r"name\s*:\s*foundryProject\.id\s*==\s*approvedFoundryProjectResourceId\s*&&\s*computedRoleAssignmentName\s*==\s*approvedRoleAssignmentName\s*\?\s*approvedRoleAssignmentName\s*:\s*''",
        r"scope\s*:\s*foundryProject",
        r"roleDefinitionId\s*:\s*foundryAgentConsumerRoleDefinitionId",
        r"principalType\s*:\s*'ServicePrincipal'",
        r"@minLength\(1\)\s*param\s+webAppPrincipalId\s+string",
        r"@minLength\(1\)\s*param\s+approvedFoundryProjectResourceId\s+string",
        r"@minLength\(36\)\s*param\s+approvedRoleAssignmentName\s+string",
    )
    return all(
        re.search(pattern, text, re.MULTILINE) is not None
        for text, patterns in (
            (entry_point, entry_contract),
            (module, module_contract),
        )
        for pattern in patterns
    )


def validate_foundry_agent_consumer_rbac_request(
    request: FoundryAgentConsumerRbacDeploymentRequest,
) -> FoundryAgentConsumerRbacDeploymentResult | None:
    if not _request_arguments_valid(request):
        return _result(request, "invalid_request")
    if not _template_contract_valid(request.template_file):
        return _result(request, "template_contract_invalid")
    return None


def _azure_command(request: FoundryAgentConsumerRbacDeploymentRequest) -> list[str]:
    evidence = request.approved_evidence
    assert evidence is not None
    command = [
        "az",
        "deployment",
        "group",
        "what-if" if request.mode == "what-if" else "create",
        "--resource-group",
        request.resource_group,
    ]
    command.extend(["--name", evidence.deployment_name])
    command.extend(
        [
            "--template-file",
            str(EXPECTED_TEMPLATE),
            "--parameters",
            f"webAppName={request.web_app_name}",
            f"foundryAccountName={request.foundry_account_name}",
            f"foundryProjectName={request.foundry_project_name}",
            f"approvedWebAppPrincipalId={evidence.web_app_principal_id}",
            f"approvedFoundryProjectResourceId={evidence.foundry_project_resource_id}",
            f"approvedRoleAssignmentName={evidence.role_assignment_name}",
        ]
    )
    if request.mode == "what-if":
        command.extend(["--no-pretty-print", "--output", "json"])
    else:
        command.extend(["--output", "none"])
    return command


def _parse_what_if_summary(
    stdout: str,
    request: FoundryAgentConsumerRbacDeploymentRequest,
) -> _WhatIfParseOutcome:
    evidence = request.approved_evidence
    assert evidence is not None
    expected_assignment = ExpectedWhatIfResource(
        resource_type=ROLE_ASSIGNMENT_RESOURCE_TYPE,
        logical_category="consumer_role_assignment",
        resource_group=_request_resource_group(evidence.foundry_project_resource_id),
        name_segments=(evidence.role_assignment_name,),
    )
    expected_ignored = _expected_daily_ignore_resources(
        evidence,
        request.web_app_name,
    )
    try:
        payload = json.loads(stdout)
    except (json.JSONDecodeError, TypeError):
        return _WhatIfParseOutcome(
            summary=None,
            diagnostic=_top_level_what_if_diagnostic("invalid_json"),
        )
    expected_resource_id = (
        f"{evidence.foundry_project_resource_id}/providers/"
        f"{ROLE_ASSIGNMENT_RESOURCE_TYPE}/{evidence.role_assignment_name}"
    )
    subscription_id, _, _, _ = _project_parts(
        evidence.foundry_project_resource_id
    )
    expected_ignore_ids = tuple(
        _expected_resource_id(subscription_id, item)
        for item in expected_ignored
    )
    normalized_payload = normalize_sanitized_what_if_payload(
        payload,
        boundary="consumer_rbac",
        record_factory=lambda ordinal, raw, facts: _normalize_what_if_record(
            ordinal=ordinal,
            raw=raw,
            facts=facts,
            evidence=evidence,
            expected_resource_id=expected_resource_id,
            expected_ignored=expected_ignored,
            expected_ignore_ids=expected_ignore_ids,
        ),
        expected_resources=(expected_assignment,),
        sanitized_additional_resource_types={
            item.resource_type: item.logical_category
            for item in expected_ignored
        },
        expected_ignored_resources=expected_ignored,
        allow_expected_ignored_resources_absent=True,
        automatically_approved_actions=frozenset({"Create", "Unsupported"}),
    )
    if not normalized_payload.payload_is_object:
        return _WhatIfParseOutcome(
            summary=None,
            diagnostic=_top_level_what_if_diagnostic("payload_not_object"),
        )
    if not normalized_payload.changes_present:
        return _WhatIfParseOutcome(
            summary=None,
            diagnostic=_top_level_what_if_diagnostic(
                "changes_missing",
                payload_is_object=True,
            ),
        )
    if not normalized_payload.changes_is_list:
        return _WhatIfParseOutcome(
            summary=None,
            diagnostic=_top_level_what_if_diagnostic(
                "changes_not_list",
                payload_is_object=True,
                changes_present=True,
            ),
        )
    normalized = normalized_payload.records
    assert normalized_payload.change_record_count is not None
    summary = _evaluate_what_if_summary(
        change_record_count=normalized_payload.change_record_count,
        parsed=normalized_payload.sanitized_summary,
        normalized=normalized,
        expected_ignored=expected_ignored,
    )
    if summary is not None:
        return _WhatIfParseOutcome(summary=summary, diagnostic=None)
    return _WhatIfParseOutcome(
        summary=None,
        diagnostic=_build_what_if_diagnostic(
            normalized,
            change_record_count=normalized_payload.change_record_count,
            expected_ignore_count=len(expected_ignored),
        ),
    )


def _evaluate_what_if_summary(
    *,
    change_record_count: int,
    parsed: SanitizedWhatIfSummary | None,
    normalized: tuple[_NormalizedWhatIfRecord, ...],
    expected_ignored: tuple[ExpectedWhatIfResource, ...],
) -> WhatIfSummary | None:
    normalized_action_counts = {
        action: sum(record.shape.action == action for record in normalized)
        for action in _SAFE_ACTIONS
    }
    bounded_unsupported_topology = bool(
        change_record_count == len(expected_ignored) + 1
        and len(normalized) == change_record_count
        and all(
            record.record_is_object and record.action_is_supported
            for record in normalized
        )
        and normalized_action_counts
        == {
            "Create": 0,
            "Modify": 0,
            "Delete": 0,
            "Ignore": len(expected_ignored),
            "NoChange": 0,
            "Deploy": 0,
            "Unsupported": 1,
            "Replacement": 0,
            "unknown": 0,
        }
    )
    if bounded_unsupported_topology:
        bounded_changes = tuple(
            SanitizedWhatIfChange(
                action=record.shape.action,
                resource_type="unidentified",
                logical_category=(
                    "bounded_manual_review_ignore"
                    if record.shape.action == "Ignore"
                    else "bounded_manual_review_unsupported"
                ),
                boundary="consumer_rbac",
                approved_boundary=record.shape.action == "Ignore",
                expected_identity_match=False,
                expected_parent_match=False,
                expected_scope_match=False,
                expected_multiplicity_match=True,
            )
            for record in normalized
        )
        return WhatIfSummary(
            preview_topology="expected_ignore_plus_unsupported",
            assignment_contents_proved=False,
            create_count=0,
            modify_count=0,
            no_change_count=0,
            delete_count=0,
            ignore_count=len(expected_ignored),
            deploy_count=0,
            unsupported_count=1,
            change_evidence=bounded_changes,
        )

    if (
        parsed is None
        or not parsed.exact_topology_match
        or len(parsed.changes) != len(normalized)
    ):
        return None
    parsed_changes: tuple[SanitizedWhatIfChange, ...] = parsed.changes
    action_counts = {
        action: sum(change.action == action for change in parsed_changes)
        for action in (
            "Create",
            "Modify",
            "NoChange",
            "Delete",
            "Ignore",
            "Deploy",
            "Unsupported",
        )
    }
    create_topology = bool(
        change_record_count == 1
        and action_counts
        == {
            "Create": 1,
            "Modify": 0,
            "NoChange": 0,
            "Delete": 0,
            "Ignore": 0,
            "Deploy": 0,
            "Unsupported": 0,
        }
    )
    if not create_topology:
        return None

    exact_changes: list[SanitizedWhatIfChange] = []
    for record, sanitized in zip(
        normalized, parsed_changes, strict=True
    ):
        if not record.shape.resource_id_shape_valid:
            return None
        expected_match = bool(
            sanitized.expected_identity_match
            and sanitized.expected_parent_match
            and sanitized.expected_scope_match
            and sanitized.expected_multiplicity_match
        )
        if record.assignment_resource_id_match:
            exact_identity = bool(
                record.assignment_resource_type_match
                and sanitized.logical_category == "consumer_role_assignment"
            )
            parent_and_scope = bool(
                record.assignment_parent_match
                and record.assignment_scope_match
            )
            action = record.shape.action
            if action != "Create" or not record.create_values_match:
                return None
            approved = True
            if not exact_identity or not parent_and_scope or not expected_match:
                return None
        else:
            return None
        exact_changes.append(
            SanitizedWhatIfChange(
                action=sanitized.action,
                resource_type=sanitized.resource_type,
                logical_category=sanitized.logical_category,
                boundary="consumer_rbac",
                approved_boundary=approved,
                expected_identity_match=exact_identity,
                expected_parent_match=parent_and_scope,
                expected_scope_match=parent_and_scope,
                expected_multiplicity_match=True,
            )
        )
    return WhatIfSummary(
        preview_topology="exact_create",
        assignment_contents_proved=True,
        create_count=sum(change.action == "Create" for change in exact_changes),
        modify_count=sum(change.action == "Modify" for change in exact_changes),
        no_change_count=sum(change.action == "NoChange" for change in exact_changes),
        delete_count=sum(change.action == "Delete" for change in exact_changes),
        ignore_count=sum(change.action == "Ignore" for change in exact_changes),
        deploy_count=sum(change.action == "Deploy" for change in exact_changes),
        unsupported_count=sum(change.action == "Unsupported" for change in exact_changes),
        change_evidence=tuple(exact_changes),
    )


def _normalize_what_if_record(
    *,
    ordinal: int,
    raw: object,
    facts,
    evidence: FoundryAgentConsumerRbacDeploymentEvidence,
    expected_resource_id: str,
    expected_ignored: tuple[ExpectedWhatIfResource, ...],
    expected_ignore_ids: tuple[str, ...],
) -> _NormalizedWhatIfRecord:
    if not facts.record_is_object:
        return _NormalizedWhatIfRecord(
            shape=WhatIfRecordShape(
                ordinal=ordinal,
                action="unknown",
                safe_resource_type="unidentified",
                resource_id_present=False,
                resource_id_shape_valid=False,
                resource_type_present=False,
                after_present=False,
                properties_present=False,
                principal_id_present=False,
                role_definition_id_present=False,
                expected_resource_match=False,
                expected_parent_match=False,
                expected_scope_match=False,
                expected_identity_match=False,
            ),
            record_is_object=False,
            action_is_supported=False,
            action_is_canonical=False,
            assignment_resource_id_match=False,
            assignment_resource_type_match=False,
            assignment_parent_match=False,
            assignment_scope_match=False,
            canonical_resource_type_present=False,
            resource_type_consistent=False,
            expected_ignore_index=None,
            expected_ignore_resource_type_match=False,
            create_values_match=False,
            principal_value_match=False,
            role_value_match=False,
            principal_value_is_none=False,
            role_value_is_none=False,
            after_value_valid=False,
            properties_value_valid=False,
            principal_value_malformed=False,
            role_value_malformed=False,
            unsupported_values_compatible=False,
        )
    assert isinstance(raw, dict)
    action: SafeWhatIfAction = facts.action
    canonical_resource_type_present = isinstance(facts.resource_type, str)
    expected_ignore_index = next(
        (
            index
            for index, expected_id in enumerate(expected_ignore_ids)
            if facts.resource_id_matches(expected_id)
        ),
        None,
    )
    assignment_resource_id_match = facts.resource_id_matches(
        expected_resource_id
    )
    authoritative_assignment_type_match = bool(
        isinstance(facts.resource_type, str)
        and facts.resource_type.casefold()
        == ROLE_ASSIGNMENT_RESOURCE_TYPE.casefold()
    )
    assignment_resource_type_match = bool(
        authoritative_assignment_type_match
        and facts.resource_type_consistent
    )
    expected_ignore_type_match = bool(
        expected_ignore_index is not None
        and isinstance(facts.resource_type, str)
        and facts.resource_type.casefold()
        == expected_ignored[expected_ignore_index].resource_type.casefold()
        and facts.resource_type_consistent
    )
    expected_resource_match = bool(
        assignment_resource_id_match or expected_ignore_index is not None
    )
    expected_identity_match = bool(
        (
            assignment_resource_id_match
            and assignment_resource_type_match
        )
        or expected_ignore_type_match
    )
    assignment_parent_match = facts.parent_matches(
        evidence.foundry_project_resource_id
    )
    assignment_scope_match = facts.resource_scope_matches(
        evidence.foundry_project_resource_id
    )
    assignment_candidate = bool(
        authoritative_assignment_type_match
        or assignment_resource_id_match
    )
    expected_scope_match = bool(
        assignment_scope_match
        if assignment_candidate
        else facts.scope_matches(
            evidence.subscription_id,
            _request_resource_group(evidence.foundry_project_resource_id),
        )
    )
    expected_parent_match = bool(
        assignment_parent_match
        if assignment_candidate
        else expected_ignore_index is not None
    )
    after = raw.get("after")
    properties = after.get("properties") if isinstance(after, dict) else None
    after_present = "after" in raw
    properties_present = isinstance(after, dict) and "properties" in after
    principal = properties.get("principalId") if isinstance(properties, dict) else None
    role = properties.get("roleDefinitionId") if isinstance(properties, dict) else None
    return _NormalizedWhatIfRecord(
        shape=WhatIfRecordShape(
            ordinal=ordinal,
            action=action,
            safe_resource_type=_safe_resource_type(
                facts.resource_type,
                expected_ignored,
            ),
            resource_id_present=facts.resource_id_present,
            resource_id_shape_valid=facts.resource_id_shape_valid,
            resource_type_present=facts.resource_type_present,
            after_present=after_present,
            properties_present=properties_present,
            principal_id_present=(
                isinstance(properties, dict) and "principalId" in properties
            ),
            role_definition_id_present=(
                isinstance(properties, dict)
                and "roleDefinitionId" in properties
            ),
            expected_resource_match=expected_resource_match,
            expected_parent_match=expected_parent_match,
            expected_scope_match=expected_scope_match,
            expected_identity_match=expected_identity_match,
        ),
        record_is_object=True,
        action_is_supported=facts.action_is_supported,
        action_is_canonical=facts.action_is_canonical,
        assignment_resource_id_match=assignment_resource_id_match,
        assignment_resource_type_match=assignment_resource_type_match,
        assignment_parent_match=assignment_parent_match,
        assignment_scope_match=assignment_scope_match,
        canonical_resource_type_present=canonical_resource_type_present,
        resource_type_consistent=facts.resource_type_consistent,
        expected_ignore_index=expected_ignore_index,
        expected_ignore_resource_type_match=expected_ignore_type_match,
        create_values_match=_create_values_match(raw, evidence),
        principal_value_match=bool(
            isinstance(properties, dict)
            and properties.get("principalId") == evidence.web_app_principal_id
        ),
        role_value_match=bool(
            isinstance(properties, dict)
            and isinstance(properties.get("roleDefinitionId"), str)
            and properties["roleDefinitionId"].casefold()
            == evidence.role_definition_id.casefold()
        ),
        principal_value_is_none=bool(
            isinstance(properties, dict)
            and "principalId" in properties
            and principal is None
        ),
        role_value_is_none=bool(
            isinstance(properties, dict)
            and "roleDefinitionId" in properties
            and role is None
        ),
        after_value_valid=bool(not after_present or isinstance(after, dict)),
        properties_value_valid=bool(
            not after_present
            or (
                isinstance(after, dict)
                and (
                    "properties" not in after
                    or isinstance(properties, dict)
                )
            )
        ),
        principal_value_malformed=bool(
            isinstance(properties, dict)
            and "principalId" in properties
            and principal is not None
            and not isinstance(principal, str)
        ),
        role_value_malformed=bool(
            isinstance(properties, dict)
            and "roleDefinitionId" in properties
            and role is not None
            and not isinstance(role, str)
        ),
        unsupported_values_compatible=_unsupported_values_compatible(
            raw, evidence
        ),
    )


def _safe_resource_type(
    raw_type: object,
    expected_ignored: tuple[ExpectedWhatIfResource, ...],
) -> SafeWhatIfResourceType:
    if not isinstance(raw_type, str):
        return "unidentified"
    normalized = raw_type.casefold()
    fixed: dict[str, SafeWhatIfResourceType] = {
        ROLE_ASSIGNMENT_RESOURCE_TYPE.casefold(): "role_assignment",
        "microsoft.resources/deployments": "nested_deployment",
        "microsoft.cognitiveservices/accounts": "foundry_account",
        "microsoft.cognitiveservices/accounts/projects": "foundry_project",
        "microsoft.web/sites": "web_app",
        "microsoft.web/serverfarms": "app_service_plan",
    }
    if normalized in fixed:
        return fixed[normalized]
    if any(
        normalized == expected.resource_type.casefold()
        for expected in expected_ignored
    ):
        return "other_known"
    return "unidentified"


def _top_level_what_if_diagnostic(
    reason: WhatIfFailureReason,
    *,
    payload_is_object: bool = False,
    changes_present: bool = False,
) -> WhatIfDiagnostic:
    reasons = _ordered_failure_reasons(
        {reason, "no_supported_topology_matched"}
    )
    return WhatIfDiagnostic(
        payload_is_object=payload_is_object,
        changes_present=changes_present,
        changes_is_list=False,
        change_record_count=None,
        action_counts=tuple((action, 0) for action in _SAFE_ACTIONS),
        resource_type_counts=tuple(
            (resource_type, 0) for resource_type in _SAFE_RESOURCE_TYPES
        ),
        record_shapes=(),
        record_shapes_truncated=False,
        resembles_exact_create=False,
        resembles_expected_ignore_plus_unsupported=False,
        failure_reasons=reasons,
    )


def _build_what_if_diagnostic(
    normalized: tuple[_NormalizedWhatIfRecord, ...],
    *,
    change_record_count: int,
    expected_ignore_count: int,
) -> WhatIfDiagnostic:
    shapes = tuple(record.shape for record in normalized)
    action_counts = tuple(
        (action, sum(shape.action == action for shape in shapes))
        for action in _SAFE_ACTIONS
    )
    resource_type_counts = tuple(
        (
            resource_type,
            sum(shape.safe_resource_type == resource_type for shape in shapes),
        )
        for resource_type in _SAFE_RESOURCE_TYPES
    )
    exact_assignment_records = [
        record for record in normalized if record.assignment_resource_id_match
    ]
    ignore_records = [
        record for record in normalized if record.shape.action == "Ignore"
    ]
    expected_ignore_indexes = [
        record.expected_ignore_index
        for record in ignore_records
        if record.expected_ignore_index is not None
    ]
    unique_expected_ignore_indexes = set(expected_ignore_indexes)
    resembles_exact_create = bool(
        any(record.shape.action == "Create" for record in normalized)
        or (change_record_count == 1 and exact_assignment_records)
    )
    resembles_unsupported = bool(
        any(
            record.shape.action in {"Ignore", "Unsupported"}
            for record in normalized
        )
    )
    object_records = tuple(
        record for record in normalized if record.record_is_object
    )
    all_records_are_objects = len(object_records) == len(normalized)
    reasons: set[WhatIfFailureReason] = {"no_supported_topology_matched"}
    if any(not record.record_is_object for record in normalized):
        reasons.add("change_record_not_object")
    if any(record.shape.action == "unknown" for record in object_records):
        reasons.add("unknown_action")
    if any(not record.shape.resource_id_present for record in object_records):
        reasons.add("resource_id_missing")
    if any(
        record.shape.resource_id_present
        and not record.shape.resource_id_shape_valid
        for record in object_records
    ):
        reasons.add("resource_id_malformed")
    if any(
        not record.shape.resource_type_present
        and not record.canonical_resource_type_present
        for record in object_records
    ):
        reasons.add("resource_type_missing")
    if any(
        record.shape.resource_type_present
        and record.canonical_resource_type_present
        and not record.resource_type_consistent
        for record in object_records
    ):
        reasons.add("resource_type_mismatch")
    if all_records_are_objects:
        if not exact_assignment_records:
            reasons.add("expected_assignment_missing")
        elif len(exact_assignment_records) > 1:
            reasons.add("expected_assignment_duplicate")
    assignment_candidates = [
        record
        for record in normalized
        if (
            record.shape.safe_resource_type == "role_assignment"
            or record.assignment_resource_id_match
        )
    ]
    for record in assignment_candidates:
        shape = record.shape
        if not shape.expected_identity_match:
            reasons.add("assignment_identity_mismatch")
        if not shape.expected_parent_match:
            reasons.add("assignment_parent_mismatch")
        if not shape.expected_scope_match:
            reasons.add("assignment_scope_mismatch")
        if shape.action == "Create":
            if not shape.properties_present:
                reasons.add("create_properties_missing")
            if not shape.principal_id_present:
                reasons.add("principal_evidence_missing")
            elif not record.principal_value_match:
                reasons.add("principal_evidence_mismatch")
            if not shape.role_definition_id_present:
                reasons.add("role_evidence_missing")
            elif not record.role_value_match:
                reasons.add("role_evidence_mismatch")
        if shape.action == "Unsupported" and record.assignment_resource_id_match:
            if (
                not record.after_value_valid
                or not record.properties_value_valid
            ):
                reasons.add("unsupported_assignment_evidence_malformed")
            if record.principal_value_malformed:
                reasons.add("unsupported_principal_evidence_malformed")
            elif (
                shape.principal_id_present
                and not record.principal_value_is_none
                and not record.principal_value_match
            ):
                reasons.add("unsupported_principal_evidence_mismatch")
            if record.role_value_malformed:
                reasons.add("unsupported_role_evidence_malformed")
            elif (
                shape.role_definition_id_present
                and not record.role_value_is_none
                and not record.role_value_match
            ):
                reasons.add("unsupported_role_evidence_mismatch")
    if resembles_unsupported and all_records_are_objects:
        if len(unique_expected_ignore_indexes) < expected_ignore_count:
            reasons.add("ignore_set_incomplete")
        if (
            len(ignore_records) > expected_ignore_count
            or len(expected_ignore_indexes) != len(unique_expected_ignore_indexes)
            or any(
                record.expected_ignore_index is None for record in ignore_records
            )
        ):
            reasons.add("ignore_set_has_extra_record")
        reasons.add("unsupported_topology_mismatch")
    if resembles_exact_create:
        reasons.add("create_topology_mismatch")
    for record in object_records:
        shape = record.shape
        assignment_compatible = bool(
            record.assignment_resource_id_match
            and record.assignment_resource_type_match
            and (
                (
                    shape.action == "Create"
                    and record.create_values_match
                )
                or (
                    shape.action == "Unsupported"
                    and record.unsupported_values_compatible
                )
            )
        )
        ignore_compatible = bool(
            shape.action == "Ignore"
            and record.expected_ignore_index is not None
            and shape.expected_identity_match
        )
        if not assignment_compatible and not ignore_compatible:
            reasons.add("unexpected_record")
    return WhatIfDiagnostic(
        payload_is_object=True,
        changes_present=True,
        changes_is_list=True,
        change_record_count=change_record_count,
        action_counts=action_counts,
        resource_type_counts=resource_type_counts,
        record_shapes=shapes[:_MAX_DIAGNOSTIC_RECORD_SHAPES],
        record_shapes_truncated=(
            change_record_count > _MAX_DIAGNOSTIC_RECORD_SHAPES
        ),
        resembles_exact_create=resembles_exact_create,
        resembles_expected_ignore_plus_unsupported=resembles_unsupported,
        failure_reasons=_ordered_failure_reasons(reasons),
    )


def _ordered_failure_reasons(
    reasons: set[WhatIfFailureReason],
) -> tuple[WhatIfFailureReason, ...]:
    return tuple(reason for reason in _FAILURE_REASON_ORDER if reason in reasons)


def _daily_resource_name_suffix(resource_group: str) -> str:
    identity = "\x00".join(
        (
            resource_group.casefold(),
            _DAILY_PROJECT_NAME,
            _DAILY_ENVIRONMENT_NAME,
        )
    ).encode()
    return hashlib.sha256(identity).hexdigest()[:13]


def _expected_daily_ignore_resources(
    evidence: FoundryAgentConsumerRbacDeploymentEvidence,
    web_app_name: str,
) -> tuple[ExpectedWhatIfResource, ...]:
    _, resource_group, account_name, project_name = _project_parts(
        evidence.foundry_project_resource_id
    )
    suffix = _daily_resource_name_suffix(resource_group)
    project_environment = f"{_DAILY_PROJECT_NAME}-{_DAILY_ENVIRONMENT_NAME}"
    cosmos_account = f"{project_environment}-{suffix}"
    plan_name = f"{project_environment}-plan-{suffix}"[:40]
    definitions = (
        (
            "Microsoft.DocumentDB/databaseAccounts",
            "cosmos_account",
            (cosmos_account,),
        ),
        (
            "Microsoft.DocumentDB/databaseAccounts/sqlDatabases",
            "cosmos_database",
            (cosmos_account, _DAILY_COSMOS_DATABASE_NAME),
        ),
        (
            "Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers",
            "cosmos_container",
            (
                cosmos_account,
                _DAILY_COSMOS_DATABASE_NAME,
                _DAILY_COSMOS_CONTAINER_NAME,
            ),
        ),
        ("Microsoft.Storage/storageAccounts", "storage_account", (f"st{suffix}",)),
        (
            "Microsoft.OperationalInsights/workspaces",
            "log_analytics",
            (f"{project_environment}-logs-{suffix}",),
        ),
        (
            "Microsoft.Insights/components",
            "application_insights",
            (f"{project_environment}-appi-{suffix}",),
        ),
        ("Microsoft.Web/serverfarms", "app_service_plan", (plan_name,)),
        (
            "Microsoft.Web/sites",
            "web_app",
            (web_app_name,),
        ),
        (
            "Microsoft.CognitiveServices/accounts",
            "foundry_account_reference",
            (account_name,),
        ),
        (
            "Microsoft.CognitiveServices/accounts/projects",
            "foundry_project_reference",
            (account_name, project_name),
        ),
    )
    return tuple(
        ExpectedWhatIfResource(
            resource_type=resource_type,
            logical_category=category,
            resource_group=resource_group,
            name_segments=name_segments,
        )
        for resource_type, category, name_segments in definitions
    )


def _create_values_match(
    raw: dict[str, object],
    evidence: FoundryAgentConsumerRbacDeploymentEvidence,
) -> bool:
    after = raw.get("after")
    properties = after.get("properties") if isinstance(after, dict) else None
    return bool(
        isinstance(properties, dict)
        and properties.get("principalId") == evidence.web_app_principal_id
        and isinstance(properties.get("roleDefinitionId"), str)
        and properties["roleDefinitionId"].casefold()
        == evidence.role_definition_id.casefold()
    )


def _unsupported_values_compatible(
    raw: dict[str, object],
    evidence: FoundryAgentConsumerRbacDeploymentEvidence,
) -> bool:
    if "after" not in raw:
        return True
    after = raw.get("after")
    if not isinstance(after, dict):
        return False
    if "properties" not in after:
        return True
    properties = after.get("properties")
    if not isinstance(properties, dict):
        return False
    principal = properties.get("principalId")
    role = properties.get("roleDefinitionId")
    return bool(
        (principal is None or principal == evidence.web_app_principal_id)
        and (
            role is None
            or (
                isinstance(role, str)
                and role.casefold() == evidence.role_definition_id.casefold()
            )
        )
    )


def _expected_ignore_change_matches(
    raw: dict[str, object],
    sanitized: SanitizedWhatIfChange,
    evidence: FoundryAgentConsumerRbacDeploymentEvidence,
    expected: tuple[ExpectedWhatIfResource, ...],
) -> bool:
    raw_id = raw.get("resourceId")
    raw_type = raw.get("resourceType")
    if not isinstance(raw_id, str) or not isinstance(raw_type, str):
        return False
    subscription_id, _, _, _ = _project_parts(
        evidence.foundry_project_resource_id
    )
    for item in expected:
        expected_id = _expected_resource_id(subscription_id, item)
        if raw_id.casefold() != expected_id.casefold():
            continue
        return bool(
            raw_type.casefold() == item.resource_type.casefold()
            and sanitized.resource_type.casefold() == item.resource_type.casefold()
            and sanitized.logical_category == item.logical_category
            and sanitized.approved_boundary
            and sanitized.expected_identity_match
            and sanitized.expected_parent_match
            and sanitized.expected_scope_match
            and sanitized.expected_multiplicity_match
        )
    return False


def _expected_resource_id(
    subscription_id: str,
    expected: ExpectedWhatIfResource,
) -> str:
    namespace, *type_segments = expected.resource_type.split("/")
    if len(type_segments) != len(expected.name_segments):
        raise ValueError("invalid expected resource identity")
    typed_names = "/".join(
        part
        for pair in zip(type_segments, expected.name_segments, strict=True)
        for part in pair
    )
    return (
        f"/subscriptions/{subscription_id}/resourceGroups/"
        f"{expected.resource_group}/providers/{namespace}/{typed_names}"
    )


def _project_parts(project_resource_id: str) -> tuple[str, str, str, str]:
    match = re.fullmatch(
        r"/subscriptions/([^/]+)/resourceGroups/([^/]+)/providers/"
        r"Microsoft\.CognitiveServices/accounts/([^/]+)/projects/([^/]+)",
        project_resource_id,
        flags=re.IGNORECASE,
    )
    if match is None:
        raise ValueError("invalid approved project identity")
    return match.groups()


def _request_resource_group(project_resource_id: str) -> str:
    return _project_parts(project_resource_id)[1]


def deploy_foundry_agent_consumer_rbac(
    request: FoundryAgentConsumerRbacDeploymentRequest,
    *,
    runner: AzureCliRunner | None = None,
) -> FoundryAgentConsumerRbacDeploymentResult:
    invalid = validate_foundry_agent_consumer_rbac_request(request)
    if invalid is not None:
        return invalid
    if request.mode == "check":
        return _result(
            request,
            "success",
            ok=True,
            template_valid=True,
            recommended_next_step=(
                "Review the local contract, then explicitly run --what-if against the existing resource group."
            ),
        )
    if runner is None:
        return _result(request, "unexpected_error", template_valid=True)

    try:
        outcome = runner.run(_azure_command(request))
    except Exception:
        return _result(
            request,
            "unexpected_error",
            template_valid=True,
            azure_operation_attempted=True,
        )

    common = {"template_valid": True, "azure_operation_attempted": True}
    if outcome.return_code == 127:
        return _result(request, "azure_cli_unavailable", **common)
    if outcome.return_code != 0:
        category: DeploymentCategory = (
            "what_if_failed" if request.mode == "what-if" else "deployment_failed"
        )
        return _result(request, category, **common)
    if request.mode == "what-if":
        assert request.approved_evidence is not None
        try:
            parsed = _parse_what_if_summary(outcome.stdout, request)
        except Exception:
            parsed = _WhatIfParseOutcome(
                summary=None,
                diagnostic=_top_level_what_if_diagnostic(
                    "diagnostic_generation_failed"
                ),
            )
        if parsed.summary is None:
            return _result(
                request,
                "what_if_parse_failed",
                what_if_diagnostic=parsed.diagnostic,
                **common,
            )
        summary = parsed.summary
        next_step = (
            "Manual review is required for Delete, Deploy, or Unsupported preview entries before any live request."
            if summary.delete_count
            or summary.deploy_count
            or summary.unsupported_count
            else "Review the sanitized preview before any separate explicit --live request."
        )
        return _result(
            request,
            "success",
            ok=True,
            summary=summary,
            recommended_next_step=next_step,
            **common,
        )
    return _result(
        request,
        "success",
        ok=True,
        deployment_request_accepted=True,
        recommended_next_step=(
            "Run separate read-only verification of the project-scoped Consumer assignment."
        ),
        **common,
    )
