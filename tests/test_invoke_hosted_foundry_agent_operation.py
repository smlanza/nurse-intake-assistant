import importlib
import inspect
import json

import pytest


def _operation():
    return importlib.import_module("src.app.operations.invoke_hosted_foundry_agent")


def _settings():
    class Settings:
        azure_ai_foundry_agent_project_endpoint = (
            "https://secret.example/api/projects/demo"
        )
        azure_ai_foundry_agent_endpoint = (
            "https://secret.example/api/projects/demo/agents/configured-agent/"
            "endpoint/protocols/openai"
        )
        azure_ai_foundry_agent_name = "configured-agent"
        azure_ai_foundry_agent_version = "7"
        azure_ai_foundry_managed_identity_client_id = None

    return Settings()


def test_check_constructs_no_live_service_credential_client_or_invocation(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    operation = _operation()
    monkeypatch.setattr(operation, "AppSettings", _settings)
    monkeypatch.setattr(operation, "hosted_invocation_sdk_available", lambda: True)
    monkeypatch.setattr(
        operation,
        "_create_live_invoker",
        lambda: pytest.fail("check must not construct live dependencies"),
    )

    exit_code = operation.main(["--check", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["category"] == "check_complete"
    assert payload["invocation_attempted"] is False
    assert payload["fictional_data_only"] is True


def test_invalid_configuration_stops_before_live_service_creation(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    operation = _operation()
    settings = _settings()
    settings.azure_ai_foundry_agent_version = None
    monkeypatch.setattr(operation, "AppSettings", lambda: settings)
    monkeypatch.setattr(operation, "hosted_invocation_sdk_available", lambda: True)
    monkeypatch.setattr(
        operation,
        "_create_live_invoker",
        lambda: pytest.fail("invalid config must stop before live dependencies"),
    )

    exit_code = operation.main(["--live", "--json"])

    output = capsys.readouterr().out
    assert exit_code == 2
    assert json.loads(output)["category"] == "missing_configuration"
    assert "configured-agent" not in output


def test_live_uses_injected_invoker_and_prints_only_sanitized_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    operation = _operation()
    service = importlib.import_module(
        "src.app.services.hosted_foundry_agent_invocation"
    )
    requests: list[object] = []

    class Invoker:
        def invoke(self, request: object):
            requests.append(request)
            return service.HostedFoundryAgentInvocationResult.success()

    monkeypatch.setattr(operation, "AppSettings", _settings)
    monkeypatch.setattr(operation, "hosted_invocation_sdk_available", lambda: True)
    monkeypatch.setattr(operation, "_create_live_invoker", Invoker)

    exit_code = operation.main(["--live", "--json"])

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert exit_code == 0
    assert len(requests) == 1
    assert payload["invocation_attempted"] is True
    assert payload["agent_output_valid"] is True
    for unsafe in ("secret.example", "configured-agent", "secret-token"):
        assert unsafe not in output


@pytest.mark.parametrize(
    "argv",
    [
        ["--check"],
        ["--live"],
        ["--check", "--json", "--prompt", "patient text"],
        ["--live", "--json", "--client-id", "unsafe"],
        ["--live", "--json", "--retry-count", "2"],
    ],
)
def test_cli_requires_json_and_rejects_arbitrary_or_identity_options(argv) -> None:
    operation = _operation()

    with pytest.raises(SystemExit) as exc:
        operation._parse_args(argv)

    assert exc.value.code == 2


def test_operation_source_has_no_application_or_azure_mutation_surface() -> None:
    operation = _operation()
    source = inspect.getsource(operation)

    for forbidden in (
        "CaseProcessingService",
        "case_repository",
        "email",
        "sms",
        "deploy",
        "role assignment",
        "create_version",
        "verify_hosted_foundry_agent",
    ):
        assert forbidden not in source
