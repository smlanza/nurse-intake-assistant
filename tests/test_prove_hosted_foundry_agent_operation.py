import importlib
import inspect
import json
from pathlib import Path

import pytest

from src.app.services.web_app_package import plan_web_app_package


ROOT = Path(__file__).resolve().parents[1]


def _operation():
    return importlib.import_module("src.app.operations.prove_hosted_foundry_agent")


def test_check_emits_exactly_one_newline_json_without_live_construction(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    operation = _operation()

    exit_code = operation.main(["--check", "--json"])

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert exit_code == 0
    assert output.endswith("\n") and not output.endswith("\n\n")
    assert payload["category"] == "check_passed"
    assert payload["command_execution_attempted"] is False
    assert payload["azure_call_made"] is False


def test_repeated_check_output_is_byte_identical(capsys) -> None:
    operation = _operation()

    assert operation.main(["--check", "--json"]) == 0
    first = capsys.readouterr().out
    assert operation.main(["--check", "--json"]) == 0
    second = capsys.readouterr().out

    assert first == second


def test_live_delegates_once_to_combined_proof_without_exposing_settings(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    operation = _operation()
    proof = importlib.import_module("src.app.services.hosted_foundry_agent_proof")
    calls: list[object] = []

    class Service:
        def prove(self, request: object):
            calls.append(request)
            return proof.HostedFoundryAgentProofResult.success()

    class Settings:
        azure_ai_foundry_agent_project_endpoint = "https://secret.example/project"
        azure_ai_foundry_agent_endpoint = "https://secret.example/agent"
        azure_ai_foundry_agent_name = "secret-agent"
        azure_ai_foundry_agent_version = "secret-version"
        azure_ai_foundry_model_deployment_name = "secret-model"
        azure_ai_foundry_managed_identity_client_id = None

    monkeypatch.setattr(operation, "AppSettings", Settings)
    monkeypatch.setattr(operation, "_create_proof_service", Service)

    exit_code = operation.main(["--live", "--json"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert len(calls) == 1
    for secret in ("secret.example", "secret-agent", "secret-version", "secret-model"):
        assert secret not in output


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["--check"],
        ["--live"],
        ["--check", "--live", "--json"],
        ["--live", "--json", "--prompt", "patient text"],
        ["--live", "--json", "--agent", "override"],
        ["--live", "--json", "--retry", "2"],
    ],
)
def test_cli_requires_exact_mode_json_and_rejects_arbitrary_inputs(argv) -> None:
    with pytest.raises(SystemExit) as error:
        _operation()._parse_args(argv)

    assert error.value.code == 2


def test_import_and_help_are_inert(capsys) -> None:
    operation = _operation()

    with pytest.raises(SystemExit) as error:
        operation.main(["--help"])

    assert error.value.code == 0
    assert "synchronous" in capsys.readouterr().out.casefold()


def test_operation_and_service_are_selected_by_ordinary_package_allowlist() -> None:
    plan = plan_web_app_package(ROOT)

    assert "src/app/operations/prove_hosted_foundry_agent.py" in plan.member_names
    assert "src/app/services/hosted_foundry_agent_proof.py" in plan.member_names
    assert all(not name.startswith("App_Data/") for name in plan.member_names)


def test_operation_has_no_route_transport_or_side_effect_surface() -> None:
    source = inspect.getsource(_operation())

    for forbidden in (
        "CaseProcessingService",
        "case_repository",
        "notification",
        "UrgencyRulesService",
        "subprocess",
        "ssh",
        "Kudu",
        "WebJob",
        "retry",
        "poll",
    ):
        assert forbidden not in source
