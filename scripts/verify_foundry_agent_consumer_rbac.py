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
    parser.add_argument("--resource-group", required=True)
    parser.add_argument("--web-app-name", required=True)
    parser.add_argument("--foundry-account-name", required=True)
    parser.add_argument("--foundry-project-name", required=True)
    parser.add_argument("--json", action="store_true", required=True)
    return parser.parse_args(argv)


def _request(args: argparse.Namespace) -> FoundryAgentConsumerRbacVerificationRequest:
    return FoundryAgentConsumerRbacVerificationRequest(
        mode="check" if args.check else "live",
        resource_group=args.resource_group,
        web_app_name=args.web_app_name,
        foundry_account_name=args.foundry_account_name,
        foundry_project_name=args.foundry_project_name,
    )


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    request = _request(args)
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
    print(json.dumps(result.to_json_dict(), separators=(",", ":"), sort_keys=True))
    return 0 if result.ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
