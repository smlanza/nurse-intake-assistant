from dataclasses import dataclass
from importlib.util import find_spec
from typing import Any, Callable, Literal

from src.app.services.nurse_intake_agent_instructions import (
    NURSE_INTAKE_AGENT_INSTRUCTION_VERSION,
)


VerificationCategory = Literal[
    "success",
    "missing_configuration",
    "agent_version_not_found",
    "definition_mismatch",
    "response_contract_invalid",
    "sdk_unavailable",
    "authentication_or_authorization_failed",
    "agent_verification_failed",
]
VERIFICATION_OPERATION = "verify_prompt_agent"
VERIFICATION_SUCCESS_MESSAGE = "Foundry prompt-agent verification completed."
VERIFICATION_FAILURE_MESSAGE = "Foundry prompt-agent verification did not complete."
VERIFICATION_NEXT_STEP = (
    "Run the separate fictional-data Foundry Agent smoke only after verification "
    "succeeds; nurse review remains required."
)


@dataclass(frozen=True)
class FoundryAgentVerificationRequest:
    project_endpoint: str
    agent_name: str
    agent_version: str
    model_deployment_name: str
    instructions: str


@dataclass(frozen=True)
class FoundryAgentVerificationResult:
    ok: bool
    mode: Literal["live"]
    operation: str
    category: VerificationCategory
    message: str
    agent_name_present: bool
    agent_version_present: bool
    model_deployment_name_present: bool
    instruction_version: str
    agent_definition_matches: bool
    agent_invoked: bool
    azure_mutation_made: bool
    recommended_next_step: str

    @classmethod
    def success(cls) -> "FoundryAgentVerificationResult":
        return cls(
            ok=True,
            mode="live",
            operation=VERIFICATION_OPERATION,
            category="success",
            message=VERIFICATION_SUCCESS_MESSAGE,
            agent_name_present=True,
            agent_version_present=True,
            model_deployment_name_present=True,
            instruction_version=NURSE_INTAKE_AGENT_INSTRUCTION_VERSION,
            agent_definition_matches=True,
            agent_invoked=False,
            azure_mutation_made=False,
            recommended_next_step=VERIFICATION_NEXT_STEP,
        )

    @classmethod
    def failure(
        cls,
        category: VerificationCategory,
        *,
        agent_name_present: bool = False,
        agent_version_present: bool = False,
        model_deployment_name_present: bool = False,
    ) -> "FoundryAgentVerificationResult":
        return cls(
            ok=False,
            mode="live",
            operation=VERIFICATION_OPERATION,
            category=category,
            message=VERIFICATION_FAILURE_MESSAGE,
            agent_name_present=agent_name_present,
            agent_version_present=agent_version_present,
            model_deployment_name_present=model_deployment_name_present,
            instruction_version=NURSE_INTAKE_AGENT_INSTRUCTION_VERSION,
            agent_definition_matches=False,
            agent_invoked=False,
            azure_mutation_made=False,
            recommended_next_step=VERIFICATION_NEXT_STEP,
        )

    def to_json_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "mode": self.mode,
            "operation": self.operation,
            "category": self.category,
            "message": self.message,
            "agent_name_present": self.agent_name_present,
            "agent_version_present": self.agent_version_present,
            "model_deployment_name_present": self.model_deployment_name_present,
            "instruction_version": self.instruction_version,
            "agent_definition_matches": self.agent_definition_matches,
            "agent_invoked": self.agent_invoked,
            "azure_mutation_made": self.azure_mutation_made,
            "recommended_next_step": self.recommended_next_step,
        }


class FoundryAgentVerification:
    """Read-only verification of one configured immutable prompt-agent version."""

    def __init__(
        self,
        *,
        project_client_factory: Callable[[str], Any] | None = None,
    ) -> None:
        self.project_client_factory = (
            project_client_factory or _create_live_project_client
        )

    def verify(
        self,
        request: FoundryAgentVerificationRequest,
    ) -> FoundryAgentVerificationResult:
        presence = {
            "agent_name_present": bool(request.agent_name),
            "agent_version_present": bool(request.agent_version),
            "model_deployment_name_present": bool(request.model_deployment_name),
        }
        try:
            project_client = self.project_client_factory(request.project_endpoint)
            remote_version = project_client.agents.get_version(
                request.agent_name,
                request.agent_version,
            )
        except Exception as exc:
            return FoundryAgentVerificationResult.failure(
                _category_for_exception(exc),
                **presence,
            )

        if not _remote_contract_is_valid(remote_version, request):
            return FoundryAgentVerificationResult.failure(
                "response_contract_invalid",
                **presence,
            )

        if not _definition_matches(remote_version, request):
            return FoundryAgentVerificationResult.failure(
                "definition_mismatch",
                **presence,
            )

        return FoundryAgentVerificationResult.success()


def foundry_agent_verification_sdk_available() -> bool:
    try:
        return (
            find_spec("azure.ai.projects") is not None
            and find_spec("azure.identity") is not None
        )
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def _create_live_project_client(project_endpoint: str) -> Any:
    from azure.ai.projects import AIProjectClient
    from azure.identity import DefaultAzureCredential

    return AIProjectClient(
        endpoint=project_endpoint,
        credential=DefaultAzureCredential(),
    )


def _remote_contract_is_valid(
    remote_version: Any,
    request: FoundryAgentVerificationRequest,
) -> bool:
    return (
        _object_value(remote_version, "name") == request.agent_name
        and _object_value(remote_version, "version") == request.agent_version
        and _raw_object_value(remote_version, "definition") is not None
    )


def _definition_matches(
    remote_version: Any,
    request: FoundryAgentVerificationRequest,
) -> bool:
    definition = _raw_object_value(remote_version, "definition")
    return (
        _object_value(definition, "model") == request.model_deployment_name
        and _object_value(definition, "instructions") == request.instructions
    )


def _raw_object_value(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _object_value(value: Any, name: str) -> str:
    raw_value = _raw_object_value(value, name)
    return str(raw_value).strip() if raw_value is not None else ""


def _category_for_exception(error: BaseException) -> VerificationCategory:
    for current in _exception_chain(error):
        status = _status_code(current)
        if status == 404:
            return "agent_version_not_found"
        if status in {401, 403}:
            return "authentication_or_authorization_failed"
        name = type(current).__name__.lower()
        if "authentication" in name or "credential" in name or "forbidden" in name:
            return "authentication_or_authorization_failed"
        if isinstance(current, (ImportError, ModuleNotFoundError)):
            return "sdk_unavailable"
    return "agent_verification_failed"


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
