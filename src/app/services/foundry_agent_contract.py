import json
import re
from dataclasses import replace
from typing import Any

from pydantic import ValidationError

from src.app.models.ai_outputs import (
    ExtractionSummaryResult,
    PatientInfo,
    UrgencyClassificationResult,
)
from src.app.services.foundry_extraction_contract import (
    FOUNDRY_ADVISORY_DISCLAIMER,
    FoundryExtractionContractError,
    FoundryExtractionNormalizationMetadata,
    FoundryExtractionParseError,
    FoundryStructuredExtractionResult,
)
from src.app.services.nurse_intake_agent_instructions import (
    NURSE_INTAKE_AGENT_INSTRUCTION_VERSION,
    build_nurse_intake_agent_instructions,
)


FOUNDRY_AGENT_INTAKE_CONTRACT_VERSION = NURSE_INTAKE_AGENT_INSTRUCTION_VERSION
FOUNDRY_AGENT_EXPECTED_TOP_LEVEL_SECTIONS = {"extraction", "urgency"}
FOUNDRY_AGENT_EXPECTED_EXTRACTION_FIELDS = {
    "patient",
    "reason_for_calling",
    "symptoms",
    "summary",
    "missing_fields",
    "uncertain_fields",
}
FOUNDRY_AGENT_EXPECTED_PATIENT_FIELDS = {
    "name",
    "date_of_birth",
    "callback_number",
}
FOUNDRY_AGENT_EXPECTED_URGENCY_FIELDS = {
    "urgency",
    "urgency_rationale",
    "advisory_disclaimer",
}
_OUTER_MARKDOWN_FENCE_PATTERN = re.compile(
    r"\A\s*```(?:json)?[ \t]*\n(?P<body>.*)\n```[ \t]*\s*\Z",
    re.IGNORECASE | re.DOTALL,
)


def build_foundry_agent_intake_instructions() -> str:
    """Build instructions for Foundry Agent structured nurse intake output."""

    return build_nurse_intake_agent_instructions()


def normalize_foundry_agent_intake_response(
    agent_response: str,
) -> FoundryStructuredExtractionResult:
    """Parse a Foundry Agent JSON response into app models with strict validation."""

    if not agent_response.strip():
        raise _agent_contract_error("Foundry Agent response was empty.")

    json_response = _strip_outer_markdown_fence(agent_response)

    try:
        payload = json.loads(json_response)
    except json.JSONDecodeError as exc:
        raise _agent_parse_error(
            "Foundry Agent response was not valid JSON."
        ) from exc

    if not isinstance(payload, dict):
        raise _agent_contract_error(
            "Foundry Agent response must be a JSON object."
        )

    metadata = FoundryExtractionNormalizationMetadata(
        provider="foundry-agent",
        normalized=True,
        ignored_extra_fields=_has_unexpected_top_level_sections(payload),
        validation_issue_count=0,
        contract_version=FOUNDRY_AGENT_INTAKE_CONTRACT_VERSION,
    )

    _require_section(payload, "extraction", metadata)
    _require_section(payload, "urgency", metadata)

    extraction_payload = payload["extraction"]
    urgency_payload = payload["urgency"]
    if not isinstance(extraction_payload, dict):
        raise _agent_contract_error(
            "Foundry Agent response section extraction must be an object.",
            metadata,
        )
    if not isinstance(urgency_payload, dict):
        raise _agent_contract_error(
            "Foundry Agent response section urgency must be an object.",
            metadata,
        )

    metadata = replace(
        metadata,
        ignored_extra_fields=metadata.ignored_extra_fields
        or _has_unexpected_extraction_fields(extraction_payload)
        or _has_unexpected_urgency_fields(urgency_payload),
    )

    _require_fields(
        extraction_payload,
        (
            "patient",
            "reason_for_calling",
            "symptoms",
            "summary",
            "missing_fields",
            "uncertain_fields",
        ),
        "extraction",
        metadata,
    )
    _require_fields(
        urgency_payload,
        ("urgency", "urgency_rationale", "advisory_disclaimer"),
        "urgency",
        metadata,
    )

    patient_payload = extraction_payload["patient"]
    if not isinstance(patient_payload, dict):
        raise _agent_contract_error(
            "Foundry Agent response field patient must be an object.",
            metadata,
        )
    metadata = replace(
        metadata,
        ignored_extra_fields=metadata.ignored_extra_fields
        or _has_unexpected_patient_fields(patient_payload),
    )
    _require_fields(
        patient_payload,
        ("name", "date_of_birth", "callback_number"),
        "patient",
        metadata,
    )
    _validate_optional_text_fields(
        patient_payload,
        ("name", "date_of_birth", "callback_number"),
        "patient",
        metadata,
    )

    symptoms = _required_string_list(extraction_payload, "symptoms", metadata)
    missing_fields = _required_string_list(
        extraction_payload,
        "missing_fields",
        metadata,
    )
    uncertain_fields = _required_string_list(
        extraction_payload,
        "uncertain_fields",
        metadata,
    )
    _validate_optional_text(
        extraction_payload["reason_for_calling"],
        "reason_for_calling",
        metadata,
    )
    _validate_required_text(extraction_payload["summary"], "summary", metadata)
    _validate_supported_urgency(urgency_payload["urgency"], metadata)
    _validate_required_text(
        urgency_payload["urgency_rationale"],
        "urgency_rationale",
        metadata,
    )
    _validate_required_text(
        urgency_payload["advisory_disclaimer"],
        "advisory_disclaimer",
        metadata,
    )

    try:
        extraction = ExtractionSummaryResult(
            patient=PatientInfo(**patient_payload),
            reason_for_calling=extraction_payload["reason_for_calling"],
            symptoms=symptoms,
            summary=extraction_payload["summary"],
            missing_fields=missing_fields,
            uncertain_fields=uncertain_fields,
            extraction_notes=(
                "Parsed from Azure AI Foundry Agent intake response contract; "
                "live agent invocation is handled by the provider integration."
            ),
        )
        urgency = UrgencyClassificationResult(
            urgency=urgency_payload["urgency"],
            urgency_rationale=urgency_payload["urgency_rationale"],
            advisory_disclaimer=urgency_payload.get(
                "advisory_disclaimer",
                FOUNDRY_ADVISORY_DISCLAIMER,
            ),
        )
    except ValidationError as exc:
        raise _agent_contract_error(
            "Foundry Agent response did not match app models.",
            metadata,
        ) from exc

    return FoundryStructuredExtractionResult(
        extraction=extraction,
        urgency=urgency,
        metadata=metadata,
    )


def _strip_outer_markdown_fence(agent_response: str) -> str:
    match = _OUTER_MARKDOWN_FENCE_PATTERN.fullmatch(agent_response)
    if match is None:
        return agent_response.strip()
    return match.group("body").strip()


def _require_section(
    payload: dict[str, Any],
    section_name: str,
    metadata: FoundryExtractionNormalizationMetadata,
) -> None:
    if section_name not in payload:
        raise _agent_contract_error(
            f"Foundry Agent response missing required section: {section_name}.",
            metadata,
        )


def _require_fields(
    payload: dict[str, Any],
    required_fields: tuple[str, ...],
    section_name: str,
    metadata: FoundryExtractionNormalizationMetadata,
) -> None:
    missing = [field for field in required_fields if field not in payload]
    if missing:
        joined = ", ".join(missing)
        raise _agent_contract_error(
            f"Foundry Agent response {section_name} missing required field(s): {joined}.",
            metadata,
        )


def _validate_optional_text_fields(
    payload: dict[str, Any],
    field_names: tuple[str, ...],
    section_name: str,
    metadata: FoundryExtractionNormalizationMetadata,
) -> None:
    for field_name in field_names:
        value = payload[field_name]
        if value is not None and not isinstance(value, str):
            raise _agent_contract_error(
                f"Foundry Agent response {section_name}.{field_name} must be text or null.",
                metadata,
            )


def _validate_optional_text(
    value: Any,
    field_name: str,
    metadata: FoundryExtractionNormalizationMetadata,
) -> None:
    if value is not None and not isinstance(value, str):
        raise _agent_contract_error(
            f"Foundry Agent response field {field_name} must be text or null.",
            metadata,
        )


def _validate_required_text(
    value: Any,
    field_name: str,
    metadata: FoundryExtractionNormalizationMetadata,
) -> None:
    if not isinstance(value, str) or not value.strip():
        raise _agent_contract_error(
            f"Foundry Agent response field {field_name} must be text.",
            metadata,
        )


def _validate_supported_urgency(
    value: Any,
    metadata: FoundryExtractionNormalizationMetadata,
) -> None:
    if value not in {"Routine", "Urgent"}:
        raise _agent_contract_error(
            "Foundry Agent response field urgency must be Routine or Urgent.",
            metadata,
        )


def _required_string_list(
    payload: dict[str, Any],
    field_name: str,
    metadata: FoundryExtractionNormalizationMetadata,
) -> list[str]:
    value = payload[field_name]
    if not isinstance(value, list) or not all(
        isinstance(item, str) for item in value
    ):
        raise _agent_contract_error(
            f"Foundry Agent response field {field_name} must be a list of text.",
            metadata,
        )
    return value


def _has_unexpected_top_level_sections(payload: dict[str, Any]) -> bool:
    return any(
        section not in FOUNDRY_AGENT_EXPECTED_TOP_LEVEL_SECTIONS
        for section in payload
    )


def _has_unexpected_extraction_fields(payload: dict[str, Any]) -> bool:
    return any(
        field not in FOUNDRY_AGENT_EXPECTED_EXTRACTION_FIELDS
        for field in payload
    )


def _has_unexpected_patient_fields(payload: dict[str, Any]) -> bool:
    return any(
        field not in FOUNDRY_AGENT_EXPECTED_PATIENT_FIELDS
        for field in payload
    )


def _has_unexpected_urgency_fields(payload: dict[str, Any]) -> bool:
    return any(
        field not in FOUNDRY_AGENT_EXPECTED_URGENCY_FIELDS
        for field in payload
    )


def _agent_contract_error(
    message: str,
    metadata: FoundryExtractionNormalizationMetadata | None = None,
) -> FoundryExtractionContractError:
    if metadata is None:
        error_metadata = FoundryExtractionNormalizationMetadata(
            provider="foundry-agent",
            normalized=False,
            validation_issue_count=1,
            contract_version=FOUNDRY_AGENT_INTAKE_CONTRACT_VERSION,
        )
    else:
        error_metadata = replace(
            metadata,
            normalized=False,
            validation_issue_count=max(1, metadata.validation_issue_count),
        )
    return FoundryExtractionContractError(message, error_metadata)


def _agent_parse_error(
    message: str,
    metadata: FoundryExtractionNormalizationMetadata | None = None,
) -> FoundryExtractionParseError:
    if metadata is None:
        error_metadata = FoundryExtractionNormalizationMetadata(
            provider="foundry-agent",
            normalized=False,
            validation_issue_count=1,
            contract_version=FOUNDRY_AGENT_INTAKE_CONTRACT_VERSION,
        )
    else:
        error_metadata = replace(
            metadata,
            normalized=False,
            validation_issue_count=max(1, metadata.validation_issue_count),
        )
    return FoundryExtractionParseError(message, error_metadata)
