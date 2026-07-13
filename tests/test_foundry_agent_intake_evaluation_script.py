import asyncio
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.app.models.ai_outputs import (
    ExtractionSummaryResult,
    PatientInfo,
    UrgencyClassificationResult,
)
from src.app.services.foundry_agent_verification import (
    FoundryAgentVerificationResult,
)
from src.app.services.nurse_intake_agent import (
    NurseIntakeAgentMetadata,
    NurseIntakeAgentResult,
)


EXPECTED_SCENARIO_IDS = [
    "urgent-red-flag",
    "routine-non-red-flag",
    "incomplete-follow-up",
]
EXPECTED_OUTCOMES = [
    ("Urgent", "Complete"),
    ("Routine", "Complete"),
    ("Routine", "NeedsFollowUp"),
]
LIVE_RESULT_KEYS = {
    "ok",
    "mode",
    "category",
    "verification",
    "scenario_count",
    "passed_count",
    "failed_count",
    "agent_client_created",
    "agent_invocation_count",
    "application_intake_count",
    "notifications_suppressed",
    "temporary_application_state_restored",
    "scenarios",
    "recommended_next_step",
}
SCENARIO_RESULT_KEYS = {
    "id",
    "ok",
    "agent_output_valid",
    "fallback_used",
    "application_safe",
    "expected_urgency",
    "actual_urgency",
    "expected_intake_status",
    "actual_intake_status",
    "review_status",
    "notifications_suppressed",
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
            "https://secret.example/api/projects/evaluation"
        ),
        "azure_ai_foundry_agent_name": "secret-evaluation-agent",
        "azure_ai_foundry_agent_version": "17",
        "azure_ai_foundry_model_deployment_name": "secret-evaluation-model",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _agent_result(raw_text: str) -> NurseIntakeAgentResult:
    incomplete = "incomplete-follow-up" in raw_text
    reason = "fictional headache" if incomplete else "fictional evaluation request"
    symptoms = ["headache"] if incomplete else []
    return NurseIntakeAgentResult(
        extraction=ExtractionSummaryResult(
            patient=PatientInfo(
                name=None if incomplete else "Fictional Evaluation Caller",
                date_of_birth=(
                    None if incomplete else "fictional-birth-reference"
                ),
                callback_number=(
                    None if incomplete else "fictional-callback-reference"
                ),
            ),
            reason_for_calling=reason,
            symptoms=symptoms,
            summary="Fictional evaluation summary requiring nurse review.",
            missing_fields=(
                [
                    "patient.name",
                    "patient.date_of_birth",
                    "patient.callback_number",
                ]
                if incomplete
                else []
            ),
            uncertain_fields=[],
        ),
        urgency=UrgencyClassificationResult(
            urgency="Routine",
            urgency_rationale="Fictional evaluation agent rationale.",
            advisory_disclaimer="Advisory only; nurse review is required.",
        ),
        handoffNote="Fictional evaluation handoff requiring nurse review.",
        metadata=NurseIntakeAgentMetadata(
            provider="foundry-agent",
            agentMode="foundry-agent",
        ),
    )


class SuccessfulCorpusAgent:
    provider = "foundry-agent"
    agentMode = "foundry-agent"

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def analyze_intake(self, raw_text: str) -> NurseIntakeAgentResult:
        self.calls.append(raw_text)
        return _agent_result(raw_text)


class InvalidFirstScenarioAgent(SuccessfulCorpusAgent):
    async def analyze_intake(self, raw_text: str) -> object:
        self.calls.append(raw_text)
        if "urgent-red-flag" in raw_text:
            return SimpleNamespace(
                raw_output="Bearer secret-agent-output raw model response"
            )
        return _agent_result(raw_text)


class ExplodingFirstScenarioAgent(SuccessfulCorpusAgent):
    async def analyze_intake(self, raw_text: str) -> NurseIntakeAgentResult:
        self.calls.append(raw_text)
        if "urgent-red-flag" in raw_text:
            raise RuntimeError(
                "Bearer secret-token https://secret.example raw response Traceback"
            )
        return _agent_result(raw_text)


class SuccessfulVerification:
    def __init__(self, events: list[str] | None = None) -> None:
        self.calls = 0
        self.events = events

    def verify(self, request: object) -> FoundryAgentVerificationResult:
        self.calls += 1
        if self.events is not None:
            self.events.append("verify")
        assert request.agent_version == "17"
        assert request.model_deployment_name == "secret-evaluation-model"
        return FoundryAgentVerificationResult.success()


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


def _configure_success(
    monkeypatch: pytest.MonkeyPatch,
    *,
    agent: SuccessfulCorpusAgent | None = None,
    verification: SuccessfulVerification | None = None,
) -> tuple[SuccessfulCorpusAgent, SuccessfulVerification]:
    import scripts.evaluate_foundry_agent_intake as script

    configured_agent = agent or SuccessfulCorpusAgent()
    configured_verification = verification or SuccessfulVerification()
    monkeypatch.setattr(script, "AppSettings", _settings)
    monkeypatch.setattr(
        script,
        "foundry_agent_verification_sdk_available",
        lambda: True,
    )
    monkeypatch.setattr(
        script,
        "_create_verification_service",
        lambda: configured_verification,
    )
    monkeypatch.setattr(
        script,
        "_create_live_agent",
        lambda settings: configured_agent,
    )
    return configured_agent, configured_verification


def test_committed_corpus_has_stable_unique_ids_and_supported_outcomes() -> None:
    import scripts.evaluate_foundry_agent_intake as script

    scenarios = script.load_evaluation_corpus()

    assert [scenario.id for scenario in scenarios] == EXPECTED_SCENARIO_IDS
    assert len({scenario.id for scenario in scenarios}) == len(scenarios)
    assert [
        (scenario.expected_urgency, scenario.expected_intake_status)
        for scenario in scenarios
    ] == EXPECTED_OUTCOMES
    for scenario in scenarios:
        assert "fictional" in scenario.intake_text.casefold()
        assert "@" not in scenario.intake_text
        assert re.search(r"\b\d{3}[- .]\d{3}[- .]\d{4}\b", scenario.intake_text) is None
        assert re.search(r"\b\d{4}-\d{2}-\d{2}\b", scenario.intake_text) is None


@pytest.mark.parametrize(
    "records",
    [
        [
            {
                "id": "duplicate",
                "intakeText": "Fixed fictional record one.",
                "expectedUrgency": "Routine",
                "expectedIntakeStatus": "Complete",
            },
            {
                "id": "duplicate",
                "intakeText": "Fixed fictional record two.",
                "expectedUrgency": "Routine",
                "expectedIntakeStatus": "Complete",
            },
        ],
        [
            {
                "id": "invalid-outcome",
                "intakeText": "Fixed fictional invalid outcome.",
                "expectedUrgency": "Emergency",
                "expectedIntakeStatus": "Complete",
            }
        ],
        [{"id": "missing-fields"}],
    ],
    ids=["duplicate-id", "invalid-outcome", "missing-fields"],
)
def test_invalid_corpus_fails_safely(
    records: list[dict[str, object]],
    tmp_path: Path,
) -> None:
    import scripts.evaluate_foundry_agent_intake as script

    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(records))

    with pytest.raises(script.EvaluationCorpusError):
        script.load_evaluation_corpus(path)


def test_check_mode_loads_corpus_without_side_effects(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.evaluate_foundry_agent_intake as script

    monkeypatch.setattr(script, "AppSettings", _settings)
    monkeypatch.setattr(
        script,
        "foundry_agent_verification_sdk_available",
        lambda: True,
    )
    monkeypatch.setattr(
        script,
        "_create_verification_service",
        lambda: pytest.fail("check mode must not create a verifier client"),
    )
    monkeypatch.setattr(
        script,
        "_create_live_agent",
        lambda settings: pytest.fail("check mode must not create an agent client"),
    )
    monkeypatch.setattr(
        script,
        "run_foundry_agent_intake_scenario",
        lambda *args, **kwargs: pytest.fail("check mode must not process intake"),
    )
    state_before = _visible_application_state()

    exit_code = script.main(["--check", "--json"])

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert exit_code == 0
    assert payload["mode"] == "check"
    assert payload["scenario_count"] == 3
    assert payload["scenario_ids"] == EXPECTED_SCENARIO_IDS
    assert payload["verification"] == {
        "requested_in_live_mode": True,
        "azure_lookup_attempted": False,
        "configured_agent_version_matched": None,
        "category": "not_attempted",
        "sdk_available": True,
    }
    assert payload["agent_client_created"] is False
    assert payload["agent_invocation_count"] == 0
    assert payload["application_intake_count"] == 0
    assert payload["case_saved_count"] == 0
    assert payload["notifications_recorded"] is False
    assert payload["temporary_application_state_restored"] is True
    assert _visible_application_state() == state_before
    _assert_sensitive_values_absent(output, script.load_evaluation_corpus())


def test_cli_mode_and_live_gate_requirements() -> None:
    import scripts.evaluate_foundry_agent_intake as script

    for argv in ([], ["--live"], ["--live", "--json"]):
        with pytest.raises(SystemExit) as exc_info:
            script.main(argv)
        assert exc_info.value.code == 2


def test_environment_values_win_over_env_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import scripts.evaluate_foundry_agent_intake as script

    path = tmp_path / "evaluation.env"
    path.write_text("AGENT_PROVIDER=foundry-agent\n")
    monkeypatch.setenv("AGENT_PROVIDER", "mock")

    assert script._load_env_file(path) is True
    assert script.os.environ["AGENT_PROVIDER"] == "mock"


def test_verification_occurs_once_before_one_client_and_ordered_scenarios(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.evaluate_foundry_agent_intake as script

    events: list[str] = []
    verification = SuccessfulVerification(events)
    agent = SuccessfulCorpusAgent()
    monkeypatch.setattr(script, "AppSettings", _settings)
    monkeypatch.setattr(
        script,
        "foundry_agent_verification_sdk_available",
        lambda: True,
    )
    monkeypatch.setattr(
        script,
        "_create_verification_service",
        lambda: verification,
    )

    def create_agent(settings: object) -> SuccessfulCorpusAgent:
        events.append("create-agent")
        return agent

    monkeypatch.setattr(script, "_create_live_agent", create_agent)

    exit_code = script.main(
        ["--live", "--json", "--verify-agent-version"]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert events == ["verify", "create-agent"]
    assert verification.calls == 1
    assert len(agent.calls) == 3
    assert [
        scenario_id
        for raw_text in agent.calls
        for scenario_id in EXPECTED_SCENARIO_IDS
        if scenario_id in raw_text
    ] == EXPECTED_SCENARIO_IDS
    assert payload["agent_client_created"] is True
    assert payload["agent_invocation_count"] == 3
    assert payload["application_intake_count"] == 3


def test_successful_fake_agent_produces_exact_sanitized_aggregate(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.evaluate_foundry_agent_intake as script

    _configure_success(monkeypatch)
    state_before = _visible_application_state()

    exit_code = script.main(
        ["--live", "--json", "--verify-agent-version"]
    )

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert exit_code == 0
    assert set(payload) == LIVE_RESULT_KEYS
    assert payload["ok"] is True
    assert payload["mode"] == "live"
    assert payload["category"] == "success"
    assert payload["verification"] == {
        "requested": True,
        "azure_lookup_attempted": True,
        "configured_agent_version_matched": True,
        "category": "success",
        "sdk_available": True,
    }
    assert payload["scenario_count"] == 3
    assert payload["passed_count"] == 3
    assert payload["failed_count"] == 0
    assert payload["notifications_suppressed"] is True
    assert payload["temporary_application_state_restored"] is True
    assert [item["id"] for item in payload["scenarios"]] == EXPECTED_SCENARIO_IDS
    assert [
        (item["actual_urgency"], item["actual_intake_status"])
        for item in payload["scenarios"]
    ] == EXPECTED_OUTCOMES
    for item in payload["scenarios"]:
        assert set(item) == SCENARIO_RESULT_KEYS
        assert item["ok"] is True
        assert item["agent_output_valid"] is True
        assert item["fallback_used"] is False
        assert item["application_safe"] is True
        assert item["review_status"] == "PendingReview"
        assert item["notifications_suppressed"] is True
        assert item["temporary_application_state_restored"] is True
        assert item["expected_safe_output_fields_present"] == [
            "extraction",
            "urgency",
            "handoffNote",
        ]
    assert _visible_application_state() == state_before
    _assert_sensitive_values_absent(output, script.load_evaluation_corpus())


@pytest.mark.parametrize(
    "agent_type",
    [InvalidFirstScenarioAgent, ExplodingFirstScenarioAgent],
    ids=["invalid-output", "agent-exception"],
)
def test_fallback_is_application_safe_but_fails_agent_quality_and_continues(
    agent_type: type[SuccessfulCorpusAgent],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.evaluate_foundry_agent_intake as script

    agent = agent_type()
    _configure_success(monkeypatch, agent=agent)
    state_before = _visible_application_state()

    exit_code = script.main(
        ["--live", "--json", "--verify-agent-version"]
    )

    output = capsys.readouterr().out
    payload = json.loads(output)
    first = payload["scenarios"][0]
    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["category"] == "evaluation_failed"
    assert payload["passed_count"] == 2
    assert payload["failed_count"] == 1
    assert len(payload["scenarios"]) == 3
    assert len(agent.calls) == 3
    assert first["ok"] is False
    assert first["agent_output_valid"] is False
    assert first["fallback_used"] is True
    assert first["application_safe"] is True
    assert first["temporary_application_state_restored"] is True
    assert _visible_application_state() == state_before
    _assert_sensitive_values_absent(output, script.load_evaluation_corpus())


@pytest.mark.parametrize(
    ("category", "lookup_attempted", "expected_match"),
    [
        ("definition_mismatch", True, False),
        ("agent_version_not_found", True, False),
        ("authentication_or_authorization_failed", False, None),
        ("agent_verification_failed", True, None),
        ("sdk_unavailable", False, None),
    ],
)
def test_verification_failure_prevents_client_and_all_scenarios(
    category: str,
    lookup_attempted: bool,
    expected_match: bool | None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.evaluate_foundry_agent_intake as script

    class FailedVerification:
        def verify(self, request: object) -> FoundryAgentVerificationResult:
            return FoundryAgentVerificationResult.failure(
                category,
                agent_name_present=True,
                agent_version_present=True,
                model_deployment_name_present=True,
                azure_lookup_attempted=lookup_attempted,
            )

    monkeypatch.setattr(script, "AppSettings", _settings)
    monkeypatch.setattr(
        script,
        "foundry_agent_verification_sdk_available",
        lambda: True,
    )
    monkeypatch.setattr(script, "_create_verification_service", FailedVerification)
    monkeypatch.setattr(
        script,
        "_create_live_agent",
        lambda settings: pytest.fail("failed verification must block client creation"),
    )
    monkeypatch.setattr(
        script,
        "run_foundry_agent_intake_scenario",
        lambda *args, **kwargs: pytest.fail("failed verification must block intake"),
    )
    state_before = _visible_application_state()

    exit_code = script.main(
        ["--live", "--json", "--verify-agent-version"]
    )

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert exit_code == 1
    assert payload["agent_client_created"] is False
    assert payload["agent_invocation_count"] == 0
    assert payload["application_intake_count"] == 0
    assert payload["scenarios"] == []
    assert payload["verification"]["configured_agent_version_matched"] is expected_match
    assert payload["temporary_application_state_restored"] is True
    assert _visible_application_state() == state_before
    _assert_sensitive_values_absent(output, script.load_evaluation_corpus())


def test_verifier_exception_is_sanitized_before_client_creation(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.evaluate_foundry_agent_intake as script

    class ExplodingVerification:
        def verify(self, request: object) -> None:
            raise RuntimeError(
                "Bearer verifier-secret raw prompt raw response Traceback"
            )

    monkeypatch.setattr(script, "AppSettings", _settings)
    monkeypatch.setattr(
        script,
        "foundry_agent_verification_sdk_available",
        lambda: True,
    )
    monkeypatch.setattr(
        script,
        "_create_verification_service",
        ExplodingVerification,
    )
    monkeypatch.setattr(
        script,
        "_create_live_agent",
        lambda settings: pytest.fail("verifier exception must block client"),
    )
    monkeypatch.setattr(
        script,
        "run_foundry_agent_intake_scenario",
        lambda *args, **kwargs: pytest.fail(
            "verifier exception must block every scenario"
        ),
    )
    state_before = _visible_application_state()

    exit_code = script.main(
        ["--live", "--json", "--verify-agent-version"]
    )

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert exit_code == 1
    assert payload["category"] == "agent_verification_failed"
    assert payload["verification"]["azure_lookup_attempted"] is None
    assert payload["verification"]["configured_agent_version_matched"] is None
    assert payload["agent_client_created"] is False
    assert payload["agent_invocation_count"] == 0
    assert payload["application_intake_count"] == 0
    assert payload["scenarios"] == []
    assert payload["temporary_application_state_restored"] is True
    assert _visible_application_state() == state_before
    _assert_sensitive_values_absent(output, script.load_evaluation_corpus())


def test_malformed_verifier_result_is_sanitized_before_client_creation(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.evaluate_foundry_agent_intake as script

    class MalformedVerification:
        def verify(self, request: object) -> SimpleNamespace:
            return SimpleNamespace(
                ok=True,
                category="success",
                raw_response=(
                    "Bearer malformed-verifier-secret raw model response "
                    "https://secret.example"
                ),
            )

    monkeypatch.setattr(script, "AppSettings", _settings)
    monkeypatch.setattr(
        script,
        "foundry_agent_verification_sdk_available",
        lambda: True,
    )
    monkeypatch.setattr(
        script,
        "_create_verification_service",
        MalformedVerification,
    )
    monkeypatch.setattr(
        script,
        "_create_live_agent",
        lambda settings: pytest.fail("malformed verifier must block client"),
    )
    monkeypatch.setattr(
        script,
        "run_foundry_agent_intake_scenario",
        lambda *args, **kwargs: pytest.fail(
            "malformed verifier must block every scenario"
        ),
    )
    state_before = _visible_application_state()

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
    assert payload["agent_client_created"] is False
    assert payload["agent_invocation_count"] == 0
    assert payload["application_intake_count"] == 0
    assert payload["scenarios"] == []
    assert payload["temporary_application_state_restored"] is True
    assert _visible_application_state() == state_before
    assert "malformed-verifier-secret" not in output
    _assert_sensitive_values_absent(output, script.load_evaluation_corpus())


def test_restoration_mismatch_stops_later_scenarios_without_leakage(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.evaluate_foundry_agent_intake as script
    import scripts.smoke_foundry_agent_intake as smoke

    agent, _ = _configure_success(monkeypatch)
    monkeypatch.setattr(smoke, "_application_state_matches", lambda before: False)

    exit_code = script.main(
        ["--live", "--json", "--verify-agent-version"]
    )

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert exit_code == 1
    assert payload["category"] == "state_restoration_failed"
    assert len(agent.calls) == 1
    assert len(payload["scenarios"]) == 1
    assert payload["scenarios"][0]["temporary_application_state_restored"] is False
    assert payload["temporary_application_state_restored"] is False
    _assert_sensitive_values_absent(output, script.load_evaluation_corpus())


def test_route_failure_restores_state_and_later_scenarios_continue(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.evaluate_foundry_agent_intake as script
    import src.app.routes.intake as intake_route

    agent, _ = _configure_success(monkeypatch)
    original = intake_route.create_text_intake
    calls = 0

    async def fail_once(request: object) -> object:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("Bearer route-secret raw patient data Traceback")
        return await original(request)

    monkeypatch.setattr(intake_route, "create_text_intake", fail_once)
    state_before = _visible_application_state()

    exit_code = script.main(
        ["--live", "--json", "--verify-agent-version"]
    )

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert exit_code == 1
    assert len(payload["scenarios"]) == 3
    assert len(agent.calls) == 2
    assert payload["scenarios"][0]["ok"] is False
    assert payload["scenarios"][0]["application_safe"] is False
    assert payload["scenarios"][0]["temporary_application_state_restored"] is True
    assert _visible_application_state() == state_before
    _assert_sensitive_values_absent(output, script.load_evaluation_corpus())


def test_legacy_smoke_contract_remains_unchanged(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_foundry_agent_intake as smoke

    agent = SuccessfulCorpusAgent()
    monkeypatch.setattr(smoke, "AppSettings", _settings)
    monkeypatch.setattr(smoke, "_create_live_agent", lambda settings: agent)

    exit_code = smoke.main(["--live", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert set(payload) == {
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
    assert "verification" not in payload
    assert "scenarios" not in payload


def _assert_sensitive_values_absent(
    output: str,
    scenarios: list[object],
) -> None:
    for scenario in scenarios:
        assert scenario.intake_text not in output
    for unsafe in (
        "secret.example",
        "secret-evaluation-agent",
        "secret-evaluation-model",
        "secret-token",
        "secret-agent-output",
        "verifier-secret",
        "route-secret",
        "raw model response",
        "raw response",
        "raw prompt",
        "Traceback",
        "Bearer",
        "Fictional Evaluation Caller",
        "fictional-birth-reference",
        "fictional-callback-reference",
    ):
        assert unsafe not in output
