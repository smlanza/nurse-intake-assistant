import argparse
import json
from pathlib import Path
import sys
from typing import TextIO


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.app.services.hosted_foundry_agent_ssh_transport import (
    HostedFoundryAgentSshTransport,
    HostedFoundryAgentSshTransportApprovals,
    HostedFoundryAgentSshTransportRequest,
    HostedFoundryAgentSshTransportResult,
    build_hosted_foundry_agent_ssh_transport_check_request,
)
from src.app.services.daily_azure_environment_rebuild import (
    READINESS_RECEIPT_FILE,
    ConfigValidationError,
    load_daily_azure_config,
    load_matching_daily_azure_readiness_receipt,
)
from src.app.services.web_app_hosting_contract import HOSTED_SETTING_OPTIONS


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate the owned App Service tunnel contract offline."
    )
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--check", action="store_true")
    modes.add_argument("--live-tunnel", action="store_true")
    modes.add_argument("--live-metadata-verification", action="store_true")
    parser.add_argument("--config", type=Path)
    parser.add_argument(
        "--readiness-receipt",
        type=Path,
        default=PROJECT_ROOT / READINESS_RECEIPT_FILE,
    )
    parser.add_argument("--json", action="store_true", required=True)
    for attribute in HOSTED_SETTING_OPTIONS.values():
        parser.add_argument(
            f"--{attribute.replace('_', '-')}",
            action="append",
        )
    args = parser.parse_args(argv)
    if args.check and args.config is not None:
        parser.error("--config is live-only")
    if args.live_tunnel and args.config is None:
        parser.error("--config is required with --live-tunnel")
    for attribute in HOSTED_SETTING_OPTIONS.values():
        values = getattr(args, attribute)
        if args.live_metadata_verification:
            if values is not None and len(values) > 1:
                parser.error(
                    f"--{attribute.replace('_', '-')} may be supplied at most "
                    "once with retired --live-metadata-verification"
                )
            setattr(args, attribute, values[0] if values else None)
        elif values:
            parser.error(
                "hosted verifier values require --live-metadata-verification"
            )
    return args


def run_check() -> HostedFoundryAgentSshTransportResult:
    return HostedFoundryAgentSshTransport().check(
        build_hosted_foundry_agent_ssh_transport_check_request()
    )


def _retired_metadata_mode_result() -> HostedFoundryAgentSshTransportResult:
    return HostedFoundryAgentSshTransportResult.build(
        ok=False,
        category="ssh_hosted_identity_execution_unsupported",
        mode="live-metadata-verification",
    )


def _prompt(
    summary: str,
    *,
    input_stream: TextIO,
    output_stream: TextIO,
) -> bool:
    output_stream.write(summary + "\n\nProceed? [y/N] ")
    output_stream.flush()
    try:
        return input_stream.readline().strip().casefold() in {"y", "yes"}
    except (EOFError, KeyboardInterrupt, OSError):
        return False


def _create_service() -> HostedFoundryAgentSshTransport:
    return HostedFoundryAgentSshTransport()


def run_live(
    args: argparse.Namespace,
    *,
    input_stream: TextIO,
    output_stream: TextIO,
) -> HostedFoundryAgentSshTransportResult:
    if getattr(args, "live_metadata_verification", False):
        return _retired_metadata_mode_result()
    mode = "live-tunnel"
    try:
        config = load_daily_azure_config(args.config, repository_root=PROJECT_ROOT)
    except ConfigValidationError:
        return HostedFoundryAgentSshTransportResult.build(
            ok=False,
            category="configuration_invalid",
            mode=mode,
        )
    receipt = load_matching_daily_azure_readiness_receipt(
        args.readiness_receipt,
        config,
    )
    if receipt is None:
        return HostedFoundryAgentSshTransportResult.build(
            ok=False,
            category="configuration_invalid",
            mode=mode,
        )
    def evidence_unchanged() -> bool:
        try:
            current_config = load_daily_azure_config(
                args.config,
                repository_root=PROJECT_ROOT,
            )
            current_receipt = load_matching_daily_azure_readiness_receipt(
                args.readiness_receipt,
                current_config,
            )
        except (ConfigValidationError, OSError):
            return False
        return current_config == config and current_receipt == receipt

    def approve(summary: str) -> bool:
        return bool(
            evidence_unchanged()
            and _prompt(
                summary,
                input_stream=input_stream,
                output_stream=output_stream,
            )
            and evidence_unchanged()
        )

    approvals = HostedFoundryAgentSshTransportApprovals(
        approve_tunnel=lambda: approve(
            "Action: start one owned App Service TCP tunnel process\n"
            "Tunnel restart permitted: no\n"
            "Raw tunnel output retained: no"
        ),
        approve_probes=lambda: approve(
            "Remote commands: two fixed APP_PATH prerequisite probes\n"
            "Arbitrary shell exploration permitted: no\n"
            "Probe retry permitted: no"
        ),
        approve_remote_check=lambda: approve(
            "Remote execution count: one\n"
            "Mode: check\n"
            "Managed identity, metadata, and Agent activity: prohibited\n"
            "Retry permitted: no"
        ),
    )
    service = _create_service()
    return service.run_live_tunnel(
        HostedFoundryAgentSshTransportRequest(
            mode=mode,
            subscription=config.subscription_name,
            resource_group=receipt.resource_group,
            web_app_name=receipt.web_app_name,
        ),
        approvals=approvals,
    )


def main(
    argv: list[str] | None = None,
    *,
    input_stream: TextIO | None = None,
    output_stream: TextIO | None = None,
) -> int:
    args = _parse_args(argv)
    result = (
        run_check()
        if args.check
        else _retired_metadata_mode_result()
        if args.live_metadata_verification
        else run_live(
            args,
            input_stream=input_stream or sys.stdin,
            output_stream=output_stream or sys.stderr,
        )
    )
    print(json.dumps(result.to_json_dict(), separators=(",", ":"), sort_keys=True))
    return 0 if result.ok is True else 2


if __name__ == "__main__":
    raise SystemExit(main())
