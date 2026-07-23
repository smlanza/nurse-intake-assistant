import argparse
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.app.services.foundry_agent_consumer_rbac_deployment import (
    CommandResult,
    DEPLOYMENT_NAME,
    EXPECTED_TEMPLATE,
    FoundryAgentConsumerRbacDeploymentEvidence,
    FoundryAgentConsumerRbacDeploymentRequest,
    deploy_foundry_agent_consumer_rbac,
    validate_foundry_agent_consumer_rbac_request,
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
            "Check, preview, or explicitly request the existing project-scoped "
            "Foundry Agent Consumer RBAC deployment."
        )
    )
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--check", action="store_true")
    modes.add_argument("--what-if", action="store_true")
    modes.add_argument("--live", action="store_true")
    parser.add_argument("--resource-group", required=True)
    parser.add_argument("--web-app-name", required=True)
    parser.add_argument("--foundry-account-name", required=True)
    parser.add_argument("--foundry-project-name", required=True)
    parser.add_argument("--subscription-id")
    parser.add_argument("--approved-foundry-project-resource-id")
    parser.add_argument("--approved-web-app-principal-id")
    parser.add_argument("--approved-role-assignment-name")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def _request(args: argparse.Namespace) -> FoundryAgentConsumerRbacDeploymentRequest:
    mode = "check" if args.check else "what-if" if args.what_if else "live"
    evidence = None
    if mode != "check" and all(
        isinstance(value, str)
        for value in (
            args.subscription_id,
            args.approved_foundry_project_resource_id,
            args.approved_web_app_principal_id,
            args.approved_role_assignment_name,
        )
    ):
        evidence = FoundryAgentConsumerRbacDeploymentEvidence(
            subscription_id=args.subscription_id,
            foundry_project_resource_id=args.approved_foundry_project_resource_id,
            web_app_principal_id=args.approved_web_app_principal_id,
            role_definition_id=(
                f"/subscriptions/{args.subscription_id}/providers/"
                "Microsoft.Authorization/roleDefinitions/"
                "eed3b665-ab3a-47b6-8f48-c9382fb1dad6"
            ),
            role_assignment_name=args.approved_role_assignment_name,
            deployment_name=DEPLOYMENT_NAME,
        )
    return FoundryAgentConsumerRbacDeploymentRequest(
        mode=mode,
        resource_group=args.resource_group,
        web_app_name=args.web_app_name,
        foundry_account_name=args.foundry_account_name,
        foundry_project_name=args.foundry_project_name,
        template_file=EXPECTED_TEMPLATE,
        approved_evidence=evidence,
    )


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    request = _request(args)
    invalid = validate_foundry_agent_consumer_rbac_request(request)
    if invalid is not None:
        result = invalid
    elif request.mode == "check":
        result = deploy_foundry_agent_consumer_rbac(request)
    else:
        result = deploy_foundry_agent_consumer_rbac(
            request,
            runner=_create_azure_cli_runner(),
        )

    if args.json:
        print(json.dumps(result.to_json_dict(), separators=(",", ":"), sort_keys=True))
    else:
        print(result.message)
        if result.ok and result.mode == "what-if":
            print(
                f"Creates: {result.create_count}, modifies: {result.modify_count}, "
                f"deletes: {result.delete_count}, unchanged: {result.no_change_count}, "
                f"ignored: {result.ignore_count}, deploy-uncertain: {result.deploy_count}, "
                f"unsupported: {result.unsupported_count}."
            )
            if result.manual_review_required:
                print(
                    "Manual review is required for Delete, Deploy, or Unsupported "
                    "preview entries; no deployment ran."
                )
    return 0 if result.ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
