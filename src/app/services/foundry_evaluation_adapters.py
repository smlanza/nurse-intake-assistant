"""Offline adapters from application case output to evaluation candidates."""

from src.app.models.case import CaseDocument, ProcessingTrace
from src.app.services.foundry_evaluation import (
    EvaluationCandidate,
    StructuredFields,
)


_AI_STEPS = [
    "ai.extract_summary",
    "ai.classify_urgency",
    "rules.apply_red_flags",
    "case.persist",
    "notifications.send",
]
_AGENT_STEPS = [
    "agent.extract_summary",
    "agent.classify_urgency",
    "rules.apply_red_flags",
    "case.persist",
    "notifications.send",
]


def adapt_foundry_ai_service_output(case: CaseDocument) -> EvaluationCandidate:
    """Adapt a completed FoundryAiService application case offline.

    The caller retains ``case.id`` as the key supplied to ``evaluate_dataset``.
    """

    _require_case_document(case)
    _require_common_processing_evidence(case)
    _require_structured_extraction_evidence(case.processing_trace)
    _require_merged_urgency_evidence(case, contract_valid=True)
    _require_intake_state(case, contract_valid=True)
    return _build_candidate(case, contract_valid=True)


def adapt_nurse_intake_agent_output(case: CaseDocument) -> EvaluationCandidate:
    """Adapt a completed NurseIntakeAgent application case offline.

    Agent response JSON and provider SDK objects are intentionally outside this
    boundary; the persisted case and processing trace are authoritative.
    """

    _require_case_document(case)
    _require_common_processing_evidence(case)
    contract_valid = _require_agent_evidence(case.processing_trace)
    _require_merged_urgency_evidence(case, contract_valid=contract_valid)
    _require_intake_state(case, contract_valid=contract_valid)
    if not contract_valid:
        _require_agent_fallback_values(case)
    return _build_candidate(case, contract_valid=contract_valid)


def _require_case_document(case: object) -> None:
    if not isinstance(case, CaseDocument):
        raise TypeError("Adapter input must be an application CaseDocument.")


def _require_common_processing_evidence(case: CaseDocument) -> None:
    if not case.id.strip():
        raise ValueError("Application output requires a case identifier.")
    if case.processingStatus != "Completed":
        raise ValueError("Application output must have completed processing.")
    if case.reviewStatus != "PendingReview":
        raise ValueError("Application output requires pending nurse review.")
    if case.ruleUrgency not in {"Routine", "Urgent"}:
        raise ValueError("Application output requires deterministic-rule evidence.")


def _require_structured_extraction_evidence(trace: ProcessingTrace) -> None:
    if trace.ai_provider != "foundry":
        raise ValueError("Application output is not from FoundryAiService.")
    if (
        trace.agent_used
        or trace.agent_attempted
        or trace.agent_output_valid is not None
        or trace.agent_fallback_used
        or trace.agent_fallback_reason is not None
        or trace.agent_provider is not None
        or trace.agent_mode is not None
    ):
        raise ValueError("Structured-extraction output has Agent evidence.")
    if trace.steps != _AI_STEPS:
        raise ValueError("Structured-extraction processing evidence is incomplete.")


def _require_agent_evidence(trace: ProcessingTrace) -> bool:
    if (
        not trace.agent_used
        or not trace.agent_attempted
        or trace.ai_provider is not None
        or not trace.agent_provider
        or not trace.agent_mode
        or trace.steps != _AGENT_STEPS
    ):
        raise ValueError("Agent processing evidence is incomplete.")

    if trace.agent_output_valid is True:
        if trace.agent_fallback_used or trace.agent_fallback_reason is not None:
            raise ValueError("Agent contract and fallback evidence contradict.")
        return True

    if trace.agent_output_valid is False:
        if not trace.agent_fallback_used or trace.agent_fallback_reason is None:
            raise ValueError("Agent contract and fallback evidence contradict.")
        return False

    raise ValueError("Agent output validity evidence is missing.")


def _require_merged_urgency_evidence(
    case: CaseDocument,
    *,
    contract_valid: bool,
) -> None:
    if contract_valid:
        if case.aiUrgency not in {"Routine", "Urgent"}:
            raise ValueError("Contract-valid advisory urgency must be known.")
    elif case.aiUrgency != "Unknown":
        raise ValueError("Contract-invalid advisory urgency must be unknown.")

    expected_final = _expected_final_urgency(
        advisory_urgency=case.aiUrgency,
        rule_urgency=case.ruleUrgency,
    )
    if case.urgency != expected_final:
        raise ValueError("Final urgency conflicts with application merge evidence.")

    rules_override = (
        case.ruleUrgency == "Urgent" and case.aiUrgency != "Urgent"
    )
    if case.processing_trace.rules_urgency_override is not rules_override:
        raise ValueError("Rule override evidence conflicts with urgency values.")

    if rules_override:
        expected_final_source = "rules"
    elif not contract_valid:
        expected_final_source = "unknown"
    elif case.processing_trace.agent_used:
        expected_final_source = "agent"
    else:
        expected_final_source = "ai"
    if case.processing_trace.final_urgency_source != expected_final_source:
        raise ValueError("Final urgency source evidence is inconsistent.")

    expected_urgency_source = _expected_urgency_source(
        advisory_urgency=case.aiUrgency,
        rule_urgency=case.ruleUrgency,
    )
    if case.urgencySource != expected_urgency_source:
        raise ValueError("Urgency source evidence is inconsistent.")


def _expected_final_urgency(
    *,
    advisory_urgency: str,
    rule_urgency: str,
) -> str:
    if rule_urgency == "Urgent" or advisory_urgency == "Urgent":
        return "Urgent"
    if advisory_urgency == "Routine":
        return "Routine"
    return "Unknown"


def _expected_urgency_source(
    *,
    advisory_urgency: str,
    rule_urgency: str,
) -> str:
    if rule_urgency == "Urgent" and advisory_urgency == "Urgent":
        return "RulesAndAI"
    if rule_urgency == "Urgent":
        return "Rules"
    if advisory_urgency == "Urgent":
        return "AI"
    return "Unknown"


def _require_intake_state(
    case: CaseDocument,
    *,
    contract_valid: bool,
) -> None:
    expected_complete = contract_valid and not case.missingFields
    if case.intakeComplete is not expected_complete:
        raise ValueError("Intake completion evidence is inconsistent.")
    expected_status = "Complete" if expected_complete else "NeedsFollowUp"
    if case.intakeStatus != expected_status:
        raise ValueError("Intake status evidence is inconsistent.")


def _require_agent_fallback_values(case: CaseDocument) -> None:
    if (
        case.patient.name is not None
        or case.patient.date_of_birth is not None
        or case.patient.callback_number is not None
        or case.reasonForCalling is not None
        or case.symptoms
        or "agent_output" not in case.missingFields
        or "agent_output" not in case.uncertainFields
        or not case.processing_trace.warnings
    ):
        raise ValueError("Agent fallback application evidence is inconsistent.")


def _build_candidate(
    case: CaseDocument,
    *,
    contract_valid: bool,
) -> EvaluationCandidate:
    return EvaluationCandidate(
        contract_valid=contract_valid,
        structured_fields=StructuredFields(
            patient_name=case.patient.name,
            date_of_birth=case.patient.date_of_birth,
            callback_identifier=case.patient.callback_number,
            reason_for_calling=case.reasonForCalling,
        ),
        symptoms=list(case.symptoms),
        missing_fields=list(case.missingFields),
        advisory_ai_urgency=case.aiUrgency,
        final_application_urgency=case.urgency,
        deterministic_rule_result=case.ruleUrgency,
        nurse_review_required=True,
        summary_text=case.summary,
        handoff_text=None,
    )
