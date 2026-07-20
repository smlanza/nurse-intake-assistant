import argparse
import json
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.app.config.settings import AppSettings
from src.app.services.foundry_agent_endpoint_routing import (
    FoundryAgentEndpointRouting,
    FoundryAgentEndpointRoutingRequest,
    FoundryAgentEndpointRoutingResult,
)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.env_file is not None and not _load_env_file(args.env_file):
        _print_result(
            FoundryAgentEndpointRoutingResult.failure(
                "missing_configuration",
                mode="check" if args.check else "live",
            )
        )
        return 2

    settings = AppSettings()
    if _missing_configuration(settings):
        _print_result(
            FoundryAgentEndpointRoutingResult.failure(
                "missing_configuration",
                mode="check" if args.check else "live",
            )
        )
        return 2

    request = FoundryAgentEndpointRoutingRequest(
        project_endpoint=settings.azure_ai_foundry_agent_project_endpoint,
        stable_agent_endpoint=settings.azure_ai_foundry_agent_endpoint,
        agent_name=settings.azure_ai_foundry_agent_name,
        agent_version=settings.azure_ai_foundry_agent_version,
        managed_identity_client_id=getattr(
            settings,
            "azure_ai_foundry_managed_identity_client_id",
            None,
        ),
    )
    service = _create_routing_service()
    result = service.check(request) if args.check else service.configure(request)
    _print_result(result)
    if result.ok:
        return 0
    if result.category in {
        "missing_configuration",
        "endpoint_mismatch",
        "sdk_unavailable",
    }:
        return 2
    return 1


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Offline-check or explicitly configure one existing Foundry prompt-agent "
            "endpoint for exclusive immutable-version routing without invocation."
        )
    )
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--check", action="store_true")
    modes.add_argument("--live", action="store_true")
    parser.add_argument("--json", action="store_true")
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
    for attribute, setting_name in (
        (
            "azure_ai_foundry_agent_project_endpoint",
            "AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT",
        ),
        (
            "azure_ai_foundry_agent_endpoint",
            "AZURE_AI_FOUNDRY_AGENT_ENDPOINT",
        ),
        ("azure_ai_foundry_agent_name", "AZURE_AI_FOUNDRY_AGENT_NAME"),
        (
            "azure_ai_foundry_agent_version",
            "AZURE_AI_FOUNDRY_AGENT_VERSION",
        ),
    ):
        if not getattr(settings, attribute, None):
            missing.append(setting_name)
    return missing


def _load_env_file(path_value: str) -> bool:
    from dotenv import dotenv_values

    path = Path(path_value)
    if not path.is_file():
        return False
    for key, value in dotenv_values(path).items():
        if value is not None:
            os.environ.setdefault(key, value)
    return True


def _create_routing_service() -> FoundryAgentEndpointRouting:
    return FoundryAgentEndpointRouting()


def _print_result(result: FoundryAgentEndpointRoutingResult) -> None:
    print(json.dumps(result.to_json_dict(), separators=(",", ":"), sort_keys=True))


if __name__ == "__main__":
    raise SystemExit(main())
