from typing import Protocol

from src.app.models.intake_telemetry import IntakeTelemetryEvent


class IntakeTelemetrySink(Protocol):
    """Receive one sanitized event for a terminal intake-processing attempt."""

    def record_intake_completed(self, event: IntakeTelemetryEvent) -> None:
        ...


class NoopIntakeTelemetrySink:
    """Preserve disabled telemetry as the inert default."""

    def record_intake_completed(self, event: IntakeTelemetryEvent) -> None:
        return None


class CollectingIntakeTelemetrySink:
    """Collect sanitized events for deterministic offline tests."""

    def __init__(self) -> None:
        self.events: list[IntakeTelemetryEvent] = []

    def record_intake_completed(self, event: IntakeTelemetryEvent) -> None:
        self.events.append(event)

