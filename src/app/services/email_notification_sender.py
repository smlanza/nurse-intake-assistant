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
    ) -> bool | None:
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

    def clear(self) -> None:
        self.sent_notifications.clear()


class AcsEmailNotificationSender:
    """Build ACS Email messages through an injected client."""

    def __init__(
        self,
        connection_string: str,
        sender_address: str,
        default_recipient: str,
        email_client: Any | None = None,
        email_client_factory: Any | None = None,
    ) -> None:
        self.connection_string = connection_string
        self.sender_address = sender_address
        self.default_recipient = default_recipient
        self.email_client = email_client
        self.email_client_factory = email_client_factory or create_acs_email_client

    def send_case_notification(
        self,
        recipient: str,
        subject: str,
        body: str,
        case_id: str,
    ) -> bool:
        try:
            poller = self._get_email_client().begin_send(
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
            if hasattr(poller, "result"):
                poller.result()
            return True
        except Exception:
            return False

    def _get_email_client(self) -> Any:
        if self.email_client is None:
            self.email_client = self.email_client_factory(self.connection_string)
        return self.email_client


def create_acs_email_client(connection_string: str) -> Any:
    from azure.communication.email import EmailClient

    return EmailClient.from_connection_string(connection_string)
