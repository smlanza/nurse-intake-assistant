import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.app.config.settings import AppSettings
from src.app.services.foundry_agent_deployment import (
    FoundryAgentDeployment,
    FoundryAgentDeploymentRequest,
    FoundryAgentDeploymentResult,
    foundry_agent_deployment_sdk_available,
)
from src.app.services.nurse_intake_agent_instructions import (
    NURSE_INTAKE_AGENT_INSTRUCTION_VERSION,
    build_nurse_intake_agent_instructions,
)


FOUNDRY_AGENT_PROVIDER_VALUES = {"foundry", "foundry-agent"}


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.env_file is not None and not _load_env_file(args.env_file):
        return 2

    settings = AppSettings()
    missing = _missing_configuration(settings)

    if args.check:
        sdk_available = foundry_agent_deployment_sdk_available()
        ready = not missing and sdk_available
        print(
            json.dumps(
                {
                    "ready": ready,
                    "mode": "check",
                    "operation": "check_agent_deployment_readiness",
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
                    "agent_created": False,
                    "agent_reused": False,
                    "agent_updated": False,
                    "agent_invoked": False,
                    "recommended_next_step": (
                        "Run --live --json when ready. Provisioning does not invoke the agent."
                        if ready
                        else "Install the optional SDK and check required settings."
                    ),
                },
                sort_keys=True,
            )
        )
        return 0 if ready else 2

    if missing:
        result = FoundryAgentDeploymentResult.failure("missing_configuration")
        print(json.dumps(result.to_json_dict(), sort_keys=True))
        return 2

    request = FoundryAgentDeploymentRequest(
        project_endpoint=settings.azure_ai_foundry_agent_project_endpoint,
        agent_name=settings.azure_ai_foundry_agent_name,
        model_deployment_name=settings.azure_ai_foundry_model_deployment_name,
        instructions=build_nurse_intake_agent_instructions(),
        managed_identity_client_id=getattr(
            settings,
            "azure_ai_foundry_managed_identity_client_id",
            None,
        ),
    )
    result = _create_deployment_service().provision(request)
    print(json.dumps(result.to_json_dict(), sort_keys=True))
    return 0 if result.ok else 1


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Explicitly create, update, or reuse the Microsoft Foundry prompt "
            "agent without invoking it."
        )
    )
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument(
        "--check",
        action="store_true",
        help="Check settings and SDK visibility offline; creates no clients or resources.",
    )
    modes.add_argument(
        "--live",
        action="store_true",
        help=(
            "Create, update, or reuse the Foundry prompt agent without invoking "
            "it; may make Azure management calls."
        ),
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
    for attribute, setting_name in (
        (
            "azure_ai_foundry_agent_project_endpoint",
            "AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT",
        ),
        ("azure_ai_foundry_agent_name", "AZURE_AI_FOUNDRY_AGENT_NAME"),
        (
            "azure_ai_foundry_model_deployment_name",
            "AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT_NAME",
        ),
    ):
        if not getattr(settings, attribute, None):
            missing.append(setting_name)
    return missing


def _create_deployment_service() -> FoundryAgentDeployment:
    return FoundryAgentDeployment()


def _load_env_file(path_value: str) -> bool:
    from dotenv import dotenv_values
    import os

    path = Path(path_value)
    if not path.is_file():
        print(
            json.dumps(
                {
                    "ok": False,
                    "category": "missing_configuration",
                    "recommended_next_step": "Check the environment file path.",
                },
                sort_keys=True,
            )
        )
        return False
    for key, value in dotenv_values(path).items():
        if value is not None:
            os.environ.setdefault(key, value)
    return True


if __name__ == "__main__":
    raise SystemExit(main())
