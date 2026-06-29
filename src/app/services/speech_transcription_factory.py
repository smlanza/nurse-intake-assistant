from src.app.config.settings import AppSettings
from src.app.services.speech_transcription_service import (
    AzureSpeechTranscriptionService,
    MockSpeechTranscriptionService,
)


def create_speech_transcription_service(
    settings: AppSettings,
) -> MockSpeechTranscriptionService | AzureSpeechTranscriptionService:
    """Select the configured transcription boundary."""

    provider = settings.speech_provider_normalized

    if provider == "mock":
        return MockSpeechTranscriptionService()

    if provider == "azure":
        return AzureSpeechTranscriptionService(
            endpoint=settings.azure_speech_endpoint,
            region=settings.azure_speech_region,
        )

    raise ValueError(f"Unsupported SPEECH_PROVIDER: {settings.speech_provider}")
