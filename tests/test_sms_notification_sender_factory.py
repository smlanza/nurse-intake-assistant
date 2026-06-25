import pytest

from src.app.config.settings import AppSettings


def test_mock_provider_creates_mock_sms_sender(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.services.sms_notification_sender import MockSmsNotificationSender
    from src.app.services.sms_notification_sender_factory import (
        create_sms_notification_sender,
    )

    monkeypatch.setenv("SMS_PROVIDER", "mock")
    monkeypatch.delenv("ACS_SMS_CONNECTION_STRING", raising=False)
    monkeypatch.delenv("ACS_SMS_FROM_PHONE_NUMBER", raising=False)
    monkeypatch.delenv("NURSE_NOTIFICATION_PHONE_NUMBER", raising=False)

    sender = create_sms_notification_sender(AppSettings())

    assert isinstance(sender, MockSmsNotificationSender)


def test_sms_provider_matching_ignores_case_and_whitespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.services.sms_notification_sender import MockSmsNotificationSender
    from src.app.services.sms_notification_sender_factory import (
        create_sms_notification_sender,
    )

    monkeypatch.setenv("SMS_PROVIDER", "  MOCK  ")

    sender = create_sms_notification_sender(AppSettings())

    assert isinstance(sender, MockSmsNotificationSender)


def test_acs_provider_creates_acs_sms_sender(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.services.sms_notification_sender import AcsSmsNotificationSender
    from src.app.services.sms_notification_sender_factory import (
        create_sms_notification_sender,
    )

    monkeypatch.setenv("SMS_PROVIDER", "acs")
    monkeypatch.setenv(
        "ACS_SMS_CONNECTION_STRING",
        "endpoint=https://example.communication.azure.com/;accesskey=fake",
    )
    monkeypatch.setenv("ACS_SMS_FROM_PHONE_NUMBER", "+15555550100")
    monkeypatch.setenv("NURSE_NOTIFICATION_PHONE_NUMBER", "+15555550123")

    sender = create_sms_notification_sender(AppSettings())

    assert isinstance(sender, AcsSmsNotificationSender)
    assert sender.from_phone_number == "+15555550100"
    assert sender.default_recipient == "+15555550123"


def test_unknown_sms_provider_raises_clear_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.services.sms_notification_sender_factory import (
        create_sms_notification_sender,
    )

    monkeypatch.setenv("SMS_PROVIDER", "twilio")

    with pytest.raises(ValueError, match="Unsupported SMS_PROVIDER"):
        create_sms_notification_sender(AppSettings())


def test_mock_provider_does_not_require_acs_sms_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.services.sms_notification_sender import MockSmsNotificationSender
    from src.app.services.sms_notification_sender_factory import (
        create_sms_notification_sender,
    )

    monkeypatch.setenv("SMS_PROVIDER", "mock")
    monkeypatch.delenv("ACS_SMS_CONNECTION_STRING", raising=False)
    monkeypatch.delenv("ACS_SMS_FROM_PHONE_NUMBER", raising=False)
    monkeypatch.delenv("NURSE_NOTIFICATION_PHONE_NUMBER", raising=False)

    sender = create_sms_notification_sender(AppSettings())

    assert isinstance(sender, MockSmsNotificationSender)


def test_acs_provider_requires_connection_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.services.sms_notification_sender_factory import (
        create_sms_notification_sender,
    )

    monkeypatch.setenv("SMS_PROVIDER", "acs")
    monkeypatch.delenv("ACS_SMS_CONNECTION_STRING", raising=False)
    monkeypatch.setenv("ACS_SMS_FROM_PHONE_NUMBER", "+15555550100")
    monkeypatch.setenv("NURSE_NOTIFICATION_PHONE_NUMBER", "+15555550123")

    with pytest.raises(ValueError, match="ACS_SMS_CONNECTION_STRING"):
        create_sms_notification_sender(AppSettings())


def test_acs_provider_requires_from_phone_number(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.services.sms_notification_sender_factory import (
        create_sms_notification_sender,
    )

    monkeypatch.setenv("SMS_PROVIDER", "acs")
    monkeypatch.setenv(
        "ACS_SMS_CONNECTION_STRING",
        "endpoint=https://example.communication.azure.com/;accesskey=fake",
    )
    monkeypatch.delenv("ACS_SMS_FROM_PHONE_NUMBER", raising=False)
    monkeypatch.setenv("NURSE_NOTIFICATION_PHONE_NUMBER", "+15555550123")

    with pytest.raises(ValueError, match="ACS_SMS_FROM_PHONE_NUMBER"):
        create_sms_notification_sender(AppSettings())


def test_acs_provider_requires_nurse_notification_phone_number(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.services.sms_notification_sender_factory import (
        create_sms_notification_sender,
    )

    monkeypatch.setenv("SMS_PROVIDER", "acs")
    monkeypatch.setenv(
        "ACS_SMS_CONNECTION_STRING",
        "endpoint=https://example.communication.azure.com/;accesskey=fake",
    )
    monkeypatch.setenv("ACS_SMS_FROM_PHONE_NUMBER", "+15555550100")
    monkeypatch.delenv("NURSE_NOTIFICATION_PHONE_NUMBER", raising=False)

    with pytest.raises(ValueError, match="NURSE_NOTIFICATION_PHONE_NUMBER"):
        create_sms_notification_sender(AppSettings())
