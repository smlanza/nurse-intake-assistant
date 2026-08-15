import importlib
import json
import os
from pathlib import Path
import re
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
INFRA = ROOT / "infra"
CLIENT_ID = "11111111-2222-4333-8444-555555555555"
TENANT_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
ANONYMOUS_PATHS = ("/health", "/version", "/demo/status")
AUTHENTICATION_MODULE = "modules/web-app-authentication.bicep"


def _compile(path: str) -> dict[str, object]:
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


def _service():
    return importlib.import_module(
        "src.app.services.web_app_authentication_verification"
    )


def test_authentication_v2_is_disabled_by_default_and_owned_once() -> None:
    main = (INFRA / "main.bicep").read_text()
    module = (INFRA / "modules/web-app.bicep").read_text()
    authentication = (INFRA / AUTHENTICATION_MODULE).read_text()
    compiled_main = _compile("main.bicep")
    compiled_module = _compile("modules/web-app.bicep")
    compiled_authentication = _compile(AUTHENTICATION_MODULE)

    for compiled in (compiled_main, compiled_module):
        assert compiled["parameters"]["appServiceAuthenticationConfiguration"][
            "defaultValue"
        ] == {"mode": "disabled"}
    assert main.count(
        "appServiceAuthenticationConfiguration: "
        "validatedAppServiceAuthenticationConfiguration"
    ) == 1
    assert module.count(
        "module webAppAuthentication 'web-app-authentication.bicep'"
    ) == 1
    assert "resource webAppAuthentication " not in module
    assert sum(
        path.read_text().count("resource webAppAuthentication ")
        for path in INFRA.rglob("*.bicep")
    ) == 1
    assert re.search(
        r"resource\s+webApp\s+'Microsoft\.Web/sites@2024-04-01'\s+"
        r"existing\s*=",
        authentication,
    )
    resources = compiled_authentication["resources"]
    resources = list(resources.values()) if isinstance(resources, dict) else resources
    assert [resource["type"] for resource in resources] == [
        "Microsoft.Web/sites/config"
    ]


def test_enabled_authentication_v2_contract_is_exact_and_non_secret() -> None:
    module = (INFRA / AUTHENTICATION_MODULE).read_text()
    compiled = _compile(AUTHENTICATION_MODULE)
    resources = compiled["resources"]
    resources = list(resources.values()) if isinstance(resources, dict) else resources
    auth = next(
        resource
        for resource in resources
        if resource["type"] == "Microsoft.Web/sites/config"
    )

    assert auth["name"] == (
        "[format('{0}/{1}', parameters('webAppName'), 'authsettingsV2')]"
    )
    assert "condition" not in auth
    properties = auth["properties"]
    assert properties["platform"] == {"enabled": True}
    assert properties["globalValidation"] == {
        "requireAuthentication": True,
        "unauthenticatedClientAction": "Return401",
        "excludedPaths": list(ANONYMOUS_PATHS),
    }
    assert properties["httpSettings"] == {"requireHttps": True}
    provider = properties["identityProviders"]["azureActiveDirectory"]
    assert provider["enabled"] is True
    assert set(provider["registration"]) == {"clientId", "openIdIssuer"}
    assert "entraClientId" in provider["registration"]["clientId"]
    assert "entraTenantId" in provider["registration"]["openIdIssuer"]

    anonymous_literals = re.findall(
        r"^\s*'(/[^']*)'\s*$",
        module,
        flags=re.MULTILINE,
    )
    assert anonymous_literals == list(ANONYMOUS_PATHS)
    for forbidden in (
        "clientSecret",
        "client_secret",
        "certificate",
        "Microsoft.Graph",
        "Microsoft.Authorization/roleAssignments",
        "Microsoft.Web/sites/slots",
    ):
        assert forbidden.casefold() not in module.casefold()


def test_offline_verifier_proves_disabled_and_enabled_contracts_without_ids() -> None:
    service = _service()

    disabled = service.check_web_app_authentication_contract(
        {"mode": "disabled"}
    )
    enabled = service.check_web_app_authentication_contract(
        {"mode": "enabled", "clientId": CLIENT_ID, "tenantId": TENANT_ID}
    )

    assert disabled.ok is True
    assert disabled.azure_request_attempted is False
    assert disabled.authentication_state_verified is True
    assert disabled.authentication_v2_enabled is False
    assert disabled.microsoft_entra_provider_verified is False
    assert disabled.client_application_identity_configuration_verified is False

    assert enabled.ok is True
    assert enabled.azure_request_attempted is False
    assert enabled.authentication_state_verified is True
    assert enabled.authentication_v2_enabled is True
    assert enabled.microsoft_entra_provider_verified is True
    assert enabled.authentication_required_verified is True
    assert enabled.https_required_verified is True
    assert enabled.anonymous_exclusions_verified is True
    assert enabled.client_application_identity_configuration_verified is True
    rendered = json.dumps(enabled.to_json_dict())
    assert CLIENT_ID not in rendered
    assert TENANT_ID not in rendered
    assert "login.microsoftonline.com" not in rendered


@pytest.mark.parametrize(
    "configuration",
    (
        {},
        {"mode": "unknown"},
        {"mode": "disabled", "clientId": CLIENT_ID},
        {"mode": "enabled", "clientId": CLIENT_ID},
        {"mode": "enabled", "tenantId": TENANT_ID},
        {"mode": "enabled", "clientId": "not-a-guid", "tenantId": TENANT_ID},
        {"mode": "enabled", "clientId": CLIENT_ID, "tenantId": TENANT_ID.upper()},
        {"mode": "enabled", "clientId": CLIENT_ID, "tenantId": "not-a-guid"},
        {
            "mode": "enabled",
            "clientId": CLIENT_ID,
            "tenantId": TENANT_ID,
            "clientSecret": "must-not-be-accepted",
        },
    ),
)
def test_offline_verifier_fails_closed_on_malformed_or_conflicting_configuration(
    configuration: dict[str, str],
) -> None:
    result = _service().check_web_app_authentication_contract(configuration)

    assert result.ok is False
    assert result.category == "configuration_invalid"
    assert result.azure_request_attempted is False
    assert result.authentication_state_verified is False
    assert "must-not-be-accepted" not in json.dumps(result.to_json_dict())


@pytest.mark.parametrize(
    "replacement",
    (
        "['/health', '/version']",
        "['/health', '/version', '/demo/status', '/demo']",
        "['/health', '/version', '/demo/status', '/demo/status']",
        "['/health', '/version', '/demo/*']",
        "['/health', '/version', '/intake/*']",
        "['/health', '/version', '/cases/*']",
        "['/health', '/version', '/docs']",
        "['/health', '/version', '/openapi.json']",
    ),
)
def test_offline_verifier_rejects_any_anonymous_allowlist_drift(
    tmp_path: Path,
    replacement: str,
) -> None:
    source = INFRA / AUTHENTICATION_MODULE
    mutated = tmp_path / "web-app-authentication.bicep"
    text = source.read_text()
    expected = """[
        '/health'
        '/version'
        '/demo/status'
      ]"""
    assert text.count(expected) == 1
    mutated.write_text(text.replace(expected, replacement, 1))
    result = _service().check_web_app_authentication_contract(
        {"mode": "disabled"},
        template_file=mutated,
    )

    assert result.ok is False
    assert result.category == "local_contract_invalid"
    assert result.azure_request_attempted is False
