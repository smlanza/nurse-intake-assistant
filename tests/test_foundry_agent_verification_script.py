import json
from types import SimpleNamespace

import pytest


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        agent_provider_normalized="foundry-agent",
        azure_ai_foundry_agent_project_endpoint=(
            "https://secret.example/api/projects/demo"
        ),
        azure_ai_foundry_agent_endpoint=(
            "https://secret.example/api/projects/demo/agents/secret-agent-name/"
            "endpoint/protocols/openai"
        ),
        azure_ai_foundry_agent_use_project_endpoint_compatibility=False,
        azure_ai_foundry_agent_name="secret-agent-name",
        azure_ai_foundry_agent_version="7",
        azure_ai_foundry_model_deployment_name="gpt-demo",
    )


def test_check_is_offline_and_reports_sanitized_readiness(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.verify_foundry_agent as script

    monkeypatch.setattr(script, "AppSettings", _settings)
    monkeypatch.setattr(script, "foundry_agent_verification_sdk_available", lambda: True)
    monkeypatch.setattr(
        script,
        "_create_verification_service",
        lambda: pytest.fail("check mode must not create a client or credential"),
    )

    exit_code = script.main(["--check", "--json"])

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert exit_code == 0
    assert payload == {
        "agent_invoked": False,
        "azure_call_made": False,
        "azure_mutation_made": False,
        "category": "success",
        "instruction_version": "foundry-agent-intake-v1",
        "mode": "check",
        "operation": "check_agent_verification_readiness",
        "ready": True,
        "recommended_next_step": (
            "Run --live --json to verify the configured immutable agent version "
            "without invoking it."
        ),
        "required_settings_missing": [],
        "sdk_available": True,
    }
    for unsafe in ("secret.example", "secret-agent-name", "gpt-demo", "7"):
        assert unsafe not in output


def test_live_json_verifies_without_mutation_or_invocation(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.verify_foundry_agent as script
    from src.app.services.foundry_agent_verification import (
        FoundryAgentVerificationResult,
    )

    requests: list[object] = []

    class FakeVerification:
        def verify(self, request: object) -> FoundryAgentVerificationResult:
            requests.append(request)
            return FoundryAgentVerificationResult.success()

    monkeypatch.setattr(script, "AppSettings", _settings)
    monkeypatch.setattr(script, "_create_verification_service", FakeVerification)

    exit_code = script.main(["--live", "--json"])

    output = capsys.readouterr().out
    payload = json.loads(output)
    request = requests[0]
    assert exit_code == 0
    assert request.project_endpoint == "https://secret.example/api/projects/demo"
    assert request.agent_name == "secret-agent-name"
    assert request.agent_version == "7"
    assert request.model_deployment_name == "gpt-demo"
    assert "foundry-agent-intake-v1" in request.instructions
    assert payload["agent_definition_matches"] is True
    assert "azure_lookup_attempted" not in payload
    assert payload["agent_invoked"] is False
    assert payload["azure_mutation_made"] is False
    for unsafe in (
        "secret.example",
        "secret-agent-name",
        "gpt-demo",
        "Bearer",
        "Traceback",
        "@",
    ):
        assert unsafe not in output


def test_live_missing_version_is_sanitized_and_does_not_create_client(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.verify_foundry_agent as script

    settings = _settings()
    settings.azure_ai_foundry_agent_version = None
    monkeypatch.setattr(script, "AppSettings", lambda: settings)
    monkeypatch.setattr(
        script,
        "_create_verification_service",
        lambda: pytest.fail("invalid configuration must not create a client"),
    )

    exit_code = script.main(["--live", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert payload["category"] == "missing_configuration"
    assert payload["agent_invoked"] is False
    assert payload["azure_mutation_made"] is False


def test_check_missing_project_endpoint_is_sanitized_and_creates_no_client(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.verify_foundry_agent as script

    settings = _settings()
    settings.azure_ai_foundry_agent_project_endpoint = None
    monkeypatch.setattr(script, "AppSettings", lambda: settings)
    monkeypatch.setattr(
        script,
        "_create_verification_service",
        lambda: pytest.fail("missing project endpoint must not create a client"),
    )

    exit_code = script.main(["--check", "--json"])

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert exit_code == 2
    assert payload["required_settings_missing"] == [
        "AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT"
    ]
    assert "secret.example" not in output


def test_check_explicit_compatibility_mode_is_ready_without_stable_endpoint(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.verify_foundry_agent as script

    settings = _settings()
    settings.azure_ai_foundry_agent_endpoint = None
    settings.azure_ai_foundry_agent_use_project_endpoint_compatibility = True
    monkeypatch.setattr(script, "AppSettings", lambda: settings)
    monkeypatch.setattr(script, "foundry_agent_verification_sdk_available", lambda: True)

    exit_code = script.main(["--check", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["ready"] is True
    assert payload["required_settings_missing"] == []


def test_live_requires_json_and_explicit_mode() -> None:
    import scripts.verify_foundry_agent as script

    with pytest.raises(SystemExit):
        script.main(["--live"])
    with pytest.raises(SystemExit):
        script.main([])
