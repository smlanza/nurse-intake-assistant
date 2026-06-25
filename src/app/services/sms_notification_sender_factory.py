from src.app.config.settings import AppSettings
from src.app.services.sms_notification_sender import (
    AcsSmsNotificationSender,
    MockSmsNotificationSender,
)


def create_sms_notification_sender(
    settings: AppSettings,
) -> MockSmsNotificationSender | AcsSmsNotificationSender:
    """Select the configured SMS notification sender."""

    provider = settings.sms_provider_normalized

    if provider == "mock":
        return MockSmsNotificationSender()

    if provider == "acs":
        return AcsSmsNotificationSender(
            connection_string=_required_setting(
                settings.acs_sms_connection_string,
                "ACS_SMS_CONNECTION_STRING",
            ),
            from_phone_number=_required_setting(
                settings.acs_sms_from_phone_number,
                "ACS_SMS_FROM_PHONE_NUMBER",
            ),
            default_recipient=_required_setting(
                settings.nurse_notification_phone_number,
                "NURSE_NOTIFICATION_PHONE_NUMBER",
            ),
        )

    raise ValueError(f"Unsupported SMS_PROVIDER: {settings.sms_provider}")


def _required_setting(value: str | None, name: str) -> str:
    if value is None:
        raise ValueError(f"{name} is required for ACS SMS provider")
    return value
