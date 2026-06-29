FOUNDRY_LIVE_CLIENT_UNAVAILABLE_MESSAGE = (
    "Azure AI Foundry live client is not configured or SDK support is not available."
)


class AzureAiFoundryLiveClient:
    """Opt-in scaffold for future live Azure AI Foundry structured extraction."""

    def __init__(self, project_endpoint: str) -> None:
        self.project_endpoint = project_endpoint

    def complete_structured_extraction(
        self,
        prompt: str,
        model_deployment_name: str,
    ) -> str:
        """Return raw JSON text from a future live Foundry model response."""

        raise RuntimeError(FOUNDRY_LIVE_CLIENT_UNAVAILABLE_MESSAGE)


def create_foundry_live_client(project_endpoint: str) -> AzureAiFoundryLiveClient:
    """Create the opt-in Foundry live adapter without constructing SDK clients."""

    return AzureAiFoundryLiveClient(project_endpoint=project_endpoint)
