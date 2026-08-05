from src.app.config.settings import AppSettings
from src.app.services.azure_monitor_intake_telemetry import (
    AzureMonitorIntakeTelemetrySink,
)
from src.app.services.intake_telemetry import (
    IntakeTelemetrySink,
    NoopIntakeTelemetrySink,
)


def create_intake_telemetry_sink(settings: AppSettings) -> IntakeTelemetrySink:
    """Select the explicitly configured intake telemetry boundary."""

    provider = getattr(settings, "telemetry_provider_normalized", "none")
    if provider == "none":
        return NoopIntakeTelemetrySink()
    if provider == "azure-monitor":
        return AzureMonitorIntakeTelemetrySink(
            connection_string=getattr(
                settings,
                "applicationinsights_connection_string",
                None,
            )
        )

    configured = getattr(settings, "telemetry_provider", provider)
    raise ValueError(f"Unsupported TELEMETRY_PROVIDER: {configured}")

