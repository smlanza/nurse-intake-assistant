from dataclasses import dataclass
import json
import re
from typing import Literal, Protocol
from uuid import UUID

from src.app.services import foundry_agent_consumer_rbac_deployment as deployment


VerificationMode = Literal["check", "live"]
VerificationCategory = Literal[
    "success",
    "invalid_configuration",
    "web_app_identity_missing",
    "foundry_project_scope_not_found",
    "assignment_missing",
    "assignment_scope_mismatch",
    "principal_mismatch",
    "role_mismatch",
    "assignment_ambiguous",
    "authentication_or_authorization_failed",
    "azure_cli_unavailable",
    "azure_request_failed",
    "response_parse_failed",
    "unexpected_error",
]

WEB_APP_IDENTITY_QUERY = (
    "{principalId:identity.principalId,type:identity.type,webAppId:id}"
)
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
    principal_id: str | None
    web_app_resource_id: str | None
    subscription_id: str | None
    foundry_account_resource_id: str | None
    foundry_project_resource_id: str | None
    role_definition_id: str | None
    matching_assignment_count: int | None

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

    @property
    def web_app_resource_guid(self) -> None:
        return None


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
    principal_id: str | None = None,
    web_app_resource_id: str | None = None,
    subscription_id: str | None = None,
    foundry_account_resource_id: str | None = None,
    foundry_project_resource_id: str | None = None,
    role_definition_id: str | None = None,
    matching_assignment_count: int | None = None,
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
        principal_id=principal_id,
        web_app_resource_id=web_app_resource_id,
        subscription_id=subscription_id,
        foundry_account_resource_id=foundry_account_resource_id,
        foundry_project_resource_id=foundry_project_resource_id,
        role_definition_id=role_definition_id,
        matching_assignment_count=matching_assignment_count,
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

    progress: dict[str, object] = {
        "local_contract_validated": True,
        "azure_request_attempted": True,
        "web_app_identity_present": False,
        "foundry_project_scope_resolved": False,
        "consumer_assignment_present": False,
        "consumer_assignment_scope_matches": False,
        "consumer_role_matches": False,
        "principal_id": None,
        "web_app_resource_id": None,
        "subscription_id": None,
        "foundry_account_resource_id": None,
        "foundry_project_resource_id": None,
        "role_definition_id": None,
        "matching_assignment_count": None,
    }

    identity, failure = _read_json(
        runner,
        [
            "az",
            "webapp",
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
    identity_values = _system_identity(identity, request)
    if identity_values is None:
        if _identity_shape_valid(identity) and _system_identity_declared_missing(identity):
            return _result(request, "web_app_identity_missing", **progress)
        return _result(request, "response_parse_failed", **progress)
    principal_id, web_app_resource_id, subscription_id = identity_values
    progress["web_app_identity_present"] = True
    progress["principal_id"] = principal_id
    progress["web_app_resource_id"] = web_app_resource_id
    progress["subscription_id"] = subscription_id

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
    project_scope = _project_scope(project, request, subscription_id)
    if project_scope is None:
        if (
            isinstance(project, dict)
            and set(project) == {"name", "id"}
            and project.get("id") is None
        ):
            return _result(request, "foundry_project_scope_not_found", **progress)
        return _result(request, "response_parse_failed", **progress)
    progress["foundry_project_scope_resolved"] = True
    foundry_account_resource_id = project_scope.rsplit("/projects/", 1)[0]
    role_definition_id = (
        f"/subscriptions/{subscription_id}/providers/"
        "Microsoft.Authorization/roleDefinitions/"
        f"{deployment.CONSUMER_ROLE_GUID}"
    )
    progress.update(
        subscription_id=subscription_id,
        foundry_account_resource_id=foundry_account_resource_id,
        foundry_project_resource_id=project_scope,
        role_definition_id=role_definition_id,
    )

    assignments, failure = _read_json(
        runner,
        [
            "az",
            "role",
            "assignment",
            "list",
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
    parsed = _role_assignment_match_state(
        assignments,
        principal_id,
        project_scope,
        role_definition_id,
    )
    if parsed is None:
        return _result(request, "response_parse_failed", **progress)
    (
        exact_count,
        assignment_present,
        scope_matches,
        role_matches,
        principal_mismatch,
    ) = parsed
    progress.update(
        consumer_assignment_present=assignment_present,
        consumer_assignment_scope_matches=scope_matches,
        consumer_role_matches=role_matches,
        matching_assignment_count=exact_count,
    )
    if exact_count > 1:
        return _result(request, "assignment_ambiguous", **progress)
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
    if principal_mismatch:
        return _result(request, "principal_mismatch", **progress)
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
    if not isinstance(payload, dict):
        return False
    required = {"principalId", "type", "webAppId"}
    return set(payload) == required or (
        set(payload) == required | {"resourceGuid"}
        and payload.get("resourceGuid") is None
    )


def _system_identity_declared_missing(payload: object) -> bool:
    if not isinstance(payload, dict):
        return False
    principal = payload.get("principalId")
    identity_type = payload.get("type")
    return (
        principal is None
        or principal == ""
        or not isinstance(identity_type, str)
        or identity_type.casefold() != "systemassigned"
    )


def _canonical_guid(value: object) -> str | None:
    if not isinstance(value, str) or not value or value != value.strip():
        return None
    try:
        canonical = str(UUID(value))
    except (ValueError, AttributeError, TypeError):
        return None
    return canonical if value.casefold() == canonical else None


def _system_identity(
    payload: object,
    request: FoundryAgentConsumerRbacVerificationRequest,
) -> tuple[str, str, str] | None:
    if not _identity_shape_valid(payload):
        return None
    principal_id = _canonical_guid(payload.get("principalId"))
    web_app_resource_id = payload.get("webAppId")
    identity_type = payload.get("type")
    if principal_id is None:
        return None
    if not isinstance(identity_type, str) or not isinstance(web_app_resource_id, str):
        return None
    if identity_type.casefold() != "systemassigned":
        return None
    match = re.fullmatch(
        r"/subscriptions/([^/]+)/resourceGroups/([^/]+)/providers/"
        r"Microsoft\.Web/sites/([^/]+)",
        web_app_resource_id,
        flags=re.IGNORECASE,
    )
    if match is None:
        return None
    subscription_id = _canonical_guid(match.group(1))
    if subscription_id is None or tuple(
        part.casefold() for part in match.groups()[1:]
    ) != (request.resource_group.casefold(), request.web_app_name.casefold()):
        return None
    return principal_id, web_app_resource_id, subscription_id


def _project_scope(
    payload: object,
    request: FoundryAgentConsumerRbacVerificationRequest,
    subscription_id: str,
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
        r"/subscriptions/([^/]+)/resourceGroups/([^/]+)/providers/"
        r"Microsoft\.CognitiveServices/accounts/([^/]+)/projects/([^/]+)",
        resource_id,
        flags=re.IGNORECASE,
    )
    if match is None:
        return None
    project_subscription = _canonical_guid(match.group(1))
    if project_subscription != subscription_id or tuple(
        part.casefold() for part in match.groups()[1:]
    ) != (
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
    expected_role_definition_id: str,
) -> tuple[int, bool, bool, bool, bool] | None:
    if not isinstance(payload, list):
        return None
    exact_count = 0
    assignment_present = False
    scope_matches = False
    role_matches = False
    principal_mismatch = False
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
        canonical_principal = _canonical_guid(record_principal)
        if (
            canonical_principal is None
            or not isinstance(role_definition_id, str)
            or not isinstance(scope, str)
            or not role_definition_id
            or role_definition_id != role_definition_id.strip()
            or not scope
            or scope != scope.strip()
        ):
            return None
        role_match = re.fullmatch(
            r"/subscriptions/([^/]+)/providers/"
            r"Microsoft\.Authorization/roleDefinitions/([^/]+)",
            role_definition_id,
            flags=re.IGNORECASE,
        )
        if (
            role_match is None
            or _canonical_guid(role_match.group(1)) is None
            or _canonical_guid(role_match.group(2)) is None
        ):
            return None
        record_principal_matches = canonical_principal == principal_id
        record_scope_matches = scope.casefold() == project_scope.casefold()
        record_role_matches = (
            role_definition_id.casefold() == expected_role_definition_id.casefold()
        )
        relevant = record_principal_matches or record_role_matches
        if not relevant:
            continue
        scope_matches = scope_matches or record_scope_matches
        role_matches = role_matches or record_role_matches
        assignment_present = assignment_present or record_role_matches or (
            record_principal_matches and record_scope_matches
        )
        principal_mismatch = principal_mismatch or (
            record_scope_matches
            and record_role_matches
            and not record_principal_matches
        )
        if record_principal_matches and record_scope_matches and record_role_matches:
            exact_count += 1
    return (
        exact_count,
        assignment_present,
        scope_matches,
        role_matches,
        principal_mismatch,
    )
