import json
from types import SimpleNamespace

import pytest


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        agent_provider_normalized="foundry-agent",
        azure_ai_foundry_agent_project_endpoint=(
            "https://secret.example/api/projects/demo"
        ),
        azure_ai_foundry_agent_name="secret-agent-name",
        azure_ai_foundry_model_deployment_name="gpt-demo",
    )


def test_check_is_offline_and_reports_sanitized_readiness(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.deploy_foundry_agent as script

    monkeypatch.setattr(script, "AppSettings", _settings)
    monkeypatch.setattr(script, "foundry_agent_deployment_sdk_available", lambda: True)
    monkeypatch.setattr(
        script,
        "_create_deployment_service",
        lambda: pytest.fail("check mode must not construct a client or credential"),
    )

    exit_code = script.main(["--check", "--json"])

    output = capsys.readouterr().out
    readiness = json.loads(output)
    assert exit_code == 0
    assert readiness["ready"] is True
    assert readiness["azure_call_made"] is False
    assert readiness["agent_created"] is False
    assert readiness["agent_invoked"] is False
    assert readiness["instruction_version"] == "foundry-agent-intake-v1"
    assert "secret.example" not in output
    assert "secret-agent-name" not in output
    assert "gpt-demo" not in output


def test_live_json_provisions_without_invoking_and_prints_only_safe_metadata(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.deploy_foundry_agent as script
    from src.app.services.foundry_agent_deployment import (
        FoundryAgentDeploymentResult,
    )

    requests: list[object] = []

    class FakeDeployment:
        def provision(self, request: object) -> FoundryAgentDeploymentResult:
            requests.append(request)
            return FoundryAgentDeploymentResult.success(agent_reused=True)

    monkeypatch.setattr(script, "AppSettings", _settings)
    monkeypatch.setattr(script, "_create_deployment_service", FakeDeployment)

    exit_code = script.main(["--live", "--json"])

    output = capsys.readouterr().out
    payload = json.loads(output)
    request = requests[0]
    assert exit_code == 0
    assert request.project_endpoint == "https://secret.example/api/projects/demo"
    assert request.agent_name == "secret-agent-name"
    assert request.model_deployment_name == "gpt-demo"
    assert "foundry-agent-intake-v1" in request.instructions
    assert set(payload) == {
        "ok",
        "mode",
        "operation",
        "category",
        "message",
        "agent_created",
        "agent_reused",
        "agent_updated",
        "agent_name_present",
        "agent_version_present",
        "model_deployment_name_present",
        "instruction_version",
        "agent_invoked",
        "recommended_next_step",
    }
    assert payload["agent_reused"] is True
    assert payload["agent_invoked"] is False
    assert payload["agent_name_present"] is True
    assert payload["agent_version_present"] is True
    assert payload["model_deployment_name_present"] is True
    for unsafe_value in (
        "secret.example",
        "secret-agent-name",
        "gpt-demo",
        "credential",
        "Bearer",
        "secret-token",
        "access-token",
        "patient prompt",
        "Traceback",
        "@",
    ):
        assert unsafe_value not in output


def test_live_json_missing_configuration_is_sanitized(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.deploy_foundry_agent as script

    settings = _settings()
    settings.azure_ai_foundry_agent_name = None
    monkeypatch.setattr(script, "AppSettings", lambda: settings)
    monkeypatch.setattr(
        script,
        "_create_deployment_service",
        lambda: pytest.fail("invalid configuration must not create a client"),
    )

    exit_code = script.main(["--live", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert payload["category"] == "missing_configuration"
    assert payload["agent_created"] is False
    assert payload["agent_invoked"] is False


def test_live_execution_requires_explicit_live_mode() -> None:
    import scripts.deploy_foundry_agent as script

    with pytest.raises(SystemExit):
        script.main([])
