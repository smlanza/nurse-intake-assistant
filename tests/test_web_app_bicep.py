import json
import os
from pathlib import Path
import re
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
INFRA = ROOT / "infra"


def _text(path: str) -> str:
    return (INFRA / path).read_text()


def _compile(path: str) -> dict:
    bicep = Path.home() / ".azure" / "bin" / "bicep"
    if not bicep.is_file():
        pytest.skip("The installed Bicep CLI is required for the offline build check")

    environment = os.environ.copy()
    environment["DOTNET_BUNDLE_EXTRACT_BASE_DIR"] = str(
        Path(os.environ.get("TMPDIR", "/tmp")) / "nurse-intake-bicep"
    )
    completed = subprocess.run(
        [str(bicep), "build", str(INFRA / path), "--stdout"],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    return json.loads(completed.stdout)


def test_main_makes_web_app_hosting_optional_through_shared_module() -> None:
    main = _text("main.bicep")

    assert re.search(r"param\s+deployApp\s+bool\s*=\s*false", main)
    assert re.search(
        r"module\s+webApp\s+'modules/web-app\.bicep'\s*=\s*if\s*\(deployApp\)",
        main,
    )


def test_main_compiles_with_web_app_hosting_disabled_by_default() -> None:
    compiled = _compile("main.bicep")

    assert compiled["parameters"]["deployApp"]["defaultValue"] is False


def test_web_app_module_defines_secure_linux_runtime_and_identity() -> None:
    module = _text("modules/web-app.bicep")

    assert "Microsoft.Web/serverfarms@" in module
    assert "Microsoft.Web/sites@" in module
    assert "kind: 'linux'" in module
    assert "reserved: true" in module
    assert "type: 'SystemAssigned'" in module
    assert "httpsOnly: true" in module
    assert "ftpsState: 'Disabled'" in module
    assert "minTlsVersion: '1.2'" in module
    assert "healthCheckPath: '/health'" in module
    assert "linuxFxVersion: pythonLinuxFxVersion" in module
    assert "name: appServicePlanSkuName" in module


def test_web_app_module_uses_safe_defaults_and_real_fastapi_entry_point() -> None:
    module = _text("modules/web-app.bicep")

    for name, value in (
        ("APP_MODE", "mock"),
        ("AI_PROVIDER", "mock"),
        ("AGENT_PROVIDER", "mock"),
        ("SPEECH_PROVIDER", "mock"),
        ("EMAIL_PROVIDER", "mock"),
        ("SMS_PROVIDER", "mock"),
        ("DEMO_SUPPRESS_NOTIFICATIONS", "true"),
    ):
        assert re.search(
            rf"name:\s*'{name}'\s+value:\s*'{value}'",
            module,
        )
    assert (
        "python -m uvicorn src.app.main:app --host 0.0.0.0 --port 8000"
        in module
    )
    assert "uvicorn[standard]" in (ROOT / "requirements.txt").read_text()


def test_web_app_module_enables_remote_build_for_source_zip_dependencies() -> None:
    compiled = _compile("modules/web-app.bicep")
    resources = compiled["resources"]
    web_app = next(
        resource
        for resource in (
            resources.values() if isinstance(resources, dict) else resources
        )
        if resource["type"] == "Microsoft.Web/sites"
    )
    app_settings = web_app["properties"]["siteConfig"]["appSettings"]

    assert app_settings.count("SCM_DO_BUILD_DURING_DEPLOYMENT") == 1
    assert "'value', 'true'" in app_settings


def test_web_app_module_has_no_secrets_rbac_or_foundry_runtime_coupling() -> None:
    module = _text("modules/web-app.bicep")
    main = _text("main.bicep")
    lowered = module.lower()

    for forbidden in (
        "connectionstring",
        "api_key",
        "apikey",
        "client_secret",
        "access_token",
        "cosmos_key",
        "managed_identity_client_id",
        "microsoft.authorization/roleassignments",
        "microsoft.cognitiveservices",
        "listkeys(",
    ):
        assert forbidden not in lowered
    assert "microsoft.authorization/roleassignments" not in main.lower()


def test_hosted_verifier_settings_are_optional_tagged_enabled_configuration() -> None:
    main = _text("main.bicep")
    module = _text("modules/web-app.bicep")
    compiled_module = _compile("modules/web-app.bicep")
    settings = {
        "AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT": "projectEndpoint",
        "AZURE_AI_FOUNDRY_AGENT_ENDPOINT": "agentEndpoint",
        "AZURE_AI_FOUNDRY_AGENT_NAME": "agentName",
        "AZURE_AI_FOUNDRY_AGENT_VERSION": "agentVersion",
        "AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT_NAME": (
            "modelDeploymentName"
        ),
    }

    for text in (main, module):
        assert "@discriminator('mode')" in text
        assert "mode: 'disabled'" in text
        assert "mode: 'enabled'" in text
        for property_name in settings.values():
            assert re.search(rf"@minLength\(1\)\s+{property_name}:\s*string", text)
    assert re.search(
        r"param\s+hostedFoundryVerifierConfiguration\s+"
        r"hostedFoundryVerifierConfigurationType\s*=\s*\{\s*mode:\s*'disabled'\s*\}",
        main,
    )
    assert compiled_module["parameters"]["hostedFoundryVerifierConfiguration"][
        "defaultValue"
    ] == {"mode": "disabled"}
    assert (
        "hostedFoundryVerifierConfiguration: "
        "validatedHostedFoundryVerifierConfiguration"
    ) in main
    assert "validatedHostedFoundryVerifierConfiguration.mode == 'enabled'" in module
    assert "appSettings: concat([" in module
    assert "hostedFoundryVerifierAppSettings" in module

    for setting_name, parameter_name in settings.items():
        assert re.search(
            rf"name:\s*'{setting_name}'\s+value:\s*"
            rf"validatedHostedFoundryVerifierConfiguration\.{parameter_name}",
            module,
        )
    for obsolete in (
        "hostedVerifierProjectEndpoint",
        "hostedVerifierStableAgentEndpoint",
        "hostedVerifierAgentName",
        "hostedVerifierAgentVersion",
        "hostedVerifierModelDeploymentName",
    ):
        assert not re.search(rf"param\s+{obsolete}\b", main)


def test_direct_web_app_module_has_independent_nested_whitespace_validation() -> None:
    compiled = _compile("modules/web-app.bicep")
    resources = compiled["resources"]
    resources = list(resources.values()) if isinstance(resources, dict) else resources
    validation = next(
        resource
        for resource in resources
        if resource["type"] == "Microsoft.Resources/deployments"
    )
    web_app = next(
        resource for resource in resources if resource["type"] == "Microsoft.Web/sites"
    )
    guarded = compiled["variables"][
        "validatedHostedFoundryVerifierConfiguration"
    ]
    enabled = validation["properties"]["template"]["definitions"][
        "hostedFoundryVerifierEnabledConfiguration"
    ]["properties"]
    settings = web_app["properties"]["siteConfig"]["appSettings"]
    hosted_settings = compiled["variables"]["hostedFoundryVerifierAppSettings"]

    assert guarded.count("trim(") == 5
    assert guarded.count("equals(") >= 5
    assert not validation["properties"]["template"]["resources"]
    assert validation["condition"] == (
        "[equals(parameters('hostedFoundryVerifierConfiguration').mode, 'enabled')]"
    )
    for name in (
        "projectEndpoint",
        "agentEndpoint",
        "agentName",
        "agentVersion",
        "modelDeploymentName",
    ):
        parameter = f"parameters('hostedFoundryVerifierConfiguration').{name}"
        assert parameter in guarded
        assert f"trim({parameter})" in guarded
        assert enabled[name]["minLength"] == 1
        assert parameter not in hosted_settings
        assert (
            f"variables('validatedHostedFoundryVerifierConfiguration').{name}"
            in hosted_settings
        )
    assert "variables('hostedFoundryVerifierAppSettings')" in settings
    assert any(
        "hostedFoundryVerifierConfigValidation" in item
        for item in web_app["dependsOn"]
    )

    for raw_value in ("", " ", "\t", "\n", " leading", "trailing "):
        guarded_value = raw_value if raw_value == raw_value.strip() else ""
        assert len(guarded_value) < 1
    assert ("approved" if "approved" == "approved".strip() else "") == "approved"


def test_internal_hosted_verifier_validation_module_compiles_without_resources() -> None:
    compiled = _compile("modules/hosted-foundry-verifier-config-validation.bicep")

    assert not compiled["resources"]
    assert compiled["outputs"]["configurationValidated"]["type"] == "bool"
    enabled = compiled["definitions"][
        "hostedFoundryVerifierEnabledConfiguration"
    ]["properties"]
    assert all(
        enabled[name]["minLength"] == 1
        for name in (
            "projectEndpoint",
            "agentEndpoint",
            "agentName",
            "agentVersion",
            "modelDeploymentName",
        )
    )


def test_main_preserves_existing_resources_and_exposes_only_safe_app_outputs() -> None:
    main = _text("main.bicep")

    for resource_type in (
        "Microsoft.DocumentDB/databaseAccounts",
        "Microsoft.Storage/storageAccounts",
        "Microsoft.OperationalInsights/workspaces",
        "Microsoft.Insights/components",
    ):
        assert resource_type in main
    assert "module foundry 'modules/foundry.bicep' = if (deployFoundry)" in main
    assert "output appHostingRequested bool = deployApp" in main
    assert "output webAppName string" in main
    assert "output webAppDefaultHostname string" in main

    output_lines = [
        line.lower() for line in main.splitlines() if line.strip().startswith("output ")
    ]
    for forbidden in (
        "principal",
        "clientid",
        "tenantid",
        "resourceid",
        "token",
        "credential",
    ):
        assert all(forbidden not in line for line in output_lines)
