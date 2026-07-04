import pytest

from src.app.config.settings import AppSettings
from src.app.services.nurse_intake_agent import MockNurseIntakeAgent


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


def test_foundry_agent_provider_fails_safely_without_creating_live_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.services.nurse_intake_agent_factory import (
        NurseIntakeAgentProviderNotImplementedError,
        create_nurse_intake_agent,
    )

    monkeypatch.setenv("AGENT_PROVIDER", "foundry-agent")

    with pytest.raises(
        NurseIntakeAgentProviderNotImplementedError,
        match="Azure AI Foundry Agent orchestration is not wired yet",
    ):
        create_nurse_intake_agent(AppSettings())


def test_unknown_agent_provider_raises_clear_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.services.nurse_intake_agent_factory import create_nurse_intake_agent

    monkeypatch.setenv("AGENT_PROVIDER", "future-agent")

    with pytest.raises(ValueError, match="Unsupported AGENT_PROVIDER"):
        create_nurse_intake_agent(AppSettings())
