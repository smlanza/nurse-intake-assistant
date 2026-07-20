from dataclasses import dataclass
from importlib.util import find_spec
from collections.abc import Mapping
from typing import Any, Callable, Literal

from src.app.services.nurse_intake_agent_instructions import (
    NURSE_INTAKE_AGENT_INSTRUCTION_VERSION,
)
from src.app.services.foundry_credential_factory import (
    FoundryCredentialConfiguration,
    FoundryCredentialFactory,
)


DeploymentCategory = Literal[
    "success",
    "missing_configuration",
    "sdk_unavailable",
    "authentication_or_authorization_failed",
    "agent_provisioning_failed",
    "unexpected_error",
]
DEPLOYMENT_OPERATION = "provision_prompt_agent"
DEPLOYMENT_SUCCESS_MESSAGE = "Foundry prompt-agent provisioning completed."
DEPLOYMENT_FAILURE_MESSAGE = "Foundry prompt-agent provisioning did not complete."
DEPLOYMENT_NEXT_STEP = (
    "Review the agent name and version in Foundry, update the ignored local "
    "environment file manually, then run the separate Foundry Agent smoke command."
)


@dataclass(frozen=True)
class FoundryAgentDeploymentRequest:
    project_endpoint: str
    agent_name: str
    model_deployment_name: str
    instructions: str
    managed_identity_client_id: str | None = None


@dataclass(frozen=True)
class FoundryAgentDeploymentResult:
    ok: bool
    mode: Literal["live"]
    operation: str
    category: DeploymentCategory
    message: str
    agent_created: bool
    agent_reused: bool
    agent_updated: bool
    agent_name_present: bool
    agent_version_present: bool
    model_deployment_name_present: bool
    instruction_version: str
    agent_invoked: bool
    recommended_next_step: str
    resolved_agent_name: str | None = None
    resolved_agent_version: str | None = None
    azure_call_made: bool = False
    azure_mutation_made: bool | None = False

    @classmethod
    def success(
        cls,
        *,
        agent_created: bool = False,
        agent_reused: bool = False,
        agent_updated: bool = False,
        agent_name_present: bool = True,
        agent_version_present: bool = True,
        model_deployment_name_present: bool = True,
        resolved_agent_name: str | None = None,
        resolved_agent_version: str | None = None,
    ) -> "FoundryAgentDeploymentResult":
        return cls(
            ok=True,
            mode="live",
            operation=DEPLOYMENT_OPERATION,
            category="success",
            message=DEPLOYMENT_SUCCESS_MESSAGE,
            agent_created=agent_created,
            agent_reused=agent_reused,
            agent_updated=agent_updated,
            agent_name_present=agent_name_present,
            agent_version_present=agent_version_present,
            model_deployment_name_present=model_deployment_name_present,
            instruction_version=NURSE_INTAKE_AGENT_INSTRUCTION_VERSION,
            agent_invoked=False,
            recommended_next_step=DEPLOYMENT_NEXT_STEP,
            resolved_agent_name=resolved_agent_name,
            resolved_agent_version=resolved_agent_version,
            azure_call_made=True,
            azure_mutation_made=agent_created or agent_updated,
        )

    @classmethod
    def failure(
        cls,
        category: DeploymentCategory,
        *,
        agent_name_present: bool = False,
        model_deployment_name_present: bool = False,
        azure_call_made: bool = False,
        azure_mutation_made: bool | None = False,
    ) -> "FoundryAgentDeploymentResult":
        return cls(
            ok=False,
            mode="live",
            operation=DEPLOYMENT_OPERATION,
            category=category,
            message=DEPLOYMENT_FAILURE_MESSAGE,
            agent_created=False,
            agent_reused=False,
            agent_updated=False,
            agent_name_present=agent_name_present,
            agent_version_present=False,
            model_deployment_name_present=model_deployment_name_present,
            instruction_version=NURSE_INTAKE_AGENT_INSTRUCTION_VERSION,
            agent_invoked=False,
            recommended_next_step=DEPLOYMENT_NEXT_STEP,
            azure_call_made=azure_call_made,
            azure_mutation_made=azure_mutation_made,
        )

    def to_json_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "mode": self.mode,
            "operation": self.operation,
            "category": self.category,
            "message": self.message,
            "agent_created": self.agent_created,
            "agent_reused": self.agent_reused,
            "agent_updated": self.agent_updated,
            "agent_name_present": self.agent_name_present,
            "agent_version_present": self.agent_version_present,
            "model_deployment_name_present": self.model_deployment_name_present,
            "instruction_version": self.instruction_version,
            "agent_invoked": self.agent_invoked,
            "recommended_next_step": self.recommended_next_step,
        }


class FoundryAgentDeployment:
    """Explicit, idempotent prompt-agent provisioning boundary."""

    def __init__(
        self,
        *,
        project_client_factory: Callable[[str], Any] | None = None,
        prompt_agent_definition_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.project_client_factory = project_client_factory
        self.prompt_agent_definition_factory = (
            prompt_agent_definition_factory or _create_prompt_agent_definition
        )

    def provision(
        self,
        request: FoundryAgentDeploymentRequest,
    ) -> FoundryAgentDeploymentResult:
        try:
            if self.project_client_factory is None:
                project_client = _create_live_project_client(
                    request.project_endpoint,
                    request.managed_identity_client_id,
                )
            else:
                project_client = self.project_client_factory(
                    request.project_endpoint
                )
        except Exception as exc:
            return FoundryAgentDeploymentResult.failure(
                _category_for_exception(exc, "agent_provisioning_failed"),
                agent_name_present=bool(request.agent_name),
                model_deployment_name_present=bool(request.model_deployment_name),
            )

        try:
            existing_version = _latest_version(
                project_client.agents,
                request.agent_name,
            )
        except Exception as exc:
            if _status_code(exc) == 404:
                existing_version = None
            else:
                return FoundryAgentDeploymentResult.failure(
                    _category_for_exception(exc, "agent_provisioning_failed"),
                    agent_name_present=bool(request.agent_name),
                    model_deployment_name_present=bool(
                        request.model_deployment_name
                    ),
                )

        if existing_version is not None and _definition_matches(
            existing_version,
            request,
        ):
            existing_name = _object_value(existing_version, "name")
            existing_version_name = _object_value(existing_version, "version")
            if not existing_name or not existing_version_name:
                return FoundryAgentDeploymentResult.failure(
                    "agent_provisioning_failed",
                    agent_name_present=bool(request.agent_name),
                    model_deployment_name_present=bool(request.model_deployment_name),
                )
            return FoundryAgentDeploymentResult.success(
                agent_reused=True,
                resolved_agent_name=existing_name,
                resolved_agent_version=existing_version_name,
            )

        create_attempted = False
        try:
            definition = self.prompt_agent_definition_factory(
                model=request.model_deployment_name,
                instructions=request.instructions,
            )
            create_attempted = True
            provisioned_version = project_client.agents.create_version(
                agent_name=request.agent_name,
                definition=definition,
            )
            provisioned_name = _object_value(provisioned_version, "name")
            provisioned_version_name = _object_value(
                provisioned_version,
                "version",
            )
            if not provisioned_name or not provisioned_version_name:
                raise ValueError(
                    "Provisioned agent version did not expose safe presence metadata."
                )
        except Exception as exc:
            return FoundryAgentDeploymentResult.failure(
                _category_for_exception(exc, "agent_provisioning_failed"),
                agent_name_present=bool(request.agent_name),
                model_deployment_name_present=bool(request.model_deployment_name),
                azure_call_made=create_attempted,
                azure_mutation_made=None if create_attempted else False,
            )

        return FoundryAgentDeploymentResult.success(
            agent_created=existing_version is None,
            agent_updated=existing_version is not None,
            agent_name_present=bool(provisioned_name),
            agent_version_present=bool(provisioned_version_name),
            resolved_agent_name=provisioned_name,
            resolved_agent_version=provisioned_version_name,
        )


def foundry_agent_deployment_sdk_available() -> bool:
    try:
        return (
            find_spec("azure.ai.projects") is not None
            and find_spec("azure.identity") is not None
        )
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def _create_live_project_client(
    project_endpoint: str,
    managed_identity_client_id: str | None = None,
) -> Any:
    project_client_class = _get_ai_project_client_class()
    credential = FoundryCredentialFactory().create(
        FoundryCredentialConfiguration(managed_identity_client_id)
    )
    return project_client_class(
        endpoint=project_endpoint,
        credential=credential,
    )


def _get_ai_project_client_class():
    from azure.ai.projects import AIProjectClient

    return AIProjectClient


def _create_prompt_agent_definition(**kwargs: str) -> Any:
    from azure.ai.projects.models import PromptAgentDefinition

    return PromptAgentDefinition(**kwargs)


def _latest_version(agents: Any, agent_name: str) -> Any | None:
    versions = agents.list_versions(agent_name, limit=1, order="desc")
    return next(iter(versions), None)


def _definition_matches(
    existing_version: Any,
    request: FoundryAgentDeploymentRequest,
) -> bool:
    definition = _raw_object_value(existing_version, "definition")
    return bool(definition) and (
        _object_value(definition, "model") == request.model_deployment_name
        and _object_value(definition, "instructions") == request.instructions
    )


def _raw_object_value(value: Any, name: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


def _object_value(value: Any, name: str) -> str:
    raw_value = _raw_object_value(value, name)
    return str(raw_value).strip() if raw_value is not None else ""


def _category_for_exception(
    error: BaseException,
    fallback: DeploymentCategory,
) -> DeploymentCategory:
    for current in _exception_chain(error):
        if getattr(current, "category", None) == "sdk_unavailable":
            return "sdk_unavailable"
        if _status_code(current) in {401, 403}:
            return "authentication_or_authorization_failed"
        name = type(current).__name__.lower()
        if "authentication" in name or "credential" in name or "forbidden" in name:
            return "authentication_or_authorization_failed"
        if isinstance(current, (ImportError, ModuleNotFoundError)):
            return "sdk_unavailable"
    return fallback


def _exception_chain(error: BaseException):
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def _status_code(error: BaseException) -> int | None:
    status = getattr(error, "status_code", None)
    if isinstance(status, int):
        return status
    response = getattr(error, "response", None)
    response_status = getattr(response, "status_code", None)
    return response_status if isinstance(response_status, int) else None
