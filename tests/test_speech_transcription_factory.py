import pytest

from src.app.config.settings import AppSettings
from src.app.services.speech_transcription_factory import (
    create_speech_transcription_service,
)
from src.app.services.speech_transcription_service import (
    AzureSpeechTranscriptionService,
    MockSpeechTranscriptionService,
)
from src.app.services import speech_transcription_service as speech_service


def test_speech_provider_defaults_to_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SPEECH_PROVIDER", raising=False)
    monkeypatch.delenv("AZURE_SPEECH_ENDPOINT", raising=False)
    monkeypatch.delenv("AZURE_SPEECH_REGION", raising=False)

    settings = AppSettings()

    assert settings.speech_provider == "mock"
    assert settings.speech_provider_normalized == "mock"
    assert settings.azure_speech_endpoint is None
    assert settings.azure_speech_region is None


def test_mock_speech_provider_does_not_require_azure_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SPEECH_PROVIDER", "mock")
    monkeypatch.delenv("AZURE_SPEECH_ENDPOINT", raising=False)
    monkeypatch.delenv("AZURE_SPEECH_REGION", raising=False)

    service = create_speech_transcription_service(
        AppSettings(),
        azure_adapter_factory=lambda endpoint, region: pytest.fail(
            "mock selection must not construct an Azure adapter"
        ),
    )

    assert isinstance(service, MockSpeechTranscriptionService)


def test_azure_speech_provider_wires_lazy_adapter_without_network_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SPEECH_PROVIDER", "azure")
    monkeypatch.setenv(
        "AZURE_SPEECH_ENDPOINT",
        "  https://example.cognitiveservices.azure.com  ",
    )
    monkeypatch.setenv("AZURE_SPEECH_REGION", "  eastus  ")
    adapter_factory_calls: list[tuple[str, str]] = []

    def adapter_factory(endpoint: str, region: str) -> object:
        adapter_factory_calls.append((endpoint, region))
        return object()

    service = create_speech_transcription_service(
        AppSettings(),
        azure_adapter_factory=adapter_factory,
    )

    assert isinstance(service, AzureSpeechTranscriptionService)
    assert service.endpoint == "https://example.cognitiveservices.azure.com"
    assert service.region == "eastus"
    assert adapter_factory_calls == []


@pytest.mark.parametrize(
    ("endpoint", "region"),
    [
        (None, "fictional-region"),
        ("https://fictional-speech.example.invalid", None),
    ],
)
def test_azure_speech_provider_rejects_missing_settings_before_adapter_construction(
    monkeypatch: pytest.MonkeyPatch,
    endpoint: str | None,
    region: str | None,
) -> None:
    monkeypatch.setenv("SPEECH_PROVIDER", "azure")
    if endpoint is None:
        monkeypatch.delenv("AZURE_SPEECH_ENDPOINT", raising=False)
    else:
        monkeypatch.setenv("AZURE_SPEECH_ENDPOINT", endpoint)
    if region is None:
        monkeypatch.delenv("AZURE_SPEECH_REGION", raising=False)
    else:
        monkeypatch.setenv("AZURE_SPEECH_REGION", region)

    with pytest.raises(speech_service.SpeechTranscriptionError) as exc_info:
        create_speech_transcription_service(
            AppSettings(),
            azure_adapter_factory=lambda configured_endpoint, configured_region: (
                pytest.fail("missing settings must fail before adapter construction")
            ),
        )

    assert exc_info.value.category == "missing_configuration"


def test_speech_provider_matching_ignores_case_and_whitespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SPEECH_PROVIDER", "  MOCK  ")

    service = create_speech_transcription_service(AppSettings())

    assert isinstance(service, MockSpeechTranscriptionService)


def test_unsupported_speech_provider_fails_clearly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SPEECH_PROVIDER", "watson")

    with pytest.raises(ValueError, match="Unsupported SPEECH_PROVIDER"):
        create_speech_transcription_service(AppSettings())
