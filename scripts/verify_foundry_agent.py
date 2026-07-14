import argparse
import json
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.app.config.settings import AppSettings
from src.app.services.foundry_agent_verification import (
    FoundryAgentVerification,
    FoundryAgentVerificationResult,
    build_foundry_agent_verification_request,
    foundry_agent_verification_sdk_available,
)
from src.app.services.nurse_intake_agent_instructions import (
    NURSE_INTAKE_AGENT_INSTRUCTION_VERSION,
)
from src.app.services.nurse_intake_agent_preflight import (
    missing_foundry_agent_invocation_settings,
)


FOUNDRY_AGENT_PROVIDER_VALUES = {"foundry", "foundry-agent"}
CHECK_NEXT_STEP = (
    "Run --live --json to verify the configured immutable agent version without "
    "invoking it."
)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.env_file is not None and not _load_env_file(args.env_file):
        return 2

    settings = AppSettings()
    missing = _missing_configuration(settings)

    if args.check:
        sdk_available = foundry_agent_verification_sdk_available()
        ready = not missing and sdk_available
        _print_json(
            {
                "ready": ready,
                "mode": "check",
                "operation": "check_agent_verification_readiness",
                "category": (
                    "success"
                    if ready
                    else "missing_configuration"
                    if missing
                    else "sdk_unavailable"
                ),
                "instruction_version": NURSE_INTAKE_AGENT_INSTRUCTION_VERSION,
                "required_settings_missing": missing,
                "sdk_available": sdk_available,
                "azure_call_made": False,
                "azure_mutation_made": False,
                "agent_invoked": False,
                "recommended_next_step": (
                    CHECK_NEXT_STEP
                    if ready
                    else "Install the optional SDK and check required settings."
                ),
            }
        )
        return 0 if ready else 2

    if missing:
        _print_json(
            FoundryAgentVerificationResult.failure(
                "missing_configuration"
            ).to_json_dict()
        )
        return 2

    request = build_foundry_agent_verification_request(settings)
    result = _create_verification_service().verify(request)
    _print_json(result.to_json_dict())
    return 0 if result.ok else 1


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Verify one configured Microsoft Foundry prompt-agent version without "
            "creating, updating, or invoking it."
        )
    )
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument(
        "--check",
        action="store_true",
        help="Check settings and SDK visibility offline without creating a client.",
    )
    modes.add_argument(
        "--live",
        action="store_true",
        help="Read and verify the configured immutable agent version in Foundry.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print exactly one sanitized JSON result; required with --live.",
    )
    parser.add_argument(
        "--env-file",
        help="Load KEY=value settings for this process; existing environment wins.",
    )
    args = parser.parse_args(argv)
    if args.live and not args.json:
        parser.error("--live requires --json")
    return args


def _missing_configuration(settings: object) -> list[str]:
    missing: list[str] = []
    if getattr(settings, "agent_provider_normalized", "") not in (
        FOUNDRY_AGENT_PROVIDER_VALUES
    ):
        missing.append("AGENT_PROVIDER")
    missing.extend(missing_foundry_agent_invocation_settings(settings))
    if not getattr(settings, "azure_ai_foundry_model_deployment_name", None):
        missing.append("AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT_NAME")
    return missing


def _create_verification_service() -> FoundryAgentVerification:
    return FoundryAgentVerification()


def _load_env_file(path_value: str) -> bool:
    from dotenv import dotenv_values

    path = Path(path_value)
    if not path.is_file():
        _print_json(
            FoundryAgentVerificationResult.failure(
                "missing_configuration"
            ).to_json_dict()
        )
        return False
    for key, value in dotenv_values(path).items():
        if value is not None:
            os.environ.setdefault(key, value)
    return True


def _print_json(payload: dict[str, object]) -> None:
    print(json.dumps(payload, separators=(",", ":"), sort_keys=True))


if __name__ == "__main__":
    raise SystemExit(main())
