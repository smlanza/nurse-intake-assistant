from importlib.util import find_spec


FOUNDRY_LIVE_CLIENT_UNAVAILABLE_MESSAGE = (
    "Azure AI Foundry live client is not configured or SDK support is not available."
)
FOUNDRY_LIVE_CLIENT_REQUEST_FAILED_MESSAGE = (
    "Azure AI Foundry live client request failed."
)
FOUNDRY_LIVE_CLIENT_EMPTY_RESPONSE_MESSAGE = (
    "Azure AI Foundry live client returned no response content."
)
FOUNDRY_LIVE_CLIENT_MODE = "foundry-project-endpoint"
FOUNDRY_LIVE_CLIENT_SUPPORTED_ENDPOINT_SHAPE = "services.ai.azure.com"
AZURE_OPENAI_LIVE_CLIENT_MODE = "azure-openai-endpoint"
AZURE_OPENAI_LIVE_CLIENT_SUPPORTED_ENDPOINT_SHAPE = "openai.azure.com"
AZURE_OPENAI_LIVE_CLIENT_UNAVAILABLE_MESSAGE = (
    "Azure OpenAI endpoint live client is not configured or SDK support is not available."
)
AZURE_OPENAI_LIVE_CLIENT_REQUEST_FAILED_MESSAGE = (
    "Azure OpenAI endpoint live client request failed."
)
AZURE_OPENAI_LIVE_CLIENT_EMPTY_RESPONSE_MESSAGE = (
    "Azure OpenAI endpoint live client returned no response content."
)
AZURE_OPENAI_AUTH_MODE = "entra-bearer-token-provider"
AZURE_OPENAI_TOKEN_SCOPE = "https://cognitiveservices.azure.com/.default"
AZURE_OPENAI_TOKEN_SCOPE_CATEGORY = "cognitiveservices.default"
AZURE_OPENAI_API_VERSION = "2024-10-21"
AZURE_OPENAI_TOKEN_PROVIDER_UNAVAILABLE_MESSAGE = (
    "Azure OpenAI endpoint token provider setup failed."
)

FOUNDRY_SYSTEM_MESSAGE = (
    "You are a structured extraction adapter for a nurse intake assistant. "
    "Return only the JSON requested by the user prompt."
)


class AzureAiFoundryLiveClient:
    """Opt-in scaffold for live Azure AI Foundry structured extraction.

    The current adapter uses the Azure AI Inference client with an Azure AI
    Foundry project endpoint. It does not implement the separate Azure OpenAI
    endpoint/client path.
    """

    def __init__(self, project_endpoint: str) -> None:
        self.project_endpoint = project_endpoint
        self._chat_client = None

    def complete_structured_extraction(
        self,
        prompt: str,
        model_deployment_name: str,
    ) -> str:
        """Return raw JSON text from a future live Foundry model response."""

        try:
            chat_client = self._get_chat_client()
            response = chat_client.complete(
                messages=_build_chat_messages(prompt),
                model=model_deployment_name,
            )
        except RuntimeError as exc:
            if str(exc) == FOUNDRY_LIVE_CLIENT_UNAVAILABLE_MESSAGE:
                raise
            raise RuntimeError(FOUNDRY_LIVE_CLIENT_REQUEST_FAILED_MESSAGE) from exc
        except Exception as exc:
            raise RuntimeError(FOUNDRY_LIVE_CLIENT_REQUEST_FAILED_MESSAGE) from exc

        content = _extract_response_content(response)
        if content is None or not content.strip():
            raise RuntimeError(FOUNDRY_LIVE_CLIENT_EMPTY_RESPONSE_MESSAGE)

        return content

    def _get_chat_client(self):
        if self._chat_client is None:
            self._chat_client = _create_chat_client(self.project_endpoint)
        return self._chat_client


def create_foundry_live_client(project_endpoint: str) -> AzureAiFoundryLiveClient:
    """Create the opt-in Foundry live adapter without constructing SDK clients."""

    return AzureAiFoundryLiveClient(project_endpoint=project_endpoint)


class AzureOpenAiEndpointLiveClient:
    """Opt-in Azure OpenAI endpoint smoke adapter using Entra credentials."""

    def __init__(self, azure_openai_endpoint: str) -> None:
        self.azure_openai_endpoint = azure_openai_endpoint
        self._chat_client = None

    def complete_structured_extraction(
        self,
        prompt: str,
        model_deployment_name: str,
    ) -> str:
        """Return raw JSON text from the Azure OpenAI endpoint smoke path."""

        try:
            chat_client = self._get_chat_client()
            response = chat_client.chat.completions.create(
                messages=_build_openai_chat_messages(prompt),
                model=model_deployment_name,
            )
        except RuntimeError as exc:
            if str(exc) in {
                AZURE_OPENAI_LIVE_CLIENT_UNAVAILABLE_MESSAGE,
                AZURE_OPENAI_TOKEN_PROVIDER_UNAVAILABLE_MESSAGE,
            }:
                raise
            raise RuntimeError(AZURE_OPENAI_LIVE_CLIENT_REQUEST_FAILED_MESSAGE) from exc
        except Exception as exc:
            raise RuntimeError(AZURE_OPENAI_LIVE_CLIENT_REQUEST_FAILED_MESSAGE) from exc

        content = _extract_response_content(response)
        if content is None or not content.strip():
            raise RuntimeError(AZURE_OPENAI_LIVE_CLIENT_EMPTY_RESPONSE_MESSAGE)

        return content

    def _get_chat_client(self):
        if self._chat_client is None:
            self._chat_client = _create_azure_openai_chat_client(
                self.azure_openai_endpoint
            )
        return self._chat_client


def create_azure_openai_live_client(
    azure_openai_endpoint: str,
) -> AzureOpenAiEndpointLiveClient:
    """Create the Azure OpenAI endpoint smoke adapter without constructing SDK clients."""

    return AzureOpenAiEndpointLiveClient(azure_openai_endpoint=azure_openai_endpoint)


def foundry_live_sdk_available() -> bool:
    """Return whether optional live Foundry SDK imports appear available."""

    return _chat_completions_sdk_available()


def azure_openai_live_sdk_available() -> bool:
    """Return whether optional Azure OpenAI endpoint smoke SDK imports appear available."""

    try:
        return (
            find_spec("openai") is not None
            and find_spec("azure.identity") is not None
        )
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def _chat_completions_sdk_available() -> bool:
    try:
        return (
            find_spec("azure.ai.inference") is not None
            and find_spec("azure.identity") is not None
        )
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def _create_chat_client(project_endpoint: str):
    try:
        from azure.ai.inference import ChatCompletionsClient
        from azure.identity import DefaultAzureCredential
    except ImportError as exc:
        raise RuntimeError(FOUNDRY_LIVE_CLIENT_UNAVAILABLE_MESSAGE) from exc

    try:
        return ChatCompletionsClient(
            endpoint=project_endpoint,
            credential=DefaultAzureCredential(),
        )
    except Exception as exc:
        raise RuntimeError(FOUNDRY_LIVE_CLIENT_UNAVAILABLE_MESSAGE) from exc


def _create_azure_openai_chat_client(azure_openai_endpoint: str):
    try:
        AzureOpenAI = _get_azure_openai_client_class()
        token_provider = _create_azure_openai_bearer_token_provider()
        return AzureOpenAI(
            azure_endpoint=azure_openai_endpoint,
            azure_ad_token_provider=token_provider,
            api_version=AZURE_OPENAI_API_VERSION,
        )
    except RuntimeError as exc:
        if str(exc) == AZURE_OPENAI_TOKEN_PROVIDER_UNAVAILABLE_MESSAGE:
            raise
        raise RuntimeError(AZURE_OPENAI_LIVE_CLIENT_UNAVAILABLE_MESSAGE) from exc
    except Exception as exc:
        raise RuntimeError(AZURE_OPENAI_LIVE_CLIENT_UNAVAILABLE_MESSAGE) from exc


def _create_azure_openai_bearer_token_provider():
    try:
        DefaultAzureCredential = _get_default_credential_class()
        get_bearer_token_provider = _get_bearer_token_provider_factory()
        return get_bearer_token_provider(
            DefaultAzureCredential(),
            AZURE_OPENAI_TOKEN_SCOPE,
        )
    except Exception as exc:
        raise RuntimeError(AZURE_OPENAI_TOKEN_PROVIDER_UNAVAILABLE_MESSAGE) from exc


def _get_azure_openai_client_class():
    try:
        from openai import AzureOpenAI
    except ImportError as exc:
        raise RuntimeError(AZURE_OPENAI_LIVE_CLIENT_UNAVAILABLE_MESSAGE) from exc
    return AzureOpenAI


def _get_default_credential_class():
    try:
        from azure.identity import DefaultAzureCredential
    except ImportError as exc:
        raise RuntimeError(AZURE_OPENAI_LIVE_CLIENT_UNAVAILABLE_MESSAGE) from exc
    return DefaultAzureCredential


def _get_bearer_token_provider_factory():
    try:
        from azure.identity import get_bearer_token_provider
    except ImportError as exc:
        raise RuntimeError(AZURE_OPENAI_LIVE_CLIENT_UNAVAILABLE_MESSAGE) from exc
    return get_bearer_token_provider


def _build_chat_messages(prompt: str) -> list[object]:
    try:
        from azure.ai.inference.models import SystemMessage, UserMessage
    except ImportError:
        return [
            {"role": "system", "content": FOUNDRY_SYSTEM_MESSAGE},
            {"role": "user", "content": prompt},
        ]

    return [
        SystemMessage(content=FOUNDRY_SYSTEM_MESSAGE),
        UserMessage(content=prompt),
    ]


def _build_openai_chat_messages(prompt: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": FOUNDRY_SYSTEM_MESSAGE},
        {"role": "user", "content": prompt},
    ]


def _extract_response_content(response: object) -> str | None:
    choices = _get_value(response, "choices")
    if not choices:
        return None

    first_choice = choices[0]
    message = _get_value(first_choice, "message")
    if message is None:
        return None

    content = _get_value(message, "content")
    return content if isinstance(content, str) else None


def _get_value(source: object, name: str):
    if isinstance(source, dict):
        return source.get(name)
    return getattr(source, name, None)
