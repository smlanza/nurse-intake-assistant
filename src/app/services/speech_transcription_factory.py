from collections.abc import Callable

from src.app.config.settings import AppSettings
from src.app.services.azure_speech_transcription_adapter import (
    AzureSpeechRecognitionAdapter,
    create_azure_speech_sdk_adapter,
)
from src.app.services.speech_transcription_service import (
    AzureSpeechTranscriptionService,
    MockSpeechTranscriptionService,
    SpeechTranscriptionError,
)


def create_speech_transcription_service(
    settings: AppSettings,
    *,
    azure_adapter_factory: Callable[
        [str, str], AzureSpeechRecognitionAdapter
    ] = create_azure_speech_sdk_adapter,
) -> MockSpeechTranscriptionService | AzureSpeechTranscriptionService:
    """Select the configured transcription boundary."""

    provider = settings.speech_provider_normalized

    if provider == "mock":
        return MockSpeechTranscriptionService()

    if provider == "azure":
        if (
            settings.azure_speech_endpoint is None
            or settings.azure_speech_region is None
        ):
            raise SpeechTranscriptionError("missing_configuration")
        return AzureSpeechTranscriptionService(
            endpoint=settings.azure_speech_endpoint,
            region=settings.azure_speech_region,
            adapter_factory=azure_adapter_factory,
        )

    raise ValueError(f"Unsupported SPEECH_PROVIDER: {settings.speech_provider}")
