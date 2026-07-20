import json
from dataclasses import replace
from pathlib import Path

import pytest

from src.app.services import foundry_agent_consumer_rbac_deployment as deployment


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "infra/foundry-agent-consumer-rbac.bicep"


class FakeRunner:
    def __init__(
        self,
        result: deployment.CommandResult | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.result = result or deployment.CommandResult(0, '{"changes":[]}', "")
        self.error = error
        self.calls: list[list[str]] = []

    def run(self, args: list[str]) -> deployment.CommandResult:
        assert isinstance(args, list)
        self.calls.append(args)
        if self.error is not None:
            raise self.error
        return self.result


@pytest.fixture
def rbac_request() -> deployment.FoundryAgentConsumerRbacDeploymentRequest:
    return deployment.FoundryAgentConsumerRbacDeploymentRequest(
        mode="check",
        resource_group="fictional-resource-group",
        web_app_name="fictional-nurse-intake-web-app",
        foundry_account_name="fictional-foundry-account",
        foundry_project_name="fictional-foundry-project",
        template_file=TEMPLATE,
    )


def test_check_validates_contract_without_runner_or_azure_operation(rbac_request) -> None:
    runner = FakeRunner(error=AssertionError("check must not invoke the runner"))

    result = deployment.deploy_foundry_agent_consumer_rbac(rbac_request, runner=runner)

    assert result.ok is True
    assert result.operation == "deploy_foundry_agent_consumer_rbac"
    assert result.mode == "check"
    assert result.category == "success"
    assert result.template_valid is True
    assert result.azure_operation_attempted is False
    assert result.deployment_request_accepted is False
    assert "no Azure operation" in result.message
    assert "--what-if" in result.recommended_next_step
    assert runner.calls == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("resource_group", ""),
        ("resource_group", "unsafe\nresource-group"),
        ("web_app_name", "--subscription"),
        ("web_app_name", "unsafe/name"),
        ("foundry_account_name", " leading-space"),
        ("foundry_project_name", "unsafe project"),
    ],
)
def test_missing_or_unsafe_names_fail_before_runner_call(
    rbac_request, field: str, value: str
) -> None:
    runner = FakeRunner()

    result = deployment.deploy_foundry_agent_consumer_rbac(
        replace(rbac_request, mode="live", **{field: value}), runner=runner
    )

    assert result.ok is False
    assert result.category == "invalid_request"
    assert result.template_valid is False
    assert result.azure_operation_attempted is False
    assert runner.calls == []


def test_invalid_mode_fails_before_runner_call(rbac_request) -> None:
    runner = FakeRunner()

    result = deployment.deploy_foundry_agent_consumer_rbac(
        replace(rbac_request, mode="check+live"), runner=runner
    )

    assert result.category == "invalid_request"
    assert result.mode == "invalid"
    assert result.azure_operation_attempted is False
    assert runner.calls == []


@pytest.mark.parametrize(
    "template_file",
    [
        ROOT / "infra/main.bicep",
        ROOT / "infra/modules/foundry-agent-consumer-rbac.bicep",
        ROOT / "infra/missing-rbac-template.bicep",
    ],
)
def test_only_exact_existing_rbac_entry_point_is_accepted(
    rbac_request, template_file: Path
) -> None:
    runner = FakeRunner()

    result = deployment.deploy_foundry_agent_consumer_rbac(
        replace(rbac_request, mode="what-if", template_file=template_file), runner=runner
    )

    assert result.category == "template_contract_invalid"
    assert result.template_valid is False
    assert result.azure_operation_attempted is False
    assert runner.calls == []


def test_what_if_runs_exactly_one_safe_resource_group_preview(rbac_request) -> None:
    runner = FakeRunner()

    result = deployment.deploy_foundry_agent_consumer_rbac(
        replace(rbac_request, mode="what-if"), runner=runner
    )

    assert result.ok is True
    assert result.azure_operation_attempted is True
    assert result.deployment_request_accepted is False
    assert runner.calls == [
        [
            "az",
            "deployment",
            "group",
            "what-if",
            "--resource-group",
            "fictional-resource-group",
            "--template-file",
            str(TEMPLATE),
            "--parameters",
            "webAppName=fictional-nurse-intake-web-app",
            "foundryAccountName=fictional-foundry-account",
            "foundryProjectName=fictional-foundry-project",
            "--no-pretty-print",
            "--output",
            "json",
        ]
    ]


def test_live_runs_exactly_one_safe_resource_group_deployment(rbac_request) -> None:
    runner = FakeRunner(deployment.CommandResult(0, "sensitive stdout", ""))

    result = deployment.deploy_foundry_agent_consumer_rbac(
        replace(rbac_request, mode="live"), runner=runner
    )

    assert result.ok is True
    assert result.azure_operation_attempted is True
    assert result.deployment_request_accepted is True
    assert runner.calls == [
        [
            "az",
            "deployment",
            "group",
            "create",
            "--resource-group",
            "fictional-resource-group",
            "--name",
            "foundry-agent-consumer-rbac",
            "--template-file",
            str(TEMPLATE),
            "--parameters",
            "webAppName=fictional-nurse-intake-web-app",
            "foundryAccountName=fictional-foundry-account",
            "foundryProjectName=fictional-foundry-project",
            "--output",
            "none",
        ]
    ]
    assert "accepted" in result.message.lower()
    assert "authorization works" not in result.message.lower()
    assert "separate verification" in result.message.lower()
    assert "verification" in result.recommended_next_step.lower()


@pytest.mark.parametrize("mode", ["what-if", "live"])
def test_azure_commands_never_create_or_delete_groups_or_invoke_foundry(
    rbac_request, mode: str
) -> None:
    runner = FakeRunner()

    deployment.deploy_foundry_agent_consumer_rbac(
        replace(rbac_request, mode=mode), runner=runner
    )

    command = runner.calls[0]
    flattened = " ".join(command).lower()
    assert command[:3] != ["az", "group", "create"]
    assert command[:3] != ["az", "group", "delete"]
    assert "role-definition" not in flattened
    assert "invoke" not in flattened
    assert "agent" not in flattened.replace("foundry-agent-consumer-rbac", "")


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ([], (0, 0, 0, 0)),
        ([{"changeType": "Create"}], (1, 0, 0, 0)),
        ([{"changeType": "Modify"}], (0, 1, 0, 0)),
        ([{"changeType": "NoChange"}], (0, 0, 1, 0)),
        ([{"changeType": "Delete"}], (0, 0, 0, 1)),
        (
            [
                {"changeType": "Create"},
                {"changeType": "Modify"},
                {"changeType": "NoChange"},
                {"changeType": "Delete"},
                {"changeType": "Modify"},
            ],
            (1, 2, 1, 1),
        ),
    ],
)
def test_valid_what_if_output_returns_aggregate_counts_only(
    rbac_request, changes: list[dict[str, str]], expected: tuple[int, int, int, int]
) -> None:
    raw = json.dumps(
        {
            "changes": [
                {
                    **change,
                    "resourceId": "/subscriptions/secret/resourceGroups/secret/providers/secret",
                    "principalId": "secret-principal-id",
                }
                for change in changes
            ],
            "tenantId": "secret-tenant-id",
        }
    )
    result = deployment.deploy_foundry_agent_consumer_rbac(
        replace(rbac_request, mode="what-if"),
        runner=FakeRunner(deployment.CommandResult(0, raw, "secret stderr")),
    )

    assert result.ok is True
    assert (
        result.create_count,
        result.modify_count,
        result.no_change_count,
        result.delete_count,
    ) == expected
    assert result.delete_review_required is (expected[3] > 0)
    assert result.manual_review_required is bool(changes)
    serialized = json.dumps(result.to_json_dict())
    for secret in (
        "secret-principal-id",
        "secret-tenant-id",
        "/subscriptions/secret",
        "secret stderr",
    ):
        assert secret not in serialized


@pytest.mark.parametrize(
    ("change_type", "count_field", "manual_review_required"),
    [
        ("Ignore", "ignore_count", False),
        ("Deploy", "deploy_count", True),
        ("Unsupported", "unsupported_count", True),
    ],
)
def test_all_additional_documented_azure_change_types_parse_successfully(
    rbac_request,
    change_type: str,
    count_field: str,
    manual_review_required: bool,
) -> None:
    raw = json.dumps(
        {
            "changes": [
                {
                    "changeType": change_type,
                    "resourceId": (
                        "/subscriptions/raw/resourceGroups/raw/providers/"
                        "Microsoft.CognitiveServices/accounts/account/projects/project/"
                        "providers/Microsoft.Authorization/roleAssignments/assignment"
                    ),
                    "principalId": "raw-principal",
                }
            ],
            "tenantId": "raw-tenant",
        }
    )

    result = deployment.deploy_foundry_agent_consumer_rbac(
        replace(rbac_request, mode="what-if"),
        runner=FakeRunner(deployment.CommandResult(0, raw, "raw stderr")),
    )

    assert result.ok is True
    assert result.category == "success"
    assert getattr(result, count_field) == 1
    assert result.delete_review_required is False
    assert result.manual_review_required is manual_review_required
    serialized = json.dumps(result.to_json_dict())
    for raw_value in ("/subscriptions/raw", "raw-principal", "raw-tenant", "raw stderr"):
        assert raw_value not in serialized


def test_mixed_preview_counts_all_seven_documented_azure_change_types(
    rbac_request,
) -> None:
    changes = [
        {"changeType": change_type, "resourceId": f"/raw/{change_type}"}
        for change_type in (
            "Create",
            "Delete",
            "Ignore",
            "Deploy",
            "NoChange",
            "Modify",
            "Unsupported",
        )
    ]

    result = deployment.deploy_foundry_agent_consumer_rbac(
        replace(rbac_request, mode="what-if"),
        runner=FakeRunner(
            deployment.CommandResult(0, json.dumps({"changes": changes}), "raw stderr")
        ),
    )

    assert result.ok is True
    assert (
        result.create_count,
        result.delete_count,
        result.ignore_count,
        result.deploy_count,
        result.no_change_count,
        result.modify_count,
        result.unsupported_count,
    ) == (1, 1, 1, 1, 1, 1, 1)
    assert result.delete_review_required is True
    assert result.manual_review_required is True
    assert "manual review" in result.recommended_next_step.lower()
    serialized = json.dumps(result.to_json_dict())
    assert "/raw/" not in serialized
    assert "raw stderr" not in serialized


@pytest.mark.parametrize(
    "stdout",
    [
        "not-json",
        "{}",
        '{"changes":null}',
        '{"changes":{}}',
        '{"changes":[null]}',
        '{"changes":[{}]}',
        '{"changes":[{"changeType":"UnexpectedFutureType"}]}',
    ],
)
def test_malformed_missing_or_unexpected_what_if_changes_fail_closed(
    rbac_request, stdout: str
) -> None:
    result = deployment.deploy_foundry_agent_consumer_rbac(
        replace(rbac_request, mode="what-if"),
        runner=FakeRunner(deployment.CommandResult(0, stdout, "secret stderr")),
    )

    assert result.ok is False
    assert result.category == "what_if_parse_failed"
    assert result.azure_operation_attempted is True
    assert result.deployment_request_accepted is False
    assert result.create_count is None
    assert result.delete_count is None
    assert "secret" not in json.dumps(result.to_json_dict())


@pytest.mark.parametrize(
    ("mode", "return_code", "category"),
    [
        ("what-if", 1, "what_if_failed"),
        ("live", 1, "deployment_failed"),
        ("what-if", 127, "azure_cli_unavailable"),
        ("live", 127, "azure_cli_unavailable"),
    ],
)
def test_azure_failures_are_mode_specific_and_sanitized(
    rbac_request, mode: str, return_code: int, category: str
) -> None:
    result = deployment.deploy_foundry_agent_consumer_rbac(
        replace(rbac_request, mode=mode),
        runner=FakeRunner(
            deployment.CommandResult(
                return_code,
                "raw subscription and principal ID",
                "credential token traceback",
            )
        ),
    )

    assert result.ok is False
    assert result.category == category
    assert result.azure_operation_attempted is True
    assert result.deployment_request_accepted is False
    serialized = json.dumps(result.to_json_dict())
    assert "subscription" not in serialized
    assert "principal" not in serialized
    assert "credential" not in serialized
    assert "traceback" not in serialized


@pytest.mark.parametrize("mode", ["what-if", "live"])
def test_missing_runner_and_runner_exceptions_are_sanitized(
    rbac_request, mode: str
) -> None:
    missing_runner = deployment.deploy_foundry_agent_consumer_rbac(
        replace(rbac_request, mode=mode)
    )
    raised = deployment.deploy_foundry_agent_consumer_rbac(
        replace(rbac_request, mode=mode),
        runner=FakeRunner(error=RuntimeError("token principal traceback")),
    )

    assert missing_runner.category == "unexpected_error"
    assert missing_runner.azure_operation_attempted is False
    assert raised.category == "unexpected_error"
    assert raised.azure_operation_attempted is True
    assert "token" not in json.dumps(raised.to_json_dict())
    assert "principal" not in json.dumps(raised.to_json_dict())


def test_result_contract_exposes_only_sanitized_boundary_fields(rbac_request) -> None:
    result = deployment.deploy_foundry_agent_consumer_rbac(rbac_request)

    assert set(result.to_json_dict()) == {
        "ok",
        "operation",
        "mode",
        "category",
        "message",
        "template_valid",
        "azure_operation_attempted",
        "deployment_request_accepted",
        "create_count",
        "modify_count",
        "no_change_count",
        "delete_count",
        "ignore_count",
        "deploy_count",
        "unsupported_count",
        "delete_review_required",
        "manual_review_required",
            "recommended_next_step",
            "change_evidence",
        }
