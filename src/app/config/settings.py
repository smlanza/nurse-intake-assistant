import os


class AppSettings:
    app_mode: str
    demo_suppress_notifications: bool

    def __init__(self) -> None:
        self.app_mode = os.getenv("APP_MODE", "mock")
        self.demo_suppress_notifications = self._parse_bool(
            os.getenv("DEMO_SUPPRESS_NOTIFICATIONS", "false")
        )

    @staticmethod
    def _parse_bool(value: str) -> bool:
        normalized_value = value.strip().lower()
        if normalized_value in {"1", "true", "yes", "on"}:
            return True
        if normalized_value in {"0", "false", "no", "off"}:
            return False
        raise ValueError(f"Invalid boolean value: {value}")
