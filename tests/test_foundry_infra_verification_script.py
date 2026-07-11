import json

import pytest

import scripts.verify_foundry_infra as script


ACCOUNT_NAME = "fictional-foundry"
PROJECT_NAME = "fictional-project"
DEPLOYMENT_NAME = "fictional-model-deployment"
ENDPOINT = (
    f"https://{ACCOUNT_NAME}.services.ai.azure.com/api/projects/{PROJECT_NAME}"
)


class FakeRunner:
    def __init__(self, results: list[script.CommandResult] | None = None) -> None:
        self.results = list(results or [])
        self.calls: list[list[str]] = []

    def run(self, args: list[str]) -> script.CommandResult:
        assert isinstance(args, list)
        self.calls.append(args)
        return self.results.pop(0)


def _account(**overrides: object) -> str:
    payload = {
        "name": ACCOUNT_NAME,
        "kind": "AIServices",
        "provisioningState": "Succeeded",
        "allowProjectManagement": True,
        "disableLocalAuth": True,
    }
    payload.update(overrides)
    return json.dumps(payload)


def _project(**overrides: object) -> str:
    payload = {"name": PROJECT_NAME, "provisioningState": "Succeeded"}
    payload.update(overrides)
    return json.dumps(payload)


def _deployment(**overrides: object) -> str:
    payload = {
        "name": DEPLOYMENT_NAME,
        "provisioningState": "Succeeded",
        "model": {"name": "fictional-model", "version": "fictional-version", "format": "OpenAI"},
        "sku": {"name": "GlobalStandard", "capacity": 1},
    }
    payload.update(overrides)
    return json.dumps(payload)


def _success_runner() -> FakeRunner:
    return FakeRunner(
        [
            script.CommandResult(0, _account(), ""),
            script.CommandResult(0, _project(), ""),
            script.CommandResult(0, _deployment(), ""),
        ]
    )


def _request(endpoint: str = ENDPOINT) -> script.VerificationRequest:
    return script.VerificationRequest("fictional-rg", endpoint, DEPLOYMENT_NAME)


def test_valid_project_endpoint_parses_account_and_project() -> None:
    assert script.parse_project_endpoint(ENDPOINT) == (ACCOUNT_NAME, PROJECT_NAME)


@pytest.mark.parametrize(
    "endpoint",
    [
        f"http://{ACCOUNT_NAME}.services.ai.azure.com/api/projects/{PROJECT_NAME}",
        f"https://services.ai.azure.com/api/projects/{PROJECT_NAME}",
        f"https://{ACCOUNT_NAME}.example.com/api/projects/{PROJECT_NAME}",
        f"https://{ACCOUNT_NAME}.services.ai.azure.com/api/projects/",
        f"https://{ACCOUNT_NAME}.services.ai.azure.com/api/projects/{PROJECT_NAME}/extra",
        f"https://{ACCOUNT_NAME}.services.ai.azure.com/api/projects/{PROJECT_NAME}?secret=value",
        f"https://{ACCOUNT_NAME}.services.ai.azure.com/api/projects/{PROJECT_NAME}#fragment",
        "not-a-url",
    ],
)
def test_invalid_endpoint_is_rejected_without_azure_calls(endpoint: str) -> None:
    runner = FakeRunner([])
    result = script.verify(_request(endpoint), runner)
    assert result["category"] == "invalid_project_endpoint"
    assert result["project_endpoint_valid"] is False
    assert runner.calls == []


def test_success_uses_exact_read_only_commands_in_order() -> None:
    runner = _success_runner()
    result = script.verify(_request(), runner)
    assert result["ok"] is True
    assert runner.calls == [
        [
            "az", "cognitiveservices", "account", "show",
            "--resource-group", "fictional-rg", "--name", ACCOUNT_NAME,
            "--query", "{name:name,kind:kind,provisioningState:properties.provisioningState,allowProjectManagement:properties.allowProjectManagement,disableLocalAuth:properties.disableLocalAuth}",
            "--output", "json", "--only-show-errors",
        ],
        [
            "az", "cognitiveservices", "account", "project", "show",
            "--resource-group", "fictional-rg", "--name", ACCOUNT_NAME,
            "--project-name", PROJECT_NAME,
            "--query", "{name:name,provisioningState:properties.provisioningState}",
            "--output", "json", "--only-show-errors",
        ],
        [
            "az", "cognitiveservices", "account", "deployment", "show",
            "--resource-group", "fictional-rg", "--name", ACCOUNT_NAME,
            "--deployment-name", DEPLOYMENT_NAME,
            "--query", "{name:name,provisioningState:properties.provisioningState,model:properties.model,sku:sku}",
            "--output", "json", "--only-show-errors",
        ],
    ]
    flattened = " ".join(" ".join(call).lower() for call in runner.calls)
    for forbidden in (" keys ", "listkeys", " create ", " update ", " delete ", "deployment group create"):
        assert forbidden not in f" {flattened} "


def test_success_returns_only_approved_contract() -> None:
    result = script.verify(_request(), _success_runner())
    assert set(result) == {
        "ok", "operation", "category", "account_verified", "project_verified",
        "model_deployment_verified", "project_endpoint_valid", "account_kind",
        "account_provisioning_state", "project_provisioning_state",
        "model_deployment_provisioning_state", "model_name", "model_version",
        "model_format", "model_sku", "recommended_next_step",
    }
    assert result == {
        "ok": True,
        "operation": "verify_foundry_infrastructure",
        "category": "success",
        "account_verified": True,
        "project_verified": True,
        "model_deployment_verified": True,
        "project_endpoint_valid": True,
        "account_kind": "AIServices",
        "account_provisioning_state": "Succeeded",
        "project_provisioning_state": "Succeeded",
        "model_deployment_provisioning_state": "Succeeded",
        "model_name": "fictional-model",
        "model_version": "fictional-version",
        "model_format": "OpenAI",
        "model_sku": "GlobalStandard",
        "recommended_next_step": "Infrastructure verification succeeded. Review the result before creating the prompt agent.",
    }


def test_qualified_project_resource_name_is_accepted() -> None:
    runner = FakeRunner(
        [
            script.CommandResult(0, _account(), ""),
            script.CommandResult(
                0,
                _project(name=f"{ACCOUNT_NAME}/{PROJECT_NAME}"),
                "",
            ),
            script.CommandResult(0, _deployment(), ""),
        ]
    )

    result = script.verify(_request(), runner)

    assert result["category"] == "success"
    assert result["ok"] is True
    assert result["project_verified"] is True
    assert result["model_deployment_verified"] is True


@pytest.mark.parametrize(
    ("overrides", "category"),
    [
        ({"kind": "OpenAI"}, "account_contract_invalid"),
        ({"allowProjectManagement": False}, "account_contract_invalid"),
        ({"disableLocalAuth": False}, "account_contract_invalid"),
        ({"name": "wrong-account"}, "account_contract_invalid"),
        ({"provisioningState": "Failed"}, "account_contract_invalid"),
    ],
)
def test_invalid_account_contract_stops_before_project(
    overrides: dict[str, object], category: str
) -> None:
    runner = FakeRunner([script.CommandResult(0, _account(**overrides), "")])
    result = script.verify(_request(), runner)
    assert result["category"] == category
    assert result["account_verified"] is False
    assert len(runner.calls) == 1


@pytest.mark.parametrize(
    ("payload", "expected_category"),
    [
        (_project(name="wrong-project"), "project_contract_invalid"),
        (
            _project(name=f"different-account/{PROJECT_NAME}"),
            "project_contract_invalid",
        ),
        (
            _project(name=f"{ACCOUNT_NAME}/wrong-project"),
            "project_contract_invalid",
        ),
        (_project(provisioningState="Failed"), "project_contract_invalid"),
    ],
)
def test_invalid_project_contract_stops_before_model(
    payload: str, expected_category: str
) -> None:
    runner = FakeRunner(
        [script.CommandResult(0, _account(), ""), script.CommandResult(0, payload, "")]
    )
    result = script.verify(_request(), runner)
    assert result["category"] == expected_category
    assert result["project_verified"] is False
    assert len(runner.calls) == 2


@pytest.mark.parametrize(
    "overrides",
    [{"name": "wrong-deployment"}, {"provisioningState": "Failed"}],
)
def test_invalid_model_deployment_contract_fails_safely(
    overrides: dict[str, object]
) -> None:
    runner = FakeRunner(
        [
            script.CommandResult(0, _account(), ""),
            script.CommandResult(0, _project(), ""),
            script.CommandResult(0, _deployment(**overrides), ""),
        ]
    )
    result = script.verify(_request(), runner)
    assert result["category"] == "model_deployment_contract_invalid"


@pytest.mark.parametrize(
    ("results", "category"),
    [
        ([script.CommandResult(1, "", "Please run az login SECRET")], "authentication_or_authorization_failed"),
        ([script.CommandResult(1, "", "ordinary SECRET")], "account_verification_failed"),
        ([script.CommandResult(0, "not-json", "SECRET")], "account_contract_invalid"),
        ([script.CommandResult(0, _account(), ""), script.CommandResult(1, "", "ordinary SECRET")], "project_verification_failed"),
        ([script.CommandResult(0, _account(), ""), script.CommandResult(0, _project(), ""), script.CommandResult(1, "", "ordinary SECRET")], "model_deployment_verification_failed"),
    ],
)
def test_cli_and_json_failures_are_sanitized(
    results: list[script.CommandResult], category: str
) -> None:
    result = script.verify(_request(), FakeRunner(results))
    rendered = json.dumps(result)
    assert result["category"] == category
    assert "SECRET" not in rendered
    assert "stderr" not in rendered.lower()
    assert "Traceback" not in rendered


def test_main_emits_exactly_one_failure_json_and_nonzero_exit(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        script,
        "verify",
        lambda request, runner=None: {
            "ok": False,
            "category": "account_verification_failed",
        },
    )
    exit_code = script.main(
        [
            "--resource-group", "fictional-rg",
            "--project-endpoint", ENDPOINT,
            "--model-deployment-name", DEPLOYMENT_NAME,
            "--json",
        ]
    )
    output = capsys.readouterr().out
    assert exit_code != 0
    assert output.count("\n") == 1
    assert json.loads(output)["category"] == "account_verification_failed"
