import json

import pytest

from src.app.services.foundry_extraction_contract import (
    FoundryExtractionContractError,
    FoundryExtractionParseError,
)
from src.app.services.foundry_agent_contract import (
    build_foundry_agent_intake_instructions,
    normalize_foundry_agent_intake_response,
)


def _valid_agent_payload() -> dict:
    return {
        "extraction": {
            "patient": {
                "name": "Foundry Demo Patient",
                "date_of_birth": None,
                "callback_number": "000-000-0101",
            },
            "reason_for_calling": "medication refill",
            "symptoms": ["fatigue"],
            "summary": "Demo patient requests a medication refill.",
            "missing_fields": ["patient.date_of_birth"],
            "uncertain_fields": [],
        },
        "urgency": {
            "urgency": "Routine",
            "urgency_rationale": "No urgent symptoms were reported.",
            "advisory_disclaimer": (
                "Advisory urgency only; nurse review and clinical judgment "
                "are required."
            ),
        },
    }


def _json_response(payload: dict | None = None) -> str:
    return json.dumps(payload or _valid_agent_payload())


def test_foundry_agent_instructions_include_required_contract_fields() -> None:
    instructions = build_foundry_agent_intake_instructions()

    for field_name in [
        "extraction",
        "patient",
        "reason_for_calling",
        "symptoms",
        "summary",
        "missing_fields",
        "uncertain_fields",
        "urgency",
        "urgency_rationale",
        "advisory_disclaimer",
    ]:
        assert field_name in instructions


def test_foundry_agent_response_normalizer_maps_valid_nested_json() -> None:
    result = normalize_foundry_agent_intake_response(_json_response())

    assert result.extraction.patient.name == "Foundry Demo Patient"
    assert result.extraction.patient.date_of_birth is None
    assert result.extraction.patient.callback_number == "000-000-0101"
    assert result.extraction.reason_for_calling == "medication refill"
    assert result.extraction.symptoms == ["fatigue"]
    assert result.extraction.summary == "Demo patient requests a medication refill."
    assert result.extraction.missing_fields == ["patient.date_of_birth"]
    assert result.extraction.uncertain_fields == []
    assert result.urgency.urgency == "Routine"
    assert result.urgency.urgency_rationale == "No urgent symptoms were reported."
    assert "nurse review" in result.urgency.advisory_disclaimer


@pytest.mark.parametrize(
    "fence",
    [
        "```json\n{body}\n```",
        "```\n{body}\n```",
    ],
)
def test_foundry_agent_response_normalizer_accepts_outer_markdown_json_fence(
    fence: str,
) -> None:
    response = fence.format(body=_json_response())

    result = normalize_foundry_agent_intake_response(response)

    assert result.extraction.patient.name == "Foundry Demo Patient"
    assert result.urgency.urgency == "Routine"


@pytest.mark.parametrize(
    "response",
    [
        "Here is the JSON:\n" + _json_response(),
        _json_response() + "\nThis is the result.",
        "{not-json",
        "   ",
        "```json\nnot-json\n```",
        _json_response() + _json_response(),
    ],
)
def test_foundry_agent_response_normalizer_rejects_malformed_json(
    response: str,
) -> None:
    with pytest.raises(FoundryExtractionContractError):
        normalize_foundry_agent_intake_response(response)


@pytest.mark.parametrize(
    "response",
    [
        "{not-json",
        "```json\nnot-json\n```",
        _json_response() + _json_response(),
    ],
)
def test_foundry_agent_response_normalizer_raises_parse_error_for_unparseable_json(
    response: str,
) -> None:
    with pytest.raises(FoundryExtractionParseError):
        normalize_foundry_agent_intake_response(response)


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda payload: payload.pop("extraction"), "missing required section"),
        (lambda payload: payload.pop("urgency"), "missing required section"),
        (lambda payload: payload["extraction"].pop("patient"), "missing required field"),
        (lambda payload: payload["extraction"].__setitem__("patient", []), "patient must be an object"),
        (lambda payload: payload["extraction"].__setitem__("symptoms", "fatigue"), "symptoms must be a list"),
        (
            lambda payload: payload["extraction"].__setitem__(
                "missing_fields",
                "patient.date_of_birth",
            ),
            "missing_fields must be a list",
        ),
        (
            lambda payload: payload["extraction"].__setitem__(
                "uncertain_fields",
                "patient.name",
            ),
            "uncertain_fields must be a list",
        ),
        (lambda payload: payload["urgency"].pop("urgency"), "missing required field"),
        (lambda payload: payload["urgency"].__setitem__("urgency", 7), "urgency must be Routine or Urgent"),
        (
            lambda payload: payload["urgency"].pop("urgency_rationale"),
            "missing required field",
        ),
        (
            lambda payload: payload["urgency"].__setitem__(
                "urgency_rationale",
                ["not text"],
            ),
            "urgency_rationale must be text",
        ),
    ],
)
def test_foundry_agent_response_normalizer_rejects_contract_violations(
    mutator,
    message: str,
) -> None:
    payload = _valid_agent_payload()
    mutator(payload)

    with pytest.raises(FoundryExtractionContractError, match=message):
        normalize_foundry_agent_intake_response(_json_response(payload))


def test_foundry_agent_response_normalizer_contract_violation_is_not_parse_error() -> None:
    payload = _valid_agent_payload()
    payload["urgency"]["urgency"] = "Emergency"

    with pytest.raises(FoundryExtractionContractError) as exc:
        normalize_foundry_agent_intake_response(_json_response(payload))

    assert not isinstance(exc.value, FoundryExtractionParseError)


def test_foundry_agent_response_normalizer_error_messages_are_sanitized() -> None:
    unsafe_response = (
        "Here is patient Jamie Secret with callback +1 555 555 0123, "
        "token=secret-bearer, https://secret-agent.services.ai.azure.com, "
        "agent-id-secret, and instructions: Return JSON only."
    )

    with pytest.raises(FoundryExtractionContractError) as exc:
        normalize_foundry_agent_intake_response(unsafe_response)

    error_text = str(exc.value)
    for unsafe_text in [
        "Jamie Secret",
        "+1 555 555 0123",
        "token=secret-bearer",
        "https://secret-agent.services.ai.azure.com",
        "agent-id-secret",
        "Return JSON only",
        unsafe_response,
    ]:
        assert unsafe_text not in error_text


def test_foundry_agent_instructions_require_json_only_output() -> None:
    instructions = build_foundry_agent_intake_instructions()

    assert "Return JSON only" in instructions
    assert "JSON object" in instructions


def test_foundry_agent_instructions_prohibit_markdown_and_explanatory_prose() -> None:
    instructions = build_foundry_agent_intake_instructions()

    assert "Do not use Markdown" in instructions
    assert "Do not wrap the response in code fences" in instructions
    assert "Do not include explanatory prose outside the JSON" in instructions


def test_foundry_agent_instructions_prohibit_inventing_missing_details() -> None:
    instructions = build_foundry_agent_intake_instructions()

    assert "Do not invent missing patient demographics" in instructions
    assert "Do not invent clinical details" in instructions
    assert "Use null" in instructions
    assert "missing_fields" in instructions
    assert "uncertain_fields" in instructions


def test_foundry_agent_instructions_include_advisory_nurse_review_boundary() -> None:
    instructions = build_foundry_agent_intake_instructions()

    assert "advisory only" in instructions
    assert "requires human nurse review" in instructions
