import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from importlib.util import find_spec
import json
import os
from typing import Any, Literal
from urllib.parse import urlsplit

from src.app.services.foundry_agent_client import (
    FOUNDRY_AGENT_PHASE_RESPONSE_EXTRACTION,
    AzureAiFoundryAgentLiveClient,
    FoundryAgentClientError,
    FoundryAgentRequest,
    FoundryAgentResponse,
    stable_agent_endpoint_matches_configuration,
)
from src.app.services.foundry_agent_contract import (
    normalize_foundry_agent_intake_response,
)
from src.app.services.foundry_extraction_contract import (
    FoundryExtractionContractError,
    FoundryExtractionParseError,
)
from src.app.services.nurse_handoff_note_formatter import NurseHandoffNoteFormatter
from src.app.services.nurse_intake_agent import (
    FoundryNurseIntakeAgent,
    NurseIntakeAgentMetadata,
    NurseIntakeAgentResult,
)
from src.app.services.nurse_intake_agent_contract import (
    validate_nurse_intake_agent_result,
)
from src.app.services.nurse_intake_agent_instructions import (
    build_nurse_intake_agent_fictional_test_input,
    build_nurse_intake_agent_instructions,
)


HostedInvocationMode = Literal["check", "live"]
HostedInvocationCategory = Literal[
    "check_complete",
    "success",
    "not_running_in_hosted_environment",
    "missing_configuration",
    "sdk_unavailable",
    "authentication_or_authorization_failed",
    "azure_request_failed",
    "response_parse_failed",
    "contract_invalid",
    "unexpected_error",
]

HOSTED_ENVIRONMENT_MARKERS = (
    "WEBSITE_INSTANCE_ID",
    "IDENTITY_ENDPOINT",
    "IDENTITY_HEADER",
)
APPROVED_RESULT_FIELDS = ("extraction", "urgency", "handoffNote")
SAFE_MESSAGES: dict[HostedInvocationCategory, str] = {
    "check_complete": "The hosted fictional invocation contract is locally valid.",
    "success": "One fictional agent response passed the application contract.",
    "not_running_in_hosted_environment": (
        "The required App Service managed-identity environment is unavailable."
    ),
    "missing_configuration": "The hosted fictional invocation configuration is invalid.",
    "sdk_unavailable": "Required hosted invocation SDK support is unavailable.",
    "authentication_or_authorization_failed": (
        "The managed identity could not authenticate or access the agent."
    ),
    "azure_request_failed": "The hosted fictional agent request failed.",
    "response_parse_failed": "The agent response could not be parsed safely.",
    "contract_invalid": "The agent response failed the application contract.",
    "unexpected_error": "The hosted fictional invocation failed safely.",
}
CHECK_NEXT_STEP = (
    "Complete the documented live prerequisites before explicit live invocation."
)
SUCCESS_NEXT_STEP = (
    "Retain human nurse review; this fictional proof is not clinical readiness."
)
FAILURE_NEXT_STEP = "Review the sanitized category before another proof attempt."


@dataclass(frozen=True)
class HostedFoundryAgentInvocationRequest:
    mode: str
    project_endpoint: str | None
    stable_agent_endpoint: str | None
    agent_name: str | None
    agent_version: str | None
    managed_identity_client_id: object | None
    instructions: str
    fictional_intake_text: str


@dataclass(frozen=True)
class HostedFoundryAgentInvocationResult:
    ok: bool
    category: HostedInvocationCategory
    message: str
    invocation_attempted: bool
    agent_output_valid: bool
    fields_present: tuple[str, ...]
    fictional_data_only: bool
    recommended_next_step: str

    @classmethod
    def check_complete(cls) -> "HostedFoundryAgentInvocationResult":
        return cls(
            ok=True,
            category="check_complete",
            message=SAFE_MESSAGES["check_complete"],
            invocation_attempted=False,
            agent_output_valid=False,
            fields_present=(),
            fictional_data_only=True,
            recommended_next_step=CHECK_NEXT_STEP,
        )

    @classmethod
    def success(cls) -> "HostedFoundryAgentInvocationResult":
        return cls(
            ok=True,
            category="success",
            message=SAFE_MESSAGES["success"],
            invocation_attempted=True,
            agent_output_valid=True,
            fields_present=APPROVED_RESULT_FIELDS,
            fictional_data_only=True,
            recommended_next_step=SUCCESS_NEXT_STEP,
        )

    @classmethod
    def failure(
        cls,
        category: HostedInvocationCategory,
        *,
        invocation_attempted: bool = False,
    ) -> "HostedFoundryAgentInvocationResult":
        return cls(
            ok=False,
            category=category,
            message=SAFE_MESSAGES[category],
            invocation_attempted=invocation_attempted,
            agent_output_valid=False,
            fields_present=(),
            fictional_data_only=True,
            recommended_next_step=FAILURE_NEXT_STEP,
        )

    def to_json_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "category": self.category,
            "message": self.message,
            "invocation_attempted": self.invocation_attempted,
            "agent_output_valid": self.agent_output_valid,
            "fields_present": list(self.fields_present),
            "fictional_data_only": self.fictional_data_only,
            "recommended_next_step": self.recommended_next_step,
        }


def build_hosted_foundry_agent_invocation_request(
    settings: Any,
    *,
    mode: str,
) -> HostedFoundryAgentInvocationRequest:
    return HostedFoundryAgentInvocationRequest(
        mode=mode,
        project_endpoint=getattr(
            settings, "azure_ai_foundry_agent_project_endpoint", None
        ),
        stable_agent_endpoint=getattr(
            settings, "azure_ai_foundry_agent_endpoint", None
        ),
        agent_name=getattr(settings, "azure_ai_foundry_agent_name", None),
        agent_version=getattr(settings, "azure_ai_foundry_agent_version", None),
        managed_identity_client_id=getattr(
            settings, "azure_ai_foundry_managed_identity_client_id", None
        ),
        instructions=build_nurse_intake_agent_instructions(),
        fictional_intake_text=build_nurse_intake_agent_fictional_test_input(),
    )


def hosted_invocation_sdk_available() -> bool:
    try:
        return all(
            find_spec(module_name) is not None
            for module_name in ("azure.ai.projects", "azure.identity", "openai")
        )
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def create_system_assigned_managed_identity_credential() -> object:
    credential_class = _get_managed_identity_credential_class()
    return credential_class()


def _get_managed_identity_credential_class():
    from azure.identity import ManagedIdentityCredential

    return ManagedIdentityCredential


def _get_ai_project_client_class():
    from azure.ai.projects import AIProjectClient

    return AIProjectClient


class _OwnedStableInvocationClient:
    """Own the stable Responses and project clients as one operation resource."""

    def __init__(
        self,
        *,
        agent_client: AzureAiFoundryAgentLiveClient,
        responses_client: object,
        project_client: object,
    ) -> None:
        self._agent_client = agent_client
        self._responses_client = responses_client
        self._project_client = project_client

    async def invoke_agent(self, request: FoundryAgentRequest) -> FoundryAgentResponse:
        return await self._agent_client.invoke_agent(request)

    def close(self) -> None:
        _close_safely(self._responses_client)
        _close_safely(self._project_client)


def _create_owned_invocation_client(
    request: HostedFoundryAgentInvocationRequest,
    credential: object,
) -> _OwnedStableInvocationClient:
    project_client: object | None = None
    responses_client: object | None = None
    try:
        project_client_class = _get_ai_project_client_class()
        project_client = project_client_class(
            endpoint=request.project_endpoint,
            credential=credential,
            allow_preview=True,
        )
        responses_client = project_client.get_openai_client(
            agent_name=request.agent_name
        )
        agent_client = AzureAiFoundryAgentLiveClient(
            project_endpoint=request.project_endpoint,
            stable_agent_endpoint=request.stable_agent_endpoint,
            agent_name=request.agent_name,
            agent_version=request.agent_version,
        )
        agent_client._responses_client = responses_client
        return _OwnedStableInvocationClient(
            agent_client=agent_client,
            responses_client=responses_client,
            project_client=project_client,
        )
    except Exception:
        _close_safely(responses_client)
        _close_safely(project_client)
        raise


class HostedFoundryAgentInvocation:
    """Run one fixed fictional prompt-agent request from App Service identity."""

    def __init__(
        self,
        *,
        credential_factory: Callable[[], object] = (
            create_system_assigned_managed_identity_credential
        ),
        invocation_client_factory: Callable[
            [HostedFoundryAgentInvocationRequest, object], object
        ] = _create_owned_invocation_client,
        environment_reader: Callable[[str], object] = os.getenv,
        sdk_available: Callable[[], bool] = hosted_invocation_sdk_available,
    ) -> None:
        self._credential_factory = credential_factory
        self._invocation_client_factory = invocation_client_factory
        self._environment_reader = environment_reader
        self._sdk_available = sdk_available

    def check(
        self,
        request: HostedFoundryAgentInvocationRequest,
    ) -> HostedFoundryAgentInvocationResult:
        if not _request_contract_valid(request, expected_mode="check"):
            return HostedFoundryAgentInvocationResult.failure(
                "missing_configuration"
            )
        if not _fixed_contract_constructible(request):
            return HostedFoundryAgentInvocationResult.failure("contract_invalid")
        if not self._sdk_available():
            return HostedFoundryAgentInvocationResult.failure("sdk_unavailable")
        return HostedFoundryAgentInvocationResult.check_complete()

    def invoke(
        self,
        request: HostedFoundryAgentInvocationRequest,
    ) -> HostedFoundryAgentInvocationResult:
        if not _request_contract_valid(request, expected_mode="live"):
            return HostedFoundryAgentInvocationResult.failure(
                "missing_configuration"
            )
        if not _fixed_contract_constructible(request):
            return HostedFoundryAgentInvocationResult.failure("contract_invalid")
        if not self._sdk_available():
            return HostedFoundryAgentInvocationResult.failure("sdk_unavailable")
        if not _hosted_environment_valid(self._environment_reader):
            return HostedFoundryAgentInvocationResult.failure(
                "not_running_in_hosted_environment"
            )

        try:
            credential = self._credential_factory()
        except Exception as error:
            return HostedFoundryAgentInvocationResult.failure(
                _credential_failure_category(error)
            )

        invocation_client: object | None = None
        try:
            try:
                invocation_client = self._invocation_client_factory(
                    request, credential
                )
            except Exception as error:
                return HostedFoundryAgentInvocationResult.failure(
                    _request_failure_category(error)
                )

            invocation_attempted = True
            try:
                response = asyncio.run(
                    invocation_client.invoke_agent(
                        FoundryAgentRequest(
                            intake_text=request.fictional_intake_text,
                            instructions=request.instructions,
                        )
                    )
                )
            except Exception as error:
                return HostedFoundryAgentInvocationResult.failure(
                    _request_failure_category(error),
                    invocation_attempted=invocation_attempted,
                )

            if not isinstance(response, FoundryAgentResponse) or not (
                isinstance(response.content, str) and response.content.strip()
            ):
                return HostedFoundryAgentInvocationResult.failure(
                    "response_parse_failed",
                    invocation_attempted=invocation_attempted,
                )

            try:
                structured = normalize_foundry_agent_intake_response(
                    response.content
                )
            except FoundryExtractionParseError:
                return HostedFoundryAgentInvocationResult.failure(
                    "response_parse_failed",
                    invocation_attempted=invocation_attempted,
                )
            except FoundryExtractionContractError:
                if _json_envelope_is_non_object(response.content):
                    return HostedFoundryAgentInvocationResult.failure(
                        "response_parse_failed",
                        invocation_attempted=invocation_attempted,
                    )
                return HostedFoundryAgentInvocationResult.failure(
                    "contract_invalid",
                    invocation_attempted=invocation_attempted,
                )
            except Exception:
                return HostedFoundryAgentInvocationResult.failure(
                    "unexpected_error",
                    invocation_attempted=invocation_attempted,
                )

            try:
                handoff_note = _build_handoff_note(
                    request.fictional_intake_text,
                    structured.extraction,
                    structured.urgency,
                )
            except Exception:
                return HostedFoundryAgentInvocationResult.failure(
                    "unexpected_error",
                    invocation_attempted=invocation_attempted,
                )
            try:
                agent_result = NurseIntakeAgentResult(
                    extraction=structured.extraction,
                    urgency=structured.urgency,
                    handoffNote=handoff_note,
                    metadata=NurseIntakeAgentMetadata(
                        provider="foundry-agent",
                        agentMode="foundry-agent",
                    ),
                )
                validation = validate_nurse_intake_agent_result(agent_result)
            except Exception:
                return HostedFoundryAgentInvocationResult.failure(
                    "contract_invalid",
                    invocation_attempted=invocation_attempted,
                )
            if not validation.is_valid:
                return HostedFoundryAgentInvocationResult.failure(
                    "contract_invalid",
                    invocation_attempted=invocation_attempted,
                )
            return HostedFoundryAgentInvocationResult.success()
        finally:
            _close_safely(invocation_client)
            _close_safely(credential)


def _request_contract_valid(
    request: HostedFoundryAgentInvocationRequest,
    *,
    expected_mode: HostedInvocationMode,
) -> bool:
    return bool(
        request.mode == expected_mode
        and _present(request.project_endpoint)
        and _present(request.stable_agent_endpoint)
        and _present(request.agent_name)
        and _present(request.agent_version)
        and request.managed_identity_client_id is None
        and request.instructions == build_nurse_intake_agent_instructions()
        and request.fictional_intake_text
        == build_nurse_intake_agent_fictional_test_input()
        and stable_agent_endpoint_matches_configuration(
            project_endpoint=request.project_endpoint,
            stable_agent_endpoint=request.stable_agent_endpoint,
            agent_name=request.agent_name,
        )
    )


def _fixed_contract_constructible(
    request: HostedFoundryAgentInvocationRequest,
) -> bool:
    try:
        fixed_request = FoundryAgentRequest(
            intake_text=request.fictional_intake_text,
            instructions=request.instructions,
        )
        sample = normalize_foundry_agent_intake_response(
            json.dumps(
                {
                    "extraction": {
                        "patient": {
                            "name": "Fictional Contract Patient",
                            "date_of_birth": None,
                            "callback_number": "fictional-callback-check",
                        },
                        "reason_for_calling": "fictional routine callback",
                        "symptoms": ["mild fatigue"],
                        "summary": "Fictional contract summary.",
                        "missing_fields": ["date_of_birth"],
                        "uncertain_fields": [],
                    },
                    "urgency": {
                        "urgency": "Routine",
                        "urgency_rationale": "No urgent fictional signs reported.",
                        "advisory_disclaimer": "Human nurse review is required.",
                    },
                }
            )
        )
        handoff_note = _build_handoff_note(
            fixed_request.intake_text,
            sample.extraction,
            sample.urgency,
        )
        candidate = NurseIntakeAgentResult(
            extraction=sample.extraction,
            urgency=sample.urgency,
            handoffNote=handoff_note,
            metadata=NurseIntakeAgentMetadata(
                provider="foundry-agent", agentMode="foundry-agent"
            ),
        )
        return validate_nurse_intake_agent_result(candidate).is_valid
    except Exception:
        return False


def _build_handoff_note(
    fictional_intake_text: str,
    extraction: object,
    urgency: object,
) -> str:
    case = FoundryNurseIntakeAgent._build_handoff_case(
        fictional_intake_text,
        extraction,
        urgency,
    )
    return NurseHandoffNoteFormatter().format(case)


def _json_envelope_is_non_object(content: str) -> bool:
    try:
        return not isinstance(json.loads(content), dict)
    except (json.JSONDecodeError, TypeError):
        return False


def _hosted_environment_valid(reader: Callable[[str], object]) -> bool:
    instance = reader("WEBSITE_INSTANCE_ID")
    identity_endpoint = reader("IDENTITY_ENDPOINT")
    identity_header = reader("IDENTITY_HEADER")
    return bool(
        _safe_marker(instance)
        and _valid_identity_endpoint(identity_endpoint)
        and _safe_marker(identity_header)
    )


def _safe_marker(value: object) -> bool:
    return bool(
        isinstance(value, str)
        and value.strip()
        and not any(ord(character) < 32 or ord(character) == 127 for character in value)
    )


def _valid_identity_endpoint(value: object) -> bool:
    if not _safe_marker(value):
        return False
    try:
        parsed = urlsplit(value.strip())
        parsed.port
    except ValueError:
        return False
    return bool(
        parsed.scheme.lower() in {"http", "https"}
        and parsed.hostname
        and parsed.username is None
        and parsed.password is None
    )


def _present(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _credential_failure_category(
    error: BaseException,
) -> HostedInvocationCategory:
    for current in _exception_chain(error):
        if isinstance(current, (ImportError, ModuleNotFoundError)):
            return "sdk_unavailable"
        if _status_code(current) in {401, 403}:
            return "authentication_or_authorization_failed"
    return "authentication_or_authorization_failed"


def _request_failure_category(error: BaseException) -> HostedInvocationCategory:
    for current in _exception_chain(error):
        if isinstance(current, (ImportError, ModuleNotFoundError)):
            return "sdk_unavailable"
        if _status_code(current) in {401, 403}:
            return "authentication_or_authorization_failed"
        if isinstance(current, FoundryAgentClientError) and (
            current.phase == FOUNDRY_AGENT_PHASE_RESPONSE_EXTRACTION
        ):
            return "response_parse_failed"
    return "azure_request_failed"


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


def _close_safely(resource: object | None) -> None:
    if resource is None:
        return
    try:
        close = getattr(resource, "close", None)
        if callable(close):
            close()
    except Exception:
        pass
