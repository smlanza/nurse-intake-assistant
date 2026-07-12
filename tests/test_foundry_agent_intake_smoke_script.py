import json
from types import SimpleNamespace

import pytest

from src.app.models.ai_outputs import (
    ExtractionSummaryResult,
    PatientInfo,
    UrgencyClassificationResult,
)
from src.app.services.nurse_intake_agent import (
    NurseIntakeAgentMetadata,
    NurseIntakeAgentResult,
)


LIVE_RESULT_KEYS = {
    "ok",
    "mode",
    "category",
    "message",
    "agent_attempted",
    "agent_output_valid",
    "fallback_used",
    "case_saved",
    "intake_status",
    "review_status",
    "urgency_present",
    "handoff_note_present",
    "processing_trace_present",
    "notifications_suppressed",
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
        "azure_ai_foundry_agent_version": "9",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class FakeSuccessfulAgent:
    provider = "foundry-agent"
    agentMode = "foundry-agent"

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def analyze_intake(self, raw_text: str) -> NurseIntakeAgentResult:
        self.calls.append(raw_text)
        return NurseIntakeAgentResult(
            extraction=ExtractionSummaryResult(
                patient=PatientInfo(
                    name="Fictional Smoke Patient",
                    date_of_birth="1990-01-01",
                    callback_number="fictional-callback-001",
                ),
                reason_for_calling="fictional routine refill",
                symptoms=[],
                summary="Fictional routine refill request.",
                missing_fields=[],
                uncertain_fields=[],
            ),
            urgency=UrgencyClassificationResult(
                urgency="Routine",
                urgency_rationale="No urgent fictional symptoms were reported.",
                advisory_disclaimer="Advisory only; nurse review is required.",
            ),
            handoffNote="Fictional handoff note requiring nurse review.",
            metadata=NurseIntakeAgentMetadata(
                provider="foundry-agent",
                agentMode="foundry-agent",
            ),
        )


class FakeInvalidAgent:
    provider = "foundry-agent"
    agentMode = "foundry-agent"

    async def analyze_intake(self, raw_text: str) -> SimpleNamespace:
        return SimpleNamespace(
            urgency=SimpleNamespace(urgency="Routine"),
            handoffNote="raw-secret-agent-output",
        )


class FakeExplodingAgent:
    provider = "foundry-agent"
    agentMode = "foundry-agent"

    async def analyze_intake(self, raw_text: str) -> None:
        raise RuntimeError(
            "Bearer secret-token https://secret.example raw patient response Traceback"
        )


def test_check_with_complete_configuration_is_offline(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_foundry_agent_intake as script

    monkeypatch.setattr(script, "AppSettings", _settings)
    monkeypatch.setattr(
        script,
        "_create_live_agent",
        lambda settings: pytest.fail("check mode must not create an agent client"),
    )
    monkeypatch.setattr(
        script,
        "_run_intake_route",
        lambda agent: pytest.fail("check mode must not process or save intake"),
    )

    exit_code = script.main(["--check", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["ready"] is True
    assert payload["category"] == "success"
    assert payload["azure_call_made"] is False
    assert payload["client_created"] is False
    assert payload["intake_processed"] is False
    assert payload["case_saved"] is False
    assert payload["notifications_recorded"] is False


def test_check_missing_configuration_reports_names_without_values(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_foundry_agent_intake as script

    monkeypatch.setattr(
        script,
        "AppSettings",
        lambda: _settings(azure_ai_foundry_agent_version=None),
    )

    exit_code = script.main(["--check", "--json"])

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert exit_code == 2
    assert payload["category"] == "missing_configuration"
    assert payload["required_settings_missing"] == [
        "AZURE_AI_FOUNDRY_AGENT_VERSION"
    ]
    for unsafe in ("secret.example", "secret-agent-name", "Bearer", "token"):
        assert unsafe not in output


def test_live_requires_explicit_live_and_json() -> None:
    import scripts.smoke_foundry_agent_intake as script

    with pytest.raises(SystemExit):
        script.main([])
    with pytest.raises(SystemExit):
        script.main(["--live"])


def test_fake_successful_application_intake_returns_exact_safe_contract(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_foundry_agent_intake as script

    agent = FakeSuccessfulAgent()
    monkeypatch.setattr(script, "AppSettings", _settings)
    monkeypatch.setattr(script, "_create_live_agent", lambda settings: agent)

    exit_code = script.main(["--live", "--json"])

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert exit_code == 0
    assert len(agent.calls) == 1
    assert set(payload) == LIVE_RESULT_KEYS
    assert payload == {
        "ok": True,
        "mode": "live",
        "category": "success",
        "message": "Application-level Foundry Agent intake smoke succeeded.",
        "agent_attempted": True,
        "agent_output_valid": True,
        "fallback_used": False,
        "case_saved": True,
        "intake_status": "Complete",
        "review_status": "PendingReview",
        "urgency_present": True,
        "handoff_note_present": True,
        "processing_trace_present": True,
        "notifications_suppressed": True,
        "recommended_next_step": (
            "Review the sanitized result, then restore AGENT_PROVIDER=mock."
        ),
    }
    _assert_unsafe_values_absent(output)


@pytest.mark.parametrize(
    "agent",
    [FakeInvalidAgent(), FakeExplodingAgent()],
    ids=["invalid-output", "agent-exception"],
)
def test_fake_agent_failures_preserve_safe_application_fallback(
    agent: object,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_foundry_agent_intake as script

    monkeypatch.setattr(script, "AppSettings", _settings)
    monkeypatch.setattr(script, "_create_live_agent", lambda settings: agent)

    exit_code = script.main(["--live", "--json"])

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert exit_code == 1
    assert set(payload) == LIVE_RESULT_KEYS
    assert payload["ok"] is False
    assert payload["category"] == "safe_fallback_used"
    assert payload["agent_attempted"] is True
    assert payload["agent_output_valid"] is False
    assert payload["fallback_used"] is True
    assert payload["case_saved"] is True
    assert payload["review_status"] == "PendingReview"
    assert payload["notifications_suppressed"] is True
    _assert_unsafe_values_absent(output)


@pytest.mark.parametrize(
    "overrides",
    [
        {"app_mode": "cosmos"},
        {"email_provider_normalized": "acs"},
        {"sms_provider_normalized": "acs"},
        {"demo_suppress_notifications": False},
    ],
)
def test_live_refuses_unsafe_application_configuration_without_invoking(
    overrides: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_foundry_agent_intake as script

    monkeypatch.setattr(script, "AppSettings", lambda: _settings(**overrides))
    monkeypatch.setattr(
        script,
        "_create_live_agent",
        lambda settings: pytest.fail("unsafe configuration must not create agent"),
    )

    exit_code = script.main(["--live", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert payload["category"] == "unsafe_application_configuration"
    assert payload["agent_attempted"] is False
    assert payload["case_saved"] is False


def _assert_unsafe_values_absent(output: str) -> None:
    for unsafe in (
        "Fictional Smoke Patient",
        "fictional-callback-001",
        "1990-01-01",
        "fictional routine refill",
        "raw-secret-agent-output",
        "raw patient response",
        "secret.example",
        "secret-agent-name",
        "secret-token",
        "Bearer",
        "Traceback",
        "@",
    ):
        assert unsafe not in output
