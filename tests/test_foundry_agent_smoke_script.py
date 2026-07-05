from types import SimpleNamespace

import pytest


def _settings(
    agent_provider: str = "foundry",
    project_endpoint: str | None = (
        "https://secret-agent.services.ai.azure.com/api/projects/demo"
    ),
    agent_id: str | None = "secret-agent-id",
) -> SimpleNamespace:
    return SimpleNamespace(
        agent_provider_normalized=agent_provider,
        azure_ai_foundry_agent_project_endpoint=project_endpoint,
        azure_ai_foundry_project_endpoint=None,
        azure_ai_foundry_agent_id=agent_id,
    )


def _patch_settings(monkeypatch: pytest.MonkeyPatch, settings: SimpleNamespace) -> None:
    import scripts.smoke_foundry_agent as script

    monkeypatch.setattr(script, "AppSettings", lambda: settings)


class FakeAgent:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def analyze_intake(self, raw_text: str) -> SimpleNamespace:
        self.calls.append(raw_text)
        return SimpleNamespace(
            extraction=SimpleNamespace(
                patient=SimpleNamespace(name="Demo Patient"),
                reason_for_calling="routine medication refill",
                symptoms=["fatigue"],
                summary="Demo patient requests a routine medication refill.",
            ),
            urgency=SimpleNamespace(urgency="Routine"),
            handoffNote="Demo handoff note.",
            metadata=SimpleNamespace(provider="foundry", agentMode="manual-smoke"),
        )


class FailingAgent:
    async def analyze_intake(self, raw_text: str) -> SimpleNamespace:
        raise RuntimeError("raw secret endpoint failure")


def test_foundry_agent_smoke_script_requires_foundry_provider(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_foundry_agent as script

    _patch_settings(monkeypatch, _settings(agent_provider="mock"))
    monkeypatch.setattr(
        script,
        "create_nurse_intake_agent",
        lambda settings: pytest.fail("Agent should not be created"),
    )

    exit_code = script.main([])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "AGENT_PROVIDER=foundry" in captured.err
    assert "AGENT_PROVIDER=mock" in captured.err
    assert captured.out == ""


def test_foundry_agent_smoke_script_reports_missing_preflight_settings(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_foundry_agent as script

    _patch_settings(monkeypatch, _settings(project_endpoint=None, agent_id=None))
    monkeypatch.setattr(
        script,
        "create_nurse_intake_agent",
        lambda settings: pytest.fail("Agent should not be created"),
    )

    exit_code = script.main([])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT" in captured.err
    assert "AZURE_AI_FOUNDRY_AGENT_ID" in captured.err
    assert "secret-agent" not in captured.err
    assert captured.out == ""


def test_foundry_agent_smoke_script_calls_agent_only_after_preflight_passes(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_foundry_agent as script

    fake_agent = FakeAgent()
    _patch_settings(monkeypatch, _settings())
    monkeypatch.setattr(
        script,
        "create_nurse_intake_agent",
        lambda settings: fake_agent,
    )

    exit_code = script.main([])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert fake_agent.calls == [script.FICTIONAL_AGENT_INTAKE_TEXT]
    assert "Foundry Agent smoke test completed" in captured.out
    assert "Routine" in captured.out
    assert "routine medication refill" in captured.out
    assert "secret-agent" not in captured.out
    assert captured.err == ""


def test_foundry_agent_smoke_script_returns_nonzero_on_agent_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_foundry_agent as script

    _patch_settings(monkeypatch, _settings())
    monkeypatch.setattr(
        script,
        "create_nurse_intake_agent",
        lambda settings: FailingAgent(),
    )

    exit_code = script.main([])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Foundry Agent smoke test failed" in captured.err
    assert "raw secret endpoint failure" not in captured.err
    assert "Traceback" not in captured.err
    assert captured.out == ""


def test_foundry_agent_smoke_script_does_not_send_notifications(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_foundry_agent as script
    import src.app.services.email_notification_sender_factory as email_factory
    import src.app.services.sms_notification_sender_factory as sms_factory

    fake_agent = FakeAgent()
    _patch_settings(monkeypatch, _settings())
    monkeypatch.setattr(script, "create_nurse_intake_agent", lambda settings: fake_agent)
    monkeypatch.setattr(
        email_factory,
        "create_email_notification_sender",
        lambda settings: pytest.fail("Email sender should not be created"),
    )
    monkeypatch.setattr(
        sms_factory,
        "create_sms_notification_sender",
        lambda settings: pytest.fail("SMS sender should not be created"),
    )

    exit_code = script.main([])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "no email or SMS was sent" in captured.out
    assert captured.err == ""
