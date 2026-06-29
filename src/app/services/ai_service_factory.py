from src.app.config.settings import AppSettings
from src.app.services.foundry_ai_service import FoundryAiService
from src.app.services.foundry_live_client import create_foundry_live_client
from src.app.services.mock_ai_service import MockAiService


def create_ai_service(settings: AppSettings) -> MockAiService | FoundryAiService:
    """Select the configured extraction service."""

    provider = settings.ai_provider_normalized

    if provider == "mock":
        return MockAiService()

    if provider == "foundry":
        return FoundryAiService(
            project_endpoint=_required_setting(
                settings.azure_ai_foundry_project_endpoint,
                "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT",
            ),
            model_deployment_name=_required_setting(
                settings.azure_ai_foundry_model_deployment_name,
                "AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT_NAME",
            ),
            client_factory=create_foundry_live_client,
        )

    raise ValueError(f"Unsupported AI_PROVIDER: {settings.ai_provider}")


def _required_setting(value: str | None, name: str) -> str:
    if value is None:
        raise ValueError(f"{name} is required for AI_PROVIDER=foundry")
    return value
