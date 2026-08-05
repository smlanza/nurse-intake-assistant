import asyncio
import json
from types import SimpleNamespace

import pytest

from src.app.models.ai_outputs import (
    ExtractionSummaryResult,
    PatientInfo,
    UrgencyClassificationResult,
)
from src.app.services.case_processing_service import CaseProcessingService
from src.app.services.intake_telemetry import CollectingIntakeTelemetrySink
from src.app.services.mock_ai_service import MockAiService


ROUTINE_TEXT = (
    "My name is Jane Doe. DOB: 1980-04-15. "
    "My callback number is +1 (555) 555-0123. I need a medication refill."
)


class SequenceClock:
    def __init__(self, *values: float) -> None:
        self._values = iter(values)

    def __call__(self) -> float:
        return next(self._values)


class Agent:
    provider = "mock"
    agentMode = "mock"

    def __init__(self, result: object | None = None, error: Exception | None = None):
        self.result = result or _valid_agent_result()
        self.error = error

    async def analyze_intake(self, raw_text: str) -> object:
        if self.error is not None:
            raise self.error
        return self.result


class ExplodingAiService:
    provider = "foundry"

    def __init__(self, error: Exception) -> None:
        self.error = error

    async def extract_and_summarize(self, raw_text: str) -> ExtractionSummaryResult:
        raise self.error

    async def classify_urgency(self, raw_text: str) -> UrgencyClassificationResult:
        raise AssertionError("classification should not be reached")


class FoundryLikeAiService(MockAiService):
    provider = "foundry"


class ExplodingRepository:
    def __init__(self, error: Exception) -> None:
        self.error = error

    async def save(self, case: object) -> None:
        raise self.error


class ExplodingTelemetrySink:
    def __init__(self, error: Exception) -> None:
        self.error = error
        self.calls = 0

    def record_intake_completed(self, event: object) -> None:
        self.calls += 1
        raise self.error


class FailingEmailSender:
    def send_case_notification(
        self,
        recipient: str,
        subject: str,
        body: str,
        case_id: str,
    ) -> bool:
        raise RuntimeError("EMAIL_EXCEPTION_SECRET_SENTINEL")


def _valid_agent_result(
    *, urgency: str = "Routine", summary: str = "Safe agent summary."
) -> SimpleNamespace:
    return SimpleNamespace(
        extraction=ExtractionSummaryResult(
            patient=PatientInfo(
                name="Agent Patient",
                date_of_birth="1988-08-08",
                callback_number="000-000-0200",
            ),
            reason_for_calling="medication refill",
            symptoms=[],
            summary=summary,
            missing_fields=[],
            uncertain_fields=[],
        ),
        urgency=SimpleNamespace(
            urgency=urgency,
            urgency_rationale="Agent classified the intake.",
            advisory_disclaimer="Nurse review required.",
        ),
        handoffNote="Nurse handoff.",
        metadata=SimpleNamespace(provider="mock", agentMode="mock"),
    )


def _service(
    sink: object,
    **overrides: object,
) -> CaseProcessingService:
    return CaseProcessingService(
        telemetry_sink=sink,
        monotonic_clock=SequenceClock(5.0, 5.6),
        suppress_notifications=True,
        **overrides,
    )


def test_successful_mock_intake_emits_exactly_one_terminal_event() -> None:
    sink = CollectingIntakeTelemetrySink()

    case = asyncio.run(_service(sink).process(ROUTINE_TEXT, "text-intake"))

    assert len(sink.events) == 1
    event = sink.events[0]
    assert event.processing_succeeded is True
    assert event.case_type == "text-intake"
    assert event.ai_provider == "mock"
    assert event.agent_provider == "none"
    assert event.agent_used is False
    assert event.fallback_used is False
    assert event.contract_valid is True
    assert event.intake_complete is case.intakeComplete
    assert event.final_urgency == "Routine"
    assert event.urgency_source == "ai"
    assert event.rules_promoted_urgency is False
    assert event.email_status == "Suppressed"
    assert event.sms_status == "Suppressed"
    assert event.safe_failure_category == "none"
    assert event.duration_bucket == "500_to_1999_ms"


def test_valid_agent_processing_emits_exactly_one_event() -> None:
    sink = CollectingIntakeTelemetrySink()

    asyncio.run(
        _service(
            sink,
            nurse_intake_agent=Agent(),
        ).process(ROUTINE_TEXT, "text-intake")
    )

    assert len(sink.events) == 1
    event = sink.events[0]
    assert event.agent_used is True
    assert event.agent_provider == "mock"
    assert event.contract_valid is True
    assert event.fallback_used is False
    assert event.urgency_source == "agent"


def test_valid_foundry_provider_processing_emits_exactly_one_event() -> None:
    sink = CollectingIntakeTelemetrySink()

    asyncio.run(
        _service(sink, ai_service=FoundryLikeAiService()).process(
            ROUTINE_TEXT,
            "text-intake",
        )
    )

    assert len(sink.events) == 1
    assert sink.events[0].ai_provider == "foundry"
    assert sink.events[0].processing_succeeded is True


def test_invalid_agent_output_emits_one_safe_fallback_event() -> None:
    sink = CollectingIntakeTelemetrySink()
    invalid_result = SimpleNamespace(
        urgency=SimpleNamespace(urgency="Routine"),
        handoffNote="PROMPT_SECRET_SENTINEL",
        metadata=SimpleNamespace(provider="ENDPOINT_SECRET_SENTINEL"),
    )

    asyncio.run(
        _service(
            sink,
            nurse_intake_agent=Agent(result=invalid_result),
        ).process(ROUTINE_TEXT, "text-intake")
    )

    assert len(sink.events) == 1
    event = sink.events[0]
    assert event.fallback_used is True
    assert event.contract_valid is False
    assert event.safe_failure_category == "invalid_agent_output"
    assert "PROMPT_SECRET_SENTINEL" not in json.dumps(event.to_properties())
    assert "ENDPOINT_SECRET_SENTINEL" not in json.dumps(event.to_properties())


@pytest.mark.parametrize(
    ("raw_text", "expected_promoted", "expected_urgency", "expected_source"),
    [
        ("The patient has chest pain.", True, "Urgent", "rules"),
        (ROUTINE_TEXT, False, "Routine", "agent"),
    ],
)
def test_event_represents_deterministic_rule_outcome(
    raw_text: str,
    expected_promoted: bool,
    expected_urgency: str,
    expected_source: str,
) -> None:
    sink = CollectingIntakeTelemetrySink()

    asyncio.run(
        _service(sink, nurse_intake_agent=Agent()).process(raw_text, "text-intake")
    )

    event = sink.events[0]
    assert event.rules_promoted_urgency is expected_promoted
    assert event.final_urgency == expected_urgency
    assert event.urgency_source == expected_source


def test_agent_provider_failure_uses_only_bounded_failure_category() -> None:
    sink = CollectingIntakeTelemetrySink()
    secret = RuntimeError("EXCEPTION_SECRET_SENTINEL ENDPOINT_SECRET_SENTINEL")

    case = asyncio.run(
        _service(sink, nurse_intake_agent=Agent(error=secret)).process(
            ROUTINE_TEXT,
            "text-intake",
        )
    )

    assert case.intakeComplete is False
    assert len(sink.events) == 1
    event = sink.events[0]
    assert event.processing_succeeded is True
    assert event.safe_failure_category == "agent_provider_failure"
    assert event.fallback_used is True
    serialized = json.dumps(event.to_properties())
    assert "EXCEPTION_SECRET_SENTINEL" not in serialized
    assert "ENDPOINT_SECRET_SENTINEL" not in serialized


def test_ai_provider_exception_is_preserved_and_emits_one_safe_event() -> None:
    sink = CollectingIntakeTelemetrySink()
    primary = RuntimeError("EXCEPTION_SECRET_SENTINEL")
    service = _service(sink, ai_service=ExplodingAiService(primary))

    with pytest.raises(RuntimeError) as exc_info:
        asyncio.run(service.process(ROUTINE_TEXT, "text-intake"))

    assert exc_info.value is primary
    assert len(sink.events) == 1
    event = sink.events[0]
    assert event.processing_succeeded is False
    assert event.safe_failure_category == "ai_provider_failure"
    assert "EXCEPTION_SECRET_SENTINEL" not in json.dumps(event.to_properties())


def test_persistence_exception_is_preserved_and_emits_one_safe_event() -> None:
    sink = CollectingIntakeTelemetrySink()
    primary = RuntimeError("PERSISTENCE_EXCEPTION_SECRET_SENTINEL")
    service = _service(sink, case_repository=ExplodingRepository(primary))

    with pytest.raises(RuntimeError) as exc_info:
        asyncio.run(service.process(ROUTINE_TEXT, "text-intake"))

    assert exc_info.value is primary
    assert len(sink.events) == 1
    assert sink.events[0].safe_failure_category == "persistence_failure"
    assert sink.events[0].processing_succeeded is False


def test_notification_failure_is_terminal_and_uses_safe_status_categories() -> None:
    sink = CollectingIntakeTelemetrySink()

    case = asyncio.run(
        _service(sink, email_notification_sender=FailingEmailSender()).process(
            ROUTINE_TEXT,
            "text-intake",
        )
    )

    assert case.notificationEmailStatus == "Suppressed"
    assert len(sink.events) == 1
    assert sink.events[0].email_status == "Suppressed"
    assert sink.events[0].safe_failure_category == "none"


def test_unsuppressed_notification_failure_uses_bounded_terminal_category() -> None:
    sink = CollectingIntakeTelemetrySink()
    service = CaseProcessingService(
        telemetry_sink=sink,
        monotonic_clock=SequenceClock(1.0, 1.1),
        email_notification_sender=FailingEmailSender(),
        suppress_notifications=False,
    )

    case = asyncio.run(service.process(ROUTINE_TEXT, "text-intake"))

    assert case.notificationEmailStatus == "Failed"
    assert len(sink.events) == 1
    assert sink.events[0].email_status == "Failed"
    assert sink.events[0].processing_succeeded is True
    assert sink.events[0].safe_failure_category == "notification_failure"


def test_unsupported_case_type_still_emits_one_sanitized_terminal_event() -> None:
    sink = CollectingIntakeTelemetrySink()
    service = _service(sink)

    with pytest.raises(ValueError, match="Unsupported case type"):
        asyncio.run(service.process(ROUTINE_TEXT, "SECRET_CASE_TYPE"))

    assert len(sink.events) == 1
    assert sink.events[0].case_type == "unknown"
    assert sink.events[0].processing_succeeded is False
    assert sink.events[0].safe_failure_category == "unsupported_case_type"


def test_telemetry_failure_does_not_alter_successful_result() -> None:
    telemetry_error = RuntimeError("TELEMETRY_EXCEPTION_SECRET_SENTINEL")
    sink = ExplodingTelemetrySink(telemetry_error)
    control = asyncio.run(
        CaseProcessingService(suppress_notifications=True).process(
            ROUTINE_TEXT,
            "text-intake",
        )
    )

    result = asyncio.run(_service(sink).process(ROUTINE_TEXT, "text-intake"))

    assert sink.calls == 1
    assert result.model_dump(exclude={"id", "createdUtc", "lastStatusUpdatedUtc"}) == (
        control.model_dump(exclude={"id", "createdUtc", "lastStatusUpdatedUtc"})
    )


def test_telemetry_failure_never_replaces_primary_processing_exception() -> None:
    primary = RuntimeError("PRIMARY_EXCEPTION_SECRET_SENTINEL")
    sink = ExplodingTelemetrySink(
        RuntimeError("TELEMETRY_EXCEPTION_SECRET_SENTINEL")
    )
    service = _service(sink, ai_service=ExplodingAiService(primary))

    with pytest.raises(RuntimeError) as exc_info:
        asyncio.run(service.process(ROUTINE_TEXT, "text-intake"))

    assert exc_info.value is primary
    assert sink.calls == 1


def test_repeated_attempts_emit_one_event_per_attempt_without_duplicates() -> None:
    sink = CollectingIntakeTelemetrySink()
    service = CaseProcessingService(
        telemetry_sink=sink,
        monotonic_clock=SequenceClock(1.0, 1.1, 2.0, 2.1, 3.0, 3.1),
        suppress_notifications=True,
    )

    for _ in range(3):
        asyncio.run(service.process(ROUTINE_TEXT, "text-intake"))

    assert len(sink.events) == 3
    assert [event.to_properties() for event in sink.events] == [
        sink.events[0].to_properties(),
        sink.events[0].to_properties(),
        sink.events[0].to_properties(),
    ]


def test_sensitive_intake_and_output_values_never_enter_event_properties() -> None:
    sensitive_values = [
        "PATIENT_SECRET_SENTINEL",
        "PHONE_SECRET_SENTINEL",
        "SUMMARY_SECRET_SENTINEL",
        "PROMPT_SECRET_SENTINEL",
        "ENDPOINT_SECRET_SENTINEL",
    ]
    raw_text = " ".join(sensitive_values)
    agent = Agent(
        result=_valid_agent_result(summary="SUMMARY_SECRET_SENTINEL")
    )
    agent.provider = "ENDPOINT_SECRET_SENTINEL"
    sink = CollectingIntakeTelemetrySink()

    asyncio.run(
        _service(sink, nurse_intake_agent=agent).process(raw_text, "text-intake")
    )

    serialized = json.dumps(sink.events[0].to_properties(), sort_keys=True)
    assert all(value not in serialized for value in sensitive_values)


def test_service_default_is_inert_noop() -> None:
    service = CaseProcessingService()

    case = asyncio.run(service.process(ROUTINE_TEXT, "text-intake"))

    assert case.processingStatus == "Completed"
    assert service.telemetry_sink.__class__.__name__ == "NoopIntakeTelemetrySink"
