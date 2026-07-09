import asyncio
import json
from types import SimpleNamespace

import pytest

from src.app.services.nurse_intake_agent import (
    FoundryNurseIntakeAgent,
    MockNurseIntakeAgent,
)


class RecordingFoundryAgentClient:
    def __init__(self) -> None:
        self.requests = []

    async def invoke_agent(self, request):
        self.requests.append(request)
        return SimpleNamespace(content=_foundry_agent_response())


def _foundry_agent_response() -> str:
    return json.dumps(
        {
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
    )


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


def test_foundry_nurse_intake_agent_sends_contract_instructions_to_client() -> None:
    client = RecordingFoundryAgentClient()
    agent = FoundryNurseIntakeAgent(
        settings=SimpleNamespace(agent_provider_normalized="foundry"),
        client=client,
    )
    raw_text = "Demo patient asks for a refill."

    result = asyncio.run(agent.analyze_intake(raw_text))

    assert result.extraction.patient.name == "Foundry Demo Patient"
    assert len(client.requests) == 1
    request = client.requests[0]
    assert request.intake_text == raw_text
    assert "Return JSON only" in request.instructions
    assert "patient" in request.instructions
    assert "urgency_rationale" in request.instructions
    assert "Do not invent missing patient demographics" in request.instructions
    assert "requires human nurse review" in request.instructions


def test_foundry_nurse_intake_agent_uses_centralized_instruction_builder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.app.services.nurse_intake_agent as agent_module

    client = RecordingFoundryAgentClient()
    monkeypatch.setattr(
        agent_module,
        "build_nurse_intake_agent_instructions",
        lambda: "centralized-test-instructions",
    )
    agent = FoundryNurseIntakeAgent(
        settings=SimpleNamespace(agent_provider_normalized="foundry-agent"),
        client=client,
    )

    asyncio.run(agent.analyze_intake("Demo patient asks for a refill."))

    assert client.requests[0].instructions == "centralized-test-instructions"
