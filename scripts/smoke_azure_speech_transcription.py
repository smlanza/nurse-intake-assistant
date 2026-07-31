import argparse
from contextlib import contextmanager
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import sys
from typing import Callable, Iterator, Literal
import wave


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.smoke_speech_transcription import azure_speech_sdk_available
from src.app.config.settings import AppSettings
from src.app.services.speech_transcription_factory import (
    create_speech_transcription_service,
)
from src.app.services.speech_transcription_service import (
    SpeechTranscriptionError,
    TranscriptionResult,
)


OPERATION = "smoke_azure_speech_transcription"
FIXTURE_DIRECTORY = PROJECT_ROOT / "tests" / "fixtures"
FIXTURE_FILENAME = "fictional_speech_intake.wav"
FIXTURE_PATH = FIXTURE_DIRECTORY / FIXTURE_FILENAME
FIXED_EXPECTED_TRANSCRIPT = (
    "This is a fictional nurse intake test for Jordan Lee."
)
MAX_FIXTURE_BYTES = 256 * 1024
MIN_FIXTURE_BYTES = 45
REQUIRED_SETTING_NAMES = (
    "AZURE_SPEECH_ENDPOINT",
    "AZURE_SPEECH_KEY",
    "AZURE_SPEECH_REGION",
)
CONFIG_SETTING_NAMES = ("SPEECH_PROVIDER", *REQUIRED_SETTING_NAMES)

SmokeMode = Literal["check", "live"]
SmokeCategory = Literal[
    "check_passed",
    "success",
    "invalid_arguments",
    "configuration_invalid",
    "fixture_invalid",
    "provider_not_selected",
    "sdk_unavailable",
    "dependency_construction_failed",
    "recognition_no_match",
    "recognition_canceled",
    "recognition_failed",
    "transcript_empty",
    "transcript_mismatch",
    "unexpected_error",
]


@dataclass(frozen=True)
class FixtureValidation:
    ok: bool
    category: Literal["success", "fixture_invalid"]
    audio_bytes: bytes | None = None


@dataclass(frozen=True)
class LiveReadiness:
    ready: bool
    category: SmokeCategory
    missing_settings: tuple[str, ...] = ()


@dataclass(frozen=True)
class AzureSpeechSmokeResult:
    ok: bool
    category: SmokeCategory
    mode: SmokeMode
    fixture_valid: bool = False
    fictional_audio: bool = True
    sdk_available: bool = False
    provider: str = "azure"
    adapter_constructed: bool = False
    transcription_attempted: bool = False
    transcript_valid: bool = False
    transcript_matches_expected: bool = False
    route_invoked: bool = False
    persistence_attempted: bool = False
    notification_attempted: bool = False
    azure_call_made: bool = False
    azure_mutation_made: bool = False
    missing_settings: tuple[str, ...] = ()

    def to_json_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["operation"] = OPERATION
        return payload


class InvalidArgumentsError(Exception):
    pass


class SmokeConfigurationError(Exception):
    def __init__(self, category: SmokeCategory = "configuration_invalid") -> None:
        super().__init__("Azure Speech smoke configuration is invalid.")
        self.category = category


class SanitizedArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise InvalidArgumentsError from None


def main(argv: list[str] | None = None) -> int:
    raw_arguments = list(sys.argv[1:] if argv is None else argv)
    json_requested = "--json" in raw_arguments
    requested_mode: SmokeMode = "live" if "--live" in raw_arguments else "check"
    try:
        try:
            arguments = parse_arguments(raw_arguments)
        except InvalidArgumentsError:
            result = _empty_result("invalid_arguments", requested_mode)
            _emit_result(result, json_requested)
            return 2

        fixture = validate_fixed_fixture(
            FIXTURE_PATH,
            approved_directory=FIXTURE_DIRECTORY,
        )
        sdk_available = azure_speech_sdk_available()

        if arguments.check:
            result = run_check_validation(
                fixture,
                sdk_available=sdk_available,
                config_path=arguments.config,
            )
            _emit_result(result, arguments.json)
            return 0 if result.ok else 2

        try:
            settings = load_speech_settings(arguments.config)
        except SmokeConfigurationError as error:
            result = _result(
                error.category,
                "live",
                fixture_valid=fixture.ok,
                sdk_available=sdk_available,
            )
            _emit_result(result, True)
            return 2

        result = run_live_validation(
            settings,
            fixture,
            sdk_available=sdk_available,
        )
        _emit_result(result, True)
        if result.ok:
            return 0
        if result.category in {
            "configuration_invalid",
            "fixture_invalid",
            "provider_not_selected",
            "sdk_unavailable",
        }:
            return 2
        return 1
    except Exception:
        result = _empty_result("unexpected_error", requested_mode)
        _emit_result(result, json_requested)
        return 1


def parse_arguments(argv: list[str]) -> argparse.Namespace:
    parser = SanitizedArgumentParser(
        description=(
            "Validate or run one fixed-fictional Azure Speech transcription proof."
        )
    )
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument(
        "--check",
        action="store_true",
        help="Validate the local fixture and smoke contract without recognition.",
    )
    modes.add_argument(
        "--live",
        action="store_true",
        help="Perform exactly one fixed-fictional Azure Speech recognition.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        help="Path to the ignored .env.speech.local configuration.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit one sanitized JSON document.",
    )
    arguments = parser.parse_args(argv)
    if arguments.live and (arguments.config is None or not arguments.json):
        parser.error("invalid live argument combination")
    return arguments


def validate_fixed_fixture(
    path: Path,
    *,
    approved_directory: Path = FIXTURE_DIRECTORY,
) -> FixtureValidation:
    try:
        if path.name != FIXTURE_FILENAME or path.is_symlink():
            return FixtureValidation(False, "fixture_invalid")
        approved = approved_directory.resolve(strict=True)
        resolved = path.resolve(strict=True)
        resolved.relative_to(approved)
        if not resolved.is_file():
            return FixtureValidation(False, "fixture_invalid")

        data = resolved.read_bytes()
        if not MIN_FIXTURE_BYTES <= len(data) <= MAX_FIXTURE_BYTES:
            return FixtureValidation(False, "fixture_invalid")
        if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
            return FixtureValidation(False, "fixture_invalid")
        declared_size = int.from_bytes(data[4:8], "little") + 8
        if declared_size != len(data):
            return FixtureValidation(False, "fixture_invalid")

        with wave.open(str(resolved), "rb") as fixture:
            if (
                fixture.getcomptype() != "NONE"
                or fixture.getnchannels() != 1
                or fixture.getsampwidth() != 2
                or fixture.getframerate() != 16_000
                or fixture.getnframes() <= 0
            ):
                return FixtureValidation(False, "fixture_invalid")
            frame_count = fixture.getnframes()
            audio_bytes = fixture.readframes(frame_count)
        if len(audio_bytes) != frame_count * 2:
            return FixtureValidation(False, "fixture_invalid")
    except (OSError, ValueError, wave.Error):
        return FixtureValidation(False, "fixture_invalid")

    return FixtureValidation(True, "success", audio_bytes)


def run_check_validation(
    fixture: FixtureValidation,
    *,
    sdk_available: bool,
    config_path: Path | None = None,
) -> AzureSpeechSmokeResult:
    if not fixture.ok or not _fixed_expected_transcript_valid():
        return _result(
            "fixture_invalid",
            "check",
            fixture_valid=False,
            sdk_available=sdk_available,
        )
    if not _production_contract_compatible():
        return _result(
            "unexpected_error",
            "check",
            fixture_valid=True,
            sdk_available=sdk_available,
        )
    if not sdk_available:
        return _result(
            "sdk_unavailable",
            "check",
            fixture_valid=True,
            sdk_available=False,
        )

    missing_settings: tuple[str, ...] = ()
    if config_path is not None:
        try:
            settings = load_speech_settings(config_path)
        except SmokeConfigurationError:
            return _result(
                "configuration_invalid",
                "check",
                fixture_valid=True,
                sdk_available=sdk_available,
            )
        readiness = build_live_readiness(settings, sdk_available=sdk_available)
        if readiness.category not in {"success", "sdk_unavailable"}:
            return _result(
                readiness.category,
                "check",
                fixture_valid=True,
                sdk_available=sdk_available,
                missing_settings=readiness.missing_settings,
                provider=getattr(settings, "speech_provider_normalized", "invalid"),
            )
        missing_settings = readiness.missing_settings

    return AzureSpeechSmokeResult(
        ok=True,
        category="check_passed",
        mode="check",
        fixture_valid=True,
        fictional_audio=True,
        sdk_available=sdk_available,
        provider="azure",
        missing_settings=missing_settings,
    )


def build_live_readiness(
    settings: object,
    *,
    sdk_available: bool,
) -> LiveReadiness:
    provider = getattr(settings, "speech_provider_normalized", None)
    if provider != "azure":
        return LiveReadiness(False, "provider_not_selected")

    required_attributes = {
        "AZURE_SPEECH_ENDPOINT": "azure_speech_endpoint",
        "AZURE_SPEECH_KEY": "azure_speech_key",
        "AZURE_SPEECH_REGION": "azure_speech_region",
    }
    missing = tuple(
        setting_name
        for setting_name, attribute_name in required_attributes.items()
        if not _nonblank(getattr(settings, attribute_name, None))
    )
    if missing:
        return LiveReadiness(False, "configuration_invalid", missing)
    if not sdk_available:
        return LiveReadiness(False, "sdk_unavailable")
    return LiveReadiness(True, "success")


def run_live_validation(
    settings: object,
    fixture: FixtureValidation,
    *,
    sdk_available: bool,
    service_factory: Callable[[object], object] = create_speech_transcription_service,
) -> AzureSpeechSmokeResult:
    provider = getattr(settings, "speech_provider_normalized", "invalid")
    if not fixture.ok or fixture.audio_bytes is None:
        return _result(
            "fixture_invalid",
            "live",
            fixture_valid=False,
            sdk_available=sdk_available,
            provider=provider,
        )

    readiness = build_live_readiness(settings, sdk_available=sdk_available)
    if not readiness.ready:
        return _result(
            readiness.category,
            "live",
            fixture_valid=True,
            sdk_available=sdk_available,
            provider=provider,
            missing_settings=readiness.missing_settings,
        )

    try:
        service = service_factory(settings)
    except SpeechTranscriptionError as error:
        return _speech_failure_result(
            error.category,
            fixture_valid=True,
            sdk_available=sdk_available,
            transcription_attempted=False,
        )
    except Exception:
        return _result(
            "unexpected_error",
            "live",
            fixture_valid=True,
            sdk_available=sdk_available,
        )

    try:
        transcription = service.transcribe_audio(fixture.audio_bytes)
    except SpeechTranscriptionError as error:
        return _speech_failure_result(
            error.category,
            fixture_valid=True,
            sdk_available=sdk_available,
            transcription_attempted=True,
        )
    except Exception:
        return _result(
            "recognition_failed",
            "live",
            fixture_valid=True,
            sdk_available=sdk_available,
            adapter_constructed=True,
            transcription_attempted=True,
            azure_call_made=True,
        )

    if not isinstance(transcription, TranscriptionResult):
        return _result(
            "recognition_failed",
            "live",
            fixture_valid=True,
            sdk_available=sdk_available,
            adapter_constructed=True,
            transcription_attempted=True,
            azure_call_made=True,
        )
    if not transcription.text.strip():
        return _result(
            "transcript_empty",
            "live",
            fixture_valid=True,
            sdk_available=sdk_available,
            adapter_constructed=True,
            transcription_attempted=True,
            azure_call_made=True,
        )

    matches = normalize_transcript(transcription.text) == normalize_transcript(
        FIXED_EXPECTED_TRANSCRIPT
    )
    return AzureSpeechSmokeResult(
        ok=matches,
        category="success" if matches else "transcript_mismatch",
        mode="live",
        fixture_valid=True,
        fictional_audio=True,
        sdk_available=sdk_available,
        provider="azure",
        adapter_constructed=True,
        transcription_attempted=True,
        transcript_valid=True,
        transcript_matches_expected=matches,
        azure_call_made=True,
    )


def normalize_transcript(value: str) -> str:
    collapsed = " ".join(value.strip().casefold().split())
    return collapsed.rstrip(".!?").rstrip()


def load_speech_settings(config_path: Path) -> AppSettings:
    try:
        if config_path.name != ".env.speech.local" or config_path.is_symlink():
            raise SmokeConfigurationError
        resolved = config_path.resolve(strict=True)
        resolved.relative_to(PROJECT_ROOT.resolve())
        if not resolved.is_file():
            raise SmokeConfigurationError
        values = _parse_config_values(resolved)
    except (OSError, ValueError, SmokeConfigurationError):
        raise SmokeConfigurationError from None

    with _isolated_speech_environment(values):
        return AppSettings()


def _parse_config_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").strip()
        if "=" not in line:
            raise SmokeConfigurationError
        name, value = line.split("=", 1)
        name = name.strip()
        if name not in CONFIG_SETTING_NAMES or name in values:
            raise SmokeConfigurationError
        values[name] = _strip_optional_quotes(value.strip())
    return values


@contextmanager
def _isolated_speech_environment(values: dict[str, str]) -> Iterator[None]:
    original = {name: os.environ.get(name) for name in CONFIG_SETTING_NAMES}
    try:
        for name in CONFIG_SETTING_NAMES:
            os.environ.pop(name, None)
        os.environ.update(values)
        yield
    finally:
        for name, value in original.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _strip_optional_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _speech_failure_result(
    application_category: str,
    *,
    fixture_valid: bool,
    sdk_available: bool,
    transcription_attempted: bool,
) -> AzureSpeechSmokeResult:
    category_map: dict[str, SmokeCategory] = {
        "missing_configuration": "configuration_invalid",
        "invalid_audio": "fixture_invalid",
        "empty_recognized_text": "transcript_empty",
        "no_match": "recognition_no_match",
        "canceled": "recognition_canceled",
        "malformed_response": "recognition_failed",
        "dependency_construction_failed": "dependency_construction_failed",
        "recognition_failed": "recognition_failed",
        "unsupported_request": "recognition_failed",
    }
    category = category_map.get(application_category, "recognition_failed")
    dependency_failed = category == "dependency_construction_failed"
    return _result(
        category,
        "live",
        fixture_valid=fixture_valid,
        sdk_available=sdk_available,
        adapter_constructed=transcription_attempted and not dependency_failed,
        transcription_attempted=transcription_attempted,
        azure_call_made=transcription_attempted and not dependency_failed,
    )


def _result(
    category: SmokeCategory,
    mode: SmokeMode,
    *,
    fixture_valid: bool = False,
    sdk_available: bool = False,
    provider: str = "azure",
    adapter_constructed: bool = False,
    transcription_attempted: bool = False,
    azure_call_made: bool = False,
    missing_settings: tuple[str, ...] = (),
) -> AzureSpeechSmokeResult:
    return AzureSpeechSmokeResult(
        ok=False,
        category=category,
        mode=mode,
        fixture_valid=fixture_valid,
        fictional_audio=True,
        sdk_available=sdk_available,
        provider=provider if provider in {"azure", "mock"} else "invalid",
        adapter_constructed=adapter_constructed,
        transcription_attempted=transcription_attempted,
        azure_call_made=azure_call_made,
        missing_settings=missing_settings,
    )


def _empty_result(
    category: SmokeCategory,
    mode: SmokeMode,
) -> AzureSpeechSmokeResult:
    return _result(category, mode)


def _fixed_expected_transcript_valid() -> bool:
    normalized = FIXED_EXPECTED_TRANSCRIPT.casefold()
    return bool(
        "fictional" in normalized
        and "jordan lee" in normalized
        and "@" not in FIXED_EXPECTED_TRANSCRIPT
        and "+1" not in FIXED_EXPECTED_TRANSCRIPT
        and "555" not in FIXED_EXPECTED_TRANSCRIPT
    )


def _production_contract_compatible() -> bool:
    return bool(
        callable(create_speech_transcription_service)
        and hasattr(
            __import__(
                "src.app.services.speech_transcription_service",
                fromlist=["AzureSpeechTranscriptionService"],
            ).AzureSpeechTranscriptionService,
            "transcribe_audio",
        )
    )


def _nonblank(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _emit_result(result: AzureSpeechSmokeResult, json_output: bool) -> None:
    if json_output:
        print(json.dumps(result.to_json_dict(), separators=(",", ":"), sort_keys=True))
        return
    status = "passed" if result.ok else "failed"
    print(f"Azure Speech smoke {result.mode} {status}: {result.category}.")


if __name__ == "__main__":
    raise SystemExit(main())
