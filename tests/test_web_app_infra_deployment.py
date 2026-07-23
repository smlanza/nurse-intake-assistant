import json
from dataclasses import replace
from pathlib import Path

import pytest

from src.app.services import web_app_infra_deployment as deployment
from src.app.services.daily_azure_environment_rebuild import (
    _plan_from_object,
    safe_guided_plan,
    safe_web_app_plan,
    safe_web_app_reconciliation_plan,
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


@pytest.fixture
def reconciliation_request(
    deployment_request: deployment.WebAppInfrastructureDeploymentRequest,
) -> deployment.WebAppInfrastructureDeploymentRequest:
    return replace(
        deployment_request,
        purpose="existing_web_app_reconciliation",
        template_file=ROOT / "infra/modules/web-app.bicep",
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


def _reconciliation_web_app_change(
    request: deployment.WebAppInfrastructureDeploymentRequest,
    action: str = "Modify",
) -> dict[str, str]:
    root = (
        f"/subscriptions/private-sub/resourceGroups/{request.resource_group}/providers"
    )
    return {
        "changeType": action,
        "resourceId": f"{root}/Microsoft.Web/sites/{request.web_app_name}",
    }


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


def test_reconciliation_check_validates_dedicated_contract_offline(
    reconciliation_request: deployment.WebAppInfrastructureDeploymentRequest,
) -> None:
    runner = FakeRunner()

    result = deployment.deploy_web_app_infrastructure(
        reconciliation_request,
        runner=runner,
    )

    assert result.ok is True
    assert result.purpose == "existing_web_app_reconciliation"
    assert result.local_validation_passed is True
    assert result.azure_operation_attempted is False
    assert runner.calls == []


def test_reconciliation_wrapper_is_removed() -> None:
    assert not (ROOT / "infra/web-app-reconciliation.bicep").exists()


@pytest.mark.parametrize(
    ("purpose", "template_name"),
    (
        ("initial_create", "web-app.bicep"),
        ("existing_web_app_reconciliation", "main.bicep"),
        ("unbounded-purpose", "main.bicep"),
    ),
)
def test_purpose_template_mismatch_fails_before_runner(
    deployment_request: deployment.WebAppInfrastructureDeploymentRequest,
    purpose: str,
    template_name: str,
) -> None:
    runner = FakeRunner()
    request = replace(
        deployment_request,
        mode="what-if",
        purpose=purpose,
        template_file=ROOT / "infra" / template_name,
    )

    result = deployment.deploy_web_app_infrastructure(request, runner=runner)

    assert result.category == "invalid_arguments"
    assert result.azure_operation_attempted is False
    assert runner.calls == []


@pytest.mark.parametrize(
    "addition",
    (
        "module extra 'modules/web-app.bicep' = { params: { location: location appServicePlanName: appServicePlanName webAppName: webAppName appServicePlanResourceId: existingAppServicePlan.id } }",
        "resource extraPlan 'Microsoft.Web/serverfarms@2024-04-01' = { name: 'extra' location: location sku: { name: 'B1' } properties: { reserved: true } }",
        "resource cosmos 'Microsoft.DocumentDB/databaseAccounts@2024-05-15' = { name: 'extra' location: location kind: 'GlobalDocumentDB' properties: { databaseAccountOfferType: 'Standard' locations: [] } }",
        "resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = { name: 'stextra' location: location sku: { name: 'Standard_LRS' } kind: 'StorageV2' }",
        "resource monitoring 'Microsoft.Insights/components@2020-02-02' = { name: 'extra' location: location kind: 'web' properties: { Application_Type: 'web' } }",
        "resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = { name: 'extra' location: location properties: {} }",
        "resource foundry 'Microsoft.CognitiveServices/accounts@2025-06-01' = { name: 'extra' location: location kind: 'AIServices' sku: { name: 'S0' } properties: {} }",
        "resource rbac 'Microsoft.Authorization/roleAssignments@2022-04-01' = { name: guid(resourceGroup().id) properties: { principalId: '00000000-0000-0000-0000-000000000001' roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '00000000-0000-0000-0000-000000000002') } }",
        "resource secondWebApp 'Microsoft.Web/sites@2024-04-01' = { name: 'extra' location: location properties: { serverFarmId: existingAppServicePlan.id } }",
        "resource slot 'Microsoft.Web/sites/slots@2024-04-01' = { parent: existingWebApp name: 'extra' location: location }",
        "resource config 'Microsoft.Web/sites/config@2024-04-01' = { name: '${webAppName}/web' properties: {} }",
    ),
)
def test_direct_module_contract_rejects_every_extra_deployment_boundary(
    reconciliation_request: deployment.WebAppInfrastructureDeploymentRequest,
    tmp_path: Path,
    addition: str,
) -> None:
    modules = tmp_path / "infra/modules"
    modules.mkdir(parents=True)
    source = reconciliation_request.template_file
    template = modules / source.name
    template.write_text(f"{source.read_text()}\n{addition}\n")
    validation_name = "hosted-foundry-verifier-config-validation.bicep"
    (modules / validation_name).write_text(
        (ROOT / "infra/modules" / validation_name).read_text()
    )
    request = replace(reconciliation_request, template_file=template)

    result = deployment.deploy_web_app_infrastructure(request)

    assert result.category == "local_contract_invalid"


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


@pytest.mark.parametrize(
    "case",
    (
        "different-account",
        "different-project",
        "malformed-project-endpoint",
        "malformed-stable-endpoint",
    ),
)
def test_inconsistent_hosted_verifier_endpoint_identity_fails_before_runner(
    deployment_request: deployment.WebAppInfrastructureDeploymentRequest,
    case: str,
) -> None:
    project_endpoint = deployment_request.hosted_verifier_project_endpoint
    stable_endpoint = deployment_request.hosted_verifier_stable_agent_endpoint
    assert isinstance(project_endpoint, str)
    assert isinstance(stable_endpoint, str)
    if case == "different-account":
        stable_endpoint = stable_endpoint.replace(
            "fictional.services.ai.azure.com",
            "other.services.ai.azure.com",
        )
    elif case == "different-project":
        stable_endpoint = stable_endpoint.replace(
            "/api/projects/demo/",
            "/api/projects/other/",
        )
    elif case == "malformed-project-endpoint":
        project_endpoint = "not-a-project-endpoint"
    else:
        stable_endpoint = "not-a-stable-endpoint"
    runner = FakeRunner()

    result = deployment.deploy_web_app_infrastructure(
        replace(
            deployment_request,
            mode="what-if",
            hosted_verifier_project_endpoint=project_endpoint,
            hosted_verifier_stable_agent_endpoint=stable_endpoint,
        ),
        runner=runner,
    )

    assert result.category == "invalid_arguments"
    assert result.azure_operation_attempted is False
    assert runner.calls == []


def test_valid_custom_endpoint_contract_fails_closed_when_arm_identity_is_unprovable(
    deployment_request: deployment.WebAppInfrastructureDeploymentRequest,
) -> None:
    project_endpoint = "https://private.example/api/projects/demo"
    stable_endpoint = (
        f"{project_endpoint}/agents/fictional-agent/endpoint/protocols/openai"
    )
    request = replace(
        deployment_request,
        mode="what-if",
        hosted_verifier_project_endpoint=project_endpoint,
        hosted_verifier_stable_agent_endpoint=stable_endpoint,
    )
    changes = [
        *_web_app_topology_changes(request),
        *_web_app_foundry_reference_ignores(request),
    ]

    result = deployment.deploy_web_app_infrastructure(
        request,
        runner=FakeRunner(
            deployment.CommandResult(0, json.dumps({"changes": changes}), "")
        ),
    )

    assert result.category == "success"
    assert result.local_validation_passed is True
    assert result.exact_topology_match is False
    assert not any(change.approved_boundary for change in result.change_evidence)


def test_missing_template_and_invalid_local_contract_fail_offline(
    deployment_request: deployment.WebAppInfrastructureDeploymentRequest,
    tmp_path: Path,
) -> None:
    missing = replace(
        deployment_request,
        template_file=tmp_path / "missing" / "main.bicep",
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


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "false",
        "quoted",
        "numeric",
        "other-resource",
        "inactive-resource",
    ],
)
def test_local_contract_requires_direct_true_always_on(
    deployment_request: deployment.WebAppInfrastructureDeploymentRequest,
    tmp_path: Path,
    mutation: str,
) -> None:
    module = _current_module(deployment_request)
    replacement = {
        "missing": "",
        "false": "      alwaysOn: false\n",
        "quoted": "      alwaysOn: 'true'\n",
        "numeric": "      alwaysOn: 1\n",
        "other-resource": "",
        "inactive-resource": "",
    }[mutation]
    module = module.replace("      alwaysOn: true\n", replacement, 1)
    if mutation in {"other-resource", "inactive-resource"}:
        condition = " = if (false)" if mutation == "inactive-resource" else " ="
        module += (
            "\nresource decoyWebApp 'Microsoft.Web/sites@2024-04-01'"
            f"{condition} {{\n"
            "  name: 'decoy-web-app'\n"
            "  location: location\n"
            "  properties: {\n"
            "    siteConfig: {\n"
            "      alwaysOn: true\n"
            "    }\n"
            "  }\n"
            "}\n"
        )

    result = deployment.deploy_web_app_infrastructure(
        _request_with_module(deployment_request, tmp_path, module)
    )

    assert result.category == "local_contract_invalid"


@pytest.mark.parametrize(
    ("level", "target", "addition"),
    (
        (
            "resource",
            "  kind: 'app,linux'\n",
            "  clientAffinityEnabled: true\n",
        ),
        (
            "properties",
            "    httpsOnly: true\n",
            "    publicNetworkAccess: 'Enabled'\n",
        ),
        (
            "site-config",
            "      alwaysOn: true\n",
            "      http20Enabled: true\n",
        ),
        (
            "identity",
            "    type: 'SystemAssigned'\n",
            "    userAssignedIdentities: {}\n",
        ),
        (
            "depends-on",
            "    hostedFoundryVerifierConfigValidation\n",
            "    appServicePlan\n",
        ),
        (
            "duplicate-properties-key",
            "    httpsOnly: true\n",
            "    httpsOnly: true\n",
        ),
        (
            "duplicate-site-config-key",
            "      healthCheckPath: '/health'\n",
            "      healthCheckPath: '/health'\n",
        ),
        (
            "properties-spread",
            "    httpsOnly: true\n",
            "    ...unrecognizedProperties\n",
        ),
    ),
)
def test_local_contract_rejects_unrecognized_active_web_app_properties(
    deployment_request: deployment.WebAppInfrastructureDeploymentRequest,
    tmp_path: Path,
    level: str,
    target: str,
    addition: str,
) -> None:
    module = _current_module(deployment_request)
    assert module.count(target) == 1
    module = module.replace(target, target + addition, 1)

    result = deployment.deploy_web_app_infrastructure(
        _request_with_module(deployment_request, tmp_path, module)
    )

    assert result.category == "local_contract_invalid", level


def test_local_contract_ignores_properties_on_another_resource(
    deployment_request: deployment.WebAppInfrastructureDeploymentRequest,
    tmp_path: Path,
) -> None:
    module = _current_module(deployment_request) + (
        "\nresource unrelated 'Microsoft.Storage/storageAccounts@2023-05-01' = {\n"
        "  name: 'fictionalunrelatedstorage'\n"
        "  location: location\n"
        "  properties: {\n"
        "    publicNetworkAccess: 'Enabled'\n"
        "  }\n"
        "}\n"
    )

    result = deployment.deploy_web_app_infrastructure(
        _request_with_module(deployment_request, tmp_path, module)
    )

    assert result.ok is True


def test_local_contract_rejects_inactive_alternate_web_app_resource(
    deployment_request: deployment.WebAppInfrastructureDeploymentRequest,
    tmp_path: Path,
) -> None:
    module = _current_module(deployment_request) + (
        "\nresource decoyWebApp 'Microsoft.Web/sites@2024-04-01' = if (false) {\n"
        "  name: 'fictional-decoy-web-app'\n"
        "  location: location\n"
        "  properties: {\n"
        "    clientAffinityEnabled: true\n"
        "  }\n"
        "}\n"
    )

    result = deployment.deploy_web_app_infrastructure(
        _request_with_module(deployment_request, tmp_path, module)
    )

    assert result.category == "local_contract_invalid"


def _detach_authoritative_optional_settings(module: str) -> str:
    return module.replace(
        "      appSettings: concat([\n",
        "      appSettings: [\n",
        1,
    ).replace(
        "      ], hostedFoundryVerifierAppSettings)\n",
        "      ]\n",
        1,
    )


def _optional_settings_declaration(module: str) -> str:
    marker = (
        "var hostedFoundryVerifierAppSettings = "
        "validatedHostedFoundryVerifierConfiguration.mode == 'enabled' ? [\n"
    )
    start = module.index(marker)
    end = module.index("] : []\n", start) + len("] : []\n")
    return module[start:end]


def _empty_optional_settings_declaration(module: str) -> str:
    declaration = _optional_settings_declaration(module)
    return module.replace(
        declaration,
        _empty_optional_settings_declaration_text(module),
        1,
    )


def _empty_optional_settings_declaration_text(module: str) -> str:
    declaration = _optional_settings_declaration(module)
    marker = declaration[: declaration.index("[\n") + len("[\n")]
    return marker + "] : []\n"


@pytest.mark.parametrize(
    ("case", "mutate"),
    (
        (
            "baseline-only",
            _detach_authoritative_optional_settings,
        ),
        (
            "wrong-optional-variable",
            lambda module: module.replace(
                "      ], hostedFoundryVerifierAppSettings)\n",
                "      ], anotherOptionalSettings)\n",
                1,
            ),
        ),
        (
            "three-argument-concat",
            lambda module: module.replace(
                "      ], hostedFoundryVerifierAppSettings)\n",
                "      ], hostedFoundryVerifierAppSettings, extraSettings)\n",
                1,
            ),
        ),
        (
            "reversed-concat-arguments",
            lambda module: module.replace(
                "      appSettings: concat([\n",
                "      appSettings: concat(hostedFoundryVerifierAppSettings, [\n",
                1,
            ).replace(
                "      ], hostedFoundryVerifierAppSettings)\n",
                "      ])\n",
                1,
            ),
        ),
        (
            "wrapped-optional-settings",
            lambda module: module.replace(
                "      ], hostedFoundryVerifierAppSettings)\n",
                "      ], concat(hostedFoundryVerifierAppSettings))\n",
                1,
            ),
        ),
        (
            "trailing-expression",
            lambda module: module.replace(
                "      ], hostedFoundryVerifierAppSettings)\n",
                "      ], hostedFoundryVerifierAppSettings) + extraSettings\n",
                1,
            ),
        ),
        (
            "correct-expression-only-in-decoy-variable",
            lambda module: _detach_authoritative_optional_settings(module)
            + (
                "\nvar decoy = {\n"
                "  appSettings: concat([], hostedFoundryVerifierAppSettings)\n"
                "}\n"
            ),
        ),
        (
            "correct-expression-only-in-comment",
            lambda module: _detach_authoritative_optional_settings(module)
            + (
                "\n// appSettings: concat([], "
                "hostedFoundryVerifierAppSettings)\n"
            ),
        ),
        (
            "correct-expression-only-in-string",
            lambda module: _detach_authoritative_optional_settings(module)
            + (
                "\nvar decoyExpression = "
                "'appSettings: concat([], hostedFoundryVerifierAppSettings)'\n"
            ),
        ),
        (
            "correct-expression-only-in-unrelated-resource",
            lambda module: _detach_authoritative_optional_settings(module)
            + (
                "\nresource unrelated 'Microsoft.Storage/storageAccounts@2023-05-01' = {\n"
                "  name: 'fictionalunrelatedstorage'\n"
                "  location: location\n"
                "  properties: {\n"
                "    appSettings: concat([], hostedFoundryVerifierAppSettings)\n"
                "  }\n"
                "}\n"
            ),
        ),
    ),
)
def test_local_contract_binds_optional_settings_to_authoritative_web_app(
    deployment_request: deployment.WebAppInfrastructureDeploymentRequest,
    tmp_path: Path,
    case: str,
    mutate,
) -> None:
    module = mutate(_current_module(deployment_request))

    result = deployment.deploy_web_app_infrastructure(
        _request_with_module(deployment_request, tmp_path, module)
    )

    assert result.category == "local_contract_invalid", case


def test_local_contract_accepts_exact_authoritative_app_settings_expression(
    deployment_request: deployment.WebAppInfrastructureDeploymentRequest,
) -> None:
    result = deployment.deploy_web_app_infrastructure(deployment_request)

    assert result.ok is True


@pytest.mark.parametrize(
    ("case", "mutate"),
    (
        (
            "multiline-string-declaration-decoy",
            lambda module: (
                "var decoyOptionalText = '''\n"
                + _optional_settings_declaration(module)
                + "'''\n"
                + _empty_optional_settings_declaration(module)
            ),
        ),
        (
            "ordinary-string-declaration-decoy",
            lambda module: _empty_optional_settings_declaration(module)
            + (
                "\nvar decoyOptionalText = "
                "'var hostedFoundryVerifierAppSettings = ignored'\n"
            ),
        ),
        (
            "commented-declaration-decoy",
            lambda module: "".join(
                f"// {line}"
                for line in _optional_settings_declaration(module).splitlines(
                    keepends=True
                )
            )
            + _empty_optional_settings_declaration(module),
        ),
        (
            "duplicate-active-declaration",
            lambda module: module
            + "\n"
            + _empty_optional_settings_declaration_text(module),
        ),
    ),
)
def test_local_contract_uses_one_active_optional_settings_declaration(
    deployment_request: deployment.WebAppInfrastructureDeploymentRequest,
    tmp_path: Path,
    case: str,
    mutate,
) -> None:
    module = mutate(_current_module(deployment_request))

    result = deployment.deploy_web_app_infrastructure(
        _request_with_module(deployment_request, tmp_path, module)
    )

    assert result.category == "local_contract_invalid", case


def test_local_contract_accepts_exact_active_optional_settings_declaration(
    deployment_request: deployment.WebAppInfrastructureDeploymentRequest,
) -> None:
    result = deployment.deploy_web_app_infrastructure(deployment_request)

    assert result.ok is True


@pytest.mark.parametrize(
    ("case", "addition", "accepted"),
    (
        (
            "relative-config-child",
            (
                "\nresource webAppConfig 'config@2024-04-01' = {\n"
                "  parent: webApp\n"
                "  name: 'web'\n"
                "  properties: {}\n"
                "}\n"
            ),
            False,
        ),
        (
            "relative-slot",
            (
                "\nresource webAppSlot 'slots@2024-04-01' = {\n"
                "  parent: webApp\n"
                "  name: 'staging'\n"
                "  properties: {}\n"
                "}\n"
            ),
            False,
        ),
        (
            "relative-extension-child",
            (
                "\nresource webAppExtension 'extensions@2024-04-01' = {\n"
                "  parent: webApp\n"
                "  name: 'fictional-extension'\n"
                "  properties: {}\n"
                "}\n"
            ),
            False,
        ),
        (
            "multiline-relative-parent",
            (
                "\nresource webAppConfig 'config@2024-04-01' = {\n"
                "  parent:\n"
                "    webApp\n"
                "  name: 'web'\n"
                "  properties: {}\n"
                "}\n"
            ),
            False,
        ),
        (
            "fully-qualified-slot",
            (
                "\nresource webAppSlot 'Microsoft.Web/sites/slots@2024-04-01' = {\n"
                "  name: 'fictional-web-app/staging'\n"
                "  properties: {}\n"
                "}\n"
            ),
            False,
        ),
        (
            "fully-qualified-child",
            (
                "\nresource webAppConfig 'Microsoft.Web/sites/config@2024-04-01' = {\n"
                "  name: 'fictional-web-app/web'\n"
                "  properties: {}\n"
                "}\n"
            ),
            False,
        ),
        (
            "commented-relative-child",
            (
                "\n// resource webAppConfig 'config@2024-04-01' = {\n"
                "//   parent: webApp\n"
                "//   name: 'web'\n"
                "//   properties: {}\n"
                "// }\n"
            ),
            True,
        ),
        (
            "string-containing-parent",
            (
                "\nvar decoyParentText = '''\n"
                "resource decoy 'config@2024-04-01' = {\n"
                "  parent: webApp\n"
                "}\n"
                "'''\n"
            ),
            True,
        ),
        (
            "other-resource-parent",
            (
                "\nresource planChild 'virtualNetworkConnections@2024-04-01' = {\n"
                "  parent: appServicePlan\n"
                "  name: 'fictional-connection'\n"
                "  properties: {}\n"
                "}\n"
            ),
            True,
        ),
    ),
)
def test_local_contract_rejects_only_active_direct_web_app_children(
    deployment_request: deployment.WebAppInfrastructureDeploymentRequest,
    tmp_path: Path,
    case: str,
    addition: str,
    accepted: bool,
) -> None:
    module = _current_module(deployment_request) + addition

    result = deployment.deploy_web_app_infrastructure(
        _request_with_module(deployment_request, tmp_path, module)
    )

    assert result.ok is accepted, case
    assert result.category == ("success" if accepted else "local_contract_invalid")


@pytest.mark.parametrize(
    ("case", "addition", "accepted"),
    (
        (
            "conditional-config-with-object-literal",
            (
                "\nresource webAppConfig 'config@2024-04-01' = "
                "if (contains({}, 'x')) {\n"
                "  parent: webApp\n"
                "  name: 'web'\n"
                "  properties: {}\n"
                "}\n"
            ),
            False,
        ),
        (
            "conditional-slot-with-object-literal",
            (
                "\nresource webAppSlot 'slots@2024-04-01' = "
                "if (contains({}, 'x')) {\n"
                "  parent: webApp\n"
                "  name: 'staging'\n"
                "  properties: {}\n"
                "}\n"
            ),
            False,
        ),
        (
            "multiline-nested-condition",
            (
                "\nresource webAppExtension 'extensions@2024-04-01' = if (\n"
                "  contains({\n"
                "    nested: [\n"
                "      format('{0}', 'x')\n"
                "    ]\n"
                "  }, 'nested')\n"
                ") {\n"
                "  parent: webApp\n"
                "  name: 'fictional-extension'\n"
                "  properties: {}\n"
                "}\n"
            ),
            False,
        ),
        (
            "brace-like-comment-and-string",
            (
                "\nresource webAppConfig 'config@2024-04-01' = if (\n"
                "  contains({}, '}]) {') /* { ignored } */\n"
                ") {\n"
                "  parent: webApp\n"
                "  name: 'web'\n"
                "  properties: {}\n"
                "}\n"
            ),
            False,
        ),
        (
            "unrelated-conditional-resource",
            (
                "\nresource planChild 'virtualNetworkConnections@2024-04-01' = "
                "if (contains({}, 'x')) {\n"
                "  parent: appServicePlan\n"
                "  name: 'fictional-connection'\n"
                "  properties: {}\n"
                "}\n"
            ),
            True,
        ),
    ),
)
def test_local_contract_finds_body_after_balanced_resource_condition(
    deployment_request: deployment.WebAppInfrastructureDeploymentRequest,
    tmp_path: Path,
    case: str,
    addition: str,
    accepted: bool,
) -> None:
    module = _current_module(deployment_request) + addition

    result = deployment.deploy_web_app_infrastructure(
        _request_with_module(deployment_request, tmp_path, module)
    )

    assert result.ok is accepted, case
    assert result.category == ("success" if accepted else "local_contract_invalid")


def test_local_contract_rejects_unrecognized_optional_app_setting(
    deployment_request: deployment.WebAppInfrastructureDeploymentRequest,
    tmp_path: Path,
) -> None:
    module = _current_module(deployment_request)
    marker = (
        "var hostedFoundryVerifierAppSettings = "
        "validatedHostedFoundryVerifierConfiguration.mode == 'enabled' ? [\n"
    )
    addition = (
        "  {\n"
        "    name: 'UNRECOGNIZED_OPTIONAL_SETTING'\n"
        "    value: validatedHostedFoundryVerifierConfiguration.agentName\n"
        "  }\n"
    )
    assert module.count(marker) == 1
    module = module.replace(marker, marker + addition, 1)

    result = deployment.deploy_web_app_infrastructure(
        _request_with_module(deployment_request, tmp_path, module)
    )

    assert result.category == "local_contract_invalid"


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "true",
        "wrong-name-case",
        "value-case",
        "value-whitespace",
        "duplicate",
        "conflicting",
        "commented-only",
        "optional-only",
    ],
)
def test_local_contract_requires_one_exact_baseline_kudu_agent_setting(
    deployment_request: deployment.WebAppInfrastructureDeploymentRequest,
    tmp_path: Path,
    mutation: str,
) -> None:
    name = "WEBSITE_SKIP_RUNNING_KUDUAGENT"
    block = _setting_block(name, "false")
    module = _current_module(deployment_request)
    if mutation == "missing":
        module = module.replace(block, "", 1)
    elif mutation == "true":
        module = module.replace(block, _setting_block(name, "true"), 1)
    elif mutation == "wrong-name-case":
        module = module.replace(
            block, _setting_block("Website_Skip_Running_Kuduagent", "false"), 1
        )
    elif mutation == "value-case":
        module = module.replace(block, _setting_block(name, "False"), 1)
    elif mutation == "value-whitespace":
        module = module.replace(block, _setting_block(name, " false "), 1)
    elif mutation == "duplicate":
        module = _append_app_setting(module, name, "false")
    elif mutation == "conflicting":
        module = _append_app_setting(module, name, "true")
    elif mutation == "commented-only":
        commented = "".join(
            f"// {line}" for line in block.splitlines(keepends=True)
        )
        module = module.replace(block, commented, 1)
    else:
        module = module.replace(block, "", 1)
        marker = (
            "var hostedFoundryVerifierAppSettings = "
            "validatedHostedFoundryVerifierConfiguration.mode == 'enabled' ? [\n"
        )
        module = module.replace(marker, marker + block, 1)

    result = deployment.deploy_web_app_infrastructure(
        _request_with_module(deployment_request, tmp_path, module)
    )

    assert result.category == "local_contract_invalid"


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


@pytest.mark.parametrize(
    ("mode", "operation"),
    (("what-if", "what-if"), ("live", "create")),
)
def test_reconciliation_command_uses_only_dedicated_web_app_parameters(
    reconciliation_request: deployment.WebAppInfrastructureDeploymentRequest,
    mode: str,
    operation: str,
) -> None:
    runner = FakeRunner()

    result = deployment.deploy_web_app_infrastructure(
        replace(reconciliation_request, mode=mode),
        runner=runner,
    )

    assert result.ok is True
    assert len(runner.calls) == 1
    command = runner.calls[0]
    assert command[:4] == ["az", "deployment", "group", operation]
    assert command[command.index("--template-file") + 1] == str(
        reconciliation_request.template_file
    )
    parameters = command[command.index("--parameters") + 1 :]
    assert parameters == [
        f"location={reconciliation_request.location}",
        (
            "appServicePlanName="
            f"{deployment._app_service_plan_name(reconciliation_request)}"
        ),
        f"webAppName={reconciliation_request.web_app_name}",
        "deployAppServicePlan=false",
        "pythonLinuxFxVersion=PYTHON|3.12",
        "hostedFoundryVerifierConfiguration="
        + json.dumps(
            {
                "mode": "enabled",
                "projectEndpoint": (
                    reconciliation_request.hosted_verifier_project_endpoint
                ),
                "agentEndpoint": (
                    reconciliation_request.hosted_verifier_stable_agent_endpoint
                ),
                "agentName": reconciliation_request.hosted_verifier_agent_name,
                "agentVersion": (
                    reconciliation_request.hosted_verifier_agent_version
                ),
                "modelDeploymentName": (
                    reconciliation_request.hosted_verifier_model_deployment_name
                ),
            },
            separators=(",", ":"),
            sort_keys=True,
        ),
    ]
    for forbidden in (
        "deployApp",
        "deployFoundry",
        "cosmosDatabaseName",
        "cosmosContainerName",
        "resourceNameSuffix",
        "appServicePlanResourceId",
    ):
        assert not any(
            parameter.startswith(f"{forbidden}=")
            for parameter in parameters
        )


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


def _web_app_foundry_reference_ignores(
    request: deployment.WebAppInfrastructureDeploymentRequest,
) -> list[dict[str, object]]:
    root = (
        f"/subscriptions/private-sub/resourceGroups/{request.resource_group}/providers/"
        "Microsoft.CognitiveServices/accounts/fictional"
    )
    return [
        {
            "changeType": "Ignore",
            "resourceId": root,
            "before": {"id": "private-before"},
            "after": {"id": "private-after"},
            "delta": {"changes": []},
        },
        {
            "changeType": "Ignore",
            "resourceId": f"{root}/projects/demo",
            "before": {"id": "private-before"},
            "after": {"id": "private-after"},
            "delta": {"changes": []},
        },
    ]


def _web_app_hosting_modify_changes(
    request: deployment.WebAppInfrastructureDeploymentRequest,
) -> list[dict[str, object]]:
    changes: list[dict[str, object]] = [
        *(_web_app_topology_changes(request)),
        *_web_app_foundry_reference_ignores(request),
    ]
    for change in changes[:7]:
        change["changeType"] = "NoChange"
    changes[7]["changeType"] = "Modify"
    return changes


def test_reconciliation_accepts_only_exact_direct_web_app_modify(
    reconciliation_request: deployment.WebAppInfrastructureDeploymentRequest,
) -> None:
    changes: list[dict[str, object]] = [
        _reconciliation_web_app_change(reconciliation_request)
    ]

    result = deployment.deploy_web_app_infrastructure(
        replace(reconciliation_request, mode="what-if"),
        runner=FakeRunner(
            deployment.CommandResult(0, json.dumps({"changes": changes}), "")
        ),
    )

    assert result.exact_topology_match is True
    assert result.modify_count == 1
    assert result.create_count == 0
    assert result.deploy_count == 0
    assert result.delete_count == 0
    assert result.unsupported_count == 0
    assert safe_web_app_reconciliation_plan(_plan_from_object(result)) is True
    assert safe_web_app_plan(_plan_from_object(result)) is False


def test_reconciliation_rejects_confirmed_nested_wrapper_preview(
    reconciliation_request: deployment.WebAppInfrastructureDeploymentRequest,
) -> None:
    web_app = _reconciliation_web_app_change(
        reconciliation_request,
        action="Deploy",
    )
    changes: list[dict[str, object]] = [
        web_app,
        *({"changeType": "Ignore"} for _index in range(9)),
    ]

    result = deployment.deploy_web_app_infrastructure(
        replace(reconciliation_request, mode="what-if"),
        runner=FakeRunner(
            deployment.CommandResult(0, json.dumps({"changes": changes}), "")
        ),
    )

    assert result.deploy_count == 1
    assert result.ignore_count == 9
    assert result.modify_count == 0
    assert result.exact_topology_match is False
    assert safe_web_app_reconciliation_plan(_plan_from_object(result)) is False


@pytest.mark.parametrize(
    "case",
    (
        "web-app-create",
        "plan-modify",
        "cosmos-modify",
        "storage-deploy",
        "monitoring-modify",
        "foundry-deploy",
        "rbac-change",
        "slot",
        "child",
        "second-web-app",
        "unidentified-ignore",
        "duplicate-reference",
        "delete",
        "deploy",
        "unsupported",
        "unknown",
        "missing-evidence",
    ),
)
def test_reconciliation_preview_policy_fails_closed(
    reconciliation_request: deployment.WebAppInfrastructureDeploymentRequest,
    case: str,
) -> None:
    web_app = _reconciliation_web_app_change(reconciliation_request)
    changes: list[dict[str, object]] = [web_app]
    root = (
        f"/subscriptions/private-sub/resourceGroups/"
        f"{reconciliation_request.resource_group}/providers"
    )
    if case == "web-app-create":
        web_app["changeType"] = "Create"
    elif case == "plan-modify":
        changes.append(
            {
                "changeType": "Modify",
                "resourceId": (
                    f"{root}/Microsoft.Web/serverfarms/"
                    f"{deployment._app_service_plan_name(reconciliation_request)}"
                ),
            }
        )
    elif case == "cosmos-modify":
        changes.append(
            {
                "changeType": "Modify",
                "resourceId": f"{root}/Microsoft.DocumentDB/databaseAccounts/extra",
            }
        )
    elif case == "storage-deploy":
        changes.append(
            {
                "changeType": "Deploy",
                "resourceId": f"{root}/Microsoft.Storage/storageAccounts/stextra",
            }
        )
    elif case == "monitoring-modify":
        changes.append(
            {
                "changeType": "Modify",
                "resourceId": f"{root}/Microsoft.Insights/components/extra",
            }
        )
    elif case == "foundry-deploy":
        changes.append(
            {
                "changeType": "Deploy",
                "resourceId": f"{root}/Microsoft.CognitiveServices/accounts/extra",
            }
        )
    elif case == "rbac-change":
        changes.append(
            {
                "changeType": "Create",
                "resourceId": (
                    f"{root}/Microsoft.Authorization/roleAssignments/"
                    "00000000-0000-0000-0000-000000000001"
                ),
            }
        )
    elif case == "slot":
        changes.append(
            {
                "changeType": "Modify",
                "resourceId": (
                    f"{root}/Microsoft.Web/sites/"
                    f"{reconciliation_request.web_app_name}/slots/extra"
                ),
            }
        )
    elif case == "child":
        changes.append(
            {
                "changeType": "Modify",
                "resourceId": (
                    f"{root}/Microsoft.Web/sites/"
                    f"{reconciliation_request.web_app_name}/config/web"
                ),
            }
        )
    elif case == "second-web-app":
        changes.append(
            {
                "changeType": "Modify",
                "resourceId": f"{root}/Microsoft.Web/sites/other-web-app",
            }
        )
    elif case == "unidentified-ignore":
        changes.append({"changeType": "Ignore"})
    elif case == "duplicate-reference":
        changes.append(dict(web_app))
    elif case == "delete":
        web_app["changeType"] = "Delete"
    elif case == "deploy":
        web_app["changeType"] = "Deploy"
    elif case == "unsupported":
        web_app["changeType"] = "Unsupported"
    elif case == "unknown":
        web_app["changeType"] = "Unknown"
    else:
        web_app.pop("resourceId")

    result = deployment.deploy_web_app_infrastructure(
        replace(reconciliation_request, mode="what-if"),
        runner=FakeRunner(
            deployment.CommandResult(0, json.dumps({"changes": changes}), "")
        ),
    )

    plan_result = _plan_from_object(result)
    assert result.category in {"success", "what_if_parse_failed"}
    assert (
        result.exact_topology_match is False
        if result.category == "success"
        else True
    )
    assert safe_web_app_reconciliation_plan(plan_result) is False


@pytest.mark.parametrize(
    "reference_indexes",
    ((), (0,), (1,), (0, 1)),
    ids=("no-references", "account-only", "project-only", "both-references"),
)
def test_web_app_adapter_accepts_exact_hosting_contract_modify_topology(
    deployment_request: deployment.WebAppInfrastructureDeploymentRequest,
    reference_indexes: tuple[int, ...],
) -> None:
    changes = _web_app_hosting_modify_changes(deployment_request)
    references = changes[8:]
    changes = [*changes[:8], *(references[index] for index in reference_indexes)]
    result = deployment.deploy_web_app_infrastructure(
        replace(deployment_request, mode="what-if"),
        runner=FakeRunner(
            deployment.CommandResult(
                0,
                json.dumps({"changes": changes}),
                "",
            )
        ),
    )

    assert result.exact_topology_match is True
    assert result.create_count == 0
    assert result.modify_count == 1
    assert result.no_change_count == 7
    assert result.ignore_count == len(reference_indexes)
    modifying = [
        change for change in result.change_evidence if change.action == "Modify"
    ]
    assert len(modifying) == 1
    assert modifying[0].resource_type == "Microsoft.Web/sites"
    assert modifying[0].logical_category == "web_app"
    assert modifying[0].approved_boundary is True


def test_web_app_adapter_accepts_exact_existing_foundry_reference_pair(
    deployment_request: deployment.WebAppInfrastructureDeploymentRequest,
) -> None:
    changes = [
        *_web_app_topology_changes(deployment_request),
        *_web_app_foundry_reference_ignores(deployment_request),
    ]
    result = deployment.deploy_web_app_infrastructure(
        replace(deployment_request, mode="what-if"),
        runner=FakeRunner(
            deployment.CommandResult(0, json.dumps({"changes": changes}), "")
        ),
    )

    application = result.change_evidence[:8]
    references = result.change_evidence[8:]
    assert [change.logical_category for change in references] == [
        "foundry_account_reference",
        "foundry_project_reference",
    ]
    assert [change.resource_type for change in references] == [
        "Microsoft.CognitiveServices/accounts",
        "Microsoft.CognitiveServices/accounts/projects",
    ]
    assert all(change.expected_identity_match for change in references)
    assert all(change.expected_parent_match for change in references)
    assert all(change.expected_scope_match for change in references)
    assert all(change.expected_multiplicity_match for change in references)
    assert all(change.approved_boundary for change in references)
    assert all(change.diagnostic is None for change in references)
    assert all(change.expected_identity_match for change in application)
    assert all(change.expected_parent_match for change in application)
    assert all(change.expected_scope_match for change in application)
    assert all(change.expected_multiplicity_match for change in application)
    assert all(change.approved_boundary for change in application)
    assert result.create_count == 8
    assert result.ignore_count == 2
    assert result.modify_count == 0
    assert result.delete_count == 0
    assert result.deploy_count == 0
    assert result.unsupported_count == 0
    assert result.exact_topology_match is True
    assert safe_guided_plan(
        _plan_from_object(result),
        expected_boundary="web_app",
        require_create=True,
    ) is True
    serialized = json.dumps(result.to_json_dict()["change_evidence"])
    for forbidden in (
        "private-sub",
        deployment_request.resource_group,
        "fictional.services.ai.azure.com",
        "/api/projects/demo",
        "private-before",
        "private-after",
    ):
        assert forbidden not in serialized


def test_foundry_reference_arm_identity_comparisons_are_case_insensitive(
    deployment_request: deployment.WebAppInfrastructureDeploymentRequest,
) -> None:
    references = _web_app_foundry_reference_ignores(deployment_request)
    for reference in references:
        reference["resourceId"] = (
            str(reference["resourceId"])
            .replace("subscriptions", "SUBSCRIPTIONS")
            .replace("private-sub", "PRIVATE-SUB")
            .replace("resourceGroups", "RESOURCEGROUPS")
            .replace(deployment_request.resource_group, deployment_request.resource_group.upper())
            .replace("providers", "PROVIDERS")
            .replace("Microsoft.CognitiveServices", "microsoft.cognitiveservices")
            .replace("accounts/fictional", "ACCOUNTS/FICTIONAL")
            .replace("projects/demo", "PROJECTS/DEMO")
        )
    changes = [*_web_app_topology_changes(deployment_request), *references]

    result = deployment.deploy_web_app_infrastructure(
        replace(deployment_request, mode="what-if"),
        runner=FakeRunner(
            deployment.CommandResult(0, json.dumps({"changes": changes}), "")
        ),
    )

    assert result.exact_topology_match is True
    assert [change.resource_type for change in result.change_evidence[8:]] == [
        "Microsoft.CognitiveServices/accounts",
        "Microsoft.CognitiveServices/accounts/projects",
    ]
    assert all(change.approved_boundary for change in result.change_evidence)


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


@pytest.mark.parametrize(
    "case",
    [
        "duplicate-account",
        "duplicate-project",
        "three",
        "unrelated-project",
        "different-parent-account",
        "different-account",
        "malformed-id",
        "missing-subscription",
        "missing-resource-group",
        "wrong-resource-group",
        "wrong-subscription",
        "wrong-provider",
        "multiple-provider-markers",
        "arbitrary-cognitive-resource",
        "other-account-child",
        "model-deployment-child",
        "extra-child-pair",
        "subscription-scope",
        "create-action",
        "modify-action",
        "delete-action",
        "nochange-action",
        "application-ignore",
    ],
)
def test_web_app_adapter_rejects_inexact_foundry_reference_ignores(
    deployment_request: deployment.WebAppInfrastructureDeploymentRequest,
    case: str,
) -> None:
    changes = _web_app_hosting_modify_changes(deployment_request)
    first = changes[8]
    second = changes[9]
    if case == "duplicate-account":
        changes[9] = dict(first)
    elif case == "duplicate-project":
        changes[8] = dict(second)
    elif case == "three":
        changes.append(dict(first))
    elif case == "unrelated-project":
        second["resourceId"] = str(second["resourceId"]).replace(
            "/projects/demo", "/projects/unrelated-project"
        )
    elif case == "different-parent-account":
        second["resourceId"] = str(second["resourceId"]).replace(
            "/accounts/fictional/", "/accounts/other-account/"
        )
    elif case == "different-account":
        first["resourceId"] = str(first["resourceId"]).replace(
            "/accounts/fictional", "/accounts/other-account"
        )
    elif case == "malformed-id":
        second["resourceId"] = "not-an-arm-resource-id"
    elif case == "missing-subscription":
        second["resourceId"] = (
            f"/resourceGroups/{deployment_request.resource_group}/providers/"
            "Microsoft.CognitiveServices/accounts/fictional/projects/demo"
        )
    elif case == "missing-resource-group":
        second["resourceId"] = (
            "/subscriptions/private-sub/providers/Microsoft.CognitiveServices/"
            "accounts/fictional/projects/demo"
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
            "Microsoft.CognitiveServices", "Microsoft.KeyVault"
        )
    elif case == "multiple-provider-markers":
        second["resourceId"] = (
            f"/subscriptions/private-sub/resourceGroups/"
            f"{deployment_request.resource_group}/providers/Microsoft.Web/sites/"
            "private-site/providers/Microsoft.CognitiveServices/accounts/"
            "fictional/projects/demo"
        )
    elif case == "arbitrary-cognitive-resource":
        second["resourceId"] = (
            f"/subscriptions/private-sub/resourceGroups/"
            f"{deployment_request.resource_group}/providers/"
            "Microsoft.CognitiveServices/locations/eastus2"
        )
    elif case == "other-account-child":
        second["resourceId"] = str(second["resourceId"]).replace(
            "/projects/", "/connections/"
        )
    elif case == "model-deployment-child":
        second["resourceId"] = str(second["resourceId"]).replace(
            "/projects/", "/deployments/"
        )
    elif case == "extra-child-pair":
        second["resourceId"] = (
            f"{second['resourceId']}/deployments/private-deployment"
        )
    elif case == "subscription-scope":
        second["resourceId"] = (
            "/subscriptions/private-sub/providers/Microsoft.CognitiveServices/"
            "accounts/fictional/projects/demo"
        )
    elif case == "create-action":
        second["changeType"] = "Create"
    elif case == "modify-action":
        second["changeType"] = "Modify"
    elif case == "delete-action":
        second["changeType"] = "Delete"
    elif case == "nochange-action":
        second["changeType"] = "NoChange"
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
    assert not any(
        change.expected_multiplicity_match
        for change in result.change_evidence[:8]
    )
    assert safe_guided_plan(
        _plan_from_object(result),
        expected_boundary="web_app",
        require_create=True,
    ) is False
    assert safe_web_app_plan(_plan_from_object(result)) is False
    serialized = json.dumps(result.to_json_dict()["change_evidence"])
    for forbidden in (
        "private-sub",
        deployment_request.resource_group,
        "unrelated-project",
        "other-account",
        "private-deployment",
        "private-site",
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
        "invalid_reference_path",
        "unexpected_reference_identity",
        "unexpected_reference_scope",
        "unexpected_reference_multiplicity",
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


@pytest.mark.parametrize("action", ["Delete", "Deploy", "Unsupported"])
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
    "modified_index",
    [0, 3, 4, 6],
    ids=("cosmos", "storage", "log-analytics", "app-service-plan"),
)
def test_web_app_adapter_rejects_modify_outside_exact_web_app_resource(
    deployment_request: deployment.WebAppInfrastructureDeploymentRequest,
    modified_index: int,
) -> None:
    changes = _web_app_hosting_modify_changes(deployment_request)
    changes[7]["changeType"] = "NoChange"
    changes[modified_index]["changeType"] = "Modify"

    result = deployment.deploy_web_app_infrastructure(
        replace(deployment_request, mode="what-if"),
        runner=FakeRunner(
            deployment.CommandResult(0, json.dumps({"changes": changes}), "")
        ),
    )

    assert result.modify_count == 1
    assert result.exact_topology_match is False
    modifying = [
        change for change in result.change_evidence if change.action == "Modify"
    ]
    assert len(modifying) == 1
    assert modifying[0].approved_boundary is False
    assert safe_web_app_plan(_plan_from_object(result)) is False


def test_web_app_adapter_represents_but_rejects_mixed_create_and_modify(
    deployment_request: deployment.WebAppInfrastructureDeploymentRequest,
) -> None:
    changes = _web_app_topology_changes(deployment_request)
    changes[7]["changeType"] = "Modify"

    result = deployment.deploy_web_app_infrastructure(
        replace(deployment_request, mode="what-if"),
        runner=FakeRunner(
            deployment.CommandResult(0, json.dumps({"changes": changes}), "")
        ),
    )

    assert result.exact_topology_match is False
    assert result.create_count == 7
    assert result.modify_count == 1
    assert next(
        change for change in result.change_evidence if change.action == "Modify"
    ).approved_boundary is False
    assert safe_web_app_plan(_plan_from_object(result)) is False


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
        "purpose",
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
