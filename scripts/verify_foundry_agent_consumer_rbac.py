import argparse
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.app.services.foundry_agent_consumer_rbac_verification import (
    CommandResult,
    FoundryAgentConsumerRbacVerificationRequest,
    validate_foundry_agent_consumer_rbac_verification_request,
    verify_foundry_agent_consumer_rbac,
)
from src.app.services.daily_azure_environment_rebuild import (
    READINESS_RECEIPT_FILE,
    ConfigValidationError,
    load_daily_azure_config,
    load_matching_daily_azure_readiness_receipt,
)


class SubprocessAzureCliRunner:
    def run(self, args: list[str]) -> CommandResult:
        try:
            completed = subprocess.run(
                args,
                shell=False,
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            return CommandResult(127, "", "")
        return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def _create_azure_cli_runner() -> SubprocessAzureCliRunner:
    return SubprocessAzureCliRunner()


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Offline-check or explicitly run read-only verification of the existing "
            "project-scoped Foundry Agent Consumer assignment."
        )
    )
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--check", action="store_true")
    modes.add_argument("--live", action="store_true")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument(
        "--readiness-receipt",
        type=Path,
        default=ROOT / READINESS_RECEIPT_FILE,
    )
    parser.add_argument("--json", action="store_true", required=True)
    return parser.parse_args(argv)


def _request(
    args: argparse.Namespace,
    *,
    resource_group: str,
    web_app_name: str,
    foundry_account_name: str,
    foundry_project_name: str,
) -> FoundryAgentConsumerRbacVerificationRequest:
    return FoundryAgentConsumerRbacVerificationRequest(
        mode="check" if args.check else "live",
        resource_group=resource_group,
        web_app_name=web_app_name,
        foundry_account_name=foundry_account_name,
        foundry_project_name=foundry_project_name,
    )


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    mode = "check" if args.check else "live"
    try:
        config = load_daily_azure_config(args.config, repository_root=ROOT)
    except ConfigValidationError:
        print(
            json.dumps(
                {
                    "ok": False,
                    "category": "invalid_configuration",
                    "operation": "verify_foundry_agent_consumer_rbac",
                    "mode": mode,
                    "rbac_handoff_validated": False,
                    "azure_request_attempted": False,
                },
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        return 2
    receipt = load_matching_daily_azure_readiness_receipt(
        args.readiness_receipt,
        config,
    )
    if receipt is None:
        print(
            json.dumps(
                {
                    "ok": False,
                    "category": "rbac_handoff_invalid",
                    "operation": "verify_foundry_agent_consumer_rbac",
                    "mode": mode,
                    "rbac_handoff_validated": False,
                    "azure_request_attempted": False,
                },
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        return 2
    request = _request(
        args,
        resource_group=receipt.resource_group,
        web_app_name=receipt.web_app_name,
        foundry_account_name=receipt.foundry_account_name,
        foundry_project_name=receipt.foundry_project_name,
    )
    invalid = validate_foundry_agent_consumer_rbac_verification_request(request)
    if invalid is not None:
        result = invalid
    elif request.mode == "check":
        result = verify_foundry_agent_consumer_rbac(request)
    else:
        result = verify_foundry_agent_consumer_rbac(
            request,
            runner=_create_azure_cli_runner(),
        )
    payload = result.to_json_dict()
    payload.update(
        {
            "rbac_handoff_validated": True,
            "requested_foundry_account_name": (
                receipt.requested_foundry_account_name
            ),
            "foundry_account_name": receipt.foundry_account_name,
        }
    )
    print(json.dumps(payload, separators=(",", ":"), sort_keys=True))
    return 0 if result.ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
