from src.app.config.settings import AppSettings
from src.app.services.email_notification_sender import MockEmailNotificationSender
from src.app.services.repository_factory import create_case_repository


settings = AppSettings()
case_repository = create_case_repository(settings)
email_notification_sender = MockEmailNotificationSender()
