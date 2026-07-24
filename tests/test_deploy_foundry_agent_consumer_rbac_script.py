import importlib
import json
import subprocess
import sys
from types import SimpleNamespace

import pytest

from src.app.services import foundry_agent_consumer_rbac_deployment as rbac_deployment


VALID_ARGUMENTS = [
    "--config",
    ".env.daily-azure.local",
    "--readiness-receipt",
    ".artifacts/daily-azure-rebuild/readiness-receipt.json",
]
APPROVED_ARGUMENTS = [
    "--subscription-id",
    "00000000-0000-0000-0000-000000000001",
    "--approved-foundry-project-resource-id",
    "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/fictional-resource-group/providers/Microsoft.CognitiveServices/accounts/fictional-foundry-account/projects/fictional-foundry-project",
    "--approved-web-app-principal-id",
    "00000000-0000-0000-0000-000000000002",
    "--approved-role-assignment-name",
    "16f4c29e-cc74-5373-8223-e478a3a63851",
]


def _approved_evidence():
    return rbac_deployment.FoundryAgentConsumerRbacDeploymentEvidence(
        subscription_id=APPROVED_ARGUMENTS[1],
        foundry_project_resource_id=APPROVED_ARGUMENTS[3],
        web_app_principal_id=APPROVED_ARGUMENTS[5],
        role_definition_id=(
            f"/subscriptions/{APPROVED_ARGUMENTS[1]}/providers/"
            "Microsoft.Authorization/roleDefinitions/"
            f"{rbac_deployment.CONSUMER_ROLE_GUID}"
        ),
        role_assignment_name=APPROVED_ARGUMENTS[7],
        deployment_name=rbac_deployment.DEPLOYMENT_NAME,
    )


def _exact_create_preview() -> dict[str, object]:
    evidence = _approved_evidence()
    return {
        "changes": [
            {
                "changeType": "Create",
                "resourceType": rbac_deployment.ROLE_ASSIGNMENT_RESOURCE_TYPE,
                "resourceId": (
                    f"{evidence.foundry_project_resource_id}/providers/"
                    f"{rbac_deployment.ROLE_ASSIGNMENT_RESOURCE_TYPE}/"
                    f"{evidence.role_assignment_name}"
                ),
                "after": {
                    "properties": {
                        "principalId": evidence.web_app_principal_id,
                        "roleDefinitionId": evidence.role_definition_id,
                    }
                },
            }
        ],
        "tenantId": "raw-tenant",
    }


def _exact_manual_review_preview() -> dict[str, object]:
    evidence = _approved_evidence()
    ignored = rbac_deployment._expected_daily_ignore_resources(
        evidence,
        "fictional-nurse-intake-web-app",
    )
    changes = [
        {
            "changeType": "Ignore",
            "resourceType": expected.resource_type,
            "resourceId": rbac_deployment._expected_resource_id(
                evidence.subscription_id,
                expected,
            ),
        }
        for expected in ignored
    ]
    changes.append(
        {
            "changeType": "Unsupported",
            "resourceType": rbac_deployment.ROLE_ASSIGNMENT_RESOURCE_TYPE,
            "resourceId": (
                f"{evidence.foundry_project_resource_id}/providers/"
                f"{rbac_deployment.ROLE_ASSIGNMENT_RESOURCE_TYPE}/"
                f"{evidence.role_assignment_name}"
            ),
            "after": {
                "properties": {
                    "principalId": evidence.web_app_principal_id,
                    "roleDefinitionId": evidence.role_definition_id,
                }
            },
        }
    )
    return {"changes": changes, "tenantId": "raw-tenant"}


def _script():
    return importlib.import_module("scripts.deploy_foundry_agent_consumer_rbac")


def _receipt():
    return SimpleNamespace(
        requested_foundry_account_name="fictional-foundry-base",
        foundry_account_name="fictional-foundry-account",
        foundry_account_name_generated=True,
        resource_group="fictional-resource-group",
        web_app_name="fictional-nurse-intake-web-app",
        foundry_project_name="fictional-foundry-project",
    )


def _patch_valid_handoff(
    script,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        script,
        "load_daily_azure_config",
        lambda path, repository_root: SimpleNamespace(
            foundry_account_name="fictional-foundry-base"
        ),
    )
    monkeypatch.setattr(
        script,
        "load_matching_daily_azure_readiness_receipt",
        lambda path, config: _receipt(),
    )


def test_import_performs_no_azure_operation(monkeypatch: pytest.MonkeyPatch) -> None:
    sys.modules.pop("scripts.deploy_foundry_agent_consumer_rbac", None)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("import must not run Azure CLI"),
    )

    _script()


def test_modes_are_required_and_mutually_exclusive() -> None:
    script = _script()
    for argv in (
        VALID_ARGUMENTS,
        ["--check", "--what-if", *VALID_ARGUMENTS],
        ["--check", "--live", *VALID_ARGUMENTS],
        ["--what-if", "--live", *VALID_ARGUMENTS],
    ):
        with pytest.raises(SystemExit):
            script.main(argv)


def test_daily_config_is_required() -> None:
    script = _script()

    with pytest.raises(SystemExit):
        script.main(["--check"])


def test_role_definition_override_is_not_a_cli_option() -> None:
    script = _script()

    with pytest.raises(SystemExit):
        script.main(
            [
                "--check",
                *VALID_ARGUMENTS,
                "--role-definition-id",
                "owner-role-id",
            ]
        )


def test_check_is_offline_and_prints_sanitized_json(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script = _script()
    monkeypatch.setattr(
        script,
        "_create_azure_cli_runner",
        lambda: pytest.fail("check must not construct a runner"),
    )
    _patch_valid_handoff(script, monkeypatch)

    exit_code = script.main(["--check", "--json", *VALID_ARGUMENTS])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["category"] == "success"
    assert payload["template_valid"] is True
    assert payload["azure_operation_attempted"] is False
    assert payload["deployment_request_accepted"] is False


def test_unsafe_input_fails_before_runner_construction(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script = _script()
    constructed: list[bool] = []
    monkeypatch.setattr(
        script, "_create_azure_cli_runner", lambda: constructed.append(True)
    )
    monkeypatch.setattr(
        script,
        "load_daily_azure_config",
        lambda path, repository_root: (_ for _ in ()).throw(
            script.ConfigValidationError("invalid_configuration")
        ),
    )

    exit_code = script.main(["--live", "--json", *VALID_ARGUMENTS])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert payload["category"] == "invalid_configuration"
    assert payload["azure_operation_attempted"] is False
    assert constructed == []


@pytest.mark.parametrize("mode", ["--what-if", "--live"])
def test_azure_modes_lazily_use_exactly_one_injected_runner(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    mode: str,
) -> None:
    script = _script()

    class FakeRunner:
        def __init__(self) -> None:
            self.calls: list[list[str]] = []

        def run(self, args: list[str]):
            self.calls.append(args)
            return script.CommandResult(
                0,
                json.dumps(_exact_create_preview()),
                "raw stderr",
            )

    runner = FakeRunner()
    monkeypatch.setattr(script, "_create_azure_cli_runner", lambda: runner)
    _patch_valid_handoff(script, monkeypatch)
    monkeypatch.setattr(
        script,
        "_account_matches_handoff",
        lambda runner, **kwargs: True,
    )
    monkeypatch.setattr(
        script,
        "_fresh_evidence",
        lambda runner, **kwargs: (_approved_evidence(), None),
    )
    if mode == "--live":
        monkeypatch.setattr(
            script,
            "prompt_for_rbac_approval",
            lambda: True,
        )
        monkeypatch.setattr(
            script,
            "verify_foundry_agent_consumer_rbac",
            lambda request, runner: SimpleNamespace(
                ok=True,
                category="success",
                web_app_identity_present=True,
                foundry_project_scope_resolved=True,
                consumer_assignment_present=True,
                consumer_assignment_scope_matches=True,
                consumer_role_matches=True,
                matching_assignment_count=1,
            ),
        )

    exit_code = script.main([mode, "--json", *VALID_ARGUMENTS])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert len(runner.calls) == (2 if mode == "--live" else 1)
    assert "raw-tenant" not in output
    assert "raw stderr" not in output


def test_non_json_what_if_prints_all_sanitized_counts_and_manual_review_warning(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script = _script()

    class FakeRunner:
        def run(self, _args: list[str]):
            return script.CommandResult(
                0,
                json.dumps(_exact_manual_review_preview()),
                "raw stderr",
            )

    monkeypatch.setattr(script, "_create_azure_cli_runner", FakeRunner)
    _patch_valid_handoff(script, monkeypatch)
    monkeypatch.setattr(
        script,
        "_account_matches_handoff",
        lambda runner, **kwargs: True,
    )
    monkeypatch.setattr(
        script,
        "_fresh_evidence",
        lambda runner, **kwargs: (_approved_evidence(), None),
    )

    exit_code = script.main(["--what-if", *VALID_ARGUMENTS])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "preview" in output.lower()
    assert "creates: 0" in output.lower()
    assert "modifies: 0" in output.lower()
    assert "deletes: 0" in output.lower()
    assert "unchanged: 0" in output.lower()
    assert "ignored: 10" in output.lower()
    assert "deploy-uncertain: 0" in output.lower()
    assert "unsupported: 1" in output.lower()
    assert "manual review" in output.lower()
    assert "raw-tenant" not in output
    assert "raw stderr" not in output


def test_subprocess_runner_uses_argument_list_without_shell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = _script()
    captured: list[tuple[object, dict[str, object]]] = []

    class Completed:
        returncode = 0
        stdout = "raw stdout"
        stderr = "raw stderr"

    def fake_run(args: object, **kwargs: object) -> Completed:
        captured.append((args, kwargs))
        return Completed()

    monkeypatch.setattr(script.subprocess, "run", fake_run)
    args = ["az", "deployment", "group", "what-if"]

    result = script.SubprocessAzureCliRunner().run(args)

    assert result == script.CommandResult(0, "raw stdout", "raw stderr")
    assert captured == [
        (
            args,
            {
                "shell": False,
                "capture_output": True,
                "text": True,
                "check": False,
            },
        )
    ]


def test_subprocess_runner_maps_missing_azure_cli_to_sanitized_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = _script()
    monkeypatch.setattr(
        script.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            FileNotFoundError("secret executable path")
        ),
    )

    result = script.SubprocessAzureCliRunner().run(["az", "version"])

    assert result == script.CommandResult(127, "", "")
