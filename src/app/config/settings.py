import os


class AppSettings:
    """Read MVP runtime, notification, and Cosmos configuration."""

    app_mode: str
    demo_suppress_notifications: bool
    email_provider: str
    email_provider_normalized: str
    acs_email_connection_string: str | None
    acs_email_sender_address: str | None
    nurse_notification_email: str | None
    sms_provider: str
    sms_provider_normalized: str
    acs_sms_connection_string: str | None
    acs_sms_from_phone_number: str | None
    nurse_notification_phone_number: str | None
    cosmos_database_name: str
    cosmos_container_name: str
    cosmos_endpoint: str | None
    cosmos_key: str | None

    def __init__(self) -> None:
        self.app_mode = os.getenv("APP_MODE", "mock")
        self.demo_suppress_notifications = self._parse_bool(
            os.getenv("DEMO_SUPPRESS_NOTIFICATIONS", "false")
        )
        self.email_provider = os.getenv("EMAIL_PROVIDER", "mock")
        self.email_provider_normalized = self.email_provider.strip().lower()
        self.acs_email_connection_string = self._optional_env(
            "ACS_EMAIL_CONNECTION_STRING"
        )
        self.acs_email_sender_address = self._optional_env("ACS_EMAIL_SENDER_ADDRESS")
        self.nurse_notification_email = self._optional_env("NURSE_NOTIFICATION_EMAIL")
        self.sms_provider = os.getenv("SMS_PROVIDER", "mock")
        self.sms_provider_normalized = self.sms_provider.strip().lower()
        self.acs_sms_connection_string = self._optional_env(
            "ACS_SMS_CONNECTION_STRING"
        )
        self.acs_sms_from_phone_number = self._optional_env(
            "ACS_SMS_FROM_PHONE_NUMBER"
        )
        self.nurse_notification_phone_number = self._optional_env(
            "NURSE_NOTIFICATION_PHONE_NUMBER"
        )
        self.cosmos_database_name = os.getenv(
            "COSMOS_DATABASE_NAME", "nurse-intake"
        ).strip()
        self.cosmos_container_name = os.getenv(
            "COSMOS_CONTAINER_NAME", "cases"
        ).strip()
        self.cosmos_endpoint = self._optional_env("COSMOS_ENDPOINT")
        self.cosmos_key = self._optional_env("COSMOS_KEY")

    @staticmethod
    def _parse_bool(value: str) -> bool:
        normalized_value = value.strip().lower()
        if normalized_value in {"1", "true", "yes", "on"}:
            return True
        if normalized_value in {"0", "false", "no", "off"}:
            return False
        raise ValueError(f"Invalid boolean value: {value}")

    @staticmethod
    def _optional_env(name: str) -> str | None:
        value = os.getenv(name)
        if value is None:
            return None
        return value.strip() or None
