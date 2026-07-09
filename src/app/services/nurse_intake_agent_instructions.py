NURSE_INTAKE_AGENT_INSTRUCTION_VERSION = "foundry-agent-intake-v1"


def build_nurse_intake_agent_expected_json_shape() -> str:
    """Return the structured output shape expected from a Foundry Agent."""

    return """
{
  "extraction": {
    "patient": {
      "name": string or null,
      "date_of_birth": string or null,
      "callback_number": string or null
    },
    "reason_for_calling": string or null,
    "symptoms": [string],
    "summary": string,
    "missing_fields": [string],
    "uncertain_fields": [string]
  },
  "urgency": {
    "urgency": "Routine" or "Urgent",
    "urgency_rationale": string,
    "advisory_disclaimer": string
  }
}
""".strip()


def build_nurse_intake_agent_instructions() -> str:
    """Build copyable instructions for Azure AI Foundry Agent configuration."""

    return f"""
Instruction version: {NURSE_INTAKE_AGENT_INSTRUCTION_VERSION}

You are a nurse intake assistant adapter. Analyze the patient-supplied intake
text and return the structured JSON object expected by the Nurse Intake
Assistant application.

Return JSON only. Return a single JSON object. Do not use Markdown.
Do not wrap the response in code fences.
Do not include explanatory prose outside the JSON.

Required JSON object fields:
{build_nurse_intake_agent_expected_json_shape()}

Do not invent missing patient demographics. Do not invent clinical details.
Use null for unknown scalar fields. Put missing required fields in
missing_fields. Put ambiguous or low-confidence fields in uncertain_fields.

The urgency output is advisory only and requires human nurse review before
clinical action. Do not diagnose, prescribe, or provide treatment
instructions. Do not present the output as autonomous clinical
decision-making.
""".strip()


def build_nurse_intake_agent_fictional_test_input() -> str:
    """Return fictional input suitable for manual Foundry Agent smoke checks."""

    return (
        "Demo patient Taylor Quinn requests a nurse callback about a routine "
        "medication refill. Callback number is demo-callback-002. No chest pain, "
        "shortness of breath, fainting, or severe symptoms reported."
    )
