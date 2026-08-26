import json
import os
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "infra/modules/web-app-telemetry.bicep"


def _compile() -> dict[str, object]:
    bicep = Path.home() / ".azure" / "bin" / "bicep"
    if not bicep.is_file():
        pytest.skip("The installed Bicep CLI is required for the offline build check")
    environment = os.environ.copy()
    environment["DOTNET_BUNDLE_EXTRACT_BASE_DIR"] = str(
        Path(os.environ.get("TMPDIR", "/tmp")) / "nurse-intake-bicep"
    )
    completed = subprocess.run(
        [str(bicep), "build", str(TEMPLATE), "--stdout"],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    return json.loads(completed.stdout)


def _resources(compiled: dict[str, object]) -> list[dict[str, object]]:
    resources = compiled["resources"]
    assert isinstance(resources, (dict, list))
    return list(resources.values()) if isinstance(resources, dict) else resources


def test_hosted_telemetry_template_compiles_to_one_deployable_configuration_child() -> None:
    compiled = _compile()
    resources = _resources(compiled)
    deployable = [resource for resource in resources if not resource.get("existing")]

    assert set(compiled["parameters"]) == {
        "webAppName",
        "applicationInsightsName",
    }
    assert compiled.get("outputs", {}) == {}
    assert len(deployable) == 1
    assert deployable[0]["type"] == "Microsoft.Web/sites/config"
    assert "appsettings" in str(deployable[0]["name"]).casefold()
    assert {
        resource["type"]
        for resource in resources
        if resource.get("existing")
    } <= {"Microsoft.Web/sites", "Microsoft.Insights/components"}
    assert not {
        "Microsoft.Resources/deployments",
        "Microsoft.Web/serverfarms",
        "Microsoft.KeyVault/vaults",
        "Microsoft.DocumentDB/databaseAccounts",
        "Microsoft.Storage/storageAccounts",
        "Microsoft.OperationalInsights/workspaces",
        "Microsoft.CognitiveServices/accounts",
        "Microsoft.Authorization/roleAssignments",
    }.intersection(resource["type"] for resource in resources)


def test_hosted_telemetry_template_preserves_settings_and_resolves_connection_internally() -> None:
    compiled = _compile()
    rendered = json.dumps(compiled, separators=(",", ":"), sort_keys=True)

    assert "TELEMETRY_PROVIDER" in rendered
    assert "azure-monitor" in rendered
    assert "APPLICATIONINSIGHTS_CONNECTION_STRING" in rendered
    assert "ConnectionString" in rendered
    assert "list(" in rendered
    assert "APPLICATIONINSIGHTS_CONNECTION_STRING" not in compiled["parameters"]
    assert "APPLICATIONINSIGHTS_CONNECTION_STRING" not in compiled.get("outputs", {})

