class FakeAcsEmailClient:
    def __init__(self) -> None:
        self.sent_messages: list[dict] = []

    def begin_send(self, message: dict) -> None:
        self.sent_messages.append(message)


def test_acs_sender_sends_case_notification_to_default_nurse_recipient() -> None:
    from src.app.services.email_notification_sender import AcsEmailNotificationSender

    fake_client = FakeAcsEmailClient()
    sender = AcsEmailNotificationSender(
        connection_string="endpoint=https://example.communication.azure.com/;accesskey=fake-secret",
        sender_address="sender@example.com",
        default_recipient="nurse@example.com",
        email_client=fake_client,
    )

    result = sender.send_case_notification(
        recipient="ignored-request-recipient@example.com",
        subject="New Urgent intake case case-123",
        body=(
            "Patient: Jane Doe\n"
            "Callback: +1 (555) 555-0123\n"
            "Summary: Patient has chest pain."
        ),
        case_id="case-123",
    )

    assert result is None
    assert len(fake_client.sent_messages) == 1
    message = fake_client.sent_messages[0]
    assert message["senderAddress"] == "sender@example.com"
    assert message["recipients"]["to"] == [{"address": "nurse@example.com"}]
    assert "case-123" in message["content"]["subject"]
    assert "Urgent" in message["content"]["subject"]
    assert "Patient has chest pain." in message["content"]["plainText"]
    assert "Jane Doe" in message["content"]["plainText"]
    assert "+1 (555) 555-0123" in message["content"]["plainText"]


def test_acs_sender_does_not_include_connection_string_in_email_payload() -> None:
    from src.app.services.email_notification_sender import AcsEmailNotificationSender

    connection_string = (
        "endpoint=https://example.communication.azure.com/;accesskey=fake-secret"
    )
    fake_client = FakeAcsEmailClient()
    sender = AcsEmailNotificationSender(
        connection_string=connection_string,
        sender_address="sender@example.com",
        default_recipient="nurse@example.com",
        email_client=fake_client,
    )

    sender.send_case_notification(
        recipient="nurse@example.com",
        subject="New Routine intake case case-456",
        body="Summary: Patient needs a medication refill.",
        case_id="case-456",
    )

    assert connection_string not in str(fake_client.sent_messages[0])
