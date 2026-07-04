import json

import pytest

from src.app.models.ai_outputs import (
    ExtractionSummaryResult,
    UrgencyClassificationResult,
)
from src.app.services.foundry_extraction_contract import (
    FoundryExtractionContractError,
    build_foundry_structured_extraction_prompt,
    parse_foundry_structured_extraction_response,
)


def _valid_response_payload() -> dict:
    return {
        "patient": {
            "name": "Jane Doe",
            "date_of_birth": "1980-04-15",
            "callback_number": None,
        },
        "reason_for_calling": "medication refill",
        "symptoms": [],
        "summary": "Patient is calling about a medication refill.",
        "urgency": "Routine",
        "urgency_rationale": "No urgent symptoms were described.",
        "advisory_disclaimer": (
            "Advisory urgency only; nurse review and clinical judgment are required."
        ),
        "missing_fields": ["patient.callback_number"],
        "uncertain_fields": [],
    }


def test_foundry_prompt_includes_json_contract_fields() -> None:
    prompt = build_foundry_structured_extraction_prompt(
        "My name is Jane Doe. I need a medication refill."
    )

    assert "Return JSON only" in prompt
    assert '"patient"' in prompt
    assert '"name"' in prompt
    assert '"date_of_birth"' in prompt
    assert '"callback_number"' in prompt
    assert '"reason_for_calling"' in prompt
    assert '"symptoms"' in prompt
    assert '"summary"' in prompt
    assert '"urgency"' in prompt
    assert '"urgency_rationale"' in prompt
    assert '"missing_fields"' in prompt
    assert '"uncertain_fields"' in prompt


def test_foundry_prompt_includes_safety_guardrails() -> None:
    prompt = build_foundry_structured_extraction_prompt("I have chest pain.")

    assert "Do not diagnose" in prompt
    assert "Do not provide medical advice" in prompt
    assert "Urgency is advisory only" in prompt
    assert "Nurse review is required" in prompt


def test_parse_foundry_response_maps_valid_json_to_app_models() -> None:
    extraction, urgency = parse_foundry_structured_extraction_response(
        json.dumps(_valid_response_payload())
    )

    assert isinstance(extraction, ExtractionSummaryResult)
    assert isinstance(urgency, UrgencyClassificationResult)
    assert extraction.patient.name == "Jane Doe"
    assert extraction.patient.date_of_birth == "1980-04-15"
    assert extraction.patient.callback_number is None
    assert extraction.reason_for_calling == "medication refill"
    assert extraction.symptoms == []
    assert extraction.summary == "Patient is calling about a medication refill."
    assert extraction.missing_fields == ["patient.callback_number"]
    assert urgency.urgency == "Routine"
    assert urgency.urgency_rationale == "No urgent symptoms were described."
    assert "nurse review" in urgency.advisory_disclaimer


def test_parse_foundry_response_defaults_missing_list_fields() -> None:
    payload = _valid_response_payload()
    payload.pop("symptoms")
    payload.pop("missing_fields")
    payload.pop("uncertain_fields")

    extraction, _ = parse_foundry_structured_extraction_response(json.dumps(payload))

    assert extraction.symptoms == []
    assert extraction.missing_fields == []
    assert extraction.uncertain_fields == []


def test_parse_foundry_response_defaults_missing_advisory_disclaimer() -> None:
    payload = _valid_response_payload()
    payload.pop("advisory_disclaimer")

    _, urgency = parse_foundry_structured_extraction_response(json.dumps(payload))

    assert "Advisory urgency only" in urgency.advisory_disclaimer
    assert "nurse review" in urgency.advisory_disclaimer


def test_parse_foundry_response_rejects_malformed_json() -> None:
    with pytest.raises(FoundryExtractionContractError, match="not valid JSON"):
        parse_foundry_structured_extraction_response("{not-json")


def test_parse_foundry_response_rejects_empty_content() -> None:
    with pytest.raises(FoundryExtractionContractError, match="empty"):
        parse_foundry_structured_extraction_response("   ")


@pytest.mark.parametrize("model_response", ['["not", "object"]', '"not object"'])
def test_parse_foundry_response_rejects_non_object_json(
    model_response: str,
) -> None:
    with pytest.raises(FoundryExtractionContractError, match="must be a JSON object"):
        parse_foundry_structured_extraction_response(model_response)


def test_parse_foundry_response_rejects_invalid_urgency_value() -> None:
    payload = _valid_response_payload()
    payload["urgency"] = "Emergency"

    with pytest.raises(FoundryExtractionContractError, match="Routine or Urgent"):
        parse_foundry_structured_extraction_response(json.dumps(payload))


def test_parse_foundry_response_rejects_missing_required_top_level_field() -> None:
    payload = _valid_response_payload()
    payload.pop("summary")

    with pytest.raises(FoundryExtractionContractError, match="missing required"):
        parse_foundry_structured_extraction_response(json.dumps(payload))


def test_parse_foundry_response_rejects_invalid_list_field() -> None:
    payload = _valid_response_payload()
    payload["missing_fields"] = "patient.callback_number"

    with pytest.raises(FoundryExtractionContractError, match="list of text"):
        parse_foundry_structured_extraction_response(json.dumps(payload))


@pytest.mark.parametrize(
    ("field_name", "bad_value", "message"),
    [
        ("summary", ["not", "text"], "did not match app models"),
        ("urgency_rationale", {"not": "text"}, "did not match app models"),
        ("advisory_disclaimer", "", "advisory_disclaimer must be text"),
    ],
)
def test_parse_foundry_response_rejects_wrong_top_level_field_types(
    field_name: str,
    bad_value: object,
    message: str,
) -> None:
    payload = _valid_response_payload()
    payload[field_name] = bad_value

    with pytest.raises(FoundryExtractionContractError, match=message):
        parse_foundry_structured_extraction_response(json.dumps(payload))


def test_parse_foundry_response_rejects_wrong_patient_field_types() -> None:
    payload = _valid_response_payload()
    payload["patient"]["name"] = ["not", "text"]

    with pytest.raises(
        FoundryExtractionContractError,
        match="did not match app models",
    ):
        parse_foundry_structured_extraction_response(json.dumps(payload))


def test_parse_foundry_response_ignores_unexpected_fields() -> None:
    payload = _valid_response_payload()
    payload["unexpected_top_level"] = "must not leak"
    payload["patient"]["unexpected_patient_field"] = "must not leak"

    extraction, urgency = parse_foundry_structured_extraction_response(
        json.dumps(payload)
    )
    returned_content = extraction.model_dump_json() + urgency.model_dump_json()

    assert extraction.patient.name == "Jane Doe"
    assert urgency.urgency == "Routine"
    assert "unexpected_top_level" not in returned_content
    assert "unexpected_patient_field" not in returned_content
    assert "must not leak" not in returned_content
