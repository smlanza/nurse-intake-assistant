from src.app.config.settings import AppSettings
from src.app.services.ai_service_factory import create_ai_service
from src.app.services.email_notification_sender_factory import (
    create_email_notification_sender,
)
from src.app.services.repository_factory import create_case_repository
from src.app.services.sms_notification_sender_factory import (
    create_sms_notification_sender,
)


settings = AppSettings()
ai_service = create_ai_service(settings)
case_repository = create_case_repository(settings)
email_notification_sender = create_email_notification_sender(settings)
sms_notification_sender = create_sms_notification_sender(settings)
