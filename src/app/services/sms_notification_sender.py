from dataclasses import dataclass
from typing import Protocol


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
    ) -> None:
        self.connection_string = connection_string
        self.from_phone_number = from_phone_number
        self.default_recipient = default_recipient
