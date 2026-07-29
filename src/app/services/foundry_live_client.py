from importlib.util import find_spec
from urllib.parse import urlparse, urlunparse


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
AZURE_OPENAI_API_PATH_MODE = "openai-v1"
AZURE_OPENAI_BASE_URL_SHAPE = "openai.azure.com/openai/v1"
AZURE_OPENAI_TOKEN_SCOPE = "https://cognitiveservices.azure.com/.default"
AZURE_OPENAI_TOKEN_SCOPE_CATEGORY = "cognitiveservices.default"
AZURE_OPENAI_TOKEN_PROVIDER_UNAVAILABLE_MESSAGE = (
    "Azure OpenAI endpoint token provider setup failed."
)

FOUNDRY_SYSTEM_MESSAGE = (
    "You are a structured extraction adapter for a nurse intake assistant. "
    "Return only the JSON requested by the user prompt."
)


class AzureAiFoundryLiveClient:
    """Opt-in Foundry project client for live structured extraction."""

    def __init__(self, project_endpoint: str) -> None:
        self.project_endpoint = project_endpoint
        self._credential = None
        self._project_client = None
        self._openai_client = None

    def complete_structured_extraction(
        self,
        prompt: str,
        model_deployment_name: str,
    ) -> str:
        """Return raw JSON text from one live Foundry model response."""

        try:
            openai_client = self._get_openai_client()
            response = openai_client.chat.completions.create(
                messages=_build_openai_chat_messages(prompt),
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

    def _get_openai_client(self):
        if self._openai_client is not None:
            return self._openai_client

        try:
            if self._credential is None:
                credential_class = _get_default_credential_class()
                self._credential = credential_class()
            if self._project_client is None:
                project_client_class = _get_ai_project_client_class()
                self._project_client = project_client_class(
                    endpoint=self.project_endpoint,
                    credential=self._credential,
                )
            self._openai_client = self._project_client.get_openai_client()
        except RuntimeError as exc:
            if str(exc) == FOUNDRY_LIVE_CLIENT_UNAVAILABLE_MESSAGE:
                raise
            raise RuntimeError(FOUNDRY_LIVE_CLIENT_UNAVAILABLE_MESSAGE) from exc
        except Exception as exc:
            raise RuntimeError(FOUNDRY_LIVE_CLIENT_UNAVAILABLE_MESSAGE) from exc

        return self._openai_client

    def close(self) -> None:
        """Close lazily constructed SDK resources when they support closing."""

        for attribute_name in (
            "_openai_client",
            "_project_client",
            "_credential",
        ):
            resource = getattr(self, attribute_name)
            setattr(self, attribute_name, None)
            _close_when_supported(resource)


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

    return _foundry_project_sdk_available()


def azure_openai_live_sdk_available() -> bool:
    """Return whether optional Azure OpenAI endpoint smoke SDK imports appear available."""

    try:
        return (
            find_spec("openai") is not None
            and find_spec("azure.identity") is not None
        )
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def _foundry_project_sdk_available() -> bool:
    try:
        return (
            find_spec("azure.ai.projects") is not None
            and find_spec("azure.identity") is not None
            and find_spec("openai") is not None
        )
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def _get_ai_project_client_class():
    try:
        from azure.ai.projects import AIProjectClient
    except ImportError as exc:
        raise RuntimeError(FOUNDRY_LIVE_CLIENT_UNAVAILABLE_MESSAGE) from exc
    return AIProjectClient


def _create_azure_openai_chat_client(azure_openai_endpoint: str):
    try:
        OpenAI = _get_openai_client_class()
        base_url = normalize_azure_openai_v1_base_url(azure_openai_endpoint)
        token_provider = _create_azure_openai_bearer_token_provider()
        return OpenAI(
            base_url=base_url,
            api_key=token_provider,
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


def normalize_azure_openai_v1_base_url(azure_openai_endpoint: str) -> str:
    parsed = urlparse(azure_openai_endpoint.strip())
    normalized_path = parsed.path.strip("/")
    if normalized_path in {"", "openai/v1"}:
        path = "/openai/v1/"
    else:
        raise ValueError("Unsupported Azure OpenAI endpoint path shape.")

    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            path,
            "",
            "",
            "",
        )
    )


def _get_openai_client_class():
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError(AZURE_OPENAI_LIVE_CLIENT_UNAVAILABLE_MESSAGE) from exc
    return OpenAI


def _get_default_credential_class():
    try:
        from azure.identity import DefaultAzureCredential
    except ImportError as exc:
        raise RuntimeError(FOUNDRY_LIVE_CLIENT_UNAVAILABLE_MESSAGE) from exc
    return DefaultAzureCredential


def _get_bearer_token_provider_factory():
    try:
        from azure.identity import get_bearer_token_provider
    except ImportError as exc:
        raise RuntimeError(AZURE_OPENAI_LIVE_CLIENT_UNAVAILABLE_MESSAGE) from exc
    return get_bearer_token_provider


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


def _close_when_supported(resource: object | None) -> None:
    close = getattr(resource, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            pass
