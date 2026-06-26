import pytest

from src.app.config.settings import AppSettings
from src.app.services.mock_ai_service import MockAiService


def test_mock_provider_creates_mock_ai_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.services.ai_service_factory import create_ai_service

    monkeypatch.setenv("AI_PROVIDER", "mock")

    service = create_ai_service(AppSettings())

    assert isinstance(service, MockAiService)


def test_ai_provider_matching_ignores_case_and_whitespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.services.ai_service_factory import create_ai_service

    monkeypatch.setenv("AI_PROVIDER", "  MOCK  ")

    service = create_ai_service(AppSettings())

    assert isinstance(service, MockAiService)


def test_blank_ai_provider_uses_mock_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.services.ai_service_factory import create_ai_service

    monkeypatch.setenv("AI_PROVIDER", "   ")

    service = create_ai_service(AppSettings())

    assert isinstance(service, MockAiService)


def test_unknown_ai_provider_raises_clear_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.services.ai_service_factory import create_ai_service

    monkeypatch.setenv("AI_PROVIDER", "openai")

    with pytest.raises(ValueError, match="Unsupported AI_PROVIDER"):
        create_ai_service(AppSettings())


def test_mock_provider_does_not_require_azure_ai_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.services.ai_service_factory import create_ai_service

    monkeypatch.setenv("AI_PROVIDER", "mock")
    monkeypatch.delenv("AZURE_AI_ENDPOINT", raising=False)
    monkeypatch.delenv("AZURE_AI_KEY", raising=False)
    monkeypatch.delenv("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT", raising=False)
    monkeypatch.delenv("AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT_NAME", raising=False)

    service = create_ai_service(AppSettings())

    assert isinstance(service, MockAiService)


def test_foundry_provider_creates_foundry_ai_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.services.ai_service_factory import create_ai_service
    from src.app.services.foundry_ai_service import FoundryAiService

    monkeypatch.setenv("AI_PROVIDER", "foundry")
    monkeypatch.setenv(
        "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT",
        "https://example.services.ai.azure.com/api/projects/demo",
    )
    monkeypatch.setenv(
        "AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT_NAME",
        "intake-extraction",
    )

    service = create_ai_service(AppSettings())

    assert isinstance(service, FoundryAiService)
    assert (
        service.project_endpoint
        == "https://example.services.ai.azure.com/api/projects/demo"
    )
    assert service.model_deployment_name == "intake-extraction"


def test_foundry_provider_matching_ignores_case_and_whitespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.services.ai_service_factory import create_ai_service
    from src.app.services.foundry_ai_service import FoundryAiService

    monkeypatch.setenv("AI_PROVIDER", "  FOUNDRY  ")
    monkeypatch.setenv(
        "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT",
        "https://example.services.ai.azure.com/api/projects/demo",
    )
    monkeypatch.setenv(
        "AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT_NAME",
        "intake-extraction",
    )

    service = create_ai_service(AppSettings())

    assert isinstance(service, FoundryAiService)


def test_foundry_provider_requires_project_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.services.ai_service_factory import create_ai_service

    monkeypatch.setenv("AI_PROVIDER", "foundry")
    monkeypatch.delenv("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT", raising=False)
    monkeypatch.setenv(
        "AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT_NAME",
        "intake-extraction",
    )

    with pytest.raises(ValueError, match="AZURE_AI_FOUNDRY_PROJECT_ENDPOINT"):
        create_ai_service(AppSettings())


def test_foundry_provider_requires_model_deployment_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.services.ai_service_factory import create_ai_service

    monkeypatch.setenv("AI_PROVIDER", "foundry")
    monkeypatch.setenv(
        "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT",
        "https://example.services.ai.azure.com/api/projects/demo",
    )
    monkeypatch.delenv("AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT_NAME", raising=False)

    with pytest.raises(
        ValueError,
        match="AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT_NAME",
    ):
        create_ai_service(AppSettings())
