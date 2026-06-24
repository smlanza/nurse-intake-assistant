import pytest


def test_demo_suppress_notifications_defaults_to_false(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.app.config.settings import AppSettings

    monkeypatch.delenv("DEMO_SUPPRESS_NOTIFICATIONS", raising=False)

    settings = AppSettings()

    assert settings.demo_suppress_notifications is False


def test_demo_suppress_notifications_reads_true(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.app.config.settings import AppSettings

    monkeypatch.setenv("DEMO_SUPPRESS_NOTIFICATIONS", "true")

    assert AppSettings().demo_suppress_notifications is True


def test_demo_suppress_notifications_reads_false(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.app.config.settings import AppSettings

    monkeypatch.setenv("DEMO_SUPPRESS_NOTIFICATIONS", "false")

    assert AppSettings().demo_suppress_notifications is False


@pytest.mark.parametrize("value", ["1", "true", "yes", "on"])
def test_demo_suppress_notifications_accepts_truthy_values(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    from src.app.config.settings import AppSettings

    monkeypatch.setenv("DEMO_SUPPRESS_NOTIFICATIONS", value)

    assert AppSettings().demo_suppress_notifications is True


@pytest.mark.parametrize("value", ["0", "false", "no", "off"])
def test_demo_suppress_notifications_accepts_falsey_values(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    from src.app.config.settings import AppSettings

    monkeypatch.setenv("DEMO_SUPPRESS_NOTIFICATIONS", value)

    assert AppSettings().demo_suppress_notifications is False


def test_app_mode_defaults_to_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.app.config.settings import AppSettings

    monkeypatch.delenv("APP_MODE", raising=False)

    assert AppSettings().app_mode == "mock"


def test_app_mode_reads_environment_value(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.app.config.settings import AppSettings

    monkeypatch.setenv("APP_MODE", "azure")

    assert AppSettings().app_mode == "azure"


def test_cosmos_settings_use_expected_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.app.config.settings import AppSettings

    monkeypatch.setenv("APP_MODE", "mock")
    monkeypatch.delenv("COSMOS_DATABASE_NAME", raising=False)
    monkeypatch.delenv("COSMOS_CONTAINER_NAME", raising=False)
    monkeypatch.delenv("COSMOS_ENDPOINT", raising=False)
    monkeypatch.delenv("COSMOS_KEY", raising=False)

    settings = AppSettings()

    assert settings.cosmos_database_name == "nurse-intake"
    assert settings.cosmos_container_name == "cases"
    assert settings.cosmos_endpoint is None
    assert settings.cosmos_key is None


def test_mock_mode_does_not_require_cosmos_endpoint_or_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.config.settings import AppSettings
    from src.app.services.case_repository import InMemoryCaseRepository
    from src.app.services.repository_factory import create_case_repository

    monkeypatch.setenv("APP_MODE", "mock")
    monkeypatch.delenv("COSMOS_ENDPOINT", raising=False)
    monkeypatch.delenv("COSMOS_KEY", raising=False)

    repository = create_case_repository(AppSettings())

    assert isinstance(repository, InMemoryCaseRepository)


def test_cosmos_settings_read_and_trim_environment_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.config.settings import AppSettings

    monkeypatch.setenv("COSMOS_DATABASE_NAME", "  intake-db  ")
    monkeypatch.setenv("COSMOS_CONTAINER_NAME", "  intake-cases  ")
    monkeypatch.setenv("COSMOS_ENDPOINT", "  https://example.documents.azure.com  ")
    monkeypatch.setenv("COSMOS_KEY", "  secret-key  ")

    settings = AppSettings()

    assert settings.cosmos_database_name == "intake-db"
    assert settings.cosmos_container_name == "intake-cases"
    assert settings.cosmos_endpoint == "https://example.documents.azure.com"
    assert settings.cosmos_key == "secret-key"


def test_blank_optional_cosmos_settings_are_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.config.settings import AppSettings

    monkeypatch.setenv("COSMOS_ENDPOINT", "   ")
    monkeypatch.setenv("COSMOS_KEY", "   ")

    settings = AppSettings()

    assert settings.cosmos_endpoint is None
    assert settings.cosmos_key is None
