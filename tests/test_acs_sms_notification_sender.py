import importlib
import builtins
import sys
from types import ModuleType


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


class FailingAcsSmsClient:
    def send(self, message: dict) -> None:
        raise RuntimeError("ACS SMS send failed")


class FailingSmsSendResult:
    def wait(self) -> None:
        raise RuntimeError("ACS SMS result handling failed")


class ResultFailingAcsSmsClient:
    def send(self, message: dict) -> FailingSmsSendResult:
        return FailingSmsSendResult()


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


def test_acs_sms_sender_returns_false_when_client_raises_during_send() -> None:
    from src.app.services.sms_notification_sender import AcsSmsNotificationSender

    sender = AcsSmsNotificationSender(
        connection_string="endpoint=https://example.communication.azure.com/;accesskey=fake-secret",
        from_phone_number="+15555550100",
        default_recipient="+15555550123",
        sms_client=FailingAcsSmsClient(),
    )

    result = sender.send_case_notification(
        recipient="+15555550123",
        body="Summary: Patient needs a medication refill.",
        case_id="case-sms-send-fails",
    )

    assert result is False


def test_acs_sms_sender_returns_false_when_client_factory_raises() -> None:
    from src.app.services.sms_notification_sender import AcsSmsNotificationSender

    def failing_client_factory(connection_string: str) -> object:
        raise RuntimeError("ACS SMS client creation failed")

    sender = AcsSmsNotificationSender(
        connection_string="endpoint=https://example.communication.azure.com/;accesskey=fake-secret",
        from_phone_number="+15555550100",
        default_recipient="+15555550123",
        sms_client_factory=failing_client_factory,
    )

    result = sender.send_case_notification(
        recipient="+15555550123",
        body="Summary: Patient needs a medication refill.",
        case_id="case-sms-factory-fails",
    )

    assert result is False


def test_acs_sms_sender_returns_false_when_send_result_path_raises() -> None:
    from src.app.services.sms_notification_sender import AcsSmsNotificationSender

    sender = AcsSmsNotificationSender(
        connection_string="endpoint=https://example.communication.azure.com/;accesskey=fake-secret",
        from_phone_number="+15555550100",
        default_recipient="+15555550123",
        sms_client=ResultFailingAcsSmsClient(),
    )

    result = sender.send_case_notification(
        recipient="+15555550123",
        body="Summary: Patient needs a medication refill.",
        case_id="case-sms-result-fails",
    )

    assert result is False


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


def test_create_acs_sms_client_lazily_imports_sdk_client(monkeypatch) -> None:
    from src.app.services.sms_notification_sender import create_acs_sms_client

    connection_string = (
        "endpoint=https://example.communication.azure.com/;accesskey=fake-secret"
    )

    class FakeSmsClient:
        connection_strings: list[str] = []

        @classmethod
        def from_connection_string(cls, value: str) -> "FakeSmsClient":
            cls.connection_strings.append(value)
            return cls()

    azure_module = ModuleType("azure")
    communication_module = ModuleType("azure.communication")
    sms_module = ModuleType("azure.communication.sms")
    sms_module.SmsClient = FakeSmsClient

    monkeypatch.setitem(sys.modules, "azure", azure_module)
    monkeypatch.setitem(sys.modules, "azure.communication", communication_module)
    monkeypatch.setitem(sys.modules, "azure.communication.sms", sms_module)

    client = create_acs_sms_client(connection_string)

    assert isinstance(client, FakeSmsClient)
    assert FakeSmsClient.connection_strings == [connection_string]


def test_mock_app_startup_does_not_require_azure_sms_sdk(monkeypatch) -> None:
    module_names = (
        "src.app.main",
        "src.app.routes.intake",
        "src.app.routes.cases",
        "src.app.routes.notifications",
        "src.app.dependencies",
    )
    original_modules = {
        module_name: sys.modules.get(module_name)
        for module_name in module_names
    }

    monkeypatch.setenv("SMS_PROVIDER", "mock")
    monkeypatch.delitem(sys.modules, "azure.communication.sms", raising=False)

    try:
        for module_name in module_names:
            sys.modules.pop(module_name, None)

        main = importlib.import_module("src.app.main")

        assert main.app is not None
        assert "azure.communication.sms" not in sys.modules
    finally:
        for module_name in reversed(module_names):
            original_module = original_modules[module_name]
            if original_module is None:
                sys.modules.pop(module_name, None)
            else:
                sys.modules[module_name] = original_module


def test_create_acs_sms_client_missing_sdk_raises_clear_error(monkeypatch) -> None:
    from src.app.services.sms_notification_sender import create_acs_sms_client

    connection_string = (
        "endpoint=https://example.communication.azure.com/;accesskey=fake-secret"
    )
    original_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "azure.communication.sms":
            raise ModuleNotFoundError("No module named 'azure.communication.sms'")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.delitem(sys.modules, "azure.communication.sms", raising=False)

    try:
        create_acs_sms_client(connection_string)
    except RuntimeError as exc:
        message = str(exc)
        assert "azure-communication-sms" in message
        assert "SMS_PROVIDER=acs" in message
        assert connection_string not in message
        assert "accesskey" not in message
        assert "fake-secret" not in message
        assert "endpoint=https://example.communication.azure.com/" not in message
    else:
        raise AssertionError("create_acs_sms_client should fail when SDK is missing")
