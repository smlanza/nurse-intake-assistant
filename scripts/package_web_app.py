import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.app.services.web_app_package import (
    PACKAGE_FILENAME,
    PackageSafetyError,
    build_web_app_package,
    plan_web_app_package,
)


def _base(mode: str, category: str, ok: bool = False) -> dict[str, object]:
    return {
        "ok": ok,
        "operation": "package_web_app",
        "mode": mode,
        "category": category,
        "package_created": False,
        "package_filename": PACKAGE_FILENAME,
        "package_size_bytes": None,
        "package_file_count": 0,
        "package_sha256": None,
        "package_sha256_present": False,
        "azure_command_attempted": False,
        "recommended_next_step": "Review the sanitized package failure category.",
    }


def execute(mode: str, *, source_root: Path | None = None) -> dict[str, object]:
    source_root = source_root or ROOT
    try:
        if mode == "check":
            plan = plan_web_app_package(source_root)
            result = _base(mode, "success", True)
            result["package_file_count"] = len(plan.member_names)
            result["recommended_next_step"] = "Run --package --json to create the deterministic local ZIP."
            return result
        if mode != "package":
            return _base(mode, "unsupported_mode")
        package = build_web_app_package(source_root)
    except PackageSafetyError as error:
        return _base(mode, error.category)

    result = _base(mode, "success", True)
    result.update(package.to_json_dict())
    result["mode"] = mode
    result["azure_command_attempted"] = False
    result["recommended_next_step"] = (
        "Add and review App Service Python build automation before any explicit live deployment."
    )
    return result


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate or build the deterministic Azure Web App package."
    )
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--check", action="store_true")
    modes.add_argument("--package", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    mode = "check" if args.check else "package"
    result = execute(mode)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
