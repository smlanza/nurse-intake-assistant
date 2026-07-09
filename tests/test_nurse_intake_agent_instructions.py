from src.app.services.nurse_intake_agent_instructions import (
    NURSE_INTAKE_AGENT_INSTRUCTION_VERSION,
    build_nurse_intake_agent_expected_json_shape,
    build_nurse_intake_agent_fictional_test_input,
    build_nurse_intake_agent_instructions,
)


def test_instruction_pack_contains_required_nurse_intake_contract_fields() -> None:
    instructions = build_nurse_intake_agent_instructions()
    expected_shape = build_nurse_intake_agent_expected_json_shape()
    combined = instructions + "\n" + expected_shape

    assert NURSE_INTAKE_AGENT_INSTRUCTION_VERSION in instructions
    for field_name in [
        "extraction",
        "patient",
        "name",
        "date_of_birth",
        "callback_number",
        "reason_for_calling",
        "symptoms",
        "summary",
        "missing_fields",
        "uncertain_fields",
        "urgency",
        "urgency_rationale",
        "advisory_disclaimer",
    ]:
        assert field_name in combined


def test_instruction_pack_requires_json_only_output() -> None:
    instructions = build_nurse_intake_agent_instructions()

    assert "Return JSON only" in instructions
    assert "single JSON object" in instructions
    assert "Do not use Markdown" in instructions
    assert "Do not include explanatory prose outside the JSON" in instructions


def test_instruction_pack_preserves_human_review_boundary() -> None:
    instructions = build_nurse_intake_agent_instructions()
    normalized_instructions = " ".join(instructions.split())

    assert "requires human nurse review" in instructions
    assert "Do not diagnose" in instructions
    assert "Do not present the output as autonomous clinical decision-making" in (
        normalized_instructions
    )


def test_instruction_pack_uses_fictional_example_only() -> None:
    fictional_input = build_nurse_intake_agent_fictional_test_input()
    combined = build_nurse_intake_agent_instructions() + "\n" + fictional_input

    assert "Demo patient" in fictional_input
    assert "demo-callback-002" in fictional_input
    for unsafe_text in [
        "https://",
        "secret-agent-id",
        "bearer",
        "token",
        "+1 555",
        "@example.com",
        "Jane Doe",
    ]:
        assert unsafe_text not in combined
