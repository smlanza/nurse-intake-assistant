import pytest

from src.app.config.settings import AppSettings
from src.app.services.speech_transcription_factory import (
    create_speech_transcription_service,
)
from src.app.services.speech_transcription_service import (
    AzureSpeechTranscriptionService,
    MockSpeechTranscriptionService,
)


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

    service = create_speech_transcription_service(AppSettings())

    assert isinstance(service, MockSpeechTranscriptionService)


def test_azure_speech_provider_wires_scaffold_without_network_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SPEECH_PROVIDER", "azure")
    monkeypatch.setenv(
        "AZURE_SPEECH_ENDPOINT",
        "  https://example.cognitiveservices.azure.com  ",
    )
    monkeypatch.setenv("AZURE_SPEECH_REGION", "  eastus  ")

    service = create_speech_transcription_service(AppSettings())

    assert isinstance(service, AzureSpeechTranscriptionService)
    assert service.endpoint == "https://example.cognitiveservices.azure.com"
    assert service.region == "eastus"


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
