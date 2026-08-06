from datetime import datetime, timedelta, timezone
import json

import pytest

from src.app.models.intake_telemetry import (
    INTAKE_TELEMETRY_OPERATION,
    IntakeTelemetryEvent,
)
from src.app.services.application_insights_telemetry_wire_diagnostic import (
    diagnose_telemetry_wire_row,
)
from src.app.services.azure_monitor_intake_telemetry import (
    intake_telemetry_wire_properties,
)


LOWER = datetime(2026, 8, 6, 12, 0, 0, tzinfo=timezone.utc)
UPPER = LOWER + timedelta(minutes=5)


def _event() -> IntakeTelemetryEvent:
    return IntakeTelemetryEvent(
        operation=INTAKE_TELEMETRY_OPERATION,
        case_type="text-intake",
        ai_provider="mock",
        agent_provider="none",
        agent_used=False,
        fallback_used=False,
        contract_valid=True,
        intake_complete=True,
        final_urgency="Routine",
        urgency_source="ai",
        rules_promoted_urgency=False,
        email_status="Suppressed",
        sms_status="Suppressed",
        processing_succeeded=True,
        safe_failure_category="none",
        duration_bucket="under_100_ms",
    )


def _wire() -> dict[str, object]:
    return dict(intake_telemetry_wire_properties(_event()))


def _diagnose(dimensions: object):
    return diagnose_telemetry_wire_row(
        [
            (LOWER + timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
            INTAKE_TELEMETRY_OPERATION,
            dimensions,
        ],
        lower=LOWER,
        upper=UPPER,
    )


def test_missing_allowlisted_field_reports_only_stable_safe_field() -> None:
    wire = _wire()
    del wire["case_type"]

    result = _diagnose(wire)

    assert result.category == "telemetry_record_invalid"
    assert result.mismatch_detected is True
    assert result.affected_field == "case_type"
    assert result.mismatch_reason == "required_field_missing"
    assert result.observed_wire_type is None


def test_unexpected_field_is_rejected_without_exposing_its_name() -> None:
    result = _diagnose({**_wire(), "UNSAFE_SECRET_KEY": "UNSAFE_SECRET_VALUE"})

    assert result.category == "telemetry_record_invalid"
    assert result.affected_field is None
    assert result.mismatch_reason == "unexpected_field_present"
    serialized = json.dumps(result.to_json_dict(), sort_keys=True)
    assert "UNSAFE_SECRET_KEY" not in serialized
    assert "UNSAFE_SECRET_VALUE" not in serialized


def test_exact_lowercase_string_boolean_token_is_compatible() -> None:
    wire = _wire()
    wire["agent_used"] = "true"

    result = _diagnose(wire)

    assert result.ok is True
    assert result.strictly_compatible is True
    assert result.mismatch_detected is False
    assert result.affected_field is None
    assert result.mismatch_reason is None
    assert result.observed_wire_type is None


def test_native_boolean_reports_type_without_value() -> None:
    wire = _wire()
    wire["agent_used"] = True

    result = _diagnose(wire)

    assert result.affected_field == "agent_used"
    assert result.mismatch_reason == "wire_type_invalid"
    assert result.observed_wire_type == "boolean"


def test_numeric_representation_reports_integer_wire_type() -> None:
    wire = _wire()
    wire["duration_bucket"] = 1

    result = _diagnose(wire)

    assert result.affected_field == "duration_bucket"
    assert result.mismatch_reason == "wire_type_invalid"
    assert result.observed_wire_type == "integer"
    assert "under_100_ms" not in json.dumps(result.to_json_dict())


def test_null_value_reports_only_null_wire_type() -> None:
    wire = _wire()
    wire["case_type"] = None

    result = _diagnose(wire)

    assert result.affected_field == "case_type"
    assert result.mismatch_reason == "wire_type_invalid"
    assert result.observed_wire_type == "null"


@pytest.mark.parametrize(
    ("field_name", "value", "wire_type"),
    [
        ("ai_provider", {"secret": "UNSAFE_SECRET_VALUE"}, "object"),
        ("agent_provider", ["UNSAFE_SECRET_VALUE"], "array"),
    ],
)
def test_object_and_array_values_are_rejected_without_serialization(
    field_name: str,
    value: object,
    wire_type: str,
) -> None:
    wire = _wire()
    wire[field_name] = value

    result = _diagnose(wire)

    assert result.affected_field == field_name
    assert result.mismatch_reason == "wire_type_invalid"
    assert result.observed_wire_type == wire_type
    assert "UNSAFE_SECRET_VALUE" not in json.dumps(result.to_json_dict())


def test_invalid_boolean_token_reports_reason_without_token() -> None:
    wire = _wire()
    wire["agent_used"] = "UNSAFE_SECRET_VALUE"

    result = _diagnose(wire)

    assert result.affected_field == "agent_used"
    assert result.mismatch_reason == "boolean_token_invalid"
    assert result.observed_wire_type == "string"
    assert "UNSAFE_SECRET_VALUE" not in json.dumps(result.to_json_dict())


def test_invalid_categorical_token_reports_reason_without_token() -> None:
    wire = _wire()
    wire["final_urgency"] = "UNSAFE_SECRET_VALUE"

    result = _diagnose(wire)

    assert result.affected_field == "final_urgency"
    assert result.mismatch_reason == "categorical_token_invalid"
    assert result.observed_wire_type == "string"
    assert "UNSAFE_SECRET_VALUE" not in json.dumps(result.to_json_dict())


def test_dynamic_json_string_reports_record_shape_without_payload() -> None:
    result = _diagnose(json.dumps(_wire()))

    assert result.affected_field is None
    assert result.mismatch_reason == "record_shape_invalid"
    assert result.observed_wire_type == "string"
    assert "case_type" not in json.dumps(result.to_json_dict())


def test_unknown_python_wire_type_remains_rejected() -> None:
    wire = _wire()
    wire["case_type"] = object()

    result = _diagnose(wire)

    assert result.affected_field == "case_type"
    assert result.mismatch_reason == "wire_type_invalid"
    assert result.observed_wire_type == "unknown"


def test_event_name_and_timestamp_fail_with_fixed_safe_reasons() -> None:
    timestamp = (LOWER + timedelta(seconds=1)).isoformat().replace("+00:00", "Z")

    wrong_name = diagnose_telemetry_wire_row(
        [timestamp, "UNSAFE_EVENT_NAME", _wire()],
        lower=LOWER,
        upper=UPPER,
    )
    wrong_timestamp = diagnose_telemetry_wire_row(
        ["UNSAFE_TIMESTAMP", INTAKE_TELEMETRY_OPERATION, _wire()],
        lower=LOWER,
        upper=UPPER,
    )

    assert wrong_name.affected_field is None
    assert wrong_name.mismatch_reason == "event_name_invalid"
    assert wrong_name.observed_wire_type == "string"
    assert wrong_timestamp.affected_field is None
    assert wrong_timestamp.mismatch_reason == "timestamp_invalid"
    assert wrong_timestamp.observed_wire_type == "string"
    serialized = json.dumps(
        [wrong_name.to_json_dict(), wrong_timestamp.to_json_dict()],
        sort_keys=True,
    )
    assert "UNSAFE_EVENT_NAME" not in serialized
    assert "UNSAFE_TIMESTAMP" not in serialized


def test_first_failure_uses_contract_order_not_azure_object_order() -> None:
    wire = dict(reversed(list(_wire().items())))
    wire["fallback_used"] = []
    wire["agent_used"] = "INVALID_BOOLEAN_TOKEN"

    result = _diagnose(wire)

    assert result.affected_field == "agent_used"
    assert result.mismatch_reason == "boolean_token_invalid"
    assert result.observed_wire_type == "string"


def test_successful_strict_row_has_no_diagnostic_mismatch() -> None:
    result = _diagnose(_wire())

    assert result.to_json_dict() == {
        "ok": True,
        "category": "success",
        "mismatch_detected": False,
        "strictly_compatible": True,
        "affected_field": None,
        "mismatch_reason": None,
        "observed_wire_type": None,
    }
