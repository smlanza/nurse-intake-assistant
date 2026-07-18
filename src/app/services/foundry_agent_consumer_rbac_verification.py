from dataclasses import dataclass
import json
import re
from typing import Literal, Protocol

from src.app.services import foundry_agent_consumer_rbac_deployment as deployment


VerificationMode = Literal["check", "live"]
VerificationCategory = Literal[
    "success",
    "invalid_configuration",
    "web_app_identity_missing",
    "foundry_project_scope_not_found",
    "assignment_missing",
    "assignment_scope_mismatch",
    "role_mismatch",
    "authentication_or_authorization_failed",
    "azure_cli_unavailable",
    "azure_request_failed",
    "response_parse_failed",
    "unexpected_error",
]

WEB_APP_IDENTITY_QUERY = "{principalId:principalId,type:type}"
FOUNDRY_PROJECT_QUERY = "{name:name,id:id}"
ROLE_ASSIGNMENT_QUERY = (
    "[].{principalId:principalId,roleDefinitionId:roleDefinitionId,scope:scope}"
)


@dataclass(frozen=True)
class CommandResult:
    return_code: int
    stdout: str
    stderr: str


class AzureCliRunner(Protocol):
    def run(self, args: list[str]) -> CommandResult: ...


@dataclass(frozen=True)
class FoundryAgentConsumerRbacVerificationRequest:
    mode: str
    resource_group: str
    web_app_name: str
    foundry_account_name: str
    foundry_project_name: str


@dataclass(frozen=True)
class FoundryAgentConsumerRbacVerificationResult:
    ok: bool
    category: VerificationCategory
    operation: str
    mode: str
    local_contract_validated: bool
    azure_request_attempted: bool
    web_app_identity_present: bool
    foundry_project_scope_resolved: bool
    consumer_assignment_present: bool
    consumer_assignment_scope_matches: bool
    consumer_role_matches: bool
    recommended_next_step: str

    def to_json_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "category": self.category,
            "operation": self.operation,
            "mode": self.mode,
            "local_contract_validated": self.local_contract_validated,
            "azure_request_attempted": self.azure_request_attempted,
            "web_app_identity_present": self.web_app_identity_present,
            "foundry_project_scope_resolved": self.foundry_project_scope_resolved,
            "consumer_assignment_present": self.consumer_assignment_present,
            "consumer_assignment_scope_matches": self.consumer_assignment_scope_matches,
            "consumer_role_matches": self.consumer_role_matches,
            "recommended_next_step": self.recommended_next_step,
        }


_FAILURE_NEXT_STEP = "Review the sanitized category and local inputs before retrying."


def _result(
    request: FoundryAgentConsumerRbacVerificationRequest,
    category: VerificationCategory,
    *,
    ok: bool = False,
    local_contract_validated: bool = False,
    azure_request_attempted: bool = False,
    web_app_identity_present: bool = False,
    foundry_project_scope_resolved: bool = False,
    consumer_assignment_present: bool = False,
    consumer_assignment_scope_matches: bool = False,
    consumer_role_matches: bool = False,
    recommended_next_step: str = _FAILURE_NEXT_STEP,
) -> FoundryAgentConsumerRbacVerificationResult:
    return FoundryAgentConsumerRbacVerificationResult(
        ok=ok,
        category=category,
        operation="verify_foundry_agent_consumer_rbac",
        mode=request.mode if request.mode in {"check", "live"} else "invalid",
        local_contract_validated=local_contract_validated,
        azure_request_attempted=azure_request_attempted,
        web_app_identity_present=web_app_identity_present,
        foundry_project_scope_resolved=foundry_project_scope_resolved,
        consumer_assignment_present=consumer_assignment_present,
        consumer_assignment_scope_matches=consumer_assignment_scope_matches,
        consumer_role_matches=consumer_role_matches,
        recommended_next_step=recommended_next_step,
    )


def _local_contract_valid(
    request: FoundryAgentConsumerRbacVerificationRequest,
) -> bool:
    if request.mode not in {"check", "live"}:
        return False
    deployment_request = deployment.FoundryAgentConsumerRbacDeploymentRequest(
        mode="check",
        resource_group=request.resource_group,
        web_app_name=request.web_app_name,
        foundry_account_name=request.foundry_account_name,
        foundry_project_name=request.foundry_project_name,
        template_file=deployment.EXPECTED_TEMPLATE,
    )
    return (
        deployment.validate_foundry_agent_consumer_rbac_request(deployment_request)
        is None
    )


def validate_foundry_agent_consumer_rbac_verification_request(
    request: FoundryAgentConsumerRbacVerificationRequest,
) -> FoundryAgentConsumerRbacVerificationResult | None:
    if not _local_contract_valid(request):
        return _result(request, "invalid_configuration")
    return None


def verify_foundry_agent_consumer_rbac(
    request: FoundryAgentConsumerRbacVerificationRequest,
    *,
    runner: AzureCliRunner | None = None,
) -> FoundryAgentConsumerRbacVerificationResult:
    invalid = validate_foundry_agent_consumer_rbac_verification_request(request)
    if invalid is not None:
        return invalid
    if request.mode == "check":
        return _result(
            request,
            "success",
            ok=True,
            local_contract_validated=True,
            recommended_next_step=(
                "After operator-reviewed RBAC deployment, run explicit --live --json "
                "read-only assignment verification."
            ),
        )
    if runner is None:
        return _result(
            request,
            "unexpected_error",
            local_contract_validated=True,
        )

    progress: dict[str, bool] = {
        "local_contract_validated": True,
        "azure_request_attempted": True,
        "web_app_identity_present": False,
        "foundry_project_scope_resolved": False,
        "consumer_assignment_present": False,
        "consumer_assignment_scope_matches": False,
        "consumer_role_matches": False,
    }

    identity, failure = _read_json(
        runner,
        [
            "az",
            "webapp",
            "identity",
            "show",
            "--resource-group",
            request.resource_group,
            "--name",
            request.web_app_name,
            "--query",
            WEB_APP_IDENTITY_QUERY,
            "--output",
            "json",
            "--only-show-errors",
        ],
        not_found_category="web_app_identity_missing",
    )
    if failure:
        return _result(request, failure, **progress)
    identity_values = _system_identity(identity)
    if identity_values is None:
        if _identity_shape_valid(identity):
            return _result(request, "web_app_identity_missing", **progress)
        return _result(request, "response_parse_failed", **progress)
    principal_id = identity_values
    progress["web_app_identity_present"] = True

    project, failure = _read_json(
        runner,
        [
            "az",
            "cognitiveservices",
            "account",
            "project",
            "show",
            "--resource-group",
            request.resource_group,
            "--name",
            request.foundry_account_name,
            "--project-name",
            request.foundry_project_name,
            "--query",
            FOUNDRY_PROJECT_QUERY,
            "--output",
            "json",
            "--only-show-errors",
        ],
        not_found_category="foundry_project_scope_not_found",
    )
    if failure:
        return _result(request, failure, **progress)
    project_scope = _project_scope(project, request)
    if project_scope is None:
        if (
            isinstance(project, dict)
            and set(project) == {"name", "id"}
            and project.get("id") is None
        ):
            return _result(request, "foundry_project_scope_not_found", **progress)
        return _result(request, "response_parse_failed", **progress)
    progress["foundry_project_scope_resolved"] = True

    assignments, failure = _read_json(
        runner,
        [
            "az",
            "role",
            "assignment",
            "list",
            "--assignee-object-id",
            principal_id,
            "--role",
            deployment.CONSUMER_ROLE_GUID,
            "--scope",
            project_scope,
            "--include-inherited",
            "--query",
            ROLE_ASSIGNMENT_QUERY,
            "--output",
            "json",
            "--only-show-errors",
        ],
    )
    if failure:
        return _result(request, failure, **progress)
    parsed = _role_assignment_match_state(assignments, principal_id, project_scope)
    if parsed is None:
        return _result(request, "response_parse_failed", **progress)
    exact_count, assignment_present, scope_matches, role_matches = parsed
    progress.update(
        consumer_assignment_present=assignment_present,
        consumer_assignment_scope_matches=scope_matches,
        consumer_role_matches=role_matches,
    )
    if exact_count > 1:
        return _result(request, "response_parse_failed", **progress)
    if exact_count == 1:
        return _result(
            request,
            "success",
            ok=True,
            recommended_next_step=(
                "Proceed to separate hosted managed-identity Foundry Agent verification."
            ),
            **progress,
        )
    if role_matches:
        return _result(request, "assignment_scope_mismatch", **progress)
    if scope_matches:
        return _result(request, "role_mismatch", **progress)
    return _result(request, "assignment_missing", **progress)


def _read_json(
    runner: AzureCliRunner,
    command: list[str],
    *,
    not_found_category: VerificationCategory | None = None,
) -> tuple[object | None, VerificationCategory | None]:
    try:
        outcome = runner.run(command)
    except Exception:
        return None, "unexpected_error"
    if outcome.return_code != 0:
        return None, _command_failure_category(
            outcome, not_found_category=not_found_category
        )
    try:
        return json.loads(outcome.stdout), None
    except (json.JSONDecodeError, TypeError):
        return None, "response_parse_failed"


def _command_failure_category(
    outcome: CommandResult,
    *,
    not_found_category: VerificationCategory | None,
) -> VerificationCategory:
    if outcome.return_code == 127:
        return "azure_cli_unavailable"
    lowered = outcome.stderr.casefold()
    if any(
        marker in lowered
        for marker in (
            "az login",
            "authentication",
            "authorization",
            "authorizationfailed",
            "unauthorized",
            "forbidden",
            "credential",
        )
    ):
        return "authentication_or_authorization_failed"
    if not_found_category and any(
        marker in lowered
        for marker in ("resourcenotfound", "could not be found", "was not found")
    ):
        return not_found_category
    return "azure_request_failed"


def _identity_shape_valid(payload: object) -> bool:
    return isinstance(payload, dict) and set(payload) == {"principalId", "type"}


def _system_identity(payload: object) -> str | None:
    if not _identity_shape_valid(payload):
        return None
    principal_id = payload.get("principalId")
    identity_type = payload.get("type")
    if not isinstance(principal_id, str) or not principal_id.strip():
        return None
    if not isinstance(identity_type, str):
        return None
    identity_types = {item.strip().casefold() for item in identity_type.split(",")}
    if "systemassigned" not in identity_types:
        return None
    return principal_id


def _project_scope(
    payload: object,
    request: FoundryAgentConsumerRbacVerificationRequest,
) -> str | None:
    if not isinstance(payload, dict) or set(payload) != {"name", "id"}:
        return None
    project_name = payload.get("name")
    resource_id = payload.get("id")
    if (
        not isinstance(project_name, str)
        or not project_name.strip()
        or project_name != project_name.strip()
        or not isinstance(resource_id, str)
        or not resource_id.strip()
        or resource_id != resource_id.strip()
    ):
        return None
    valid_names = {
        request.foundry_project_name.casefold(),
        f"{request.foundry_account_name}/{request.foundry_project_name}".casefold(),
    }
    if project_name.casefold() not in valid_names:
        return None
    match = re.fullmatch(
        r"/subscriptions/[^/]+/resourceGroups/([^/]+)/providers/"
        r"Microsoft\.CognitiveServices/accounts/([^/]+)/projects/([^/]+)",
        resource_id,
        flags=re.IGNORECASE,
    )
    if match is None:
        return None
    if tuple(part.casefold() for part in match.groups()) != (
        request.resource_group.casefold(),
        request.foundry_account_name.casefold(),
        request.foundry_project_name.casefold(),
    ):
        return None
    return resource_id


def _role_assignment_match_state(
    payload: object,
    principal_id: str,
    project_scope: str,
) -> tuple[int, bool, bool, bool] | None:
    if not isinstance(payload, list):
        return None
    exact_count = 0
    assignment_present = False
    scope_matches = False
    role_matches = False
    expected_role_suffix = (
        "/providers/microsoft.authorization/roledefinitions/"
        f"{deployment.CONSUMER_ROLE_GUID}"
    )
    for assignment in payload:
        if not isinstance(assignment, dict) or set(assignment) != {
            "principalId",
            "roleDefinitionId",
            "scope",
        }:
            return None
        record_principal = assignment.get("principalId")
        role_definition_id = assignment.get("roleDefinitionId")
        scope = assignment.get("scope")
        if not all(
            isinstance(value, str) and bool(value.strip())
            for value in (record_principal, role_definition_id, scope)
        ):
            return None
        if record_principal.casefold() != principal_id.casefold():
            continue
        record_scope_matches = scope.casefold() == project_scope.casefold()
        record_role_matches = role_definition_id.casefold().endswith(
            expected_role_suffix.casefold()
        )
        scope_matches = scope_matches or record_scope_matches
        role_matches = role_matches or record_role_matches
        assignment_present = assignment_present or record_role_matches
        if record_scope_matches and record_role_matches:
            exact_count += 1
    return exact_count, assignment_present, scope_matches, role_matches
