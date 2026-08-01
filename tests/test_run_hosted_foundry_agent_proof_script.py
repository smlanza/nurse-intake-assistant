import importlib
import inspect
import json
from dataclasses import replace

import pytest


def _script():
    return importlib.import_module("scripts.run_hosted_foundry_agent_proof")


def test_check_validates_fixed_module_and_command_without_execution(capsys) -> None:
    script = _script()

    exit_code = script.main(["--check", "--json"])

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["category"] == "check_passed"
    assert payload["mode"] == "check"
    assert payload["execution_boundary"] == "app_service_ssh"
    assert payload["packaged_operation_validated"] is True
    assert payload["remote_command_contract_validated"] is True
    assert payload["command_execution_attempted"] is False
    assert payload["ssh_connection_attempted"] is False
    assert payload["subprocess_attempted"] is False
    assert payload["azure_call_made"] is False
    assert output.endswith("\n") and not output.endswith("\n\n")


def test_repeated_check_is_byte_identical(capsys) -> None:
    script = _script()

    assert script.main(["--check", "--json"]) == 0
    first = capsys.readouterr().out
    assert script.main(["--check", "--json"]) == 0
    second = capsys.readouterr().out

    assert first == second


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["--check"],
        ["--live", "--json"],
        ["--check", "--json", "--command", "whoami"],
        ["--check", "--json", "--module", "unsafe.module"],
        ["--check", "--json", "--interpreter", "/tmp/python"],
    ],
)
def test_cli_exposes_no_live_arbitrary_command_module_or_interpreter_surface(argv) -> None:
    with pytest.raises(SystemExit) as error:
        _script()._parse_args(argv)

    assert error.value.code == 2


def test_remote_command_contract_is_exact_and_application_owned() -> None:
    script = _script()

    assert script.PACKAGED_MODULE == "src.app.operations.prove_hosted_foundry_agent"
    assert script.FIXED_REMOTE_COMMAND == (
        "python",
        "-m",
        "src.app.operations.prove_hosted_foundry_agent",
        "--live",
        "--json",
    )


def test_malformed_exact_type_check_result_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = _script()
    proof = importlib.import_module("src.app.services.hosted_foundry_agent_proof")

    class Operation:
        __name__ = script.PACKAGED_MODULE

        @staticmethod
        def run_hosted_foundry_agent_proof(_mode: str):
            return replace(proof.HostedFoundryAgentProofResult.check_passed(), ok=1)

    monkeypatch.setattr(script.importlib, "import_module", lambda _name: Operation)

    result = script.run_check()

    assert result.proof.ok is False
    assert result.packaged_operation_validated is False
    assert result.remote_command_contract_validated is False


def test_script_has_no_process_ssh_network_or_azure_dependency() -> None:
    source = inspect.getsource(_script())

    for forbidden in (
        "import subprocess",
        "subprocess.",
        "paramiko",
        "pexpect",
        "sshpass",
        "requests",
        "httpx",
        "azure.cli",
        "az webapp",
        "Kudu",
        "WebJob",
    ):
        assert forbidden not in source
