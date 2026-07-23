import json
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import shutil
import sys
import types

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
            "import os\n"
            "class HostedFoundryAgentVerificationResult:\n"
            "    def __init__(self, ok, mode):\n"
            "        self.ok=ok; self.category='success' if ok else 'agent_not_found'; "
            "self.operation='verify_hosted_foundry_agent'; self.mode=mode; "
            "self.local_contract_validated=ok; self.hosted_environment_present=ok; "
            "self.managed_identity_attempted=ok; self.managed_identity_authenticated=ok; "
            "self.project_access_verified=ok; self.agent_present=ok; "
            "self.configured_version_present=ok; self.agent_contract_verified=ok; "
            "self.agent_invocation_attempted=False; self.azure_mutation_made=False; "
            "self.recommended_next_step='Run the separate fictional-data hosted agent invocation.'\n"
            "def run_hosted_foundry_agent_verification(mode):\n"
            "    ok = int(os.environ['FAKE_EXIT_CODE']) == 0\n"
            "    return HostedFoundryAgentVerificationResult(ok, mode)\n"
        )
        invocation = operation.with_name("invoke_hosted_foundry_agent.py")
        invocation.write_text(
            "import os\n"
            "class HostedFoundryAgentInvocationResult:\n"
            "    def __init__(self, ok):\n"
            "        self.ok=ok; self.category='success' if ok else 'invalid_agent_output'; "
            "self.message='One fictional agent response passed the application contract.'; self.invocation_attempted=True; "
            "self.agent_output_valid=ok; self.fields_present=('extraction','urgency','handoffNote') if ok else (); "
            "self.fictional_data_only=True; self.recommended_next_step='Retain human nurse review; this fictional proof is not clinical readiness.'\n"
            "def run_hosted_foundry_agent_invocation(mode):\n"
            "    ok = int(os.environ['FAKE_EXIT_CODE']) == 0\n"
            "    return HostedFoundryAgentInvocationResult(ok)\n"
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
    environment["FAKE_EXIT_CODE"] = "0"
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

    assert completed.returncode == (0 if operation_exit_code == 0 else 1)
    payload = json.loads(completed.stdout)
    assert payload["ok"] is (operation_exit_code == 0)
    assert completed.stdout.count("\n") == 1
    assert completed.stderr == ""


@pytest.mark.parametrize("home", [None, "", "   ", "relative/home"])
def test_invalid_home_fails_with_one_fixed_sanitized_bootstrap_result(
    tmp_path: Path,
    home: str | None,
) -> None:
    entrypoint, _valid_home = _stage(tmp_path)

    completed = _run(entrypoint, tmp_path, home=home)

    assert completed.returncode == 2
    payload = json.loads(completed.stdout)
    assert payload["ok"] is False
    assert payload["category"] == "bootstrap_failed"
    assert payload["metadata_verification_proven"] is False
    assert payload["invocation_succeeded"] is False
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
        "class HostedFoundryAgentVerificationResult:\n"
        "    def __init__(self, mode):\n"
        "        self.ok=True; self.category='success'; self.operation='verify_hosted_foundry_agent'; self.mode=mode; "
        "self.local_contract_validated=True; self.hosted_environment_present=True; "
        "self.managed_identity_attempted=True; self.managed_identity_authenticated=True; "
        "self.project_access_verified=True; self.agent_present=True; self.configured_version_present=True; "
        "self.agent_contract_verified=True; self.agent_invocation_attempted=False; self.azure_mutation_made=False; "
        "self.recommended_next_step='Run the separate fictional-data hosted agent invocation.'\n"
        "def run_hosted_foundry_agent_verification(mode):\n"
        "    return HostedFoundryAgentVerificationResult(mode)\n",
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

    assert completed.returncode == 0
    assert json.loads(completed.stdout)["ok"] is True
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


def test_entrypoint_is_fixed_to_verification_then_fictional_invocation() -> None:
    source = ENTRYPOINT.read_text()

    assert "HOME" in source
    assert "site" in source and "wwwroot" in source
    assert "home_path.is_absolute()" in source
    assert '"src/app/operations/verify_hosted_foundry_agent.py"' in source
    assert '"src/app/operations/invoke_hosted_foundry_agent.py"' in source
    assert 'run_hosted_foundry_agent_verification("live")' in source
    assert 'run_hosted_foundry_agent_invocation("live")' in source
    assert "importlib.invalidate_caches()" in source
    assert "resolved_operation" in source
    assert 'getattr(operation, "__file__", None)' in source
    for forbidden in (
        "WEBJOBS_PATH",
        "getcwd",
        "argparse",
        "sys.argv",
        "input(",
        "subprocess",
        "requests",
    ):
        assert forbidden not in source


def test_entrypoint_success_emits_exactly_one_combined_json_document(
    tmp_path: Path,
) -> None:
    entrypoint, home = _stage(tmp_path)

    completed = _run(entrypoint, tmp_path, home=str(home), exit_code=0)

    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    assert completed.stdout.count("\n") == 1
    assert payload["metadata_verification_proven"] is True
    assert payload["invocation_succeeded"] is True
    assert payload["agent_output_valid"] is True
    assert payload["fictional_data_only"] is True
    assert "coordinator" in payload["recommended_next_step"].lower()
    assert "restore" not in payload["recommended_next_step"].lower()
    assert completed.stderr == ""


def test_entrypoint_sanitizes_unexpected_operation_exception_without_traceback(
    tmp_path: Path,
) -> None:
    entrypoint, home = _stage(tmp_path)
    operation = home / "site/wwwroot/src/app/operations/verify_hosted_foundry_agent.py"
    operation.write_text(
        "def run_hosted_foundry_agent_verification(mode):\n"
        "    raise RuntimeError('Bearer secret-token https://secret.example')\n"
    )

    completed = _run(entrypoint, tmp_path, home=str(home), exit_code=0)

    assert completed.returncode != 0
    assert json.loads(completed.stdout)["category"] == "unexpected_error"
    assert completed.stdout.count("\n") == 1
    assert "Traceback" not in completed.stderr
    assert "secret" not in completed.stdout + completed.stderr


def test_entrypoint_serialization_failure_keeps_the_complete_fixed_json_shape(
    monkeypatch,
) -> None:
    spec = importlib.util.spec_from_file_location("webjob_entrypoint", ENTRYPOINT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    output = io.StringIO()

    monkeypatch.setattr(module, "_load_operations", lambda: None)
    monkeypatch.setattr(
        module.json,
        "dumps",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(TypeError("secret")),
    )
    monkeypatch.setattr(module.sys, "stdout", output)

    assert module.run() == 1
    payload = json.loads(output.getvalue())
    assert payload == module.UNEXPECTED_FAILURE
    assert output.getvalue().count("\n") == 1


class _TruthyProof:
    def __bool__(self) -> bool:
        return True


def _loaded_entrypoint_module():
    spec = importlib.util.spec_from_file_location("review_webjob_entrypoint", ENTRYPOINT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "proof",
    [
        "yes",
        "true",
        1,
        0,
        "",
        [True],
        {"ok": True},
        None,
        _TruthyProof(),
    ],
)
def test_entrypoint_rejects_non_boolean_or_non_owned_success_proofs(
    monkeypatch, proof: object
) -> None:
    module = _loaded_entrypoint_module()
    verification = types.SimpleNamespace(
        ok=proof,
        category="success",
        operation="verify_hosted_foundry_agent",
        mode="live",
        local_contract_validated=proof,
        hosted_environment_present=proof,
        managed_identity_attempted=proof,
        managed_identity_authenticated=proof,
        project_access_verified=proof,
        agent_present=proof,
        configured_version_present=proof,
        agent_contract_verified=proof,
        agent_invocation_attempted=False,
        azure_mutation_made=False,
        recommended_next_step="safe",
    )
    invocation = types.SimpleNamespace(
        ok=proof,
        category="success",
        message="safe",
        invocation_attempted=proof,
        agent_output_valid=proof,
        fields_present=("extraction", "urgency", "handoffNote"),
        fictional_data_only=proof,
        recommended_next_step="safe",
    )
    calls: list[str] = []
    monkeypatch.setattr(
        module,
        "_load_operations",
        lambda: (
            types.SimpleNamespace(
                run_hosted_foundry_agent_verification=lambda _mode: verification
            ),
            types.SimpleNamespace(
                run_hosted_foundry_agent_invocation=lambda _mode: (
                    calls.append("invoke") or invocation
                )
            ),
        ),
    )
    output = io.StringIO()
    monkeypatch.setattr(module.sys, "stdout", output)

    assert module.run() != 0
    payload = json.loads(output.getvalue())
    assert payload["ok"] is False
    assert payload["metadata_verification_proven"] is False
    assert payload["invocation_succeeded"] is False


def test_entrypoint_rejects_owned_metadata_result_with_omitted_field(
    monkeypatch,
) -> None:
    module = _loaded_entrypoint_module()

    class HostedFoundryAgentVerificationResult:
        ok = True
        category = "success"
        operation = "verify_hosted_foundry_agent"
        mode = "live"
        local_contract_validated = True

    verification = HostedFoundryAgentVerificationResult()
    verifier = types.SimpleNamespace(
        HostedFoundryAgentVerificationResult=HostedFoundryAgentVerificationResult,
        run_hosted_foundry_agent_verification=lambda _mode: verification,
    )
    invocations: list[str] = []
    monkeypatch.setattr(
        module,
        "_load_operations",
        lambda: (
            verifier,
            types.SimpleNamespace(
                run_hosted_foundry_agent_invocation=lambda _mode: invocations.append(
                    "invoke"
                )
            ),
        ),
    )
    output = io.StringIO()
    monkeypatch.setattr(module.sys, "stdout", output)

    assert module.run() != 0
    assert json.loads(output.getvalue())["ok"] is False
    assert invocations == []


def test_entrypoint_rejects_mapping_that_mimics_owned_result(monkeypatch) -> None:
    module = _loaded_entrypoint_module()
    mapping = {
        "ok": True,
        "category": "success",
        "mode": "live",
        "local_contract_validated": True,
    }
    monkeypatch.setattr(
        module,
        "_load_operations",
        lambda: (
            types.SimpleNamespace(
                run_hosted_foundry_agent_verification=lambda _mode: mapping
            ),
            types.SimpleNamespace(),
        ),
    )
    output = io.StringIO()
    monkeypatch.setattr(module.sys, "stdout", output)

    assert module.run() != 0
    assert json.loads(output.getvalue())["category"] == "metadata_result_malformed"


@pytest.mark.parametrize(
    "relative_path",
    [
        "src",
        "src/app",
        "src/app/operations",
        "src/__init__.py",
        "src/app/__init__.py",
        "src/app/operations/__init__.py",
        "src/app/operations/verify_hosted_foundry_agent.py",
        "src/app/operations/invoke_hosted_foundry_agent.py",
    ],
)
@pytest.mark.parametrize("target_location", ["inside", "outside"])
def test_entrypoint_rejects_symlink_anywhere_in_home_import_chain(
    tmp_path: Path, relative_path: str, target_location: str
) -> None:
    entrypoint, home = _stage(tmp_path)
    root = home / "site/wwwroot"
    target = root / relative_path
    replacement_parent = root if target_location == "inside" else tmp_path
    replacement = replacement_parent / "replacement"
    if target.is_dir():
        shutil.move(str(target), str(replacement))
        target.symlink_to(replacement, target_is_directory=True)
    else:
        replacement.write_text(target.read_text())
        target.unlink()
        target.symlink_to(replacement)

    completed = _run(entrypoint, tmp_path, home=str(home))

    assert completed.returncode == 2
    assert json.loads(completed.stdout)["category"] == "bootstrap_failed"
    assert completed.stderr == ""


@pytest.mark.parametrize("trusted_component", ["home", "site", "wwwroot"])
def test_entrypoint_rejects_symlinked_trusted_parent_directory(
    tmp_path: Path, trusted_component: str
) -> None:
    entrypoint, home = _stage(tmp_path)
    component = {
        "home": home,
        "site": home / "site",
        "wwwroot": home / "site/wwwroot",
    }[trusted_component]
    replacement = tmp_path / f"real-{trusted_component}"
    component.rename(replacement)
    component.symlink_to(replacement, target_is_directory=True)

    completed = _run(entrypoint, tmp_path, home=str(home))

    assert completed.returncode == 2
    assert json.loads(completed.stdout)["category"] == "bootstrap_failed"
