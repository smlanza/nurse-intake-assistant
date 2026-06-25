class MockSmsNotificationSender:
    """Placeholder SMS sender for safe local/mock mode."""


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
