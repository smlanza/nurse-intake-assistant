from types import SimpleNamespace

from src.app.models.ai_outputs import ExtractionSummaryResult, PatientInfo
from src.app.services.nurse_intake_agent_contract import (
    validate_nurse_intake_agent_result,
)


def _valid_agent_result() -> SimpleNamespace:
    return SimpleNamespace(
        extraction=ExtractionSummaryResult(
            patient=PatientInfo(
                name="Demo Patient",
                date_of_birth="1988-08-08",
                callback_number="000-000-0200",
            ),
            reason_for_calling="medication refill",
            symptoms=["fatigue"],
            summary="Patient requests a medication refill.",
            missing_fields=[],
            uncertain_fields=[],
        ),
        urgency=SimpleNamespace(
            urgency="Routine",
            urgency_rationale="No urgent symptoms were reported.",
            advisory_disclaimer="Advisory only; nurse review required.",
        ),
        handoffNote="Demo handoff note.",
    )


def test_valid_agent_result_passes_contract_validation() -> None:
    result = validate_nurse_intake_agent_result(_valid_agent_result())

    assert result.is_valid is True
    assert result.warnings == []


def test_missing_extraction_fails_contract_validation() -> None:
    agent_result = _valid_agent_result()
    delattr(agent_result, "extraction")

    result = validate_nurse_intake_agent_result(agent_result)

    assert result.is_valid is False
    assert "Agent output missing extraction." in result.warnings


def test_invalid_urgency_value_fails_contract_validation() -> None:
    agent_result = _valid_agent_result()
    agent_result.urgency.urgency = "Emergency"

    result = validate_nurse_intake_agent_result(agent_result)

    assert result.is_valid is False
    assert (
        "Agent output urgency.urgency must be Routine, Urgent, or Unknown."
        in result.warnings
    )
