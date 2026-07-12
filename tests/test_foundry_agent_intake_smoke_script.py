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
        "secret-token",
        "Bearer",
        "Traceback",
        "@",
    ):
        assert unsafe not in output
