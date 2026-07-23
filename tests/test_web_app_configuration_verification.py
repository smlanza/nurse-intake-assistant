import importlib
import json
import re

import pytest


RESOURCE_GROUP = "fictional-rg"
WEB_APP_NAME = "fictional-web-app"
EXPECTED_HOSTED_VERIFIER_SETTINGS = {
    "AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT": (
        "https://fictional.services.ai.azure.com/api/projects/demo"
    ),
    "AZURE_AI_FOUNDRY_AGENT_ENDPOINT": (
        "https://fictional.services.ai.azure.com/api/projects/demo/agents/"
        "fictional-agent/endpoint/protocols/openai"
    ),
    "AZURE_AI_FOUNDRY_AGENT_NAME": "fictional-agent",
    "AZURE_AI_FOUNDRY_AGENT_VERSION": "7",
    "AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT_NAME": "fictional-model",
}


def _service():
    return importlib.import_module(
        "src.app.services.web_app_configuration_verification"
    )


def _site(**overrides: object) -> str:
    payload = {
        "state": "Running",
        "enabled": True,
        "kind": "app,linux",
        "reserved": True,
        "httpsOnly": True,
        "identityType": "SystemAssigned",
    }
    payload.update(overrides)
    return json.dumps(payload)


def _config(**overrides: object) -> str:
    payload = {
        "linuxFxVersion": "PYTHON|3.12",
        "appCommandLine": (
            "python -m uvicorn src.app.main:app --host 0.0.0.0 --port 8000"
        ),
        "ftpsState": "Disabled",
        "minTlsVersion": "1.2",
        "scmMinTlsVersion": "1.2",
        "healthCheckPath": "/health",
        "alwaysOn": True,
    }
    payload.update(overrides)
    return json.dumps(payload)


def _settings(**overrides: str | None) -> str:
    values: dict[str, str] = {
        "APP_MODE": "mock",
        "AI_PROVIDER": "mock",
        "AGENT_PROVIDER": "mock",
        "SPEECH_PROVIDER": "mock",
        "EMAIL_PROVIDER": "mock",
        "SMS_PROVIDER": "mock",
        "DEMO_SUPPRESS_NOTIFICATIONS": "true",
        "SCM_DO_BUILD_DURING_DEPLOYMENT": "true",
        "WEBSITE_SKIP_RUNNING_KUDUAGENT": "false",
        **EXPECTED_HOSTED_VERIFIER_SETTINGS,
    }
    for name, value in overrides.items():
        if value is None:
            values.pop(name, None)
        else:
            values[name] = value
    return json.dumps([{"name": name, "value": value} for name, value in values.items()])


class FakeRunner:
    def __init__(self, results: list[object]) -> None:
        self.results = list(results)
        self.calls: list[list[str]] = []

    def run(self, args: list[str]):
        self.calls.append(args)
        result = self.results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


def _result(return_code: int, stdout: str = "", stderr: str = ""):
    return _service().CommandResult(return_code, stdout, stderr)


def _success_runner() -> FakeRunner:
    return FakeRunner(
        [
            _result(0, _site()),
            _result(0, _config()),
            _result(0, _settings()),
        ]
    )


def _verify(runner: FakeRunner):
    return _service().verify_web_app_configuration(
        RESOURCE_GROUP,
        WEB_APP_NAME,
        EXPECTED_HOSTED_VERIFIER_SETTINGS,
        verify_hosted_foundry_verifier=True,
        runner=runner,
    )


def test_check_validates_local_contract_without_runner_or_azure_call() -> None:
    result = _service().check_web_app_configuration_contract()

    assert result.ok is True
    assert result.mode == "check"
    assert result.category == "success"
    assert result.local_contract_validated is True
    assert result.azure_request_attempted is False
    assert result.web_app_present is False
    assert result.managed_identity_present is False
    assert result.hosted_verifier_configuration_verified is False
    assert result.recommended_next_step == (
        "Run explicit --live --json Web App configuration verification after operator review."
    )


def test_success_uses_three_targeted_read_only_commands_and_sanitized_result() -> None:
    service = _service()
    runner = _success_runner()

    result = _verify(runner)

    assert result.ok is True
    assert result.category == "success"
    assert result.mode == "live"
    assert result.local_contract_validated is True
    assert result.azure_request_attempted is True
    assert result.web_app_present is True
    assert result.provisioning_state_verified is True
    assert result.linux_runtime_verified is True
    assert result.startup_command_verified is True
    assert result.remote_build_verified is True
    assert result.https_only_verified is True
    assert result.ftps_disabled_verified is True
    assert result.minimum_tls_verified is True
    assert result.health_check_verified is True
    assert result.managed_identity_present is True
    assert result.safe_provider_posture_verified is True
    assert result.hosted_verifier_configuration_verified is True
    assert result.recommended_next_step == (
        "Run the separate application code-deployment command."
    )
    assert runner.calls == [
        [
            "az",
            "webapp",
            "show",
            "--resource-group",
            RESOURCE_GROUP,
            "--name",
            WEB_APP_NAME,
            "--query",
            service.SITE_QUERY,
            "--output",
            "json",
            "--only-show-errors",
        ],
        [
            "az",
            "webapp",
            "config",
            "show",
            "--resource-group",
            RESOURCE_GROUP,
            "--name",
            WEB_APP_NAME,
            "--query",
            service.SITE_CONFIG_QUERY,
            "--output",
            "json",
            "--only-show-errors",
        ],
        [
            "az",
            "webapp",
            "config",
            "appsettings",
            "list",
            "--resource-group",
            RESOURCE_GROUP,
            "--name",
            WEB_APP_NAME,
            "--query",
            service.APP_SETTINGS_QUERY,
            "--output",
            "json",
            "--only-show-errors",
        ],
    ]
    flattened = " ".join(" ".join(call).lower() for call in runner.calls)
    for forbidden in (
        " create ",
        " update ",
        " set ",
        " delete ",
        " restart ",
        " deploy ",
        " list-publishing",
        " identity assign ",
        " role assignment ",
    ):
        assert forbidden not in f" {flattened} "
    serialized = json.dumps(result.to_json_dict())
    assert RESOURCE_GROUP not in serialized
    assert WEB_APP_NAME not in serialized


def test_baseline_live_verification_needs_no_hosted_values_and_uses_narrow_query() -> None:
    service = _service()
    runner = _success_runner()

    result = service.verify_web_app_configuration(
        RESOURCE_GROUP,
        WEB_APP_NAME,
        runner=runner,
    )

    assert result.ok is True
    assert result.safe_provider_posture_verified is True
    assert result.hosted_verifier_configuration_verified is False
    assert runner.calls[2][runner.calls[2].index("--query") + 1] == (
        service.BASE_APP_SETTINGS_QUERY
    )
    for name in EXPECTED_HOSTED_VERIFIER_SETTINGS:
        assert name not in service.BASE_APP_SETTINGS_QUERY


def test_running_enabled_cli_site_shape_proceeds_to_full_configuration_verification() -> None:
    runner = FakeRunner(
        [
            _result(
                0,
                json.dumps(
                    {
                        "state": "Running",
                        "enabled": True,
                        "httpsOnly": True,
                        "kind": "app,linux",
                        "reserved": True,
                        "identityType": "SystemAssigned",
                    }
                ),
            ),
            _result(0, _config()),
            _result(0, _settings()),
        ]
    )

    result = _verify(runner)

    assert result.ok is True
    assert result.category == "success"
    assert len(runner.calls) == 3


def test_missing_live_arguments_make_no_azure_call() -> None:
    service = _service()
    for resource_group, web_app_name in (("", WEB_APP_NAME), (RESOURCE_GROUP, "")):
        runner = FakeRunner([])
        result = service.verify_web_app_configuration(
            resource_group,
            web_app_name,
            EXPECTED_HOSTED_VERIFIER_SETTINGS,
            verify_hosted_foundry_verifier=True,
            runner=runner,
        )
        assert result.category == "missing_arguments"
        assert result.azure_request_attempted is False
        assert runner.calls == []


def test_first_read_command_failures_have_stable_sanitized_categories() -> None:
    cases = (
        (127, "", "secret", "azure_cli_unavailable"),
        (1, "", "Please run az login with secret-token", "authentication_or_authorization_failed"),
        (3, "", "ResourceNotFound subscription-id", "web_app_not_found"),
        (1, "sensitive stdout", "ordinary failure", "azure_request_failed"),
    )
    for return_code, stdout, stderr, category in cases:
        runner = FakeRunner([_result(return_code, stdout, stderr)])
        result = _verify(runner)
        rendered = json.dumps(result.to_json_dict())
        assert result.category == category
        assert len(runner.calls) == 1
        for forbidden in (stdout, stderr, "secret-token", "subscription-id"):
            if forbidden:
                assert forbidden not in rendered


def test_malformed_json_at_each_stage_stops_immediately() -> None:
    valid_results = [_result(0, _site()), _result(0, _config())]
    for stage in range(3):
        runner = FakeRunner(valid_results[:stage] + [_result(0, "not-json SECRET")])
        result = _verify(runner)
        assert result.category == "response_parse_failed"
        assert len(runner.calls) == stage + 1
        assert "SECRET" not in json.dumps(result.to_json_dict())


def test_site_contract_failures_are_distinct_and_stop_before_config_reads() -> None:
    cases = (
        ({"state": "Stopped"}, "provisioning_incomplete"),
        ({"state": "Stopping"}, "provisioning_incomplete"),
        ({"state": "Starting"}, "provisioning_incomplete"),
        ({"state": "Unknown"}, "provisioning_incomplete"),
        ({"state": ""}, "provisioning_incomplete"),
        ({"state": None}, "provisioning_incomplete"),
        ({"enabled": False}, "provisioning_incomplete"),
        ({"enabled": None}, "provisioning_incomplete"),
        ({"enabled": "true"}, "provisioning_incomplete"),
        ({"kind": "app"}, "runtime_contract_invalid"),
        ({"kind": "app,windows"}, "runtime_contract_invalid"),
        ({"reserved": False}, "runtime_contract_invalid"),
        ({"reserved": None}, "runtime_contract_invalid"),
        ({"httpsOnly": False}, "security_configuration_invalid"),
        ({"identityType": "None"}, "managed_identity_missing"),
        ({"identityType": None}, "managed_identity_missing"),
    )
    for overrides, category in cases:
        runner = FakeRunner([_result(0, _site(**overrides))])
        result = _verify(runner)
        assert result.category == category
        assert result.web_app_present is True
        assert len(runner.calls) == 1


@pytest.mark.parametrize("missing_field", ["state", "enabled"])
def test_missing_site_availability_field_fails_closed(missing_field: str) -> None:
    payload = json.loads(_site())
    payload.pop(missing_field)
    runner = FakeRunner([_result(0, json.dumps(payload))])

    result = _verify(runner)

    assert result.category == "provisioning_incomplete"
    assert result.web_app_present is True
    assert result.provisioning_state_verified is False
    assert len(runner.calls) == 1


def test_multiple_site_records_fail_as_ambiguous_response() -> None:
    site = json.loads(_site())
    runner = FakeRunner([_result(0, json.dumps([site, site]))])

    result = _verify(runner)

    assert result.category == "response_parse_failed"
    assert result.web_app_present is False
    assert len(runner.calls) == 1


def test_runtime_startup_and_security_config_failures_stop_before_settings() -> None:
    cases = (
        ({"linuxFxVersion": "NODE|22"}, "runtime_contract_invalid"),
        ({"linuxFxVersion": None}, "runtime_contract_invalid"),
        ({"appCommandLine": "python unsafe.py"}, "startup_command_invalid"),
        ({"appCommandLine": None}, "startup_command_invalid"),
        ({"ftpsState": "AllAllowed"}, "security_configuration_invalid"),
        ({"minTlsVersion": "1.1"}, "security_configuration_invalid"),
        ({"scmMinTlsVersion": "1.0"}, "security_configuration_invalid"),
        ({"healthCheckPath": "/status"}, "security_configuration_invalid"),
        ({"healthCheckPath": None}, "security_configuration_invalid"),
    )
    for overrides, category in cases:
        runner = FakeRunner([_result(0, _site()), _result(0, _config(**overrides))])
        result = _verify(runner)
        assert result.category == category
        assert len(runner.calls) == 2


@pytest.mark.parametrize("actual_value", (None, False, "true", 1))
def test_missing_or_non_boolean_always_on_blocks_linux_webjob_hosting_contract(
    actual_value: object,
) -> None:
    config = json.loads(_config())
    if actual_value is None:
        config.pop("alwaysOn")
    else:
        config["alwaysOn"] = actual_value
    runner = FakeRunner(
        [
            _result(0, _site()),
            _result(0, json.dumps(config)),
        ]
    )

    result = _verify(runner)

    assert result.ok is False
    assert result.category == "webjob_hosting_configuration_invalid"
    assert len(runner.calls) == 2


def test_duplicate_projected_kudu_agent_setting_fails_closed() -> None:
    settings = json.loads(_settings())
    settings.append(
        {"name": "WEBSITE_SKIP_RUNNING_KUDUAGENT", "value": "false"}
    )
    runner = FakeRunner(
        [
            _result(0, _site()),
            _result(0, _config()),
            _result(0, json.dumps(settings)),
        ]
    )

    result = _verify(runner)

    assert result.ok is False
    assert result.category == "response_parse_failed"
    assert len(runner.calls) == 3


@pytest.mark.parametrize(
    "actual_value",
    [None, "true", "False", " false "],
)
def test_kudu_agent_setting_must_be_exact_false(
    actual_value: str | None,
) -> None:
    runner = FakeRunner(
        [
            _result(0, _site()),
            _result(0, _config()),
            _result(
                0,
                _settings(
                    **{"WEBSITE_SKIP_RUNNING_KUDUAGENT": actual_value}
                ),
            ),
        ]
    )

    result = _verify(runner)

    assert result.ok is False
    assert result.category == "webjob_hosting_configuration_invalid"
    assert len(runner.calls) == 3


def test_remote_build_and_safe_provider_posture_failures_are_distinct() -> None:
    cases = (
        ({"SCM_DO_BUILD_DURING_DEPLOYMENT": None}, "remote_build_missing"),
        ({"SCM_DO_BUILD_DURING_DEPLOYMENT": "false"}, "remote_build_missing"),
        ({"AI_PROVIDER": "foundry"}, "safe_posture_invalid"),
        ({"APP_MODE": None}, "safe_posture_invalid"),
        ({"DEMO_SUPPRESS_NOTIFICATIONS": "false"}, "safe_posture_invalid"),
    )
    for overrides, category in cases:
        runner = FakeRunner(
            [
                _result(0, _site()),
                _result(0, _config()),
                _result(0, _settings(**overrides)),
            ]
        )
        result = _verify(runner)
        assert result.category == category
        assert result.safe_provider_posture_verified is False
        assert len(runner.calls) == 3


@pytest.mark.parametrize(
    ("setting_name", "actual_value"),
    [
        ("AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT", None),
        ("AZURE_AI_FOUNDRY_AGENT_ENDPOINT", "https://mismatch.example"),
        ("AZURE_AI_FOUNDRY_AGENT_NAME", "different-agent"),
        ("AZURE_AI_FOUNDRY_AGENT_VERSION", "8"),
        ("AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT_NAME", "different-model"),
    ],
)
def test_hosted_verifier_setting_missing_or_mismatch_fails_closed(
    setting_name: str,
    actual_value: str | None,
) -> None:
    runner = FakeRunner(
        [
            _result(0, _site()),
            _result(0, _config()),
            _result(0, _settings(**{setting_name: actual_value})),
        ]
    )

    result = _verify(runner)

    assert result.ok is False
    assert result.category == "hosted_verifier_configuration_invalid"
    assert result.safe_provider_posture_verified is True
    assert result.hosted_verifier_configuration_verified is False
    rendered = json.dumps(result.to_json_dict())
    assert actual_value not in rendered if actual_value else True


def test_duplicate_projected_setting_fails_as_ambiguous_response() -> None:
    payload = json.loads(_settings())
    payload.append(
        {
            "name": "AZURE_AI_FOUNDRY_AGENT_VERSION",
            "value": EXPECTED_HOSTED_VERIFIER_SETTINGS[
                "AZURE_AI_FOUNDRY_AGENT_VERSION"
            ],
        }
    )
    runner = FakeRunner(
        [
            _result(0, _site()),
            _result(0, _config()),
            _result(0, json.dumps(payload)),
        ]
    )

    result = _verify(runner)

    assert result.category == "response_parse_failed"
    assert result.hosted_verifier_configuration_verified is False


def test_raw_identifiers_settings_errors_and_exceptions_never_leak() -> None:
    service = _service()
    sensitive = (
        "subscription-0000 tenant-0000 client-0000 principal-0000 "
        "https://secret-host.example /subscriptions/secret raw-secret "
        "Bearer-token patient@example.com +15551234567 Traceback"
    )
    site_payload = json.loads(_site())
    site_payload.update(
        {
            "id": sensitive,
            "defaultHostName": sensitive,
            "principalId": sensitive,
            "connectionString": sensitive,
        }
    )
    success_runner = FakeRunner(
        [
            _result(0, json.dumps(site_payload)),
            _result(0, _config()),
            _result(0, _settings()),
        ]
    )
    results = [
        _verify(success_runner),
        service.verify_web_app_configuration(
            RESOURCE_GROUP,
            WEB_APP_NAME,
            EXPECTED_HOSTED_VERIFIER_SETTINGS,
            verify_hosted_foundry_verifier=True,
            runner=FakeRunner([RuntimeError(sensitive)]),
        ),
    ]
    for result in results:
        rendered = json.dumps(result.to_json_dict())
        for forbidden in (
            "subscription-0000",
            "tenant-0000",
            "client-0000",
            "principal-0000",
            "secret-host",
            "/subscriptions/",
            "raw-secret",
            "Bearer-token",
            "patient@example.com",
            "+15551234567",
            "Traceback",
        ):
            assert forbidden not in rendered


def test_local_contract_rejects_exact_mapping_and_scalar_mutations_before_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()
    expected_settings = dict(service.SAFE_APP_SETTINGS)
    mutations = (
        (
            "SAFE_APP_SETTINGS",
            {**expected_settings, "APP_MODE": "true"},
        ),
        (
            "SAFE_APP_SETTINGS",
            {**expected_settings, "DEMO_SUPPRESS_NOTIFICATIONS": "mock"},
        ),
        (
            "SAFE_APP_SETTINGS",
            {
                name: value
                for name, value in expected_settings.items()
                if name != "SMS_PROVIDER"
            },
        ),
        (
            "SAFE_APP_SETTINGS",
            {**expected_settings, "UNEXPECTED_PROVIDER": "mock"},
        ),
        ("EXPECTED_LINUX_FX_VERSION", "PYTHON|3.11"),
        ("EXPECTED_STARTUP_COMMAND", "python unexpected.py"),
        ("EXPECTED_HEALTH_CHECK_PATH", "/unexpected"),
        ("REMOTE_BUILD_SETTING", "UNEXPECTED_REMOTE_BUILD_SETTING"),
    )

    for attribute, invalid_value in mutations:
        original_value = getattr(service, attribute)
        with monkeypatch.context() as patch:
            patch.setattr(service, attribute, invalid_value)
            check_result = service.check_web_app_configuration_contract()
            runner = FakeRunner([])
            live_result = service.verify_web_app_configuration(
                RESOURCE_GROUP,
                WEB_APP_NAME,
                EXPECTED_HOSTED_VERIFIER_SETTINGS,
                verify_hosted_foundry_verifier=True,
                runner=runner,
            )

            assert check_result.ok is False
            assert check_result.category == "unexpected_error"
            assert check_result.local_contract_validated is False
            assert live_result.ok is False
            assert live_result.category == "unexpected_error"
            assert live_result.local_contract_validated is False
            assert live_result.azure_request_attempted is False
            assert live_result.web_app_present is False
            assert live_result.provisioning_state_verified is False
            assert live_result.linux_runtime_verified is False
            assert live_result.startup_command_verified is False
            assert live_result.remote_build_verified is False
            assert live_result.https_only_verified is False
            assert live_result.ftps_disabled_verified is False
            assert live_result.minimum_tls_verified is False
            assert live_result.health_check_verified is False
            assert live_result.managed_identity_present is False
            assert live_result.safe_provider_posture_verified is False
            assert live_result.hosted_verifier_configuration_verified is False
            assert "local contract" in live_result.recommended_next_step.lower()
            assert runner.calls == []
        assert getattr(service, attribute) == original_value


def _projection_fields(query: str) -> dict[str, str]:
    return {
        alias: expression
        for alias, expression in re.findall(
            r"([A-Za-z][A-Za-z0-9]*):([^,}]+)",
            query,
        )
    }


def test_site_query_selects_only_required_nonidentifying_fields() -> None:
    query = _service().SITE_QUERY

    assert _projection_fields(query) == {
        "state": "state",
        "enabled": "enabled",
        "kind": "kind",
        "reserved": "reserved",
        "httpsOnly": "httpsOnly",
        "identityType": "identity.type",
    }
    lowered = query.lower()
    for forbidden in (
        "subscription",
        "tenant",
        "hostname",
        "defaulthostname",
        "principalid",
        "clientid",
        "identity:identity",
        "connectionstring",
        "tags",
        "publishing",
    ):
        assert forbidden not in lowered


def test_site_config_query_selects_only_required_runtime_and_security_fields() -> None:
    query = _service().SITE_CONFIG_QUERY

    assert _projection_fields(query) == {
        "linuxFxVersion": "linuxFxVersion",
        "appCommandLine": "appCommandLine",
        "ftpsState": "ftpsState",
        "minTlsVersion": "minTlsVersion",
        "scmMinTlsVersion": "scmMinTlsVersion",
        "healthCheckPath": "healthCheckPath",
        "alwaysOn": "alwaysOn",
    }
    assert query.startswith("{")
    assert query.endswith("}")


def test_app_settings_query_filters_to_exact_bicep_owned_allowlist() -> None:
    query = _service().APP_SETTINGS_QUERY
    expected_names = {
        "APP_MODE",
        "AI_PROVIDER",
        "AGENT_PROVIDER",
        "SPEECH_PROVIDER",
        "EMAIL_PROVIDER",
        "SMS_PROVIDER",
        "DEMO_SUPPRESS_NOTIFICATIONS",
        "SCM_DO_BUILD_DURING_DEPLOYMENT",
        "WEBSITE_SKIP_RUNNING_KUDUAGENT",
        *EXPECTED_HOSTED_VERIFIER_SETTINGS,
    }

    requested_names = re.findall(r"name=='([^']+)'", query)
    assert set(requested_names) == expected_names
    assert len(requested_names) == len(expected_names)
    assert query.startswith("[?")
    assert "].{" in query
    lowered = query.lower()
    for forbidden in (
        "connection",
        "email_address",
        "phone",
        "secret",
        "key",
        "token",
        "credential",
    ):
        assert forbidden not in lowered
