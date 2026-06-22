import asyncio

import pytest

from src.app.models.ai_outputs import (
    ExtractionSummaryResult,
    UrgencyClassificationResult,
)
from src.app.services.mock_ai_service import MockAiService


def test_extracts_complete_routine_intake() -> None:
    service = MockAiService()
    text = (
        "My name is Jane Doe. DOB: 1980-04-15. "
        "My callback number is +1 (555) 555-0123. I need a medication refill."
    )

    extraction = asyncio.run(service.extract_and_summarize(text))
    urgency = asyncio.run(service.classify_urgency(text))

    assert isinstance(extraction, ExtractionSummaryResult)
    assert extraction.patient.name == "Jane Doe"
    assert extraction.patient.date_of_birth == "1980-04-15"
    assert extraction.patient.callback_number == "+1 (555) 555-0123"
    assert extraction.reason_for_calling == "medication refill"
    assert extraction.symptoms == []
    assert extraction.summary == "Patient is calling about medication refill."
    assert extraction.missing_fields == []
    assert extraction.uncertain_fields == []
    assert extraction.extraction_notes is not None

    assert isinstance(urgency, UrgencyClassificationResult)
    assert urgency.urgency == "Routine"
    assert urgency.urgency_rationale
    assert urgency.advisory_disclaimer


@pytest.mark.parametrize("symptom", ["CHEST PAIN", "shortness of breath"])
def test_classifies_urgent_keyword_text(symptom: str) -> None:
    service = MockAiService()

    result = asyncio.run(service.classify_urgency(f"I am having {symptom}."))

    assert result.urgency == "Urgent"
    assert "keyword matched" in result.urgency_rationale
    assert result.advisory_disclaimer


def test_reports_missing_patient_fields() -> None:
    service = MockAiService()

    result = asyncio.run(service.extract_and_summarize("I have a cough and fever."))

    assert result.patient.name is None
    assert result.patient.date_of_birth is None
    assert result.patient.callback_number is None
    assert result.missing_fields == ["name", "date_of_birth", "callback_number"]
    assert result.reason_for_calling == "fever"
    assert result.symptoms == ["fever", "cough"]
    assert result.summary == "Patient reports fever, cough."
    assert result.uncertain_fields == []
    assert result.extraction_notes is not None
