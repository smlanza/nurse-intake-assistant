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


@dataclass(frozen=True)
class FoundryAgentRequest:
    """Input contract for future Foundry Agent orchestration."""

    intake_text: str
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

    def __init__(self, message: str, *, category: str) -> None:
        super().__init__(message)
        self.category = category


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
    """Opt-in scaffold for future live Azure AI Foundry Agent invocation."""

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
        raise FoundryAgentClientError(
            FOUNDRY_AGENT_CLIENT_NOT_WIRED_MESSAGE,
            category=FOUNDRY_AGENT_NOT_WIRED_CATEGORY,
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
        )
    return value


def _create_agents_client(project_endpoint: str):
    try:
        AgentsClient = _get_agents_client_class()
        DefaultAzureCredential = _get_default_credential_class()
        return AgentsClient(
            endpoint=project_endpoint,
            credential=DefaultAzureCredential(),
        )
    except FoundryAgentClientError:
        raise
    except Exception as exc:
        raise FoundryAgentClientError(
            FOUNDRY_AGENT_CLIENT_UNAVAILABLE_MESSAGE,
            category=FOUNDRY_AGENT_SDK_UNAVAILABLE_CATEGORY,
        ) from exc


def _get_agents_client_class():
    try:
        from azure.ai.agents import AgentsClient
    except ImportError as exc:
        raise FoundryAgentClientError(
            FOUNDRY_AGENT_CLIENT_UNAVAILABLE_MESSAGE,
            category=FOUNDRY_AGENT_SDK_UNAVAILABLE_CATEGORY,
        ) from exc
    return AgentsClient


def _get_default_credential_class():
    try:
        from azure.identity import DefaultAzureCredential
    except ImportError as exc:
        raise FoundryAgentClientError(
            FOUNDRY_AGENT_CLIENT_UNAVAILABLE_MESSAGE,
            category=FOUNDRY_AGENT_SDK_UNAVAILABLE_CATEGORY,
        ) from exc
    return DefaultAzureCredential
