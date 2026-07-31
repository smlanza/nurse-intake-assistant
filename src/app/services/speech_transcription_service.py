from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from src.app.services.azure_speech_transcription_adapter import (
    AzureSpeechAdapterDependencyError,
    AzureSpeechRecognition,
    AzureSpeechRecognitionAdapter,
    create_azure_speech_sdk_adapter,
)


@dataclass(frozen=True)
class TranscriptionResult:
    text: str
    source: str
    confidence: float | None = None
    duration_seconds: float | None = None


SpeechTranscriptionErrorCategory = Literal[
    "missing_configuration",
    "invalid_audio",
    "empty_recognized_text",
    "no_match",
    "canceled",
    "malformed_response",
    "dependency_construction_failed",
    "recognition_failed",
    "unsupported_request",
]

SPEECH_TRANSCRIPTION_MESSAGES: dict[SpeechTranscriptionErrorCategory, str] = {
    "missing_configuration": "Azure Speech configuration is incomplete.",
    "invalid_audio": "The transcription audio request is invalid.",
    "empty_recognized_text": "Azure Speech returned no recognized text.",
    "no_match": "Azure Speech did not recognize speech in the request.",
    "canceled": "Azure Speech canceled the recognition request.",
    "malformed_response": "Azure Speech returned an unsupported response.",
    "dependency_construction_failed": (
        "Azure Speech dependencies could not be constructed."
    ),
    "recognition_failed": "Azure Speech recognition failed.",
    "unsupported_request": (
        "Azure Speech requires an explicit in-memory audio transcription request."
    ),
}


class SpeechTranscriptionError(RuntimeError):
    """Deterministic application-owned Speech failure without provider details."""

    def __init__(self, category: SpeechTranscriptionErrorCategory) -> None:
        super().__init__(SPEECH_TRANSCRIPTION_MESSAGES[category])
        self.category = category


class MockSpeechTranscriptionService:
    """Offline transcription boundary for already-transcribed demo text."""

    def transcribe_text(self, transcript_text: str) -> TranscriptionResult:
        cleaned_text = transcript_text.strip()
        if not cleaned_text:
            raise ValueError("transcript text is required")

        return TranscriptionResult(
            text=cleaned_text,
            source="mock",
            confidence=1.0,
        )


class AzureSpeechTranscriptionService:
    """Application-owned Azure Speech boundary with a lazy injected adapter."""

    def __init__(
        self,
        endpoint: str | None = None,
        region: str | None = None,
        *,
        adapter: AzureSpeechRecognitionAdapter | None = None,
        adapter_factory: Callable[
            [str, str], AzureSpeechRecognitionAdapter
        ] = create_azure_speech_sdk_adapter,
    ) -> None:
        self.endpoint = endpoint
        self.region = region
        self._adapter = adapter
        self._adapter_factory = adapter_factory

    def transcribe_text(self, transcript_text: str) -> TranscriptionResult:
        raise SpeechTranscriptionError("unsupported_request")

    def transcribe_audio(self, audio_bytes: bytes) -> TranscriptionResult:
        """Transcribe one in-memory audio request through the Azure adapter."""

        self._validate_request(audio_bytes)

        adapter = self._adapter
        if adapter is None:
            construction_failed = False
            try:
                adapter = self._adapter_factory(self.endpoint, self.region)
            except Exception:
                construction_failed = True
            if construction_failed:
                raise SpeechTranscriptionError("dependency_construction_failed")

        category: SpeechTranscriptionErrorCategory | None = None
        transcription: TranscriptionResult | None = None
        try:
            try:
                recognition = adapter.recognize_once(audio_bytes)
            except AzureSpeechAdapterDependencyError:
                category = "dependency_construction_failed"
            except Exception:
                category = "recognition_failed"
            else:
                category, transcription = self._normalize_recognition(recognition)
        finally:
            _close_adapter(adapter)

        if category is not None:
            raise SpeechTranscriptionError(category)

        if transcription is None:
            raise SpeechTranscriptionError("malformed_response")
        return transcription

    def _validate_request(self, audio_bytes: bytes) -> None:
        if not self.endpoint or not self.region:
            raise SpeechTranscriptionError("missing_configuration")
        if not isinstance(audio_bytes, bytes) or not audio_bytes:
            raise SpeechTranscriptionError("invalid_audio")

    @staticmethod
    def _normalize_recognition(
        recognition: object,
    ) -> tuple[SpeechTranscriptionErrorCategory | None, TranscriptionResult | None]:
        if not isinstance(recognition, AzureSpeechRecognition):
            return "malformed_response", None

        if recognition.status == "no_match":
            return "no_match", None
        if recognition.status == "canceled":
            return "canceled", None
        if recognition.status == "malformed":
            return "malformed_response", None
        if recognition.status != "recognized" or not isinstance(recognition.text, str):
            return "malformed_response", None

        cleaned_text = recognition.text.strip()
        if not cleaned_text:
            return "empty_recognized_text", None

        return None, TranscriptionResult(text=cleaned_text, source="azure")


def _close_adapter(adapter: AzureSpeechRecognitionAdapter) -> None:
    try:
        adapter.close()
    except Exception:
        return
