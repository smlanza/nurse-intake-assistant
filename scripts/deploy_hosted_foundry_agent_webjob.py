import argparse
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.app.services.daily_azure_environment_rebuild import (
    ConfigValidationError,
    load_daily_azure_config,
    load_matching_daily_azure_readiness_receipt,
)
from src.app.services.hosted_foundry_agent_webjob_deployment import (
    HostedFoundryAgentWebJobDeploymentRequest,
    KuduTriggeredWebJobUploader,
    WebJobDeploymentApprovalSummary,
    deploy_hosted_foundry_agent_webjob,
)
from src.app.services.hosted_foundry_agent_webjob_execution import (
    CommandResult,
    WEBJOB_NAME,
)
from src.app.services.hosted_foundry_agent_webjob_handoff import (
    RepositoryEnvironmentGenerationEvidenceReader,
    load_hosted_foundry_agent_webjob_handoff,
)
from src.app.services.hosted_foundry_agent_webjob_kudu import (
    KuduTriggeredWebJobDiscoverer,
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


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Deploy only the fixed hosted Foundry Agent triggered WebJob, "
            "then stop after read-only discovery."
        )
    )
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--check", action="store_true")
    modes.add_argument("--live", action="store_true")
    parser.add_argument("--resource-group", required=True)
    parser.add_argument("--web-app-name", required=True)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--readiness-receipt", required=True, type=Path)
    parser.add_argument("--json", action="store_true", required=True)
    return parser.parse_args(argv)


def _create_evidence_reader(config, receipt):
    return RepositoryEnvironmentGenerationEvidenceReader(
        source_root=ROOT,
        config=config,
        readiness_receipt=receipt,
        runner=SubprocessAzureCliRunner(),
    )


def _create_uploader():
    return KuduTriggeredWebJobUploader(
        token_runner=SubprocessAzureCliRunner(),
    )


def _create_discoverer():
    return KuduTriggeredWebJobDiscoverer(
        token_runner=SubprocessAzureCliRunner(),
    )


def _approve(summary: WebJobDeploymentApprovalSummary) -> bool:
    print(summary.heading, file=sys.stderr)
    for name, value in summary.facts:
        print(f"{name}: {value}", file=sys.stderr)
    print("Proceed? [y/N] ", end="", file=sys.stderr, flush=True)
    try:
        response = sys.stdin.readline()
    except (EOFError, KeyboardInterrupt, OSError):
        return False
    return response.strip().lower() in {"y", "yes"}


def _emit(result) -> int:
    print(
        json.dumps(
            result.to_json_dict(),
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0 if result.ok else 2


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    mode = "check" if args.check else "live"
    request = HostedFoundryAgentWebJobDeploymentRequest(
        mode=mode,
        source_root=ROOT,
        resource_group=args.resource_group,
        web_app_name=args.web_app_name,
        webjob_name=WEBJOB_NAME,
    )
    if mode == "check":
        return _emit(
            deploy_hosted_foundry_agent_webjob(
                request,
                readiness_receipt=None,
                generation_handoff=None,
            )
        )
    try:
        config = load_daily_azure_config(
            args.config,
            repository_root=ROOT,
        )
    except ConfigValidationError:
        return _emit(
            deploy_hosted_foundry_agent_webjob(
                request,
                readiness_receipt=None,
                generation_handoff=None,
            )
        )
    if (
        config.resource_group != args.resource_group
        or config.web_app_name != args.web_app_name
    ):
        return _emit(
            deploy_hosted_foundry_agent_webjob(
                request,
                readiness_receipt=None,
                generation_handoff=None,
            )
        )
    receipt = load_matching_daily_azure_readiness_receipt(
        args.readiness_receipt,
        config,
    )
    handoff = (
        load_hosted_foundry_agent_webjob_handoff(
            ROOT,
            receipt,
            resource_group=args.resource_group,
            web_app_name=args.web_app_name,
        )
        if receipt is not None
        else None
    )

    def read_current_binding():
        current_receipt = load_matching_daily_azure_readiness_receipt(
            args.readiness_receipt,
            config,
        )
        current_handoff = (
            load_hosted_foundry_agent_webjob_handoff(
                ROOT,
                current_receipt,
                resource_group=args.resource_group,
                web_app_name=args.web_app_name,
            )
            if current_receipt is not None
            else None
        )
        return current_receipt, current_handoff

    return _emit(
        deploy_hosted_foundry_agent_webjob(
            request,
            readiness_receipt=receipt,
            generation_handoff=handoff,
            evidence_reader=(
                _create_evidence_reader(config, receipt)
                if receipt is not None
                else None
            ),
            current_binding_reader=read_current_binding,
            approver=_approve,
            uploader_factory=_create_uploader,
            discovery_factory=_create_discoverer,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
