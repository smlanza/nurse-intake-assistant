import asyncio
import json

import pytest

from src.app.models.ai_outputs import (
    ExtractionSummaryResult,
    UrgencyClassificationResult,
)
from src.app.services.foundry_ai_service import FoundryAiService
from src.app.services.foundry_extraction_contract import (
    FoundryExtractionContractError,
)


def _fake_model_response() -> str:
    return json.dumps(
        {
            "patient": {
                "name": "Jane Doe",
                "date_of_birth": "1980-04-15",
                "callback_number": None,
            },
            "reason_for_calling": "medication refill",
            "symptoms": ["fatigue"],
            "summary": "Patient is calling about medication refill and fatigue.",
            "urgency": "Routine",
            "urgency_rationale": "No urgent symptoms were described.",
            "advisory_disclaimer": (
                "Advisory urgency only; nurse review and clinical judgment "
                "are required."
            ),
            "missing_fields": ["patient.callback_number"],
            "uncertain_fields": ["symptoms"],
        }
    )


def _fake_model_payload() -> dict:
    return json.loads(_fake_model_response())


class FakeStructuredFoundryClient:
    def __init__(self, model_response: str | None = None) -> None:
        self.model_response = model_response or _fake_model_response()
        self.calls: list[dict[str, str]] = []

    def complete_structured_extraction(
        self,
        prompt: str,
        model_deployment_name: str,
    ) -> str:
        self.calls.append(
            {
                "prompt": prompt,
                "model_deployment_name": model_deployment_name,
            }
        )
        return self.model_response


class FailingStructuredFoundryClient:
    def complete_structured_extraction(
        self,
        prompt: str,
        model_deployment_name: str,
    ) -> str:
        raise RuntimeError("fake client failure with private marker")


def create_service(client: object | None = None) -> FoundryAiService:
    return FoundryAiService(
        project_endpoint="https://example.services.ai.azure.com/api/projects/demo",
        model_deployment_name="intake-extraction",
        client=client,
    )


def test_foundry_service_sends_contract_prompt_to_fake_client() -> None:
    client = FakeStructuredFoundryClient()
    service = create_service(client)

    asyncio.run(
        service.extract_and_summarize(
            "My name is Jane Doe and I need a medication refill."
        )
    )

    assert len(client.calls) == 1
    sent_prompt = client.calls[0]["prompt"]
    assert client.calls[0]["model_deployment_name"] == "intake-extraction"
    assert "Return JSON only" in sent_prompt
    assert '"patient"' in sent_prompt
    assert '"urgency"' in sent_prompt
    assert "Nurse review is required" in sent_prompt
    assert "Do not diagnose" in sent_prompt


def test_foundry_service_maps_fake_structured_extraction_result() -> None:
    client = FakeStructuredFoundryClient()
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
    assert result.symptoms == ["fatigue"]
    assert result.summary == "Patient is calling about medication refill and fatigue."
    assert result.missing_fields == ["patient.callback_number"]
    assert result.uncertain_fields == ["symptoms"]


def test_foundry_service_maps_cached_fake_urgency_result() -> None:
    client = FakeStructuredFoundryClient()
    service = create_service(client)
    raw_text = "My name is Jane Doe and I need a medication refill."

    asyncio.run(service.extract_and_summarize(raw_text))
    result = asyncio.run(service.classify_urgency(raw_text))

    assert isinstance(result, UrgencyClassificationResult)
    assert result.urgency == "Routine"
    assert result.urgency_rationale == "No urgent symptoms were described."
    assert "nurse review" in result.advisory_disclaimer
    assert len(client.calls) == 1


def test_foundry_service_classify_urgency_can_call_fake_client_first() -> None:
    client = FakeStructuredFoundryClient()
    service = create_service(client)

    result = asyncio.run(service.classify_urgency("I need a medication refill."))

    assert result.urgency == "Routine"
    assert len(client.calls) == 1
    assert "Return JSON only" in client.calls[0]["prompt"]


def test_foundry_service_does_not_expose_configuration_in_returned_content() -> None:
    service = create_service(FakeStructuredFoundryClient())

    extraction = asyncio.run(service.extract_and_summarize("I need a refill."))
    urgency = asyncio.run(service.classify_urgency("I need a refill."))
    returned_content = extraction.model_dump_json() + urgency.model_dump_json()

    assert "https://example.services.ai.azure.com" not in returned_content
    assert "intake-extraction" not in returned_content
    assert "private marker" not in returned_content


def test_foundry_service_wraps_fake_client_exceptions() -> None:
    service = create_service(FailingStructuredFoundryClient())

    with pytest.raises(
        RuntimeError,
        match="Azure AI Foundry structured extraction failed",
    ) as exc:
        asyncio.run(service.extract_and_summarize("I need a refill."))

    assert "private marker" not in str(exc.value)


def test_foundry_service_invalid_fake_response_fails_with_contract_error() -> None:
    service = create_service(FakeStructuredFoundryClient(model_response="{not-json"))

    with pytest.raises(FoundryExtractionContractError, match="not valid JSON"):
        asyncio.run(service.extract_and_summarize("I need a refill."))


@pytest.mark.parametrize(
    ("model_response", "message"),
    [
        ("not JSON at all", "not valid JSON"),
        ("   ", "empty"),
        ('["not", "object"]', "must be a JSON object"),
    ],
)
def test_foundry_service_rejects_malformed_model_content(
    model_response: str,
    message: str,
) -> None:
    service = create_service(FakeStructuredFoundryClient(model_response=model_response))

    with pytest.raises(FoundryExtractionContractError, match=message):
        asyncio.run(service.extract_and_summarize("I need a refill."))


def test_foundry_service_rejects_model_object_missing_expected_fields() -> None:
    payload = _fake_model_payload()
    payload.pop("summary")
    service = create_service(
        FakeStructuredFoundryClient(model_response=json.dumps(payload))
    )

    with pytest.raises(FoundryExtractionContractError, match="missing required"):
        asyncio.run(service.extract_and_summarize("I need a refill."))


def test_foundry_service_rejects_model_object_with_wrong_field_types() -> None:
    payload = _fake_model_payload()
    payload["symptoms"] = "fatigue"
    service = create_service(
        FakeStructuredFoundryClient(model_response=json.dumps(payload))
    )

    with pytest.raises(FoundryExtractionContractError, match="list of text"):
        asyncio.run(service.extract_and_summarize("I need a refill."))


def test_foundry_service_ignores_unexpected_model_fields() -> None:
    payload = _fake_model_payload()
    payload["unexpected_top_level"] = "must not leak"
    payload["patient"]["unexpected_patient_field"] = "must not leak"
    service = create_service(
        FakeStructuredFoundryClient(model_response=json.dumps(payload))
    )

    extraction = asyncio.run(service.extract_and_summarize("I need a refill."))
    urgency = asyncio.run(service.classify_urgency("I need a refill."))
    returned_content = extraction.model_dump_json() + urgency.model_dump_json()

    assert extraction.patient.name == "Jane Doe"
    assert urgency.urgency == "Routine"
    assert "unexpected_top_level" not in returned_content
    assert "unexpected_patient_field" not in returned_content
    assert "must not leak" not in returned_content


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
