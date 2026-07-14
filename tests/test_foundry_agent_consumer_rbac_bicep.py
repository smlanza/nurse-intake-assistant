import json
import os
from pathlib import Path
import re
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
INFRA = ROOT / "infra"
ENTRY_POINT = "foundry-agent-consumer-rbac.bicep"
MODULE = "modules/foundry-agent-consumer-rbac.bicep"
ROLE_GUID = "eed3b665-ab3a-47b6-8f48-c9382fb1dad6"


def _text(path: str) -> str:
    return (INFRA / path).read_text()


def test_separate_entry_point_derives_principal_from_existing_web_app() -> None:
    entry_point = _text(ENTRY_POINT)

    assert "targetScope = 'resourceGroup'" in entry_point
    assert "resource webApp 'Microsoft.Web/sites@2024-04-01' existing" in entry_point
    assert "webAppPrincipalId: webApp.identity.principalId" in entry_point
    assert re.search(
        r"module\s+foundryAgentConsumerRbac\s+"
        r"'modules/foundry-agent-consumer-rbac\.bicep'",
        entry_point,
    )

    parameters = re.findall(r"^param\s+(\w+)\s+", entry_point, re.MULTILINE)
    assert parameters == ["webAppName", "foundryAccountName", "foundryProjectName"]


def test_module_uses_existing_foundry_project_as_assignment_scope() -> None:
    module = _text(MODULE)

    assert (
        "resource foundryAccount "
        "'Microsoft.CognitiveServices/accounts@2025-06-01' existing"
        in module
    )
    assert (
        "resource foundryProject "
        "'Microsoft.CognitiveServices/accounts/projects@2025-06-01' existing"
        in module
    )
    assert "parent: foundryAccount" in module
    assert "Microsoft.Authorization/roleAssignments@" in module
    assert "scope: foundryProject" in module
    assert "principalType: 'ServicePrincipal'" in module


def test_module_uses_exact_consumer_role_and_deterministic_assignment_name() -> None:
    module = _text(MODULE)

    assert f"var foundryAgentConsumerRoleDefinitionGuid = '{ROLE_GUID}'" in module
    assert "subscriptionResourceId(" in module
    assert "'Microsoft.Authorization/roleDefinitions'" in module
    assert "foundryAgentConsumerRoleDefinitionGuid" in module
    assert re.search(
        r"name:\s*guid\(\s*foundryProject\.id,\s*"
        r"webAppPrincipalId,\s*foundryAgentConsumerRoleDefinitionId\s*\)",
        module,
    )
    assert "roleDefinitionId: foundryAgentConsumerRoleDefinitionId" in module
    assert "newGuid(" not in module


def test_module_grants_no_broader_or_custom_role() -> None:
    module = _text(MODULE)

    for forbidden in (
        "Foundry User",
        "Foundry Project Manager",
        "Foundry Owner",
        "Contributor",
        "Cognitive Services",
        "customRole",
        "roleDefinitions@",
    ):
        assert forbidden not in module
    assert re.search(r"\bOwner\b", module) is None


def test_rbac_is_not_coupled_to_existing_infrastructure_templates() -> None:
    for path in (
        "main.bicep",
        "modules/web-app.bicep",
        "modules/foundry.bicep",
    ):
        text = _text(path)
        assert "Microsoft.Authorization/roleAssignments" not in text
        assert ROLE_GUID not in text
        assert "foundry-agent-consumer-rbac.bicep" not in text


def test_entry_point_has_only_safe_factual_outputs_and_no_agent_operations() -> None:
    combined = _text(ENTRY_POINT) + _text(MODULE)
    entry_point = _text(ENTRY_POINT)
    output_lines = [
        line.lower()
        for line in entry_point.splitlines()
        if line.strip().startswith("output ")
    ]

    for forbidden in (
        "principal",
        "clientid",
        "tenantid",
        "subscriptionid",
        "roleassignmentid",
        "roledefinitionid",
        "resourceid",
        "endpoint",
        "agentname",
        "agentversion",
        "token",
        "credential",
    ):
        assert all(forbidden not in line for line in output_lines)
    for forbidden in (
        "Microsoft.CognitiveServices/accounts/deployments",
        "Microsoft.CognitiveServices/accounts/agents",
        "agent_endpoint",
        "get_openai_client",
        "invoke",
        "verification",
        "model call",
    ):
        assert forbidden not in combined


def test_rbac_templates_compile_offline() -> None:
    bicep = Path.home() / ".azure" / "bin" / "bicep"
    if not bicep.is_file():
        pytest.skip("The installed Bicep CLI is required for the offline build check")

    environment = os.environ.copy()
    environment["DOTNET_BUNDLE_EXTRACT_BASE_DIR"] = str(
        Path(os.environ.get("TMPDIR", "/tmp")) / "nurse-intake-bicep"
    )
    for path in (MODULE, ENTRY_POINT):
        completed = subprocess.run(
            [str(bicep), "build", str(INFRA / path), "--stdout"],
            check=True,
            capture_output=True,
            text=True,
            env=environment,
        )
        compiled = json.loads(completed.stdout)
        assert compiled["$schema"].endswith("deploymentTemplate.json#")
