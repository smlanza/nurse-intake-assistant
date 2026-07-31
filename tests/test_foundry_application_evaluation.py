import asyncio
from importlib import import_module
import json
from pathlib import Path
import socket
from types import SimpleNamespace
from typing import Any

import pytest

from src.app.application_composition import compose_application
from src.app.services.case_repository import InMemoryCaseRepository
from src.app.services.email_notification_sender import MockEmailNotificationSender
from src.app.services.foundry_agent_client import FoundryAgentResponse
from src.app.services.foundry_ai_service import FoundryAiService
from src.app.services.foundry_evaluation import (
    EvaluationDataset,
    EvaluationReport,
    evaluate_dataset,
    load_candidate_fixture,
    load_evaluation_dataset,
)
from src.app.services.mock_ai_service import MockAiService
from src.app.services.nurse_intake_agent import FoundryNurseIntakeAgent
from src.app.services.sms_notification_sender import MockSmsNotificationSender


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATASET_PATH = PROJECT_ROOT / "evaluation" / "fictional-intake-baseline-v1.json"
CANDIDATE_PATH = (
    PROJECT_ROOT / "evaluation" / "fictional-intake-baseline-v1-candidates.json"
)


def _runner():
    try:
        return import_module("src.app.services.foundry_application_evaluation")
    except ModuleNotFoundError:
        pytest.fail("The offline application-composed evaluation runner is absent.")


def _dataset() -> EvaluationDataset:
    return load_evaluation_dataset(DATASET_PATH)


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        app_mode="unsafe-input-is-overridden",
        demo_suppress_notifications=False,
        email_provider="acs",
        email_provider_normalized="acs",
        sms_provider="acs",
        sms_provider_normalized="acs",
        ai_provider="mock",
        ai_provider_normalized="mock",
        agent_provider="mock",
        agent_provider_normalized="mock",
        azure_ai_foundry_project_endpoint="https://offline.invalid/project",
        azure_ai_foundry_model_deployment_name="offline-evaluation-model",
    )


def _structured_payload(case: Any) -> dict[str, object]:
    expected = case.expected
    return {
        "patient": {
            "name": expected.structured_fields.patient_name,
            "date_of_birth": expected.structured_fields.date_of_birth,
            "callback_number": expected.structured_fields.callback_identifier,
        },
        "reason_for_calling": expected.structured_fields.reason_for_calling,
        "symptoms": list(expected.symptoms),
        "summary": f"Fictional deterministic summary for {case.case_id}.",
        "urgency": expected.advisory_ai_urgency,
        "urgency_rationale": "Deterministic offline advisory result.",
        "advisory_disclaimer": "Advisory only; nurse review required.",
        "missing_fields": list(expected.missing_fields),
        "uncertain_fields": [],
    }


def _agent_payload(case: Any) -> dict[str, object]:
    payload = _structured_payload(case)
    return {
        "extraction": {
            key: payload[key]
            for key in (
                "patient",
                "reason_for_calling",
                "symptoms",
                "summary",
                "missing_fields",
                "uncertain_fields",
            )
        },
        "urgency": {
            key: payload[key]
            for key in (
                "urgency",
                "urgency_rationale",
                "advisory_disclaimer",
            )
        },
    }


class DatasetStructuredClient:
    def __init__(self, dataset: EvaluationDataset) -> None:
        self.dataset = dataset
        self.calls: list[dict[str, str]] = []

    def complete_structured_extraction(
        self,
        prompt: str,
        model_deployment_name: str,
    ) -> str:
        self.calls.append(
            {"prompt": prompt, "model_deployment_name": model_deployment_name}
        )
        matching = [case for case in self.dataset.cases if case.intake_text in prompt]
        if len(matching) != 1:
            raise AssertionError("fake structured client could not select one case")
        return json.dumps(_structured_payload(matching[0]), sort_keys=True)


class DatasetAgentClient:
    def __init__(
        self,
        dataset: EvaluationDataset,
        *,
        malformed_case_ids: set[str] | None = None,
    ) -> None:
        self.dataset = dataset
        self.malformed_case_ids = malformed_case_ids or set()
        self.requests: list[Any] = []

    async def invoke_agent(self, request: Any) -> FoundryAgentResponse:
        self.requests.append(request)
        matching = [
            case for case in self.dataset.cases if case.intake_text == request.intake_text
        ]
        if len(matching) != 1:
            raise AssertionError("fake Agent client could not select one case")
        case = matching[0]
        content = (
            "malformed Agent output"
            if case.case_id in self.malformed_case_ids
            else json.dumps(_agent_payload(case), sort_keys=True)
        )
        return FoundryAgentResponse(
            content=content,
            metadata={"provider": "foundry-agent", "agentMode": "fake"},
        )


def _run(
    mode: str,
    *,
    dataset: EvaluationDataset | None = None,
    client: object | None = None,
    settings: object | None = None,
) -> EvaluationReport:
    runner = _runner()
    selected_dataset = dataset or _dataset()
    selected_client = client
    if selected_client is None:
        selected_client = (
            DatasetStructuredClient(selected_dataset)
            if mode == "structured-extraction"
            else DatasetAgentClient(selected_dataset)
        )
    return runner.run_foundry_application_evaluation(
        mode=mode,
        dataset=selected_dataset,
        settings=settings or _settings(),
        fake_client=selected_client,
    )


def _record_composition(monkeypatch: pytest.MonkeyPatch):
    runner = _runner()
    applications = []

    def recording_compose(settings):
        application = compose_application(settings)
        applications.append(application)
        return application

    monkeypatch.setattr(runner, "compose_application", recording_compose)
    return applications


def test_supported_modes_are_exact_and_unsupported_modes_fail_before_composition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _runner()
    assert {mode.value for mode in runner.ApplicationEvaluationMode} == {
        "structured-extraction",
        "agent",
    }
    monkeypatch.setattr(
        runner,
        "compose_application",
        lambda settings: pytest.fail("invalid mode must fail before composition"),
    )

    for malformed in ("", " ", "structured", "agent ", None, 7):
        with pytest.raises(runner.FoundryApplicationEvaluationError) as error:
            runner.run_foundry_application_evaluation(
                mode=malformed,
                dataset=_dataset(),
                settings=_settings(),
                fake_client=object(),
            )
        assert error.value.category == "invalid_mode"
        assert str(error.value) == "Offline application evaluation failed."


@pytest.mark.parametrize("mode", ["structured-extraction", "agent"])
def test_each_mode_uses_production_composition_and_complete_case_processing(
    mode: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset = _dataset()
    applications = _record_composition(monkeypatch)
    client = (
        DatasetStructuredClient(dataset)
        if mode == "structured-extraction"
        else DatasetAgentClient(dataset)
    )

    report = _run(mode, dataset=dataset, client=client)

    assert isinstance(report, EvaluationReport)
    assert len(applications) == 1
    assert report.metrics.evaluated_case_count == len(dataset.cases)
    assert {case.case_id for case in report.cases} == {
        case.case_id for case in dataset.cases
    }
    calls = client.calls if isinstance(client, DatasetStructuredClient) else client.requests
    assert len(calls) == len(dataset.cases)


def test_structured_mode_uses_actual_foundry_service_and_fake_client_seam(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset = _dataset()
    client = DatasetStructuredClient(dataset)
    applications = _record_composition(monkeypatch)

    _run("structured-extraction", dataset=dataset, client=client)

    application = applications[0]
    assert isinstance(application.ai_service, FoundryAiService)
    assert application.ai_service.client is client
    assert application.nurse_intake_agent is None
    assert all(call["model_deployment_name"] == "offline-evaluation-model" for call in client.calls)


def test_agent_mode_uses_actual_foundry_agent_and_fake_client_seam(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset = _dataset()
    client = DatasetAgentClient(dataset)
    applications = _record_composition(monkeypatch)

    _run("agent", dataset=dataset, client=client)

    application = applications[0]
    assert isinstance(application.ai_service, MockAiService)
    assert isinstance(application.nurse_intake_agent, FoundryNurseIntakeAgent)
    assert application.nurse_intake_agent.client is client
    assert all("Return JSON only" in request.instructions for request in client.requests)


@pytest.mark.parametrize(
    ("mode", "adapter_name"),
    [
        ("structured-extraction", "adapt_foundry_ai_service_output"),
        ("agent", "adapt_nurse_intake_agent_output"),
    ],
)
def test_every_application_result_uses_the_existing_mode_adapter(
    mode: str,
    adapter_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _runner()
    dataset = _dataset()
    original = getattr(runner, adapter_name)
    adapted_cases = []

    def recording_adapter(case):
        adapted_cases.append(case)
        return original(case)

    monkeypatch.setattr(runner, adapter_name, recording_adapter)

    _run(mode, dataset=dataset)

    assert len(adapted_cases) == len(dataset.cases)
    assert all(case.reviewStatus == "PendingReview" for case in adapted_cases)


@pytest.mark.parametrize(
    ("malformed_case_id", "expected_rule", "expected_final"),
    [
        ("invalid-candidate-output", "Routine", "Unknown"),
        ("positive-urgent-red-flag", "Urgent", "Urgent"),
    ],
)
def test_malformed_agent_output_uses_real_fallback_and_rule_invariant(
    malformed_case_id: str,
    expected_rule: str,
    expected_final: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _runner()
    dataset = _dataset()
    client = DatasetAgentClient(dataset, malformed_case_ids={malformed_case_id})
    original = runner.adapt_nurse_intake_agent_output
    candidates = {}

    def recording_adapter(case):
        candidate = original(case)
        matching = [
            item for item in dataset.cases if item.intake_text == case.transcript
        ]
        candidates[matching[0].case_id] = candidate
        return candidate

    monkeypatch.setattr(runner, "adapt_nurse_intake_agent_output", recording_adapter)

    _run("agent", dataset=dataset, client=client)

    candidate = candidates[malformed_case_id]
    assert candidate.contract_valid is False
    assert candidate.advisory_ai_urgency == "Unknown"
    assert candidate.deterministic_rule_result == expected_rule
    assert candidate.final_application_urgency == expected_final
    assert candidate.nurse_review_required is True
    assert candidate.missing_fields == ("agent_output",)


def test_candidate_keys_are_dataset_ids_and_evaluator_receives_complete_mapping_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _runner()
    dataset = _dataset()
    evaluator_calls = []

    def recording_evaluator(received_dataset, candidates):
        evaluator_calls.append((received_dataset, dict(candidates)))
        return evaluate_dataset(received_dataset, candidates)

    monkeypatch.setattr(runner, "evaluate_dataset", recording_evaluator)

    report = _run("structured-extraction", dataset=dataset)

    assert len(evaluator_calls) == 1
    received_dataset, candidates = evaluator_calls[0]
    expected_ids = {case.case_id for case in dataset.cases}
    assert received_dataset == dataset
    assert set(candidates) == expected_ids
    assert {case.case_id for case in report.cases} == expected_ids
    assert not any(candidate.model_fields_set & {"case_id", "id"} for candidate in candidates.values())


@pytest.mark.parametrize("defect", ["blank", "duplicate"])
def test_invalid_dataset_ids_fail_closed_before_composition(
    defect: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _runner()
    dataset = _dataset()
    cases = list(dataset.cases)
    if defect == "blank":
        cases[0] = cases[0].model_copy(update={"case_id": " "})
    else:
        cases[1] = cases[1].model_copy(update={"case_id": cases[0].case_id.upper()})
    invalid_dataset = dataset.model_copy(update={"cases": tuple(cases)})
    monkeypatch.setattr(
        runner,
        "compose_application",
        lambda settings: pytest.fail("invalid dataset must fail before composition"),
    )

    with pytest.raises(runner.FoundryApplicationEvaluationError) as error:
        _run("structured-extraction", dataset=invalid_dataset)

    assert error.value.category == "invalid_dataset"


def test_missing_application_output_aborts_without_evaluation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _runner()
    original_compose = compose_application

    def composition_with_missing_output(settings):
        application = original_compose(settings)

        async def missing_output(raw_text, case_type):
            return None

        application.case_processing_service.process = missing_output
        return application

    monkeypatch.setattr(runner, "compose_application", composition_with_missing_output)
    monkeypatch.setattr(
        runner,
        "evaluate_dataset",
        lambda dataset, candidates: pytest.fail("partial candidates must not evaluate"),
    )

    with pytest.raises(runner.FoundryApplicationEvaluationError) as error:
        _run("structured-extraction")

    assert error.value.category == "processing_failed"


def test_unexpected_processing_boundary_failure_is_sanitized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _runner()

    def failing_async_run(coroutine):
        coroutine.close()
        raise RuntimeError("private orchestration marker")

    monkeypatch.setattr(runner.asyncio, "run", failing_async_run)
    monkeypatch.setattr(
        runner,
        "evaluate_dataset",
        lambda dataset, candidates: pytest.fail("failed processing must not evaluate"),
    )

    with pytest.raises(runner.FoundryApplicationEvaluationError) as error:
        _run("structured-extraction")

    assert error.value.category == "processing_failed"
    assert str(error.value) == "Offline application evaluation failed."
    assert "private" not in str(error.value)


@pytest.mark.parametrize(
    "candidate_keys",
    [
        {"complete-routine"},
        {case.case_id for case in _dataset().cases} | {"unexpected"},
    ],
    ids=["missing", "unexpected"],
)
def test_incomplete_or_unexpected_candidate_keys_fail_closed(
    candidate_keys: set[str],
) -> None:
    runner = _runner()
    dataset = _dataset()

    with pytest.raises(runner.FoundryApplicationEvaluationError) as error:
        runner._require_exact_candidate_keys(
            dataset,
            {key: object() for key in candidate_keys},
        )

    assert error.value.category == "invalid_candidate_set"


def test_adapter_rejection_aborts_without_partial_evaluation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _runner()
    calls = 0

    def rejecting_adapter(case):
        nonlocal calls
        calls += 1
        raise ValueError("private contradictory evidence marker")

    monkeypatch.setattr(runner, "adapt_foundry_ai_service_output", rejecting_adapter)
    monkeypatch.setattr(
        runner,
        "evaluate_dataset",
        lambda dataset, candidates: pytest.fail("rejected candidates must not evaluate"),
    )

    with pytest.raises(runner.FoundryApplicationEvaluationError) as error:
        _run("structured-extraction")

    assert calls == 1
    assert error.value.category == "adaptation_failed"
    assert "private" not in str(error.value)


def test_existing_fixture_scores_are_unchanged() -> None:
    dataset = _dataset()
    candidates = load_candidate_fixture(CANDIDATE_PATH)

    before = evaluate_dataset(dataset, candidates)
    _run("structured-extraction", dataset=dataset)
    after = evaluate_dataset(dataset, candidates)

    assert after == before
    assert after.metrics.candidate_contract_valid_count == 7
    assert after.metrics.evaluated_case_count == 8
    assert after.metrics.final_urgency_correct_count == 5


@pytest.mark.parametrize("mode", ["structured-extraction", "agent"])
def test_persistence_is_isolated_and_notifications_are_suppressed(
    mode: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset = _dataset()
    applications = _record_composition(monkeypatch)

    report = _run(mode, dataset=dataset)

    application = applications[0]
    assert isinstance(application.case_repository, InMemoryCaseRepository)
    assert isinstance(application.email_notification_sender, MockEmailNotificationSender)
    assert isinstance(application.sms_notification_sender, MockSmsNotificationSender)
    cases = asyncio.run(application.case_repository.list_cases())
    assert len(cases) == len(dataset.cases)
    assert all(case.notificationEmailStatus == "Suppressed" for case in cases)
    assert all(case.notificationSmsStatus == "Suppressed" for case in cases)
    assert application.email_notification_sender.sent_notifications == []
    assert application.sms_notification_sender.sent_notifications == []
    serialized = json.dumps(report.to_json_dict(), sort_keys=True)
    assert "notification" not in serialized.casefold()


@pytest.mark.parametrize("mode", ["structured-extraction", "agent"])
def test_live_clients_credentials_network_and_acs_construction_are_forbidden(
    mode: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.services import (
        email_notification_sender_factory,
        foundry_live_client,
        sms_notification_sender_factory,
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("offline runner reached a live dependency")

    monkeypatch.setattr(foundry_live_client, "create_foundry_live_client", forbidden)
    monkeypatch.setattr(foundry_live_client, "_get_default_credential_class", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(email_notification_sender_factory, "AcsEmailNotificationSender", forbidden)
    monkeypatch.setattr(sms_notification_sender_factory, "AcsSmsNotificationSender", forbidden)

    report = _run(mode)

    assert report.ok is True


def test_structured_mode_never_constructs_or_invokes_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.services import nurse_intake_agent_factory

    original = nurse_intake_agent_factory.create_optional_nurse_intake_agent

    def verify_mock_only(settings):
        assert settings.agent_provider_normalized == "mock"
        return original(settings)

    monkeypatch.setattr(
        nurse_intake_agent_factory,
        "create_optional_nurse_intake_agent",
        verify_mock_only,
    )
    monkeypatch.setattr(
        FoundryNurseIntakeAgent,
        "analyze_intake",
        lambda self, raw_text: pytest.fail("structured mode invoked Agent"),
    )

    _run("structured-extraction")


def test_agent_mode_never_constructs_or_invokes_structured_foundry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.services import ai_service_factory

    original = ai_service_factory.create_ai_service

    def verify_mock_only(settings):
        assert settings.ai_provider_normalized == "mock"
        return original(settings)

    monkeypatch.setattr(ai_service_factory, "create_ai_service", verify_mock_only)
    monkeypatch.setattr(
        FoundryAiService,
        "extract_and_summarize",
        lambda self, raw_text: pytest.fail("Agent mode invoked structured Foundry"),
    )

    _run("agent")


@pytest.mark.parametrize("mode", ["structured-extraction", "agent"])
def test_repeated_runs_have_equal_typed_results_and_deterministic_json(
    mode: str,
) -> None:
    dataset = _dataset()

    first = _run(mode, dataset=dataset)
    second = _run(mode, dataset=dataset)
    first_json = json.dumps(
        first.to_json_dict(), separators=(",", ":"), sort_keys=True
    )
    second_json = json.dumps(
        second.to_json_dict(), separators=(",", ":"), sort_keys=True
    )

    assert first == second
    assert first_json == second_json
    assert "offline.invalid" not in first_json
    assert "offline-evaluation-model" not in first_json
    assert not any(case.id in first_json for case in [])


def test_generated_repository_case_ids_never_enter_evaluation_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    applications = _record_composition(monkeypatch)

    report = _run("structured-extraction")

    cases = asyncio.run(applications[0].case_repository.list_cases())
    serialized = json.dumps(report.to_json_dict(), sort_keys=True)
    assert cases
    assert all(case.id not in serialized for case in cases)
    assert all(case.createdUtc.isoformat() not in serialized for case in cases)
    assert all(case.transcript not in serialized for case in cases)


def test_missing_fake_client_fails_before_composition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _runner()
    monkeypatch.setattr(
        runner,
        "compose_application",
        lambda settings: pytest.fail("missing fake must fail before composition"),
    )

    with pytest.raises(runner.FoundryApplicationEvaluationError) as error:
        runner.run_foundry_application_evaluation(
            mode="agent",
            dataset=_dataset(),
            settings=_settings(),
            fake_client=None,
        )

    assert error.value.category == "missing_fake_client"
