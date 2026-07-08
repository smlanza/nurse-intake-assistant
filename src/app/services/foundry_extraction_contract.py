import json
from dataclasses import dataclass, replace
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
FOUNDRY_STRUCTURED_EXTRACTION_CONTRACT_VERSION = (
    "foundry-structured-extraction-v1"
)
FOUNDRY_EXPECTED_TOP_LEVEL_FIELDS = {
    "patient",
    "reason_for_calling",
    "symptoms",
    "summary",
    "urgency",
    "urgency_rationale",
    "advisory_disclaimer",
    "missing_fields",
    "uncertain_fields",
}
FOUNDRY_EXPECTED_PATIENT_FIELDS = {
    "name",
    "date_of_birth",
    "callback_number",
}


@dataclass(frozen=True)
class FoundryExtractionNormalizationMetadata:
    provider: str = "foundry"
    normalized: bool = False
    fallback_used: bool = False
    ignored_extra_fields: bool = False
    validation_issue_count: int = 0
    contract_version: str = FOUNDRY_STRUCTURED_EXTRACTION_CONTRACT_VERSION


@dataclass(frozen=True)
class FoundryStructuredExtractionResult:
    extraction: ExtractionSummaryResult
    urgency: UrgencyClassificationResult
    metadata: FoundryExtractionNormalizationMetadata


class FoundryExtractionContractError(ValueError):
    """Raised when a Foundry structured extraction response violates contract."""

    def __init__(
        self,
        message: str,
        normalization_metadata: FoundryExtractionNormalizationMetadata | None = None,
    ) -> None:
        super().__init__(message)
        self.normalization_metadata = (
            normalization_metadata
            or FoundryExtractionNormalizationMetadata(
                normalized=False,
                validation_issue_count=1,
            )
        )


class FoundryExtractionParseError(FoundryExtractionContractError):
    """Raised when a Foundry structured extraction response is not parseable."""


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

    result = normalize_foundry_structured_extraction_response(model_response)
    return result.extraction, result.urgency


def normalize_foundry_structured_extraction_response(
    model_response: str,
) -> FoundryStructuredExtractionResult:
    """Parse model JSON and return app models with safe normalization metadata."""

    if not model_response.strip():
        raise _contract_error("Foundry structured extraction response was empty.")

    try:
        payload = json.loads(model_response)
    except json.JSONDecodeError as exc:
        raise _parse_error(
            "Foundry structured extraction response was not valid JSON."
        ) from exc

    if not isinstance(payload, dict):
        raise _contract_error(
            "Foundry structured extraction response must be a JSON object."
        )

    metadata = FoundryExtractionNormalizationMetadata(
        normalized=True,
        ignored_extra_fields=_has_unexpected_fields(payload),
        validation_issue_count=0,
    )

    _require_top_level_fields(
        payload,
        required_fields=("patient", "summary", "urgency", "urgency_rationale"),
        metadata=metadata,
    )
    _validate_supported_urgency(payload["urgency"], metadata)

    patient_payload = payload["patient"]
    if not isinstance(patient_payload, dict):
        raise _contract_error(
            "Foundry structured extraction field patient must be an object.",
            metadata,
        )

    metadata = replace(
        metadata,
        ignored_extra_fields=metadata.ignored_extra_fields
        or _has_unexpected_patient_fields(patient_payload),
    )

    symptoms = _optional_string_list(payload, "symptoms", metadata)
    missing_fields = _optional_string_list(payload, "missing_fields", metadata)
    uncertain_fields = _optional_string_list(payload, "uncertain_fields", metadata)
    advisory_disclaimer = payload.get(
        "advisory_disclaimer",
        FOUNDRY_ADVISORY_DISCLAIMER,
    )

    if not isinstance(advisory_disclaimer, str) or not advisory_disclaimer.strip():
        raise _contract_error(
            "Foundry structured extraction field advisory_disclaimer must be text.",
            metadata,
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
        raise _contract_error(
            "Foundry structured extraction response did not match app models.",
            metadata,
        ) from exc

    return FoundryStructuredExtractionResult(
        extraction=extraction,
        urgency=urgency,
        metadata=metadata,
    )


def _require_top_level_fields(
    payload: dict[str, Any],
    required_fields: tuple[str, ...],
    metadata: FoundryExtractionNormalizationMetadata,
) -> None:
    missing = [field for field in required_fields if field not in payload]
    if missing:
        joined = ", ".join(missing)
        raise _contract_error(
            f"Foundry structured extraction response missing required field(s): {joined}.",
            metadata,
        )


def _validate_supported_urgency(
    value: Any,
    metadata: FoundryExtractionNormalizationMetadata,
) -> None:
    if value not in {"Routine", "Urgent"}:
        raise _contract_error(
            "Foundry structured extraction field urgency must be Routine or Urgent.",
            metadata,
        )


def _optional_string_list(
    payload: dict[str, Any],
    field_name: str,
    metadata: FoundryExtractionNormalizationMetadata,
) -> list[str]:
    value = payload.get(field_name, [])
    if value is None:
        return []
    if not isinstance(value, list) or not all(
        isinstance(item, str) for item in value
    ):
        raise _contract_error(
            f"Foundry structured extraction field {field_name} must be a list of text.",
            metadata,
        )
    return value


def _has_unexpected_fields(payload: dict[str, Any]) -> bool:
    return any(field not in FOUNDRY_EXPECTED_TOP_LEVEL_FIELDS for field in payload)


def _has_unexpected_patient_fields(patient_payload: dict[str, Any]) -> bool:
    return any(field not in FOUNDRY_EXPECTED_PATIENT_FIELDS for field in patient_payload)


def _contract_error(
    message: str,
    metadata: FoundryExtractionNormalizationMetadata | None = None,
) -> FoundryExtractionContractError:
    if metadata is None:
        error_metadata = FoundryExtractionNormalizationMetadata(
            normalized=False,
            validation_issue_count=1,
        )
    else:
        error_metadata = replace(
            metadata,
            normalized=False,
            validation_issue_count=max(1, metadata.validation_issue_count),
        )
    return FoundryExtractionContractError(message, error_metadata)


def _parse_error(
    message: str,
    metadata: FoundryExtractionNormalizationMetadata | None = None,
) -> FoundryExtractionParseError:
    if metadata is None:
        error_metadata = FoundryExtractionNormalizationMetadata(
            normalized=False,
            validation_issue_count=1,
        )
    else:
        error_metadata = replace(
            metadata,
            normalized=False,
            validation_issue_count=max(1, metadata.validation_issue_count),
        )
    return FoundryExtractionParseError(message, error_metadata)
