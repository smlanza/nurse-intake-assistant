import argparse
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.app.services.hosted_foundry_agent_webjob_execution import (
    AzureCliProcessNotStarted,
    CommandResult,
    HostedFoundryAgentWebJobExecutionRequest,
    execute_hosted_foundry_agent_webjob,
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
        except OSError as error:
            raise AzureCliProcessNotStarted() from error
        return CommandResult(
            completed.returncode,
            completed.stdout,
            completed.stderr,
        )


def _create_azure_cli_runner() -> SubprocessAzureCliRunner:
    return SubprocessAzureCliRunner()


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Check, discover, trigger, or read one receipt-correlated status "
            "for the fixed hosted Foundry metadata-verification WebJob."
        )
    )
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--check", action="store_true")
    modes.add_argument("--live-discover", action="store_true")
    modes.add_argument("--live-trigger", action="store_true")
    modes.add_argument("--live-status", action="store_true")
    parser.add_argument("--resource-group", required=True)
    parser.add_argument("--web-app-name", required=True)
    parser.add_argument("--json", action="store_true", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    mode = (
        "check"
        if args.check
        else "live-discover"
        if args.live_discover
        else "live-trigger"
        if args.live_trigger
        else "live-status"
    )
    request = HostedFoundryAgentWebJobExecutionRequest(
        mode=mode,
        resource_group=args.resource_group,
        web_app_name=args.web_app_name,
        source_root=ROOT,
    )
    if mode == "check":
        result = execute_hosted_foundry_agent_webjob(request)
    else:
        result = execute_hosted_foundry_agent_webjob(
            request,
            runner_factory=_create_azure_cli_runner,
        )
    print(json.dumps(result.to_json_dict(), separators=(",", ":"), sort_keys=True))
    return 0 if result.ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
