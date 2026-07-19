import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = ROOT / "App_Data/jobs/triggered/verify-hosted-foundry-agent/run.py"


def _stage(tmp_path: Path, *, include_operation: bool = True) -> tuple[Path, Path]:
    staged_entrypoint = tmp_path / "webjob/run.py"
    staged_entrypoint.parent.mkdir(parents=True)
    staged_entrypoint.write_text(ENTRYPOINT.read_text())
    home = tmp_path / "home"
    operation = home / "site/wwwroot/src/app/operations/verify_hosted_foundry_agent.py"
    if include_operation:
        operation.parent.mkdir(parents=True)
        for package in (operation.parents[2], operation.parents[1], operation.parent):
            (package / "__init__.py").write_text("")
        operation.write_text(
            "import json, os\n"
            "def main(argv):\n"
            "    print(json.dumps({'argv': argv}, separators=(',', ':')))\n"
            "    return int(os.environ['FAKE_EXIT_CODE'])\n"
        )
    return staged_entrypoint, home


def _run(
    entrypoint: Path,
    tmp_path: Path,
    *,
    home: str | None,
    exit_code: int = 0,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment["FAKE_EXIT_CODE"] = str(exit_code)
    if home is None:
        environment.pop("HOME", None)
    else:
        environment["HOME"] = home
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir(exist_ok=True)
    return subprocess.run(
        [sys.executable, "-I", str(entrypoint)],
        cwd=unrelated,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def _write_operation(root: Path, body: str) -> Path:
    operation = root / "src/app/operations/verify_hosted_foundry_agent.py"
    operation.parent.mkdir(parents=True, exist_ok=True)
    for package in (operation.parents[2], operation.parents[1], operation.parent):
        (package / "__init__.py").write_text("")
    operation.write_text(body)
    return operation


def _run_with_ordered_paths(
    entrypoint: Path,
    tmp_path: Path,
    *,
    home: Path,
    alternate_root: Path,
    preload_alternate: bool = False,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment["HOME"] = str(home)
    application_root = home / "site/wwwroot"
    setup = (
        "import src.app.operations.verify_hosted_foundry_agent;"
        if preload_alternate
        else ""
    )
    harness = (
        "import runpy,sys;"
        f"sys.path[:0]=[{str(alternate_root)!r},{str(application_root)!r}];"
        f"{setup}"
        f"runpy.run_path({str(entrypoint)!r},run_name='__main__')"
    )
    unrelated = tmp_path / "ordered-path-cwd"
    unrelated.mkdir(exist_ok=True)
    return subprocess.run(
        [sys.executable, "-I", "-c", harness],
        cwd=unrelated,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize("operation_exit_code", [0, 1, 2])
def test_staged_entrypoint_uses_only_absolute_home_root_and_preserves_exit_code(
    tmp_path: Path,
    operation_exit_code: int,
) -> None:
    entrypoint, home = _stage(tmp_path)

    completed = _run(
        entrypoint,
        tmp_path,
        home=str(home),
        exit_code=operation_exit_code,
    )

    assert completed.returncode == operation_exit_code
    assert json.loads(completed.stdout) == {"argv": ["--live", "--json"]}
    assert completed.stderr == ""


@pytest.mark.parametrize("home", [None, "", "   ", "relative/home"])
def test_invalid_home_fails_with_one_fixed_sanitized_bootstrap_result(
    tmp_path: Path,
    home: str | None,
) -> None:
    entrypoint, _valid_home = _stage(tmp_path)

    completed = _run(entrypoint, tmp_path, home=home)

    assert completed.returncode == 2
    assert json.loads(completed.stdout) == {
        "ok": False,
        "category": "bootstrap_failed",
        "message": "The hosted verifier bootstrap did not complete.",
        "mode": "live",
        "recommended_next_step": "Restore the deployed application package.",
    }
    assert completed.stderr == ""
    assert str(tmp_path) not in completed.stdout


def test_missing_deployed_operation_fails_closed_without_path_disclosure(
    tmp_path: Path,
) -> None:
    entrypoint, home = _stage(tmp_path, include_operation=False)

    completed = _run(entrypoint, tmp_path, home=str(home))

    assert completed.returncode == 2
    assert json.loads(completed.stdout)["category"] == "bootstrap_failed"
    assert str(home) not in completed.stdout


def test_home_operation_wins_when_alternate_src_precedes_existing_home_root(
    tmp_path: Path,
) -> None:
    entrypoint, home = _stage(tmp_path)
    application_root = home / "site/wwwroot"
    _write_operation(
        application_root,
        "def main(argv):\n"
        "    print('{\"selected\":\"home\"}')\n"
        "    return 7 if argv == ['--live', '--json'] else 8\n",
    )
    alternate_root = tmp_path / "alternate-root"
    _write_operation(
        alternate_root,
        "def main(argv):\n"
        "    print('{\"selected\":\"alternate\"}')\n"
        "    return 9\n",
    )

    completed = _run_with_ordered_paths(
        entrypoint,
        tmp_path,
        home=home,
        alternate_root=alternate_root,
    )

    assert completed.returncode == 7
    assert json.loads(completed.stdout) == {"selected": "home"}
    assert "alternate" not in completed.stdout
    assert completed.stderr == ""


def test_preloaded_alternate_target_module_fails_closed_without_disclosure(
    tmp_path: Path,
) -> None:
    entrypoint, home = _stage(tmp_path)
    alternate_root = tmp_path / "preloaded-alternate-root"
    _write_operation(
        alternate_root,
        "def main(argv):\n"
        "    print('{\"selected\":\"preloaded-alternate\"}')\n"
        "    return 9\n",
    )

    completed = _run_with_ordered_paths(
        entrypoint,
        tmp_path,
        home=home,
        alternate_root=alternate_root,
        preload_alternate=True,
    )

    assert completed.returncode == 2
    assert json.loads(completed.stdout)["category"] == "bootstrap_failed"
    assert "alternate" not in completed.stdout
    assert str(alternate_root) not in completed.stdout
    assert completed.stderr == ""


def test_entrypoint_is_fixed_and_has_no_path_fallback_or_invocation_surface() -> None:
    source = ENTRYPOINT.read_text()

    assert "HOME" in source
    assert "site" in source and "wwwroot" in source
    assert "home_path.is_absolute()" in source
    assert '"src/app/operations/verify_hosted_foundry_agent.py"' in source
    assert '["--live", "--json"]' in source
    assert "importlib.invalidate_caches()" in source
    assert "resolved_operation" in source
    assert 'getattr(verify_hosted_foundry_agent, "__file__", None)' in source
    for forbidden in (
        "invoke_hosted_foundry_agent",
        "WEBJOBS_PATH",
        "getcwd",
        "argparse",
        "sys.argv",
        "input(",
        "subprocess",
        "requests",
    ):
        assert forbidden not in source
