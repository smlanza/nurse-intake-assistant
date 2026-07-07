import pytest

from src.app.config.settings import AppSettings
from src.app.services.nurse_intake_agent import (
    FoundryNurseIntakeAgent,
    MockNurseIntakeAgent,
)


def test_agent_provider_defaults_to_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.app.services.nurse_intake_agent_factory import create_nurse_intake_agent

    monkeypatch.delenv("AGENT_PROVIDER", raising=False)

    agent = create_nurse_intake_agent(AppSettings())

    assert isinstance(agent, MockNurseIntakeAgent)


def test_agent_provider_matching_ignores_case_and_whitespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.services.nurse_intake_agent_factory import create_nurse_intake_agent

    monkeypatch.setenv("AGENT_PROVIDER", "  MOCK  ")

    agent = create_nurse_intake_agent(AppSettings())

    assert isinstance(agent, MockNurseIntakeAgent)


def test_blank_agent_provider_uses_mock_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.services.nurse_intake_agent_factory import create_nurse_intake_agent

    monkeypatch.setenv("AGENT_PROVIDER", "   ")

    agent = create_nurse_intake_agent(AppSettings())

    assert isinstance(agent, MockNurseIntakeAgent)


def test_foundry_agent_provider_creates_lazy_foundry_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.services.nurse_intake_agent_factory import create_nurse_intake_agent

    monkeypatch.setenv("AGENT_PROVIDER", "foundry-agent")

    agent = create_nurse_intake_agent(AppSettings())

    assert isinstance(agent, FoundryNurseIntakeAgent)
    assert agent.client is None


def test_foundry_agent_provider_does_not_require_live_settings_during_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.services.nurse_intake_agent_factory import create_nurse_intake_agent

    monkeypatch.setenv("AGENT_PROVIDER", "foundry-agent")
    monkeypatch.delenv("AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT", raising=False)
    monkeypatch.delenv("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT", raising=False)
    monkeypatch.delenv("AZURE_AI_FOUNDRY_AGENT_ID", raising=False)

    agent = create_nurse_intake_agent(AppSettings())

    assert isinstance(agent, FoundryNurseIntakeAgent)
    assert agent.client is None


def test_foundry_agent_provider_supports_foundry_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.services.nurse_intake_agent_factory import create_nurse_intake_agent

    monkeypatch.setenv("AGENT_PROVIDER", "foundry")

    agent = create_nurse_intake_agent(AppSettings())

    assert isinstance(agent, FoundryNurseIntakeAgent)
    assert agent.client is None


def test_optional_agent_factory_returns_none_for_mock_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.services.nurse_intake_agent_factory import (
        create_optional_nurse_intake_agent,
    )

    monkeypatch.setenv("AGENT_PROVIDER", "mock")

    assert create_optional_nurse_intake_agent(AppSettings()) is None


def test_optional_agent_factory_returns_foundry_agent_only_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.services.nurse_intake_agent_factory import (
        create_optional_nurse_intake_agent,
    )

    monkeypatch.setenv("AGENT_PROVIDER", "foundry-agent")

    agent = create_optional_nurse_intake_agent(AppSettings())

    assert isinstance(agent, FoundryNurseIntakeAgent)
    assert agent.client is None


def test_unknown_agent_provider_raises_clear_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.services.nurse_intake_agent_factory import create_nurse_intake_agent

    monkeypatch.setenv("AGENT_PROVIDER", "future-agent")

    with pytest.raises(ValueError, match="Unsupported AGENT_PROVIDER"):
        create_nurse_intake_agent(AppSettings())
