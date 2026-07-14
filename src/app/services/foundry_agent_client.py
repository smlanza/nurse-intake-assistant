from dataclasses import dataclass, field
from importlib.util import find_spec
from typing import Any, Protocol
from urllib.parse import urlsplit

from src.app.config.settings import AppSettings
from src.app.services.foundry_credential_factory import (
    FoundryCredentialConfiguration,
    FoundryCredentialFactory,
)


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
FOUNDRY_AGENT_STABLE_ENDPOINT_MISSING_CATEGORY = "stable_endpoint_missing"
FOUNDRY_AGENT_STABLE_ENDPOINT_INVALID_CATEGORY = "stable_endpoint_invalid"
FOUNDRY_AGENT_STABLE_ENDPOINT_MISMATCH_CATEGORY = "stable_endpoint_mismatch"
FOUNDRY_AGENT_STABLE_ENDPOINT_REQUEST_FAILED_CATEGORY = (
    "stable_endpoint_request_failed"
)
FOUNDRY_AGENT_STABLE_ENDPOINT_MODE = "stable_agent_endpoint"
FOUNDRY_AGENT_PROJECT_ENDPOINT_COMPATIBILITY_MODE = (
    "project_endpoint_compatibility"
)
FOUNDRY_AGENT_PHASE_SDK_IMPORT = "sdk_import"
FOUNDRY_AGENT_PHASE_CREDENTIAL_CREATION = "credential_creation"
FOUNDRY_AGENT_PHASE_CLIENT_CREATION = "client_creation"
FOUNDRY_AGENT_PHASE_AGENT_REFERENCE_CREATION = "agent_reference_creation"
FOUNDRY_AGENT_PHASE_AGENT_INVOCATION = "agent_invocation"
FOUNDRY_AGENT_PHASE_RESPONSE_CREATION = "response_creation"
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

    def __init__(
        self,
        project_endpoint: str | None,
        agent_name: str,
        agent_version: str,
        managed_identity_client_id: str | None = None,
        credential_factory: FoundryCredentialFactory | None = None,
        stable_agent_endpoint: str | None = None,
    ) -> None:
        self.project_endpoint = project_endpoint
        self.stable_agent_endpoint = stable_agent_endpoint
        self.agent_name = agent_name
        self.agent_version = agent_version
        self.managed_identity_client_id = managed_identity_client_id
        self.credential_factory = credential_factory
        self.invocation_mode = (
            FOUNDRY_AGENT_STABLE_ENDPOINT_MODE
            if stable_agent_endpoint is not None
            else FOUNDRY_AGENT_PROJECT_ENDPOINT_COMPATIBILITY_MODE
        )
        self._responses_client = None

    async def invoke_agent(
        self,
        request: FoundryAgentRequest,
    ) -> FoundryAgentResponse:
        try:
            responses_client = self._get_responses_client()
            return await self._invoke_with_client(responses_client, request)
        except FoundryAgentClientError as exc:
            if (
                self.stable_agent_endpoint is not None
                and exc.category == FOUNDRY_AGENT_REQUEST_FAILED_CATEGORY
            ):
                raise FoundryAgentClientError(
                    FOUNDRY_AGENT_CLIENT_REQUEST_FAILED_MESSAGE,
                    category=FOUNDRY_AGENT_STABLE_ENDPOINT_REQUEST_FAILED_CATEGORY,
                    phase=exc.phase,
                ) from exc
            raise
        except Exception as exc:
            raise FoundryAgentClientError(
                FOUNDRY_AGENT_CLIENT_REQUEST_FAILED_MESSAGE,
                category=FOUNDRY_AGENT_REQUEST_FAILED_CATEGORY,
                phase=FOUNDRY_AGENT_PHASE_RESPONSE_CREATION,
            ) from exc

    def _get_responses_client(self):
        if self._responses_client is None:
            if self.stable_agent_endpoint is not None:
                self._responses_client = _create_stable_responses_client(
                    stable_agent_endpoint=self.stable_agent_endpoint,
                    project_endpoint=self.project_endpoint,
                    agent_name=self.agent_name,
                    managed_identity_client_id=self.managed_identity_client_id,
                    credential_factory=self.credential_factory,
                )
            else:
                if self.project_endpoint is None:
                    raise FoundryAgentClientError(
                        FOUNDRY_AGENT_CLIENT_UNAVAILABLE_MESSAGE,
                        category=FOUNDRY_AGENT_MISSING_CONFIGURATION_CATEGORY,
                    )
                self._responses_client = _create_project_responses_client(
                    self.project_endpoint,
                    self.agent_name,
                    self.agent_version,
                    self.managed_identity_client_id,
                    credential_factory=self.credential_factory,
                )
        return self._responses_client

    async def _invoke_with_client(
        self,
        responses_client: Any,
        request: FoundryAgentRequest,
    ) -> FoundryAgentResponse:
        response = _create_project_agent_response(
            responses_client,
            _build_agent_user_message(request),
        )
        content = _extract_response_output_text(response)

        return FoundryAgentResponse(
            content=content,
            metadata={
                "provider": "foundry-agent",
                "agentMode": "live",
                "endpointMode": self.invocation_mode,
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

    stable_agent_endpoint = getattr(
        settings,
        "azure_ai_foundry_agent_endpoint",
        None,
    )
    compatibility_setting = getattr(
        settings,
        "azure_ai_foundry_agent_use_project_endpoint_compatibility",
        None,
    )
    use_project_endpoint_compatibility = compatibility_setting is True
    project_endpoint = getattr(
        settings,
        "azure_ai_foundry_agent_project_endpoint",
        None,
    )
    if stable_agent_endpoint is not None:
        if not is_valid_stable_agent_endpoint(stable_agent_endpoint):
            raise FoundryAgentClientError(
                FOUNDRY_AGENT_CLIENT_UNAVAILABLE_MESSAGE,
                category=FOUNDRY_AGENT_STABLE_ENDPOINT_INVALID_CATEGORY,
                phase=FOUNDRY_AGENT_PHASE_UNKNOWN,
            )
        project_endpoint = _required_agent_setting(
            project_endpoint,
            "AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT",
        )
        configured_agent_name = _required_agent_setting(
            settings.azure_ai_foundry_agent_name,
            "AZURE_AI_FOUNDRY_AGENT_NAME",
        )
        if not stable_agent_endpoint_matches_configuration(
            project_endpoint=project_endpoint,
            stable_agent_endpoint=stable_agent_endpoint,
            agent_name=configured_agent_name,
        ):
            raise FoundryAgentClientError(
                FOUNDRY_AGENT_CLIENT_UNAVAILABLE_MESSAGE,
                category=FOUNDRY_AGENT_STABLE_ENDPOINT_MISMATCH_CATEGORY,
                phase=FOUNDRY_AGENT_PHASE_UNKNOWN,
            )
    elif use_project_endpoint_compatibility:
        project_endpoint = _required_agent_setting(
            project_endpoint,
            "AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT",
        )
    else:
        raise FoundryAgentClientError(
            FOUNDRY_AGENT_CLIENT_UNAVAILABLE_MESSAGE,
            category=FOUNDRY_AGENT_STABLE_ENDPOINT_MISSING_CATEGORY,
            phase=FOUNDRY_AGENT_PHASE_UNKNOWN,
        )

    agent_name = _required_agent_setting(
        settings.azure_ai_foundry_agent_name,
        "AZURE_AI_FOUNDRY_AGENT_NAME",
    )
    agent_version = _required_agent_setting(
        settings.azure_ai_foundry_agent_version,
        "AZURE_AI_FOUNDRY_AGENT_VERSION",
    )

    if not foundry_agent_sdk_available():
        raise FoundryAgentClientError(
            FOUNDRY_AGENT_CLIENT_UNAVAILABLE_MESSAGE,
            category=FOUNDRY_AGENT_SDK_UNAVAILABLE_CATEGORY,
            phase=FOUNDRY_AGENT_PHASE_SDK_IMPORT,
        )

    return AzureAiFoundryAgentLiveClient(
        project_endpoint=project_endpoint,
        stable_agent_endpoint=stable_agent_endpoint,
        agent_name=agent_name,
        agent_version=agent_version,
        managed_identity_client_id=getattr(
            settings,
            "azure_ai_foundry_managed_identity_client_id",
            None,
        ),
    )


def foundry_agent_sdk_available() -> bool:
    """Return whether optional Foundry Agent SDK imports appear available."""

    try:
        return (
            find_spec("azure.ai.projects") is not None
            and find_spec("azure.identity") is not None
            and find_spec("openai") is not None
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


def is_valid_stable_agent_endpoint(value: str | None) -> bool:
    """Validate the complete per-agent OpenAI protocol base without I/O."""

    normalized = _normalized_https_endpoint(value)
    if normalized is None:
        return False
    _, path_parts = normalized
    return (
        len(path_parts) >= 5
        and path_parts[-5] == "agents"
        and path_parts[-3:] == ["endpoint", "protocols", "openai"]
    )


def stable_agent_endpoint_matches_configuration(
    *,
    project_endpoint: str | None,
    stable_agent_endpoint: str | None,
    agent_name: str | None,
) -> bool:
    """Bind a stable endpoint to the configured project and exact agent name."""

    project = _normalized_https_endpoint(project_endpoint)
    stable = _normalized_https_endpoint(stable_agent_endpoint)
    if project is None or stable is None:
        return False
    if (
        not isinstance(agent_name, str)
        or not agent_name
        or any(character in agent_name for character in "/\\%")
        or agent_name in {".", ".."}
    ):
        return False
    project_host, project_parts = project
    stable_host, stable_parts = stable
    expected_stable_parts = project_parts + [
        "agents",
        agent_name,
        "endpoint",
        "protocols",
        "openai",
    ]
    return stable_host == project_host and stable_parts == expected_stable_parts


def _normalized_https_endpoint(
    value: str | None,
) -> tuple[str, list[str]] | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = urlsplit(value.strip())
        port = parsed.port
    except ValueError:
        return None
    raw_path = parsed.path
    normalized_path = raw_path[:-1] if raw_path.endswith("/") else raw_path
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or port is not None
        or "%" in parsed.netloc
        or "%" in raw_path
        or "\\" in raw_path
        or not normalized_path.startswith("/")
        or "//" in normalized_path
    ):
        return None
    path_parts = normalized_path[1:].split("/")
    if not path_parts or any(part in {"", ".", ".."} for part in path_parts):
        return None
    return parsed.hostname.lower(), path_parts


def _create_agents_client(
    project_endpoint: str,
    managed_identity_client_id: str | None = None,
    *,
    credential_factory: FoundryCredentialFactory | None = None,
):
    try:
        AgentsClient = _get_agents_client_class()
        try:
            factory = credential_factory or FoundryCredentialFactory(
                credential_constructor=_get_default_credential_class()
            )
            credential = factory.create(
                FoundryCredentialConfiguration(managed_identity_client_id)
            )
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


def _create_project_responses_client(
    project_endpoint: str,
    agent_name: str,
    agent_version: str,
    managed_identity_client_id: str | None = None,
    *,
    credential_factory: FoundryCredentialFactory | None = None,
):
    try:
        AIProjectClient = _get_ai_project_client_class()
        try:
            factory = credential_factory or FoundryCredentialFactory(
                credential_constructor=_get_default_credential_class()
            )
            credential = factory.create(
                FoundryCredentialConfiguration(managed_identity_client_id)
            )
        except Exception as exc:
            raise FoundryAgentClientError(
                FOUNDRY_AGENT_CLIENT_UNAVAILABLE_MESSAGE,
                category=FOUNDRY_AGENT_SDK_UNAVAILABLE_CATEGORY,
                phase=FOUNDRY_AGENT_PHASE_CREDENTIAL_CREATION,
            ) from exc
        try:
            project_client = AIProjectClient(
                endpoint=project_endpoint,
                credential=credential,
                allow_preview=True,
            )
        except Exception as exc:
            raise FoundryAgentClientError(
                FOUNDRY_AGENT_CLIENT_REQUEST_FAILED_MESSAGE,
                category=FOUNDRY_AGENT_REQUEST_FAILED_CATEGORY,
                phase=FOUNDRY_AGENT_PHASE_CLIENT_CREATION,
            ) from exc
        try:
            return project_client.get_openai_client(
                agent_name=agent_name,
                default_query={"agentVersion": agent_version},
            )
        except Exception as exc:
            raise FoundryAgentClientError(
                FOUNDRY_AGENT_CLIENT_REQUEST_FAILED_MESSAGE,
                category=FOUNDRY_AGENT_REQUEST_FAILED_CATEGORY,
                phase=FOUNDRY_AGENT_PHASE_AGENT_REFERENCE_CREATION,
            ) from exc
    except FoundryAgentClientError:
        raise
    except Exception as exc:
        raise FoundryAgentClientError(
            FOUNDRY_AGENT_CLIENT_REQUEST_FAILED_MESSAGE,
            category=FOUNDRY_AGENT_REQUEST_FAILED_CATEGORY,
            phase=FOUNDRY_AGENT_PHASE_CLIENT_CREATION,
        ) from exc


def _create_stable_responses_client(
    *,
    stable_agent_endpoint: str,
    agent_name: str,
    project_endpoint: str,
    managed_identity_client_id: str | None = None,
    credential_factory: FoundryCredentialFactory | None = None,
    project_client_class: Any | None = None,
):
    """Create an SDK-supported OpenAI client at the configured agent base URL."""

    if not is_valid_stable_agent_endpoint(stable_agent_endpoint):
        raise FoundryAgentClientError(
            FOUNDRY_AGENT_CLIENT_UNAVAILABLE_MESSAGE,
            category=FOUNDRY_AGENT_STABLE_ENDPOINT_INVALID_CATEGORY,
            phase=FOUNDRY_AGENT_PHASE_CLIENT_CREATION,
        )
    if not stable_agent_endpoint_matches_configuration(
        project_endpoint=project_endpoint,
        stable_agent_endpoint=stable_agent_endpoint,
        agent_name=agent_name,
    ):
        raise FoundryAgentClientError(
            FOUNDRY_AGENT_CLIENT_UNAVAILABLE_MESSAGE,
            category=FOUNDRY_AGENT_STABLE_ENDPOINT_MISMATCH_CATEGORY,
            phase=FOUNDRY_AGENT_PHASE_CLIENT_CREATION,
        )
    try:
        AIProjectClient = project_client_class or _get_ai_project_client_class()
        try:
            factory = credential_factory or FoundryCredentialFactory(
                credential_constructor=_get_default_credential_class()
            )
            credential = factory.create(
                FoundryCredentialConfiguration(managed_identity_client_id)
            )
        except Exception as exc:
            raise FoundryAgentClientError(
                FOUNDRY_AGENT_CLIENT_UNAVAILABLE_MESSAGE,
                category=FOUNDRY_AGENT_SDK_UNAVAILABLE_CATEGORY,
                phase=FOUNDRY_AGENT_PHASE_CREDENTIAL_CREATION,
            ) from exc
        try:
            project_client = AIProjectClient(
                endpoint=project_endpoint,
                credential=credential,
                allow_preview=True,
            )
            return project_client.get_openai_client(agent_name=agent_name)
        except Exception as exc:
            raise FoundryAgentClientError(
                FOUNDRY_AGENT_CLIENT_REQUEST_FAILED_MESSAGE,
                category=FOUNDRY_AGENT_STABLE_ENDPOINT_REQUEST_FAILED_CATEGORY,
                phase=FOUNDRY_AGENT_PHASE_CLIENT_CREATION,
            ) from exc
    except FoundryAgentClientError:
        raise
    except Exception as exc:
        raise FoundryAgentClientError(
            FOUNDRY_AGENT_CLIENT_REQUEST_FAILED_MESSAGE,
            category=FOUNDRY_AGENT_STABLE_ENDPOINT_REQUEST_FAILED_CATEGORY,
            phase=FOUNDRY_AGENT_PHASE_CLIENT_CREATION,
        ) from exc


def _get_ai_project_client_class():
    try:
        from azure.ai.projects import AIProjectClient
    except ImportError as exc:
        raise FoundryAgentClientError(
            FOUNDRY_AGENT_CLIENT_UNAVAILABLE_MESSAGE,
            category=FOUNDRY_AGENT_SDK_UNAVAILABLE_CATEGORY,
            phase=FOUNDRY_AGENT_PHASE_SDK_IMPORT,
        ) from exc
    return AIProjectClient


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


def _create_project_agent_response(
    responses_client: Any,
    content: str,
) -> Any:
    try:
        return responses_client.responses.create(input=content)
    except Exception as exc:
        raise FoundryAgentClientError(
            FOUNDRY_AGENT_CLIENT_REQUEST_FAILED_MESSAGE,
            category=FOUNDRY_AGENT_REQUEST_FAILED_CATEGORY,
            phase=FOUNDRY_AGENT_PHASE_RESPONSE_CREATION,
        ) from exc


def _extract_response_output_text(response: Any) -> str:
    try:
        content = _text_from_responses_output(response)
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


def _text_from_responses_output(response: Any) -> str:
    output_text = _safe_object_value(response, "output_text")
    if output_text:
        return output_text

    output = _value_at(response, "output")
    if isinstance(output, (list, tuple)):
        for item in output:
            content = _text_from_unknown_value(_value_at(item, "content"))
            if content:
                return content
            content = _text_from_unknown_value(item)
            if content:
                return content
    content = _text_from_unknown_value(_value_at(response, "content"))
    if content:
        return content
    return ""


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
