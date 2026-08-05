from types import SimpleNamespace

import pytest

from src.app.config.settings import AppSettings
from src.app.services.azure_monitor_intake_telemetry import (
    AzureMonitorIntakeTelemetrySink,
)
from src.app.services.intake_telemetry import NoopIntakeTelemetrySink
from src.app.services.intake_telemetry_factory import create_intake_telemetry_sink


def test_telemetry_provider_defaults_to_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TELEMETRY_PROVIDER", raising=False)
    monkeypatch.delenv("APPLICATIONINSIGHTS_CONNECTION_STRING", raising=False)

    settings = AppSettings()
    sink = create_intake_telemetry_sink(settings)

    assert settings.telemetry_provider == "none"
    assert settings.telemetry_provider_normalized == "none"
    assert isinstance(sink, NoopIntakeTelemetrySink)


def test_disabled_provider_constructs_no_azure_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.app.services.azure_monitor_intake_telemetry as azure_adapter

    monkeypatch.setattr(
        azure_adapter,
        "_get_telemetry_client_class",
        lambda: (_ for _ in ()).throw(AssertionError("must stay lazy")),
    )

    sink = create_intake_telemetry_sink(
        SimpleNamespace(telemetry_provider_normalized="none")
    )

    assert isinstance(sink, NoopIntakeTelemetrySink)


def test_azure_monitor_selection_constructs_only_lazy_adapter() -> None:
    settings = SimpleNamespace(
        telemetry_provider_normalized="azure-monitor",
        applicationinsights_connection_string=(
            "InstrumentationKey=fake-instrumentation-key"
        ),
    )

    sink = create_intake_telemetry_sink(settings)

    assert isinstance(sink, AzureMonitorIntakeTelemetrySink)
    assert sink.client is None


def test_unsupported_telemetry_provider_fails_factory_selection() -> None:
    settings = SimpleNamespace(
        telemetry_provider="arbitrary-provider",
        telemetry_provider_normalized="arbitrary-provider",
    )

    with pytest.raises(ValueError, match="Unsupported TELEMETRY_PROVIDER"):
        create_intake_telemetry_sink(settings)

