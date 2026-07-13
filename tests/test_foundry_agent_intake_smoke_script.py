import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

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

GATED_RESULT_KEYS = LIVE_RESULT_KEYS | {
    "verification",
    "invocation_attempted",
    "application_intake_attempted",
    "temporary_application_state_restored",
    "expected_safe_output_fields_present",
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
        "azure_ai_foundry_model_deployment_name": "secret-model-deployment",
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


def _smoke_case(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "processing_trace": SimpleNamespace(
            agent_attempted=True,
            agent_output_valid=True,
            agent_fallback_used=False,
        ),
        "notificationEmailStatus": "Suppressed",
        "notificationSmsStatus": "Suppressed",
        "reviewStatus": "PendingReview",
        "intakeStatus": "Complete",
        "urgency": "Routine",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _visible_application_state() -> tuple[object, ...]:
    from src.app.dependencies import (
        case_repository as application_repository,
        email_notification_sender,
        sms_notification_sender,
    )
    from src.app.main import app
    import src.app.routes.intake as intake_route

    return (
        intake_route.case_processing_service,
        intake_route.case_repository,
        app.dependency_overrides,
        dict(app.dependency_overrides),
        tuple(asyncio.run(application_repository.list_cases())),
        tuple(email_notification_sender.sent_notifications),
        tuple(sms_notification_sender.sent_notifications),
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


def test_check_with_verification_gate_is_offline_and_reports_both_stages(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_foundry_agent_intake as script

    monkeypatch.setattr(script, "AppSettings", _settings)
    monkeypatch.setattr(
        script,
        "foundry_agent_verification_sdk_available",
        lambda: True,
    )
    monkeypatch.setattr(
        script,
        "_create_verification_service",
        lambda: pytest.fail("check mode must not create a verification client"),
    )
    monkeypatch.setattr(
        script,
        "_create_live_agent",
        lambda settings: pytest.fail("check mode must not create an agent client"),
    )
    monkeypatch.setattr(
        script,
        "_run_intake_route",
        lambda agent: pytest.fail("check mode must not process intake"),
    )

    exit_code = script.main(
        ["--check", "--json", "--verify-agent-version"]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["ready"] is True
    assert payload["verification"] == {
        "requested": True,
        "azure_lookup_attempted": False,
        "configured_agent_version_matched": None,
        "category": "not_attempted",
        "sdk_available": True,
    }
    assert payload["invocation_attempted"] is False
    assert payload["application_intake_attempted"] is False
    assert payload["temporary_application_state_restored"] is True
    assert payload["expected_safe_output_fields_present"] == []
    assert payload["azure_call_made"] is False
    assert payload["client_created"] is False
    assert "AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT_NAME" in payload[
        "required_settings_present"
    ]


def test_check_with_verification_gate_reports_sdk_unavailable_without_clients(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_foundry_agent_intake as script

    monkeypatch.setattr(script, "AppSettings", _settings)
    monkeypatch.setattr(
        script,
        "foundry_agent_verification_sdk_available",
        lambda: False,
    )
    monkeypatch.setattr(
        script,
        "_create_verification_service",
        lambda: pytest.fail("SDK readiness failure must not create a client"),
    )

    exit_code = script.main(
        ["--check", "--json", "--verify-agent-version"]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert payload["ready"] is False
    assert payload["category"] == "sdk_unavailable"
    assert payload["verification"]["requested"] is True
    assert payload["verification"]["azure_lookup_attempted"] is False
    assert payload["verification"]["sdk_available"] is False
    assert payload["invocation_attempted"] is False
    assert payload["application_intake_attempted"] is False


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
    with pytest.raises(SystemExit):
        script.main(["--verify-agent-version"])


def test_live_missing_configuration_uses_safe_contract_and_nonzero_exit(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_foundry_agent_intake as script

    monkeypatch.setattr(
        script,
        "AppSettings",
        lambda: _settings(azure_ai_foundry_agent_version=None),
    )
    monkeypatch.setattr(
        script,
        "_create_live_agent",
        lambda settings: pytest.fail("missing configuration must not create agent"),
    )

    exit_code = script.main(["--live", "--json"])

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert exit_code == 2
    assert set(payload) == LIVE_RESULT_KEYS
    assert payload["ok"] is False
    assert payload["category"] == "missing_configuration"
    _assert_unsafe_values_absent(output)


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


def test_successful_verification_precedes_fixed_application_intake(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_foundry_agent_intake as script
    from src.app.services.foundry_agent_verification import (
        FoundryAgentVerificationResult,
    )

    events: list[str] = []
    agent = FakeSuccessfulAgent()

    class FakeVerification:
        def verify(self, request: object) -> FoundryAgentVerificationResult:
            events.append("verify")
            assert request.agent_name == "secret-agent-name"
            assert request.agent_version == "9"
            assert request.model_deployment_name == "secret-model-deployment"
            assert "foundry-agent-intake-v1" in request.instructions
            return FoundryAgentVerificationResult.success()

    def create_agent(settings: object) -> FakeSuccessfulAgent:
        events.append("create-agent")
        return agent

    monkeypatch.setattr(script, "AppSettings", _settings)
    monkeypatch.setattr(script, "_create_verification_service", FakeVerification)
    monkeypatch.setattr(script, "_create_live_agent", create_agent)

    state_before = _visible_application_state()
    exit_code = script.main(
        ["--live", "--json", "--verify-agent-version"]
    )
    state_after = _visible_application_state()

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert exit_code == 0
    assert events == ["verify", "create-agent"]
    assert agent.calls == [script.FICTIONAL_INTAKE_TEXT]
    assert set(payload) == GATED_RESULT_KEYS
    assert payload["ok"] is True
    assert payload["category"] == "success"
    assert payload["verification"]["requested"] is True
    assert payload["verification"]["azure_lookup_attempted"] is True
    assert payload["verification"]["configured_agent_version_matched"] is True
    assert payload["verification"]["category"] == "success"
    assert payload["invocation_attempted"] is True
    assert payload["application_intake_attempted"] is True
    assert payload["agent_output_valid"] is True
    assert payload["fallback_used"] is False
    assert payload["review_status"] == "PendingReview"
    assert payload["notifications_suppressed"] is True
    assert payload["temporary_application_state_restored"] is True
    assert state_after == state_before
    assert payload["expected_safe_output_fields_present"] == [
        "extraction",
        "urgency",
        "handoffNote",
    ]
    _assert_unsafe_values_absent(output)


def test_successful_verification_preserves_safe_fallback_on_invocation_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_foundry_agent_intake as script
    from src.app.services.foundry_agent_verification import (
        FoundryAgentVerificationResult,
    )

    class FakeVerification:
        def verify(self, request: object) -> FoundryAgentVerificationResult:
            return FoundryAgentVerificationResult.success()

    monkeypatch.setattr(script, "AppSettings", _settings)
    monkeypatch.setattr(script, "_create_verification_service", FakeVerification)
    monkeypatch.setattr(
        script,
        "_create_live_agent",
        lambda settings: FakeExplodingAgent(),
    )

    state_before = _visible_application_state()
    exit_code = script.main(
        ["--live", "--json", "--verify-agent-version"]
    )
    state_after = _visible_application_state()

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert exit_code == 1
    assert payload["verification"]["configured_agent_version_matched"] is True
    assert payload["invocation_attempted"] is True
    assert payload["application_intake_attempted"] is True
    assert payload["category"] == "safe_fallback_used"
    assert payload["agent_output_valid"] is False
    assert payload["fallback_used"] is True
    assert payload["case_saved"] is True
    assert payload["review_status"] == "PendingReview"
    assert payload["notifications_suppressed"] is True
    assert payload["temporary_application_state_restored"] is True
    assert state_after == state_before
    assert payload["expected_safe_output_fields_present"] == [
        "extraction",
        "urgency",
        "handoffNote",
    ]
    _assert_unsafe_values_absent(output)


def test_verification_gate_requires_model_setting_but_legacy_smoke_does_not(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_foundry_agent_intake as script

    settings = _settings(azure_ai_foundry_model_deployment_name=None)
    assert script.build_foundry_agent_intake_readiness(settings).ready is True
    monkeypatch.setattr(script, "AppSettings", lambda: settings)
    monkeypatch.setattr(
        script,
        "_create_verification_service",
        lambda: pytest.fail("missing model setting must stop before verification"),
    )
    monkeypatch.setattr(
        script,
        "_create_live_agent",
        lambda current_settings: pytest.fail(
            "missing gated setting must stop before invocation"
        ),
    )

    exit_code = script.main(
        ["--live", "--json", "--verify-agent-version"]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert payload["category"] == "missing_configuration"
    assert payload["verification"]["azure_lookup_attempted"] is False
    assert payload["invocation_attempted"] is False
    assert payload["application_intake_attempted"] is False


@pytest.mark.parametrize(
    (
        "category",
        "lookup_attempted",
        "expected_category",
        "expected_match",
        "expected_sdk_available",
    ),
    [
        ("definition_mismatch", True, "definition_mismatch", False, True),
        ("agent_version_not_found", True, "agent_version_not_found", False, True),
        (
            "authentication_or_authorization_failed",
            False,
            "authentication_or_authorization_failed",
            None,
            True,
        ),
        ("agent_verification_failed", True, "azure_request_failed", None, True),
        ("response_contract_invalid", True, "response_contract_invalid", None, True),
        ("sdk_unavailable", False, "sdk_unavailable", None, False),
    ],
    ids=[
        "definition-drift",
        "version-not-found",
        "authorization-before-lookup",
        "azure-request-failed",
        "malformed-sdk-response",
        "sdk-unavailable",
    ],
)
def test_verification_failure_prevents_client_creation_and_application_intake(
    category: str,
    lookup_attempted: bool,
    expected_category: str,
    expected_match: bool | None,
    expected_sdk_available: bool,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_foundry_agent_intake as script
    from src.app.services.foundry_agent_verification import (
        FoundryAgentVerificationResult,
    )

    class FakeVerification:
        def verify(self, request: object) -> FoundryAgentVerificationResult:
            return FoundryAgentVerificationResult.failure(
                category,
                agent_name_present=True,
                agent_version_present=True,
                model_deployment_name_present=True,
                azure_lookup_attempted=lookup_attempted,
            )

    monkeypatch.setattr(script, "AppSettings", _settings)
    monkeypatch.setattr(script, "_create_verification_service", FakeVerification)
    monkeypatch.setattr(
        script,
        "_create_live_agent",
        lambda settings: pytest.fail(
            "verification failure must not create the invocation client"
        ),
    )
    monkeypatch.setattr(
        script,
        "_run_intake_route",
        lambda agent: pytest.fail("verification failure must not process intake"),
    )

    exit_code = script.main(
        ["--live", "--json", "--verify-agent-version"]
    )

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert exit_code == 1
    assert set(payload) == GATED_RESULT_KEYS
    assert payload["ok"] is False
    assert payload["category"] == expected_category
    assert payload["verification"]["category"] == expected_category
    assert (
        payload["verification"]["azure_lookup_attempted"]
        is lookup_attempted
    )
    assert (
        payload["verification"]["configured_agent_version_matched"]
        is expected_match
    )
    assert (
        payload["verification"]["sdk_available"]
        is expected_sdk_available
    )
    assert payload["invocation_attempted"] is False
    assert payload["application_intake_attempted"] is False
    assert payload["temporary_application_state_restored"] is True
    assert payload["expected_safe_output_fields_present"] == []
    _assert_unsafe_values_absent(output)


def test_malformed_verifier_result_prevents_invocation_safely(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_foundry_agent_intake as script

    class MalformedVerification:
        def verify(self, request: object) -> SimpleNamespace:
            return SimpleNamespace(
                ok=True,
                category="success",
                raw_response="Bearer raw-model-response secret.example",
            )

    monkeypatch.setattr(script, "AppSettings", _settings)
    monkeypatch.setattr(
        script,
        "_create_verification_service",
        MalformedVerification,
    )
    monkeypatch.setattr(
        script,
        "_create_live_agent",
        lambda settings: pytest.fail("malformed verification must stop the smoke"),
    )

    exit_code = script.main(
        ["--live", "--json", "--verify-agent-version"]
    )

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert exit_code == 1
    assert payload["category"] == "response_contract_invalid"
    assert payload["verification"]["category"] == "response_contract_invalid"
    assert payload["verification"]["azure_lookup_attempted"] is None
    assert payload["verification"]["configured_agent_version_matched"] is None
    assert payload["verification"]["sdk_available"] is None
    assert payload["invocation_attempted"] is False
    assert payload["application_intake_attempted"] is False
    _assert_unsafe_values_absent(output)


def test_verifier_exception_is_sanitized_and_does_not_change_application_state(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_foundry_agent_intake as script
    from src.app.main import app
    import src.app.routes.intake as intake_route

    original_service = intake_route.case_processing_service
    original_repository = intake_route.case_repository
    original_overrides = app.dependency_overrides
    original_override_values = dict(original_overrides)

    class ExplodingVerification:
        def verify(self, request: object) -> None:
            raise RuntimeError(
                "Bearer verifier-secret raw prompt raw model response Traceback"
            )

    monkeypatch.setattr(script, "AppSettings", _settings)
    monkeypatch.setattr(
        script,
        "_create_verification_service",
        ExplodingVerification,
    )
    monkeypatch.setattr(
        script,
        "_create_live_agent",
        lambda settings: pytest.fail("verifier exception must prevent invocation"),
    )

    exit_code = script.main(
        ["--live", "--json", "--verify-agent-version"]
    )

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert exit_code == 1
    assert payload["category"] == "agent_verification_failed"
    assert payload["verification"]["azure_lookup_attempted"] is None
    assert payload["verification"]["configured_agent_version_matched"] is None
    assert payload["verification"]["sdk_available"] is None
    assert payload["invocation_attempted"] is False
    assert payload["application_intake_attempted"] is False
    assert payload["temporary_application_state_restored"] is True
    assert intake_route.case_processing_service is original_service
    assert intake_route.case_repository is original_repository
    assert app.dependency_overrides is original_overrides
    assert app.dependency_overrides == original_override_values
    _assert_unsafe_values_absent(output)


def test_guarded_route_exception_reports_observed_state_restoration(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_foundry_agent_intake as script
    from src.app.main import app
    import src.app.routes.intake as intake_route
    from src.app.services.foundry_agent_verification import (
        FoundryAgentVerificationResult,
    )

    class FakeVerification:
        def verify(self, request: object) -> FoundryAgentVerificationResult:
            return FoundryAgentVerificationResult.success()

    temporary_key = object()
    temporary_value = object()

    async def raise_after_temporary_mutation(request: object) -> None:
        app.dependency_overrides[temporary_key] = temporary_value
        raise RuntimeError(
            "Bearer route-secret raw patient response Traceback"
        )

    monkeypatch.setattr(script, "AppSettings", _settings)
    monkeypatch.setattr(script, "_create_verification_service", FakeVerification)
    monkeypatch.setattr(
        script,
        "_create_live_agent",
        lambda settings: FakeSuccessfulAgent(),
    )
    monkeypatch.setattr(
        intake_route,
        "create_text_intake",
        raise_after_temporary_mutation,
    )

    state_before = _visible_application_state()
    exit_code = script.main(
        ["--live", "--json", "--verify-agent-version"]
    )
    state_after = _visible_application_state()

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert exit_code == 1
    assert payload["category"] == "unexpected_error"
    assert payload["application_intake_attempted"] is True
    assert payload["invocation_attempted"] is False
    assert payload["temporary_application_state_restored"] is True
    assert temporary_key not in app.dependency_overrides
    assert state_after == state_before
    _assert_unsafe_values_absent(output)


def test_guarded_restoration_mismatch_is_reported_without_state_leakage(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_foundry_agent_intake as script
    import src.app.routes.intake as intake_route
    from src.app.services.foundry_agent_verification import (
        FoundryAgentVerificationResult,
    )

    class FakeVerification:
        def verify(self, request: object) -> FoundryAgentVerificationResult:
            return FoundryAgentVerificationResult.success()

    original_repository = intake_route.case_repository

    def corrupt_state_then_fail(agent: object) -> None:
        intake_route.case_repository = SimpleNamespace(
            secret="Bearer repository-secret raw patient state"
        )
        raise RuntimeError("Traceback raw route failure")

    monkeypatch.setattr(script, "AppSettings", _settings)
    monkeypatch.setattr(script, "_create_verification_service", FakeVerification)
    monkeypatch.setattr(script, "_create_live_agent", lambda settings: object())
    monkeypatch.setattr(script, "_run_intake_route", corrupt_state_then_fail)

    exit_code = script.main(
        ["--live", "--json", "--verify-agent-version"]
    )

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert exit_code == 1
    assert payload["category"] == "unexpected_error"
    assert payload["temporary_application_state_restored"] is False
    assert "repository-secret" not in output
    assert "raw patient state" not in output
    intake_route.case_repository = original_repository
    _assert_unsafe_values_absent(output)


@pytest.mark.parametrize(
    ("case", "handoff_note_present", "expected_fields"),
    [
        (
            _smoke_case(
                patient=SimpleNamespace(name=None),
                summary="Safe fallback summary.",
                symptoms=[],
                urgency=None,
            ),
            False,
            ["extraction"],
        ),
        (_smoke_case(), False, ["urgency"]),
        (_smoke_case(urgency=None), True, ["handoffNote"]),
    ],
    ids=["extraction-only", "urgency-only", "handoff-only"],
)
def test_gated_expected_fields_are_reported_independently(
    case: SimpleNamespace,
    handoff_note_present: bool,
    expected_fields: list[str],
) -> None:
    import scripts.smoke_foundry_agent_intake as script
    from src.app.services.foundry_agent_verification import (
        FoundryAgentVerificationResult,
    )

    result = script._result_from_case(
        case,
        case_saved=True,
        handoff_note_present=handoff_note_present,
    )
    payload = script._live_result_payload(
        result,
        verification_requested=True,
        verification_result=FoundryAgentVerificationResult.success(),
    )

    assert payload["expected_safe_output_fields_present"] == expected_fields


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


def test_non_success_route_result_is_sanitized_request_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_foundry_agent_intake as script

    monkeypatch.setattr(script, "AppSettings", _settings)
    monkeypatch.setattr(script, "_create_live_agent", lambda settings: object())
    monkeypatch.setattr(
        script,
        "_run_intake_route",
        lambda agent: SimpleNamespace(
            status_code=503,
            text="Bearer route-secret raw response body Traceback",
        ),
    )

    exit_code = script.main(["--live", "--json"])

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert exit_code != 0
    assert set(payload) == LIVE_RESULT_KEYS
    assert payload["ok"] is False
    assert payload["category"] == "route_request_failed"
    _assert_unsafe_values_absent(output)


def test_expected_route_exception_is_sanitized_request_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_foundry_agent_intake as script

    monkeypatch.setattr(script, "AppSettings", _settings)
    monkeypatch.setattr(script, "_create_live_agent", lambda settings: object())

    def raise_request_failure(agent: object) -> None:
        raise HTTPException(
            status_code=422,
            detail="Bearer route-secret raw patient response Traceback",
        )

    monkeypatch.setattr(script, "_run_intake_route", raise_request_failure)

    exit_code = script.main(["--live", "--json"])

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert exit_code != 0
    assert payload["category"] == "route_request_failed"
    _assert_unsafe_values_absent(output)


def test_unexpected_route_runner_exception_is_not_misclassified(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_foundry_agent_intake as script

    monkeypatch.setattr(script, "AppSettings", _settings)
    monkeypatch.setattr(script, "_create_live_agent", lambda settings: object())

    def raise_unexpected_error(agent: object) -> None:
        raise RuntimeError(
            "Bearer runner-secret raw patient response Traceback"
        )

    monkeypatch.setattr(script, "_run_intake_route", raise_unexpected_error)

    exit_code = script.main(["--live", "--json"])

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert exit_code != 0
    assert payload["category"] == "unexpected_error"
    _assert_unsafe_values_absent(output)


def test_present_trace_proving_agent_not_attempted_is_not_success() -> None:
    import scripts.smoke_foundry_agent_intake as script

    case = _smoke_case(
        processing_trace=SimpleNamespace(
            agent_attempted=False,
            agent_output_valid=None,
            agent_fallback_used=False,
        )
    )

    result = script._result_from_case(
        case,
        case_saved=True,
        handoff_note_present=True,
    )

    assert result.ok is False
    assert result.category == "agent_not_attempted"
    assert result.agent_output_valid is None
    assert result.fallback_used is False


def test_not_attempted_with_valid_output_is_invalid_sanitized_contract(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_foundry_agent_intake as script

    contradictory_case = _smoke_case(
        processing_trace=SimpleNamespace(
            agent_attempted=False,
            agent_output_valid=True,
            agent_fallback_used=False,
        ),
        id="secret-case-id",
        summary="raw secret summary",
    )
    monkeypatch.setattr(script, "AppSettings", _settings)
    monkeypatch.setattr(script, "_create_live_agent", lambda settings: object())
    monkeypatch.setattr(
        script,
        "_run_intake_route",
        lambda agent: (contradictory_case, True, True),
    )

    exit_code = script.main(["--live", "--json"])

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert exit_code != 0
    assert set(payload) == LIVE_RESULT_KEYS
    assert payload["ok"] is False
    assert payload["category"] == "response_contract_invalid"
    _assert_unsafe_values_absent(output)


@pytest.mark.parametrize(
    "outcome",
    [
        "success",
        "safe-fallback",
        "expected-exception",
        "unexpected-exception",
        "malformed",
    ],
)
def test_route_run_restores_exact_application_state_for_every_exit(
    outcome: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scripts.smoke_foundry_agent_intake as script
    from src.app.main import app
    import src.app.routes.intake as intake_route

    existing_key = object()
    existing_override = object()
    temporary_key = object()
    temporary_override = object()
    previous_overrides = {existing_key: existing_override}
    original_service = object()
    original_repository = object()
    original_route = intake_route.create_text_intake
    monkeypatch.setattr(app, "dependency_overrides", previous_overrides)
    monkeypatch.setattr(intake_route, "case_processing_service", original_service)
    monkeypatch.setattr(intake_route, "case_repository", original_repository)

    async def state_mutating_route(request: object) -> object:
        app.dependency_overrides[temporary_key] = temporary_override
        if outcome == "expected-exception":
            raise HTTPException(status_code=422, detail="raw secret route detail")
        if outcome == "unexpected-exception":
            raise RuntimeError("Bearer secret-token raw patient data Traceback")
        if outcome == "malformed":
            return SimpleNamespace(id="secret-case-id")
        return await original_route(request)

    monkeypatch.setattr(intake_route, "create_text_intake", state_mutating_route)

    route_agent = (
        FakeInvalidAgent() if outcome == "safe-fallback" else FakeSuccessfulAgent()
    )
    if outcome in {"success", "safe-fallback"}:
        case, case_saved, handoff_note_present = asyncio.run(
            script._run_intake_route_async(route_agent)
        )
        assert case.reviewStatus == "PendingReview"
        assert case_saved is True
        assert handoff_note_present is True
        assert case.notificationEmailStatus == "Suppressed"
        assert case.notificationSmsStatus == "Suppressed"
        assert case.processing_trace.agent_fallback_used is (
            outcome == "safe-fallback"
        )
    else:
        with pytest.raises(Exception):
            asyncio.run(script._run_intake_route_async(FakeSuccessfulAgent()))

    assert app.dependency_overrides is previous_overrides
    assert app.dependency_overrides == {existing_key: existing_override}
    assert app.dependency_overrides[existing_key] is existing_override
    assert temporary_key not in app.dependency_overrides
    assert intake_route.case_processing_service is original_service
    assert intake_route.case_repository is original_repository


def test_consecutive_route_runs_use_fresh_local_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scripts.smoke_foundry_agent_intake as script
    from src.app.dependencies import (
        case_repository as application_repository,
        email_notification_sender,
        sms_notification_sender,
    )
    from src.app.services.case_repository import InMemoryCaseRepository
    import src.app.routes.intake as intake_route

    repositories: list[InMemoryCaseRepository] = []
    services: list[script.CaseProcessingService] = []

    class TrackingRepository(InMemoryCaseRepository):
        def __init__(self) -> None:
            super().__init__()
            repositories.append(self)

    class TrackingService(script.CaseProcessingService):
        def __init__(self, **kwargs: object) -> None:
            super().__init__(**kwargs)
            services.append(self)

    original_service = intake_route.case_processing_service
    original_repository = intake_route.case_repository
    application_cases = list(asyncio.run(application_repository.list_cases()))
    email_notifications = list(email_notification_sender.sent_notifications)
    sms_notifications = list(sms_notification_sender.sent_notifications)
    first_agent = FakeSuccessfulAgent()
    second_agent = FakeSuccessfulAgent()
    monkeypatch.setattr(script, "InMemoryCaseRepository", TrackingRepository)
    monkeypatch.setattr(script, "CaseProcessingService", TrackingService)

    first_result = asyncio.run(script._run_intake_route_async(first_agent))
    second_result = asyncio.run(script._run_intake_route_async(second_agent))

    assert len(repositories) == 2
    assert len(services) == 2
    assert repositories[0] is not repositories[1]
    assert services[0] is not services[1]
    assert services[0].nurse_intake_agent is first_agent
    assert services[1].nurse_intake_agent is second_agent
    assert services[0].email_notification_sender is None
    assert services[0].sms_notification_sender is None
    assert services[1].email_notification_sender is None
    assert services[1].sms_notification_sender is None
    assert services[0].suppress_notifications is True
    assert services[1].suppress_notifications is True
    assert len(asyncio.run(repositories[0].list_cases())) == 1
    assert len(asyncio.run(repositories[1].list_cases())) == 1
    assert first_result[0] is not second_result[0]
    assert first_agent.calls == [script.FICTIONAL_INTAKE_TEXT]
    assert second_agent.calls == [script.FICTIONAL_INTAKE_TEXT]
    assert intake_route.case_processing_service is original_service
    assert intake_route.case_repository is original_repository
    assert asyncio.run(application_repository.list_cases()) == application_cases
    assert email_notification_sender.sent_notifications == email_notifications
    assert sms_notification_sender.sent_notifications == sms_notifications


@pytest.mark.parametrize(
    ("overrides", "case_saved", "handoff_note_present"),
    [
        ({"processing_trace": None}, True, True),
        ({}, False, True),
        ({"reviewStatus": "Reviewed"}, True, True),
        ({"intakeStatus": None}, True, True),
        ({"intakeStatus": "ProcessingFailed"}, True, True),
        ({"urgency": None}, True, True),
        ({}, True, False),
        ({"notificationEmailStatus": "Accepted"}, True, True),
        (
            {
                "processing_trace": SimpleNamespace(
                    agent_output_valid=True,
                    agent_fallback_used=False,
                )
            },
            True,
            True,
        ),
    ],
    ids=[
        "missing-trace",
        "case-not-saved",
        "review-not-pending",
        "missing-intake-status",
        "failed-intake-status",
        "missing-urgency",
        "missing-handoff-note",
        "notifications-not-suppressed",
        "missing-agent-attempted-metadata",
    ],
)
def test_missing_success_postcondition_is_response_contract_invalid(
    overrides: dict[str, object],
    case_saved: bool,
    handoff_note_present: bool,
) -> None:
    import scripts.smoke_foundry_agent_intake as script

    result = script._result_from_case(
        _smoke_case(**overrides),
        case_saved=case_saved,
        handoff_note_present=handoff_note_present,
    )

    assert result.ok is False
    assert result.category == "response_contract_invalid"


@pytest.mark.parametrize(
    ("overrides", "case_saved", "handoff_note_present"),
    [
        ({}, False, True),
        ({"reviewStatus": "Reviewed"}, True, True),
        ({"notificationSmsStatus": "Accepted"}, True, True),
        ({"urgency": None}, True, True),
        ({}, True, False),
    ],
    ids=[
        "case-not-saved",
        "review-not-pending",
        "notifications-not-suppressed",
        "urgency-missing",
        "handoff-note-missing",
    ],
)
def test_fallback_does_not_mask_invalid_safe_postcondition(
    overrides: dict[str, object],
    case_saved: bool,
    handoff_note_present: bool,
) -> None:
    import scripts.smoke_foundry_agent_intake as script

    fallback_trace = SimpleNamespace(
        agent_attempted=True,
        agent_output_valid=False,
        agent_fallback_used=True,
    )
    result = script._result_from_case(
        _smoke_case(processing_trace=fallback_trace, **overrides),
        case_saved=case_saved,
        handoff_note_present=handoff_note_present,
    )

    assert result.ok is False
    assert result.category == "response_contract_invalid"


@pytest.mark.parametrize(
    "category",
    [
        "missing_configuration",
        "unsafe_application_configuration",
        "route_request_failed",
        "agent_not_attempted",
        "safe_fallback_used",
        "response_contract_invalid",
        "unexpected_error",
    ],
)
def test_every_failure_payload_uses_exact_safe_live_contract(
    category: str,
) -> None:
    import scripts.smoke_foundry_agent_intake as script

    result = script._empty_live_result(category)

    assert result.ok is False
    assert set(result.to_json_dict()) == LIVE_RESULT_KEYS


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
    assert set(payload) == LIVE_RESULT_KEYS
    assert payload["category"] == "unsafe_application_configuration"
    assert payload["agent_attempted"] is False
    assert payload["case_saved"] is False


@pytest.mark.parametrize(
    ("case", "case_saved", "handoff_note_present", "expected_category"),
    [
        (
            _smoke_case(
                processing_trace=SimpleNamespace(
                    agent_attempted=False,
                    agent_output_valid=None,
                    agent_fallback_used=False,
                )
            ),
            True,
            True,
            "agent_not_attempted",
        ),
        (
            _smoke_case(
                processing_trace=None,
                id="secret-case-id",
                summary="raw secret summary",
                symptoms=["raw secret symptom"],
                prompt="raw secret prompt",
            ),
            True,
            True,
            "response_contract_invalid",
        ),
    ],
    ids=["agent-not-attempted", "invalid-response-contract"],
)
def test_serialized_application_failures_are_sanitized_and_nonzero(
    case: SimpleNamespace,
    case_saved: bool,
    handoff_note_present: bool,
    expected_category: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_foundry_agent_intake as script

    monkeypatch.setattr(script, "AppSettings", _settings)
    monkeypatch.setattr(script, "_create_live_agent", lambda settings: object())
    monkeypatch.setattr(
        script,
        "_run_intake_route",
        lambda agent: (case, case_saved, handoff_note_present),
    )

    exit_code = script.main(["--live", "--json"])

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert exit_code != 0
    assert set(payload) == LIVE_RESULT_KEYS
    assert payload["ok"] is False
    assert payload["category"] == expected_category
    _assert_unsafe_values_absent(output)


def _assert_unsafe_values_absent(output: str) -> None:
    for unsafe in (
        "Fictional Smoke Patient",
        "fictional-callback-001",
        "1990-01-01",
        "fictional routine refill",
        "raw-secret-agent-output",
        "raw patient response",
        "raw response body",
        "raw secret summary",
        "raw secret symptom",
        "raw secret prompt",
        "secret-case-id",
        "secret.example",
        "secret-agent-name",
        "secret-model-deployment",
        "secret-token",
        "raw-model-response",
        "Bearer",
        "Traceback",
        "@",
    ):
        assert unsafe not in output
