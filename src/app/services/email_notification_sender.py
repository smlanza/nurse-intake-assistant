from dataclasses import dataclass
from typing import Any, Protocol


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


class AcsEmailNotificationSender:
    """Build ACS Email messages through an injected client."""

    def __init__(
        self,
        connection_string: str,
        sender_address: str,
        default_recipient: str,
        email_client: Any | None = None,
    ) -> None:
        self.connection_string = connection_string
        self.sender_address = sender_address
        self.default_recipient = default_recipient
        self.email_client = email_client

    def send_case_notification(
        self,
        recipient: str,
        subject: str,
        body: str,
        case_id: str,
    ) -> None:
        if self.email_client is None:
            raise NotImplementedError("ACS Email client is not configured yet.")

        self.email_client.begin_send(
            {
                "senderAddress": self.sender_address,
                "recipients": {
                    "to": [{"address": self.default_recipient}],
                },
                "content": {
                    "subject": subject,
                    "plainText": body,
                },
            }
        )
