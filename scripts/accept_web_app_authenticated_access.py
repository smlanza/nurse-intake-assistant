import argparse
import json
from pathlib import Path
import sys
from typing import TextIO


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.accept_web_app_authentication import (
    DEFAULT_SESSION_FILE,
    _create_azure_cli_runner,
    _load_private_request,
    diagnose_authentication_configuration_shape,
    parse_authentication_configuration_evidence,
    read_authentication_configuration_stdout,
)
from scripts.verify_web_app_authentication_runtime import (
    _create_runtime_transport,
    _operator_identifiers,
)
from src.app.services.web_app_authenticated_access_acceptance import (
    AuthenticatedAccessAcceptanceResult,
    InteractiveAuthenticationEvidence,
    InteractiveAuthenticationPrompt,
    InteractiveOutcome,
    accept_authenticated_application_access,
    check_authenticated_access_acceptance_contract,
)
from src.app.services.web_app_authentication_runtime_verification import (
    RuntimeAuthenticationEvidence,
    verify_web_app_authentication_runtime,
)
from src.app.services.web_app_hosting_contract import (
    app_service_authentication_configuration_valid,
)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Check or supervise one interactive Microsoft Entra sign-in and "
            "authenticated GET /demo acceptance."
        )
    )
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--check", action="store_true")
    modes.add_argument("--live", action="store_true")
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / ".env.daily-azure.local",
    )
    parser.add_argument(
        "--readiness-receipt",
        type=Path,
        default=ROOT / ".artifacts/daily-azure-rebuild/readiness-receipt.json",
    )
    parser.add_argument(
        "--current-session",
        type=Path,
        default=DEFAULT_SESSION_FILE,
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.live and not args.json:
        parser.error("--live requires --json")
    return args


def prompt_for_interactive_outcome(
    prompt: InteractiveAuthenticationPrompt,
    *,
    input_stream: TextIO | None = None,
    output_stream: TextIO | None = None,
) -> InteractiveOutcome:
    source = input_stream or sys.stdin
    destination = output_stream or sys.stderr
    destination.write(
        "APP SERVICE AUTHENTICATED ACCESS\n\n"
        f"Current READY evidence: {'yes' if prompt.ready_current else 'no'}\n"
        "Authentication configuration current: "
        f"{'yes' if prompt.authentication_configuration_current else 'no'}\n"
        "Runtime perimeter proof current: "
        f"{'yes' if prompt.runtime_perimeter_current else 'no'}\n"
        f"Fixed protected request: {prompt.method} {prompt.route}\n\n"
        "Complete Microsoft Entra sign-in in the supervised browser. Enter y "
        "only after the protected demo application surface is visible. "
        "Enter f for sign-in failure or a for protected-access failure. [y/N] "
    )
    destination.flush()
    response = source.readline().strip().casefold()
    if response in {"y", "yes"}:
        return "verified"
    if response in {"f", "failed"}:
        return "sign_in_failed"
    if response in {"a", "access-failed"}:
        return "access_failed"
    return "cancelled"


def _payload(
    result: AuthenticatedAccessAcceptanceResult,
    *,
    authentication_reads: int = 0,
    runtime_perimeter_requests: int = 0,
    ready_current: bool = False,
    exact_web_app_artifact_current: bool = False,
    authentication_configuration_current: bool = False,
    runtime_perimeter_current: bool = False,
) -> dict[str, object]:
    payload = result.to_json_dict()
    payload.update(
        authentication_reads=authentication_reads,
        runtime_perimeter_requests=runtime_perimeter_requests,
        azure_commands=authentication_reads,
        network_request_count=(
            authentication_reads + runtime_perimeter_requests
        ),
        ready_current=ready_current,
        exact_web_app_artifact_current=exact_web_app_artifact_current,
        authentication_configuration_current=(
            authentication_configuration_current
        ),
        runtime_perimeter_current=runtime_perimeter_current,
    )
    return payload


def _blocked_payload(
    reason: str,
    *,
    authentication_reads: int = 0,
    runtime_perimeter_requests: int = 0,
    ready_current: bool = False,
    exact_web_app_artifact_current: bool = False,
    authentication_configuration_current: bool = False,
) -> dict[str, object]:
    result = AuthenticatedAccessAcceptanceResult(
        ok=False,
        mode="live",
        category="authenticated_acceptance_blocked",
        reason=reason,
    )
    return _payload(
        result,
        authentication_reads=authentication_reads,
        runtime_perimeter_requests=runtime_perimeter_requests,
        ready_current=ready_current,
        exact_web_app_artifact_current=exact_web_app_artifact_current,
        authentication_configuration_current=(
            authentication_configuration_current
        ),
    )


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.check:
        result = check_authenticated_access_acceptance_contract()
        payload = _payload(result)
        print(json.dumps(payload, separators=(",", ":"), sort_keys=True))
        return 0 if result.ok else 2

    client_application_id, tenant_id = _operator_identifiers()
    configuration = {
        "mode": "enabled",
        "clientId": client_application_id,
        "tenantId": tenant_id,
    }
    if not app_service_authentication_configuration_valid(configuration):
        payload = _blocked_payload("authentication_evidence_invalid")
    else:
        args.client_application_id = client_application_id
        args.tenant_id = tenant_id
        loaded = _load_private_request(args)
        if loaded is None:
            payload = _blocked_payload("authentication_evidence_invalid")
        else:
            _, request = loaded
            current = {
                "ready_current": True,
                "exact_web_app_artifact_current": True,
            }
            runner = _create_azure_cli_runner()
            stdout = read_authentication_configuration_stdout(runner, request)
            configured = None
            if (
                stdout is not None
                and diagnose_authentication_configuration_shape(stdout) is None
            ):
                configured = parse_authentication_configuration_evidence(
                    stdout,
                    expected_client_id=request.client_application_id,
                    expected_tenant_id=request.tenant_id,
                    expected_login_endpoint=None,
                )
            if configured is None:
                payload = _blocked_payload(
                    "authentication_configuration_evidence_invalid",
                    authentication_reads=1,
                    **current,
                )
            else:
                runtime_result = verify_web_app_authentication_runtime(
                    RuntimeAuthenticationEvidence(
                        hosted_origin=request.hosted_origin,
                        ready_current=True,
                        exact_web_app_current=True,
                        artifact_readiness_current=True,
                        authentication_configuration_current=True,
                    ),
                    transport_factory=_create_runtime_transport,
                )
                runtime_requests = (
                    runtime_result.anonymous_gets_attempted
                    + runtime_result.protected_gets_attempted
                )
                if not runtime_result.ok:
                    payload = _blocked_payload(
                        "runtime_perimeter_evidence_invalid",
                        authentication_reads=1,
                        runtime_perimeter_requests=runtime_requests,
                        authentication_configuration_current=True,
                        **current,
                    )
                else:
                    result = accept_authenticated_application_access(
                        InteractiveAuthenticationEvidence(
                            hosted_origin=request.hosted_origin,
                            ready_current=True,
                            exact_web_app_artifact_current=True,
                            authentication_configuration_current=True,
                            runtime_perimeter_current=True,
                        ),
                        operator_checkpoint=prompt_for_interactive_outcome,
                    )
                    payload = _payload(
                        result,
                        authentication_reads=1,
                        runtime_perimeter_requests=runtime_requests,
                        authentication_configuration_current=True,
                        runtime_perimeter_current=True,
                        **current,
                    )
    print(json.dumps(payload, separators=(",", ":"), sort_keys=True))
    return 0 if payload["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
