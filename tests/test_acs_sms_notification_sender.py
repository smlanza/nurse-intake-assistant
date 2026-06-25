class FakeAcsSmsClient:
    def __init__(self) -> None:
        self.sent_messages: list[dict] = []

    def send(self, message: dict) -> None:
        self.sent_messages.append(message)


class RecordingAcsSmsClient:
    instances: list["RecordingAcsSmsClient"] = []

    def __init__(self, connection_string: str) -> None:
        self.connection_string = connection_string
        self.sent_messages: list[dict] = []
        RecordingAcsSmsClient.instances.append(self)

    def send(self, message: dict) -> None:
        self.sent_messages.append(message)


def test_acs_sms_sender_returns_true_when_client_accepts_send() -> None:
    from src.app.services.sms_notification_sender import AcsSmsNotificationSender

    fake_client = FakeAcsSmsClient()
    sender = AcsSmsNotificationSender(
        connection_string="endpoint=https://example.communication.azure.com/;accesskey=fake-secret",
        from_phone_number="+15555550100",
        default_recipient="+15555550123",
        sms_client=fake_client,
    )

    result = sender.send_case_notification(
        recipient="+15555550999",
        body="Summary: Patient needs a medication refill.",
        case_id="case-sms-success",
    )

    assert result is True
    assert len(fake_client.sent_messages) == 1


def test_acs_sms_sender_sends_case_notification_to_default_recipient() -> None:
    from src.app.services.sms_notification_sender import AcsSmsNotificationSender

    fake_client = FakeAcsSmsClient()
    sender = AcsSmsNotificationSender(
        connection_string="endpoint=https://example.communication.azure.com/;accesskey=fake-secret",
        from_phone_number="+15555550100",
        default_recipient="+15555550123",
        sms_client=fake_client,
    )

    result = sender.send_case_notification(
        recipient="+15555550999",
        body="Summary: Patient has chest pain.",
        case_id="case-sms-123",
    )

    assert result is True
    assert len(fake_client.sent_messages) == 1
    message = fake_client.sent_messages[0]
    assert message["from"] == "+15555550100"
    assert message["to"] == ["+15555550123"]
    assert "case-sms-123" in message["message"]
    assert "Patient has chest pain." in message["message"]


def test_acs_sms_sender_does_not_include_connection_string_in_sms_payload() -> None:
    from src.app.services.sms_notification_sender import AcsSmsNotificationSender

    connection_string = (
        "endpoint=https://example.communication.azure.com/;accesskey=fake-secret"
    )
    fake_client = FakeAcsSmsClient()
    sender = AcsSmsNotificationSender(
        connection_string=connection_string,
        from_phone_number="+15555550100",
        default_recipient="+15555550123",
        sms_client=fake_client,
    )

    sender.send_case_notification(
        recipient="+15555550123",
        body="Summary: Patient needs a medication refill.",
        case_id="case-sms-secret-check",
    )

    assert connection_string not in str(fake_client.sent_messages[0])


def test_acs_sms_sender_lazily_creates_client_from_factory_on_first_send() -> None:
    from src.app.services.sms_notification_sender import AcsSmsNotificationSender

    connection_string = (
        "endpoint=https://example.communication.azure.com/;accesskey=fake-secret"
    )
    factory_calls: list[str] = []

    def fake_client_factory(value: str) -> RecordingAcsSmsClient:
        factory_calls.append(value)
        return RecordingAcsSmsClient(value)

    sender = AcsSmsNotificationSender(
        connection_string=connection_string,
        from_phone_number="+15555550100",
        default_recipient="+15555550123",
        sms_client_factory=fake_client_factory,
    )

    assert factory_calls == []

    sender.send_case_notification(
        recipient="+15555550123",
        body="Summary: Patient has shortness of breath.",
        case_id="case-sms-789",
    )

    assert factory_calls == [connection_string]
    assert len(RecordingAcsSmsClient.instances) == 1
    assert len(RecordingAcsSmsClient.instances[0].sent_messages) == 1


def test_acs_sms_sender_reuses_created_client_for_multiple_sends() -> None:
    from src.app.services.sms_notification_sender import AcsSmsNotificationSender

    RecordingAcsSmsClient.instances.clear()

    sender = AcsSmsNotificationSender(
        connection_string="endpoint=https://example.communication.azure.com/;accesskey=fake-secret",
        from_phone_number="+15555550100",
        default_recipient="+15555550123",
        sms_client_factory=RecordingAcsSmsClient,
    )

    sender.send_case_notification(
        recipient="+15555550123",
        body="Summary: First case.",
        case_id="case-sms-1",
    )
    sender.send_case_notification(
        recipient="+15555550123",
        body="Summary: Second case.",
        case_id="case-sms-2",
    )

    assert len(RecordingAcsSmsClient.instances) == 1
    assert len(RecordingAcsSmsClient.instances[0].sent_messages) == 2


def test_create_acs_sms_client_factory_function_exists() -> None:
    from src.app.services.sms_notification_sender import create_acs_sms_client

    assert callable(create_acs_sms_client)
