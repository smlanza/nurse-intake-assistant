from src.app.config.settings import AppSettings
from src.app.services.email_notification_sender import (
    AcsEmailNotificationSender,
    EmailNotificationSender,
    MockEmailNotificationSender,
)


def create_email_notification_sender(settings: AppSettings) -> EmailNotificationSender:
    """Select the configured email notification sender."""

    provider = settings.email_provider_normalized

    if provider == "mock":
        return MockEmailNotificationSender()

    if provider == "acs":
        return AcsEmailNotificationSender(
            connection_string=_required_setting(
                settings.acs_email_connection_string,
                "ACS_EMAIL_CONNECTION_STRING",
            ),
            sender_address=_required_setting(
                settings.acs_email_sender_address,
                "ACS_EMAIL_SENDER_ADDRESS",
            ),
            default_recipient=_required_setting(
                settings.nurse_notification_email,
                "NURSE_NOTIFICATION_EMAIL",
            ),
        )

    raise ValueError(f"Unsupported EMAIL_PROVIDER: {settings.email_provider}")


def _required_setting(value: str | None, name: str) -> str:
    if value is None:
        raise ValueError(f"{name} is required for ACS email provider")
    return value
