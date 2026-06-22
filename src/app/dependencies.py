from src.app.config.settings import AppSettings
from src.app.services.case_repository import InMemoryCaseRepository
from src.app.services.email_notification_sender import MockEmailNotificationSender


settings = AppSettings()
case_repository = InMemoryCaseRepository()
email_notification_sender = MockEmailNotificationSender()
