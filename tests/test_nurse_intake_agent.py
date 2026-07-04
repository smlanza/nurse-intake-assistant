import asyncio

from src.app.services.nurse_intake_agent import MockNurseIntakeAgent


def test_mock_nurse_intake_agent_returns_deterministic_analysis() -> None:
    agent = MockNurseIntakeAgent()
    text = "My name is Demo Patient. DOB: 1980-04-15. I have chest pain."

    first_result = asyncio.run(agent.analyze_intake(text))
    second_result = asyncio.run(agent.analyze_intake(text))

    assert first_result == second_result
    assert first_result.extraction.patient.name == "Demo Patient"
    assert first_result.extraction.patient.date_of_birth == "1980-04-15"
    assert first_result.urgency.urgency == "Urgent"
    assert "chest pain" in first_result.extraction.symptoms
    assert "DEMO ONLY" in first_result.handoffNote
    assert "Urgency level: Urgent" in first_result.handoffNote


def test_mock_nurse_intake_agent_metadata_identifies_mock_mode() -> None:
    agent = MockNurseIntakeAgent()

    result = asyncio.run(agent.analyze_intake("I need a medication refill."))

    assert result.metadata.provider == "mock"
    assert result.metadata.agentMode == "mock"


def test_mock_nurse_intake_agent_output_contains_safe_analysis_fields() -> None:
    agent = MockNurseIntakeAgent()

    result = asyncio.run(agent.analyze_intake("I have a cough and fever."))

    assert result.extraction.summary == "Patient reports fever, cough."
    assert result.extraction.missing_fields == [
        "patient.name",
        "patient.date_of_birth",
        "patient.callback_number",
    ]
    assert result.urgency.urgency in {"Routine", "Urgent"}
    assert "nurse review" in result.urgency.advisory_disclaimer
    assert "Missing required fields" in result.handoffNote


def test_mock_nurse_intake_agent_does_not_expose_secrets_or_configuration() -> None:
    agent = MockNurseIntakeAgent()

    result = asyncio.run(agent.analyze_intake("I need a refill."))
    serialized = result.model_dump_json()

    for unsafe_text in [
        "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT",
        "AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT_NAME",
        "connectionString",
        "token",
        "secret",
        "password",
        "https://example.services.ai.azure.com",
        "intake-extraction",
        "provider credential",
    ]:
        assert unsafe_text not in serialized
