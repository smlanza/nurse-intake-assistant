import sys
from types import ModuleType


class FakeAcsEmailClient:
    def __init__(self) -> None:
        self.sent_messages: list[dict] = []

    def begin_send(self, message: dict) -> None:
        self.sent_messages.append(message)


class FakeSuccessfulPoller:
    def result(self) -> dict:
        return {"status": "Succeeded"}


class FakeSuccessfulAcsEmailClient:
    def __init__(self) -> None:
        self.sent_messages: list[dict] = []

    def begin_send(self, message: dict) -> FakeSuccessfulPoller:
        self.sent_messages.append(message)
        return FakeSuccessfulPoller()


def test_acs_sender_returns_true_when_client_accepts_send() -> None:
    from src.app.services.email_notification_sender import AcsEmailNotificationSender

    fake_client = FakeSuccessfulAcsEmailClient()
    sender = AcsEmailNotificationSender(
        connection_string="endpoint=https://example.communication.azure.com/;accesskey=fake-secret",
        sender_address="sender@example.com",
        default_recipient="nurse@example.com",
        email_client=fake_client,
    )

    result = sender.send_case_notification(
        recipient="nurse@example.com",
        subject="New Routine intake case case-success",
        body="Summary: Patient needs a medication refill.",
        case_id="case-success",
    )

    assert result is True
    assert len(fake_client.sent_messages) == 1


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

    assert result is True
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


class RecordingAcsEmailClient:
    instances: list["RecordingAcsEmailClient"] = []

    def __init__(self, connection_string: str) -> None:
        self.connection_string = connection_string
        self.sent_messages: list[dict] = []
        RecordingAcsEmailClient.instances.append(self)

    def begin_send(self, message: dict) -> None:
        self.sent_messages.append(message)


def test_acs_sender_lazily_creates_client_from_factory_on_first_send() -> None:
    from src.app.services.email_notification_sender import AcsEmailNotificationSender

    connection_string = (
        "endpoint=https://example.communication.azure.com/;accesskey=fake-secret"
    )
    factory_calls: list[str] = []

    def fake_client_factory(value: str) -> RecordingAcsEmailClient:
        factory_calls.append(value)
        return RecordingAcsEmailClient(value)

    sender = AcsEmailNotificationSender(
        connection_string=connection_string,
        sender_address="sender@example.com",
        default_recipient="nurse@example.com",
        email_client_factory=fake_client_factory,
    )

    assert factory_calls == []

    sender.send_case_notification(
        recipient="nurse@example.com",
        subject="New Urgent intake case case-789",
        body="Summary: Patient has shortness of breath.",
        case_id="case-789",
    )

    assert factory_calls == [connection_string]
    assert len(RecordingAcsEmailClient.instances) == 1
    assert len(RecordingAcsEmailClient.instances[0].sent_messages) == 1


def test_acs_sender_reuses_created_client_for_multiple_sends() -> None:
    from src.app.services.email_notification_sender import AcsEmailNotificationSender

    RecordingAcsEmailClient.instances.clear()

    sender = AcsEmailNotificationSender(
        connection_string="endpoint=https://example.communication.azure.com/;accesskey=fake-secret",
        sender_address="sender@example.com",
        default_recipient="nurse@example.com",
        email_client_factory=RecordingAcsEmailClient,
    )

    sender.send_case_notification(
        recipient="nurse@example.com",
        subject="New Routine intake case case-1",
        body="Summary: First case.",
        case_id="case-1",
    )
    sender.send_case_notification(
        recipient="nurse@example.com",
        subject="New Routine intake case case-2",
        body="Summary: Second case.",
        case_id="case-2",
    )

    assert len(RecordingAcsEmailClient.instances) == 1
    assert len(RecordingAcsEmailClient.instances[0].sent_messages) == 2


def test_create_acs_email_client_lazily_imports_sdk_client(
    monkeypatch,
) -> None:
    from src.app.services.email_notification_sender import create_acs_email_client

    connection_string = (
        "endpoint=https://example.communication.azure.com/;accesskey=fake-secret"
    )

    class FakeEmailClient:
        connection_strings: list[str] = []

        @classmethod
        def from_connection_string(cls, value: str) -> "FakeEmailClient":
            cls.connection_strings.append(value)
            return cls()

    azure_module = ModuleType("azure")
    communication_module = ModuleType("azure.communication")
    email_module = ModuleType("azure.communication.email")
    email_module.EmailClient = FakeEmailClient

    monkeypatch.setitem(sys.modules, "azure", azure_module)
    monkeypatch.setitem(sys.modules, "azure.communication", communication_module)
    monkeypatch.setitem(sys.modules, "azure.communication.email", email_module)

    client = create_acs_email_client(connection_string)

    assert isinstance(client, FakeEmailClient)
    assert FakeEmailClient.connection_strings == [connection_string]
