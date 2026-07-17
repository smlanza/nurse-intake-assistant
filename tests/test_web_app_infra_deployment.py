import json
from dataclasses import replace
from pathlib import Path

import pytest

from src.app.services import web_app_infra_deployment as deployment


ROOT = Path(__file__).resolve().parents[1]


class FakeRunner:
    def __init__(
        self,
        result: deployment.CommandResult | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.result = result or deployment.CommandResult(0, '{"changes":[]}', "")
        self.error = error
        self.calls: list[list[str]] = []

    def run(self, args: list[str]) -> deployment.CommandResult:
        assert isinstance(args, list)
        self.calls.append(args)
        if self.error is not None:
            raise self.error
        return self.result


@pytest.fixture
def deployment_request() -> deployment.WebAppInfrastructureDeploymentRequest:
    return deployment.WebAppInfrastructureDeploymentRequest(
        mode="check",
        resource_group="fictional-webapp-rg",
        location="eastus2",
        environment_name="demo",
        project_name="nurse-intake",
        web_app_name="fictional-nurse-intake-web-app",
        cosmos_database_name="nurse-intake",
        cosmos_container_name="cases",
        template_file=ROOT / "infra/main.bicep",
    )


def _setting_block(name: str, value: str) -> str:
    return (
        "        {\n"
        f"          name: '{name}'\n"
        f"          value: '{value}'\n"
        "        }\n"
    )


def _request_with_module(
    deployment_request: deployment.WebAppInfrastructureDeploymentRequest,
    tmp_path: Path,
    module_text: str,
) -> deployment.WebAppInfrastructureDeploymentRequest:
    template = tmp_path / "main.bicep"
    module = tmp_path / "modules/web-app.bicep"
    module.parent.mkdir()
    template.write_text(deployment_request.template_file.read_text())
    module.write_text(module_text)
    return replace(deployment_request, template_file=template)


def _current_module(
    deployment_request: deployment.WebAppInfrastructureDeploymentRequest,
) -> str:
    return (
        deployment_request.template_file.parent / "modules/web-app.bicep"
    ).read_text()


def _append_app_setting(module: str, name: str, value: str) -> str:
    marker = "      ]\n    }\n  }\n"
    assert marker in module
    return module.replace(marker, _setting_block(name, value) + marker, 1)


def test_check_validates_local_contract_without_runner_or_azure_operation(
    deployment_request: deployment.WebAppInfrastructureDeploymentRequest,
) -> None:
    runner = FakeRunner()

    result = deployment.deploy_web_app_infrastructure(
        deployment_request, runner=runner
    )

    assert result.ok is True
    assert result.category == "success"
    assert result.mode == "check"
    assert result.local_validation_passed is True
    assert result.azure_operation_attempted is False
    assert result.what_if_attempted is False
    assert result.deployment_attempted is False
    assert result.deploy_app is True
    assert result.deploy_foundry is False
    assert runner.calls == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("resource_group", ""),
        ("location", "\nwestus"),
        ("environment_name", "--subscription"),
        ("project_name", "ab"),
        ("web_app_name", "unsafe/name"),
        ("cosmos_database_name", "bad?name"),
        ("cosmos_container_name", "-leading-option"),
    ],
)
def test_missing_or_unsafe_arguments_fail_before_runner_call(
    deployment_request: deployment.WebAppInfrastructureDeploymentRequest,
    field: str,
    value: str,
) -> None:
    runner = FakeRunner()

    result = deployment.deploy_web_app_infrastructure(
        replace(deployment_request, mode="live", **{field: value}),
        runner=runner,
    )

    assert result.ok is False
    assert result.category == "invalid_arguments"
    assert result.local_validation_passed is False
    assert result.azure_operation_attempted is False
    assert runner.calls == []


def test_missing_template_and_invalid_local_contract_fail_offline(
    deployment_request: deployment.WebAppInfrastructureDeploymentRequest,
    tmp_path: Path,
) -> None:
    missing = replace(
        deployment_request, template_file=tmp_path / "missing.bicep"
    )
    invalid = tmp_path / "main.bicep"
    invalid.write_text("param deployApp bool = false\n")

    missing_result = deployment.deploy_web_app_infrastructure(missing)
    invalid_result = deployment.deploy_web_app_infrastructure(
        replace(deployment_request, template_file=invalid)
    )

    assert missing_result.category == "local_contract_invalid"
    assert invalid_result.category == "local_contract_invalid"
    assert missing_result.azure_operation_attempted is False
    assert invalid_result.azure_operation_attempted is False


def test_check_rejects_non_mock_hosted_posture(
    deployment_request: deployment.WebAppInfrastructureDeploymentRequest,
    tmp_path: Path,
) -> None:
    template = tmp_path / "main.bicep"
    module = tmp_path / "modules/web-app.bicep"
    module.parent.mkdir()
    template.write_text(deployment_request.template_file.read_text())
    current_module = (
        deployment_request.template_file.parent / "modules/web-app.bicep"
    ).read_text()
    module.write_text(current_module.replace("value: 'mock'", "value: 'live'", 1))

    result = deployment.deploy_web_app_infrastructure(
        replace(deployment_request, template_file=template)
    )

    assert result.category == "local_contract_invalid"
    assert result.azure_operation_attempted is False


def test_exact_safe_hosted_settings_contract_is_shared_with_configuration_verifier(
    deployment_request: deployment.WebAppInfrastructureDeploymentRequest,
) -> None:
    from src.app.services import web_app_configuration_verification as verification
    from src.app.services import web_app_hosting_contract as hosting_contract

    result = deployment.deploy_web_app_infrastructure(deployment_request)

    assert result.ok is True
    assert deployment.SAFE_HOSTED_SETTINGS is hosting_contract.SAFE_HOSTED_SETTINGS
    assert verification.EXPECTED_SAFE_APP_SETTINGS is hosting_contract.SAFE_HOSTED_SETTINGS
    assert dict(hosting_contract.SAFE_HOSTED_SETTINGS) == {
        "APP_MODE": "mock",
        "AI_PROVIDER": "mock",
        "AGENT_PROVIDER": "mock",
        "SPEECH_PROVIDER": "mock",
        "EMAIL_PROVIDER": "mock",
        "SMS_PROVIDER": "mock",
        "DEMO_SUPPRESS_NOTIFICATIONS": "true",
    }


def test_local_contract_rejects_missing_setting(
    deployment_request: deployment.WebAppInfrastructureDeploymentRequest,
    tmp_path: Path,
) -> None:
    module = _current_module(deployment_request).replace(
        _setting_block("APP_MODE", "mock"), "", 1
    )
    request = _request_with_module(deployment_request, tmp_path, module)

    result = deployment.deploy_web_app_infrastructure(request)

    assert result.category == "local_contract_invalid"


def test_local_contract_rejects_extra_setting(
    deployment_request: deployment.WebAppInfrastructureDeploymentRequest,
    tmp_path: Path,
) -> None:
    module = _append_app_setting(
        _current_module(deployment_request), "EXTRA_SETTING", "unsafe"
    )
    request = _request_with_module(deployment_request, tmp_path, module)

    result = deployment.deploy_web_app_infrastructure(request)

    assert result.category == "local_contract_invalid"


def test_local_contract_rejects_duplicate_setting_with_same_value(
    deployment_request: deployment.WebAppInfrastructureDeploymentRequest,
    tmp_path: Path,
) -> None:
    module = _append_app_setting(
        _current_module(deployment_request), "APP_MODE", "mock"
    )
    request = _request_with_module(deployment_request, tmp_path, module)

    result = deployment.deploy_web_app_infrastructure(request)

    assert result.category == "local_contract_invalid"


def test_local_contract_rejects_duplicate_setting_with_conflicting_value(
    deployment_request: deployment.WebAppInfrastructureDeploymentRequest,
    tmp_path: Path,
) -> None:
    module = _append_app_setting(
        _current_module(deployment_request), "APP_MODE", "live"
    )
    request = _request_with_module(deployment_request, tmp_path, module)

    result = deployment.deploy_web_app_infrastructure(request)

    assert result.category == "local_contract_invalid"


def test_commented_out_required_setting_does_not_satisfy_contract(
    deployment_request: deployment.WebAppInfrastructureDeploymentRequest,
    tmp_path: Path,
) -> None:
    block = _setting_block("APP_MODE", "mock")
    commented = "".join(f"// {line}" for line in block.splitlines(keepends=True))
    module = _current_module(deployment_request).replace(block, commented, 1)
    request = _request_with_module(deployment_request, tmp_path, module)

    result = deployment.deploy_web_app_infrastructure(request)

    assert result.category == "local_contract_invalid"


def test_unsafe_override_after_safe_setting_fails_before_runner_call(
    deployment_request: deployment.WebAppInfrastructureDeploymentRequest,
    tmp_path: Path,
) -> None:
    module = _append_app_setting(
        _current_module(deployment_request), "APP_MODE", "live"
    )
    request = replace(
        _request_with_module(deployment_request, tmp_path, module), mode="live"
    )
    runner = FakeRunner()

    result = deployment.deploy_web_app_infrastructure(request, runner=runner)

    assert result.category == "local_contract_invalid"
    assert result.azure_operation_attempted is False
    assert runner.calls == []


@pytest.mark.parametrize(
    ("mode", "operation"),
    [("what-if", "what-if"), ("live", "create")],
)
def test_azure_modes_issue_one_allowlisted_infrastructure_command(
    deployment_request: deployment.WebAppInfrastructureDeploymentRequest,
    mode: str,
    operation: str,
) -> None:
    runner = FakeRunner()

    result = deployment.deploy_web_app_infrastructure(
        replace(deployment_request, mode=mode),
        runner=runner,
    )

    assert result.ok is True
    assert len(runner.calls) == 1
    command = runner.calls[0]
    assert command[:4] == ["az", "deployment", "group", operation]
    assert command[command.index("--resource-group") + 1] == deployment_request.resource_group
    assert command[command.index("--template-file") + 1] == str(
        deployment_request.template_file
    )
    parameters = command[command.index("--parameters") + 1 :]
    assert "deployApp=true" in parameters
    assert "deployFoundry=false" in parameters
    assert f"environmentName={deployment_request.environment_name}" in parameters
    assert f"location={deployment_request.location}" in parameters
    assert f"projectName={deployment_request.project_name}" in parameters
    assert f"webAppName={deployment_request.web_app_name}" in parameters
    assert f"cosmosDatabaseName={deployment_request.cosmos_database_name}" in parameters
    assert f"cosmosContainerName={deployment_request.cosmos_container_name}" in parameters
    assert result.what_if_attempted is (mode == "what-if")
    assert result.deployment_attempted is (mode == "live")


def test_what_if_command_requests_machine_readable_json(
    deployment_request: deployment.WebAppInfrastructureDeploymentRequest,
) -> None:
    runner = FakeRunner()

    deployment.deploy_web_app_infrastructure(
        replace(deployment_request, mode="what-if"), runner=runner
    )

    command = runner.calls[0]
    assert "--no-pretty-print" in command
    assert command[command.index("--result-format") + 1] == "ResourceIdOnly"
    assert command[command.index("--output") + 1] == "json"


def test_live_uses_a_deterministic_deployment_name(
    deployment_request: deployment.WebAppInfrastructureDeploymentRequest,
) -> None:
    first = FakeRunner()
    second = FakeRunner()

    deployment.deploy_web_app_infrastructure(
        replace(deployment_request, mode="live"), runner=first
    )
    deployment.deploy_web_app_infrastructure(
        replace(deployment_request, mode="live"), runner=second
    )

    first_name = first.calls[0][first.calls[0].index("--name") + 1]
    second_name = second.calls[0][second.calls[0].index("--name") + 1]
    assert first_name == second_name == "nurse-intake-demo-web-app-infra"


def test_commands_never_couple_resource_group_code_rbac_foundry_or_cleanup(
    deployment_request: deployment.WebAppInfrastructureDeploymentRequest,
) -> None:
    for mode in ("what-if", "live"):
        runner = FakeRunner()
        deployment.deploy_web_app_infrastructure(
            replace(deployment_request, mode=mode), runner=runner
        )
        assert runner.calls[0][:3] != ["az", "group", "create"]
        assert runner.calls[0][:3] != ["az", "group", "delete"]
        command = " ".join(runner.calls[0]).lower()
        for forbidden in (
            "webapp deploy",
            "config appsettings",
            "role assignment",
            "foundry agent",
            "invoke",
        ):
            assert forbidden not in command


def test_missing_cli_and_nonzero_results_are_sanitized_and_actionable(
    deployment_request: deployment.WebAppInfrastructureDeploymentRequest,
) -> None:
    for command_result, expected_category in (
        (deployment.CommandResult(127, "subscription-id", "secret path"), "azure_cli_unavailable"),
        (deployment.CommandResult(1, "tenant-id", "access-token"), "azure_operation_failed"),
    ):
        result = deployment.deploy_web_app_infrastructure(
            replace(deployment_request, mode="live"),
            runner=FakeRunner(command_result),
        )
        rendered = json.dumps(result.to_json_dict())
        assert result.category == expected_category
        assert result.ok is False
        assert result.azure_operation_attempted is True
        for forbidden in (
            "subscription-id",
            "tenant-id",
            "secret path",
            "access-token",
        ):
            assert forbidden not in rendered


def test_unexpected_runner_error_is_sanitized(
    deployment_request: deployment.WebAppInfrastructureDeploymentRequest,
) -> None:
    result = deployment.deploy_web_app_infrastructure(
        replace(deployment_request, mode="what-if"),
        runner=FakeRunner(error=RuntimeError("credential and stack trace")),
    )

    rendered = json.dumps(result.to_json_dict())
    assert result.category == "unexpected_error"
    assert result.azure_operation_attempted is True
    assert "credential" not in rendered
    assert "stack trace" not in rendered


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ([], (0, 0, 0, 0, 0, 0, 0)),
        ([{"changeType": "Create"}], (1, 0, 0, 0, 0, 0, 0)),
        ([{"changeType": "modify"}], (0, 1, 0, 0, 0, 0, 0)),
        ([{"changeType": "DELETE"}], (0, 0, 1, 0, 0, 0, 0)),
        ([{"changeType": "NoChange"}], (0, 0, 0, 1, 0, 0, 0)),
        (
            [
                {"changeType": "Create"},
                {"changeType": "Modify"},
                {"changeType": "Delete"},
                {"changeType": "NoChange"},
                {"changeType": "Ignore"},
                {"changeType": "Deploy"},
                {"changeType": "Unsupported"},
            ],
            (1, 1, 1, 1, 1, 1, 1),
        ),
        ([{"changeType": "FutureChangeType"}], (0, 0, 0, 0, 0, 0, 1)),
    ],
)
def test_what_if_json_is_reduced_to_sanitized_change_counts(
    deployment_request: deployment.WebAppInfrastructureDeploymentRequest,
    changes: list[dict[str, str]],
    expected: tuple[int, int, int, int, int, int, int],
) -> None:
    raw = json.dumps(
        {
            "changes": [
                {
                    **change,
                    "resourceId": "/subscriptions/raw-subscription/resourceGroups/raw-rg",
                }
                for change in changes
            ]
        }
    )
    runner = FakeRunner(deployment.CommandResult(0, raw, "raw stderr secret"))

    result = deployment.deploy_web_app_infrastructure(
        replace(deployment_request, mode="what-if"), runner=runner
    )

    assert result.ok is True
    assert result.what_if_summary_available is True
    assert (
        result.create_count,
        result.modify_count,
        result.delete_count,
        result.no_change_count,
        result.ignore_count,
        result.deploy_count,
        result.unsupported_count,
    ) == expected
    assert result.delete_detected is (expected[2] > 0)
    rendered = json.dumps(result.to_json_dict())
    for forbidden in (
        "raw-subscription",
        "raw-rg",
        "resourceId",
        "raw stderr secret",
        "changes",
    ):
        assert forbidden not in rendered


@pytest.mark.parametrize(
    "stdout",
    [
        "not-json",
        '{}',
        '{"changes":{}}',
    ],
)
def test_invalid_what_if_json_structure_fails_safely(
    deployment_request: deployment.WebAppInfrastructureDeploymentRequest,
    stdout: str,
) -> None:
    runner = FakeRunner(deployment.CommandResult(0, stdout, "secret stderr"))

    result = deployment.deploy_web_app_infrastructure(
        replace(deployment_request, mode="what-if"), runner=runner
    )

    rendered = json.dumps(result.to_json_dict())
    assert result.ok is False
    assert result.category == "what_if_parse_failed"
    assert result.what_if_summary_available is False
    assert result.create_count is None
    assert result.modify_count is None
    assert result.delete_count is None
    assert result.no_change_count is None
    assert "secret stderr" not in rendered
    assert "not-json" not in rendered


def test_nonzero_what_if_result_remains_a_sanitized_failure(
    deployment_request: deployment.WebAppInfrastructureDeploymentRequest,
) -> None:
    runner = FakeRunner(
        deployment.CommandResult(1, "raw stdout resource ID", "raw access token")
    )

    result = deployment.deploy_web_app_infrastructure(
        replace(deployment_request, mode="what-if"), runner=runner
    )

    rendered = json.dumps(result.to_json_dict())
    assert result.category == "azure_operation_failed"
    assert result.ok is False
    assert result.what_if_summary_available is False
    assert "resource ID" not in rendered
    assert "access token" not in rendered


@pytest.mark.parametrize("change_type", ["Delete", "Create"])
def test_successful_what_if_requires_explicit_review_before_live(
    deployment_request: deployment.WebAppInfrastructureDeploymentRequest,
    change_type: str,
) -> None:
    runner = FakeRunner(
        deployment.CommandResult(
            0, json.dumps({"changes": [{"changeType": change_type}]}), ""
        )
    )

    result = deployment.deploy_web_app_infrastructure(
        replace(deployment_request, mode="what-if"), runner=runner
    )

    next_step = result.recommended_next_step.lower()
    assert "review" in next_step
    assert "explicit" in next_step
    assert "live" in next_step
    if change_type == "Delete":
        assert "delet" in next_step


def test_json_result_is_exactly_the_approved_sanitized_projection(
    deployment_request: deployment.WebAppInfrastructureDeploymentRequest,
) -> None:
    result = deployment.deploy_web_app_infrastructure(deployment_request)

    assert set(result.to_json_dict()) == {
        "ok",
        "category",
        "mode",
        "message",
        "resource_group",
        "web_app_name",
        "deployment_name",
        "local_validation_passed",
        "azure_operation_attempted",
        "what_if_attempted",
        "deployment_attempted",
        "deploy_app",
        "deploy_foundry",
        "create_count",
        "modify_count",
        "delete_count",
        "no_change_count",
        "ignore_count",
        "deploy_count",
        "unsupported_count",
        "delete_detected",
        "what_if_summary_available",
        "recommended_next_step",
    }


def test_success_messages_are_mode_specific_and_never_claim_readiness(
    deployment_request: deployment.WebAppInfrastructureDeploymentRequest,
) -> None:
    results = {
        "check": deployment.deploy_web_app_infrastructure(deployment_request),
        "what-if": deployment.deploy_web_app_infrastructure(
            replace(deployment_request, mode="what-if"), runner=FakeRunner()
        ),
        "live": deployment.deploy_web_app_infrastructure(
            replace(deployment_request, mode="live"), runner=FakeRunner()
        ),
    }

    assert "local" in results["check"].message.lower()
    assert "validation" in results["check"].message.lower()
    assert "preview" in results["what-if"].message.lower()
    assert "accepted" in results["live"].message.lower()
    assert "deployment request" in results["live"].message.lower()
    for result in results.values():
        assert "startup" not in result.message.lower()
        assert "ready" not in result.message.lower()


def test_successful_live_result_directs_operator_to_separate_configuration_check(
    deployment_request: deployment.WebAppInfrastructureDeploymentRequest,
) -> None:
    result = deployment.deploy_web_app_infrastructure(
        replace(deployment_request, mode="live"), runner=FakeRunner()
    )

    next_step = result.recommended_next_step
    assert "verify_web_app_configuration.py" in next_step
    assert "startup" not in next_step.lower()
    assert "readiness" not in next_step.lower()
