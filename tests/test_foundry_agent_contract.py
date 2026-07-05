from src.app.services.foundry_agent_contract import (
    build_foundry_agent_intake_instructions,
)


def test_foundry_agent_instructions_include_required_contract_fields() -> None:
    instructions = build_foundry_agent_intake_instructions()

    for field_name in [
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
    assert "requires nurse review" in instructions
