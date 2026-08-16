import importlib
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
CLIENT_ID = "11111111-2222-4333-8444-555555555555"
TENANT_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
SUBSCRIPTION_ID = "00000000-0000-4000-8000-000000000001"
RESOURCE_GROUP = "fictional-resource-group"
WEB_APP_NAME = "fictional-nurse-intake-web-app"
BASE_URL = f"https://{WEB_APP_NAME}.azurewebsites.net"
ARTIFACT_DIGEST = "a" * 64


def _script():
    return importlib.import_module("scripts.accept_web_app_authentication")


def _generation(script):
    return script.CurrentGenerationBinding(
        configuration_fingerprint="b" * 64,
        correlation_fingerprint="c" * 64,
        run_epoch="d" * 32,
        resource_group=RESOURCE_GROUP,
        web_app_name=WEB_APP_NAME,
        hosted_origin=BASE_URL,
        current_day_verified=True,
    )


def _request(script):
    return script.AuthenticationAcceptanceRequest(
        subscription_name="Fictional Subscription",
        resource_group=RESOURCE_GROUP,
        location="centralus",
        environment_name="dev",
        project_name="nurse",
        web_app_name=WEB_APP_NAME,
        hosted_origin=BASE_URL,
        client_application_id=CLIENT_ID,
        tenant_id=TENANT_ID,
        hosted_verifier_project_endpoint=(
            "https://fictional.services.ai.azure.com/api/projects/demo"
        ),
        hosted_verifier_stable_agent_endpoint=(
            "https://fictional.services.ai.azure.com/api/projects/demo/"
            "agents/nurse-agent/endpoint/protocols/openai"
        ),
        hosted_verifier_agent_name="nurse-agent",
        hosted_verifier_agent_version="1",
        hosted_verifier_model_deployment_name="nurse-model",
        template_file=ROOT / "infra/modules/web-app-authentication.bicep",
        generation=_generation(script),
    )


def _prepared_template(script, tmp_path: Path):
    del tmp_path
    path = ROOT / "infra/modules/web-app-authentication.bicep"
    payload = path.read_bytes()
    return script.PreparedAuthenticationTemplate(
        path=path,
        digest=script.hashlib.sha256(payload).hexdigest(),
    )


def _account_payload() -> str:
    return json.dumps(
        {
            "environmentName": "AzureCloud",
            "id": SUBSCRIPTION_ID,
            "name": "Fictional Subscription",
            "tenantId": TENANT_ID,
        }
    )


def _web_app_payload() -> str:
    return json.dumps(
        {
            "defaultHostName": f"{WEB_APP_NAME}.azurewebsites.net",
            "httpsOnly": True,
            "id": (
                f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/{RESOURCE_GROUP}/"
                f"providers/Microsoft.Web/sites/{WEB_APP_NAME}"
            ),
            "name": WEB_APP_NAME,
            "resourceGroup": RESOURCE_GROUP,
            "location": "Central US",
            "kind": "app,linux",
            "serverFarmId": (
                f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/{RESOURCE_GROUP}/"
                "providers/Microsoft.Web/serverfarms/nurse-dev-plan-private"
            ),
            "tags": {},
            "identityType": "SystemAssigned",
        }
    )


def _site_config_payload(*, always_on: bool = True) -> str:
    return json.dumps(
        {
            "linuxFxVersion": "PYTHON|3.12",
            "appCommandLine": (
                "python -m uvicorn src.app.main:app --host 0.0.0.0 --port 8000"
            ),
            "ftpsState": "Disabled",
            "minTlsVersion": "1.2",
            "scmMinTlsVersion": "1.2",
            "healthCheckPath": "/health",
            "alwaysOn": always_on,
        }
    )


def _app_settings_payload(script) -> str:
    settings = {
        **script.BASELINE_APP_SETTINGS,
        "AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT": (
            "https://fictional.services.ai.azure.com/api/projects/demo"
        ),
        "AZURE_AI_FOUNDRY_AGENT_ENDPOINT": (
            "https://fictional.services.ai.azure.com/api/projects/demo/"
            "agents/nurse-agent/endpoint/protocols/openai"
        ),
        "AZURE_AI_FOUNDRY_AGENT_NAME": "nurse-agent",
        "AZURE_AI_FOUNDRY_AGENT_VERSION": "1",
        "AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT_NAME": "nurse-model",
    }
    return json.dumps(
        [
            {"name": name, "value": value}
            for name, value in reversed(tuple(settings.items()))
        ]
    )


def _disabled_auth_payload() -> str:
    return json.dumps(
        {
            "clientId": None,
            "entraEnabled": False,
            "excludedPaths": [],
            "openIdIssuer": None,
            "platformEnabled": False,
            "requireAuthentication": False,
            "requireHttps": True,
            "unauthenticatedClientAction": "RedirectToLoginPage",
        }
    )


def _enabled_auth_payload(*, exclusions=None, issuer=None) -> str:
    return json.dumps(
        {
            "clientId": CLIENT_ID,
            "entraEnabled": True,
            "excludedPaths": exclusions
            if exclusions is not None
            else ["/health", "/version", "/demo/status"],
            "openIdIssuer": issuer
            or f"https://login.microsoftonline.com/{TENANT_ID}/v2.0",
            "platformEnabled": True,
            "requireAuthentication": True,
            "requireHttps": True,
            "unauthenticatedClientAction": "Return401",
        }
    )


def _mutated_enabled_auth_payload(
    *,
    field: str | None = None,
    value=None,
    remove: bool = False,
    extra: bool = False,
) -> str:
    payload = json.loads(_enabled_auth_payload())
    if field is not None:
        if remove:
            del payload[field]
        else:
            payload[field] = value
    if extra:
        payload["privateAzureField"] = "private-azure-value"
    return json.dumps(payload)


def _preview_payload(
    *,
    unrelated: bool = False,
    parent_web_app_action: str | None = None,
    authentication_action: str = "Create",
    authentication_web_app_name: str = WEB_APP_NAME,
    authentication_resource_group: str = RESOURCE_GROUP,
    duplicate_authentication: bool = False,
) -> str:
    root = f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/{RESOURCE_GROUP}/providers"
    authentication_root = (
        f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/"
        f"{authentication_resource_group}/providers"
    )
    authentication_change = {
        "changeType": authentication_action,
        "resourceId": (
            f"{authentication_root}/Microsoft.Web/sites/"
            f"{authentication_web_app_name}/config/authsettingsV2"
        ),
        "before": {"properties": {"privatePreviewValue": "private-before"}},
        "after": {"properties": {"privatePreviewValue": "private-after"}},
        "delta": {"changes": [{"path": "properties.privatePreviewValue"}]},
    }
    changes = [
        authentication_change,
    ]
    if duplicate_authentication:
        changes.append(dict(authentication_change))
    if parent_web_app_action is not None:
        changes.append(
            {
                "changeType": parent_web_app_action,
                "resourceId": f"{root}/Microsoft.Web/sites/{WEB_APP_NAME}",
                "before": {"privateWebValue": "private-web-before"},
                "after": {"privateWebValue": "private-web-after"},
            }
        )
    if unrelated:
        changes.append(
            {
                "changeType": "Modify",
                "resourceId": f"{root}/Microsoft.Storage/storageAccounts/other",
            }
        )
    return json.dumps({"changes": changes, "tenantId": "must-never-escape"})


def _structural_diagnostic_preview_payload() -> str:
    root = (
        f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/{RESOURCE_GROUP}/"
        "providers"
    )
    return json.dumps(
        {
            "changes": [
                {
                    "changeType": "Modify",
                    "resourceId": (
                        f"{root}/Microsoft.Web/sites/{WEB_APP_NAME}/"
                        "config/authsettingsV2"
                    ),
                },
                {
                    "changeType": "Ignore",
                    "resourceId": (
                        f"{root}/Microsoft.Web/sites/{WEB_APP_NAME}"
                    ),
                },
                {
                    "changeType": "Ignore",
                    "resourceId": (
                        f"{root}/Microsoft.Network/virtualNetworks/"
                        "private-network"
                    ),
                },
                {
                    "changeType": "Deploy",
                    "resourceId": (
                        f"{root}/Microsoft.Storage/storageAccounts/"
                        "deployed-storage"
                    ),
                },
            ]
        }
    )


class FakeRunner:
    def __init__(
        self,
        script,
        *,
        preview_stdout: str | None = None,
        preview_return_code: int = 0,
        preview_authentication_action: str = "Create",
        hosting_drift_after_preview: bool = False,
    ) -> None:
        self.script = script
        self.commands: list[list[str]] = []
        self.auth_reads = 0
        self.preview_stdout = preview_stdout
        self.preview_return_code = preview_return_code
        self.preview_authentication_action = preview_authentication_action
        self.hosting_drift_after_preview = hosting_drift_after_preview
        self.site_config_reads = 0

    def run(self, args: list[str]):
        self.commands.append(args)
        result = self.script.CommandResult
        if args[:3] == ["az", "account", "show"]:
            return result(0, _account_payload(), "")
        if args[:3] == ["az", "cloud", "show"]:
            return result(0, "https://login.microsoftonline.com/\n", "")
        if args[:3] == ["az", "webapp", "show"]:
            return result(0, _web_app_payload(), "")
        if args[:4] == ["az", "webapp", "config", "show"]:
            self.site_config_reads += 1
            return result(
                0,
                _site_config_payload(
                    always_on=not (
                        self.hosting_drift_after_preview
                        and self.site_config_reads > 1
                    )
                ),
                "",
            )
        if args[:5] == ["az", "webapp", "config", "appsettings", "list"]:
            return result(0, _app_settings_payload(self.script), "")
        if args[:3] == ["az", "resource", "show"]:
            self.auth_reads += 1
            payload = (
                _enabled_auth_payload()
                if self.auth_reads == 3
                else _disabled_auth_payload()
            )
            return result(0, payload, "")
        if args[:4] == ["az", "deployment", "group", "what-if"]:
            return result(
                self.preview_return_code,
                self.preview_stdout
                if self.preview_stdout is not None
                else _preview_payload(
                    authentication_action=self.preview_authentication_action
                ),
                "raw stderr secret",
            )
        if args[:4] == ["az", "deployment", "group", "create"]:
            return result(0, json.dumps({"id": "raw-arm-id"}), "")
        raise AssertionError(f"unexpected command shape: {args[:4]}")


class FakeTransport:
    def __init__(self, script) -> None:
        self.script = script
        self.paths: list[str] = []

    def get(self, path: str, timeout_seconds: float):
        self.paths.append(path)
        response = self.script.HttpResponse
        if path == "/health":
            return response(
                200,
                b'{"status":"ok","service":"nurse-intake-assistant"}',
            )
        if path == "/version":
            return response(
                200,
                json.dumps(
                    {
                        "service": "nurse-intake-assistant",
                        "version": "0.1.0",
                        "environment": "hosted",
                        "artifactDigest": ARTIFACT_DIGEST,
                    }
                ).encode(),
            )
        if path == "/demo/status":
            return response(
                200,
                json.dumps(
                    {
                        "appMode": "mock",
                        "aiProvider": "mock",
                        "speechProvider": "mock",
                        "emailProvider": "mock",
                        "smsProvider": "mock",
                        "agentProvider": "mock",
                        "safetyBoundary": "demo",
                        "demoModeReady": True,
                        "notificationsSuppressed": True,
                        "safeForLocalDemo": True,
                        "warnings": [],
                        "agentStatus": {
                            "provider": "mock",
                            "ready": True,
                            "mode": "mock",
                            "missingSettings": [],
                        },
                        "agentProviderStatus": {
                            "provider": "mock",
                            "configured": True,
                            "liveValidation": "not_attempted",
                            "manualValidationAvailable": False,
                            "manualValidationCommand": None,
                            "missingSettings": [],
                            "warnings": [],
                        },
                    }
                ).encode(),
            )
        if path in {"/demo", "/cases", "/openapi.json"}:
            return response(401, b"raw response body must not escape")
        raise AssertionError(path)


def test_import_performs_no_azure_or_network_operation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sys.modules.pop("scripts.accept_web_app_authentication", None)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("import must remain offline"),
    )

    _script()


def test_auth_read_targets_exact_v2_resource_and_projects_explicit_properties() -> None:
    script = _script()
    commands: list[list[str]] = []

    class RecordingRunner:
        def run(self, args: list[str]):
            commands.append(args)
            return script.CommandResult(0, _enabled_auth_payload(), "")

    stdout = script._read_authentication_stdout(
        RecordingRunner(),
        _request(script),
    )

    assert stdout == _enabled_auth_payload()
    assert len(commands) == 1
    command = commands[0]
    assert command[:3] == ["az", "resource", "show"]
    assert command[command.index("--namespace") + 1] == "Microsoft.Web"
    assert command[command.index("--parent") + 1] == f"sites/{WEB_APP_NAME}"
    assert command[command.index("--resource-type") + 1] == "config"
    assert command[command.index("--name") + 1] == "authsettingsV2"
    assert command[command.index("--api-version") + 1] == "2024-04-01"
    assert "keys(" not in script.AUTH_QUERY
    assert "properties.platform.enabled" in script.AUTH_QUERY
    assert "properties.identityProviders.azureActiveDirectory.enabled" in (
        script.AUTH_QUERY
    )
    assert (
        "properties.identityProviders.azureActiveDirectory.registration.clientId"
        in script.AUTH_QUERY
    )


def test_check_is_offline_and_sanitized() -> None:
    script = _script()

    result = script.check_authentication_acceptance_request(_request(script))

    assert result.ok is True
    assert result.category == "success"
    assert result.current_generation_verified is True
    assert result.local_contract_validated is True
    assert result.azure_operation_attempted is False
    rendered = json.dumps(result.to_json_dict())
    for forbidden in (CLIENT_ID, TENANT_ID, RESOURCE_GROUP, WEB_APP_NAME, BASE_URL):
        assert forbidden not in rendered


def test_cli_uses_operator_local_authentication_identifiers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = _script()
    monkeypatch.setenv("OPERATOR_ENTRA_APPLICATION_ID", CLIENT_ID)
    monkeypatch.setenv("OPERATOR_ENTRA_TENANT_ID", TENANT_ID)

    args = script._parse_args(
        ["--check", "--config", ".env.daily-azure.local"]
    )

    assert args.client_application_id == CLIENT_ID
    assert args.tenant_id == TENANT_ID


def test_missing_operator_local_identifiers_fail_before_runner_construction(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = _script()
    monkeypatch.delenv("OPERATOR_ENTRA_APPLICATION_ID", raising=False)
    monkeypatch.delenv("OPERATOR_ENTRA_TENANT_ID", raising=False)

    def load_private_request(args):
        assert args.client_application_id is None
        assert args.tenant_id is None
        return None

    monkeypatch.setattr(script, "_load_private_request", load_private_request)
    monkeypatch.setattr(
        script,
        "_create_azure_cli_runner",
        lambda: pytest.fail("missing identifiers must stop before runner construction"),
    )

    exit_code = script.main(
        [
            "--live",
            "--json",
            "--config",
            ".env.daily-azure.local",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert payload["category"] == "invalid_configuration"
    assert payload["azure_operation_attempted"] is False


def test_disabled_authentication_accepts_only_exact_absent_child_shape() -> None:
    script = _script()
    absent = {field: None for field in script.AUTH_FIELDS}

    proof = script._parse_disabled_authentication_evidence(json.dumps(absent))

    assert proof is not None
    assert proof.enabled is False
    absent["requireHttps"] = True
    assert script._parse_disabled_authentication_evidence(json.dumps(absent)) is None


@pytest.mark.parametrize(
    "field,value",
    (
        ("client_application_id", ""),
        ("client_application_id", " " + CLIENT_ID),
        ("client_application_id", "not-a-guid"),
        ("tenant_id", ""),
        ("tenant_id", TENANT_ID.upper()),
    ),
)
def test_invalid_identifiers_fail_before_runner_construction(
    field: str,
    value: str,
) -> None:
    script = _script()
    request = script.replace(_request(script), **{field: value})

    result = script.check_authentication_acceptance_request(request)

    assert result.ok is False
    assert result.category == "invalid_configuration"
    assert result.azure_operation_attempted is False


def test_authentication_acceptance_uses_direct_existing_web_app_boundary() -> None:
    script = _script()
    if not (Path.home() / ".azure/bin/bicep").is_file():
        pytest.skip("Bicep CLI is not installed")

    request = _request(script)
    prepared = script.prepare_authentication_deployment_template(
        request.template_file
    )

    assert prepared is not None
    try:
        assert prepared.path == request.template_file
        command = script._authentication_deployment_command(
            request,
            "what-if",
            prepared,
        )
        assert command[command.index("--template-file") + 1] == str(
            ROOT / "infra/modules/web-app-authentication.bicep"
        )
        parameters = command[command.index("--parameters") + 1 :]
        assert f"webAppName={request.web_app_name}" in parameters
        assert f"entraClientId={CLIENT_ID}" in parameters
        assert f"entraTenantId={TENANT_ID}" in parameters
        assert len(parameters) == 3
    finally:
        if prepared.path != request.template_file:
            prepared.path.unlink()


@pytest.mark.parametrize("authentication_action", ("Create", "Modify"))
def test_live_acceptance_uses_one_preview_one_mutation_and_independent_proofs(
    tmp_path: Path,
    authentication_action: str,
) -> None:
    script = _script()
    request = _request(script)
    runner = FakeRunner(
        script,
        preview_authentication_action=authentication_action,
    )
    transport = FakeTransport(script)
    summaries = []

    result = script.accept_web_app_authentication(
        request,
        runner=runner,
        current_generation_reader=lambda: request.generation,
        approval_callback=lambda summary: summaries.append(summary) or True,
        artifact_digest_reader=lambda: ARTIFACT_DIGEST,
        transport_factory=lambda base_url: transport,
        deployment_template=_prepared_template(script, tmp_path),
    )

    assert result.ok is True
    assert result.category == "success"
    assert result.preview_diagnostic is None
    assert result.authentication_enabled is True
    assert result.entra_provider_verified is True
    assert result.tenant_binding_verified is True
    assert result.application_binding_verified is True
    assert result.unauthenticated_action_verified is True
    assert result.anonymous_exclusions_verified is True
    assert result.deployment_attempted is True
    assert result.deployment_accepted is True
    assert result.configuration_verified is True
    assert result.anonymous_readiness_routes_verified is True
    assert result.protected_routes_verified is True
    assert result.hosted_readiness_verified is True
    assert result.azure_mutation_made is True
    assert result.authenticated_sign_in_verified is False
    assert len(summaries) == 1
    assert summaries[0].unrelated_resource_changes == 0
    assert summaries[0].anonymous_readiness_exclusions == 3
    assert sum(command[:4] == ["az", "deployment", "group", "what-if"] for command in runner.commands) == 1
    assert sum(command[:4] == ["az", "deployment", "group", "create"] for command in runner.commands) == 1
    preview = next(
        command
        for command in runner.commands
        if command[:4] == ["az", "deployment", "group", "what-if"]
    )
    assert preview[preview.index("--result-format") + 1] == "FullResourcePayloads"
    assert preview[preview.index("--exclude-change-types") + 1] == "Ignore"
    assert preview[preview.index("--mode") + 1] == "Incremental"
    mutation = next(
        command
        for command in runner.commands
        if command[:4] == ["az", "deployment", "group", "create"]
    )
    assert mutation[mutation.index("--template-file") + 1].endswith(
        "/infra/modules/web-app-authentication.bicep"
    )
    assert mutation[mutation.index("--mode") + 1] == "Incremental"
    rendered_mutation = " ".join(mutation)
    assert "deployAppServicePlan" not in rendered_mutation
    assert "webAppName=" in rendered_mutation
    assert "entraClientId=" in rendered_mutation
    assert "entraTenantId=" in rendered_mutation
    for unrelated in (
        "cosmos",
        "storage",
        "keyVault",
    ):
        assert unrelated not in rendered_mutation
    assert transport.paths == [
        "/health",
        "/version",
        "/demo/status",
        "/health",
        "/version",
        "/demo/status",
        "/health",
        "/version",
        "/demo/status",
        "/demo",
        "/cases",
        "/openapi.json",
        "/health",
        "/version",
        "/demo/status",
    ]
    rendered = json.dumps(result.to_json_dict())
    for forbidden in (
        CLIENT_ID,
        TENANT_ID,
        SUBSCRIPTION_ID,
        RESOURCE_GROUP,
        WEB_APP_NAME,
        BASE_URL,
        "raw stderr secret",
        "raw-arm-id",
        "raw response body",
        "private-before",
        "private-after",
        "privatePreviewValue",
    ):
        assert forbidden not in rendered


@pytest.mark.parametrize(
    ("preview_stdout", "preview_return_code", "expected_diagnostic"),
    (
        (
            "private-command-output",
            1,
            {"reason": "preview_command_failed", "record_count": None},
        ),
        (
            json.dumps({"privateClientId": CLIENT_ID}),
            0,
            {
                "reason": "preview_parse_failed",
                "record_count": None,
                "malformed_or_unsupported_evidence_present": True,
            },
        ),
        (
            json.dumps({"changes": []}),
            0,
            {
                "reason": "topology_mismatch",
                "record_count": 0,
                "authentication_resource_count": 0,
                "unexpected_resource_count": 0,
                "expected_multiplicity_proven": False,
            },
        ),
        *(
            (
                _preview_payload(authentication_action=action),
                0,
                {
                    "reason": "action_not_allowed",
                    "record_count": 1,
                    "authentication_resource_count": 1,
                    "unexpected_resource_count": 0,
                    "expected_multiplicity_proven": True,
                    "authentication_action": action,
                    "malformed_or_unsupported_evidence_present": (
                        action == "Unsupported"
                    ),
                },
            )
            for action in ("NoChange", "Delete", "Deploy", "Unsupported")
        ),
        (
            _preview_payload(authentication_web_app_name="other-web-app"),
            0,
            {
                "reason": "identity_not_proven",
                "record_count": 1,
                "authentication_resource_count": 1,
                "expected_web_app_relationship_proven": False,
                "exact_identity_scope_proven": False,
                "expected_multiplicity_proven": True,
            },
        ),
        (
            _preview_payload(authentication_resource_group="other-resource-group"),
            0,
            {
                "reason": "identity_not_proven",
                "record_count": 1,
                "authentication_resource_count": 1,
                "expected_web_app_relationship_proven": True,
                "exact_identity_scope_proven": False,
                "expected_multiplicity_proven": True,
            },
        ),
        (
            _preview_payload(duplicate_authentication=True),
            0,
            {
                "reason": "topology_mismatch",
                "record_count": 2,
                "authentication_resource_count": 2,
                "unexpected_resource_count": 0,
                "expected_multiplicity_proven": False,
            },
        ),
        (
            _preview_payload(parent_web_app_action="Modify"),
            0,
            {
                "reason": "topology_mismatch",
                "record_count": 2,
                "authentication_resource_count": 1,
                "unexpected_resource_count": 1,
                "expected_multiplicity_proven": False,
                "unexpected_change_counts": [
                    {
                        "action": "Modify",
                        "resource_family": "web_site",
                        "provider_family": None,
                        "count": 1,
                    }
                ],
            },
        ),
        (
            _preview_payload(unrelated=True),
            0,
            {
                "reason": "topology_mismatch",
                "record_count": 2,
                "authentication_resource_count": 1,
                "unexpected_resource_count": 1,
                "expected_multiplicity_proven": False,
                "unexpected_change_counts": [
                    {
                        "action": "Modify",
                        "resource_family": "storage_account",
                        "provider_family": None,
                        "count": 1,
                    }
                ],
            },
        ),
        (
            _structural_diagnostic_preview_payload(),
            0,
            {
                "reason": "topology_mismatch",
                "record_count": 4,
                "authentication_resource_count": 1,
                "unexpected_resource_count": 3,
                "expected_multiplicity_proven": False,
                "authentication_action": "Modify",
            },
        ),
    ),
)
def test_rejected_preview_is_diagnosed_and_fails_closed_before_approval_or_mutation(
    tmp_path: Path,
    preview_stdout: str,
    preview_return_code: int,
    expected_diagnostic: dict[str, object],
) -> None:
    script = _script()
    request = _request(script)
    runner = FakeRunner(
        script,
        preview_stdout=preview_stdout,
        preview_return_code=preview_return_code,
    )
    transport = FakeTransport(script)
    approvals: list[bool] = []

    result = script.accept_web_app_authentication(
        request,
        runner=runner,
        current_generation_reader=lambda: request.generation,
        approval_callback=lambda _summary: approvals.append(True) or True,
        artifact_digest_reader=lambda: ARTIFACT_DIGEST,
        transport_factory=lambda _base_url: transport,
        deployment_template=_prepared_template(script, tmp_path),
    )

    assert result.ok is False
    assert result.category == "unexpected_preview_changes"
    assert result.preview_verified is False
    assert result.deployment_attempted is False
    assert result.azure_mutation_made is False
    assert result.preview_diagnostic is not None
    diagnostic = result.preview_diagnostic.to_json_dict()
    assert set(diagnostic) == {
        "reason",
        "record_count",
        "create_count",
        "modify_count",
        "no_change_count",
        "delete_count",
        "ignore_count",
        "deploy_count",
        "unsupported_count",
        "authentication_resource_count",
        "unexpected_resource_count",
        "expected_web_app_relationship_proven",
        "exact_identity_scope_proven",
        "expected_multiplicity_proven",
        "malformed_or_unsupported_evidence_present",
        "authentication_action",
        "unexpected_change_counts",
    }
    assert {
        key: diagnostic[key] for key in expected_diagnostic
    } == expected_diagnostic
    assert approvals == []
    assert not any(
        command[:4] == ["az", "deployment", "group", "create"]
        for command in runner.commands
    )
    serialized = json.dumps(result.to_json_dict())
    assert expected_diagnostic["reason"] in serialized
    for forbidden in (
        CLIENT_ID,
        TENANT_ID,
        SUBSCRIPTION_ID,
        RESOURCE_GROUP,
        WEB_APP_NAME,
        BASE_URL,
        "raw stderr secret",
        "private-command-output",
        "other-web-app",
        "other-resource-group",
        "Microsoft.Network",
        "Microsoft.Storage",
        "private-network",
        "deployed-storage",
        "private-before",
        "private-after",
        "privatePreviewValue",
        "private-web-before",
        "private-web-after",
    ):
        assert forbidden not in serialized

@pytest.mark.parametrize("stale_evidence", ("generation", "hosting"))
def test_stale_approval_evidence_invalidates_mutation(
    tmp_path: Path,
    stale_evidence: str,
) -> None:
    script = _script()
    request = _request(script)
    runner = FakeRunner(
        script,
        hosting_drift_after_preview=stale_evidence == "hosting",
    )
    transport = FakeTransport(script)
    reads = iter(
        (request.generation, None)
        if stale_evidence == "generation"
        else (request.generation, request.generation)
    )

    result = script.accept_web_app_authentication(
        request,
        runner=runner,
        current_generation_reader=lambda: next(reads),
        approval_callback=lambda _summary: True,
        artifact_digest_reader=lambda: ARTIFACT_DIGEST,
        transport_factory=lambda _base_url: transport,
        deployment_template=_prepared_template(script, tmp_path),
    )

    assert result.ok is False
    assert result.category == "approval_evidence_stale"
    assert result.deployment_attempted is False
    assert result.azure_mutation_made is False


@pytest.mark.parametrize(
    ("payload", "expected_shape_diagnostic"),
    (
        (_enabled_auth_payload(exclusions=["/health", "/version"]), None),
        (
            _enabled_auth_payload(
                exclusions=["/health", "/version", "/demo/status", "/demo"]
            ),
            None,
        ),
        (
            _enabled_auth_payload(
                issuer="https://login.microsoftonline.com/other/v2.0"
            ),
            None,
        ),
        (
            "private malformed Azure JSON",
            {
                "field": "response",
                "reason": "unsupported_shape",
                "expected_type": "object",
            },
        ),
        (
            json.dumps(["private-list-value"]),
            {
                "field": "response",
                "reason": "wrong_object_type",
                "expected_type": "object",
            },
        ),
        (
            _mutated_enabled_auth_payload(field="clientId", remove=True),
            {
                "field": "client_id",
                "reason": "missing",
                "expected_type": "string",
            },
        ),
        (
            _mutated_enabled_auth_payload(extra=True),
            {
                "field": "response",
                "reason": "unsupported_shape",
                "expected_type": "object",
            },
        ),
        (
            _mutated_enabled_auth_payload(field="openIdIssuer", value=None),
            {
                "field": "open_id_issuer",
                "reason": "null_not_allowed",
                "expected_type": "string",
            },
        ),
        (
            _mutated_enabled_auth_payload(
                field="platformEnabled",
                value="private-boolean-value",
            ),
            {
                "field": "platform_enabled",
                "reason": "wrong_scalar_type",
                "expected_type": "boolean",
            },
        ),
        (
            _mutated_enabled_auth_payload(
                field="excludedPaths",
                value={"private": "object"},
            ),
            {
                "field": "excluded_paths",
                "reason": "wrong_list_type",
                "expected_type": "list",
            },
        ),
        (
            _mutated_enabled_auth_payload(
                field="excludedPaths",
                value=["/health", {"private": "path"}],
            ),
            {
                "field": "excluded_paths",
                "reason": "wrong_list_item_type",
                "expected_type": "list",
            },
        ),
    ),
)
def test_independent_configuration_proof_rejects_contract_drift(
    payload: str,
    expected_shape_diagnostic: dict[str, str] | None,
) -> None:
    script = _script()

    proof = script.parse_authentication_configuration_evidence(
        payload,
        expected_client_id=CLIENT_ID,
        expected_tenant_id=TENANT_ID,
        expected_login_endpoint="https://login.microsoftonline.com/",
    )
    diagnostic = script.diagnose_authentication_configuration_shape(payload)

    assert proof is None
    assert (
        diagnostic.to_json_dict() if diagnostic is not None else None
    ) == expected_shape_diagnostic
    result = script.AuthenticationAcceptanceResult.failure(
        "configuration_verification_failed",
        configuration_shape_diagnostic=diagnostic,
    )
    serialized = json.dumps(
        result.to_json_dict()
    )
    for forbidden in (
        CLIENT_ID,
        TENANT_ID,
        "other/v2.0",
        "/health",
        "private",
        "Azure JSON",
    ):
        assert forbidden not in serialized


def test_public_result_contract_contains_only_bounded_fields() -> None:
    script = _script()
    result = script.AuthenticationAcceptanceResult.failure(
        "configuration_verification_failed",
        azure_operation_attempted=True,
        deployment_attempted=True,
        deployment_accepted=True,
        azure_mutation_made=True,
    )

    assert set(result.to_json_dict()) == {
        "ok",
        "category",
        "operation",
        "mode",
        "current_generation_verified",
        "local_contract_validated",
        "current_web_app_verified",
        "current_configuration_evidence_verified",
        "preview_verified",
        "operator_approved",
        "authentication_enabled",
        "entra_provider_verified",
        "tenant_binding_verified",
        "application_binding_verified",
        "unauthenticated_action_verified",
        "anonymous_exclusions_verified",
        "deployment_attempted",
        "deployment_accepted",
        "configuration_verified",
        "anonymous_readiness_routes_verified",
        "protected_routes_verified",
        "hosted_readiness_verified",
        "authenticated_sign_in_verified",
        "azure_operation_attempted",
        "azure_mutation_made",
        "recommended_next_step",
    }
    for invalid in (
        {"field": "private", "reason": "missing", "expected_type": "string"},
        {
            "field": "client_id",
            "reason": "private",
            "expected_type": "string",
        },
        {
            "field": "client_id",
            "reason": "missing",
            "expected_type": "private",
        },
    ):
        with pytest.raises(ValueError):
            script.AuthenticationConfigurationShapeDiagnostic(**invalid)


def test_noncurrent_generation_fails_offline() -> None:
    script = _script()
    request = _request(script)
    request = script.replace(
        request,
        generation=script.replace(
            request.generation,
            current_day_verified=False,
        ),
    )

    result = script.check_authentication_acceptance_request(request)

    assert result.ok is False
    assert result.category == "invalid_configuration"
    assert result.azure_operation_attempted is False


def test_live_cli_rechecks_inputs_before_runner_construction(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = _script()
    invalid = script.replace(_request(script), tenant_id="not-a-guid")
    monkeypatch.setattr(
        script,
        "_load_private_request",
        lambda _args: (SimpleNamespace(), invalid),
    )
    monkeypatch.setattr(
        script,
        "_create_azure_cli_runner",
        lambda: pytest.fail("invalid identifiers must stop before runner construction"),
    )

    exit_code = script.main(
        [
            "--live",
            "--json",
            "--config",
            ".env.daily-azure.local",
            "--client-application-id",
            CLIENT_ID,
            "--tenant-id",
            TENANT_ID,
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert payload["category"] == "invalid_configuration"
    assert payload["azure_operation_attempted"] is False


def test_repair_live_uses_one_preview_one_terminal_deployment_and_one_auth_read(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = _script()
    request = _request(script)
    commands: list[list[str]] = []

    class RepairRunner:
        def run(self, args: list[str]):
            commands.append(args)
            result = script.CommandResult
            if args[:4] == ["az", "deployment", "group", "what-if"]:
                return result(
                    0,
                    _preview_payload(authentication_action="Modify"),
                    "",
                )
            if args[:4] == ["az", "deployment", "group", "create"]:
                return result(
                    0,
                    json.dumps(
                        {
                            "name": "nurse-dev-web-app-authentication",
                            "provisioningState": "Succeeded",
                        }
                    ),
                    "",
                )
            if args[:3] == ["az", "resource", "show"]:
                return result(0, _enabled_auth_payload(), "")
            raise AssertionError(args[:4])

    monkeypatch.setenv("OPERATOR_ENTRA_APPLICATION_ID", CLIENT_ID)
    monkeypatch.setenv("OPERATOR_ENTRA_TENANT_ID", TENANT_ID)
    monkeypatch.setattr(
        script,
        "_load_private_request",
        lambda _args: (SimpleNamespace(), request),
    )
    monkeypatch.setattr(
        script,
        "prepare_authentication_deployment_template",
        lambda _path: _prepared_template(script, ROOT),
    )
    monkeypatch.setattr(script, "_create_azure_cli_runner", RepairRunner)
    monkeypatch.setattr(
        script,
        "prompt_for_authentication_approval",
        lambda _summary: True,
    )

    exit_code = script.main(
        ["--repair-live", "--json", "--config", ".env.daily-azure.local"]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["category"] == "authentication_configuration_verified"
    assert payload["safe_preview"] is True
    assert payload["approval_presented"] is True
    assert payload["approval_granted"] is True
    assert payload["deployment_request_accepted"] is True
    assert payload["terminal_deployment_verified"] is True
    assert payload["authentication_reads"] == 1
    assert [command[:4] for command in commands] == [
        ["az", "deployment", "group", "what-if"],
        ["az", "deployment", "group", "create"],
        ["az", "resource", "show", "--resource-group"],
    ]


def test_repair_live_ambiguous_terminal_state_stops_before_auth_read(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = _script()
    request = _request(script)
    commands: list[list[str]] = []

    class AmbiguousRunner:
        def run(self, args: list[str]):
            commands.append(args)
            result = script.CommandResult
            if args[:4] == ["az", "deployment", "group", "what-if"]:
                return result(0, _preview_payload(), "")
            if args[:4] == ["az", "deployment", "group", "create"]:
                return result(0, json.dumps({"private": "state"}), "")
            raise AssertionError("terminal ambiguity must stop before auth read")

    monkeypatch.setenv("OPERATOR_ENTRA_APPLICATION_ID", CLIENT_ID)
    monkeypatch.setenv("OPERATOR_ENTRA_TENANT_ID", TENANT_ID)
    monkeypatch.setattr(
        script,
        "_load_private_request",
        lambda _args: (SimpleNamespace(), request),
    )
    monkeypatch.setattr(
        script,
        "prepare_authentication_deployment_template",
        lambda _path: _prepared_template(script, ROOT),
    )
    monkeypatch.setattr(script, "_create_azure_cli_runner", AmbiguousRunner)
    monkeypatch.setattr(
        script,
        "prompt_for_authentication_approval",
        lambda _summary: True,
    )

    exit_code = script.main(
        ["--repair-live", "--json", "--config", ".env.daily-azure.local"]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert payload["category"] == "deployment_failed_or_ambiguous"
    assert payload["deployment_request_accepted"] is True
    assert payload["terminal_deployment_verified"] is False
    assert payload["authentication_reads"] == 0
    assert len(commands) == 2


def test_approval_prompt_is_default_no_and_contains_no_identifiers() -> None:
    script = _script()
    from io import StringIO

    output = StringIO()
    approved = script.prompt_for_authentication_approval(
        script.AuthenticationApprovalSummary(True, True, True, True, 3, 0),
        input_stream=StringIO("\n"),
        output_stream=output,
    )

    rendered = output.getvalue()
    assert approved is False
    assert "APP SERVICE AUTHENTICATION V2" in rendered
    assert "Proceed? [y/N]" in rendered
    assert "Anonymous readiness exclusions: 3" in rendered
    assert "Unrelated resource changes: 0" in rendered
    assert CLIENT_ID not in rendered
    assert TENANT_ID not in rendered
