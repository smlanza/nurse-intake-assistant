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
from src.app.services.web_app_configuration_verification import (
    HOSTED_SETTING_OPTIONS,
    WebAppConfigurationVerificationResult,
    verify_web_app_configuration,
)


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
    if (args.live_tunnel or args.live_metadata_verification) and args.config is None:
        parser.error("--config is required for live modes")
    for attribute in HOSTED_SETTING_OPTIONS.values():
        values = getattr(args, attribute)
        if args.live_metadata_verification:
            if not isinstance(values, list) or len(values) != 1:
                parser.error(
                    f"--{attribute.replace('_', '-')} is required exactly once "
                    "with --live-metadata-verification"
                )
            setattr(args, attribute, values[0])
        elif values:
            parser.error(
                "hosted verifier values require --live-metadata-verification"
            )
    return args


def run_check() -> HostedFoundryAgentSshTransportResult:
    return HostedFoundryAgentSshTransport().check(
        build_hosted_foundry_agent_ssh_transport_check_request()
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


def _create_service(
    hosted_verifier_configuration_proof: (
        WebAppConfigurationVerificationResult | None
    ) = None,
) -> HostedFoundryAgentSshTransport:
    return HostedFoundryAgentSshTransport(
        hosted_verifier_configuration_proof=(
            hosted_verifier_configuration_proof
        )
    )


def _expected_hosted_verifier_settings(
    args: argparse.Namespace,
) -> dict[str, str]:
    return {
        setting_name: getattr(args, attribute)
        for setting_name, attribute in HOSTED_SETTING_OPTIONS.items()
    }


def _create_configuration_runner():
    from scripts.verify_web_app_configuration import SubprocessAzureCliRunner

    return SubprocessAzureCliRunner()


def _verify_hosted_verifier_configuration(
    config: object,
    receipt: object,
    args: argparse.Namespace,
) -> WebAppConfigurationVerificationResult:
    if getattr(config, "enable_hosted_foundry_verifier", None) is not True:
        return WebAppConfigurationVerificationResult.failure(
            "hosted_verifier_configuration_invalid"
        )
    return verify_web_app_configuration(
        getattr(receipt, "resource_group", None),
        getattr(receipt, "web_app_name", None),
        _expected_hosted_verifier_settings(args),
        verify_hosted_foundry_verifier=True,
        runner=_create_configuration_runner(),
    )


def run_live(
    args: argparse.Namespace,
    *,
    input_stream: TextIO,
    output_stream: TextIO,
) -> HostedFoundryAgentSshTransportResult:
    mode = (
        "live-metadata-verification"
        if getattr(args, "live_metadata_verification", False)
        else "live-tunnel"
    )
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
    configuration_proof: WebAppConfigurationVerificationResult | None = None
    if mode == "live-metadata-verification":
        try:
            candidate = _verify_hosted_verifier_configuration(
                config,
                receipt,
                args,
            )
        except Exception:
            candidate = None
        expected_proof = WebAppConfigurationVerificationResult.live_success(
            hosted_verifier_configuration_verified=True
        )
        if (
            type(candidate) is not WebAppConfigurationVerificationResult
            or candidate != expected_proof
        ):
            return HostedFoundryAgentSshTransportResult.build(
                ok=False,
                category="hosted_verifier_configuration_invalid",
                mode=mode,
                azure_call_made=bool(
                    type(candidate) is WebAppConfigurationVerificationResult
                    and candidate.azure_request_attempted is True
                ),
            )
        configuration_proof = candidate

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
        approve_metadata_verification=lambda: (
            approve(
                "Remote execution count: one\n"
                "Mode: hosted metadata verification\n"
                "System-assigned managed identity: required\n"
                "Foundry metadata reads: permitted\n"
                "Agent invocation: prohibited\n"
                "Azure mutation: prohibited\n"
                "Retry permitted: no"
            )
            if mode == "live-metadata-verification"
            else False
        ),
    )
    service = (
        _create_service(configuration_proof)
        if mode == "live-metadata-verification"
        else _create_service()
    )
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
