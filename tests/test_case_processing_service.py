import asyncio
from datetime import date

import pytest

from src.app.models.ai_outputs import UrgencyClassificationResult
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
    assert case.reviewStatus == "New"
    assert date.fromisoformat(case.createdDate) == case.createdUtc.date()


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


def test_successful_email_notification_updates_returned_case() -> None:
    service = CaseProcessingService(
        email_notification_sender=SuccessfulEmailNotificationSender()
    )

    case = asyncio.run(service.process(ROUTINE_TEXT, "text-intake"))

    assert case.notificationEmailSent is True


def test_successful_sms_notification_updates_returned_case() -> None:
    service = CaseProcessingService(
        sms_notification_sender=SuccessfulSmsNotificationSender()
    )

    case = asyncio.run(service.process(ROUTINE_TEXT, "text-intake"))

    assert case.notificationSmsSent is True


def test_failed_sms_notification_leaves_returned_case_unsent() -> None:
    service = CaseProcessingService(
        sms_notification_sender=FailingSmsNotificationSender()
    )

    case = asyncio.run(service.process(ROUTINE_TEXT, "text-intake"))

    assert case.notificationSmsSent is False


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


def test_suppressed_notifications_suppresses_sms_notification() -> None:
    sms_sender = MockSmsNotificationSender()
    service = CaseProcessingService(
        sms_notification_sender=sms_sender,
        suppress_notifications=True,
    )

    case = asyncio.run(service.process(ROUTINE_TEXT, "text-intake"))

    assert case.notificationSmsSent is False
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


def test_missing_patient_fields_are_carried_into_case() -> None:
    case = asyncio.run(
        CaseProcessingService().process("I have a cough and fever.", "text-intake")
    )

    assert case.missingFields == ["name", "date_of_birth", "callback_number"]
    assert case.uncertainFields == []
    assert case.intakeStatus == "NeedsFollowUp"
    assert case.patient.name is None


@pytest.mark.parametrize("raw_text", ["", "   "])
def test_empty_text_creates_completed_case_without_crashing(raw_text: str) -> None:
    case = asyncio.run(CaseProcessingService().process(raw_text, "text-intake"))

    assert case.transcript == raw_text
    assert case.summary == "No reason for calling or symptoms were provided."
    assert case.urgency == "Routine"
    assert case.processingStatus == "Completed"
    assert case.missingFields == ["name", "date_of_birth", "callback_number"]
