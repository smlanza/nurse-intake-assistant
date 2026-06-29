import pytest

from src.app.services.speech_transcription_service import (
    AzureSpeechTranscriptionService,
    AzureSpeechUnavailableError,
    MockSpeechTranscriptionService,
    TranscriptionResult,
)


def test_mock_speech_transcription_returns_provided_transcript() -> None:
    service = MockSpeechTranscriptionService()

    result = service.transcribe_text("Patient left a voicemail about a refill.")

    assert isinstance(result, TranscriptionResult)
    assert result.text == "Patient left a voicemail about a refill."
    assert result.source == "mock"
    assert result.confidence == 1.0
    assert result.duration_seconds is None


def test_mock_speech_transcription_rejects_blank_transcript() -> None:
    service = MockSpeechTranscriptionService()

    with pytest.raises(ValueError, match="transcript text is required"):
        service.transcribe_text("   ")


def test_azure_speech_transcription_scaffold_fails_clearly() -> None:
    service = AzureSpeechTranscriptionService(
        endpoint="https://example.cognitiveservices.azure.com",
        region="eastus",
    )

    with pytest.raises(
        AzureSpeechUnavailableError,
        match="Azure Speech transcription is deferred",
    ) as exc:
        service.transcribe_text("Patient left a voicemail about a refill.")

    message = str(exc.value)
    assert "example.cognitiveservices.azure.com" not in message
    assert "eastus" not in message
