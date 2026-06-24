import pytest

from src.app.config.settings import AppSettings
from src.app.services.email_notification_sender import MockEmailNotificationSender


def test_mock_provider_creates_mock_email_sender(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.services.email_notification_sender_factory import (
        create_email_notification_sender,
    )

    monkeypatch.setenv("EMAIL_PROVIDER", "mock")
    monkeypatch.delenv("ACS_EMAIL_CONNECTION_STRING", raising=False)
    monkeypatch.delenv("ACS_EMAIL_SENDER_ADDRESS", raising=False)
    monkeypatch.delenv("NURSE_NOTIFICATION_EMAIL", raising=False)

    sender = create_email_notification_sender(AppSettings())

    assert isinstance(sender, MockEmailNotificationSender)


def test_email_provider_matching_ignores_case_and_whitespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.services.email_notification_sender_factory import (
        create_email_notification_sender,
    )

    monkeypatch.setenv("EMAIL_PROVIDER", "  MOCK  ")

    sender = create_email_notification_sender(AppSettings())

    assert isinstance(sender, MockEmailNotificationSender)


def test_acs_provider_creates_acs_email_sender(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.services.email_notification_sender import AcsEmailNotificationSender
    from src.app.services.email_notification_sender_factory import (
        create_email_notification_sender,
    )

    monkeypatch.setenv("EMAIL_PROVIDER", "acs")
    monkeypatch.setenv(
        "ACS_EMAIL_CONNECTION_STRING",
        "endpoint=https://example.communication.azure.com/;accesskey=fake",
    )
    monkeypatch.setenv("ACS_EMAIL_SENDER_ADDRESS", "sender@example.com")
    monkeypatch.setenv("NURSE_NOTIFICATION_EMAIL", "nurse@example.com")

    sender = create_email_notification_sender(AppSettings())

    assert isinstance(sender, AcsEmailNotificationSender)
    assert sender.sender_address == "sender@example.com"
    assert sender.default_recipient == "nurse@example.com"


def test_unknown_email_provider_raises_clear_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.services.email_notification_sender_factory import (
        create_email_notification_sender,
    )

    monkeypatch.setenv("EMAIL_PROVIDER", "smtp")

    with pytest.raises(ValueError, match="Unsupported EMAIL_PROVIDER"):
        create_email_notification_sender(AppSettings())


def test_mock_provider_does_not_require_acs_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.services.email_notification_sender_factory import (
        create_email_notification_sender,
    )

    monkeypatch.setenv("EMAIL_PROVIDER", "mock")
    monkeypatch.delenv("ACS_EMAIL_CONNECTION_STRING", raising=False)
    monkeypatch.delenv("ACS_EMAIL_SENDER_ADDRESS", raising=False)
    monkeypatch.delenv("NURSE_NOTIFICATION_EMAIL", raising=False)

    sender = create_email_notification_sender(AppSettings())

    assert isinstance(sender, MockEmailNotificationSender)


def test_acs_provider_requires_connection_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.services.email_notification_sender_factory import (
        create_email_notification_sender,
    )

    monkeypatch.setenv("EMAIL_PROVIDER", "acs")
    monkeypatch.delenv("ACS_EMAIL_CONNECTION_STRING", raising=False)
    monkeypatch.setenv("ACS_EMAIL_SENDER_ADDRESS", "sender@example.com")
    monkeypatch.setenv("NURSE_NOTIFICATION_EMAIL", "nurse@example.com")

    with pytest.raises(ValueError, match="ACS_EMAIL_CONNECTION_STRING"):
        create_email_notification_sender(AppSettings())


def test_acs_provider_requires_sender_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.services.email_notification_sender_factory import (
        create_email_notification_sender,
    )

    monkeypatch.setenv("EMAIL_PROVIDER", "acs")
    monkeypatch.setenv(
        "ACS_EMAIL_CONNECTION_STRING",
        "endpoint=https://example.communication.azure.com/;accesskey=fake",
    )
    monkeypatch.delenv("ACS_EMAIL_SENDER_ADDRESS", raising=False)
    monkeypatch.setenv("NURSE_NOTIFICATION_EMAIL", "nurse@example.com")

    with pytest.raises(ValueError, match="ACS_EMAIL_SENDER_ADDRESS"):
        create_email_notification_sender(AppSettings())


def test_acs_provider_requires_nurse_notification_email(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.services.email_notification_sender_factory import (
        create_email_notification_sender,
    )

    monkeypatch.setenv("EMAIL_PROVIDER", "acs")
    monkeypatch.setenv(
        "ACS_EMAIL_CONNECTION_STRING",
        "endpoint=https://example.communication.azure.com/;accesskey=fake",
    )
    monkeypatch.setenv("ACS_EMAIL_SENDER_ADDRESS", "sender@example.com")
    monkeypatch.delenv("NURSE_NOTIFICATION_EMAIL", raising=False)

    with pytest.raises(ValueError, match="NURSE_NOTIFICATION_EMAIL"):
        create_email_notification_sender(AppSettings())
