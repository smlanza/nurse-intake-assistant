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


def test_main_makes_web_app_hosting_optional_through_shared_module() -> None:
    main = _text("main.bicep")

    assert re.search(r"param\s+deployApp\s+bool\s*=\s*false", main)
    assert re.search(
        r"module\s+webApp\s+'modules/web-app\.bicep'\s*=\s*if\s*\(deployApp\)",
        main,
    )


def test_main_compiles_with_web_app_hosting_disabled_by_default() -> None:
    bicep = Path.home() / ".azure" / "bin" / "bicep"
    if not bicep.is_file():
        pytest.skip("The installed Bicep CLI is required for the offline build check")

    environment = os.environ.copy()
    environment["DOTNET_BUNDLE_EXTRACT_BASE_DIR"] = str(
        Path(os.environ.get("TMPDIR", "/tmp")) / "nurse-intake-bicep"
    )
    completed = subprocess.run(
        [
            str(bicep),
            "build",
            str(INFRA / "main.bicep"),
            "--stdout",
        ],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    compiled = json.loads(completed.stdout)

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
        "azure_ai_foundry_agent_endpoint",
        "azure_ai_foundry_agent_name",
        "azure_ai_foundry_agent_version",
        "managed_identity_client_id",
        "microsoft.authorization/roleassignments",
        "microsoft.cognitiveservices",
        "listkeys(",
    ):
        assert forbidden not in lowered
    assert "microsoft.authorization/roleassignments" not in main.lower()


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
