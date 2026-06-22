import os


class AppSettings:
    """Read the MVP runtime mode, suppression, and Cosmos configuration."""

    app_mode: str
    demo_suppress_notifications: bool
    cosmos_database_name: str
    cosmos_container_name: str
    cosmos_endpoint: str | None
    cosmos_key: str | None

    def __init__(self) -> None:
        self.app_mode = os.getenv("APP_MODE", "mock")
        self.demo_suppress_notifications = self._parse_bool(
            os.getenv("DEMO_SUPPRESS_NOTIFICATIONS", "false")
        )
        self.cosmos_database_name = os.getenv(
            "COSMOS_DATABASE_NAME", "nurse-intake"
        ).strip()
        self.cosmos_container_name = os.getenv(
            "COSMOS_CONTAINER_NAME", "cases"
        ).strip()
        self.cosmos_endpoint = self._optional_env("COSMOS_ENDPOINT")
        self.cosmos_key = self._optional_env("COSMOS_KEY")

    @staticmethod
    def _parse_bool(value: str) -> bool:
        normalized_value = value.strip().lower()
        if normalized_value in {"1", "true", "yes", "on"}:
            return True
        if normalized_value in {"0", "false", "no", "off"}:
            return False
        raise ValueError(f"Invalid boolean value: {value}")

    @staticmethod
    def _optional_env(name: str) -> str | None:
        value = os.getenv(name)
        if value is None:
            return None
        return value.strip() or None
