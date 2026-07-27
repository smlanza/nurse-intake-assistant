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
from src.app.services.hosted_foundry_agent_webjob_handoff import (
    FileHostedFoundryAgentWebJobHandoffStore,
    HostedFoundryAgentWebJobHandoffRequest,
    RepositoryEnvironmentGenerationEvidenceReader,
    prepare_hosted_foundry_agent_webjob_handoff,
)


class SubprocessAzureCliRunner:
    def run(self, args: list[str]):
        from src.app.services.foundry_agent_consumer_rbac_verification import (
            CommandResult,
        )

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
            "Prepare one private environment-generation handoff for the "
            "standalone hosted Foundry Agent WebJob workflow."
        )
    )
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--check", action="store_true")
    modes.add_argument("--live", action="store_true")
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


def _create_handoff_store():
    return FileHostedFoundryAgentWebJobHandoffStore(ROOT)


def _failure(mode: str) -> dict[str, object]:
    return {
        "ok": False,
        "category": "readiness_receipt_invalid",
        "operation": "prepare_hosted_foundry_agent_webjob_handoff",
        "mode": mode,
        "local_contract_validated": True,
        "readiness_receipt_validated": False,
        "evidence_read_attempted": False,
        "generation_evidence_validated": False,
        "handoff_persisted": False,
        "handoff_reused": False,
        "azure_read_attempted": False,
        "webjob_operation_attempted": False,
        "recommended_next_step": (
            "Stop and obtain a current successful daily readiness receipt."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    mode = "check" if args.check else "live"
    if mode == "check":
        request = HostedFoundryAgentWebJobHandoffRequest(
            mode="check",
            source_root=ROOT,
            resource_group="offline-check-rg",
            web_app_name="offline-check-app",
        )
        result = prepare_hosted_foundry_agent_webjob_handoff(
            request,
            readiness_receipt=None,
            evidence_reader=lambda: None,
            handoff_store=_create_handoff_store(),
        )
        payload = result.to_json_dict()
        print(json.dumps(payload, separators=(",", ":"), sort_keys=True))
        return 0 if result.ok else 2
    try:
        config = load_daily_azure_config(args.config, repository_root=ROOT)
    except ConfigValidationError:
        print(json.dumps(_failure(mode), separators=(",", ":"), sort_keys=True))
        return 2
    receipt = load_matching_daily_azure_readiness_receipt(
        args.readiness_receipt,
        config,
    )
    if receipt is None:
        print(json.dumps(_failure(mode), separators=(",", ":"), sort_keys=True))
        return 2
    request = HostedFoundryAgentWebJobHandoffRequest(
        mode="live",
        source_root=ROOT,
        resource_group=config.resource_group,
        web_app_name=config.web_app_name,
    )
    result = prepare_hosted_foundry_agent_webjob_handoff(
        request,
        readiness_receipt=receipt,
        evidence_reader=_create_evidence_reader(config, receipt),
        handoff_store=_create_handoff_store(),
    )
    print(
        json.dumps(
            result.to_json_dict(),
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0 if result.ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
