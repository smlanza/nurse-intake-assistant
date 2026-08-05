import argparse
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
from typing import TextIO


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.app.application_composition import compose_application
from src.app.services.application_insights_intake_telemetry_proof import (
    ApplicationInsightsIntakeTelemetryApprovalSummary,
    ApplicationInsightsIntakeTelemetryProof,
    CommandResult,
    build_check_result,
    build_fictional_check_readiness_receipt,
    failure_result,
)
from src.app.services.daily_azure_environment_rebuild import (
    READINESS_RECEIPT_FILE,
    ConfigValidationError,
    load_daily_azure_config,
    load_matching_daily_azure_readiness_receipt,
)


DEFAULT_CONFIG = ROOT / ".env.daily-azure.local"
DEFAULT_RECEIPT = ROOT / READINESS_RECEIPT_FILE


class ProofCliError(ValueError):
    def __init__(self, category: str) -> None:
        super().__init__("Application Insights telemetry proof input is invalid")
        self.category = category


class _SanitizedParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ProofCliError("invalid_configuration") from None


class SubprocessAzureCliRunner:
    def run(
        self,
        args: list[str],
        *,
        timeout_seconds: float | None = None,
    ) -> CommandResult:
        try:
            completed = subprocess.run(
                args,
                shell=False,
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout_seconds,
            )
        except (OSError, subprocess.TimeoutExpired):
            return CommandResult(1, "", "")
        return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def _create_runner() -> SubprocessAzureCliRunner:
    return SubprocessAzureCliRunner()


def _sdk_available() -> bool:
    return importlib.util.find_spec("applicationinsights") is not None


def _cli_available() -> bool:
    return shutil.which("az") is not None


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = _SanitizedParser(
        description=(
            "Validate or run one fixed-fictional Application Insights intake "
            "telemetry proof."
        )
    )
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--check", action="store_true")
    modes.add_argument("--live", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--readiness-receipt", type=Path)
    args = parser.parse_args(argv)
    if not args.json:
        parser.error("json output is required")
    if args.live and (args.config is None or args.readiness_receipt is None):
        parser.error("live configuration is required")
    if args.check:
        args.config = args.config or DEFAULT_CONFIG
        args.readiness_receipt = args.readiness_receipt or DEFAULT_RECEIPT
    return args


def _load_local_contract(config_path: Path, receipt_path: Path):
    try:
        config = load_daily_azure_config(config_path, repository_root=ROOT)
    except ConfigValidationError:
        raise ProofCliError("invalid_configuration") from None
    receipt = load_matching_daily_azure_readiness_receipt(receipt_path, config)
    if receipt is None:
        raise ProofCliError("readiness_invalid")
    return config, receipt


def _load_check_contract(config_path: Path):
    try:
        config = load_daily_azure_config(config_path, repository_root=ROOT)
    except ConfigValidationError:
        raise ProofCliError("invalid_configuration") from None
    return config, build_fictional_check_readiness_receipt(config)


def prompt_for_approval(
    summary: ApplicationInsightsIntakeTelemetryApprovalSummary,
    *,
    input_stream: TextIO | None = None,
    output_stream: TextIO | None = None,
) -> bool:
    source = input_stream or sys.stdin
    destination = output_stream or sys.stderr
    destination.write(
        "Action: process one fixed-fictional local intake and emit telemetry once\n"
        "Current readiness verified: yes\n"
        "Current Azure account verified: yes\n"
        "Owned Application Insights resource verified: yes\n"
        "Safe mock provider posture: yes\n"
        "Notifications suppressed: yes\n"
        "Read-only bounded ingestion query: yes\n"
        "Infrastructure mutation: no\n\n"
        "Proceed? [y/N] "
    )
    destination.flush()
    return source.readline().strip().casefold() in {"y", "yes"}


def _emit(result: object) -> None:
    payload = result.to_json_dict()
    sys.stdout.write(json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n")


def main(argv: list[str] | None = None) -> int:
    mode = "live" if "--live" in (argv or sys.argv[1:]) else "check"
    try:
        args = _parse_args(list(sys.argv[1:] if argv is None else argv))
        config, receipt = (
            _load_check_contract(args.config)
            if args.check
            else _load_local_contract(args.config, args.readiness_receipt)
        )
        sdk_available = _sdk_available()
        cli_available = _cli_available()
        check = build_check_result(
            config=config,
            readiness_receipt=receipt,
            readiness_receipt_path=args.readiness_receipt,
            sdk_available=sdk_available,
            cli_available=cli_available,
        )
        if args.check or not check.ok:
            result = check if args.check else failure_result(check.category, "live")
            _emit(result)
            return 0 if result.ok else 2

        proof = ApplicationInsightsIntakeTelemetryProof(
            config=config,
            readiness_receipt=receipt,
            readiness_receipt_path=args.readiness_receipt,
            runner=_create_runner(),
            approver=prompt_for_approval,
            receipt_loader=load_matching_daily_azure_readiness_receipt,
            compose=compose_application,
        )
        result = proof.run_live()
        _emit(result)
        return 0 if result.ok else 2
    except ProofCliError as error:
        _emit(failure_result(error.category, mode))
        return 2
    except Exception:
        _emit(failure_result("unexpected_error", mode))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
