def test_mock_sender_can_send_case_notification() -> None:
    from src.app.services.email_notification_sender import (
        EmailNotificationSender,
        MockEmailNotificationSender,
    )

    sender: EmailNotificationSender = MockEmailNotificationSender()

    result = sender.send_case_notification(
        recipient="nurse@example.com",
        subject="New intake case",
        body="A new case is ready for review.",
        case_id="case-123",
    )

    assert result is None


def test_mock_sender_records_notification_fields_in_memory() -> None:
    from src.app.services.email_notification_sender import MockEmailNotificationSender

    sender = MockEmailNotificationSender()

    sender.send_case_notification(
        recipient="nurse@example.com",
        subject="Urgent intake case",
        body="Please review this case promptly.",
        case_id="case-urgent-123",
    )

    assert len(sender.sent_notifications) == 1
    notification = sender.sent_notifications[0]
    assert notification.recipient == "nurse@example.com"
    assert notification.subject == "Urgent intake case"
    assert notification.body == "Please review this case promptly."
    assert notification.case_id == "case-urgent-123"


def test_mock_sender_preserves_multiple_notifications_in_order() -> None:
    from src.app.services.email_notification_sender import MockEmailNotificationSender

    sender = MockEmailNotificationSender()

    sender.send_case_notification(
        recipient="first@example.com",
        subject="First case",
        body="First notification body.",
        case_id="case-1",
    )
    sender.send_case_notification(
        recipient="second@example.com",
        subject="Second case",
        body="Second notification body.",
        case_id="case-2",
    )

    assert [item.case_id for item in sender.sent_notifications] == ["case-1", "case-2"]
    assert [item.recipient for item in sender.sent_notifications] == [
        "first@example.com",
        "second@example.com",
    ]


def test_mock_sender_exposes_sent_notifications_list() -> None:
    from src.app.services.email_notification_sender import MockEmailNotificationSender

    sender = MockEmailNotificationSender()

    assert isinstance(sender.sent_notifications, list)
    assert sender.sent_notifications == []
