from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Literal, Protocol


DeploymentMode = Literal["check", "what-if", "live"]
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


@dataclass(frozen=True)
class WhatIfSummary:
    create_count: int
    modify_count: int
    no_change_count: int
    delete_count: int
    ignore_count: int
    deploy_count: int
    unsupported_count: int


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
    delete_review_required: bool
    manual_review_required: bool
    recommended_next_step: str

    def to_json_dict(self) -> dict[str, object]:
        return {
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
            "delete_review_required": self.delete_review_required,
            "manual_review_required": self.manual_review_required,
            "recommended_next_step": self.recommended_next_step,
        }


def _result(
    request: FoundryAgentConsumerRbacDeploymentRequest,
    category: DeploymentCategory,
    *,
    ok: bool = False,
    template_valid: bool = False,
    azure_operation_attempted: bool = False,
    deployment_request_accepted: bool = False,
    summary: WhatIfSummary | None = None,
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
        delete_review_required=bool(summary and summary.delete_count),
        manual_review_required=bool(
            summary
            and (
                summary.delete_count
                or summary.deploy_count
                or summary.unsupported_count
            )
        ),
        recommended_next_step=recommended_next_step,
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
    return (
        request.mode in {"check", "what-if", "live"}
        and _safe_resource_group(request.resource_group)
        and _safe_resource_name(request.web_app_name, minimum=2, maximum=60)
        and _safe_resource_name(request.foundry_account_name, minimum=2, maximum=64)
        and _safe_resource_name(request.foundry_project_name, minimum=2, maximum=64)
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
    if parameters != ["webAppName", "foundryAccountName", "foundryProjectName"]:
        return False

    entry_contract = (
        r"^\s*targetScope\s*=\s*'resourceGroup'\s*$",
        r"resource\s+webApp\s+'Microsoft\.Web/sites@2024-04-01'\s+existing\s*=",
        r"module\s+foundryAgentConsumerRbac\s+'modules/foundry-agent-consumer-rbac\.bicep'\s*=",
        r"webAppPrincipalId\s*:\s*webApp\.identity\.principalId",
    )
    module_contract = (
        r"^\s*targetScope\s*=\s*'resourceGroup'\s*$",
        rf"foundryAgentConsumerRoleDefinitionGuid\s*=\s*'{CONSUMER_ROLE_GUID}'",
        r"resource\s+foundryAccount\s+'Microsoft\.CognitiveServices/accounts@2025-06-01'\s+existing\s*=",
        r"resource\s+foundryProject\s+'Microsoft\.CognitiveServices/accounts/projects@2025-06-01'\s+existing\s*=",
        r"parent\s*:\s*foundryAccount",
        r"name\s*:\s*foundryProjectName",
        r"resource\s+foundryAgentConsumerRoleAssignment\s+'Microsoft\.Authorization/roleAssignments@2022-04-01'\s*=",
        r"name\s*:\s*guid\(\s*foundryProject\.id,\s*webAppPrincipalId,\s*foundryAgentConsumerRoleDefinitionId\s*\)",
        r"scope\s*:\s*foundryProject",
        r"roleDefinitionId\s*:\s*foundryAgentConsumerRoleDefinitionId",
        r"principalType\s*:\s*'ServicePrincipal'",
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
    command = [
        "az",
        "deployment",
        "group",
        "what-if" if request.mode == "what-if" else "create",
        "--resource-group",
        request.resource_group,
    ]
    if request.mode == "live":
        command.extend(["--name", DEPLOYMENT_NAME])
    command.extend(
        [
            "--template-file",
            str(EXPECTED_TEMPLATE),
            "--parameters",
            f"webAppName={request.web_app_name}",
            f"foundryAccountName={request.foundry_account_name}",
            f"foundryProjectName={request.foundry_project_name}",
        ]
    )
    if request.mode == "what-if":
        command.extend(["--no-pretty-print", "--output", "json"])
    else:
        command.extend(["--output", "none"])
    return command


def _parse_what_if_summary(stdout: str) -> WhatIfSummary | None:
    try:
        payload = json.loads(stdout)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("changes"), list):
        return None

    counts = {
        "create": 0,
        "modify": 0,
        "nochange": 0,
        "delete": 0,
        "ignore": 0,
        "deploy": 0,
        "unsupported": 0,
    }
    for change in payload["changes"]:
        if not isinstance(change, dict):
            return None
        change_type = change.get("changeType")
        if not isinstance(change_type, str):
            return None
        normalized = change_type.casefold()
        if normalized not in counts:
            return None
        counts[normalized] += 1
    return WhatIfSummary(
        create_count=counts["create"],
        modify_count=counts["modify"],
        no_change_count=counts["nochange"],
        delete_count=counts["delete"],
        ignore_count=counts["ignore"],
        deploy_count=counts["deploy"],
        unsupported_count=counts["unsupported"],
    )


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
        summary = _parse_what_if_summary(outcome.stdout)
        if summary is None:
            return _result(request, "what_if_parse_failed", **common)
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
