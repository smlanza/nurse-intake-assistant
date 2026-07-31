from datetime import datetime, timezone
from importlib import import_module
import socket

from pydantic import ValidationError
import pytest

from src.app.models.ai_outputs import PatientInfo
from src.app.models.case import CaseDocument, ProcessingTrace
from src.app.services.foundry_evaluation import EvaluationCandidate


FIXED_UTC = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _adapters():
    try:
        return import_module("src.app.services.foundry_evaluation_adapters")
    except ModuleNotFoundError:
        pytest.fail("The offline application-output adapters are not implemented.")


def _case(
    *,
    agent_used: bool,
    contract_valid: bool = True,
    advisory_urgency: str = "Routine",
    final_urgency: str | None = None,
    rule_urgency: str = "Routine",
    review_status: str = "PendingReview",
) -> CaseDocument:
    if final_urgency is None:
        final_urgency = (
            "Urgent"
            if rule_urgency == "Urgent" or advisory_urgency == "Urgent"
            else advisory_urgency
        )

    fallback_used = agent_used and not contract_valid
    rules_override = (
        rule_urgency == "Urgent" and advisory_urgency != "Urgent"
    )
    if rules_override:
        final_source = "rules"
    elif fallback_used:
        final_source = "unknown"
    elif agent_used:
        final_source = "agent"
    else:
        final_source = "ai"

    if rule_urgency == "Urgent" and advisory_urgency == "Urgent":
        urgency_source = "RulesAndAI"
    elif rule_urgency == "Urgent":
        urgency_source = "Rules"
    elif advisory_urgency == "Urgent":
        urgency_source = "AI"
    else:
        urgency_source = "Unknown"

    if fallback_used:
        patient = PatientInfo()
        reason_for_calling = None
        symptoms: list[str] = []
        summary = "Agent output could not be safely parsed. Nurse review required."
        missing_fields = ["agent_output"]
        intake_complete = False
        intake_status = "NeedsFollowUp"
    else:
        patient = PatientInfo(
            name="Fictional Rowan Example",
            date_of_birth="2001-01-01",
            callback_number="fictional-callback-rowan",
        )
        reason_for_calling = "routine follow-up"
        symptoms = ["mild cough"]
        summary = "Fictional nonclinical application summary."
        missing_fields = ["patient.insurance"]
        intake_complete = False
        intake_status = "NeedsFollowUp"

    return CaseDocument(
        id="fictional-case-001",
        createdDate=FIXED_UTC.date().isoformat(),
        createdUtc=FIXED_UTC,
        lastStatusUpdatedUtc=FIXED_UTC,
        caseType="text-intake",
        patient=patient,
        reasonForCalling=reason_for_calling,
        symptoms=symptoms,
        transcript="Fictional intake text.",
        summary=summary,
        urgency=final_urgency,
        urgencySource=urgency_source,
        ruleUrgency=rule_urgency,
        aiUrgency=advisory_urgency,
        urgencyRationale="Fictional application urgency rationale.",
        missingFields=missing_fields,
        uncertainFields=(
            ["agent_output"] if fallback_used else ["patient.insurance"]
        ),
        intakeComplete=intake_complete,
        processingStatus="Completed",
        intakeStatus=intake_status,
        reviewStatus=review_status,
        processing_trace=ProcessingTrace(
            ai_provider=None if agent_used else "foundry",
            agent_provider="foundry-agent" if agent_used else None,
            agent_mode="foundry-agent" if agent_used else None,
            agent_used=agent_used,
            agent_attempted=agent_used,
            agent_output_valid=contract_valid if agent_used else None,
            agent_fallback_used=fallback_used,
            agent_fallback_reason=("invalid_agent_output" if fallback_used else None),
            steps=[
                "agent.extract_summary" if agent_used else "ai.extract_summary",
                (
                    "agent.classify_urgency"
                    if agent_used
                    else "ai.classify_urgency"
                ),
                "rules.apply_red_flags",
                "case.persist",
                "notifications.send",
            ],
            rules_urgency_override=rules_override,
            final_urgency_source=final_source,
            warnings=(
                [
                    "Agent output failed contract validation; "
                    "safe fallback values were used."
                ]
                if fallback_used
                else []
            ),
        ),
    )


def _assert_common_candidate(candidate: EvaluationCandidate) -> None:
    assert candidate.structured_fields.model_dump() == {
        "patient_name": "Fictional Rowan Example",
        "date_of_birth": "2001-01-01",
        "callback_identifier": "fictional-callback-rowan",
        "reason_for_calling": "routine follow-up",
    }
    assert candidate.symptoms == ("mild cough",)
    assert candidate.missing_fields == ("patient.insurance",)
    assert candidate.advisory_ai_urgency == "Routine"
    assert candidate.final_application_urgency == "Routine"
    assert candidate.deterministic_rule_result == "Routine"
    assert candidate.nurse_review_required is True
    assert candidate.summary_text == "Fictional nonclinical application summary."


def test_valid_structured_extraction_output_maps_to_canonical_candidate() -> None:
    adapters = _adapters()
    case = _case(agent_used=False)

    candidates = {
        case.id: adapters.adapt_foundry_ai_service_output(case),
    }
    candidate = candidates[case.id]

    assert isinstance(candidate, EvaluationCandidate)
    assert set(candidates) == {"fictional-case-001"}
    assert candidate.contract_valid is True
    assert candidate.handoff_text is None
    _assert_common_candidate(candidate)
    assert EvaluationCandidate.model_validate(candidate) is candidate


def test_valid_agent_output_maps_to_canonical_candidate() -> None:
    adapters = _adapters()
    case = _case(agent_used=True)

    candidates = {
        case.id: adapters.adapt_nurse_intake_agent_output(case),
    }
    candidate = candidates[case.id]

    assert isinstance(candidate, EvaluationCandidate)
    assert set(candidates) == {"fictional-case-001"}
    assert candidate.contract_valid is True
    assert candidate.handoff_text is None
    _assert_common_candidate(candidate)
    assert EvaluationCandidate.model_validate(candidate) is candidate


def test_invalid_agent_routine_fallback_preserves_unknown_urgencies() -> None:
    adapters = _adapters()
    case = _case(
        agent_used=True,
        contract_valid=False,
        advisory_urgency="Unknown",
        rule_urgency="Routine",
    )

    candidate = adapters.adapt_nurse_intake_agent_output(case)

    assert candidate.contract_valid is False
    assert candidate.advisory_ai_urgency == "Unknown"
    assert candidate.final_application_urgency == "Unknown"
    assert candidate.deterministic_rule_result == "Routine"
    assert candidate.nurse_review_required is True
    assert candidate.missing_fields == ("agent_output",)
    assert EvaluationCandidate.model_validate(candidate) is candidate


def test_invalid_agent_urgent_fallback_preserves_rule_promotion() -> None:
    adapters = _adapters()
    case = _case(
        agent_used=True,
        contract_valid=False,
        advisory_urgency="Unknown",
        rule_urgency="Urgent",
    )

    candidate = adapters.adapt_nurse_intake_agent_output(case)

    assert candidate.contract_valid is False
    assert candidate.advisory_ai_urgency == "Unknown"
    assert candidate.final_application_urgency == "Urgent"
    assert candidate.deterministic_rule_result == "Urgent"
    assert candidate.nurse_review_required is True
    assert EvaluationCandidate.model_validate(candidate) is candidate


@pytest.mark.parametrize(
    "adapter_name,agent_used",
    [
        ("adapt_foundry_ai_service_output", False),
        ("adapt_nurse_intake_agent_output", True),
    ],
)
def test_valid_output_with_unknown_urgency_is_rejected(
    adapter_name: str,
    agent_used: bool,
) -> None:
    adapters = _adapters()
    case = _case(
        agent_used=agent_used,
        advisory_urgency="Unknown",
        final_urgency="Unknown",
    )

    with pytest.raises((ValueError, ValidationError)):
        getattr(adapters, adapter_name)(case)


@pytest.mark.parametrize("fabricated_urgency", ["Routine", "Urgent"])
def test_invalid_agent_fallback_with_binary_advisory_is_rejected(
    fabricated_urgency: str,
) -> None:
    adapters = _adapters()
    case = _case(
        agent_used=True,
        contract_valid=False,
        advisory_urgency=fabricated_urgency,
        final_urgency=("Urgent" if fabricated_urgency == "Urgent" else "Unknown"),
    )

    with pytest.raises((ValueError, ValidationError)):
        adapters.adapt_nurse_intake_agent_output(case)


def test_invalid_agent_fallback_without_pending_nurse_review_is_rejected() -> None:
    adapters = _adapters()
    case = _case(
        agent_used=True,
        contract_valid=False,
        advisory_urgency="Unknown",
        review_status="Reviewed",
    )

    with pytest.raises((ValueError, ValidationError)):
        adapters.adapt_nurse_intake_agent_output(case)


@pytest.mark.parametrize(
    "changes",
    [
        {"agent_output_valid": False, "agent_fallback_used": False},
        {"agent_output_valid": True, "agent_fallback_used": True},
        {"agent_output_valid": False, "agent_fallback_used": True,
         "agent_fallback_reason": None},
    ],
)
def test_contradictory_agent_contract_and_fallback_evidence_is_rejected(
    changes: dict[str, object],
) -> None:
    adapters = _adapters()
    case = _case(agent_used=True)
    case.processing_trace = case.processing_trace.model_copy(update=changes)

    with pytest.raises(ValueError):
        adapters.adapt_nurse_intake_agent_output(case)


def test_invalid_agent_fallback_with_conflicting_final_urgency_is_rejected() -> None:
    adapters = _adapters()
    case = _case(
        agent_used=True,
        contract_valid=False,
        advisory_urgency="Unknown",
        final_urgency="Routine",
        rule_urgency="Routine",
    )

    with pytest.raises((ValueError, ValidationError)):
        adapters.adapt_nurse_intake_agent_output(case)


def test_missing_required_application_evidence_is_rejected() -> None:
    adapters = _adapters()
    case = _case(agent_used=False)
    case.summary = None

    with pytest.raises((ValueError, ValidationError)):
        adapters.adapt_foundry_ai_service_output(case)


@pytest.mark.parametrize(
    "adapter_name",
    [
        "adapt_foundry_ai_service_output",
        "adapt_nurse_intake_agent_output",
    ],
)
def test_raw_provider_objects_are_rejected(adapter_name: str) -> None:
    adapters = _adapters()
    raw_provider_response = object()

    with pytest.raises(TypeError):
        getattr(adapters, adapter_name)(raw_provider_response)


def test_equivalent_provider_outputs_produce_equivalent_candidates() -> None:
    adapters = _adapters()

    structured_candidate = adapters.adapt_foundry_ai_service_output(
        _case(agent_used=False)
    )
    agent_candidate = adapters.adapt_nurse_intake_agent_output(
        _case(agent_used=True)
    )

    assert structured_candidate == agent_candidate
    assert structured_candidate.model_dump(mode="json") == (
        agent_candidate.model_dump(mode="json")
    )


@pytest.mark.parametrize(
    "adapter_name,agent_used",
    [
        ("adapt_foundry_ai_service_output", False),
        ("adapt_nurse_intake_agent_output", True),
    ],
)
def test_repeated_adaptation_is_deterministic(
    adapter_name: str,
    agent_used: bool,
) -> None:
    adapters = _adapters()
    case = _case(agent_used=agent_used)
    adapt = getattr(adapters, adapter_name)

    first = adapt(case)
    second = adapt(case)

    assert first == second
    assert first.model_dump_json() == second.model_dump_json()


def test_adapters_construct_no_provider_clients_and_make_no_side_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapters = _adapters()

    def fail(*args: object, **kwargs: object) -> None:
        raise AssertionError("Adapter attempted a provider or network side effect.")

    monkeypatch.setattr(socket, "socket", fail)
    monkeypatch.setattr(
        "src.app.services.foundry_ai_service.FoundryAiService.__init__",
        fail,
    )
    monkeypatch.setattr(
        "src.app.services.nurse_intake_agent.FoundryNurseIntakeAgent.__init__",
        fail,
    )

    structured = adapters.adapt_foundry_ai_service_output(
        _case(agent_used=False)
    )
    agent = adapters.adapt_nurse_intake_agent_output(_case(agent_used=True))

    assert structured.contract_valid is True
    assert agent.contract_valid is True
