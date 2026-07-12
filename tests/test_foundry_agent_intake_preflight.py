import json
from types import SimpleNamespace

import pytest


RESULT_KEYS = {
    "ok",
    "check",
    "category",
    "ready",
    "required_settings_missing",
    "unsafe_settings",
    "azure_call_made",
    "agent_client_created",
    "intake_processed",
    "case_saved",
    "notifications_recorded",
    "manual_command",
    "recommended_next_step",
}


def _settings(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "app_mode": "mock",
        "ai_provider_normalized": "mock",
        "agent_provider_normalized": "foundry-agent",
        "email_provider_normalized": "mock",
        "sms_provider_normalized": "mock",
        "demo_suppress_notifications": True,
        "azure_ai_foundry_agent_project_endpoint": (
            "https://secret.example/api/projects/demo"
        ),
        "azure_ai_foundry_agent_name": "secret-agent-name",
        "azure_ai_foundry_agent_version": "secret-version",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _forbid_live_boundaries(monkeypatch: pytest.MonkeyPatch) -> None:
    import scripts.smoke_foundry_agent_intake as intake_smoke
    import src.app.services.foundry_agent_client as foundry_client

    monkeypatch.setattr(
        intake_smoke,
        "_create_live_agent",
        lambda settings: pytest.fail("preflight must not create an agent client"),
    )
    monkeypatch.setattr(
        intake_smoke,
        "_run_intake_route",
        lambda agent: pytest.fail("preflight must not process an intake"),
    )
    monkeypatch.setattr(
        foundry_client,
        "_create_agents_client",
        lambda endpoint: pytest.fail("preflight must not create Azure credentials"),
    )


def test_foundry_agent_intake_option_reports_ready_with_exact_safe_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.preflight as script

    monkeypatch.setattr(script, "AppSettings", _settings)
    _forbid_live_boundaries(monkeypatch)

    exit_code = script.main(["--foundry-agent-intake", "--json"])

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert exit_code == 0
    assert set(payload) == RESULT_KEYS
    assert payload == {
        "ok": True,
        "check": "foundry_agent_intake",
        "category": "success",
        "ready": True,
        "required_settings_missing": [],
        "unsafe_settings": [],
        "azure_call_made": False,
        "agent_client_created": False,
        "intake_processed": False,
        "case_saved": False,
        "notifications_recorded": False,
        "manual_command": (
            "python scripts/smoke_foundry_agent_intake.py --live --json"
        ),
        "recommended_next_step": (
            "Run the static manual command only for later fictional-data validation."
        ),
    }
    _assert_unsafe_values_absent(output)


def test_foundry_agent_intake_preflight_reports_only_missing_setting_names(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.preflight as script

    monkeypatch.setattr(
        script,
        "AppSettings",
        lambda: _settings(
            azure_ai_foundry_agent_project_endpoint=None,
            azure_ai_foundry_agent_version=None,
        ),
    )
    _forbid_live_boundaries(monkeypatch)

    exit_code = script.main(["--foundry-agent-intake", "--json"])

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert exit_code == 1
    assert set(payload) == RESULT_KEYS
    assert payload["category"] == "missing_configuration"
    assert payload["ready"] is False
    assert payload["required_settings_missing"] == [
        "AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT",
        "AZURE_AI_FOUNDRY_AGENT_VERSION",
    ]
    assert payload["agent_client_created"] is False
    assert payload["intake_processed"] is False
    assert payload["case_saved"] is False
    _assert_unsafe_values_absent(output)


def test_foundry_agent_intake_preflight_reports_only_unsafe_setting_names(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.preflight as script

    monkeypatch.setattr(
        script,
        "AppSettings",
        lambda: _settings(
            app_mode="cosmos",
            email_provider_normalized="acs",
            sms_provider_normalized="acs",
            demo_suppress_notifications=False,
        ),
    )
    _forbid_live_boundaries(monkeypatch)

    exit_code = script.main(["--foundry-agent-intake", "--json"])

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert exit_code == 1
    assert set(payload) == RESULT_KEYS
    assert payload["category"] == "unsafe_application_configuration"
    assert payload["ready"] is False
    assert payload["required_settings_missing"] == []
    assert payload["unsafe_settings"] == [
        "APP_MODE",
        "EMAIL_PROVIDER",
        "SMS_PROVIDER",
        "DEMO_SUPPRESS_NOTIFICATIONS",
    ]
    assert payload["agent_client_created"] is False
    assert payload["intake_processed"] is False
    assert payload["case_saved"] is False
    assert payload["notifications_recorded"] is False
    _assert_unsafe_values_absent(output)


def _assert_unsafe_values_absent(output: str) -> None:
    for unsafe in (
        "secret.example",
        "secret-agent-name",
        "secret-version",
        "Bearer",
        "token",
        "Fictional Smoke Patient",
        "callback",
        "Traceback",
    ):
        assert unsafe not in output
