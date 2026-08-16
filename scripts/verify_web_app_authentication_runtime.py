import argparse
import json
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.accept_web_app_authentication import (
    DEFAULT_SESSION_FILE,
    OPERATOR_IDENTIFIER_ENVIRONMENT,
    _create_azure_cli_runner,
    _load_private_request,
    diagnose_authentication_configuration_shape,
    parse_authentication_configuration_evidence,
    read_authentication_configuration_stdout,
)
from src.app.services.web_app_authentication_runtime_verification import (
    AuthenticationRuntimeVerificationResult,
    RuntimeAuthenticationEvidence,
    check_web_app_authentication_runtime_contract,
    verify_web_app_authentication_runtime,
)
from src.app.services.web_app_hosting_contract import (
    app_service_authentication_configuration_valid,
)
from src.app.services.web_app_readiness_verification import (
    UrllibWebAppReadinessTransport,
)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Check or live-verify the bounded unauthenticated App Service "
            "Authentication runtime perimeter."
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


def _create_runtime_transport(
    hosted_origin: str,
) -> UrllibWebAppReadinessTransport:
    return UrllibWebAppReadinessTransport(hosted_origin)


def _result_payload(
    result: AuthenticationRuntimeVerificationResult,
    *,
    authentication_reads: int = 0,
    ready_current: bool = False,
    exact_web_app_current: bool = False,
    artifact_readiness_current: bool = False,
    authentication_configuration_current: bool = False,
) -> dict[str, object]:
    payload = result.to_json_dict()
    runtime_requests = (
        result.anonymous_gets_attempted + result.protected_gets_attempted
    )
    payload.update(
        authentication_reads=authentication_reads,
        azure_request_attempted=authentication_reads == 1,
        azure_commands=authentication_reads,
        runtime_http_request_count=runtime_requests,
        network_request_count=authentication_reads + runtime_requests,
        ready_current=ready_current,
        exact_web_app_current=exact_web_app_current,
        artifact_readiness_current=artifact_readiness_current,
        authentication_configuration_current=(
            authentication_configuration_current
        ),
    )
    return payload


def _blocked_payload(
    reason: str,
    *,
    authentication_reads: int = 0,
    ready_current: bool = False,
    exact_web_app_current: bool = False,
    artifact_readiness_current: bool = False,
) -> dict[str, object]:
    result = AuthenticationRuntimeVerificationResult(
        ok=False,
        mode="live",
        category="safe_runtime_verification_blocked",
    )
    payload = _result_payload(
        result,
        authentication_reads=authentication_reads,
        ready_current=ready_current,
        exact_web_app_current=exact_web_app_current,
        artifact_readiness_current=artifact_readiness_current,
    )
    payload["reason"] = reason
    return payload


def _operator_identifiers() -> tuple[str | None, str | None]:
    return tuple(
        os.environ.get(environment_name)
        for environment_name in OPERATOR_IDENTIFIER_ENVIRONMENT.values()
    )


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.check:
        result = check_web_app_authentication_runtime_contract()
        payload = _result_payload(result)
        print(json.dumps(payload, separators=(",", ":"), sort_keys=True))
        return 0 if result.ok else 2

    client_application_id, tenant_id = _operator_identifiers()
    configuration = {
        "mode": "enabled",
        "clientId": client_application_id,
        "tenantId": tenant_id,
    }
    if not app_service_authentication_configuration_valid(configuration):
        payload = _blocked_payload("readiness_evidence_invalid")
    else:
        args.client_application_id = client_application_id
        args.tenant_id = tenant_id
        loaded = _load_private_request(args)
        if loaded is None:
            payload = _blocked_payload("readiness_evidence_invalid")
        else:
            _, request = loaded
            evidence_values = {
                "ready_current": True,
                "exact_web_app_current": True,
                "artifact_readiness_current": True,
            }
            runner = _create_azure_cli_runner()
            stdout = read_authentication_configuration_stdout(runner, request)
            if stdout is None:
                payload = _blocked_payload(
                    "authentication_configuration_unavailable",
                    authentication_reads=1,
                    **evidence_values,
                )
            elif diagnose_authentication_configuration_shape(stdout) is not None:
                payload = _blocked_payload(
                    "authentication_configuration_invalid",
                    authentication_reads=1,
                    **evidence_values,
                )
            else:
                configured = parse_authentication_configuration_evidence(
                    stdout,
                    expected_client_id=request.client_application_id,
                    expected_tenant_id=request.tenant_id,
                    expected_login_endpoint=None,
                )
                if configured is None:
                    payload = _blocked_payload(
                        "authentication_configuration_invalid",
                        authentication_reads=1,
                        **evidence_values,
                    )
                else:
                    evidence = RuntimeAuthenticationEvidence(
                        hosted_origin=request.hosted_origin,
                        authentication_configuration_current=True,
                        **evidence_values,
                    )
                    result = verify_web_app_authentication_runtime(
                        evidence,
                        transport_factory=_create_runtime_transport,
                    )
                    payload = _result_payload(
                        result,
                        authentication_reads=1,
                        authentication_configuration_current=True,
                        **evidence_values,
                    )
    print(json.dumps(payload, separators=(",", ":"), sort_keys=True))
    return 0 if payload["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
