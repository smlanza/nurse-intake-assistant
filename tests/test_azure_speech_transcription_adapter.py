from importlib import import_module
from types import SimpleNamespace

import pytest


class FakeClosable:
    def __init__(self) -> None:
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


class FakePushAudioInputStream(FakeClosable):
    def __init__(self) -> None:
        super().__init__()
        self.writes: list[bytes] = []

    def write(self, audio_bytes: bytes) -> None:
        self.writes.append(audio_bytes)


class FakeAudioConfig(FakeClosable):
    def __init__(self, *, stream: FakePushAudioInputStream) -> None:
        super().__init__()
        self.stream = stream


class FakeSpeechConfig(FakeClosable):
    def __init__(self, *, endpoint: str) -> None:
        super().__init__()
        self.endpoint = endpoint


class FakeRecognitionFuture:
    def __init__(self, result: object = None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error

    def get(self) -> object:
        if self.error is not None:
            raise self.error
        return self.result


class FakeSpeechRecognizer(FakeClosable):
    def __init__(
        self,
        *,
        speech_config: FakeSpeechConfig,
        audio_config: FakeAudioConfig,
        result: object,
        recognition_error: Exception | None,
    ) -> None:
        super().__init__()
        self.speech_config = speech_config
        self.audio_config = audio_config
        self.result = result
        self.recognition_error = recognition_error
        self.recognize_calls = 0

    def recognize_once_async(self) -> FakeRecognitionFuture:
        self.recognize_calls += 1
        return FakeRecognitionFuture(self.result, self.recognition_error)


class FakeSpeechSdk:
    RECOGNIZED = object()
    NO_MATCH = object()
    CANCELED = object()

    ResultReason = SimpleNamespace(
        RecognizedSpeech=RECOGNIZED,
        NoMatch=NO_MATCH,
        Canceled=CANCELED,
    )

    def __init__(
        self,
        result: object,
        recognition_error: Exception | None = None,
    ) -> None:
        self.result = result
        self.recognition_error = recognition_error
        self.speech_configs: list[FakeSpeechConfig] = []
        self.push_streams: list[FakePushAudioInputStream] = []
        self.audio_configs: list[FakeAudioConfig] = []
        self.recognizers: list[FakeSpeechRecognizer] = []
        self.audio = SimpleNamespace(
            PushAudioInputStream=self._create_push_stream,
            AudioConfig=self._create_audio_config,
        )

    def SpeechConfig(self, *, endpoint: str) -> FakeSpeechConfig:
        config = FakeSpeechConfig(endpoint=endpoint)
        self.speech_configs.append(config)
        return config

    def SpeechRecognizer(
        self,
        *,
        speech_config: FakeSpeechConfig,
        audio_config: FakeAudioConfig,
    ) -> FakeSpeechRecognizer:
        recognizer = FakeSpeechRecognizer(
            speech_config=speech_config,
            audio_config=audio_config,
            result=self.result,
            recognition_error=self.recognition_error,
        )
        self.recognizers.append(recognizer)
        return recognizer

    def _create_push_stream(self) -> FakePushAudioInputStream:
        stream = FakePushAudioInputStream()
        self.push_streams.append(stream)
        return stream

    def _create_audio_config(
        self,
        *,
        stream: FakePushAudioInputStream,
    ) -> FakeAudioConfig:
        config = FakeAudioConfig(stream=stream)
        self.audio_configs.append(config)
        return config


def _adapter_module():
    return import_module("src.app.services.azure_speech_transcription_adapter")


def _sdk_result(reason: object, text: object = None) -> SimpleNamespace:
    return SimpleNamespace(reason=reason, text=text)


def test_sdk_adapter_is_lazy_and_normalizes_recognized_text() -> None:
    adapter_module = _adapter_module()
    sdk = FakeSpeechSdk(_sdk_result(FakeSpeechSdk.RECOGNIZED, "Call me back."))
    loader_calls = 0

    def load_sdk() -> FakeSpeechSdk:
        nonlocal loader_calls
        loader_calls += 1
        return sdk

    adapter = adapter_module.AzureSpeechSdkAdapter(
        endpoint="https://fictional-speech.example.invalid",
        region="fictional-region",
        sdk_loader=load_sdk,
    )

    assert loader_calls == 0
    assert sdk.recognizers == []

    result = adapter.recognize_once(b"fictional-audio")

    assert result == adapter_module.AzureSpeechRecognition(
        status="recognized",
        text="Call me back.",
    )
    assert loader_calls == 1
    assert sdk.push_streams[0].writes == [b"fictional-audio"]
    assert sdk.recognizers[0].recognize_calls == 1


@pytest.mark.parametrize(
    ("reason", "expected_status"),
    [
        (FakeSpeechSdk.NO_MATCH, "no_match"),
        (FakeSpeechSdk.CANCELED, "canceled"),
        (object(), "malformed"),
    ],
)
def test_sdk_adapter_normalizes_non_success_reasons(
    reason: object,
    expected_status: str,
) -> None:
    adapter_module = _adapter_module()
    sdk = FakeSpeechSdk(_sdk_result(reason, "must-not-be-trusted"))
    adapter = adapter_module.AzureSpeechSdkAdapter(
        endpoint="https://fictional-speech.example.invalid",
        region="fictional-region",
        sdk_loader=lambda: sdk,
    )

    result = adapter.recognize_once(b"fictional-audio")

    assert result.status == expected_status
    assert result.text is None


def test_sdk_adapter_treats_unsupported_result_shape_as_malformed() -> None:
    adapter_module = _adapter_module()
    sdk = FakeSpeechSdk(object())
    adapter = adapter_module.AzureSpeechSdkAdapter(
        endpoint="https://fictional-speech.example.invalid",
        region="fictional-region",
        sdk_loader=lambda: sdk,
    )

    result = adapter.recognize_once(b"fictional-audio")

    assert result.status == "malformed"
    assert result.text is None


def test_sdk_adapter_sanitizes_dependency_construction_failure() -> None:
    adapter_module = _adapter_module()

    def failing_loader() -> object:
        raise RuntimeError("credential token and private endpoint")

    adapter = adapter_module.AzureSpeechSdkAdapter(
        endpoint="https://fictional-speech.example.invalid",
        region="fictional-region",
        sdk_loader=failing_loader,
    )

    with pytest.raises(adapter_module.AzureSpeechAdapterDependencyError) as exc_info:
        adapter.recognize_once(b"fictional-audio")

    assert str(exc_info.value) == adapter_module.DEPENDENCY_FAILURE_MESSAGE
    assert "credential" not in str(exc_info.value)
    assert exc_info.value.__cause__ is None


def test_sdk_adapter_sanitizes_recognition_failure() -> None:
    adapter_module = _adapter_module()
    sdk = FakeSpeechSdk(
        result=None,
        recognition_error=RuntimeError(
            "token endpoint /tmp/private.wav cancellation details"
        ),
    )
    adapter = adapter_module.AzureSpeechSdkAdapter(
        endpoint="https://fictional-speech.example.invalid",
        region="fictional-region",
        sdk_loader=lambda: sdk,
    )

    with pytest.raises(adapter_module.AzureSpeechAdapterRecognitionError) as exc_info:
        adapter.recognize_once(b"secret-raw-audio")

    assert str(exc_info.value) == adapter_module.RECOGNITION_FAILURE_MESSAGE
    assert "token" not in str(exc_info.value)
    assert "private.wav" not in str(exc_info.value)
    assert "secret-raw-audio" not in str(exc_info.value)
    assert exc_info.value.__cause__ is None


def test_sdk_adapter_closes_all_owned_resources() -> None:
    adapter_module = _adapter_module()
    sdk = FakeSpeechSdk(_sdk_result(FakeSpeechSdk.RECOGNIZED, "Call me."))
    adapter = adapter_module.AzureSpeechSdkAdapter(
        endpoint="https://fictional-speech.example.invalid",
        region="fictional-region",
        sdk_loader=lambda: sdk,
    )
    adapter.recognize_once(b"fictional-audio")

    adapter.close()

    assert sdk.recognizers[0].close_calls == 1
    assert sdk.audio_configs[0].close_calls == 1
    assert sdk.push_streams[0].close_calls >= 1
    assert sdk.speech_configs[0].close_calls == 1
