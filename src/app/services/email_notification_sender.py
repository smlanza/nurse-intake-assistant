from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class EmailNotification:
    recipient: str
    subject: str
    body: str
    case_id: str


class EmailNotificationSender(Protocol):
    def send_case_notification(
        self,
        recipient: str,
        subject: str,
        body: str,
        case_id: str,
    ) -> None:
        ...


class MockEmailNotificationSender:
    """Record email notifications in memory for tests and demo inspection."""

    def __init__(self) -> None:
        self.sent_notifications: list[EmailNotification] = []

    def send_case_notification(
        self,
        recipient: str,
        subject: str,
        body: str,
        case_id: str,
    ) -> None:
        self.sent_notifications.append(
            EmailNotification(
                recipient=recipient,
                subject=subject,
                body=body,
                case_id=case_id,
            )
        )
