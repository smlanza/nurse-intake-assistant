import importlib
import json
import os
from pathlib import Path
import stat
import sys


BOOTSTRAP_FAILURE = {
    "agent_output_valid": False,
    "category": "bootstrap_failed",
    "fictional_data_only": True,
    "invocation_attempted": False,
    "invocation_succeeded": False,
    "message": "The hosted verifier bootstrap did not complete.",
    "metadata_verification_proven": False,
    "mode": "live",
    "ok": False,
    "recommended_next_step": "Restore the deployed application package.",
}
SUCCESS = {
    "agent_output_valid": True,
    "category": "success",
    "fictional_data_only": True,
    "invocation_attempted": True,
    "invocation_succeeded": True,
    "message": "The current hosted metadata and fixed-fictional invocation proofs completed.",
    "metadata_verification_proven": True,
    "mode": "live",
    "ok": True,
    "recommended_next_step": "Return this current-generation proof to the daily rebuild coordinator.",
}
UNEXPECTED_FAILURE = {
    "agent_output_valid": False,
    "category": "unexpected_error",
    "fictional_data_only": True,
    "invocation_attempted": False,
    "invocation_succeeded": False,
    "metadata_verification_proven": False,
    "mode": "live",
    "ok": False,
    "recommended_next_step": "Restore the deployed application package and review the sanitized WebJob result.",
}
METADATA_FAILURE = {
    **UNEXPECTED_FAILURE,
    "category": "metadata_verification_failed",
}
INVOCATION_FAILURE = {
    **UNEXPECTED_FAILURE,
    "category": "invocation_failed",
    "invocation_attempted": True,
    "metadata_verification_proven": True,
}
MALFORMED_METADATA_FAILURE = {
    **UNEXPECTED_FAILURE,
    "category": "metadata_result_malformed",
}
MALFORMED_INVOCATION_FAILURE = {
    **UNEXPECTED_FAILURE,
    "category": "invocation_result_malformed",
    "metadata_verification_proven": True,
}
UNEXPECTED_FAILURE_JSON = (
    '{"agent_output_valid":false,"category":"unexpected_error",'
    '"fictional_data_only":true,"invocation_attempted":false,'
    '"invocation_succeeded":false,"metadata_verification_proven":false,'
    '"mode":"live","ok":false,"recommended_next_step":'
    '"Restore the deployed application package and review the sanitized WebJob result."}'
)


def _load_operations():
    try:
        home = os.environ.get("HOME")
        if not isinstance(home, str) or not home.strip() or home != home.strip():
            return None
        home_path = Path(home)
        if not home_path.is_absolute():
            return None
        application_root = home_path / "site" / "wwwroot"
        for directory in (
            home_path,
            home_path / "site",
            application_root,
            application_root / "src",
            application_root / "src/app",
            application_root / "src/app/operations",
        ):
            if directory.is_symlink() or not stat.S_ISDIR(directory.lstat().st_mode):
                return None
        application_root = application_root.resolve(strict=True)
        source_root = application_root / "src"
        for directory, names, files in os.walk(source_root, followlinks=False):
            current = Path(directory)
            if current.is_symlink() or not stat.S_ISDIR(current.lstat().st_mode):
                return None
            for name in (*names, *files):
                candidate = current / name
                mode = candidate.lstat().st_mode
                if candidate.is_symlink() or not (
                    stat.S_ISDIR(mode) or stat.S_ISREG(mode)
                ):
                    return None
        operation_paths = {
            "verify_hosted_foundry_agent": application_root
            / "src/app/operations/verify_hosted_foundry_agent.py",
            "invoke_hosted_foundry_agent": application_root
            / "src/app/operations/invoke_hosted_foundry_agent.py",
        }
        resolved_operations = {
            name: path.resolve(strict=True)
            for name, path in operation_paths.items()
        }
        if (
            not application_root.is_dir()
            or any(
                path.is_symlink()
                or not stat.S_ISREG(path.lstat().st_mode)
                or not path.is_relative_to(application_root)
                for path in resolved_operations.values()
            )
        ):
            return None
        expected_modules = {
            "src": (application_root / "src", None),
            "src.app": (application_root / "src/app", None),
            "src.app.operations": (application_root / "src/app/operations", None),
            "src.app.operations.verify_hosted_foundry_agent": (
                application_root / "src/app/operations",
                resolved_operations["verify_hosted_foundry_agent"],
            ),
            "src.app.operations.invoke_hosted_foundry_agent": (
                application_root / "src/app/operations",
                resolved_operations["invoke_hosted_foundry_agent"],
            ),
        }

        def loaded_module_matches(module, package_directory, exact_file):
            expected_file = exact_file or package_directory / "__init__.py"
            loaded_file = getattr(module, "__file__", None)
            if expected_file.is_file():
                return (
                    isinstance(loaded_file, str)
                    and bool(loaded_file.strip())
                    and Path(loaded_file).resolve(strict=True)
                    == expected_file.resolve(strict=True)
                    and not expected_file.is_symlink()
                    and stat.S_ISREG(expected_file.lstat().st_mode)
                )
            loaded_paths = getattr(module, "__path__", None)
            if loaded_file is not None or loaded_paths is None:
                return False
            resolved_paths = [Path(path).resolve(strict=True) for path in loaded_paths]
            return resolved_paths == [package_directory.resolve(strict=True)]

        for module_name, expected in expected_modules.items():
            loaded = sys.modules.get(module_name)
            if loaded is not None and not loaded_module_matches(loaded, *expected):
                return None
        root = str(application_root)
        retained_paths = []
        for entry in sys.path:
            try:
                if isinstance(entry, str) and Path(entry).resolve() == application_root:
                    continue
            except (OSError, RuntimeError, ValueError):
                pass
            retained_paths.append(entry)
        sys.path[:] = [root, *retained_paths]
        importlib.invalidate_caches()
        from src.app.operations import (
            invoke_hosted_foundry_agent,
            verify_hosted_foundry_agent,
        )

        imported_operations = {
            "verify_hosted_foundry_agent": verify_hosted_foundry_agent,
            "invoke_hosted_foundry_agent": invoke_hosted_foundry_agent,
        }
        for name, operation in imported_operations.items():
            imported_file = getattr(operation, "__file__", None)
            if (
                not isinstance(imported_file, str)
                or not imported_file.strip()
                or Path(imported_file).resolve(strict=True)
                != resolved_operations[name]
            ):
                return None
        if any(
            not loaded_module_matches(sys.modules.get(module_name), *expected)
            for module_name, expected in expected_modules.items()
        ):
            return None
        for module_name, module in tuple(sys.modules.items()):
            if module_name != "src" and not module_name.startswith("src."):
                continue
            loaded_file = getattr(module, "__file__", None)
            if loaded_file is not None:
                candidate = Path(loaded_file)
                if (
                    candidate.is_symlink()
                    or not stat.S_ISREG(candidate.lstat().st_mode)
                    or not candidate.resolve(strict=True).is_relative_to(source_root)
                ):
                    return None
        return verify_hosted_foundry_agent, invoke_hosted_foundry_agent
    except Exception:
        return None


def _exact_metadata_success(verifier, result) -> bool:
    expected_type = getattr(verifier, "HostedFoundryAgentVerificationResult", None)
    return bool(
        isinstance(expected_type, type)
        and type(result) is expected_type
        and result.ok is True
        and result.category == "success"
        and result.operation == "verify_hosted_foundry_agent"
        and result.mode == "live"
        and result.local_contract_validated is True
        and result.hosted_environment_present is True
        and result.managed_identity_attempted is True
        and result.managed_identity_authenticated is True
        and result.project_access_verified is True
        and result.agent_present is True
        and result.configured_version_present is True
        and result.agent_contract_verified is True
        and result.agent_invocation_attempted is False
        and result.azure_mutation_made is False
        and result.recommended_next_step
        == "Run the separate fictional-data hosted agent invocation."
    )


def _exact_invocation_success(invoker, result) -> bool:
    expected_type = getattr(invoker, "HostedFoundryAgentInvocationResult", None)
    return bool(
        isinstance(expected_type, type)
        and type(result) is expected_type
        and result.ok is True
        and result.category == "success"
        and result.invocation_attempted is True
        and result.agent_output_valid is True
        and result.fields_present == ("extraction", "urgency", "handoffNote")
        and result.fictional_data_only is True
        and result.message
        == "One fictional agent response passed the application contract."
        and result.recommended_next_step
        == "Retain human nurse review; this fictional proof is not clinical readiness."
    )


def run() -> int:
    result = UNEXPECTED_FAILURE
    exit_code = 1
    try:
        loaded_operations = _load_operations()
        if loaded_operations is None:
            result = BOOTSTRAP_FAILURE
            exit_code = 2
        else:
            verifier, invoker = loaded_operations
            verification = verifier.run_hosted_foundry_agent_verification("live")
            verification_type = getattr(
                verifier, "HostedFoundryAgentVerificationResult", None
            )
            if not isinstance(verification_type, type) or type(verification) is not verification_type:
                result = MALFORMED_METADATA_FAILURE
                verification_proven = False
            else:
                verification_proven = _exact_metadata_success(verifier, verification)
            if not verification_proven:
                if result is not MALFORMED_METADATA_FAILURE:
                    result = METADATA_FAILURE
            else:
                invocation = invoker.run_hosted_foundry_agent_invocation("live")
                invocation_type = getattr(
                    invoker, "HostedFoundryAgentInvocationResult", None
                )
                if not isinstance(invocation_type, type) or type(invocation) is not invocation_type:
                    invocation_succeeded = False
                    result = MALFORMED_INVOCATION_FAILURE
                else:
                    invocation_succeeded = _exact_invocation_success(invoker, invocation)
                    result = (
                        {**SUCCESS, "fictional_data_only": invocation.fictional_data_only}
                        if invocation_succeeded
                        else {
                            **INVOCATION_FAILURE,
                            "fictional_data_only": (
                                invocation.fictional_data_only
                                if invocation.fictional_data_only is True
                                else False
                            ),
                        }
                    )
                exit_code = 0 if invocation_succeeded else 1
    except Exception:
        result = UNEXPECTED_FAILURE
        exit_code = 1
    try:
        output = json.dumps(result, separators=(",", ":"), sort_keys=True)
    except Exception:
        output = UNEXPECTED_FAILURE_JSON
        exit_code = 1
    sys.stdout.write(output + "\n")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(run())
