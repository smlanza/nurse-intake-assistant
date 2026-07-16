import importlib
import json
from pathlib import Path

import pytest

from src.app.services.web_app_package import plan_web_app_package


ROOT = Path(__file__).resolve().parents[1]


def _operation():
    return importlib.import_module("src.app.operations.verify_hosted_foundry_agent")


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
        azure_ai_foundry_model_deployment_name = "gpt-demo"

    return Settings()


def test_check_creates_no_live_verifier_credential_client_transport_or_runner(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    operation = _operation()
    monkeypatch.setattr(operation, "AppSettings", _settings)
    monkeypatch.setattr(operation, "hosted_verification_sdk_available", lambda: True)
    monkeypatch.setattr(
        operation,
        "_create_live_verifier",
        lambda: pytest.fail("check must not construct live dependencies"),
    )

    exit_code = operation.main(["--check", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["mode"] == "check"
    assert payload["managed_identity_attempted"] is False
    assert payload["agent_invocation_attempted"] is False


def test_missing_live_configuration_stops_before_verifier_creation(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    operation = _operation()
    settings = _settings()
    settings.azure_ai_foundry_agent_version = None
    monkeypatch.setattr(operation, "AppSettings", lambda: settings)
    monkeypatch.setattr(operation, "hosted_verification_sdk_available", lambda: True)
    monkeypatch.setattr(
        operation,
        "_create_live_verifier",
        lambda: pytest.fail("missing configuration must stop before factories"),
    )

    exit_code = operation.main(["--live", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert payload["category"] == "missing_configuration"
    assert "configured-agent" not in json.dumps(payload)


def test_live_uses_injected_verifier_and_prints_sanitized_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    operation = _operation()
    service = importlib.import_module(
        "src.app.services.hosted_foundry_agent_verification"
    )
    requests: list[object] = []

    class Verifier:
        def verify(self, request: object):
            requests.append(request)
            return service.HostedFoundryAgentVerificationResult.success("live")

    monkeypatch.setattr(operation, "AppSettings", _settings)
    monkeypatch.setattr(operation, "hosted_verification_sdk_available", lambda: True)
    monkeypatch.setattr(operation, "_create_live_verifier", Verifier)

    exit_code = operation.main(["--live", "--json"])

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert exit_code == 0
    assert requests[0].agent_version == "7"
    assert payload["agent_invocation_attempted"] is False
    for unsafe in ("secret.example", "configured-agent", "gpt-demo"):
        assert unsafe not in output


def test_live_output_never_contains_identity_header(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    operation = _operation()
    service = importlib.import_module(
        "src.app.services.hosted_foundry_agent_verification"
    )
    sensitive_header = "super-secret-app-service-identity-header"

    verifier = service.HostedFoundryAgentVerification(
        credential_factory=lambda: object(),
        project_client_factory=lambda _endpoint, _credential: type(
            "Client",
            (),
            {"agents": object()},
        )(),
        environment_reader={
            "WEBSITE_INSTANCE_ID": "instance",
            "IDENTITY_ENDPOINT": "http://identity",
            "IDENTITY_HEADER": sensitive_header,
        }.get,
        sdk_available=lambda: True,
    )
    monkeypatch.setattr(operation, "AppSettings", _settings)
    monkeypatch.setattr(operation, "hosted_verification_sdk_available", lambda: True)
    monkeypatch.setattr(operation, "_create_live_verifier", lambda: verifier)

    exit_code = operation.main(["--live", "--json"])

    output = capsys.readouterr().out
    assert exit_code != 0
    assert sensitive_header not in output
    assert "IDENTITY_HEADER" not in output


def test_cli_requires_explicit_mode_and_json() -> None:
    operation = _operation()
    for argv in ([], ["--check"], ["--live"], ["--check", "--live", "--json"]):
        with pytest.raises(SystemExit):
            operation.main(argv)


def test_import_and_help_make_no_live_call(monkeypatch, capsys) -> None:
    operation = _operation()
    monkeypatch.setattr(
        operation,
        "_create_live_verifier",
        lambda: pytest.fail("help must be inert"),
    )

    with pytest.raises(SystemExit) as exit_info:
        operation.main(["--help"])

    assert exit_info.value.code == 0
    assert "managed identity" in capsys.readouterr().out.lower()


def test_operation_is_selected_by_existing_deterministic_package_allowlist() -> None:
    plan = plan_web_app_package(ROOT)

    assert "src/app/operations/__init__.py" in plan.member_names
    assert "src/app/operations/verify_hosted_foundry_agent.py" in plan.member_names
    assert "src/app/services/hosted_foundry_agent_verification.py" in plan.member_names


def test_operation_does_not_change_mock_defaults_or_notification_suppression(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.config.settings import AppSettings

    for name in (
        "APP_MODE",
        "AI_PROVIDER",
        "AGENT_PROVIDER",
        "EMAIL_PROVIDER",
        "SMS_PROVIDER",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DEMO_SUPPRESS_NOTIFICATIONS", "true")

    settings = AppSettings()

    assert settings.app_mode == "mock"
    assert settings.ai_provider_normalized == "mock"
    assert settings.agent_provider_normalized == "mock"
    assert settings.email_provider_normalized == "mock"
    assert settings.sms_provider_normalized == "mock"
    assert settings.demo_suppress_notifications is True
