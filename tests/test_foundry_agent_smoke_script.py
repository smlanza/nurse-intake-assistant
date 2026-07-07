from pathlib import Path
from types import SimpleNamespace

import pytest

from src.app.services.foundry_agent_client import FoundryAgentClientError
from src.app.services.foundry_extraction_contract import FoundryExtractionContractError


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


class StatusCodeError(Exception):
    def __init__(self, status_code: int, message: str = "raw secret message") -> None:
        super().__init__(message)
        self.status_code = status_code


class CategoryFailingAgent:
    def __init__(self, error: BaseException) -> None:
        self.error = error

    async def analyze_intake(self, raw_text: str) -> SimpleNamespace:
        raise self.error


def _patch_script_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    env_text: str,
) -> Path:
    env_file = tmp_path / ".env.foundry-agent.local"
    env_file.write_text(env_text)
    return env_file


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

    exit_code = script.main(["--check"])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "AGENT_PROVIDER=foundry-agent" in captured.err
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

    exit_code = script.main(["--check"])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT" in captured.err
    assert "AZURE_AI_FOUNDRY_AGENT_ID" in captured.err
    assert "secret-agent" not in captured.err
    assert captured.out == ""


def test_foundry_agent_smoke_script_check_does_not_create_agent_or_live_client(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_foundry_agent as script

    _patch_settings(monkeypatch, _settings(agent_provider="foundry-agent"))
    monkeypatch.setattr(
        script,
        "create_nurse_intake_agent",
        lambda settings: pytest.fail("Agent should not be created in --check"),
    )
    monkeypatch.setattr(script, "foundry_agent_sdk_available", lambda: True)

    exit_code = script.main(["--check"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "preflight passed" in captured.out
    assert "No Foundry Agent client was created" in captured.out
    assert "No Azure call was made" in captured.out
    assert "Optional Foundry Agent SDK package appears importable" in captured.out
    assert "secret-agent" not in captured.out
    assert captured.err == ""


def test_foundry_agent_smoke_script_check_reports_sdk_visibility_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_foundry_agent as script

    _patch_settings(monkeypatch, _settings(agent_provider="foundry-agent"))
    monkeypatch.setattr(script, "foundry_agent_sdk_available", lambda: False)

    exit_code = script.main(["--check"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Optional Foundry Agent SDK package is not importable" in captured.out
    assert "No Azure call was made" in captured.out
    assert captured.err == ""


def test_foundry_agent_smoke_script_default_does_not_call_live_agent(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_foundry_agent as script

    _patch_settings(monkeypatch, _settings(agent_provider="foundry-agent"))
    monkeypatch.setattr(
        script,
        "create_nurse_intake_agent",
        lambda settings: pytest.fail("Agent should not be created without --live"),
    )

    exit_code = script.main([])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "--check" in captured.err
    assert "--live" in captured.err
    assert captured.out == ""


def test_foundry_agent_smoke_script_calls_agent_only_in_live_mode(
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

    exit_code = script.main(["--live"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert fake_agent.calls == [script.FICTIONAL_AGENT_INTAKE_TEXT]
    assert "Foundry Agent smoke test completed" in captured.out
    assert "Routine" in captured.out
    assert "routine medication refill" in captured.out
    assert "fictional demo intake" in captured.out
    assert "secret-agent" not in captured.out
    assert "instructions" not in captured.out.lower()
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

    exit_code = script.main(["--live"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Foundry Agent smoke test failed" in captured.err
    assert "Safe failure category: unknown" in captured.err
    assert "Next check:" in captured.err
    assert "raw secret endpoint failure" not in captured.err
    assert "Traceback" not in captured.err
    assert captured.out == ""


@pytest.mark.parametrize(
    ("error", "category"),
    [
        (StatusCodeError(401, "bearer token secret"), "authentication"),
        (StatusCodeError(403, "forbidden endpoint secret"), "authorization"),
        (StatusCodeError(404, "agent id secret not found"), "not_found"),
        (StatusCodeError(400, "bad prompt secret"), "bad_request"),
        (
            FoundryExtractionContractError("raw prompt parse secret"),
            "parsing",
        ),
        (RuntimeError("full endpoint token secret"), "unknown"),
    ],
)
def test_foundry_agent_smoke_script_live_failures_are_categorized_safely(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    error: BaseException,
    category: str,
) -> None:
    import scripts.smoke_foundry_agent as script

    _patch_settings(monkeypatch, _settings(agent_provider="foundry-agent"))
    monkeypatch.setattr(
        script,
        "create_nurse_intake_agent",
        lambda settings: CategoryFailingAgent(error),
    )

    exit_code = script.main(["--live"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert f"Safe failure category: {category}" in captured.err
    assert "Next check:" in captured.err
    assert "secret" not in captured.err
    assert "Traceback" not in captured.err
    assert captured.out == ""


def test_foundry_agent_smoke_script_classifies_client_error_categories() -> None:
    import scripts.smoke_foundry_agent as script

    assert (
        script.classify_live_agent_failure(
            FoundryAgentClientError("secret", category="foundry-agent-sdk-unavailable")
        )
        == "sdk_missing"
    )
    assert (
        script.classify_live_agent_failure(
            FoundryAgentClientError("secret", category="foundry-agent-missing-configuration")
        )
        == "configuration"
    )


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

    exit_code = script.main(["--live"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "no email or SMS was sent" in captured.out
    assert captured.err == ""


def test_foundry_agent_smoke_script_env_file_check_loads_missing_settings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_foundry_agent as script

    env_file = _patch_script_env(
        monkeypatch,
        tmp_path,
        "\n".join(
            [
                "AGENT_PROVIDER=foundry-agent",
                "AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT=https://secret-agent.services.ai.azure.com/api/projects/demo",
                "AZURE_AI_FOUNDRY_AGENT_ID=secret-agent-id",
            ]
        ),
    )
    for key in [
        "AGENT_PROVIDER",
        "AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT",
        "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT",
        "AZURE_AI_FOUNDRY_AGENT_ID",
    ]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(script, "foundry_agent_sdk_available", lambda: True)
    monkeypatch.setattr(
        script,
        "create_nurse_intake_agent",
        lambda settings: pytest.fail("Agent should not be created in --check"),
    )

    exit_code = script.main(["--env-file", str(env_file), "--check"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Loaded Foundry Agent smoke environment file" in captured.out
    assert "preflight passed" in captured.out
    assert "secret-agent" not in captured.out
    assert captured.err == ""


def test_foundry_agent_smoke_script_shell_env_overrides_env_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_foundry_agent as script

    env_file = _patch_script_env(
        monkeypatch,
        tmp_path,
        "\n".join(
            [
                "AGENT_PROVIDER=mock",
                "AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT=https://file-secret.services.ai.azure.com/api/projects/demo",
                "AZURE_AI_FOUNDRY_AGENT_ID=file-secret-agent-id",
            ]
        ),
    )
    monkeypatch.setenv("AGENT_PROVIDER", "foundry-agent")
    monkeypatch.setenv(
        "AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT",
        "https://shell-secret.services.ai.azure.com/api/projects/demo",
    )
    monkeypatch.setenv("AZURE_AI_FOUNDRY_AGENT_ID", "shell-secret-agent-id")
    monkeypatch.setattr(script, "foundry_agent_sdk_available", lambda: True)

    exit_code = script.main(["--env-file", str(env_file), "--check"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "preflight passed" in captured.out
    assert "file-secret" not in captured.out
    assert "shell-secret" not in captured.out
    assert captured.err == ""


def test_foundry_agent_smoke_script_missing_env_file_is_sanitized(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_foundry_agent as script

    missing_file = tmp_path / "secret-agent.env"

    exit_code = script.main(["--env-file", str(missing_file), "--check"])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "Foundry Agent smoke env file not found" in captured.err
    assert "secret-agent.env" not in captured.err
    assert "No Azure call was made" in captured.err
    assert captured.out == ""
