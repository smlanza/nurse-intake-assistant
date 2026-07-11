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

    exit_code = script.main(["--check"])

    output = capsys.readouterr().out
    readiness = json.loads(output)
    assert exit_code == 0
    assert readiness["ready"] is True
    assert readiness["instruction_version"] == "foundry-agent-intake-v1"
    assert "secret.example" not in output
    assert "secret-agent-name" not in output


def test_live_json_creates_and_invokes_once_with_only_safe_output(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.deploy_foundry_agent as script
    from src.app.services.foundry_agent_deployment import (
        FoundryAgentDeployment,
    )

    create_calls: list[dict[str, object]] = []
    response_calls: list[dict[str, object]] = []
    valid_output = json.dumps(
        {
            "extraction": {
                "patient": {
                    "name": "Taylor Quinn",
                    "date_of_birth": None,
                    "callback_number": "demo-callback-002",
                },
                "reason_for_calling": "routine medication refill",
                "symptoms": [],
                "summary": "Fictional patient requests a routine refill.",
                "missing_fields": ["date_of_birth"],
                "uncertain_fields": [],
            },
            "urgency": {
                "urgency": "Routine",
                "urgency_rationale": "No urgent symptoms were reported.",
                "advisory_disclaimer": "Advisory only; nurse review is required.",
            },
        }
    )

    class FakeResponses:
        def create(self, **kwargs: object) -> SimpleNamespace:
            response_calls.append(kwargs)
            return SimpleNamespace(output_text=valid_output)

    class FakeProjectClient:
        agents: "FakeProjectClient"

        def __init__(self) -> None:
            self.agents = self

        def create_version(self, **kwargs: object) -> SimpleNamespace:
            create_calls.append(kwargs)
            return SimpleNamespace(name="secret-agent-name", version="8")

        def get_openai_client(self) -> SimpleNamespace:
            return SimpleNamespace(responses=FakeResponses())

    deployment = FoundryAgentDeployment(
        project_client_factory=lambda endpoint: FakeProjectClient(),
        prompt_agent_definition_factory=lambda **kwargs: SimpleNamespace(**kwargs),
    )

    monkeypatch.setattr(script, "AppSettings", _settings)
    monkeypatch.setattr(script, "_create_deployment_service", lambda: deployment)

    exit_code = script.main(["--live", "--json"])

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert exit_code == 0
    assert len(create_calls) == 1
    assert len(response_calls) == 1
    assert response_calls[0]["extra_body"] == {
        "agent_reference": {
            "name": "secret-agent-name",
            "version": "8",
            "type": "agent_reference",
        }
    }
    assert set(payload) == {
        "ok",
        "mode",
        "operation",
        "category",
        "agent_created",
        "agent_invoked",
        "agent_output_valid",
        "created_version",
        "instruction_version",
        "fields_present",
        "recommended_next_step",
    }
    assert payload["created_version"] == "8"
    assert payload["agent_created"] is True
    assert payload["agent_invoked"] is True
    assert payload["agent_output_valid"] is True
    for unsafe_value in (
        "secret.example",
        "secret-agent-name",
        "gpt-demo",
        "demo-callback-002",
        "Taylor Quinn",
        "Instruction version",
        "token",
        "agent-id",
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
