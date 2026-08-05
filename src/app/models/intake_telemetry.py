from dataclasses import dataclass
from math import isfinite
from typing import Literal


INTAKE_TELEMETRY_OPERATION = "intake_processing_completed"

TelemetryCaseType = Literal[
    "text-intake",
    "phone-intake",
    "audio-upload",
    "unknown",
]
TelemetryProvider = Literal["none", "mock", "foundry", "foundry-agent", "unknown"]
TelemetryUrgency = Literal["Routine", "Urgent", "Unknown"]
TelemetryUrgencySource = Literal["agent", "ai", "rules", "unknown"]
TelemetryNotificationStatus = Literal[
    "NotAttempted",
    "MockRecorded",
    "Accepted",
    "Failed",
    "Suppressed",
    "Unknown",
]
SafeFailureCategory = Literal[
    "none",
    "unsupported_case_type",
    "invalid_agent_output",
    "agent_provider_failure",
    "ai_provider_failure",
    "persistence_failure",
    "notification_failure",
    "processing_failure",
]
DurationBucket = Literal[
    "under_100_ms",
    "100_to_499_ms",
    "500_to_1999_ms",
    "2000_ms_or_more",
    "unknown",
]

_CASE_TYPES = {"text-intake", "phone-intake", "audio-upload"}
_PROVIDERS = {"none", "mock", "foundry", "foundry-agent"}
_URGENCIES = {"Routine", "Urgent", "Unknown"}
_URGENCY_SOURCES = {"agent", "ai", "rules", "unknown"}
_NOTIFICATION_STATUSES = {
    "NotAttempted",
    "MockRecorded",
    "Accepted",
    "Failed",
    "Suppressed",
    "Unknown",
}
_FAILURE_CATEGORIES = {
    "none",
    "unsupported_case_type",
    "invalid_agent_output",
    "agent_provider_failure",
    "ai_provider_failure",
    "persistence_failure",
    "notification_failure",
    "processing_failure",
}
_DURATION_BUCKETS = {
    "under_100_ms",
    "100_to_499_ms",
    "500_to_1999_ms",
    "2000_ms_or_more",
    "unknown",
}


@dataclass(frozen=True, slots=True)
class IntakeTelemetryEvent:
    """Sanitized terminal intake-processing telemetry owned by the application."""

    operation: Literal["intake_processing_completed"]
    case_type: TelemetryCaseType
    ai_provider: TelemetryProvider
    agent_provider: TelemetryProvider
    agent_used: bool
    fallback_used: bool
    contract_valid: bool
    intake_complete: bool
    final_urgency: TelemetryUrgency
    urgency_source: TelemetryUrgencySource
    rules_promoted_urgency: bool
    email_status: TelemetryNotificationStatus
    sms_status: TelemetryNotificationStatus
    processing_succeeded: bool
    safe_failure_category: SafeFailureCategory
    duration_bucket: DurationBucket

    def __post_init__(self) -> None:
        if self.operation != INTAKE_TELEMETRY_OPERATION:
            raise ValueError("Unsupported intake telemetry operation")
        _require_allowed(self.case_type, _CASE_TYPES | {"unknown"}, "case_type")
        _require_allowed(self.ai_provider, _PROVIDERS | {"unknown"}, "ai_provider")
        _require_allowed(
            self.agent_provider,
            _PROVIDERS | {"unknown"},
            "agent_provider",
        )
        _require_allowed(self.final_urgency, _URGENCIES, "final_urgency")
        _require_allowed(
            self.urgency_source,
            _URGENCY_SOURCES,
            "urgency_source",
        )
        _require_allowed(
            self.email_status,
            _NOTIFICATION_STATUSES,
            "email_status",
        )
        _require_allowed(self.sms_status, _NOTIFICATION_STATUSES, "sms_status")
        _require_allowed(
            self.safe_failure_category,
            _FAILURE_CATEGORIES,
            "safe_failure_category",
        )
        _require_allowed(
            self.duration_bucket,
            _DURATION_BUCKETS,
            "duration_bucket",
        )
        for name in (
            "agent_used",
            "fallback_used",
            "contract_valid",
            "intake_complete",
            "rules_promoted_urgency",
            "processing_succeeded",
        ):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"Intake telemetry {name} must be Boolean")

    def to_properties(self) -> dict[str, str | bool]:
        """Serialize only the fixed, sanitized terminal property contract."""

        return {
            "operation": self.operation,
            "case_type": self.case_type,
            "ai_provider": self.ai_provider,
            "agent_provider": self.agent_provider,
            "agent_used": self.agent_used,
            "fallback_used": self.fallback_used,
            "contract_valid": self.contract_valid,
            "intake_complete": self.intake_complete,
            "final_urgency": self.final_urgency,
            "urgency_source": self.urgency_source,
            "rules_promoted_urgency": self.rules_promoted_urgency,
            "email_status": self.email_status,
            "sms_status": self.sms_status,
            "processing_succeeded": self.processing_succeeded,
            "safe_failure_category": self.safe_failure_category,
            "duration_bucket": self.duration_bucket,
        }


def build_intake_telemetry_event(
    *,
    case: object | None,
    requested_case_type: object,
    ai_provider: object,
    agent_provider: object,
    agent_used: object,
    contract_valid: object,
    fallback_used: object,
    processing_succeeded: object,
    safe_failure_category: object,
    started_monotonic: object,
    finished_monotonic: object,
) -> IntakeTelemetryEvent:
    """Map a terminal processing outcome into the structural safe allowlist."""

    trace = getattr(case, "processing_trace", None)
    return IntakeTelemetryEvent(
        operation=INTAKE_TELEMETRY_OPERATION,
        case_type=_allowed_or_unknown(requested_case_type, _CASE_TYPES),
        ai_provider=_provider(
            getattr(trace, "ai_provider", None) if case is not None else ai_provider
        ),
        agent_provider=_provider(
            getattr(trace, "agent_provider", None)
            if case is not None
            else agent_provider
        ),
        agent_used=_boolean(agent_used),
        fallback_used=_boolean(
            getattr(trace, "agent_fallback_used", fallback_used)
            if case is not None
            else fallback_used
        ),
        contract_valid=_boolean(
            _contract_valid(trace, contract_valid)
            if case is not None
            else contract_valid
        ),
        intake_complete=_boolean(getattr(case, "intakeComplete", False)),
        final_urgency=_allowed_or_unknown(
            getattr(case, "urgency", None),
            _URGENCIES - {"Unknown"},
            unknown="Unknown",
        ),
        urgency_source=_allowed_or_unknown(
            getattr(trace, "final_urgency_source", None),
            _URGENCY_SOURCES - {"unknown"},
        ),
        rules_promoted_urgency=_boolean(
            getattr(trace, "rules_urgency_override", False)
        ),
        email_status=_allowed_or_unknown(
            getattr(case, "notificationEmailStatus", None),
            _NOTIFICATION_STATUSES - {"Unknown"},
            unknown="Unknown",
        ),
        sms_status=_allowed_or_unknown(
            getattr(case, "notificationSmsStatus", None),
            _NOTIFICATION_STATUSES - {"Unknown"},
            unknown="Unknown",
        ),
        processing_succeeded=_boolean(processing_succeeded),
        safe_failure_category=_failure_category(safe_failure_category),
        duration_bucket=_duration_bucket(started_monotonic, finished_monotonic),
    )


def _contract_valid(trace: object, fallback: object) -> object:
    agent_output_valid = getattr(trace, "agent_output_valid", None)
    return fallback if agent_output_valid is None else agent_output_valid


def _provider(value: object) -> TelemetryProvider:
    if isinstance(value, str) and value in _PROVIDERS:
        return value
    if value is None:
        return "none"
    return "unknown"


def _failure_category(value: object) -> SafeFailureCategory:
    if isinstance(value, str) and value in _FAILURE_CATEGORIES:
        return value
    return "processing_failure"


def _allowed_or_unknown(
    value: object,
    allowed: set[str],
    *,
    unknown: str = "unknown",
):
    if isinstance(value, str) and value in allowed:
        return value
    return unknown


def _boolean(value: object) -> bool:
    return value is True


def _duration_bucket(start: object, finish: object) -> DurationBucket:
    if not _finite_number(start) or not _finite_number(finish):
        return "unknown"

    duration_seconds = float(finish) - float(start)
    if duration_seconds < 0:
        return "unknown"
    if duration_seconds < 0.1:
        return "under_100_ms"
    if duration_seconds < 0.5:
        return "100_to_499_ms"
    if duration_seconds < 2.0:
        return "500_to_1999_ms"
    return "2000_ms_or_more"


def _finite_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and isfinite(float(value))
    )


def _require_allowed(value: object, allowed: set[str], name: str) -> None:
    if not isinstance(value, str) or value not in allowed:
        raise ValueError(f"Unsupported intake telemetry {name}")
