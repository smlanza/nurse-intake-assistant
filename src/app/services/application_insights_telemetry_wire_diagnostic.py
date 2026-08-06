from dataclasses import asdict, dataclass, fields
from datetime import datetime, timedelta
from typing import Literal

from src.app.models.intake_telemetry import (
    INTAKE_TELEMETRY_OPERATION,
    IntakeTelemetryEvent,
)


TelemetryMismatchReason = Literal[
    "required_field_missing",
    "unexpected_field_present",
    "wire_type_invalid",
    "boolean_token_invalid",
    "categorical_token_invalid",
    "event_name_invalid",
    "timestamp_invalid",
    "record_shape_invalid",
]
ObservedWireType = Literal[
    "string",
    "boolean",
    "integer",
    "floating_point",
    "null",
    "object",
    "array",
    "unknown",
]

TELEMETRY_FIELD_ORDER = tuple(field.name for field in fields(IntakeTelemetryEvent))
TELEMETRY_FIELD_ALLOWLIST = frozenset(TELEMETRY_FIELD_ORDER)
BOOLEAN_FIELDS = frozenset(
    field.name for field in fields(IntakeTelemetryEvent) if field.type is bool
)
MISMATCH_REASONS = frozenset(TelemetryMismatchReason.__args__)
OBSERVED_WIRE_TYPES = frozenset(ObservedWireType.__args__)


@dataclass(frozen=True)
class TelemetryWireShapeDiagnostic:
    ok: bool
    category: Literal["success", "telemetry_record_invalid"]
    mismatch_detected: bool
    strictly_compatible: bool
    affected_field: str | None = None
    mismatch_reason: TelemetryMismatchReason | None = None
    observed_wire_type: ObservedWireType | None = None

    def __post_init__(self) -> None:
        if self.affected_field is not None and (
            self.affected_field not in TELEMETRY_FIELD_ALLOWLIST
        ):
            raise ValueError("Diagnostic field is not allowlisted")
        if self.mismatch_reason is not None and (
            self.mismatch_reason not in MISMATCH_REASONS
        ):
            raise ValueError("Diagnostic reason is not allowlisted")
        if self.observed_wire_type is not None and (
            self.observed_wire_type not in OBSERVED_WIRE_TYPES
        ):
            raise ValueError("Diagnostic wire type is not allowlisted")
        if self.ok is not self.strictly_compatible:
            raise ValueError("Diagnostic success state is inconsistent")
        if self.mismatch_detected is self.strictly_compatible:
            raise ValueError("Diagnostic mismatch state is inconsistent")

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)


def diagnose_telemetry_wire_row(
    row: object,
    *,
    lower: datetime,
    upper: datetime,
) -> TelemetryWireShapeDiagnostic:
    """Classify one projected row without retaining or returning its values."""

    if not _utc_datetime(lower) or not _utc_datetime(upper) or lower >= upper:
        return _mismatch("timestamp_invalid")
    if not isinstance(row, list) or len(row) != 3:
        return _mismatch(
            "record_shape_invalid",
            observed_wire_type=_wire_type(row),
        )

    timestamp = _parse_utc(row[0])
    if timestamp is None or timestamp < lower or timestamp > upper:
        return _mismatch(
            "timestamp_invalid",
            observed_wire_type=_wire_type(row[0]),
        )
    if row[1] != INTAKE_TELEMETRY_OPERATION:
        return _mismatch(
            "event_name_invalid",
            observed_wire_type=_wire_type(row[1]),
        )

    dimensions = row[2]
    if not isinstance(dimensions, dict):
        return _mismatch(
            "record_shape_invalid",
            observed_wire_type=_wire_type(dimensions),
        )

    keys = set(dimensions)
    for field_name in TELEMETRY_FIELD_ORDER:
        if field_name not in keys:
            return _mismatch(
                "required_field_missing",
                affected_field=field_name,
            )
    if keys != TELEMETRY_FIELD_ALLOWLIST:
        return _mismatch("unexpected_field_present")

    decoded: dict[str, str | bool] = {}
    for field_name in TELEMETRY_FIELD_ORDER:
        value = dimensions[field_name]
        if not isinstance(value, str):
            return _mismatch(
                "wire_type_invalid",
                affected_field=field_name,
                observed_wire_type=_wire_type(value),
            )
        if field_name in BOOLEAN_FIELDS:
            if value not in {"true", "false"}:
                return _mismatch(
                    "boolean_token_invalid",
                    affected_field=field_name,
                    observed_wire_type="string",
                )
            decoded[field_name] = value == "true"
        else:
            decoded[field_name] = value

    try:
        IntakeTelemetryEvent(**decoded)
    except (TypeError, ValueError) as error:
        affected_field = _categorical_error_field(error)
        return _mismatch(
            "categorical_token_invalid" if affected_field is not None else "record_shape_invalid",
            affected_field=affected_field,
            observed_wire_type="string" if affected_field is not None else None,
        )

    return TelemetryWireShapeDiagnostic(
        ok=True,
        category="success",
        mismatch_detected=False,
        strictly_compatible=True,
    )


def _mismatch(
    reason: TelemetryMismatchReason,
    *,
    affected_field: str | None = None,
    observed_wire_type: ObservedWireType | None = None,
) -> TelemetryWireShapeDiagnostic:
    return TelemetryWireShapeDiagnostic(
        ok=False,
        category="telemetry_record_invalid",
        mismatch_detected=True,
        strictly_compatible=False,
        affected_field=affected_field,
        mismatch_reason=reason,
        observed_wire_type=observed_wire_type,
    )


def _categorical_error_field(error: Exception) -> str | None:
    message = str(error)
    for field_name in TELEMETRY_FIELD_ORDER:
        if message == f"Unsupported intake telemetry {field_name}":
            return field_name
    return None


def _wire_type(value: object) -> ObservedWireType:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, str):
        return "string"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "floating_point"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    return "unknown"


def _utc_datetime(value: object) -> bool:
    return bool(
        isinstance(value, datetime)
        and value.tzinfo is not None
        and value.utcoffset() == timedelta(0)
    )


def _parse_utc(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if _utc_datetime(parsed) else None
