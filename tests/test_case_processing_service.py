import asyncio
from datetime import date

import pytest

from src.app.models.ai_outputs import UrgencyClassificationResult
from src.app.models.ai_outputs import ExtractionSummaryResult, PatientInfo
from src.app.models.case import CaseDocument
from src.app.services.case_repository import InMemoryCaseRepository
from src.app.services.case_processing_service import CaseProcessingService
from src.app.services.email_notification_sender import MockEmailNotificationSender
from src.app.services.mock_ai_service import MockAiService
from src.app.services.sms_notification_sender import MockSmsNotificationSender


ROUTINE_TEXT = (
    "My name is Jane Doe. DOB: 1980-04-15. "
    "My callback number is +1 (555) 555-0123. I need a medication refill."
)


class RecordingCaseRepository:
    def __init__(self) -> None:
        self.saved_case: CaseDocument | None = None

    async def save(self, case: CaseDocument) -> None:
        self.saved_case = case

    async def get_by_id(self, case_id: str) -> CaseDocument | None:
        if self.saved_case is not None and self.saved_case.id == case_id:
            return self.saved_case
        return None


class SuccessfulEmailNotificationSender:
    def send_case_notification(
        self,
        recipient: str,
        subject: str,
        body: str,
        case_id: str,
    ) -> bool:
        return True


class FailingEmailNotificationSender:
    def send_case_notification(
        self,
        recipient: str,
        subject: str,
        body: str,
        case_id: str,
    ) -> bool:
        return False


class SuccessfulSmsNotificationSender:
    def send_case_notification(
        self,
        recipient: str,
        body: str,
        case_id: str,
    ) -> bool:
        return True


class FailingSmsNotificationSender:
    def send_case_notification(
        self,
        recipient: str,
        body: str,
        case_id: str,
    ) -> bool:
        return False


class ExceptionSmsNotificationSender:
    def send_case_notification(
        self,
        recipient: str,
        body: str,
        case_id: str,
    ) -> bool:
        raise RuntimeError("SMS notification failed")


class ExceptionEmailNotificationSender:
    def send_case_notification(
        self,
        recipient: str,
        subject: str,
        body: str,
        case_id: str,
    ) -> bool:
        raise RuntimeError("Email notification failed")


class ExplodingAiService:
    async def extract_and_summarize(self, raw_text: str) -> ExtractionSummaryResult:
        raise AssertionError("AI service should not run when agent is configured")

    async def classify_urgency(self, raw_text: str) -> UrgencyClassificationResult:
        raise AssertionError("AI service should not run when agent is configured")


class RecordingNurseIntakeAgent:
    def __init__(
        self,
        urgency: str = "Routine",
        summary: str = "Agent mapped summary.",
        missing_fields: list[str] | None = None,
    ) -> None:
        self.calls: list[str] = []
        self.urgency = urgency
        self.summary = summary
        self.missing_fields = missing_fields or []

    async def analyze_intake(self, raw_text: str):
        self.calls.append(raw_text)
        return _agent_result(
            urgency=self.urgency,
            summary=self.summary,
            missing_fields=self.missing_fields,
        )


def _agent_result(
    urgency: str = "Routine",
    summary: str = "Agent mapped summary.",
    missing_fields: list[str] | None = None,
):
    return type(
        "AgentResult",
        (),
        {
            "extraction": ExtractionSummaryResult(
                patient=PatientInfo(
                    name="Agent Demo Patient",
                    date_of_birth="1988-08-08",
                    callback_number="000-000-0200",
                ),
                reason_for_calling="agent-assisted refill",
                symptoms=["fatigue"],
                summary=summary,
                missing_fields=missing_fields or [],
                uncertain_fields=[],
            ),
            "urgency": UrgencyClassificationResult(
                urgency=urgency,
                urgency_rationale="Agent classified the intake.",
                advisory_disclaimer="Advisory only; nurse review is required.",
            ),
            "handoffNote": "Agent handoff note.",
            "metadata": type(
                "AgentMetadata",
                (),
                {
                    "provider": "mock",
                    "agentMode": "mock",
                },
            )(),
        },
    )()


def test_routine_intake_creates_completed_case() -> None:
    case = asyncio.run(CaseProcessingService().process(ROUTINE_TEXT, "text-intake"))

    assert isinstance(case, CaseDocument)
    assert case.caseType == "text-intake"
    assert case.transcript == ROUTINE_TEXT
    assert case.patient.name == "Jane Doe"
    assert case.reasonForCalling == "medication refill"
    assert case.summary == "Patient is calling about medication refill."
    assert case.urgency == "Routine"
    assert case.ruleUrgency == "Routine"
    assert case.aiUrgency == "Routine"
    assert case.urgencySource == "Unknown"
    assert case.processingStatus == "Completed"
    assert case.intakeStatus == "Complete"
    assert case.intakeComplete is True
    assert case.missingFields == []
    assert case.reviewStatus == "PendingReview"
    assert date.fromisoformat(case.createdDate) == case.createdUtc.date()


def test_mock_agent_provider_path_still_uses_ai_service() -> None:
    service = CaseProcessingService(suppress_notifications=True)

    case = asyncio.run(service.process(ROUTINE_TEXT, "text-intake"))

    assert case.patient.name == "Jane Doe"
    assert case.reasonForCalling == "medication refill"
    assert case.summary == "Patient is calling about medication refill."
    assert case.urgency == "Routine"


def test_agent_configured_intake_uses_agent_instead_of_ai_service() -> None:
    agent = RecordingNurseIntakeAgent()
    service = CaseProcessingService(
        ai_service=ExplodingAiService(),
        nurse_intake_agent=agent,
        suppress_notifications=True,
    )

    case = asyncio.run(service.process(ROUTINE_TEXT, "text-intake"))

    assert agent.calls == [ROUTINE_TEXT]
    assert case.patient.name == "Agent Demo Patient"
    assert case.reasonForCalling == "agent-assisted refill"
    assert case.summary == "Agent mapped summary."
    assert case.urgency == "Routine"
    assert case.aiUrgency == "Routine"
    assert case.ruleUrgency == "Routine"
    assert case.notificationEmailStatus == "Suppressed"
    assert case.notificationSmsStatus == "Suppressed"
    assert case.processing_trace.agent_used is True
    assert case.processing_trace.ai_provider is None
    assert case.processing_trace.agent_provider == "mock"
    assert case.processing_trace.final_urgency_source == "agent"
    assert case.processing_trace.rules_urgency_override is False
    assert case.processing_trace.steps == [
        "agent.extract_summary",
        "agent.classify_urgency",
        "rules.apply_red_flags",
        "case.persist",
        "notifications.send",
    ]


def test_non_agent_processing_records_ai_processing_trace() -> None:
    service = CaseProcessingService(suppress_notifications=True)

    case = asyncio.run(service.process(ROUTINE_TEXT, "text-intake"))

    assert case.processing_trace.agent_used is False
    assert case.processing_trace.agent_provider is None
    assert case.processing_trace.ai_provider == "mock"
    assert case.processing_trace.final_urgency_source == "ai"
    assert case.processing_trace.rules_urgency_override is False
    assert case.processing_trace.steps == [
        "ai.extract_summary",
        "ai.classify_urgency",
        "rules.apply_red_flags",
        "case.persist",
        "notifications.send",
    ]


def test_agent_configured_intake_preserves_missing_field_validation() -> None:
    agent = RecordingNurseIntakeAgent(
        missing_fields=[
            "patient.date_of_birth",
            "patient.callback_number",
        ],
    )
    service = CaseProcessingService(
        ai_service=ExplodingAiService(),
        nurse_intake_agent=agent,
        suppress_notifications=True,
    )

    case = asyncio.run(
        service.process("Agent text with incomplete demographics.", "text-intake")
    )

    assert agent.calls == ["Agent text with incomplete demographics."]
    assert case.intakeComplete is False
    assert case.intakeStatus == "NeedsFollowUp"
    assert case.missingFields == [
        "patient.date_of_birth",
        "patient.callback_number",
    ]
    assert case.reviewStatus == "PendingReview"


def test_agent_configured_intake_preserves_red_flag_rules() -> None:
    text = "I have chest pain and need help with my refill."
    agent = RecordingNurseIntakeAgent(urgency="Routine")
    service = CaseProcessingService(
        ai_service=ExplodingAiService(),
        nurse_intake_agent=agent,
        suppress_notifications=True,
    )

    case = asyncio.run(service.process(text, "text-intake"))

    assert agent.calls == [text]
    assert case.urgency == "Urgent"
    assert case.aiUrgency == "Routine"
    assert case.ruleUrgency == "Urgent"
    assert case.urgencySource == "Rules"
    assert "Red-flag rule match" in case.urgencyRationale
    assert case.processing_trace.rules_urgency_override is True
    assert case.processing_trace.final_urgency_source == "rules"


def test_agent_configured_intake_saves_same_core_case_fields() -> None:
    repository = RecordingCaseRepository()
    agent = RecordingNurseIntakeAgent(summary="Agent saved summary.")
    service = CaseProcessingService(
        ai_service=ExplodingAiService(),
        nurse_intake_agent=agent,
        case_repository=repository,
        suppress_notifications=True,
    )

    case = asyncio.run(service.process(ROUTINE_TEXT, "text-intake"))

    assert repository.saved_case is case
    assert repository.saved_case is not None
    assert repository.saved_case.caseType == "text-intake"
    assert repository.saved_case.patient.name == "Agent Demo Patient"
    assert repository.saved_case.reasonForCalling == "agent-assisted refill"
    assert repository.saved_case.symptoms == ["fatigue"]
    assert repository.saved_case.transcript == ROUTINE_TEXT
    assert repository.saved_case.summary == "Agent saved summary."
    assert repository.saved_case.reviewStatus == "PendingReview"


def test_agent_configured_intake_keeps_mock_notification_semantics() -> None:
    email_sender = MockEmailNotificationSender()
    sms_sender = MockSmsNotificationSender()
    agent = RecordingNurseIntakeAgent()
    service = CaseProcessingService(
        ai_service=ExplodingAiService(),
        nurse_intake_agent=agent,
        email_notification_sender=email_sender,
        sms_notification_sender=sms_sender,
    )

    case = asyncio.run(service.process(ROUTINE_TEXT, "text-intake"))

    assert case.notificationEmailSent is True
    assert case.notificationEmailStatus == "MockRecorded"
    assert case.notificationSmsSent is True
    assert case.notificationSmsStatus == "MockRecorded"
    assert case.notificationSmsDeliveryConfirmed is False
    assert email_sender.sent_notifications[0].case_id == case.id
    assert sms_sender.sent_notifications[0].case_id == case.id


def test_processed_case_is_saved_through_repository() -> None:
    repository = RecordingCaseRepository()
    service = CaseProcessingService(case_repository=repository)

    case = asyncio.run(service.process(ROUTINE_TEXT, "text-intake"))

    assert repository.saved_case == case


def test_case_processing_service_accepts_email_notification_sender() -> None:
    email_sender = MockEmailNotificationSender()

    service = CaseProcessingService(email_notification_sender=email_sender)

    assert service.email_notification_sender is email_sender


def test_case_processing_service_accepts_sms_notification_sender() -> None:
    sms_sender = MockSmsNotificationSender()

    service = CaseProcessingService(sms_notification_sender=sms_sender)

    assert service.sms_notification_sender is sms_sender


def test_processed_case_is_saved_and_sends_email_notification() -> None:
    repository = InMemoryCaseRepository()
    email_sender = MockEmailNotificationSender()
    service = CaseProcessingService(
        case_repository=repository,
        email_notification_sender=email_sender,
    )

    case = asyncio.run(service.process(ROUTINE_TEXT, "text-intake"))

    assert isinstance(case, CaseDocument)
    assert asyncio.run(repository.get_by_id(case.id)) == case
    assert len(email_sender.sent_notifications) == 1
    notification = email_sender.sent_notifications[0]
    assert notification.case_id == case.id
    assert case.urgency in notification.subject
    assert case.summary in notification.body
    assert case.notificationEmailSent is True
    assert case.notificationEmailStatus == "MockRecorded"


def test_successful_email_notification_updates_returned_case() -> None:
    service = CaseProcessingService(
        email_notification_sender=SuccessfulEmailNotificationSender()
    )

    case = asyncio.run(service.process(ROUTINE_TEXT, "text-intake"))

    assert case.notificationEmailSent is True
    assert case.notificationEmailStatus == "Accepted"


def test_successful_sms_notification_updates_returned_case() -> None:
    service = CaseProcessingService(
        sms_notification_sender=SuccessfulSmsNotificationSender()
    )

    case = asyncio.run(service.process(ROUTINE_TEXT, "text-intake"))

    assert case.notificationSmsSent is True
    assert case.notificationSmsStatus == "Accepted"
    assert case.notificationSmsDeliveryConfirmed is False


def test_failed_sms_notification_leaves_returned_case_unsent() -> None:
    service = CaseProcessingService(
        sms_notification_sender=FailingSmsNotificationSender()
    )

    case = asyncio.run(service.process(ROUTINE_TEXT, "text-intake"))

    assert case.notificationSmsSent is False
    assert case.notificationSmsStatus == "Failed"
    assert case.notificationSmsDeliveryConfirmed is False


def test_failed_sms_notification_still_saves_and_returns_case() -> None:
    repository = InMemoryCaseRepository()
    service = CaseProcessingService(
        case_repository=repository,
        sms_notification_sender=FailingSmsNotificationSender(),
    )

    case = asyncio.run(service.process(ROUTINE_TEXT, "text-intake"))

    assert isinstance(case, CaseDocument)
    assert asyncio.run(repository.get_by_id(case.id)) == case
    assert case.notificationSmsSent is False


def test_sms_sender_exception_still_saves_and_returns_case() -> None:
    repository = InMemoryCaseRepository()
    service = CaseProcessingService(
        case_repository=repository,
        sms_notification_sender=ExceptionSmsNotificationSender(),
    )

    case = asyncio.run(service.process(ROUTINE_TEXT, "text-intake"))

    assert isinstance(case, CaseDocument)
    assert asyncio.run(repository.get_by_id(case.id)) == case
    assert case.notificationSmsSent is False
    assert case.notificationSmsStatus == "Failed"
    assert case.notificationSmsDeliveryConfirmed is False


def test_sms_sender_exception_does_not_change_email_notification_behavior() -> None:
    service = CaseProcessingService(
        email_notification_sender=SuccessfulEmailNotificationSender(),
        sms_notification_sender=ExceptionSmsNotificationSender(),
    )

    case = asyncio.run(service.process(ROUTINE_TEXT, "text-intake"))

    assert case.notificationEmailSent is True
    assert case.notificationSmsSent is False


def test_failed_email_notification_still_saves_and_returns_case() -> None:
    repository = InMemoryCaseRepository()
    service = CaseProcessingService(
        case_repository=repository,
        email_notification_sender=FailingEmailNotificationSender(),
    )

    case = asyncio.run(service.process(ROUTINE_TEXT, "text-intake"))

    assert isinstance(case, CaseDocument)
    assert asyncio.run(repository.get_by_id(case.id)) == case
    assert case.notificationEmailSent is False
    assert case.notificationEmailStatus == "Failed"


def test_email_sender_exception_still_saves_and_returns_case() -> None:
    repository = InMemoryCaseRepository()
    service = CaseProcessingService(
        case_repository=repository,
        email_notification_sender=ExceptionEmailNotificationSender(),
    )

    case = asyncio.run(service.process(ROUTINE_TEXT, "text-intake"))

    assert isinstance(case, CaseDocument)
    assert asyncio.run(repository.get_by_id(case.id)) == case
    assert case.notificationEmailSent is False
    assert case.notificationEmailStatus == "Failed"


def test_case_processing_service_accepts_suppress_notifications_flag() -> None:
    service = CaseProcessingService(suppress_notifications=True)

    assert service.suppress_notifications is True


def test_suppressed_notifications_still_returns_and_saves_case() -> None:
    repository = InMemoryCaseRepository()
    email_sender = MockEmailNotificationSender()
    service = CaseProcessingService(
        case_repository=repository,
        email_notification_sender=email_sender,
        suppress_notifications=True,
    )

    case = asyncio.run(service.process(ROUTINE_TEXT, "text-intake"))

    assert isinstance(case, CaseDocument)
    assert case.id
    assert case.summary == "Patient is calling about medication refill."
    assert case.urgency == "Routine"
    assert asyncio.run(repository.get_by_id(case.id)) == case
    assert email_sender.sent_notifications == []
    assert case.notificationEmailSent is False
    assert case.notificationEmailStatus == "Suppressed"


def test_suppressed_notifications_suppresses_sms_notification() -> None:
    sms_sender = MockSmsNotificationSender()
    service = CaseProcessingService(
        sms_notification_sender=sms_sender,
        suppress_notifications=True,
    )

    case = asyncio.run(service.process(ROUTINE_TEXT, "text-intake"))

    assert case.notificationSmsSent is False
    assert case.notificationSmsStatus == "Suppressed"
    assert case.notificationSmsDeliveryConfirmed is False
    assert sms_sender.sent_notifications == []


def test_explicit_false_suppression_sends_email_notification() -> None:
    email_sender = MockEmailNotificationSender()
    service = CaseProcessingService(
        email_notification_sender=email_sender,
        suppress_notifications=False,
    )

    case = asyncio.run(service.process(ROUTINE_TEXT, "text-intake"))

    assert len(email_sender.sent_notifications) == 1
    assert email_sender.sent_notifications[0].case_id == case.id


def test_mock_sms_sender_records_case_notifications() -> None:
    sms_sender = MockSmsNotificationSender()

    result = sms_sender.send_case_notification(
        recipient="+15555550123",
        body="Summary: Patient needs a medication refill.",
        case_id="case-sms-1",
    )

    assert result is True
    assert len(sms_sender.sent_notifications) == 1
    notification = sms_sender.sent_notifications[0]
    assert notification.recipient == "+15555550123"
    assert notification.body == "Summary: Patient needs a medication refill."
    assert notification.case_id == "case-sms-1"


def test_mock_sms_notification_updates_returned_case_status() -> None:
    sms_sender = MockSmsNotificationSender()
    service = CaseProcessingService(sms_notification_sender=sms_sender)

    case = asyncio.run(service.process(ROUTINE_TEXT, "text-intake"))

    assert case.notificationSmsSent is True
    assert case.notificationSmsStatus == "MockRecorded"
    assert case.notificationSmsDeliveryConfirmed is False


def test_processed_case_is_saved_with_notification_statuses() -> None:
    repository = InMemoryCaseRepository()
    email_sender = MockEmailNotificationSender()
    sms_sender = MockSmsNotificationSender()
    service = CaseProcessingService(
        case_repository=repository,
        email_notification_sender=email_sender,
        sms_notification_sender=sms_sender,
    )

    case = asyncio.run(service.process(ROUTINE_TEXT, "text-intake"))

    saved_case = asyncio.run(repository.get_by_id(case.id))
    assert saved_case == case
    assert saved_case is not None
    assert saved_case.notificationEmailStatus == "MockRecorded"
    assert saved_case.notificationSmsStatus == "MockRecorded"
    assert saved_case.notificationSmsDeliveryConfirmed is False


def test_urgent_red_flag_intake_creates_completed_urgent_case() -> None:
    text = "My name is Jane Doe and I have CHEST PAIN."

    case = asyncio.run(CaseProcessingService().process(text, "phone-intake"))

    assert case.caseType == "phone-intake"
    assert case.urgency == "Urgent"
    assert case.ruleUrgency == "Urgent"
    assert case.aiUrgency == "Urgent"
    assert case.urgencySource == "RulesAndAI"
    assert case.processingStatus == "Completed"
    assert "Chest pain" in case.urgencyRationale
    assert "Advisory urgency only" in case.urgencyRationale


class RoutineOnlyMockAiService(MockAiService):
    async def classify_urgency(self, raw_text: str) -> UrgencyClassificationResult:
        return UrgencyClassificationResult(
            urgency="Routine",
            urgency_rationale="Forced routine result for merge-rule testing.",
            advisory_disclaimer="Advisory only; nurse review required.",
        )


def test_rule_urgency_overrides_ai_routine_result() -> None:
    service = CaseProcessingService(ai_service=RoutineOnlyMockAiService())

    case = asyncio.run(
        service.process("The patient reports shortness of breath.", "audio-upload")
    )

    assert case.urgency == "Urgent"
    assert case.ruleUrgency == "Urgent"
    assert case.aiUrgency == "Routine"
    assert case.urgencySource == "Rules"
    assert "Forced routine result" in case.urgencyRationale
    assert "Shortness of breath" in case.urgencyRationale
    assert case.processing_trace.rules_urgency_override is True
    assert case.processing_trace.final_urgency_source == "rules"


def test_missing_patient_fields_are_carried_into_case() -> None:
    case = asyncio.run(
        CaseProcessingService().process("I have a cough and fever.", "text-intake")
    )

    assert case.missingFields == [
        "patient.name",
        "patient.date_of_birth",
        "patient.callback_number",
    ]
    assert case.uncertainFields == []
    assert case.intakeStatus == "NeedsFollowUp"
    assert case.intakeComplete is False
    assert case.reviewStatus == "PendingReview"
    assert case.patient.name is None


def test_missing_field_case_is_saved_and_notifications_still_send() -> None:
    repository = InMemoryCaseRepository()
    email_sender = MockEmailNotificationSender()
    sms_sender = MockSmsNotificationSender()
    service = CaseProcessingService(
        case_repository=repository,
        email_notification_sender=email_sender,
        sms_notification_sender=sms_sender,
    )

    case = asyncio.run(service.process("I need a refill.", "text-intake"))

    assert case.intakeComplete is False
    assert case.reviewStatus == "PendingReview"
    assert case.missingFields == [
        "patient.name",
        "patient.date_of_birth",
        "patient.callback_number",
    ]
    assert asyncio.run(repository.get_by_id(case.id)) == case
    assert case.notificationEmailSent is True
    assert case.notificationEmailStatus == "MockRecorded"
    assert case.notificationSmsSent is True
    assert case.notificationSmsStatus == "MockRecorded"
    assert len(email_sender.sent_notifications) == 1
    assert len(sms_sender.sent_notifications) == 1


@pytest.mark.parametrize("raw_text", ["", "   "])
def test_empty_text_creates_completed_case_without_crashing(raw_text: str) -> None:
    case = asyncio.run(CaseProcessingService().process(raw_text, "text-intake"))

    assert case.transcript == raw_text
    assert case.summary == "No reason for calling or symptoms were provided."
    assert case.urgency == "Routine"
    assert case.processingStatus == "Completed"
    assert case.intakeComplete is False
    assert case.reviewStatus == "PendingReview"
    assert case.missingFields == [
        "patient.name",
        "patient.date_of_birth",
        "patient.callback_number",
        "reason_for_calling",
    ]
