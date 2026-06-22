import pytest

from src.app.config.settings import AppSettings
from src.app.services.case_repository import InMemoryCaseRepository
from src.app.services.cosmos_case_repository import CosmosCaseRepository


class FakeCosmosContainer:
    pass


def settings_for_mode(monkeypatch: pytest.MonkeyPatch, app_mode: str) -> AppSettings:
    monkeypatch.setenv("APP_MODE", app_mode)
    return AppSettings()


def test_mock_mode_creates_in_memory_repository(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.services.repository_factory import create_case_repository

    settings = settings_for_mode(monkeypatch, "mock")

    repository = create_case_repository(settings)

    assert isinstance(repository, InMemoryCaseRepository)


def test_cosmos_mode_creates_cosmos_repository_with_injected_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.services.repository_factory import create_case_repository

    settings = settings_for_mode(monkeypatch, "cosmos")
    container = FakeCosmosContainer()

    repository = create_case_repository(settings, cosmos_container=container)

    assert isinstance(repository, CosmosCaseRepository)
    assert repository.container is container


def test_app_mode_is_case_insensitive_and_ignores_whitespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.services.repository_factory import create_case_repository

    settings = settings_for_mode(monkeypatch, "  COSMOS  ")
    container = FakeCosmosContainer()

    repository = create_case_repository(settings, cosmos_container=container)

    assert isinstance(repository, CosmosCaseRepository)


def test_unsupported_app_mode_raises_value_error_with_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.services.repository_factory import create_case_repository

    settings = settings_for_mode(monkeypatch, "unsupported-mode")

    with pytest.raises(ValueError, match="unsupported-mode"):
        create_case_repository(settings)


def test_cosmos_mode_requires_injected_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.services.repository_factory import create_case_repository

    settings = settings_for_mode(monkeypatch, "cosmos")

    with pytest.raises(ValueError, match="container"):
        create_case_repository(settings)
