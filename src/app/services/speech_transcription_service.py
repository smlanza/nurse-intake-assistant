from dataclasses import dataclass


@dataclass(frozen=True)
class TranscriptionResult:
    text: str
    source: str
    confidence: float | None = None
    duration_seconds: float | None = None


class AzureSpeechUnavailableError(RuntimeError):
    """Raised when the deferred Azure Speech scaffold is invoked."""


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
    """Scaffold future Azure Speech transcription without SDK calls."""

    def __init__(self, endpoint: str | None = None, region: str | None = None) -> None:
        self.endpoint = endpoint
        self.region = region

    def transcribe_text(self, transcript_text: str) -> TranscriptionResult:
        raise AzureSpeechUnavailableError(
            "Azure Speech transcription is deferred; current voicemail intake "
            "expects already-transcribed text."
        )
