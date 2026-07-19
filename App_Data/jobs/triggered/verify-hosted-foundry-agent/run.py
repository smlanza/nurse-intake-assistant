import importlib
import json
import os
from pathlib import Path
import sys


BOOTSTRAP_FAILURE = {
    "category": "bootstrap_failed",
    "message": "The hosted verifier bootstrap did not complete.",
    "mode": "live",
    "ok": False,
    "recommended_next_step": "Restore the deployed application package.",
}


def _load_operation():
    try:
        home = os.environ.get("HOME")
        if not isinstance(home, str) or not home.strip() or home != home.strip():
            return None
        home_path = Path(home)
        if not home_path.is_absolute():
            return None
        application_root = (home_path / "site" / "wwwroot").resolve(strict=True)
        operation_path = (
            application_root
            / "src/app/operations/verify_hosted_foundry_agent.py"
        )
        resolved_operation = operation_path.resolve(strict=True)
        if (
            not application_root.is_dir()
            or not resolved_operation.is_file()
            or not resolved_operation.is_relative_to(application_root)
        ):
            return None
        expected_modules = {
            "src": (application_root / "src", None),
            "src.app": (application_root / "src/app", None),
            "src.app.operations": (application_root / "src/app/operations", None),
            "src.app.operations.verify_hosted_foundry_agent": (
                application_root / "src/app/operations",
                resolved_operation,
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
        from src.app.operations import verify_hosted_foundry_agent

        imported_file = getattr(verify_hosted_foundry_agent, "__file__", None)
        if (
            not isinstance(imported_file, str)
            or not imported_file.strip()
            or Path(imported_file).resolve(strict=True) != resolved_operation
        ):
            return None
        if any(
            not loaded_module_matches(sys.modules.get(module_name), *expected)
            for module_name, expected in expected_modules.items()
        ):
            return None
        return verify_hosted_foundry_agent
    except Exception:
        return None


verify_hosted_foundry_agent = _load_operation()


def run() -> int:
    if verify_hosted_foundry_agent is None:
        print(json.dumps(BOOTSTRAP_FAILURE, separators=(",", ":"), sort_keys=True))
        return 2
    return verify_hosted_foundry_agent.main(["--live", "--json"])


if __name__ == "__main__":
    raise SystemExit(run())
