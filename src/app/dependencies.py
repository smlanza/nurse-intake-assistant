from src.app.config.settings import AppSettings
from src.app.application_composition import compose_application


settings = AppSettings()
application = compose_application(settings)
ai_service = application.ai_service
nurse_intake_agent = application.nurse_intake_agent
case_repository = application.case_repository
email_notification_sender = application.email_notification_sender
sms_notification_sender = application.sms_notification_sender
case_processing_service = application.case_processing_service
