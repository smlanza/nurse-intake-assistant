from dataclasses import dataclass
from importlib.util import find_spec
from types import SimpleNamespace
from typing import Any, Callable, Literal

from src.app.services.foundry_agent_client import _extract_response_output_text
from src.app.services.foundry_agent_contract import (
    FoundryExtractionContractError,
    FoundryExtractionParseError,
    normalize_foundry_agent_intake_response,
)
from src.app.services.nurse_intake_agent_contract import (
    validate_nurse_intake_agent_result,
)
from src.app.services.nurse_intake_agent_instructions import (
    NURSE_INTAKE_AGENT_INSTRUCTION_VERSION,
)


DeploymentCategory = Literal[
    "success",
    "missing_configuration",
    "sdk_unavailable",
    "authentication_or_authorization_failed",
    "agent_version_creation_failed",
    "agent_invocation_failed",
    "response_parse_failed",
    "contract_invalid",
    "unexpected_error",
]
DEPLOYMENT_OPERATION = "create_and_validate_agent_version"
DEPLOYMENT_NEXT_STEP = (
    "Run the existing Foundry Agent intake smoke or restore AGENT_PROVIDER=mock."
)


@dataclass(frozen=True)
class FoundryAgentDeploymentRequest:
    project_endpoint: str
    agent_name: str
    model_deployment_name: str
    instructions: str
    fictional_validation_input: str


@dataclass(frozen=True)
class FoundryAgentDeploymentResult:
    ok: bool
    mode: Literal["live"]
    operation: str
    category: DeploymentCategory
    agent_created: bool
    agent_invoked: bool
    agent_output_valid: bool | None
    created_version: str | None
    instruction_version: str
    fields_present: list[str]
    recommended_next_step: str

    @classmethod
    def success(
        cls,
        *,
        created_version: str,
        fields_present: list[str],
    ) -> "FoundryAgentDeploymentResult":
        return cls(
            ok=True,
            mode="live",
            operation=DEPLOYMENT_OPERATION,
            category="success",
            agent_created=True,
            agent_invoked=True,
            agent_output_valid=True,
            created_version=created_version,
            instruction_version=NURSE_INTAKE_AGENT_INSTRUCTION_VERSION,
            fields_present=fields_present,
            recommended_next_step=DEPLOYMENT_NEXT_STEP,
        )

    @classmethod
    def failure(
        cls,
        category: DeploymentCategory,
        *,
        agent_created: bool = False,
        agent_invoked: bool = False,
        agent_output_valid: bool | None = None,
        created_version: str | None = None,
    ) -> "FoundryAgentDeploymentResult":
        return cls(
            ok=False,
            mode="live",
            operation=DEPLOYMENT_OPERATION,
            category=category,
            agent_created=agent_created,
            agent_invoked=agent_invoked,
            agent_output_valid=agent_output_valid,
            created_version=created_version,
            instruction_version=NURSE_INTAKE_AGENT_INSTRUCTION_VERSION,
            fields_present=[],
            recommended_next_step=DEPLOYMENT_NEXT_STEP,
        )

    def to_json_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "mode": self.mode,
            "operation": self.operation,
            "category": self.category,
            "agent_created": self.agent_created,
            "agent_invoked": self.agent_invoked,
            "agent_output_valid": self.agent_output_valid,
            "created_version": self.created_version,
            "instruction_version": self.instruction_version,
            "fields_present": self.fields_present,
            "recommended_next_step": self.recommended_next_step,
        }


class FoundryAgentDeployment:
    """Explicit prompt-agent version deployment and validation boundary."""

    def __init__(
        self,
        *,
        project_client_factory: Callable[[str], Any] | None = None,
        prompt_agent_definition_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.project_client_factory = (
            project_client_factory or _create_live_project_client
        )
        self.prompt_agent_definition_factory = (
            prompt_agent_definition_factory or _create_prompt_agent_definition
        )

    def create_and_validate(
        self,
        request: FoundryAgentDeploymentRequest,
    ) -> FoundryAgentDeploymentResult:
        try:
            project_client = self.project_client_factory(request.project_endpoint)
            definition = self.prompt_agent_definition_factory(
                model=request.model_deployment_name,
                instructions=request.instructions,
            )
            created_agent = project_client.agents.create_version(
                agent_name=request.agent_name,
                definition=definition,
            )
            created_name = _object_value(created_agent, "name")
            created_version = _object_value(created_agent, "version")
            if not created_name or not created_version:
                raise ValueError("Created agent version did not expose name and version.")
        except Exception as exc:
            return FoundryAgentDeploymentResult.failure(
                _category_for_exception(exc, "agent_version_creation_failed")
            )

        try:
            openai_client = project_client.get_openai_client()
            response = openai_client.responses.create(
                input=request.fictional_validation_input,
                extra_body={
                    "agent_reference": {
                        "name": created_name,
                        "version": created_version,
                        "type": "agent_reference",
                    }
                },
            )
            output_text = _extract_response_output_text(response)
        except Exception as exc:
            return FoundryAgentDeploymentResult.failure(
                _category_for_exception(exc, "agent_invocation_failed"),
                agent_created=True,
                created_version=created_version,
                agent_output_valid=False,
            )

        try:
            structured_result = normalize_foundry_agent_intake_response(output_text)
        except FoundryExtractionParseError:
            return FoundryAgentDeploymentResult.failure(
                "response_parse_failed",
                agent_created=True,
                agent_invoked=True,
                agent_output_valid=False,
                created_version=created_version,
            )
        except FoundryExtractionContractError:
            return FoundryAgentDeploymentResult.failure(
                "contract_invalid",
                agent_created=True,
                agent_invoked=True,
                agent_output_valid=False,
                created_version=created_version,
            )
        except Exception:
            return FoundryAgentDeploymentResult.failure(
                "unexpected_error",
                agent_created=True,
                agent_invoked=True,
                agent_output_valid=False,
                created_version=created_version,
            )

        validation = validate_nurse_intake_agent_result(
            SimpleNamespace(
                extraction=structured_result.extraction,
                urgency=structured_result.urgency,
                handoffNote="Application-side nurse handoff formatting available.",
            )
        )
        if not validation.is_valid:
            return FoundryAgentDeploymentResult.failure(
                "contract_invalid",
                agent_created=True,
                agent_invoked=True,
                agent_output_valid=False,
                created_version=created_version,
            )

        return FoundryAgentDeploymentResult.success(
            created_version=created_version,
            fields_present=["extraction", "urgency"],
        )


def foundry_agent_deployment_sdk_available() -> bool:
    try:
        return (
            find_spec("azure.ai.projects") is not None
            and find_spec("azure.identity") is not None
            and find_spec("openai") is not None
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


def _create_prompt_agent_definition(**kwargs: str) -> Any:
    from azure.ai.projects.models import PromptAgentDefinition

    return PromptAgentDefinition(**kwargs)


def _object_value(value: Any, name: str) -> str:
    if isinstance(value, dict):
        raw_value = value.get(name)
    else:
        raw_value = getattr(value, name, None)
    return str(raw_value).strip() if raw_value is not None else ""


def _category_for_exception(
    error: BaseException,
    fallback: DeploymentCategory,
) -> DeploymentCategory:
    for current in _exception_chain(error):
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
