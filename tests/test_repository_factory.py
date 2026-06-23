import pytest

from src.app.config.settings import AppSettings
from src.app.services.case_repository import InMemoryCaseRepository
from src.app.services.cosmos_case_repository import CosmosCaseRepository


class FakeCosmosContainer:
    pass


class OtherFakeCosmosContainer:
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


def test_cosmos_mode_without_container_requires_cosmos_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.services.repository_factory import create_case_repository

    settings = settings_for_mode(monkeypatch, "cosmos")

    with pytest.raises(ValueError, match="COSMOS_ENDPOINT"):
        create_case_repository(settings)


def test_cosmos_mode_without_injected_container_creates_cosmos_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.app.services.repository_factory as repository_factory

    settings = settings_for_mode(monkeypatch, "cosmos")
    container = FakeCosmosContainer()
    calls: list[AppSettings] = []

    def fake_create_cosmos_container(settings_arg: AppSettings) -> FakeCosmosContainer:
        calls.append(settings_arg)
        return container

    monkeypatch.setattr(
        repository_factory,
        "create_cosmos_container",
        fake_create_cosmos_container,
        raising=False,
    )

    repository = repository_factory.create_case_repository(settings)

    assert calls == [settings]
    assert isinstance(repository, CosmosCaseRepository)
    assert repository.container is container


def test_cosmos_mode_with_injected_container_does_not_create_cosmos_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.app.services.repository_factory as repository_factory

    settings = settings_for_mode(monkeypatch, "cosmos")
    container = OtherFakeCosmosContainer()

    def fail_if_called(settings_arg: AppSettings) -> None:
        raise AssertionError("create_cosmos_container should not be called")

    monkeypatch.setattr(
        repository_factory,
        "create_cosmos_container",
        fail_if_called,
        raising=False,
    )

    repository = repository_factory.create_case_repository(
        settings,
        cosmos_container=container,
    )

    assert isinstance(repository, CosmosCaseRepository)
    assert repository.container is container


def test_mock_mode_does_not_create_cosmos_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.app.services.repository_factory as repository_factory

    settings = settings_for_mode(monkeypatch, "mock")

    def fail_if_called(settings_arg: AppSettings) -> None:
        raise AssertionError("create_cosmos_container should not be called")

    monkeypatch.setattr(
        repository_factory,
        "create_cosmos_container",
        fail_if_called,
        raising=False,
    )

    repository = repository_factory.create_case_repository(settings)

    assert isinstance(repository, InMemoryCaseRepository)
