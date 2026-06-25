from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class SmsNotification:
    recipient: str
    body: str
    case_id: str


class SmsNotificationSender(Protocol):
    def send_case_notification(
        self,
        recipient: str,
        body: str,
        case_id: str,
    ) -> bool:
        ...


class MockSmsNotificationSender:
    """Record SMS notifications in memory for tests and demo inspection."""

    def __init__(self) -> None:
        self.sent_notifications: list[SmsNotification] = []

    def send_case_notification(
        self,
        recipient: str,
        body: str,
        case_id: str,
    ) -> bool:
        self.sent_notifications.append(
            SmsNotification(
                recipient=recipient,
                body=body,
                case_id=case_id,
            )
        )
        return True


class AcsSmsNotificationSender:
    """Placeholder ACS SMS sender with configuration only."""

    def __init__(
        self,
        connection_string: str,
        from_phone_number: str,
        default_recipient: str,
        sms_client: Any | None = None,
        sms_client_factory: Any | None = None,
    ) -> None:
        self.connection_string = connection_string
        self.from_phone_number = from_phone_number
        self.default_recipient = default_recipient
        self.sms_client = sms_client
        self.sms_client_factory = sms_client_factory or create_acs_sms_client

    def send_case_notification(
        self,
        recipient: str | None,
        body: str,
        case_id: str,
    ) -> bool:
        self._get_sms_client().send(
            {
                "from": self.from_phone_number,
                "to": [self.default_recipient],
                "message": f"Case {case_id}: {body}",
            }
        )
        return True

    def _get_sms_client(self) -> Any:
        if self.sms_client is None:
            self.sms_client = self.sms_client_factory(self.connection_string)
        return self.sms_client


def create_acs_sms_client(connection_string: str) -> Any:
    raise NotImplementedError("ACS SMS client creation is not implemented yet")
