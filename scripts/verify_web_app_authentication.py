import argparse
import json
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.app.services.web_app_authentication_verification import (
    check_web_app_authentication_contract,
)
from src.app.services.web_app_hosting_contract import (
    app_service_authentication_configuration_valid,
)
from scripts.accept_web_app_authentication import (
    DEFAULT_SESSION_FILE,
    OPERATOR_IDENTIFIER_ENVIRONMENT,
    _create_azure_cli_runner,
    _load_private_request,
    diagnose_authentication_configuration_shape,
    parse_authentication_configuration_evidence,
    read_authentication_configuration_stdout,
)


def _live_result(
    category: str,
    *,
    ok: bool = False,
    azure_request_attempted: bool = False,
    authentication_reads: int = 0,
    diagnostic: object | None = None,
    verified: object | None = None,
) -> dict[str, object]:
    result: dict[str, object] = {
        "ok": ok,
        "category": category,
        "mode": "live",
        "operation": "verify_web_app_authentication",
        "azure_request_attempted": azure_request_attempted,
        "authentication_reads": authentication_reads,
        "azure_mutation_made": False,
    }
    if diagnostic is not None:
        result.update(diagnostic.to_json_dict())
    if verified is not None:
        result.update(
            authentication_v2_enabled=verified.enabled,
            authentication_required_verified=(
                verified.authentication_required_verified
            ),
            https_required_verified=verified.https_required_verified,
            unauthenticated_action_verified=(
                verified.unauthenticated_action_verified
            ),
            anonymous_exclusions_verified=(
                verified.anonymous_exclusions_verified
            ),
            microsoft_entra_provider_verified=verified.entra_provider_verified,
            client_application_identity_configuration_verified=(
                verified.application_binding_verified
            ),
            tenant_binding_verified=verified.tenant_binding_verified,
        )
    return result


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check or live-verify App Service Authentication v2."
    )
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--check", action="store_true")
    modes.add_argument("--live", action="store_true")
    parser.add_argument("--expect-enabled", action="store_true")
    parser.add_argument("--client-application-id", action="append")
    parser.add_argument("--tenant-id", action="append")
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
    if args.live:
        if args.expect_enabled:
            parser.error("--expect-enabled belongs to --check")
        for attribute, environment_name in OPERATOR_IDENTIFIER_ENVIRONMENT.items():
            values = getattr(args, attribute)
            if values is None:
                setattr(args, attribute, os.environ.get(environment_name))
            elif not isinstance(values, list) or len(values) != 1:
                parser.error(
                    f"--{attribute.replace('_', '-')} must be supplied exactly once"
                )
            else:
                setattr(args, attribute, values[0])
        if not args.json:
            parser.error("--live requires --json")
    elif args.expect_enabled:
        supplied = (args.client_application_id, args.tenant_id)
        if any(not isinstance(values, list) or len(values) != 1 for values in supplied):
            parser.error(
                "--expect-enabled requires exactly one --client-application-id "
                "and --tenant-id"
            )
        args.client_application_id = args.client_application_id[0]
        args.tenant_id = args.tenant_id[0]
    elif any((args.client_application_id, args.tenant_id)):
        parser.error("Entra identifiers require --expect-enabled")
    return args


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.live:
        configuration = {
            "mode": "enabled",
            "clientId": args.client_application_id,
            "tenantId": args.tenant_id,
        }
        if not app_service_authentication_configuration_valid(configuration):
            result = _live_result("operator_identifiers_unavailable")
        else:
            loaded = _load_private_request(args)
            if loaded is None:
                result = _live_result("safe_live_verification_blocked")
            else:
                _, request = loaded
                runner = _create_azure_cli_runner()
                stdout = read_authentication_configuration_stdout(runner, request)
                if stdout is None:
                    result = _live_result(
                        "safe_live_verification_blocked",
                        azure_request_attempted=True,
                        authentication_reads=1,
                    )
                else:
                    diagnostic = diagnose_authentication_configuration_shape(stdout)
                    if diagnostic is not None:
                        result = _live_result(
                            "response_shape_mismatch",
                            azure_request_attempted=True,
                            authentication_reads=1,
                            diagnostic=diagnostic,
                        )
                    else:
                        verified = parse_authentication_configuration_evidence(
                            stdout,
                            expected_client_id=request.client_application_id,
                            expected_tenant_id=request.tenant_id,
                            expected_login_endpoint=None,
                        )
                        if verified is None:
                            result = _live_result(
                                "authentication_semantic_mismatch",
                                azure_request_attempted=True,
                                authentication_reads=1,
                            )
                            result.update(
                                field="authentication_configuration",
                                reason="contract_mismatch",
                            )
                        else:
                            result = _live_result(
                                "authentication_configuration_verified",
                                ok=True,
                                azure_request_attempted=True,
                                authentication_reads=1,
                                verified=verified,
                            )
        print(json.dumps(result, separators=(",", ":"), sort_keys=True))
        return 0 if result["ok"] else 2

    configuration = (
        {
            "mode": "enabled",
            "clientId": args.client_application_id,
            "tenantId": args.tenant_id,
        }
        if args.expect_enabled
        else {"mode": "disabled"}
    )
    result = check_web_app_authentication_contract(configuration)
    print(json.dumps(result.to_json_dict(), separators=(",", ":"), sort_keys=True))
    return 0 if result.ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
