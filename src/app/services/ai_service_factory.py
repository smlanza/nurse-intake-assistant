from src.app.config.settings import AppSettings
from src.app.services.mock_ai_service import MockAiService


def create_ai_service(settings: AppSettings) -> MockAiService:
    """Select the configured extraction service."""

    provider = settings.ai_provider_normalized

    if provider == "mock":
        return MockAiService()

    raise ValueError(f"Unsupported AI_PROVIDER: {settings.ai_provider}")
