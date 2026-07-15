import argparse
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.app.services.web_app_infra_deployment import (
    CommandResult,
    WebAppInfrastructureDeploymentRequest,
    deploy_web_app_infrastructure,
    validate_web_app_infrastructure_request,
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
            "Check, preview, or explicitly deploy the existing Web App infrastructure."
        )
    )
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--check", action="store_true")
    modes.add_argument("--what-if", action="store_true")
    modes.add_argument("--live", action="store_true")
    parser.add_argument("--resource-group", required=True)
    parser.add_argument("--location", required=True)
    parser.add_argument("--environment-name", required=True)
    parser.add_argument("--project-name", required=True)
    parser.add_argument("--web-app-name", required=True)
    parser.add_argument("--cosmos-database-name", default="nurse-intake")
    parser.add_argument("--cosmos-container-name", default="cases")
    parser.add_argument(
        "--template-file",
        type=Path,
        default=ROOT / "infra/main.bicep",
    )
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def _request(args: argparse.Namespace) -> WebAppInfrastructureDeploymentRequest:
    mode = "check" if args.check else "what-if" if args.what_if else "live"
    return WebAppInfrastructureDeploymentRequest(
        mode=mode,
        resource_group=args.resource_group,
        location=args.location,
        environment_name=args.environment_name,
        project_name=args.project_name,
        web_app_name=args.web_app_name,
        cosmos_database_name=args.cosmos_database_name,
        cosmos_container_name=args.cosmos_container_name,
        template_file=args.template_file,
    )


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    request = _request(args)
    invalid = validate_web_app_infrastructure_request(request)
    if invalid is not None:
        result = invalid
    elif request.mode == "check":
        result = deploy_web_app_infrastructure(request)
    else:
        result = deploy_web_app_infrastructure(
            request,
            runner=_create_azure_cli_runner(),
        )

    if args.json:
        print(json.dumps(result.to_json_dict(), separators=(",", ":"), sort_keys=True))
    else:
        print(result.message)
        if result.ok and result.mode == "what-if" and result.what_if_summary_available:
            print(
                f"Creates: {result.create_count}, modifies: {result.modify_count}, "
                f"deletes: {result.delete_count}, unchanged: {result.no_change_count}."
            )
            if result.delete_detected:
                print("Review proposed deletions before any explicit live deployment.")
    return 0 if result.ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
