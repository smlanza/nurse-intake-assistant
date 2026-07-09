from dataclasses import dataclass, field
from importlib.util import find_spec
from typing import Any, Protocol

from src.app.config.settings import AppSettings


FOUNDRY_AGENT_CLIENT_UNAVAILABLE_MESSAGE = (
    "Azure AI Foundry Agent client is not configured or SDK support is not available."
)
FOUNDRY_AGENT_CLIENT_REQUEST_FAILED_MESSAGE = (
    "Azure AI Foundry Agent client request failed."
)
FOUNDRY_AGENT_CLIENT_NOT_WIRED_MESSAGE = (
    "Azure AI Foundry Agent live invocation is scaffolded but not wired yet."
)
FOUNDRY_AGENT_MISSING_CONFIGURATION_CATEGORY = (
    "foundry-agent-missing-configuration"
)
FOUNDRY_AGENT_SDK_UNAVAILABLE_CATEGORY = "foundry-agent-sdk-unavailable"
FOUNDRY_AGENT_REQUEST_FAILED_CATEGORY = "foundry-agent-request-failed"
FOUNDRY_AGENT_NOT_WIRED_CATEGORY = "foundry-agent-not-wired"
FOUNDRY_AGENT_PHASE_SDK_IMPORT = "sdk_import"
FOUNDRY_AGENT_PHASE_CREDENTIAL_CREATION = "credential_creation"
FOUNDRY_AGENT_PHASE_CLIENT_CREATION = "client_creation"
FOUNDRY_AGENT_PHASE_AGENT_INVOCATION = "agent_invocation"
FOUNDRY_AGENT_PHASE_RESPONSE_EXTRACTION = "response_extraction"
FOUNDRY_AGENT_PHASE_RESPONSE_PARSING = "response_parsing"
FOUNDRY_AGENT_PHASE_NOT_WIRED = "not_wired"
FOUNDRY_AGENT_PHASE_UNKNOWN = "unknown"


@dataclass(frozen=True)
class FoundryAgentRequest:
    """Input contract for future Foundry Agent orchestration."""

    intake_text: str
    instructions: str
    correlation_id: str | None = None


@dataclass(frozen=True)
class FoundryAgentResponse:
    """Output contract returned by Foundry Agent client implementations."""

    content: str
    metadata: dict[str, str] = field(default_factory=dict)


class FoundryAgentClient(Protocol):
    async def invoke_agent(
        self,
        request: FoundryAgentRequest,
    ) -> FoundryAgentResponse:
        """Invoke the configured Foundry Agent boundary."""


class FoundryAgentClientError(RuntimeError):
    """Safe diagnostic for Foundry Agent client setup or invocation failures."""

    def __init__(
        self,
        message: str,
        *,
        category: str,
        phase: str = FOUNDRY_AGENT_PHASE_UNKNOWN,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.phase = phase


class FakeFoundryAgentClient:
    """Deterministic fake Foundry Agent client for offline tests."""

    def __init__(
        self,
        response: FoundryAgentResponse | None = None,
    ) -> None:
        self.response = response or FoundryAgentResponse(
            content="Fake Foundry Agent response for local nurse review.",
            metadata={
                "provider": "foundry-agent",
                "agentMode": "fake",
            },
        )
        self.requests: list[FoundryAgentRequest] = []

    async def invoke_agent(
        self,
        request: FoundryAgentRequest,
    ) -> FoundryAgentResponse:
        self.requests.append(request)
        return self.response


class AzureAiFoundryAgentLiveClient:
    """Opt-in live Azure AI Foundry Agent invocation boundary."""

    def __init__(self, project_endpoint: str, agent_id: str) -> None:
        self.project_endpoint = project_endpoint
        self.agent_id = agent_id
        self._agents_client = None

    async def invoke_agent(
        self,
        request: FoundryAgentRequest,
    ) -> FoundryAgentResponse:
        try:
            agents_client = self._get_agents_client()
            return await self._invoke_with_client(agents_client, request)
        except FoundryAgentClientError:
            raise
        except Exception as exc:
            raise FoundryAgentClientError(
                FOUNDRY_AGENT_CLIENT_REQUEST_FAILED_MESSAGE,
                category=FOUNDRY_AGENT_REQUEST_FAILED_CATEGORY,
                phase=FOUNDRY_AGENT_PHASE_AGENT_INVOCATION,
            ) from exc

    def _get_agents_client(self):
        if self._agents_client is None:
            self._agents_client = _create_agents_client(self.project_endpoint)
        return self._agents_client

    async def _invoke_with_client(
        self,
        agents_client: Any,
        request: FoundryAgentRequest,
    ) -> FoundryAgentResponse:
        thread_id = _create_agent_thread(agents_client)
        _create_agent_message(
            agents_client,
            thread_id,
            _build_agent_user_message(request),
        )
        run = _process_agent_run(agents_client, thread_id, self.agent_id)
        _raise_for_unsuccessful_run(run)
        content = _extract_agent_response_text(agents_client, thread_id)

        return FoundryAgentResponse(
            content=content,
            metadata={
                "provider": "foundry-agent",
                "agentMode": "live",
            },
        )


def create_foundry_agent_client(
    settings: AppSettings,
    *,
    client: FoundryAgentClient | None = None,
    enable_live: bool = False,
) -> FoundryAgentClient | None:
    """Create the Foundry Agent client only for explicit fake/live paths."""

    if client is not None:
        return client

    if settings.agent_provider_normalized not in {"foundry", "foundry-agent"}:
        return None

    if not enable_live:
        return None

    project_endpoint = _required_agent_setting(
        _agent_project_endpoint(settings),
        "AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT",
    )
    agent_id = _required_agent_setting(
        settings.azure_ai_foundry_agent_id,
        "AZURE_AI_FOUNDRY_AGENT_ID",
    )

    if not foundry_agent_sdk_available():
        raise FoundryAgentClientError(
            FOUNDRY_AGENT_CLIENT_UNAVAILABLE_MESSAGE,
            category=FOUNDRY_AGENT_SDK_UNAVAILABLE_CATEGORY,
            phase=FOUNDRY_AGENT_PHASE_SDK_IMPORT,
        )

    return AzureAiFoundryAgentLiveClient(
        project_endpoint=project_endpoint,
        agent_id=agent_id,
    )


def foundry_agent_sdk_available() -> bool:
    """Return whether optional Foundry Agent SDK imports appear available."""

    try:
        return (
            find_spec("azure.ai.agents") is not None
            and find_spec("azure.identity") is not None
        )
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def _agent_project_endpoint(settings: AppSettings) -> str | None:
    return (
        settings.azure_ai_foundry_agent_project_endpoint
        or settings.azure_ai_foundry_project_endpoint
    )


def _required_agent_setting(value: str | None, name: str) -> str:
    if value is None:
        raise FoundryAgentClientError(
            f"{name} is required for explicit Azure AI Foundry Agent client creation.",
            category=FOUNDRY_AGENT_MISSING_CONFIGURATION_CATEGORY,
            phase=FOUNDRY_AGENT_PHASE_UNKNOWN,
        )
    return value


def _create_agents_client(project_endpoint: str):
    try:
        AgentsClient = _get_agents_client_class()
        DefaultAzureCredential = _get_default_credential_class()
        try:
            credential = DefaultAzureCredential()
        except Exception as exc:
            raise FoundryAgentClientError(
                FOUNDRY_AGENT_CLIENT_UNAVAILABLE_MESSAGE,
                category=FOUNDRY_AGENT_SDK_UNAVAILABLE_CATEGORY,
                phase=FOUNDRY_AGENT_PHASE_CREDENTIAL_CREATION,
            ) from exc
        return AgentsClient(
            endpoint=project_endpoint,
            credential=credential,
        )
    except FoundryAgentClientError:
        raise
    except Exception as exc:
        raise FoundryAgentClientError(
            FOUNDRY_AGENT_CLIENT_REQUEST_FAILED_MESSAGE,
            category=FOUNDRY_AGENT_REQUEST_FAILED_CATEGORY,
            phase=FOUNDRY_AGENT_PHASE_CLIENT_CREATION,
        ) from exc


def _get_agents_client_class():
    try:
        from azure.ai.agents import AgentsClient
    except ImportError as exc:
        raise FoundryAgentClientError(
            FOUNDRY_AGENT_CLIENT_UNAVAILABLE_MESSAGE,
            category=FOUNDRY_AGENT_SDK_UNAVAILABLE_CATEGORY,
            phase=FOUNDRY_AGENT_PHASE_SDK_IMPORT,
        ) from exc
    return AgentsClient


def _get_default_credential_class():
    try:
        from azure.identity import DefaultAzureCredential
    except ImportError as exc:
        raise FoundryAgentClientError(
            FOUNDRY_AGENT_CLIENT_UNAVAILABLE_MESSAGE,
            category=FOUNDRY_AGENT_SDK_UNAVAILABLE_CATEGORY,
            phase=FOUNDRY_AGENT_PHASE_SDK_IMPORT,
        ) from exc
    return DefaultAzureCredential


def _build_agent_user_message(request: FoundryAgentRequest) -> str:
    return "\n\n".join(
        [
            request.instructions,
            "Fictional patient intake text:",
            request.intake_text,
            "Return only the JSON object required by the instructions.",
        ]
    )


def _create_agent_thread(agents_client: Any) -> str:
    try:
        thread = agents_client.threads.create()
    except Exception as exc:
        raise FoundryAgentClientError(
            FOUNDRY_AGENT_CLIENT_REQUEST_FAILED_MESSAGE,
            category=FOUNDRY_AGENT_REQUEST_FAILED_CATEGORY,
            phase=FOUNDRY_AGENT_PHASE_AGENT_INVOCATION,
        ) from exc

    thread_id = _safe_object_value(thread, "id")
    if not thread_id:
        raise FoundryAgentClientError(
            FOUNDRY_AGENT_CLIENT_REQUEST_FAILED_MESSAGE,
            category=FOUNDRY_AGENT_REQUEST_FAILED_CATEGORY,
            phase=FOUNDRY_AGENT_PHASE_RESPONSE_EXTRACTION,
        )
    return thread_id


def _create_agent_message(
    agents_client: Any,
    thread_id: str,
    content: str,
) -> None:
    try:
        agents_client.messages.create(
            thread_id=thread_id,
            role="user",
            content=content,
        )
    except Exception as exc:
        raise FoundryAgentClientError(
            FOUNDRY_AGENT_CLIENT_REQUEST_FAILED_MESSAGE,
            category=FOUNDRY_AGENT_REQUEST_FAILED_CATEGORY,
            phase=FOUNDRY_AGENT_PHASE_AGENT_INVOCATION,
        ) from exc


def _process_agent_run(
    agents_client: Any,
    thread_id: str,
    agent_id: str,
) -> Any:
    try:
        return agents_client.runs.create_and_process(
            thread_id=thread_id,
            agent_id=agent_id,
        )
    except Exception as exc:
        raise FoundryAgentClientError(
            FOUNDRY_AGENT_CLIENT_REQUEST_FAILED_MESSAGE,
            category=FOUNDRY_AGENT_REQUEST_FAILED_CATEGORY,
            phase=FOUNDRY_AGENT_PHASE_AGENT_INVOCATION,
        ) from exc


def _raise_for_unsuccessful_run(run: Any) -> None:
    status = _safe_object_value(run, "status")
    if status.casefold() in {"failed", "cancelled", "canceled", "expired"}:
        raise FoundryAgentClientError(
            FOUNDRY_AGENT_CLIENT_REQUEST_FAILED_MESSAGE,
            category=FOUNDRY_AGENT_REQUEST_FAILED_CATEGORY,
            phase=FOUNDRY_AGENT_PHASE_AGENT_INVOCATION,
        )


def _extract_agent_response_text(agents_client: Any, thread_id: str) -> str:
    try:
        text_content_reader = getattr(
            agents_client.messages,
            "get_last_message_text_by_role",
            None,
        )
        if callable(text_content_reader):
            content = _text_from_unknown_value(
                text_content_reader(thread_id=thread_id, role="assistant")
            )
            if content:
                return content

        messages = agents_client.messages.list(thread_id=thread_id)
        content = _text_from_message_collection(messages)
    except Exception as exc:
        raise FoundryAgentClientError(
            FOUNDRY_AGENT_CLIENT_REQUEST_FAILED_MESSAGE,
            category=FOUNDRY_AGENT_REQUEST_FAILED_CATEGORY,
            phase=FOUNDRY_AGENT_PHASE_RESPONSE_EXTRACTION,
        ) from exc

    if not content:
        raise FoundryAgentClientError(
            FOUNDRY_AGENT_CLIENT_REQUEST_FAILED_MESSAGE,
            category=FOUNDRY_AGENT_REQUEST_FAILED_CATEGORY,
            phase=FOUNDRY_AGENT_PHASE_RESPONSE_EXTRACTION,
        )
    return content


def _text_from_message_collection(messages: Any) -> str:
    for message in _iter_message_values(messages):
        role = _safe_object_value(message, "role")
        if role and role.casefold() != "assistant":
            continue
        content = _text_from_unknown_value(_value_at(message, "content"))
        if content:
            return content
    return ""


def _iter_message_values(messages: Any):
    data = _value_at(messages, "data")
    iterable = data if data is not None else messages
    if isinstance(iterable, dict):
        iterable = iterable.values()

    try:
        yield from iterable
    except TypeError:
        return


def _text_from_unknown_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("value", "text", "content"):
            content = _text_from_unknown_value(value.get(key))
            if content:
                return content
        return ""
    if isinstance(value, (list, tuple)):
        for item in value:
            content = _text_from_unknown_value(item)
            if content:
                return content
        return ""

    for key in ("value", "text", "content"):
        content = _text_from_unknown_value(_value_at(value, key))
        if content:
            return content
    return ""


def _safe_object_value(value: Any, name: str) -> str:
    raw_value = _value_at(value, name)
    if raw_value is None:
        return ""
    return str(raw_value).strip()


def _value_at(value: Any, name: str) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)
