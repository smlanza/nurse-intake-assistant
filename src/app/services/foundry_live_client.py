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

FOUNDRY_SYSTEM_MESSAGE = (
    "You are a structured extraction adapter for a nurse intake assistant. "
    "Return only the JSON requested by the user prompt."
)


class AzureAiFoundryLiveClient:
    """Opt-in scaffold for future live Azure AI Foundry structured extraction."""

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


def foundry_live_sdk_available() -> bool:
    """Return whether optional live Foundry SDK imports appear available."""

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
