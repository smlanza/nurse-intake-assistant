import json
from dataclasses import replace
from pathlib import Path

import pytest

from src.app.services import web_app_infra_deployment as deployment
from src.app.services.daily_azure_environment_rebuild import (
    _plan_from_object,
    safe_guided_plan,
)


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
        enable_hosted_foundry_verifier=True,
        hosted_verifier_project_endpoint=(
            "https://fictional.services.ai.azure.com/api/projects/demo"
        ),
        hosted_verifier_stable_agent_endpoint=(
            "https://fictional.services.ai.azure.com/api/projects/demo/agents/"
            "fictional-agent/endpoint/protocols/openai"
        ),
        hosted_verifier_agent_name="fictional-agent",
        hosted_verifier_agent_version="7",
        hosted_verifier_model_deployment_name="fictional-model",
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
    validation_name = "hosted-foundry-verifier-config-validation.bicep"
    validation_source = deployment_request.template_file.parent / "modules" / validation_name
    (module.parent / validation_name).write_text(validation_source.read_text())
    return replace(deployment_request, template_file=template)


def _current_module(
    deployment_request: deployment.WebAppInfrastructureDeploymentRequest,
) -> str:
    return (
        deployment_request.template_file.parent / "modules/web-app.bicep"
    ).read_text()


def _append_app_setting(module: str, name: str, value: str) -> str:
    marker = "      ], hostedFoundryVerifierAppSettings)\n"
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
    assert result.hosted_verifier_configuration_supplied is True
    assert runner.calls == []


def test_ordinary_web_app_deployment_defaults_hosted_verifier_to_disabled(
    deployment_request: deployment.WebAppInfrastructureDeploymentRequest,
) -> None:
    request = replace(
        deployment_request,
        enable_hosted_foundry_verifier=False,
        hosted_verifier_project_endpoint=None,
        hosted_verifier_stable_agent_endpoint=None,
        hosted_verifier_agent_name=None,
        hosted_verifier_agent_version=None,
        hosted_verifier_model_deployment_name=None,
    )

    result = deployment.deploy_web_app_infrastructure(request)

    assert result.ok is True
    assert result.hosted_verifier_configuration_supplied is False


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
        ("hosted_verifier_project_endpoint", ""),
        ("hosted_verifier_stable_agent_endpoint", "not-an-endpoint"),
        ("hosted_verifier_agent_name", "different-agent"),
        ("hosted_verifier_agent_version", " "),
        ("hosted_verifier_model_deployment_name", "\nunsafe"),
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
    validation_name = "hosted-foundry-verifier-config-validation.bicep"
    validation_source = deployment_request.template_file.parent / "modules" / validation_name
    (module.parent / validation_name).write_text(validation_source.read_text())

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
    assert tuple(hosting_contract.HOSTED_VERIFIER_SETTING_NAMES) == (
        "AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT",
        "AZURE_AI_FOUNDRY_AGENT_ENDPOINT",
        "AZURE_AI_FOUNDRY_AGENT_NAME",
        "AZURE_AI_FOUNDRY_AGENT_VERSION",
        "AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT_NAME",
    )


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
    assert (
        f"resourceNameSuffix={deployment._resource_name_suffix(deployment_request)}"
        in parameters
    )
    hosted_parameter = next(
        parameter
        for parameter in parameters
        if parameter.startswith("hostedFoundryVerifierConfiguration=")
    )
    assert json.loads(hosted_parameter.split("=", 1)[1]) == {
        "mode": "enabled",
        "projectEndpoint": deployment_request.hosted_verifier_project_endpoint,
        "agentEndpoint": deployment_request.hosted_verifier_stable_agent_endpoint,
        "agentName": deployment_request.hosted_verifier_agent_name,
        "agentVersion": deployment_request.hosted_verifier_agent_version,
        "modelDeploymentName": deployment_request.hosted_verifier_model_deployment_name,
    }
    assert not any(parameter.startswith("hostedVerifier") for parameter in parameters)
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
        "raw stderr secret",
        "changes",
    ):
        assert forbidden not in rendered


def _web_app_topology_changes(
    request: deployment.WebAppInfrastructureDeploymentRequest,
) -> list[dict[str, str]]:
    suffix = deployment._resource_name_suffix(request)
    project_environment = f"{request.project_name}-{request.environment_name}"
    account_name = f"{project_environment}-{suffix}".lower()
    plan_name = f"{project_environment}-plan-{suffix}".lower()[:40]
    root = (
        f"/subscriptions/private-sub/resourceGroups/{request.resource_group}/providers"
    )
    account = f"{root}/Microsoft.DocumentDB/databaseAccounts/{account_name}"
    return [
        {"changeType": "Create", "resourceId": account},
        {
            "changeType": "Create",
            "resourceId": f"{account}/sqlDatabases/{request.cosmos_database_name}",
        },
        {
            "changeType": "Create",
            "resourceId": (
                f"{account}/sqlDatabases/{request.cosmos_database_name}/containers/"
                f"{request.cosmos_container_name}"
            ),
        },
        {
            "changeType": "Create",
            "resourceId": f"{root}/Microsoft.Storage/storageAccounts/st{suffix}",
        },
        {
            "changeType": "Create",
            "resourceId": (
                f"{root}/Microsoft.OperationalInsights/workspaces/"
                f"{project_environment}-logs-{suffix}"
            ),
        },
        {
            "changeType": "Create",
            "resourceId": (
                f"{root}/Microsoft.Insights/components/"
                f"{project_environment}-appi-{suffix}"
            ),
        },
        {
            "changeType": "Create",
            "resourceId": f"{root}/Microsoft.Web/serverfarms/{plan_name}",
        },
        {
            "changeType": "Create",
            "resourceId": f"{root}/Microsoft.Web/sites/{request.web_app_name}",
        },
    ]


def _web_app_nested_deployment_ignores(
    request: deployment.WebAppInfrastructureDeploymentRequest,
) -> list[dict[str, object]]:
    root = (
        f"/subscriptions/private-sub/resourceGroups/{request.resource_group}/providers/"
        "Microsoft.Resources/deployments"
    )
    return [
        {
            "changeType": "Ignore",
            "resourceId": f"{root}/{name}",
            "before": {"id": "private-before"},
            "after": {"id": "private-after"},
            "delta": {"changes": []},
        }
        for name in ("web-app", "hosted-foundry-verifier-validation")
    ]


def test_web_app_adapter_accepts_only_the_exact_expected_topology(
    deployment_request: deployment.WebAppInfrastructureDeploymentRequest,
) -> None:
    changes = _web_app_topology_changes(deployment_request)
    runner = FakeRunner(
        deployment.CommandResult(0, json.dumps({"changes": changes}), "")
    )

    result = deployment.deploy_web_app_infrastructure(
        replace(deployment_request, mode="what-if"), runner=runner
    )

    assert result.exact_topology_match is True
    assert all(change.approved_boundary for change in result.change_evidence)
    assert all(
        "diagnostic" not in change
        for change in result.to_json_dict()["change_evidence"]
    )


def test_web_app_adapter_accepts_exact_topology_with_bounded_module_ignores(
    deployment_request: deployment.WebAppInfrastructureDeploymentRequest,
) -> None:
    changes = [
        *_web_app_topology_changes(deployment_request),
        *_web_app_nested_deployment_ignores(deployment_request),
    ]
    runner = FakeRunner(
        deployment.CommandResult(0, json.dumps({"changes": changes}), "")
    )

    result = deployment.deploy_web_app_infrastructure(
        replace(deployment_request, mode="what-if"), runner=runner
    )

    expected = result.change_evidence[:8]
    ignores = result.change_evidence[8:]
    assert result.exact_topology_match is True
    assert all(change.expected_multiplicity_match for change in expected)
    assert all(change.approved_boundary for change in expected)
    assert [change.logical_category for change in ignores] == [
        "web_app_module_deployment",
        "hosted_verifier_validation_deployment",
    ]
    assert all(change.approved_boundary for change in ignores)
    assert all(change.expected_identity_match for change in ignores)
    assert all(change.expected_parent_match for change in ignores)
    assert all(change.expected_scope_match for change in ignores)
    serialized = json.dumps(result.to_json_dict()["change_evidence"])
    for forbidden in (
        "private-sub",
        deployment_request.resource_group,
        "web-app",
        "hosted-foundry-verifier-validation",
        "private-before",
        "private-after",
    ):
        assert forbidden not in serialized
    assert safe_guided_plan(
        _plan_from_object(result),
        expected_boundary="web_app",
        require_create=True,
    ) is True


def test_expected_ignore_identities_are_derived_from_bicep_module_names(
    deployment_request: deployment.WebAppInfrastructureDeploymentRequest,
    tmp_path: Path,
) -> None:
    request = _request_with_module(
        deployment_request,
        tmp_path,
        _current_module(deployment_request).replace(
            "name: 'hosted-foundry-verifier-validation'",
            "name: 'fictional-validation-v2'",
            1,
        ),
    )
    request.template_file.write_text(
        request.template_file.read_text().replace(
            "name: 'web-app'", "name: 'fictional-web-app-v2'", 1
        )
    )
    root = (
        f"/subscriptions/private-sub/resourceGroups/{request.resource_group}/providers/"
        "Microsoft.Resources/deployments"
    )
    changes = [
        *_web_app_topology_changes(request),
        {
            "changeType": "Ignore",
            "resourceId": f"{root}/fictional-web-app-v2",
        },
        {
            "changeType": "Ignore",
            "resourceId": f"{root}/fictional-validation-v2",
        },
    ]

    result = deployment.deploy_web_app_infrastructure(
        replace(request, mode="what-if"),
        runner=FakeRunner(
            deployment.CommandResult(0, json.dumps({"changes": changes}), "")
        ),
    )

    assert result.exact_topology_match is True
    assert all(change.approved_boundary for change in result.change_evidence)


@pytest.mark.parametrize(
    "case",
    [
        "one",
        "three",
        "duplicate",
        "unrelated-deployment",
        "malformed-id",
        "missing-subscription",
        "missing-resource-group",
        "wrong-resource-group",
        "wrong-subscription",
        "wrong-provider",
        "wrong-resource-type",
        "subscription-scope",
        "wrong-name",
        "wrong-action",
        "application-ignore",
    ],
)
def test_web_app_adapter_rejects_inexact_identified_deployment_ignores(
    deployment_request: deployment.WebAppInfrastructureDeploymentRequest,
    case: str,
) -> None:
    expected = _web_app_nested_deployment_ignores(deployment_request)
    changes: list[dict[str, object]] = [
        *_web_app_topology_changes(deployment_request),
        *expected,
    ]
    first = changes[8]
    second = changes[9]
    if case == "one":
        changes.pop()
    elif case == "three":
        changes.append(dict(first))
    elif case == "duplicate":
        changes[9] = dict(first)
    elif case in {"unrelated-deployment", "wrong-name"}:
        second["resourceId"] = str(second["resourceId"]).replace(
            "hosted-foundry-verifier-validation", "unrelated-deployment"
        )
    elif case == "malformed-id":
        second["resourceId"] = "not-an-arm-resource-id"
    elif case == "missing-subscription":
        second["resourceId"] = (
            f"/resourceGroups/{deployment_request.resource_group}/providers/"
            "Microsoft.Resources/deployments/hosted-foundry-verifier-validation"
        )
    elif case == "missing-resource-group":
        second["resourceId"] = (
            "/subscriptions/private-sub/providers/Microsoft.Resources/deployments/"
            "hosted-foundry-verifier-validation"
        )
    elif case == "wrong-resource-group":
        second["resourceId"] = str(second["resourceId"]).replace(
            deployment_request.resource_group, "wrong-resource-group"
        )
    elif case == "wrong-subscription":
        second["resourceId"] = str(second["resourceId"]).replace(
            "private-sub", "other-private-sub"
        )
    elif case == "wrong-provider":
        second["resourceId"] = str(second["resourceId"]).replace(
            "Microsoft.Resources", "Microsoft.KeyVault"
        )
    elif case == "wrong-resource-type":
        second["resourceId"] = str(second["resourceId"]).replace(
            "/deployments/", "/deploymentScripts/"
        )
    elif case == "subscription-scope":
        second["resourceId"] = (
            "/subscriptions/private-sub/providers/Microsoft.Resources/deployments/"
            "hosted-foundry-verifier-validation"
        )
    elif case == "wrong-action":
        second["changeType"] = "Create"
    elif case == "application-ignore":
        changes[9] = {**changes[0], "changeType": "Ignore"}

    runner = FakeRunner(
        deployment.CommandResult(0, json.dumps({"changes": changes}), "")
    )
    result = deployment.deploy_web_app_infrastructure(
        replace(deployment_request, mode="what-if"), runner=runner
    )

    assert result.exact_topology_match is False
    assert not all(change.approved_boundary for change in result.change_evidence)
    assert safe_guided_plan(
        _plan_from_object(result),
        expected_boundary="web_app",
        require_create=True,
    ) is False
    serialized = json.dumps(result.to_json_dict()["change_evidence"])
    for forbidden in (
        "private-sub",
        deployment_request.resource_group,
        "hosted-foundry-verifier-validation",
        "unrelated-deployment",
        "wrong-resource-group",
    ):
        assert forbidden not in serialized


def test_ignore_evidence_serializes_only_safe_shape_diagnostics(
    deployment_request: deployment.WebAppInfrastructureDeploymentRequest,
) -> None:
    changes = [
        *_web_app_topology_changes(deployment_request),
        {"changeType": "Ignore"},
        {
            "changeType": "Ignore",
            "resourceId": None,
            "after": {"id": "private-after-resource-name"},
            "secretOperatorField": "private-tenant-value",
        },
    ]
    runner = FakeRunner(
        deployment.CommandResult(0, json.dumps({"changes": changes}), "")
    )

    result = deployment.deploy_web_app_infrastructure(
        replace(deployment_request, mode="what-if"), runner=runner
    )
    rendered = result.to_json_dict()["change_evidence"]
    first = rendered[8]["diagnostic"]
    second = rendered[9]["diagnostic"]

    assert result.exact_topology_match is False
    assert first == {
        "diagnostic_kind": "unidentified_ignore_shape",
        "top_level_fields_present": ["changeType"],
        "unknown_top_level_field_count": 0,
        "resource_id_present": False,
        "resource_type_present": False,
        "before_present": False,
        "after_present": False,
        "delta_present": False,
        "children_present": False,
        "nested_resource_change_count": 0,
        "nested_resource_change_count_truncated": False,
        "parser_shape": "resource_change",
        "bounded_ignore_candidate": False,
        "bounded_ignore_rejection_reason": "malformed_resource_id",
        "arm_path": {
            "arm_id_parse_status": "malformed",
            "scope_kind": "unknown",
            "path_segment_count": 0,
            "path_segment_count_truncated": False,
            "provider_marker_count": 0,
            "provider_marker_count_truncated": False,
            "selected_provider_marker": "none",
            "nested_provider_chain_present": False,
            "provider_chain_depth": 0,
            "provider_chain_depth_truncated": False,
            "selected_provider_namespace_class": "missing",
            "selected_resource_type_class": "missing",
            "segments_after_selected_provider_count": 0,
            "segments_after_selected_provider_count_truncated": False,
            "resource_type_segment_count": 0,
            "resource_type_segment_count_truncated": False,
            "resource_name_segment_count": 0,
            "resource_name_segment_count_truncated": False,
            "type_name_pairing_valid": False,
            "multiple_provider_namespaces_present": False,
            "extension_resource_shape": False,
            "trailing_unmatched_segment_present": False,
        },
    }
    assert second["top_level_fields_present"] == [
        "changeType",
        "resourceId",
        "after",
    ]
    assert second["unknown_top_level_field_count"] == 1
    assert second["resource_id_present"] is True
    assert second["after_present"] is True
    serialized = json.dumps(rendered)
    for forbidden in (
        "secretOperatorField",
        "private-after-resource-name",
        "private-tenant-value",
    ):
        assert forbidden not in serialized


def test_nested_and_identified_ignores_have_closed_rejection_diagnostics(
    deployment_request: deployment.WebAppInfrastructureDeploymentRequest,
) -> None:
    root = (
        "/subscriptions/private-subscription/resourceGroups/private-group/providers/"
    )
    changes = [
        *_web_app_topology_changes(deployment_request),
        {
            "changeType": "Ignore",
            "children": [
                {
                    "resourceId": (
                        f"{root}Microsoft.Web/sites/private-child-{index}"
                    )
                }
                for index in range(25)
            ],
        },
        {
            "changeType": "Ignore",
            "resourceId": f"{root}Microsoft.KeyVault/vaults/private-vault",
            "before": {"id": "private-parent"},
        },
    ]
    runner = FakeRunner(
        deployment.CommandResult(0, json.dumps({"changes": changes}), "")
    )

    result = deployment.deploy_web_app_infrastructure(
        replace(deployment_request, mode="what-if"), runner=runner
    )
    rendered = result.to_json_dict()["change_evidence"]
    nested = rendered[8]["diagnostic"]
    identified = rendered[9]["diagnostic"]

    assert result.exact_topology_match is False
    assert nested["parser_shape"] == "resource_change_with_children"
    assert nested["nested_resource_change_count"] == 20
    assert nested["nested_resource_change_count_truncated"] is True
    assert nested["bounded_ignore_rejection_reason"] == "malformed_resource_id"
    assert identified["bounded_ignore_candidate"] is False
    assert identified["bounded_ignore_rejection_reason"] == (
        "unexpected_resource_provider"
    )
    assert {
        item["diagnostic"]["bounded_ignore_rejection_reason"]
        for item in rendered[8:]
    } <= {
        "none",
        "unidentified_ignore_count_not_allowed",
        "resource_identity_present",
        "malformed_resource_id",
        "unexpected_resource_provider",
        "unexpected_resource_type",
        "unexpected_deployment_identity",
        "unexpected_deployment_scope",
        "unexpected_deployment_multiplicity",
    }
    serialized = json.dumps(rendered)
    for forbidden in (
        "private-subscription",
        "private-group",
        "private-child",
        "private-vault",
        "private-parent",
    ):
        assert forbidden not in serialized
    assert safe_guided_plan(
        _plan_from_object(result),
        expected_boundary="web_app",
        require_create=True,
    ) is False


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        (
            "resource-group-deployment",
            {
                "arm_id_parse_status": "parsed",
                "scope_kind": "resource_group",
                "provider_marker_count": 1,
                "selected_provider_marker": "only",
                "selected_provider_namespace_class": "microsoft_resources",
                "selected_resource_type_class": "deployments",
                "resource_type_segment_count": 1,
                "resource_name_segment_count": 1,
                "type_name_pairing_valid": True,
                "extension_resource_shape": False,
            },
        ),
        (
            "multiple-providers",
            {
                "arm_id_parse_status": "parsed",
                "scope_kind": "resource_group",
                "provider_marker_count": 2,
                "selected_provider_marker": "last",
                "nested_provider_chain_present": True,
                "provider_chain_depth": 2,
                "selected_provider_namespace_class": "microsoft_resources",
                "selected_resource_type_class": "deployments",
                "extension_resource_shape": True,
            },
        ),
        (
            "extension-provider",
            {
                "arm_id_parse_status": "parsed",
                "provider_marker_count": 2,
                "selected_provider_marker": "last",
                "selected_provider_namespace_class": "other",
                "selected_resource_type_class": "other",
                "extension_resource_shape": True,
            },
        ),
        (
            "nested-type-name",
            {
                "arm_id_parse_status": "parsed",
                "selected_provider_namespace_class": (
                    "approved_application_provider"
                ),
                "selected_resource_type_class": "approved_application_resource",
                "segments_after_selected_provider_count": 5,
                "resource_type_segment_count": 2,
                "resource_name_segment_count": 2,
                "type_name_pairing_valid": True,
            },
        ),
        (
            "incomplete-provider-chain",
            {
                "arm_id_parse_status": "incomplete_provider_chain",
                "selected_provider_namespace_class": "microsoft_resources",
                "selected_resource_type_class": "missing",
                "resource_type_segment_count": 1,
                "resource_name_segment_count": 0,
                "type_name_pairing_valid": False,
                "trailing_unmatched_segment_present": True,
            },
        ),
        (
            "malformed",
            {
                "arm_id_parse_status": "malformed",
                "scope_kind": "unknown",
                "provider_marker_count": 0,
                "selected_provider_marker": "none",
                "selected_provider_namespace_class": "missing",
                "selected_resource_type_class": "missing",
            },
        ),
        (
            "other-provider",
            {
                "arm_id_parse_status": "parsed",
                "selected_provider_namespace_class": "other",
                "selected_resource_type_class": "other",
            },
        ),
    ],
)
def test_rejected_ignore_diagnostic_describes_arm_path_without_values(
    deployment_request: deployment.WebAppInfrastructureDeploymentRequest,
    case: str,
    expected: dict[str, object],
) -> None:
    root = (
        f"/subscriptions/private-sub/resourceGroups/{deployment_request.resource_group}"
    )
    resource_ids = {
        "resource-group-deployment": (
            f"{root}/providers/Microsoft.Resources/deployments/private-unexpected"
        ),
        "multiple-providers": (
            f"{root}/providers/Microsoft.Web/sites/private-site/providers/"
            "Microsoft.Resources/deployments/private-unexpected"
        ),
        "extension-provider": (
            f"{root}/providers/Microsoft.Resources/deployments/private-parent/"
            "providers/Microsoft.Authorization/roleAssignments/private-role"
        ),
        "nested-type-name": (
            f"{root}/providers/Microsoft.DocumentDB/databaseAccounts/private-account/"
            "sqlDatabases/private-database"
        ),
        "incomplete-provider-chain": (
            f"{root}/providers/Microsoft.Resources/deployments"
        ),
        "malformed": "private-malicious-id",
        "other-provider": (
            f"{root}/providers/Microsoft.KeyVault/vaults/private-vault"
        ),
    }
    changes = [
        *_web_app_topology_changes(deployment_request),
        {
            "changeType": "Ignore",
            "resourceId": resource_ids[case],
            "before": {"id": "private-before"},
            "after": {"id": "private-after"},
            "delta": {"changes": []},
        },
    ]
    result = deployment.deploy_web_app_infrastructure(
        replace(deployment_request, mode="what-if"),
        runner=FakeRunner(
            deployment.CommandResult(0, json.dumps({"changes": changes}), "")
        ),
    )

    rendered = result.to_json_dict()["change_evidence"]
    arm_path = rendered[8]["diagnostic"]["arm_path"]
    assert result.exact_topology_match is False
    assert not any(change.approved_boundary for change in result.change_evidence)
    assert expected.items() <= arm_path.items()
    assert arm_path["arm_id_parse_status"] in {
        "parsed",
        "malformed",
        "unsupported_scope",
        "incomplete_provider_chain",
    }
    assert arm_path["scope_kind"] in {
        "resource_group",
        "subscription",
        "tenant",
        "management_group",
        "resource",
        "unknown",
    }
    assert arm_path["selected_provider_marker"] in {
        "first",
        "last",
        "only",
        "none",
        "ambiguous",
    }
    assert arm_path["selected_provider_namespace_class"] in {
        "microsoft_resources",
        "approved_application_provider",
        "other",
        "missing",
        "malformed",
    }
    assert arm_path["selected_resource_type_class"] in {
        "deployments",
        "approved_application_resource",
        "other",
        "missing",
        "malformed",
    }
    serialized_arm_path = json.dumps(arm_path)
    for forbidden in (
        "private-sub",
        deployment_request.resource_group,
        "Microsoft.Resources",
        "Microsoft.Web",
        "Microsoft.Authorization",
        "Microsoft.DocumentDB",
        "Microsoft.KeyVault",
        "private-unexpected",
        "private-site",
        "private-role",
        "private-account",
        "private-database",
        "private-malicious-id",
        "private-before",
        "private-after",
    ):
        assert forbidden not in serialized_arm_path
    serialized_evidence = json.dumps(rendered)
    for forbidden in (
        "private-sub",
        deployment_request.resource_group,
        "private-unexpected",
        "private-site",
        "private-role",
        "private-account",
        "private-database",
        "private-malicious-id",
        "private-before",
        "private-after",
    ):
        assert forbidden not in serialized_evidence
    assert safe_guided_plan(
        _plan_from_object(result),
        expected_boundary="web_app",
        require_create=True,
    ) is False


def test_rejected_ignore_arm_path_counts_are_bounded_and_report_truncation(
    deployment_request: deployment.WebAppInfrastructureDeploymentRequest,
) -> None:
    tail = "/".join(
        item
        for index in range(30)
        for item in (f"private-type-{index}", f"private-name-{index}")
    )
    resource_id = (
        f"/subscriptions/private-sub/resourceGroups/{deployment_request.resource_group}/"
        f"providers/Microsoft.Private/private-root/{tail}"
    )
    changes = [
        *_web_app_topology_changes(deployment_request),
        {"changeType": "Ignore", "resourceId": resource_id},
    ]
    result = deployment.deploy_web_app_infrastructure(
        replace(deployment_request, mode="what-if"),
        runner=FakeRunner(
            deployment.CommandResult(0, json.dumps({"changes": changes}), "")
        ),
    )

    arm_path = result.to_json_dict()["change_evidence"][8]["diagnostic"][
        "arm_path"
    ]
    for field in (
        "path_segment_count",
        "provider_marker_count",
        "provider_chain_depth",
        "segments_after_selected_provider_count",
        "resource_type_segment_count",
        "resource_name_segment_count",
    ):
        assert 0 <= arm_path[field] <= 20
    assert arm_path["path_segment_count_truncated"] is True
    assert arm_path["segments_after_selected_provider_count_truncated"] is True
    assert arm_path["resource_type_segment_count_truncated"] is True
    assert arm_path["resource_name_segment_count_truncated"] is True
    serialized = json.dumps(result.to_json_dict()["change_evidence"])
    assert "private-type" not in serialized
    assert "private-name" not in serialized


@pytest.mark.parametrize(
    "extra_evidence",
    [
        [{"changeType": "Ignore"}],
        [
            {"changeType": "Ignore"},
            {"changeType": "Ignore"},
            {"changeType": "Ignore"},
        ],
        [
            {"changeType": "Ignore"},
            {"changeType": "Ignore"},
            {"changeType": "NoChange"},
        ],
        [
            {"changeType": "Ignore"},
            {"changeType": "Ignore"},
            {
                "changeType": "Ignore",
                "resourceId": (
                    "/subscriptions/private-sub/resourceGroups/fictional-webapp-rg/"
                    "providers/Microsoft.KeyVault/vaults/unexpected"
                ),
            },
        ],
    ],
    ids=("one", "three", "unknown-action", "identified-unexpected"),
)
def test_web_app_adapter_rejects_ignore_evidence_outside_bounded_policy(
    deployment_request: deployment.WebAppInfrastructureDeploymentRequest,
    extra_evidence: list[dict[str, str]],
) -> None:
    changes = [*_web_app_topology_changes(deployment_request), *extra_evidence]
    runner = FakeRunner(
        deployment.CommandResult(0, json.dumps({"changes": changes}), "")
    )

    result = deployment.deploy_web_app_infrastructure(
        replace(deployment_request, mode="what-if"), runner=runner
    )

    assert result.exact_topology_match is False
    assert not any(
        change.expected_multiplicity_match
        for change in result.change_evidence[:8]
    )
    assert safe_guided_plan(
        _plan_from_object(result),
        expected_boundary="web_app",
        require_create=True,
    ) is False


@pytest.mark.parametrize(
    "mutate",
    [
        lambda changes: changes.__setitem__(
            7,
            {
                **changes[7],
                "resourceId": changes[7]["resourceId"].replace(
                    "fictional-nurse-intake-web-app", "wrong-web-app"
                ),
            },
        ),
        lambda changes: changes.__setitem__(
            7,
            {
                **changes[7],
                "resourceId": changes[7]["resourceId"].replace(
                    "fictional-webapp-rg", "wrong-rg"
                ),
            },
        ),
        lambda changes: changes.__setitem__(
            2,
            {
                **changes[2],
                "resourceId": changes[2]["resourceId"].replace(
                    "/sqlDatabases/nurse-intake/", "/sqlDatabases/wrong-parent/"
                ),
            },
        ),
        lambda changes: changes.append(dict(changes[7])),
        lambda changes: changes.append(
            {
                "changeType": "Create",
                "resourceId": changes[7]["resourceId"].replace(
                    "fictional-nurse-intake-web-app", "extra-web-app"
                ),
            }
        ),
        lambda changes: changes.append(
            {
                "changeType": "Modify",
                "resourceId": (
                    "/subscriptions/private-sub/resourceGroups/fictional-webapp-rg/"
                    "providers/Microsoft.KeyVault/vaults/unexpected"
                ),
            }
        ),
        lambda changes: changes.pop(),
    ],
    ids=(
        "wrong-name",
        "wrong-group",
        "wrong-parent",
        "duplicate",
        "extra",
        "unexpected-modify",
        "missing",
    ),
)
def test_web_app_adapter_rejects_inexact_topologies(
    deployment_request: deployment.WebAppInfrastructureDeploymentRequest,
    mutate,
) -> None:
    changes = _web_app_topology_changes(deployment_request)
    mutate(changes)
    runner = FakeRunner(
        deployment.CommandResult(0, json.dumps({"changes": changes}), "")
    )

    result = deployment.deploy_web_app_infrastructure(
        replace(deployment_request, mode="what-if"), runner=runner
    )

    assert result.exact_topology_match is False
    assert not all(change.approved_boundary for change in result.change_evidence)


@pytest.mark.parametrize("action", ["Modify", "Delete", "Deploy", "Unsupported"])
def test_web_app_adapter_rejects_unapproved_actions_for_expected_resources(
    deployment_request: deployment.WebAppInfrastructureDeploymentRequest,
    action: str,
) -> None:
    changes = _web_app_topology_changes(deployment_request)
    changes[7]["changeType"] = action
    runner = FakeRunner(
        deployment.CommandResult(0, json.dumps({"changes": changes}), "")
    )

    result = deployment.deploy_web_app_infrastructure(
        replace(deployment_request, mode="what-if"), runner=runner
    )

    assert not all(change.approved_boundary for change in result.change_evidence)
    assert safe_guided_plan(
        _plan_from_object(result),
        expected_boundary="web_app",
        require_create=True,
    ) is False


@pytest.mark.parametrize(
    "stdout",
    [
        "not-json",
        '{}',
        '{"changes":{}}',
        '{"changes":[{"changeType":"Unknown"}]}',
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
        "hosted_verifier_configuration_supplied",
        "create_count",
        "modify_count",
        "delete_count",
        "no_change_count",
        "ignore_count",
        "deploy_count",
        "unsupported_count",
        "delete_detected",
            "what_if_summary_available",
            "exact_topology_match",
            "recommended_next_step",
            "change_evidence",
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
