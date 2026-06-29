import asyncio
import json

import pytest

from src.app.models.ai_outputs import (
    ExtractionSummaryResult,
    UrgencyClassificationResult,
)
from src.app.services.foundry_ai_service import FoundryAiService


class FakeFoundryClient:
    def __init__(self) -> None:
        self.extraction_calls: list[dict[str, str]] = []
        self.urgency_calls: list[dict[str, str]] = []

    def extract_and_summarize(
        self,
        raw_text: str,
        model_deployment_name: str,
    ) -> dict:
        self.extraction_calls.append(
            {
                "raw_text": raw_text,
                "model_deployment_name": model_deployment_name,
            }
        )
        return {
            "patient": {
                "name": "Jane Doe",
                "date_of_birth": "1980-04-15",
                "callback_number": None,
            },
            "reason_for_calling": "medication refill",
            "symptoms": [],
            "summary": "Patient is calling about medication refill.",
            "missing_fields": ["patient.callback_number"],
            "uncertain_fields": [],
            "extraction_notes": "Fake Foundry extraction result for tests.",
        }

    def classify_urgency(
        self,
        raw_text: str,
        model_deployment_name: str,
    ) -> dict:
        self.urgency_calls.append(
            {
                "raw_text": raw_text,
                "model_deployment_name": model_deployment_name,
            }
        )
        return {
            "urgency": "Routine",
            "urgency_rationale": "Fake Foundry urgency result for tests.",
            "advisory_disclaimer": (
                "Advisory urgency only; nurse review and clinical judgment "
                "are required."
            ),
        }


class FailingFoundryClient:
    def extract_and_summarize(
        self,
        raw_text: str,
        model_deployment_name: str,
    ) -> dict:
        raise RuntimeError("fake client failure with private marker")

    def classify_urgency(
        self,
        raw_text: str,
        model_deployment_name: str,
    ) -> dict:
        raise RuntimeError("fake client failure with private marker")


def create_service(client: object | None = None) -> FoundryAiService:
    return FoundryAiService(
        project_endpoint="https://example.services.ai.azure.com/api/projects/demo",
        model_deployment_name="intake-extraction",
        client=client,
    )


def test_foundry_service_maps_fake_extraction_result() -> None:
    client = FakeFoundryClient()
    service = create_service(client)

    result = asyncio.run(
        service.extract_and_summarize(
            "My name is Jane Doe and I need a medication refill."
        )
    )

    assert isinstance(result, ExtractionSummaryResult)
    assert result.patient.name == "Jane Doe"
    assert result.patient.date_of_birth == "1980-04-15"
    assert result.patient.callback_number is None
    assert result.reason_for_calling == "medication refill"
    assert result.summary == "Patient is calling about medication refill."
    assert result.missing_fields == ["patient.callback_number"]
    assert client.extraction_calls == [
        {
            "raw_text": "My name is Jane Doe and I need a medication refill.",
            "model_deployment_name": "intake-extraction",
        }
    ]


def test_foundry_service_maps_fake_urgency_result() -> None:
    client = FakeFoundryClient()
    service = create_service(client)

    result = asyncio.run(service.classify_urgency("I need a medication refill."))

    assert isinstance(result, UrgencyClassificationResult)
    assert result.urgency == "Routine"
    assert result.urgency_rationale == "Fake Foundry urgency result for tests."
    assert "nurse review" in result.advisory_disclaimer
    assert client.urgency_calls == [
        {
            "raw_text": "I need a medication refill.",
            "model_deployment_name": "intake-extraction",
        }
    ]


def test_foundry_service_does_not_expose_configuration_in_returned_content() -> None:
    service = create_service(FakeFoundryClient())

    extraction = asyncio.run(service.extract_and_summarize("I need a refill."))
    urgency = asyncio.run(service.classify_urgency("I need a refill."))
    returned_content = (
        extraction.model_dump_json()
        + urgency.model_dump_json()
    )

    assert "https://example.services.ai.azure.com" not in returned_content
    assert "intake-extraction" not in returned_content
    assert "private marker" not in returned_content


def test_foundry_service_wraps_fake_client_exceptions() -> None:
    service = create_service(FailingFoundryClient())

    with pytest.raises(RuntimeError, match="Azure AI Foundry extraction failed") as exc:
        asyncio.run(service.extract_and_summarize("I need a refill."))

    assert "private marker" not in str(exc.value)


def test_foundry_service_without_client_does_not_create_live_client() -> None:
    service = create_service(client=None)

    with pytest.raises(RuntimeError, match="client creation is not implemented"):
        asyncio.run(service.extract_and_summarize("I need a refill."))


def test_foundry_service_exposes_offline_structured_contract_helpers() -> None:
    service = create_service(client=None)

    prompt = service.build_structured_extraction_prompt("I need a refill.")
    extraction, urgency = service.parse_structured_extraction_response(
        json.dumps(
            {
                "patient": {
                    "name": "Jane Doe",
                    "date_of_birth": "1980-04-15",
                    "callback_number": None,
                },
                "reason_for_calling": "medication refill",
                "summary": "Patient is calling about a medication refill.",
                "urgency": "Routine",
                "urgency_rationale": "No urgent symptoms were described.",
            }
        )
    )

    assert "Return JSON only" in prompt
    assert extraction.patient.name == "Jane Doe"
    assert extraction.symptoms == []
    assert urgency.urgency == "Routine"
    assert "nurse review" in urgency.advisory_disclaimer
