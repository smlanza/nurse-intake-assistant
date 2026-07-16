import json
from dataclasses import replace

import pytest

from src.app.services import foundry_agent_consumer_rbac_verification as verification


RESOURCE_GROUP = "fictional-resource-group"
WEB_APP_NAME = "fictional-nurse-intake-web-app"
FOUNDRY_ACCOUNT_NAME = "fictional-foundry-account"
FOUNDRY_PROJECT_NAME = "fictional-foundry-project"
PRINCIPAL_ID = "00000000-0000-0000-0000-000000000001"
SUBSCRIPTION_ID = "00000000-0000-0000-0000-000000000002"
PROJECT_SCOPE = (
    f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/{RESOURCE_GROUP}"
    f"/providers/Microsoft.CognitiveServices/accounts/{FOUNDRY_ACCOUNT_NAME}"
    f"/projects/{FOUNDRY_PROJECT_NAME}"
)
CONSUMER_ROLE_ID = (
    f"/subscriptions/{SUBSCRIPTION_ID}/providers/Microsoft.Authorization/roleDefinitions/"
    "eed3b665-ab3a-47b6-8f48-c9382fb1dad6"
)
OTHER_ROLE_ID = (
    f"/subscriptions/{SUBSCRIPTION_ID}/providers/Microsoft.Authorization/roleDefinitions/"
    "00000000-0000-0000-0000-000000000003"
)


class FakeRunner:
    def __init__(self, results: list[object]) -> None:
        self.results = list(results)
        self.calls: list[list[str]] = []

    def run(self, args: list[str]):
        assert isinstance(args, list)
        self.calls.append(args)
        result = self.results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


@pytest.fixture
def verification_request() -> verification.FoundryAgentConsumerRbacVerificationRequest:
    return verification.FoundryAgentConsumerRbacVerificationRequest(
        mode="live",
        resource_group=RESOURCE_GROUP,
        web_app_name=WEB_APP_NAME,
        foundry_account_name=FOUNDRY_ACCOUNT_NAME,
        foundry_project_name=FOUNDRY_PROJECT_NAME,
    )


def _result(return_code: int, stdout: str = "", stderr: str = ""):
    return verification.CommandResult(return_code, stdout, stderr)


def _identity(**overrides: object) -> str:
    payload = {"principalId": PRINCIPAL_ID, "type": "SystemAssigned"}
    payload.update(overrides)
    return json.dumps(payload)


def _project(**overrides: object) -> str:
    payload = {"id": PROJECT_SCOPE}
    payload.update(overrides)
    return json.dumps(payload)


def _assignment(
    *,
    principal_id: str = PRINCIPAL_ID,
    role_definition_id: str = CONSUMER_ROLE_ID,
    scope: str = PROJECT_SCOPE,
) -> dict[str, str]:
    return {
        "principalId": principal_id,
        "roleDefinitionId": role_definition_id,
        "scope": scope,
    }


def _runner(assignments: list[dict[str, str]] | None = None) -> FakeRunner:
    return FakeRunner(
        [
            _result(0, _identity()),
            _result(0, _project()),
            _result(0, json.dumps(assignments if assignments is not None else [_assignment()])),
        ]
    )


def _verify(
    request: verification.FoundryAgentConsumerRbacVerificationRequest,
    runner: FakeRunner,
):
    return verification.verify_foundry_agent_consumer_rbac(request, runner=runner)


def test_check_validates_local_contract_without_runner_or_azure_call(verification_request) -> None:
    runner = FakeRunner([AssertionError("check must remain offline")])

    result = _verify(replace(verification_request, mode="check"), runner)

    assert result.ok is True
    assert result.mode == "check"
    assert result.operation == "verify_foundry_agent_consumer_rbac"
    assert result.category == "success"
    assert result.local_contract_validated is True
    assert result.azure_request_attempted is False
    assert result.web_app_identity_present is False
    assert result.foundry_project_scope_resolved is False
    assert result.consumer_assignment_present is False
    assert runner.calls == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("resource_group", ""),
        ("resource_group", "unsafe/resource-group"),
        ("web_app_name", "--subscription"),
        ("foundry_account_name", " leading"),
        ("foundry_project_name", "unsafe project"),
        ("mode", "what-if"),
    ],
)
def test_invalid_request_fails_before_runner_call(verification_request, field: str, value: str) -> None:
    runner = FakeRunner([])

    result = _verify(replace(verification_request, **{field: value}), runner)

    assert result.category == "invalid_configuration"
    assert result.azure_request_attempted is False
    assert runner.calls == []


def test_fixed_consumer_role_contract_is_enforced(verification_request, monkeypatch) -> None:
    monkeypatch.setattr(
        verification.deployment,
        "CONSUMER_ROLE_GUID",
        "00000000-0000-0000-0000-000000000004",
    )
    runner = FakeRunner([])

    result = _verify(replace(verification_request, mode="check"), runner)

    assert result.category == "invalid_configuration"
    assert result.local_contract_validated is False
    assert runner.calls == []


@pytest.mark.parametrize(
    "identity",
    [
        {"principalId": None, "type": "SystemAssigned"},
        {"principalId": "", "type": "SystemAssigned"},
        {"principalId": PRINCIPAL_ID, "type": "UserAssigned"},
        {"principalId": PRINCIPAL_ID, "type": None},
    ],
)
def test_missing_system_identity_fails_safely(verification_request, identity: dict[str, object]) -> None:
    runner = FakeRunner([_result(0, json.dumps(identity))])

    result = _verify(verification_request, runner)

    assert result.category == "web_app_identity_missing"
    assert result.web_app_identity_present is False
    assert len(runner.calls) == 1


def test_missing_project_scope_fails_safely(verification_request) -> None:
    runner = FakeRunner(
        [_result(0, _identity()), _result(3, "secret stdout", "ResourceNotFound secret")]
    )

    result = _verify(verification_request, runner)

    assert result.category == "foundry_project_scope_not_found"
    assert result.web_app_identity_present is True
    assert result.foundry_project_scope_resolved is False
    assert len(runner.calls) == 2
    assert "secret" not in json.dumps(result.to_json_dict())


def test_no_matching_assignment_returns_assignment_missing(verification_request) -> None:
    result = _verify(verification_request, _runner([]))

    assert result.category == "assignment_missing"
    assert result.consumer_assignment_present is False


@pytest.mark.parametrize(
    "scope",
    [
        f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/{RESOURCE_GROUP}",
        (
            f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/{RESOURCE_GROUP}"
            f"/providers/Microsoft.CognitiveServices/accounts/{FOUNDRY_ACCOUNT_NAME}"
        ),
        f"/subscriptions/{SUBSCRIPTION_ID}",
    ],
)
def test_consumer_role_at_broader_scope_is_rejected(verification_request, scope: str) -> None:
    result = _verify(verification_request, _runner([_assignment(scope=scope)]))

    assert result.category == "assignment_scope_mismatch"
    assert result.consumer_assignment_present is True
    assert result.consumer_role_matches is True
    assert result.consumer_assignment_scope_matches is False


def test_different_role_at_project_scope_is_rejected(verification_request) -> None:
    result = _verify(
        verification_request,
        _runner([_assignment(role_definition_id=OTHER_ROLE_ID)]),
    )

    assert result.category == "role_mismatch"
    assert result.consumer_assignment_scope_matches is True
    assert result.consumer_role_matches is False


def test_assignment_for_different_principal_is_rejected(verification_request) -> None:
    result = _verify(
        verification_request,
        _runner([_assignment(principal_id="00000000-0000-0000-0000-000000000099")]),
    )

    assert result.category == "assignment_missing"
    assert result.consumer_assignment_present is False


def test_exact_project_scoped_consumer_assignment_succeeds(verification_request) -> None:
    runner = _runner()

    result = _verify(verification_request, runner)

    assert result.ok is True
    assert result.category == "success"
    assert result.mode == "live"
    assert result.local_contract_validated is True
    assert result.azure_request_attempted is True
    assert result.web_app_identity_present is True
    assert result.foundry_project_scope_resolved is True
    assert result.consumer_assignment_present is True
    assert result.consumer_assignment_scope_matches is True
    assert result.consumer_role_matches is True
    assert "hosted managed-identity Foundry Agent verification" in result.recommended_next_step


def test_duplicate_exact_assignments_fail_closed_deterministically(verification_request) -> None:
    result = _verify(verification_request, _runner([_assignment(), _assignment()]))

    assert result.ok is False
    assert result.category == "response_parse_failed"
    assert result.consumer_assignment_present is True


@pytest.mark.parametrize(
    "results",
    [
        [_result(0, "not-json secret")],
        [_result(0, _identity()), _result(0, "not-json secret")],
        [_result(0, _identity()), _result(0, _project()), _result(0, "not-json secret")],
        [_result(0, "[]")],
        [_result(0, _identity()), _result(0, "[]")],
        [_result(0, _identity()), _result(0, _project()), _result(0, "{}")],
    ],
)
def test_malformed_or_unknown_response_shapes_fail_closed(verification_request, results) -> None:
    runner = FakeRunner(results)

    result = _verify(verification_request, runner)

    assert result.category == "response_parse_failed"
    assert "secret" not in json.dumps(result.to_json_dict())


def test_unexpected_project_fields_fail_without_leaking(verification_request) -> None:
    sensitive = "tenant-secret endpoint.example token-secret"
    runner = FakeRunner(
        [
            _result(0, _identity()),
            _result(0, json.dumps({"id": PROJECT_SCOPE, "unexpected": sensitive})),
        ]
    )

    result = _verify(verification_request, runner)

    rendered = json.dumps(result.to_json_dict())
    assert result.category == "response_parse_failed"
    assert sensitive not in rendered


@pytest.mark.parametrize(
    ("return_code", "stderr", "category"),
    [
        (127, "secret executable path", "azure_cli_unavailable"),
        (1, "Please run az login with secret-token", "authentication_or_authorization_failed"),
        (1, "AuthorizationFailed tenant-secret", "authentication_or_authorization_failed"),
        (1, "ordinary Azure failure subscription-secret", "azure_request_failed"),
    ],
)
def test_command_failures_are_sanitized(verification_request, return_code, stderr, category) -> None:
    runner = FakeRunner([_result(return_code, "raw stdout principal-secret", stderr)])

    result = _verify(verification_request, runner)

    rendered = json.dumps(result.to_json_dict())
    assert result.category == category
    for forbidden in ("raw stdout", "principal-secret", stderr, "tenant-secret"):
        assert forbidden not in rendered


def test_raw_identifiers_and_assignment_fields_are_never_serialized(verification_request) -> None:
    assignment = {
        **_assignment(),
        "id": "assignment-secret",
        "tenantId": "tenant-secret",
        "clientId": "client-secret",
        "endpoint": "https://secret.example",
        "credential": "Bearer secret-token",
    }
    runner = _runner([assignment])

    result = _verify(verification_request, runner)

    rendered = json.dumps(result.to_json_dict())
    assert result.category == "response_parse_failed"
    for forbidden in (
        PRINCIPAL_ID,
        SUBSCRIPTION_ID,
        PROJECT_SCOPE,
        CONSUMER_ROLE_ID,
        "assignment-secret",
        "tenant-secret",
        "client-secret",
        "secret.example",
        "secret-token",
    ):
        assert forbidden not in rendered


def test_live_uses_only_three_bounded_read_only_projection_commands(verification_request) -> None:
    runner = _runner()

    result = _verify(verification_request, runner)

    assert result.ok is True
    assert runner.calls == [
        [
            "az", "webapp", "identity", "show",
            "--resource-group", RESOURCE_GROUP,
            "--name", WEB_APP_NAME,
            "--query", verification.WEB_APP_IDENTITY_QUERY,
            "--output", "json",
            "--only-show-errors",
        ],
        [
            "az", "resource", "show",
            "--resource-group", RESOURCE_GROUP,
            "--resource-type", "Microsoft.CognitiveServices/accounts/projects",
            "--name", f"{FOUNDRY_ACCOUNT_NAME}/{FOUNDRY_PROJECT_NAME}",
            "--api-version", "2025-06-01",
            "--query", verification.FOUNDRY_PROJECT_QUERY,
            "--output", "json",
            "--only-show-errors",
        ],
        [
            "az", "role", "assignment", "list",
            "--assignee-object-id", PRINCIPAL_ID,
            "--role", "eed3b665-ab3a-47b6-8f48-c9382fb1dad6",
            "--scope", PROJECT_SCOPE,
            "--include-inherited",
            "--query", verification.ROLE_ASSIGNMENT_QUERY,
            "--output", "json",
            "--only-show-errors",
        ],
    ]
    flattened = " ".join(" ".join(call).lower() for call in runner.calls)
    for forbidden in (
        " create ", " update ", " set ", " delete ", " assign ", " remove ",
        " token ", " restart ", " deployment ", " invoke ", " agent ",
    ):
        assert forbidden not in f" {flattened} "


def test_runner_exception_is_sanitized(verification_request) -> None:
    runner = FakeRunner([RuntimeError("Traceback tenant-secret principal-secret")])

    result = _verify(verification_request, runner)

    rendered = json.dumps(result.to_json_dict())
    assert result.category == "unexpected_error"
    assert "Traceback" not in rendered
    assert "secret" not in rendered
