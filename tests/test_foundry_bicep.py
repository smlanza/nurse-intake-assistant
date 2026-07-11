from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
INFRA = ROOT / "infra"


def _text(name: str) -> str:
    return (INFRA / name).read_text()


def test_main_preserves_core_resources_and_outputs() -> None:
    text = _text("main.bicep")
    for resource_type in (
        "Microsoft.DocumentDB/databaseAccounts",
        "Microsoft.Storage/storageAccounts",
        "Microsoft.OperationalInsights/workspaces",
        "Microsoft.Insights/components",
    ):
        assert resource_type in text
    assert "paths: [\n          '/createdDate'" in text
    assert "output applicationInsightsConnectionString" in text


def test_main_makes_foundry_optional_through_shared_module() -> None:
    text = _text("main.bicep")
    assert re.search(r"param\s+deployFoundry\s+bool\s*=\s*false", text)
    assert re.search(
        r"module\s+foundry\s+'modules/foundry\.bicep'\s*=\s*if\s*\(deployFoundry\)",
        text,
    )


def test_foundry_only_uses_shared_module_and_no_application_resources() -> None:
    text = _text("foundry-only.bicep")
    assert "targetScope = 'resourceGroup'" in text
    assert re.search(r"module\s+foundry\s+'modules/foundry\.bicep'\s*=\s*{", text)
    for forbidden in (
        "Microsoft.DocumentDB",
        "Microsoft.Storage",
        "Microsoft.OperationalInsights",
        "Microsoft.Insights/components",
    ):
        assert forbidden not in text


def test_shared_module_has_foundry_project_and_model_resources() -> None:
    text = _text("modules/foundry.bicep")
    assert "Microsoft.CognitiveServices/accounts@" in text
    assert "kind: 'AIServices'" in text
    assert "allowProjectManagement: true" in text
    assert "Microsoft.CognitiveServices/accounts/projects@" in text
    assert "Microsoft.CognitiveServices/accounts/deployments@" in text
    assert "name: modelDeploymentName" in text


def test_safe_outputs_exist_without_secret_operations() -> None:
    combined = _text("modules/foundry.bicep") + _text("foundry-only.bicep")
    for output_name in (
        "foundryResourceName",
        "foundryProjectName",
        "foundryProjectEndpoint",
        "modelDeploymentName",
    ):
        assert re.search(rf"output\s+{output_name}\s+", combined)
    lowered = combined.lower()
    for forbidden in ("listkeys(", "accesskey", "token", "connectionstring"):
        assert forbidden not in lowered


def test_example_parameter_file_is_committed_but_local_file_is_ignored() -> None:
    example = _text("foundry-only.example.bicepparam")
    for parameter in (
        "modelDeploymentName",
        "modelName",
        "modelVersion",
        "modelPublisherFormat",
        "modelSkuName",
        "modelCapacity",
    ):
        assert re.search(rf"param\s+{parameter}\s*=", example)
    gitignore = (ROOT / ".gitignore").read_text()
    assert "infra/foundry-only.bicepparam" in gitignore
    assert "foundry-only.example.bicepparam" not in gitignore
