from importlib import import_module
import inspect
import json
from pathlib import Path
import socket

from pydantic import ValidationError
import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATASET_PATH = PROJECT_ROOT / "evaluation" / "fictional-intake-baseline-v1.json"
CANDIDATE_FIXTURE_PATH = (
    PROJECT_ROOT / "evaluation" / "fictional-intake-baseline-v1-candidates.json"
)


def _evaluation():
    try:
        return import_module("src.app.services.foundry_evaluation")
    except ModuleNotFoundError:
        pytest.fail("The offline Foundry evaluation boundary is not implemented.")


def test_valid_v1_dataset_loads() -> None:
    evaluation = _evaluation()

    dataset = evaluation.load_evaluation_dataset(DATASET_PATH)

    assert dataset.dataset_version == "fictional-intake-baseline-v1"
    assert len(dataset.cases) == 8
    assert len({case.case_id for case in dataset.cases}) == 8


def _expected_payload(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "structured_fields": {
            "patient_name": "Fictional Rowan Example",
            "date_of_birth": "2001-01-01",
            "callback_identifier": "fictional-callback-rowan",
            "reason_for_calling": "routine follow-up",
        },
        "symptoms": ["mild cough"],
        "missing_fields": [],
        "advisory_ai_urgency": "Routine",
        "final_application_urgency": "Routine",
        "deterministic_rule_result": "Routine",
        "nurse_review_required": True,
    }
    values.update(overrides)
    return values


def _case_payload(
    case_id: str = "case-a",
    *,
    expected: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "case_id": case_id,
        "intake_text": f"Fictional intake text for {case_id}.",
        "expected": expected or _expected_payload(),
    }


def _dataset_payload(*cases: dict[str, object]) -> dict[str, object]:
    return {
        "dataset_version": "fictional-intake-baseline-v1",
        "cases": list(cases or (_case_payload(),)),
    }


def _candidate_payload(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "contract_valid": True,
        "structured_fields": {
            "patient_name": "Fictional Rowan Example",
            "date_of_birth": "2001-01-01",
            "callback_identifier": "fictional-callback-rowan",
            "reason_for_calling": "routine follow-up",
        },
        "symptoms": ["mild cough"],
        "missing_fields": [],
        "advisory_ai_urgency": "Routine",
        "final_application_urgency": "Routine",
        "deterministic_rule_result": "Routine",
        "nurse_review_required": True,
        "summary_text": "Fictional nonclinical baseline summary.",
    }
    values.update(overrides)
    return values


def _invalid_candidate_payload(**overrides: object) -> dict[str, object]:
    values = _candidate_payload(
        contract_valid=False,
        advisory_ai_urgency="Unknown",
        final_application_urgency="Unknown",
    )
    values.update(overrides)
    return values


def _write_payload(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _load_dataset(tmp_path: Path, payload: object):
    evaluation = _evaluation()
    path = _write_payload(tmp_path / "dataset.json", payload)
    return evaluation.load_evaluation_dataset(path)


def test_repository_dataset_and_candidates_are_clearly_fictional() -> None:
    evaluation = _evaluation()

    dataset = evaluation.load_evaluation_dataset(DATASET_PATH)
    candidates = evaluation.load_candidate_fixture(CANDIDATE_FIXTURE_PATH)
    serialized = DATASET_PATH.read_text() + CANDIDATE_FIXTURE_PATH.read_text()

    assert all("fictional" in case.intake_text.casefold() for case in dataset.cases)
    assert set(candidates) == {case.case_id for case in dataset.cases}
    assert "@" not in serialized
    assert "https://" not in serialized
    assert "subscription" not in serialized.casefold()
    assert "tenant" not in serialized.casefold()


def test_missing_dataset_file_fails_safely(tmp_path: Path) -> None:
    evaluation = _evaluation()

    with pytest.raises(evaluation.EvaluationValidationError) as error:
        evaluation.load_evaluation_dataset(tmp_path / "missing.json")

    assert error.value.category == "missing_dataset"


def test_invalid_json_fails_safely(tmp_path: Path) -> None:
    evaluation = _evaluation()
    path = tmp_path / "dataset.json"
    path.write_text("{not-json", encoding="utf-8")

    with pytest.raises(evaluation.EvaluationValidationError) as error:
        evaluation.load_evaluation_dataset(path)

    assert error.value.category == "invalid_json"


def test_unsupported_dataset_version_fails(tmp_path: Path) -> None:
    evaluation = _evaluation()
    payload = _dataset_payload()
    payload["dataset_version"] = "fictional-intake-baseline-v2"

    with pytest.raises(evaluation.EvaluationValidationError) as error:
        _load_dataset(tmp_path, payload)

    assert error.value.category == "unsupported_dataset_version"


@pytest.mark.parametrize(
    "payload",
    [
        _dataset_payload(_case_payload("duplicate"), _case_payload("duplicate")),
        _dataset_payload(
            {
                **_case_payload(),
                "intake_text": "   ",
            }
        ),
        _dataset_payload(
            {
                "case_id": "missing-expected",
                "intake_text": "Fictional intake.",
            }
        ),
        _dataset_payload(
            _case_payload(
                expected=_expected_payload(advisory_ai_urgency="Unknown")
            )
        ),
        _dataset_payload(
            _case_payload(
                expected=_expected_payload(
                    final_application_urgency="Unknown"
                )
            )
        ),
        _dataset_payload(
            _case_payload(
                expected=_expected_payload(
                    deterministic_rule_result="Unknown"
                )
            )
        ),
        _dataset_payload(
            _case_payload(
                expected=_expected_payload(deterministic_rule_result="Matched")
            )
        ),
        _dataset_payload(
            _case_payload(expected=_expected_payload(nurse_review_required="true"))
        ),
        _dataset_payload(
            _case_payload(expected=_expected_payload(nurse_review_required=False))
        ),
        _dataset_payload(
            _case_payload(expected=_expected_payload(symptoms="mild cough"))
        ),
        _dataset_payload(
            _case_payload(expected=_expected_payload(unexpected="ambiguous"))
        ),
        {
            **_dataset_payload(),
            "unexpected": "ambiguous",
        },
    ],
    ids=[
        "duplicate-case-id",
        "blank-intake",
        "missing-expected",
        "unknown-expected-advisory-urgency",
        "unknown-expected-final-urgency",
        "unknown-expected-rule-result",
        "unknown-rule-result",
        "nonboolean-review",
        "review-not-required",
        "incorrect-collection-type",
        "unexpected-expected-shape",
        "unexpected-dataset-shape",
    ],
)
def test_malformed_dataset_contract_fails_closed(
    payload: object,
    tmp_path: Path,
) -> None:
    evaluation = _evaluation()

    with pytest.raises(evaluation.EvaluationValidationError) as error:
        _load_dataset(tmp_path, payload)

    assert error.value.category == "invalid_dataset"


def test_empty_case_collection_and_blank_case_id_fail(tmp_path: Path) -> None:
    evaluation = _evaluation()

    for payload in (
        {
            "dataset_version": "fictional-intake-baseline-v1",
            "cases": [],
        },
        _dataset_payload(_case_payload(" ")),
    ):
        with pytest.raises(evaluation.EvaluationValidationError) as error:
            _load_dataset(tmp_path, payload)
        assert error.value.category == "invalid_dataset"


def test_structured_fields_use_trimmed_exact_equality(tmp_path: Path) -> None:
    evaluation = _evaluation()
    dataset = _load_dataset(tmp_path, _dataset_payload())
    candidate = _candidate_payload(
        structured_fields={
            "patient_name": " Fictional Rowan Example ",
            "date_of_birth": "2001-01-01",
            "callback_identifier": "fictional-callback-rowan",
            "reason_for_calling": "Routine follow-up",
        }
    )

    report = evaluation.evaluate_dataset(dataset, {"case-a": candidate})

    case = report.cases[0]
    assert case.structured_field_exact_match_count == 3
    assert case.structured_field_comparison_count == 4
    assert report.metrics.structured_field_exact_match_rate == 0.75


def test_collection_scoring_is_order_independent_and_deduplicated(
    tmp_path: Path,
) -> None:
    evaluation = _evaluation()
    expected = _expected_payload(
        symptoms=["fever", "cough"],
        missing_fields=["patient.name", "patient.callback_identifier"],
    )
    dataset = _load_dataset(
        tmp_path,
        _dataset_payload(_case_payload(expected=expected)),
    )
    candidate = _candidate_payload(
        symptoms=[" COUGH ", "cough", "nausea"],
        missing_fields=["patient.name", "patient.name", "reason_for_calling"],
    )

    report = evaluation.evaluate_dataset(dataset, {"case-a": candidate})
    metrics = report.metrics

    assert (metrics.symptom_true_positives, metrics.symptom_false_positives) == (
        1,
        1,
    )
    assert metrics.symptom_false_negatives == 1
    assert metrics.symptom_precision == 0.5
    assert metrics.symptom_recall == 0.5
    assert metrics.symptom_f1 == 0.5
    assert metrics.missing_field_true_positives == 1
    assert metrics.missing_field_false_positives == 1
    assert metrics.missing_field_false_negatives == 1
    assert metrics.missing_field_recall == 0.5


def test_urgency_rules_and_review_metrics_are_deterministic(tmp_path: Path) -> None:
    evaluation = _evaluation()
    dataset = _load_dataset(tmp_path, _dataset_payload())
    candidate = _candidate_payload(
        advisory_ai_urgency="Urgent",
        final_application_urgency="Routine",
        deterministic_rule_result="Urgent",
        nurse_review_required=False,
    )

    metrics = evaluation.evaluate_dataset(
        dataset,
        {"case-a": candidate},
    ).metrics

    assert metrics.advisory_urgency_correct_count == 0
    assert metrics.advisory_urgency_accuracy == 0.0
    assert metrics.final_urgency_correct_count == 1
    assert metrics.final_urgency_accuracy == 1.0
    assert metrics.deterministic_rule_agreement_count == 0
    assert metrics.deterministic_rule_agreement_rate == 0.0
    assert metrics.nurse_review_invariant_correct_count == 0
    assert metrics.nurse_review_invariant_rate == 0.0


@pytest.mark.parametrize(
    "candidate",
    [
        _candidate_payload(),
        _candidate_payload(
            advisory_ai_urgency="Urgent",
            final_application_urgency="Urgent",
            deterministic_rule_result="Urgent",
        ),
        _invalid_candidate_payload(),
        _invalid_candidate_payload(
            final_application_urgency="Urgent",
            deterministic_rule_result="Urgent",
        ),
    ],
    ids=[
        "valid-routine",
        "valid-urgent",
        "invalid-routine-rule",
        "invalid-urgent-rule",
    ],
)
def test_candidate_urgency_invariants_accept_supported_states(
    candidate: dict[str, object],
) -> None:
    evaluation = _evaluation()

    result = evaluation.EvaluationCandidate.model_validate(candidate)

    assert result.contract_valid is candidate["contract_valid"]
    assert result.advisory_ai_urgency == candidate["advisory_ai_urgency"]
    assert (
        result.final_application_urgency
        == candidate["final_application_urgency"]
    )
    assert (
        result.deterministic_rule_result
        == candidate["deterministic_rule_result"]
    )


@pytest.mark.parametrize(
    "candidate",
    [
        _candidate_payload(advisory_ai_urgency="Unknown"),
        _candidate_payload(final_application_urgency="Unknown"),
        _invalid_candidate_payload(advisory_ai_urgency="Routine"),
        _invalid_candidate_payload(advisory_ai_urgency="Urgent"),
        _invalid_candidate_payload(final_application_urgency="Routine"),
        _invalid_candidate_payload(final_application_urgency="Urgent"),
        _invalid_candidate_payload(
            deterministic_rule_result="Urgent",
            final_application_urgency="Unknown",
        ),
        _invalid_candidate_payload(
            deterministic_rule_result="Urgent",
            final_application_urgency="Routine",
        ),
        _invalid_candidate_payload(deterministic_rule_result="Unknown"),
        _invalid_candidate_payload(nurse_review_required=False),
    ],
    ids=[
        "valid-unknown-advisory",
        "valid-unknown-final",
        "invalid-routine-advisory",
        "invalid-urgent-advisory",
        "invalid-routine-rule-routine-final",
        "invalid-routine-rule-urgent-final",
        "invalid-urgent-rule-unknown-final",
        "invalid-urgent-rule-routine-final",
        "unknown-rule-result",
        "invalid-review-not-required",
    ],
)
def test_candidate_urgency_invariants_reject_contradictory_states(
    candidate: dict[str, object],
) -> None:
    evaluation = _evaluation()

    with pytest.raises(ValidationError):
        evaluation.EvaluationCandidate.model_validate(candidate)


def test_unknown_observed_urgency_is_scored_without_aborting(
    tmp_path: Path,
) -> None:
    evaluation = _evaluation()
    dataset = _load_dataset(
        tmp_path,
        _dataset_payload(_case_payload("case-b"), _case_payload("case-a")),
    )
    candidates = {
        "case-a": _invalid_candidate_payload(),
        "case-b": _candidate_payload(),
    }

    report = evaluation.evaluate_dataset(dataset, candidates)

    assert report.metrics.evaluated_case_count == 2
    assert report.metrics.candidate_contract_valid_count == 1
    assert report.metrics.candidate_contract_valid_rate == 0.5
    assert report.metrics.advisory_urgency_correct_count == 1
    assert report.metrics.advisory_urgency_accuracy == 0.5
    assert report.metrics.final_urgency_correct_count == 1
    assert report.metrics.final_urgency_accuracy == 0.5
    assert report.metrics.deterministic_rule_agreement_count == 2
    assert report.metrics.deterministic_rule_agreement_rate == 1.0
    assert report.metrics.nurse_review_invariant_correct_count == 2
    assert report.metrics.nurse_review_invariant_rate == 1.0
    assert report.cases[0].candidate_contract_valid is False
    assert report.cases[0].advisory_urgency_match is False
    assert report.cases[0].final_urgency_match is False
    assert report.cases[0].deterministic_rule_match is True
    assert report.cases[0].nurse_review_invariant_match is True
    assert report.cases[0].error_category == "candidate_contract_invalid"


def test_zero_denominators_return_zero(tmp_path: Path) -> None:
    evaluation = _evaluation()
    expected = _expected_payload(symptoms=[], missing_fields=[])
    dataset = _load_dataset(
        tmp_path,
        _dataset_payload(_case_payload(expected=expected)),
    )
    candidate = _candidate_payload(symptoms=[], missing_fields=[])

    metrics = evaluation.evaluate_dataset(
        dataset,
        {"case-a": candidate},
    ).metrics

    assert metrics.symptom_precision == 0.0
    assert metrics.symptom_recall == 0.0
    assert metrics.symptom_f1 == 0.0
    assert metrics.missing_field_recall == 0.0


def test_invalid_candidate_is_scored_without_aborting_dataset(
    tmp_path: Path,
) -> None:
    evaluation = _evaluation()
    dataset = _load_dataset(
        tmp_path,
        _dataset_payload(_case_payload("case-b"), _case_payload("case-a")),
    )
    candidates = {
        "case-a": {"contract_valid": True},
        "case-b": _candidate_payload(),
    }

    report = evaluation.evaluate_dataset(dataset, candidates)

    assert report.metrics.evaluated_case_count == 2
    assert report.metrics.candidate_contract_valid_count == 1
    assert report.metrics.candidate_contract_valid_rate == 0.5
    assert [case.case_id for case in report.cases] == ["case-a", "case-b"]
    assert report.cases[0].candidate_contract_valid is False
    assert report.cases[0].error_category == "candidate_contract_invalid"
    assert report.cases[1].candidate_contract_valid is True


def test_prohibited_candidate_shape_is_a_contract_failure(tmp_path: Path) -> None:
    evaluation = _evaluation()
    dataset = _load_dataset(tmp_path, _dataset_payload())
    candidate = {
        **_candidate_payload(),
        "diagnosis": "private-diagnosis-marker",
    }

    report = evaluation.evaluate_dataset(dataset, {"case-a": candidate})

    assert report.cases[0].candidate_contract_valid is False
    assert report.cases[0].error_category == "candidate_contract_invalid"


def test_reordered_cases_preserve_metrics_and_sort_results() -> None:
    evaluation = _evaluation()
    dataset = evaluation.load_evaluation_dataset(DATASET_PATH)
    candidates = evaluation.load_candidate_fixture(CANDIDATE_FIXTURE_PATH)
    reversed_dataset = dataset.model_copy(
        update={"cases": tuple(reversed(dataset.cases))}
    )

    first = evaluation.evaluate_dataset(dataset, candidates)
    second = evaluation.evaluate_dataset(reversed_dataset, candidates)

    assert first.metrics == second.metrics
    assert [case.case_id for case in first.cases] == sorted(
        case.case_id for case in dataset.cases
    )
    assert [case.case_id for case in second.cases] == [
        case.case_id for case in first.cases
    ]


def test_report_is_sanitized_and_contains_no_source_values(
    tmp_path: Path,
) -> None:
    evaluation = _evaluation()
    expected = _expected_payload(
        structured_fields={
            "patient_name": "private-patient-field-marker",
            "date_of_birth": "private-birth-marker",
            "callback_identifier": "private-callback-marker",
            "reason_for_calling": "private-reason-marker",
        },
        symptoms=["private-symptom-marker"],
    )
    case = _case_payload(expected=expected)
    case["intake_text"] = "private-intake-marker"
    dataset = _load_dataset(tmp_path, _dataset_payload(case))
    candidate = _candidate_payload(
        summary_text="private-summary-marker",
        handoff_text="private-handoff-marker",
    )

    report = evaluation.evaluate_dataset(dataset, {"case-a": candidate})
    serialized = json.dumps(report.to_json_dict())

    for private_value in (
        "private-intake-marker",
        "private-patient-field-marker",
        "private-birth-marker",
        "private-callback-marker",
        "private-reason-marker",
        "private-symptom-marker",
        "private-summary-marker",
        "private-handoff-marker",
    ):
        assert private_value not in serialized


def test_evaluation_constructs_no_azure_network_repository_or_notification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evaluation = _evaluation()
    from azure import identity
    from src.app.services.case_repository import InMemoryCaseRepository
    from src.app.services.email_notification_sender import MockEmailNotificationSender
    from src.app.services.sms_notification_sender import MockSmsNotificationSender

    def forbidden(*args, **kwargs):
        raise AssertionError("offline evaluation attempted a forbidden side effect")

    monkeypatch.setattr(identity, "DefaultAzureCredential", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(InMemoryCaseRepository, "save", forbidden)
    monkeypatch.setattr(MockEmailNotificationSender, "send_case_notification", forbidden)
    monkeypatch.setattr(MockSmsNotificationSender, "send_case_notification", forbidden)
    dataset = evaluation.load_evaluation_dataset(DATASET_PATH)
    candidates = evaluation.load_candidate_fixture(CANDIDATE_FIXTURE_PATH)

    report = evaluation.evaluate_dataset(dataset, candidates)

    assert report.ok is True
    source = inspect.getsource(evaluation)
    assert "azure." not in source
    assert "httpx" not in source
    assert "requests" not in source
