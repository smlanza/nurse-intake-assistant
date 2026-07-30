import json
from pathlib import Path
from typing import Annotated, Any, Literal, Mapping

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
    model_validator,
)


DATASET_VERSION = "fictional-intake-baseline-v1"
CANDIDATE_FIXTURE_VERSION = "fictional-intake-baseline-candidates-v1"
DEFAULT_DATASET_ID = "evaluation/fictional-intake-baseline-v1.json"
ExpectedUrgency = Literal["Routine", "Urgent"]
ObservedCandidateUrgency = Literal["Routine", "Urgent", "Unknown"]
DeterministicRuleResult = Literal["Routine", "Urgent"]
EvaluationErrorCategory = Literal[
    "missing_dataset",
    "invalid_json",
    "unsupported_dataset_version",
    "invalid_dataset",
    "missing_candidate_fixture",
    "invalid_candidate_fixture_json",
    "unsupported_candidate_fixture_version",
    "invalid_candidate_fixture",
    "invalid_candidate_set",
]
CandidateErrorCategory = Literal[
    "candidate_missing",
    "candidate_contract_invalid",
]
NonBlankString = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class StructuredFields(_StrictFrozenModel):
    patient_name: NonBlankString | None
    date_of_birth: NonBlankString | None
    callback_identifier: NonBlankString | None
    reason_for_calling: NonBlankString | None


class ExpectedEvaluationOutput(_StrictFrozenModel):
    structured_fields: StructuredFields
    symptoms: tuple[NonBlankString, ...]
    missing_fields: tuple[NonBlankString, ...]
    advisory_ai_urgency: ExpectedUrgency
    final_application_urgency: ExpectedUrgency
    deterministic_rule_result: DeterministicRuleResult
    nurse_review_required: Literal[True]

    @field_validator("symptoms", "missing_fields", mode="before")
    @classmethod
    def _require_string_array(cls, value: object) -> object:
        return _validated_string_array(value)


class EvaluationCase(_StrictFrozenModel):
    case_id: NonBlankString
    intake_text: NonBlankString
    expected: ExpectedEvaluationOutput


class EvaluationDataset(_StrictFrozenModel):
    dataset_version: Literal[DATASET_VERSION]
    cases: tuple[EvaluationCase, ...] = Field(min_length=1)

    @field_validator("cases", mode="before")
    @classmethod
    def _require_case_array(cls, value: object) -> object:
        if not isinstance(value, list):
            raise ValueError("cases must be an array")
        return tuple(value)

    @model_validator(mode="after")
    def _require_unique_case_ids(self) -> "EvaluationDataset":
        case_ids = [case.case_id.casefold() for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("case IDs must be unique")
        return self


class EvaluationCandidate(_StrictFrozenModel):
    contract_valid: bool
    structured_fields: StructuredFields
    symptoms: tuple[NonBlankString, ...]
    missing_fields: tuple[NonBlankString, ...]
    advisory_ai_urgency: ObservedCandidateUrgency
    final_application_urgency: ObservedCandidateUrgency
    deterministic_rule_result: DeterministicRuleResult
    nurse_review_required: bool
    summary_text: NonBlankString
    handoff_text: NonBlankString | None = None

    @field_validator("symptoms", "missing_fields", mode="before")
    @classmethod
    def _require_string_array(cls, value: object) -> object:
        return _validated_string_array(value)

    @model_validator(mode="after")
    def _require_consistent_urgency_state(self) -> "EvaluationCandidate":
        if self.contract_valid:
            if (
                self.advisory_ai_urgency == "Unknown"
                or self.final_application_urgency == "Unknown"
            ):
                raise ValueError(
                    "Contract-valid candidate urgency must be known."
                )
            return self

        if self.advisory_ai_urgency != "Unknown":
            raise ValueError(
                "Contract-invalid candidate advisory urgency must be unknown."
            )
        expected_final_urgency: ObservedCandidateUrgency = (
            "Urgent"
            if self.deterministic_rule_result == "Urgent"
            else "Unknown"
        )
        if self.final_application_urgency != expected_final_urgency:
            raise ValueError(
                "Contract-invalid candidate final urgency is inconsistent."
            )
        if not self.nurse_review_required:
            raise ValueError(
                "Contract-invalid candidate requires nurse review."
            )
        return self


class _CandidateFixtureEntry(_StrictFrozenModel):
    case_id: NonBlankString
    candidate: dict[str, Any]

    @field_validator("candidate", mode="before")
    @classmethod
    def _require_candidate_object(cls, value: object) -> object:
        if not isinstance(value, dict):
            raise ValueError("candidate must be an object")
        return value


class _CandidateFixture(_StrictFrozenModel):
    fixture_version: Literal[CANDIDATE_FIXTURE_VERSION]
    candidates: tuple[_CandidateFixtureEntry, ...] = Field(min_length=1)

    @field_validator("candidates", mode="before")
    @classmethod
    def _require_candidate_array(cls, value: object) -> object:
        if not isinstance(value, list):
            raise ValueError("candidates must be an array")
        return tuple(value)

    @model_validator(mode="after")
    def _require_unique_case_ids(self) -> "_CandidateFixture":
        case_ids = [entry.case_id.casefold() for entry in self.candidates]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("candidate case IDs must be unique")
        return self


class CaseEvaluationResult(_StrictFrozenModel):
    case_id: NonBlankString
    candidate_contract_valid: bool
    structured_field_exact_match_count: int = Field(ge=0)
    structured_field_comparison_count: int = Field(ge=0)
    symptom_true_positives: int = Field(ge=0)
    symptom_false_positives: int = Field(ge=0)
    symptom_false_negatives: int = Field(ge=0)
    missing_field_true_positives: int = Field(ge=0)
    missing_field_false_positives: int = Field(ge=0)
    missing_field_false_negatives: int = Field(ge=0)
    advisory_urgency_match: bool
    final_urgency_match: bool
    deterministic_rule_match: bool
    nurse_review_invariant_match: bool
    error_category: CandidateErrorCategory | None = None


class EvaluationMetrics(_StrictFrozenModel):
    evaluated_case_count: int = Field(ge=0)
    candidate_contract_valid_count: int = Field(ge=0)
    candidate_contract_valid_rate: float = Field(ge=0.0, le=1.0)
    structured_field_exact_match_count: int = Field(ge=0)
    structured_field_comparison_count: int = Field(ge=0)
    structured_field_exact_match_rate: float = Field(ge=0.0, le=1.0)
    symptom_true_positives: int = Field(ge=0)
    symptom_false_positives: int = Field(ge=0)
    symptom_false_negatives: int = Field(ge=0)
    symptom_precision: float = Field(ge=0.0, le=1.0)
    symptom_recall: float = Field(ge=0.0, le=1.0)
    symptom_f1: float = Field(ge=0.0, le=1.0)
    missing_field_true_positives: int = Field(ge=0)
    missing_field_false_positives: int = Field(ge=0)
    missing_field_false_negatives: int = Field(ge=0)
    missing_field_recall: float = Field(ge=0.0, le=1.0)
    advisory_urgency_correct_count: int = Field(ge=0)
    advisory_urgency_accuracy: float = Field(ge=0.0, le=1.0)
    final_urgency_correct_count: int = Field(ge=0)
    final_urgency_accuracy: float = Field(ge=0.0, le=1.0)
    deterministic_rule_agreement_count: int = Field(ge=0)
    deterministic_rule_agreement_rate: float = Field(ge=0.0, le=1.0)
    nurse_review_invariant_correct_count: int = Field(ge=0)
    nurse_review_invariant_rate: float = Field(ge=0.0, le=1.0)


class EvaluationReport(_StrictFrozenModel):
    ok: Literal[True] = True
    category: Literal["success"] = "success"
    operation: Literal["evaluate_foundry_baseline"] = "evaluate_foundry_baseline"
    dataset_id: Literal[DEFAULT_DATASET_ID] = DEFAULT_DATASET_ID
    dataset_version: Literal[DATASET_VERSION] = DATASET_VERSION
    metrics: EvaluationMetrics
    cases: tuple[CaseEvaluationResult, ...]

    def to_json_dict(self) -> dict[str, object]:
        return self.model_dump(mode="json")


class EvaluationValidationError(ValueError):
    """Fail-closed evaluation setup error with an allowlisted safe category."""

    def __init__(self, category: EvaluationErrorCategory) -> None:
        super().__init__("Offline Foundry evaluation validation failed.")
        self.category = category


def load_evaluation_dataset(path: str | Path) -> EvaluationDataset:
    payload = _load_json_object(
        Path(path),
        missing_category="missing_dataset",
        invalid_json_category="invalid_json",
        invalid_shape_category="invalid_dataset",
    )
    version = payload.get("dataset_version")
    if isinstance(version, str) and version != DATASET_VERSION:
        raise EvaluationValidationError("unsupported_dataset_version")
    try:
        return EvaluationDataset.model_validate(payload)
    except ValidationError as exc:
        raise EvaluationValidationError("invalid_dataset") from exc


def load_candidate_fixture(path: str | Path) -> dict[str, dict[str, Any]]:
    payload = _load_json_object(
        Path(path),
        missing_category="missing_candidate_fixture",
        invalid_json_category="invalid_candidate_fixture_json",
        invalid_shape_category="invalid_candidate_fixture",
    )
    version = payload.get("fixture_version")
    if isinstance(version, str) and version != CANDIDATE_FIXTURE_VERSION:
        raise EvaluationValidationError("unsupported_candidate_fixture_version")
    try:
        fixture = _CandidateFixture.model_validate(payload)
    except ValidationError as exc:
        raise EvaluationValidationError("invalid_candidate_fixture") from exc
    return {
        entry.case_id: dict(entry.candidate)
        for entry in fixture.candidates
    }


def evaluate_dataset(
    dataset: EvaluationDataset,
    candidate_payloads: Mapping[str, object],
) -> EvaluationReport:
    dataset_case_ids = {case.case_id for case in dataset.cases}
    if any(
        not isinstance(case_id, str) or not case_id.strip()
        for case_id in candidate_payloads
    ):
        raise EvaluationValidationError("invalid_candidate_set")
    if set(candidate_payloads) - dataset_case_ids:
        raise EvaluationValidationError("invalid_candidate_set")

    case_results = tuple(
        _score_case(case, candidate_payloads.get(case.case_id))
        for case in sorted(dataset.cases, key=lambda item: item.case_id)
    )
    return EvaluationReport(
        metrics=_aggregate_metrics(case_results),
        cases=case_results,
    )


def _score_case(
    case: EvaluationCase,
    raw_candidate: object | None,
) -> CaseEvaluationResult:
    candidate, error_category = _validated_candidate(raw_candidate)
    candidate_valid = bool(
        candidate is not None and candidate.contract_valid
    )

    expected_symptoms = _normalized_set(case.expected.symptoms)
    expected_missing = _normalized_set(case.expected.missing_fields)
    if candidate is not None:
        advisory_match = (
            candidate.advisory_ai_urgency
            == case.expected.advisory_ai_urgency
        )
        final_match = (
            candidate.final_application_urgency
            == case.expected.final_application_urgency
        )
        rule_match = (
            candidate.deterministic_rule_result
            == case.expected.deterministic_rule_result
        )
        nurse_review_match = (
            candidate.nurse_review_required
            == case.expected.nurse_review_required
        )
    else:
        advisory_match = False
        final_match = False
        rule_match = False
        nurse_review_match = False

    if candidate_valid and candidate is not None:
        actual_symptoms = _normalized_set(candidate.symptoms)
        actual_missing = _normalized_set(candidate.missing_fields)
        structured_matches = _structured_field_matches(
            case.expected.structured_fields,
            candidate.structured_fields,
        )
    else:
        actual_symptoms = set()
        actual_missing = set()
        structured_matches = 0

    symptom_tp, symptom_fp, symptom_fn = _set_counts(
        expected_symptoms,
        actual_symptoms,
    )
    missing_tp, missing_fp, missing_fn = _set_counts(
        expected_missing,
        actual_missing,
    )
    return CaseEvaluationResult(
        case_id=case.case_id,
        candidate_contract_valid=candidate_valid,
        structured_field_exact_match_count=structured_matches,
        structured_field_comparison_count=4,
        symptom_true_positives=symptom_tp,
        symptom_false_positives=symptom_fp,
        symptom_false_negatives=symptom_fn,
        missing_field_true_positives=missing_tp,
        missing_field_false_positives=missing_fp,
        missing_field_false_negatives=missing_fn,
        advisory_urgency_match=advisory_match,
        final_urgency_match=final_match,
        deterministic_rule_match=rule_match,
        nurse_review_invariant_match=nurse_review_match,
        error_category=error_category,
    )


def _validated_candidate(
    raw_candidate: object | None,
) -> tuple[EvaluationCandidate | None, CandidateErrorCategory | None]:
    if raw_candidate is None:
        return None, "candidate_missing"
    try:
        candidate = EvaluationCandidate.model_validate(raw_candidate)
    except ValidationError:
        return None, "candidate_contract_invalid"
    if not candidate.contract_valid:
        return candidate, "candidate_contract_invalid"
    return candidate, None


def _structured_field_matches(
    expected: StructuredFields,
    actual: StructuredFields,
) -> int:
    return sum(
        _normalized_field(getattr(expected, field_name))
        == _normalized_field(getattr(actual, field_name))
        for field_name in (
            "patient_name",
            "date_of_birth",
            "callback_identifier",
            "reason_for_calling",
        )
    )


def _normalized_field(value: str | None) -> str | None:
    return value.strip() if isinstance(value, str) else None


def _normalized_set(values: tuple[str, ...]) -> set[str]:
    return {value.strip().casefold() for value in values}


def _set_counts(
    expected: set[str],
    actual: set[str],
) -> tuple[int, int, int]:
    return (
        len(expected & actual),
        len(actual - expected),
        len(expected - actual),
    )


def _aggregate_metrics(
    cases: tuple[CaseEvaluationResult, ...],
) -> EvaluationMetrics:
    evaluated_count = len(cases)
    contract_valid_count = sum(case.candidate_contract_valid for case in cases)
    structured_matches = sum(
        case.structured_field_exact_match_count for case in cases
    )
    structured_comparisons = sum(
        case.structured_field_comparison_count for case in cases
    )
    symptom_tp = sum(case.symptom_true_positives for case in cases)
    symptom_fp = sum(case.symptom_false_positives for case in cases)
    symptom_fn = sum(case.symptom_false_negatives for case in cases)
    symptom_precision = _safe_rate(symptom_tp, symptom_tp + symptom_fp)
    symptom_recall = _safe_rate(symptom_tp, symptom_tp + symptom_fn)
    symptom_f1 = _safe_rate(
        2 * symptom_precision * symptom_recall,
        symptom_precision + symptom_recall,
    )
    missing_tp = sum(case.missing_field_true_positives for case in cases)
    missing_fp = sum(case.missing_field_false_positives for case in cases)
    missing_fn = sum(case.missing_field_false_negatives for case in cases)
    advisory_correct = sum(case.advisory_urgency_match for case in cases)
    final_correct = sum(case.final_urgency_match for case in cases)
    rules_correct = sum(case.deterministic_rule_match for case in cases)
    nurse_review_correct = sum(
        case.nurse_review_invariant_match for case in cases
    )
    return EvaluationMetrics(
        evaluated_case_count=evaluated_count,
        candidate_contract_valid_count=contract_valid_count,
        candidate_contract_valid_rate=_safe_rate(
            contract_valid_count,
            evaluated_count,
        ),
        structured_field_exact_match_count=structured_matches,
        structured_field_comparison_count=structured_comparisons,
        structured_field_exact_match_rate=_safe_rate(
            structured_matches,
            structured_comparisons,
        ),
        symptom_true_positives=symptom_tp,
        symptom_false_positives=symptom_fp,
        symptom_false_negatives=symptom_fn,
        symptom_precision=symptom_precision,
        symptom_recall=symptom_recall,
        symptom_f1=symptom_f1,
        missing_field_true_positives=missing_tp,
        missing_field_false_positives=missing_fp,
        missing_field_false_negatives=missing_fn,
        missing_field_recall=_safe_rate(missing_tp, missing_tp + missing_fn),
        advisory_urgency_correct_count=advisory_correct,
        advisory_urgency_accuracy=_safe_rate(
            advisory_correct,
            evaluated_count,
        ),
        final_urgency_correct_count=final_correct,
        final_urgency_accuracy=_safe_rate(final_correct, evaluated_count),
        deterministic_rule_agreement_count=rules_correct,
        deterministic_rule_agreement_rate=_safe_rate(
            rules_correct,
            evaluated_count,
        ),
        nurse_review_invariant_correct_count=nurse_review_correct,
        nurse_review_invariant_rate=_safe_rate(
            nurse_review_correct,
            evaluated_count,
        ),
    )


def _safe_rate(numerator: int | float, denominator: int | float) -> float:
    """Return 0.0 when a deterministic metric has no observations."""

    return float(numerator / denominator) if denominator else 0.0


def _load_json_object(
    path: Path,
    *,
    missing_category: EvaluationErrorCategory,
    invalid_json_category: EvaluationErrorCategory,
    invalid_shape_category: EvaluationErrorCategory,
) -> dict[str, Any]:
    try:
        raw_text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise EvaluationValidationError(missing_category) from exc
    except OSError as exc:
        raise EvaluationValidationError(invalid_shape_category) from exc
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise EvaluationValidationError(invalid_json_category) from exc
    if not isinstance(payload, dict):
        raise EvaluationValidationError(invalid_shape_category)
    return payload


def _validated_string_array(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) for item in value
    ):
        raise ValueError("value must be an array of text")
    return tuple(value)
