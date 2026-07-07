from dataclasses import dataclass, field
from typing import Any


SUPPORTED_AGENT_URGENCY_VALUES = {"Routine", "Urgent", "Unknown"}


@dataclass(frozen=True)
class NurseIntakeAgentValidationResult:
    is_valid: bool
    warnings: list[str] = field(default_factory=list)


def validate_nurse_intake_agent_result(
    agent_result: object,
) -> NurseIntakeAgentValidationResult:
    """Validate the structured result returned by a NurseIntakeAgent."""

    warnings: list[str] = []
    extraction = _get_attr(agent_result, "extraction")
    urgency = _get_attr(agent_result, "urgency")
    handoff_note = _get_attr(agent_result, "handoffNote")

    if extraction is _MISSING:
        warnings.append("Agent output missing extraction.")
    else:
        summary = _get_attr(extraction, "summary")
        if summary is _MISSING:
            warnings.append("Agent output missing extraction.summary.")
        elif not _is_non_blank_text(summary):
            warnings.append("Agent output extraction.summary must be non-blank text.")

    if urgency is _MISSING:
        warnings.append("Agent output missing urgency.")
    else:
        urgency_value = _get_attr(urgency, "urgency")
        if urgency_value is _MISSING:
            warnings.append("Agent output missing urgency.urgency.")
        elif urgency_value not in SUPPORTED_AGENT_URGENCY_VALUES:
            warnings.append(
                "Agent output urgency.urgency must be Routine, Urgent, or Unknown."
            )

    if handoff_note is _MISSING:
        warnings.append("Agent output missing handoffNote.")
    elif not _is_non_blank_text(handoff_note):
        warnings.append("Agent output handoffNote must be non-blank text.")

    return NurseIntakeAgentValidationResult(
        is_valid=not warnings,
        warnings=warnings,
    )


_MISSING = object()


def _get_attr(value: object, name: str) -> Any:
    return getattr(value, name, _MISSING)


def _is_non_blank_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())
