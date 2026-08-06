from collections.abc import Callable
from typing import Protocol

from src.app.models.intake_telemetry import IntakeTelemetryEvent


class _TelemetryClient(Protocol):
    def track_event(self, name: str, properties: dict[str, str]) -> None:
        ...

    def flush(self) -> None:
        ...


class AzureMonitorIntakeTelemetrySink:
    """Lazy Application Insights adapter for sanitized intake terminal events."""

    def __init__(
        self,
        *,
        connection_string: str | None,
        client: _TelemetryClient | None = None,
        client_factory: Callable[[str], _TelemetryClient] | None = None,
        send_function: Callable[[str, dict[str, str]], None] | None = None,
    ) -> None:
        self._connection_string = connection_string
        self._client = client
        self._client_factory = client_factory
        self._send_function = send_function

    @property
    def client(self) -> _TelemetryClient | None:
        return self._client

    def record_intake_completed(self, event: IntakeTelemetryEvent) -> None:
        properties = intake_telemetry_wire_properties(event)
        if self._send_function is not None:
            self._send_function(event.operation, properties)
            return

        client = self._get_or_create_client()
        client.track_event(event.operation, properties)
        client.flush()

    def _get_or_create_client(self) -> _TelemetryClient:
        if self._client is not None:
            return self._client

        instrumentation_key = _instrumentation_key(self._connection_string)
        if instrumentation_key is None:
            raise RuntimeError("Azure Monitor telemetry is not configured")

        factory = self._client_factory or _get_telemetry_client_class()
        self._client = factory(instrumentation_key)
        return self._client


def intake_telemetry_wire_properties(
    event: IntakeTelemetryEvent,
) -> dict[str, str]:
    """Encode the typed event into Application Insights string properties."""

    return {
        name: ("true" if value else "false") if isinstance(value, bool) else value
        for name, value in event.to_properties().items()
    }


def _instrumentation_key(connection_string: str | None) -> str | None:
    if not isinstance(connection_string, str):
        return None
    for part in connection_string.split(";"):
        key, separator, value = part.partition("=")
        if separator and key.strip().casefold() == "instrumentationkey":
            return value.strip() or None
    return None


def _get_telemetry_client_class():
    from applicationinsights import TelemetryClient

    return TelemetryClient
