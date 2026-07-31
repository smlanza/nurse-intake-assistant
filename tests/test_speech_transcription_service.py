import pytest

from src.app.services import speech_transcription_service as speech_service


class FakeAzureSpeechAdapter:
    def __init__(self, result: object = None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.audio_requests: list[bytes] = []
        self.close_calls = 0
        self.close_error: Exception | None = None

    def recognize_once(self, audio_bytes: bytes) -> object:
        self.audio_requests.append(audio_bytes)
        if self.error is not None:
            raise self.error
        return self.result

    def close(self) -> None:
        self.close_calls += 1
        if self.close_error is not None:
            raise self.close_error


def _recognition(status: str, text: str | None = None) -> object:
    from src.app.services.azure_speech_transcription_adapter import (
        AzureSpeechRecognition,
    )

    return AzureSpeechRecognition(status=status, text=text)


def _error_type():
    return speech_service.SpeechTranscriptionError


def test_mock_speech_transcription_returns_provided_transcript() -> None:
    service = speech_service.MockSpeechTranscriptionService()

    result = service.transcribe_text("Patient left a voicemail about a refill.")

    assert isinstance(result, speech_service.TranscriptionResult)
    assert result.text == "Patient left a voicemail about a refill."
    assert result.source == "mock"
    assert result.confidence == 1.0
    assert result.duration_seconds is None


def test_mock_speech_transcription_rejects_blank_transcript() -> None:
    service = speech_service.MockSpeechTranscriptionService()

    with pytest.raises(ValueError, match="transcript text is required"):
        service.transcribe_text("   ")


def test_azure_speech_maps_recognized_text_through_injected_adapter() -> None:
    adapter = FakeAzureSpeechAdapter(_recognition("recognized", "  Call me back.  "))
    service = speech_service.AzureSpeechTranscriptionService(
        endpoint="https://fictional-speech.example.invalid",
        region="fictional-region",
        adapter=adapter,
    )

    result = service.transcribe_audio(b"fictional-audio")

    assert result == speech_service.TranscriptionResult(
        text="Call me back.",
        source="azure",
    )
    assert adapter.audio_requests == [b"fictional-audio"]
    assert adapter.close_calls == 1


@pytest.mark.parametrize(
    ("status", "text", "malformed", "category"),
    [
        ("no_match", None, False, "no_match"),
        ("canceled", None, False, "canceled"),
        ("recognized", "   ", False, "empty_recognized_text"),
        ("recognized", "unused", True, "malformed_response"),
    ],
)
def test_azure_speech_fails_closed_for_non_success_results(
    status: str,
    text: str | None,
    malformed: bool,
    category: str,
) -> None:
    recognition = object() if malformed else _recognition(status, text)
    adapter = FakeAzureSpeechAdapter(recognition)
    service = speech_service.AzureSpeechTranscriptionService(
        endpoint="https://fictional-speech.example.invalid",
        region="fictional-region",
        adapter=adapter,
    )

    with pytest.raises(_error_type()) as exc_info:
        service.transcribe_audio(b"fictional-audio")

    assert exc_info.value.category == category
    assert str(exc_info.value) == speech_service.SPEECH_TRANSCRIPTION_MESSAGES[category]
    assert adapter.close_calls == 1


def test_azure_speech_sanitizes_recognition_exceptions_and_closes_adapter() -> None:
    sensitive_text = (
        "subscription-key token https://private.example.invalid "
        "/tmp/private-recording.wav cancellation details"
    )
    adapter = FakeAzureSpeechAdapter(error=RuntimeError(sensitive_text))
    service = speech_service.AzureSpeechTranscriptionService(
        endpoint="https://fictional-speech.example.invalid",
        region="fictional-region",
        adapter=adapter,
    )

    with pytest.raises(_error_type()) as exc_info:
        service.transcribe_audio(b"secret-raw-audio")

    assert exc_info.value.category == "recognition_failed"
    assert str(exc_info.value) == speech_service.SPEECH_TRANSCRIPTION_MESSAGES[
        "recognition_failed"
    ]
    assert sensitive_text not in str(exc_info.value)
    assert "secret-raw-audio" not in str(exc_info.value)
    assert exc_info.value.__cause__ is None
    assert adapter.close_calls == 1


def test_azure_speech_dependency_construction_is_lazy_and_sanitized() -> None:
    factory_calls: list[tuple[str, str]] = []

    def failing_factory(endpoint: str, region: str) -> object:
        factory_calls.append((endpoint, region))
        raise RuntimeError("private endpoint and credential construction detail")

    service = speech_service.AzureSpeechTranscriptionService(
        endpoint="https://fictional-speech.example.invalid",
        region="fictional-region",
        adapter_factory=failing_factory,
    )

    assert factory_calls == []

    with pytest.raises(_error_type()) as exc_info:
        service.transcribe_audio(b"fictional-audio")

    assert factory_calls == [
        ("https://fictional-speech.example.invalid", "fictional-region")
    ]
    assert exc_info.value.category == "dependency_construction_failed"
    assert "private endpoint" not in str(exc_info.value)
    assert exc_info.value.__cause__ is None


def test_azure_speech_missing_settings_fail_before_adapter_construction() -> None:
    def forbidden_factory(endpoint: str, region: str) -> object:
        pytest.fail("adapter construction must follow settings validation")

    service = speech_service.AzureSpeechTranscriptionService(
        endpoint=None,
        region="fictional-region",
        adapter_factory=forbidden_factory,
    )

    with pytest.raises(_error_type()) as exc_info:
        service.transcribe_audio(b"fictional-audio")

    assert exc_info.value.category == "missing_configuration"


def test_azure_speech_cleanup_error_does_not_replace_success() -> None:
    adapter = FakeAzureSpeechAdapter(_recognition("recognized", "Call me."))
    adapter.close_error = RuntimeError("private cleanup detail")
    service = speech_service.AzureSpeechTranscriptionService(
        endpoint="https://fictional-speech.example.invalid",
        region="fictional-region",
        adapter=adapter,
    )

    result = service.transcribe_audio(b"fictional-audio")

    assert result.text == "Call me."
    assert adapter.close_calls == 1


def test_azure_speech_cleanup_error_does_not_replace_primary_failure() -> None:
    adapter = FakeAzureSpeechAdapter(_recognition("no_match"))
    adapter.close_error = RuntimeError("private cleanup detail")
    service = speech_service.AzureSpeechTranscriptionService(
        endpoint="https://fictional-speech.example.invalid",
        region="fictional-region",
        adapter=adapter,
    )

    with pytest.raises(_error_type()) as exc_info:
        service.transcribe_audio(b"fictional-audio")

    assert exc_info.value.category == "no_match"
    assert adapter.close_calls == 1
