import importlib
import json
from pathlib import Path
from types import SimpleNamespace
import wave

import pytest

from src.app.services.azure_speech_transcription_adapter import (
    AzureSpeechRecognition,
)
from src.app.services.speech_transcription_factory import (
    create_speech_transcription_service,
)
from src.app.services.speech_transcription_service import (
    AzureSpeechTranscriptionService,
    SpeechTranscriptionError,
)


EXPECTED_TEXT = "This is a fictional nurse intake test for Jordan Lee."
PRIVATE_MARKER = (
    "secret-key https://private-speech.example.invalid private-region "
    "/tmp/private.wav raw cancellation details"
)


def _script():
    return importlib.import_module("scripts.smoke_azure_speech_transcription")


def _write_wav(
    path: Path,
    *,
    channels: int = 1,
    sample_width: int = 2,
    frame_rate: int = 16_000,
    frames: bytes | None = None,
) -> Path:
    audio_frames = frames if frames is not None else b"\x00\x00" * 160
    with wave.open(str(path), "wb") as fixture:
        fixture.setnchannels(channels)
        fixture.setsampwidth(sample_width)
        fixture.setframerate(frame_rate)
        fixture.writeframes(audio_frames)
    return path


def _valid_fixture(tmp_path: Path) -> Path:
    fixture_dir = tmp_path / "fixtures"
    fixture_dir.mkdir(parents=True)
    return _write_wav(fixture_dir / "fictional_speech_intake.wav")


def _settings(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "speech_provider": "azure",
        "speech_provider_normalized": "azure",
        "azure_speech_endpoint": "https://private-speech.example.invalid",
        "azure_speech_region": "private-region",
        "azure_speech_key": "secret-key",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class FakeAdapter:
    def __init__(
        self,
        recognition: object = None,
        error: Exception | None = None,
        close_error: Exception | None = None,
    ) -> None:
        self.recognition = recognition
        self.error = error
        self.close_error = close_error
        self.recognition_calls = 0
        self.close_calls = 0
        self.audio_requests: list[bytes] = []

    def recognize_once(self, audio_bytes: bytes) -> object:
        self.recognition_calls += 1
        self.audio_requests.append(audio_bytes)
        if self.error is not None:
            raise self.error
        return self.recognition

    def close(self) -> None:
        self.close_calls += 1
        if self.close_error is not None:
            raise self.close_error


def _service(adapter: FakeAdapter) -> AzureSpeechTranscriptionService:
    return AzureSpeechTranscriptionService(
        endpoint="https://private-speech.example.invalid",
        region="private-region",
        adapter=adapter,
    )


def _run_live(script, tmp_path: Path, service: object):
    fixture = script.validate_fixed_fixture(
        _valid_fixture(tmp_path),
        approved_directory=tmp_path / "fixtures",
    )
    return script.run_live_validation(
        _settings(),
        fixture,
        sdk_available=True,
        service_factory=lambda settings: service,
    )


def test_check_mode_fails_closed_without_sdk_or_live_construction(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    script = _script()
    fixture = _valid_fixture(tmp_path)
    monkeypatch.setattr(script, "FIXTURE_PATH", fixture)
    monkeypatch.setattr(script, "FIXTURE_DIRECTORY", fixture.parent)
    monkeypatch.setattr(script, "azure_speech_sdk_available", lambda: False)
    monkeypatch.setattr(
        script,
        "create_speech_transcription_service",
        lambda settings: pytest.fail("check mode must not construct a service"),
    )

    exit_code = script.main(["--check", "--json"])

    output = capsys.readouterr()
    payload = json.loads(output.out)
    assert exit_code == 2
    assert output.err == ""
    assert payload == {
        "adapter_constructed": False,
        "azure_call_made": False,
        "azure_mutation_made": False,
        "category": "sdk_unavailable",
        "fictional_audio": True,
        "fixture_valid": True,
        "missing_settings": [],
        "mode": "check",
        "notification_attempted": False,
        "ok": False,
        "operation": "smoke_azure_speech_transcription",
        "persistence_attempted": False,
        "provider": "azure",
        "route_invoked": False,
        "sdk_available": False,
        "transcript_matches_expected": False,
        "transcript_valid": False,
        "transcription_attempted": False,
    }


def test_check_json_is_deterministic_and_one_newline_terminated_document(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    script = _script()
    fixture = _valid_fixture(tmp_path)
    monkeypatch.setattr(script, "FIXTURE_PATH", fixture)
    monkeypatch.setattr(script, "FIXTURE_DIRECTORY", fixture.parent)
    monkeypatch.setattr(script, "azure_speech_sdk_available", lambda: True)

    assert script.main(["--check", "--json"]) == 0
    first = capsys.readouterr().out
    assert script.main(["--check", "--json"]) == 0
    second = capsys.readouterr().out

    assert first == second
    assert first.endswith("\n")
    assert first.count("\n") == 1
    assert json.loads(first)["transcription_attempted"] is False


@pytest.mark.parametrize(
    "arguments",
    [
        [],
        ["--check", "--live", "--json"],
        ["--live", "--json"],
        ["--live", "--config", ".env.speech.local"],
    ],
)
def test_cli_rejects_invalid_or_ambiguous_modes(arguments: list[str]) -> None:
    script = _script()

    with pytest.raises(script.InvalidArgumentsError):
        script.parse_arguments(arguments)


def test_fixture_validation_accepts_only_fixed_owned_pcm_wav(tmp_path: Path) -> None:
    script = _script()
    fixture = _valid_fixture(tmp_path)

    result = script.validate_fixed_fixture(
        fixture,
        approved_directory=fixture.parent,
    )

    assert result.ok is True
    assert result.category == "success"
    assert result.audio_bytes == b"\x00\x00" * 160


def test_fixture_validation_rejects_symlink(tmp_path: Path) -> None:
    script = _script()
    fixture = _valid_fixture(tmp_path)
    target = fixture.with_name("target.wav")
    fixture.rename(target)
    fixture.symlink_to(target)

    result = script.validate_fixed_fixture(
        fixture,
        approved_directory=fixture.parent,
    )

    assert result.ok is False
    assert result.category == "fixture_invalid"


def test_fixture_validation_rejects_wrong_filename(tmp_path: Path) -> None:
    script = _script()
    approved = tmp_path / "fixtures"
    approved.mkdir()
    fixture = _write_wav(approved / "other.wav")

    result = script.validate_fixed_fixture(fixture, approved_directory=approved)

    assert result.ok is False
    assert result.category == "fixture_invalid"


@pytest.mark.parametrize(
    ("fixture_builder", "expected_category"),
    [
        (lambda path: path.write_bytes(b"not-a-wave"), "fixture_invalid"),
        (
            lambda path: _write_wav(path, channels=2),
            "fixture_invalid",
        ),
        (
            lambda path: _write_wav(path, sample_width=1),
            "fixture_invalid",
        ),
        (
            lambda path: _write_wav(path, frame_rate=8_000),
            "fixture_invalid",
        ),
    ],
)
def test_fixture_validation_rejects_malformed_or_unsupported_wav(
    tmp_path: Path,
    fixture_builder,
    expected_category: str,
) -> None:
    script = _script()
    approved = tmp_path / "fixtures"
    approved.mkdir()
    fixture = approved / "fictional_speech_intake.wav"
    fixture_builder(fixture)

    result = script.validate_fixed_fixture(fixture, approved_directory=approved)

    assert result.ok is False
    assert result.category == expected_category


def test_fixture_validation_rejects_oversized_file(tmp_path: Path) -> None:
    script = _script()
    fixture = _valid_fixture(tmp_path)
    fixture.write_bytes(b"R" * (script.MAX_FIXTURE_BYTES + 1))

    result = script.validate_fixed_fixture(
        fixture,
        approved_directory=fixture.parent,
    )

    assert result.ok is False
    assert result.category == "fixture_invalid"


def test_fixture_validation_rejects_trailing_bytes(tmp_path: Path) -> None:
    script = _script()
    fixture = _valid_fixture(tmp_path)
    fixture.write_bytes(fixture.read_bytes() + b"unexpected")

    result = script.validate_fixed_fixture(
        fixture,
        approved_directory=fixture.parent,
    )

    assert result.ok is False
    assert result.category == "fixture_invalid"


def test_live_readiness_reports_missing_setting_names_only() -> None:
    script = _script()
    readiness = script.build_live_readiness(
        _settings(
            azure_speech_endpoint=None,
            azure_speech_region=None,
            azure_speech_key=None,
        ),
        sdk_available=True,
    )

    assert readiness.category == "configuration_invalid"
    assert readiness.missing_settings == (
        "AZURE_SPEECH_ENDPOINT",
        "AZURE_SPEECH_KEY",
        "AZURE_SPEECH_REGION",
    )
    assert PRIVATE_MARKER not in repr(readiness)


def test_live_mode_rejects_mock_before_service_construction(tmp_path: Path) -> None:
    script = _script()
    fixture = script.validate_fixed_fixture(
        _valid_fixture(tmp_path),
        approved_directory=tmp_path / "fixtures",
    )

    result = script.run_live_validation(
        _settings(speech_provider="mock", speech_provider_normalized="mock"),
        fixture,
        sdk_available=True,
        service_factory=lambda settings: pytest.fail(
            "mock must fail before service construction"
        ),
    )

    assert result.category == "provider_not_selected"
    assert result.transcription_attempted is False
    assert result.azure_call_made is False


def test_live_success_uses_injected_service_once_and_matches_transcript(
    tmp_path: Path,
) -> None:
    script = _script()
    adapter = FakeAdapter(AzureSpeechRecognition("recognized", EXPECTED_TEXT))

    result = _run_live(script, tmp_path, _service(adapter))

    assert result.ok is True
    assert result.category == "success"
    assert result.adapter_constructed is True
    assert result.transcription_attempted is True
    assert result.azure_call_made is True
    assert result.transcript_valid is True
    assert result.transcript_matches_expected is True
    assert adapter.recognition_calls == 1
    assert adapter.close_calls == 1
    assert len(adapter.audio_requests) == 1
    payload = result.to_json_dict()
    assert EXPECTED_TEXT not in json.dumps(payload)
    assert all(
        payload[field] is False
        for field in (
            "route_invoked",
            "persistence_attempted",
            "notification_attempted",
            "azure_mutation_made",
        )
    )


def test_transcript_normalization_is_narrow_and_deterministic() -> None:
    script = _script()

    assert script.normalize_transcript("  THIS   is a test!!! ") == "this is a test"
    assert script.normalize_transcript("this-is a test") != "this is a test"


@pytest.mark.parametrize(
    ("recognized_text", "expected_category"),
    [
        ("   ", "transcript_empty"),
        ("A different fictional sentence.", "transcript_mismatch"),
    ],
)
def test_live_fails_for_empty_or_mismatched_transcript_after_cleanup(
    tmp_path: Path,
    recognized_text: str,
    expected_category: str,
) -> None:
    script = _script()
    adapter = FakeAdapter(AzureSpeechRecognition("recognized", recognized_text))

    result = _run_live(script, tmp_path, _service(adapter))

    assert result.ok is False
    assert result.category == expected_category
    assert result.transcription_attempted is True
    assert adapter.recognition_calls == 1
    assert adapter.close_calls == 1


@pytest.mark.parametrize(
    ("recognition", "expected_category"),
    [
        (AzureSpeechRecognition("no_match"), "recognition_no_match"),
        (AzureSpeechRecognition("canceled"), "recognition_canceled"),
        (object(), "recognition_failed"),
    ],
)
def test_live_maps_application_failures_and_cleans_up(
    tmp_path: Path,
    recognition: object,
    expected_category: str,
) -> None:
    script = _script()
    adapter = FakeAdapter(recognition)

    result = _run_live(script, tmp_path, _service(adapter))

    assert result.category == expected_category
    assert adapter.recognition_calls == 1
    assert adapter.close_calls == 1


def test_live_sanitizes_recognition_exception_and_output(tmp_path: Path) -> None:
    script = _script()
    adapter = FakeAdapter(error=RuntimeError(PRIVATE_MARKER))

    result = _run_live(script, tmp_path, _service(adapter))
    serialized = json.dumps(result.to_json_dict())

    assert result.category == "recognition_failed"
    assert PRIVATE_MARKER not in serialized
    assert EXPECTED_TEXT not in serialized
    assert str(tmp_path) not in serialized


def test_cleanup_failure_does_not_mask_success_or_primary_failure(
    tmp_path: Path,
) -> None:
    script = _script()
    successful_adapter = FakeAdapter(
        AzureSpeechRecognition("recognized", EXPECTED_TEXT),
        close_error=RuntimeError(PRIVATE_MARKER),
    )
    failed_adapter = FakeAdapter(
        AzureSpeechRecognition("no_match"),
        close_error=RuntimeError(PRIVATE_MARKER),
    )

    success = _run_live(script, tmp_path / "success", _service(successful_adapter))
    failure = _run_live(script, tmp_path / "failure", _service(failed_adapter))

    assert success.category == "success"
    assert failure.category == "recognition_no_match"
    assert successful_adapter.close_calls == 1
    assert failed_adapter.close_calls == 1


def test_production_factory_passes_subscription_key_lazily() -> None:
    calls: list[tuple[str, str, str | None]] = []
    adapter = FakeAdapter(AzureSpeechRecognition("recognized", EXPECTED_TEXT))

    def adapter_factory(
        endpoint: str,
        region: str,
        subscription_key: str | None = None,
    ) -> FakeAdapter:
        calls.append((endpoint, region, subscription_key))
        return adapter

    service = create_speech_transcription_service(
        _settings(),
        azure_adapter_factory=adapter_factory,
    )

    assert calls == []
    service.transcribe_audio(b"fictional-pcm")
    assert calls == [
        (
            "https://private-speech.example.invalid",
            "private-region",
            "secret-key",
        )
    ]


def test_partial_sdk_construction_failure_cleans_owned_resources() -> None:
    adapter_module = importlib.import_module(
        "src.app.services.azure_speech_transcription_adapter"
    )

    class Resource:
        def __init__(self) -> None:
            self.close_calls = 0

        def close(self) -> None:
            self.close_calls += 1

    speech_config = Resource()
    input_stream = Resource()
    sdk = SimpleNamespace(
        SpeechConfig=lambda **kwargs: speech_config,
        audio=SimpleNamespace(
            PushAudioInputStream=lambda: input_stream,
            AudioConfig=lambda **kwargs: (_ for _ in ()).throw(
                RuntimeError(PRIVATE_MARKER)
            ),
        ),
    )
    adapter = adapter_module.AzureSpeechSdkAdapter(
        endpoint="https://private-speech.example.invalid",
        region="private-region",
        subscription_key="secret-key",
        sdk_loader=lambda: sdk,
    )

    with pytest.raises(adapter_module.AzureSpeechAdapterDependencyError):
        adapter.recognize_once(b"fictional-pcm")

    assert speech_config.close_calls == 1
    assert input_stream.close_calls == 1


def test_json_result_never_contains_private_values_or_transcripts() -> None:
    script = _script()
    result = script.AzureSpeechSmokeResult(
        ok=False,
        category="recognition_failed",
        mode="live",
        fixture_valid=True,
        fictional_audio=True,
        sdk_available=True,
        provider="azure",
        adapter_constructed=True,
        transcription_attempted=True,
        azure_call_made=True,
    )

    serialized = json.dumps(result.to_json_dict(), sort_keys=True)

    assert PRIVATE_MARKER not in serialized
    assert EXPECTED_TEXT not in serialized
    assert "/" not in serialized
