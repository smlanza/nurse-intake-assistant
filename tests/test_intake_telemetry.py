import json
from types import SimpleNamespace

import pytest

from src.app.models.intake_telemetry import (
    INTAKE_TELEMETRY_OPERATION,
    IntakeTelemetryEvent,
    build_intake_telemetry_event,
)
from src.app.services.azure_monitor_intake_telemetry import (
    AzureMonitorIntakeTelemetrySink,
)
from src.app.services.intake_telemetry import CollectingIntakeTelemetrySink


def _event(**overrides: object) -> IntakeTelemetryEvent:
    values: dict[str, object] = {
        "operation": INTAKE_TELEMETRY_OPERATION,
        "case_type": "text-intake",
        "ai_provider": "mock",
        "agent_provider": "none",
        "agent_used": False,
        "fallback_used": False,
        "contract_valid": True,
        "intake_complete": True,
        "final_urgency": "Routine",
        "urgency_source": "ai",
        "rules_promoted_urgency": False,
        "email_status": "Suppressed",
        "sms_status": "Suppressed",
        "processing_succeeded": True,
        "safe_failure_category": "none",
        "duration_bucket": "under_100_ms",
    }
    values.update(overrides)
    return IntakeTelemetryEvent(**values)


def test_event_serialization_has_exact_sanitized_property_allowlist() -> None:
    event = _event()

    assert event.to_properties() == {
        "operation": "intake_processing_completed",
        "case_type": "text-intake",
        "ai_provider": "mock",
        "agent_provider": "none",
        "agent_used": False,
        "fallback_used": False,
        "contract_valid": True,
        "intake_complete": True,
        "final_urgency": "Routine",
        "urgency_source": "ai",
        "rules_promoted_urgency": False,
        "email_status": "Suppressed",
        "sms_status": "Suppressed",
        "processing_succeeded": True,
        "safe_failure_category": "none",
        "duration_bucket": "under_100_ms",
    }


def test_mapper_rejects_arbitrary_categories_and_sensitive_fields() -> None:
    sensitive_values = [
        "INTAKE_SECRET_SENTINEL",
        "TRANSCRIPT_SECRET_SENTINEL",
        "PATIENT_SECRET_SENTINEL",
        "CALLER_SECRET_SENTINEL",
        "PHONE_SECRET_SENTINEL",
        "EMAIL_SECRET_SENTINEL",
        "DOB_SECRET_SENTINEL",
        "ADDRESS_SECRET_SENTINEL",
        "SYMPTOM_SECRET_SENTINEL",
        "REASON_SECRET_SENTINEL",
        "MISSING_FIELD_SECRET_SENTINEL",
        "SUMMARY_SECRET_SENTINEL",
        "HANDOFF_SECRET_SENTINEL",
        "REVIEW_SECRET_SENTINEL",
        "CASE_ID_SECRET_SENTINEL",
        "IDEMPOTENCY_SECRET_SENTINEL",
        "CALL_ID_SECRET_SENTINEL",
        "RECORDING_ID_SECRET_SENTINEL",
        "AUDIO_BLOB_SECRET_SENTINEL",
        "PROMPT_SECRET_SENTINEL",
        "MODEL_RESPONSE_SECRET_SENTINEL",
        "AGENT_RESPONSE_SECRET_SENTINEL",
        "EXCEPTION_SECRET_SENTINEL",
        "ENDPOINT_SECRET_SENTINEL",
        "HOSTNAME_SECRET_SENTINEL",
        "RESOURCE_ID_SECRET_SENTINEL",
        "SUBSCRIPTION_ID_SECRET_SENTINEL",
        "TENANT_ID_SECRET_SENTINEL",
        "PRINCIPAL_ID_SECRET_SENTINEL",
        "CONNECTION_STRING_SECRET_SENTINEL",
        "CREDENTIAL_SECRET_SENTINEL",
        "TOKEN_SECRET_SENTINEL",
        "API_KEY_SECRET_SENTINEL",
        "STACK_TRACE_SECRET_SENTINEL",
        "FILESYSTEM_PATH_SECRET_SENTINEL",
        "COMMAND_SECRET_SENTINEL",
        "SDK_RESPONSE_SECRET_SENTINEL",
    ]
    sensitive = " ".join(sensitive_values)
    case = SimpleNamespace(
        id=sensitive,
        caseType=sensitive,
        patient=SimpleNamespace(
            name=sensitive,
            date_of_birth=sensitive,
            callback_number=sensitive,
            email=sensitive,
            address=sensitive,
        ),
        callerName=sensitive,
        transcript=sensitive,
        rawIntake=sensitive,
        reasonForCalling=sensitive,
        symptoms=[sensitive],
        summary=sensitive,
        missingFields=[sensitive],
        handoffNote=sensitive,
        reviewNotes=sensitive,
        idempotencyKey=sensitive,
        sourceCallId=sensitive,
        sourceRecordingId=sensitive,
        audioBlobName=sensitive,
        prompt=sensitive,
        modelResponse=sensitive,
        agentResponse=sensitive,
        exception=sensitive,
        endpoint=sensitive,
        hostname=sensitive,
        resourceId=sensitive,
        subscriptionId=sensitive,
        tenantId=sensitive,
        principalId=sensitive,
        connectionString=sensitive,
        credential=sensitive,
        token=sensitive,
        apiKey=sensitive,
        stackTrace=sensitive,
        filesystemPath=sensitive,
        command=sensitive,
        sdkResponse=sensitive,
        urgency=sensitive,
        intakeComplete=True,
        notificationEmailStatus=sensitive,
        notificationSmsStatus=sensitive,
        processing_trace=SimpleNamespace(
            ai_provider=sensitive,
            agent_provider=sensitive,
            agent_fallback_used=False,
            agent_output_valid=True,
            rules_urgency_override=False,
            final_urgency_source=sensitive,
        ),
    )

    event = build_intake_telemetry_event(
        case=case,
        requested_case_type=sensitive,
        ai_provider=sensitive,
        agent_provider=sensitive,
        agent_used=False,
        contract_valid=True,
        fallback_used=False,
        processing_succeeded=False,
        safe_failure_category=sensitive,
        started_monotonic=1.0,
        finished_monotonic=1.1,
    )
    serialized = json.dumps(event.to_properties(), sort_keys=True)

    assert event.case_type == "unknown"
    assert event.ai_provider == "unknown"
    assert event.agent_provider == "unknown"
    assert event.final_urgency == "Unknown"
    assert event.urgency_source == "unknown"
    assert event.email_status == "Unknown"
    assert event.sms_status == "Unknown"
    assert event.safe_failure_category == "processing_failure"
    assert all(value not in serialized for value in sensitive_values)


@pytest.mark.parametrize(
    ("start", "finish", "expected"),
    [
        (1.0, 1.099, "under_100_ms"),
        (1.0, 1.1, "100_to_499_ms"),
        (1.0, 1.499, "100_to_499_ms"),
        (1.0, 1.5, "500_to_1999_ms"),
        (1.0, 2.999, "500_to_1999_ms"),
        (1.0, 3.0, "2000_ms_or_more"),
        (None, 3.0, "unknown"),
        (3.0, 1.0, "unknown"),
    ],
)
def test_duration_is_coarse_and_deterministic(
    start: float | None,
    finish: float,
    expected: str,
) -> None:
    event = build_intake_telemetry_event(
        case=None,
        requested_case_type="text-intake",
        ai_provider="mock",
        agent_provider=None,
        agent_used=False,
        contract_valid=True,
        fallback_used=False,
        processing_succeeded=False,
        safe_failure_category="processing_failure",
        started_monotonic=start,
        finished_monotonic=finish,
    )

    assert event.duration_bucket == expected


def test_collecting_sink_records_events_in_memory() -> None:
    sink = CollectingIntakeTelemetrySink()
    event = _event()

    sink.record_intake_completed(event)

    assert sink.events == [event]


def test_azure_adapter_constructs_client_only_on_first_emission() -> None:
    calls: list[str] = []

    class FakeClient:
        def track_event(self, name: str, properties: dict[str, str]) -> None:
            calls.append(json.dumps({"name": name, "properties": properties}))

        def flush(self) -> None:
            calls.append("flush")

    def create_client(instrumentation_key: str) -> FakeClient:
        calls.append(f"create:{instrumentation_key}")
        return FakeClient()

    adapter = AzureMonitorIntakeTelemetrySink(
        connection_string="InstrumentationKey=fake-key",
        client_factory=create_client,
    )

    assert calls == []

    adapter.record_intake_completed(_event())

    assert calls[0] == "create:fake-key"
    payload = json.loads(calls[1])
    assert payload["name"] == INTAKE_TELEMETRY_OPERATION
    assert payload["properties"] == {
        name: str(value).lower() if isinstance(value, bool) else value
        for name, value in _event().to_properties().items()
    }
    assert calls[2] == "flush"


def test_azure_adapter_accepts_injected_send_function_without_client() -> None:
    sent: list[tuple[str, dict[str, str]]] = []
    adapter = AzureMonitorIntakeTelemetrySink(
        connection_string="EndpointSuffix=ENDPOINT_SECRET_SENTINEL",
        send_function=lambda name, properties: sent.append((name, properties)),
    )

    adapter.record_intake_completed(_event())

    assert sent == [
        (
            INTAKE_TELEMETRY_OPERATION,
            {
                name: str(value).lower() if isinstance(value, bool) else value
                for name, value in _event().to_properties().items()
            },
        )
    ]
    assert "ENDPOINT_SECRET_SENTINEL" not in json.dumps(sent)


def test_azure_adapter_missing_configuration_raises_only_safe_text() -> None:
    adapter = AzureMonitorIntakeTelemetrySink(connection_string=None)

    with pytest.raises(RuntimeError) as exc_info:
        adapter.record_intake_completed(_event())

    assert str(exc_info.value) == "Azure Monitor telemetry is not configured"
