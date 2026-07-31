from collections.abc import Callable
from dataclasses import dataclass
from importlib import import_module
from typing import Any, Literal, Protocol


AzureSpeechRecognitionStatus = Literal[
    "recognized",
    "no_match",
    "canceled",
    "malformed",
]

DEPENDENCY_FAILURE_MESSAGE = "Azure Speech dependencies could not be constructed."
RECOGNITION_FAILURE_MESSAGE = "Azure Speech recognition failed."


@dataclass(frozen=True)
class AzureSpeechRecognition:
    """Application-owned normalization of one Azure Speech SDK result."""

    status: AzureSpeechRecognitionStatus
    text: str | None = None


class AzureSpeechRecognitionAdapter(Protocol):
    """Narrow seam that keeps Azure SDK response objects out of the service."""

    def recognize_once(self, audio_bytes: bytes) -> AzureSpeechRecognition:
        """Recognize one in-memory audio request."""

    def close(self) -> None:
        """Release any resources owned by this one recognition operation."""


class AzureSpeechAdapterDependencyError(RuntimeError):
    """Sanitized Azure Speech SDK construction failure."""


class AzureSpeechAdapterRecognitionError(RuntimeError):
    """Sanitized Azure Speech SDK recognition failure."""


class AzureSpeechSdkAdapter:
    """Lazy, one-shot Azure Speech SDK adapter for in-memory audio."""

    def __init__(
        self,
        *,
        endpoint: str,
        region: str,
        subscription_key: str | None = None,
        sdk_loader: Callable[[], Any] | None = None,
    ) -> None:
        self.endpoint = endpoint
        self.region = region
        self._subscription_key = subscription_key
        self._sdk_loader = sdk_loader or _load_speech_sdk
        self._sdk: Any | None = None
        self._speech_config: Any | None = None
        self._input_stream: Any | None = None
        self._audio_config: Any | None = None
        self._recognizer: Any | None = None

    def recognize_once(self, audio_bytes: bytes) -> AzureSpeechRecognition:
        dependency_failed = False
        try:
            self._construct_dependencies()
        except Exception:
            dependency_failed = True

        if dependency_failed:
            self.close()
            raise AzureSpeechAdapterDependencyError(DEPENDENCY_FAILURE_MESSAGE)

        recognition_failed = False
        sdk_result: object | None = None
        try:
            self._input_stream.write(audio_bytes)
            self._input_stream.close()
            sdk_result = self._recognizer.recognize_once_async().get()
        except Exception:
            recognition_failed = True

        if recognition_failed:
            raise AzureSpeechAdapterRecognitionError(RECOGNITION_FAILURE_MESSAGE)

        return self._normalize_result(sdk_result)

    def close(self) -> None:
        """Release owned SDK resources without replacing the primary outcome."""

        for attribute_name in (
            "_recognizer",
            "_audio_config",
            "_input_stream",
            "_speech_config",
        ):
            resource = getattr(self, attribute_name)
            setattr(self, attribute_name, None)
            _close_when_supported(resource)
        self._sdk = None

    def _construct_dependencies(self) -> None:
        if self._recognizer is not None:
            return

        self._sdk = self._sdk_loader()
        if self._subscription_key is None:
            self._speech_config = self._sdk.SpeechConfig(endpoint=self.endpoint)
        else:
            self._speech_config = self._sdk.SpeechConfig(
                subscription=self._subscription_key,
                endpoint=self.endpoint,
            )
        self._input_stream = self._sdk.audio.PushAudioInputStream()
        self._audio_config = self._sdk.audio.AudioConfig(stream=self._input_stream)
        self._recognizer = self._sdk.SpeechRecognizer(
            speech_config=self._speech_config,
            audio_config=self._audio_config,
        )

    def _normalize_result(self, sdk_result: object | None) -> AzureSpeechRecognition:
        if self._sdk is None or sdk_result is None:
            return AzureSpeechRecognition(status="malformed")

        reason = getattr(sdk_result, "reason", None)
        result_reason = getattr(self._sdk, "ResultReason", None)
        if result_reason is None:
            return AzureSpeechRecognition(status="malformed")

        if reason == getattr(result_reason, "RecognizedSpeech", object()):
            text = getattr(sdk_result, "text", None)
            if not isinstance(text, str):
                return AzureSpeechRecognition(status="malformed")
            return AzureSpeechRecognition(status="recognized", text=text)

        if reason == getattr(result_reason, "NoMatch", object()):
            return AzureSpeechRecognition(status="no_match")

        if reason == getattr(result_reason, "Canceled", object()):
            return AzureSpeechRecognition(status="canceled")

        return AzureSpeechRecognition(status="malformed")


def create_azure_speech_sdk_adapter(
    endpoint: str,
    region: str,
    subscription_key: str | None = None,
) -> AzureSpeechSdkAdapter:
    """Create a lazy adapter without importing or constructing the Azure SDK."""

    return AzureSpeechSdkAdapter(
        endpoint=endpoint,
        region=region,
        subscription_key=subscription_key,
    )


def _load_speech_sdk() -> Any:
    return import_module("azure.cognitiveservices.speech")


def _close_when_supported(resource: object | None) -> None:
    close = getattr(resource, "close", None)
    if not callable(close):
        return
    try:
        close()
    except Exception:
        return
