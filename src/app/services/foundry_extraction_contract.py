import json
from typing import Any

from pydantic import ValidationError

from src.app.models.ai_outputs import (
    ExtractionSummaryResult,
    PatientInfo,
    UrgencyClassificationResult,
)


FOUNDRY_ADVISORY_DISCLAIMER = (
    "Advisory urgency only; nurse review and clinical judgment are required."
)


class FoundryExtractionContractError(ValueError):
    """Raised when a Foundry structured extraction response violates contract."""


def build_foundry_structured_extraction_prompt(raw_text: str) -> str:
    """Build deterministic instructions for future Foundry structured extraction."""

    payload = json.dumps(raw_text, ensure_ascii=True)
    return f"""
You are helping prepare a nurse intake case from patient-supplied text.
Return JSON only. Do not wrap the JSON in Markdown or explanatory prose.

Safety constraints:
- Do not diagnose.
- Do not provide medical advice or treatment instructions.
- Urgency is advisory only.
- Nurse review is required before any clinical action.
- If required fields are missing, list them in missing_fields.
- If fields are uncertain, list them in uncertain_fields.

Required JSON object shape:
{{
  "patient": {{
    "name": string or null,
    "date_of_birth": string or null,
    "callback_number": string or null
  }},
  "reason_for_calling": string or null,
  "symptoms": [string],
  "summary": string,
  "urgency": "Routine" or "Urgent",
  "urgency_rationale": string,
  "advisory_disclaimer": string,
  "missing_fields": [string],
  "uncertain_fields": [string]
}}

Required fields for completeness are patient.name, patient.date_of_birth,
patient.callback_number, and reason_for_calling.

Patient intake text:
{payload}
""".strip()


def parse_foundry_structured_extraction_response(
    model_response: str,
) -> tuple[ExtractionSummaryResult, UrgencyClassificationResult]:
    """Parse and validate JSON returned by a future Foundry model call."""

    try:
        payload = json.loads(model_response)
    except json.JSONDecodeError as exc:
        raise FoundryExtractionContractError(
            "Foundry structured extraction response was not valid JSON."
        ) from exc

    if not isinstance(payload, dict):
        raise FoundryExtractionContractError(
            "Foundry structured extraction response must be a JSON object."
        )

    _require_top_level_fields(
        payload,
        required_fields=("patient", "summary", "urgency", "urgency_rationale"),
    )
    _validate_supported_urgency(payload["urgency"])

    patient_payload = payload["patient"]
    if not isinstance(patient_payload, dict):
        raise FoundryExtractionContractError(
            "Foundry structured extraction field patient must be an object."
        )

    symptoms = _optional_string_list(payload, "symptoms")
    missing_fields = _optional_string_list(payload, "missing_fields")
    uncertain_fields = _optional_string_list(payload, "uncertain_fields")
    advisory_disclaimer = payload.get(
        "advisory_disclaimer",
        FOUNDRY_ADVISORY_DISCLAIMER,
    )

    if not isinstance(advisory_disclaimer, str) or not advisory_disclaimer.strip():
        raise FoundryExtractionContractError(
            "Foundry structured extraction field advisory_disclaimer must be text."
        )

    try:
        extraction = ExtractionSummaryResult(
            patient=PatientInfo(**patient_payload),
            reason_for_calling=payload.get("reason_for_calling"),
            symptoms=symptoms,
            summary=payload["summary"],
            missing_fields=missing_fields,
            uncertain_fields=uncertain_fields,
            extraction_notes=(
                "Parsed from Azure AI Foundry structured extraction contract; "
                "live Foundry call is handled by the provider integration."
            ),
        )
        urgency = UrgencyClassificationResult(
            urgency=payload["urgency"],
            urgency_rationale=payload["urgency_rationale"],
            advisory_disclaimer=advisory_disclaimer,
        )
    except ValidationError as exc:
        raise FoundryExtractionContractError(
            "Foundry structured extraction response did not match app models."
        ) from exc

    return extraction, urgency


def _require_top_level_fields(
    payload: dict[str, Any],
    required_fields: tuple[str, ...],
) -> None:
    missing = [field for field in required_fields if field not in payload]
    if missing:
        joined = ", ".join(missing)
        raise FoundryExtractionContractError(
            f"Foundry structured extraction response missing required field(s): {joined}."
        )


def _validate_supported_urgency(value: Any) -> None:
    if value not in {"Routine", "Urgent"}:
        raise FoundryExtractionContractError(
            "Foundry structured extraction field urgency must be Routine or Urgent."
        )


def _optional_string_list(payload: dict[str, Any], field_name: str) -> list[str]:
    value = payload.get(field_name, [])
    if value is None:
        return []
    if not isinstance(value, list) or not all(
        isinstance(item, str) for item in value
    ):
        raise FoundryExtractionContractError(
            f"Foundry structured extraction field {field_name} must be a list of text."
        )
    return value
