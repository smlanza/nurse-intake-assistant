from dataclasses import dataclass

from src.app.config.settings import AppSettings
from src.app.services.case_processing_service import CaseProcessingService
from src.app.services.case_repository import CaseRepository
from src.app.services.email_notification_sender import EmailNotificationSender
from src.app.services.foundry_ai_service import FoundryAiService
from src.app.services.mock_ai_service import MockAiService
from src.app.services.nurse_intake_agent import NurseIntakeAgent
from src.app.services import (
    ai_service_factory,
    email_notification_sender_factory,
    nurse_intake_agent_factory,
    repository_factory,
    sms_notification_sender_factory,
)
from src.app.services.sms_notification_sender import (
    AcsSmsNotificationSender,
    MockSmsNotificationSender,
)


@dataclass(frozen=True)
class ApplicationComposition:
    settings: AppSettings
    ai_service: MockAiService | FoundryAiService
    nurse_intake_agent: NurseIntakeAgent | None
    case_repository: CaseRepository
    email_notification_sender: EmailNotificationSender
    sms_notification_sender: MockSmsNotificationSender | AcsSmsNotificationSender
    case_processing_service: CaseProcessingService


def compose_application(settings: AppSettings) -> ApplicationComposition:
    """Compose the production intake dependencies without processing an intake."""

    ai_service = ai_service_factory.create_ai_service(settings)
    nurse_intake_agent = nurse_intake_agent_factory.create_optional_nurse_intake_agent(
        settings
    )
    case_repository = repository_factory.create_case_repository(settings)
    email_notification_sender = (
        email_notification_sender_factory.create_email_notification_sender(settings)
    )
    sms_notification_sender = (
        sms_notification_sender_factory.create_sms_notification_sender(settings)
    )
    case_processing_service = CaseProcessingService(
        ai_service=ai_service,
        case_repository=case_repository,
        email_notification_sender=email_notification_sender,
        sms_notification_sender=sms_notification_sender,
        nurse_intake_agent=nurse_intake_agent,
        suppress_notifications=settings.demo_suppress_notifications,
    )
    return ApplicationComposition(
        settings=settings,
        ai_service=ai_service,
        nurse_intake_agent=nurse_intake_agent,
        case_repository=case_repository,
        email_notification_sender=email_notification_sender,
        sms_notification_sender=sms_notification_sender,
        case_processing_service=case_processing_service,
    )
