import json
import hashlib
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
    subscription_id = "00000000-0000-0000-0000-000000000001"
    project_id = (
        f"/subscriptions/{subscription_id}/resourceGroups/fictional-resource-group/"
        "providers/Microsoft.CognitiveServices/accounts/fictional-foundry-account/"
        "projects/fictional-foundry-project"
    )
    principal_id = "00000000-0000-0000-0000-000000000002"
    role_id = (
        f"/subscriptions/{subscription_id}/providers/"
        "Microsoft.Authorization/roleDefinitions/"
        "eed3b665-ab3a-47b6-8f48-c9382fb1dad6"
    )
    return deployment.FoundryAgentConsumerRbacDeploymentRequest(
        mode="check",
        resource_group="fictional-resource-group",
        web_app_name="fictional-nurse-intake-web-app",
        foundry_account_name="fictional-foundry-account",
        foundry_project_name="fictional-foundry-project",
        template_file=TEMPLATE,
        approved_evidence=deployment.FoundryAgentConsumerRbacDeploymentEvidence(
            subscription_id=subscription_id,
            foundry_project_resource_id=project_id,
            web_app_principal_id=principal_id,
            role_definition_id=role_id,
            role_assignment_name=deployment.deterministic_role_assignment_name(
                project_id, principal_id, role_id
            ),
            deployment_name=deployment.DEPLOYMENT_NAME,
        ),
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
    runner = FakeRunner(
        deployment.CommandResult(
            0,
            json.dumps({"changes": [_exact_change(rbac_request)]}),
            "",
        )
    )

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
            "--name",
            "foundry-agent-consumer-rbac",
            "--template-file",
            str(TEMPLATE),
            "--parameters",
            "webAppName=fictional-nurse-intake-web-app",
            "foundryAccountName=fictional-foundry-account",
            "foundryProjectName=fictional-foundry-project",
            "approvedWebAppPrincipalId=00000000-0000-0000-0000-000000000002",
            "approvedFoundryProjectResourceId=/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/fictional-resource-group/providers/Microsoft.CognitiveServices/accounts/fictional-foundry-account/projects/fictional-foundry-project",
            "approvedRoleAssignmentName=16f4c29e-cc74-5373-8223-e478a3a63851",
            "--no-pretty-print",
            "--output",
            "json",
        ]
    ]


def _exact_change(request, *, include_properties: bool = True) -> dict[str, object]:
    evidence = request.approved_evidence
    assert evidence is not None
    change: dict[str, object] = {
        "changeType": "Create",
        "resourceType": "Microsoft.Authorization/roleAssignments",
        "resourceId": (
            f"{evidence.foundry_project_resource_id}/providers/"
            "Microsoft.Authorization/roleAssignments/"
            f"{evidence.role_assignment_name}"
        ),
    }
    if include_properties:
        change["after"] = {
            "properties": {
                "principalId": evidence.web_app_principal_id,
                "roleDefinitionId": evidence.role_definition_id,
            }
        }
    return change


def _known_ignore_changes(request) -> list[dict[str, object]]:
    evidence = request.approved_evidence
    assert evidence is not None
    identity = "\x00".join(
        (
            request.resource_group.casefold(),
            "nurse-intake",
            "daily",
        )
    ).encode()
    suffix = hashlib.sha256(identity).hexdigest()[:13]
    project_environment = "nurse-intake-daily"
    cosmos_name = f"{project_environment}-{suffix}"
    plan_name = f"{project_environment}-plan-{suffix}"[:40]
    root = (
        f"/subscriptions/{evidence.subscription_id}/resourceGroups/"
        f"{request.resource_group}/providers"
    )
    cosmos = f"{root}/Microsoft.DocumentDB/databaseAccounts/{cosmos_name}"
    resources = (
        (
            "Microsoft.DocumentDB/databaseAccounts",
            cosmos,
        ),
        (
            "Microsoft.DocumentDB/databaseAccounts/sqlDatabases",
            f"{cosmos}/sqlDatabases/nurse-intake",
        ),
        (
            "Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers",
            f"{cosmos}/sqlDatabases/nurse-intake/containers/cases",
        ),
        (
            "Microsoft.Storage/storageAccounts",
            f"{root}/Microsoft.Storage/storageAccounts/st{suffix}",
        ),
        (
            "Microsoft.OperationalInsights/workspaces",
            (
                f"{root}/Microsoft.OperationalInsights/workspaces/"
                f"{project_environment}-logs-{suffix}"
            ),
        ),
        (
            "Microsoft.Insights/components",
            (
                f"{root}/Microsoft.Insights/components/"
                f"{project_environment}-appi-{suffix}"
            ),
        ),
        (
            "Microsoft.Web/serverfarms",
            f"{root}/Microsoft.Web/serverfarms/{plan_name}",
        ),
        (
            "Microsoft.Web/sites",
            f"{root}/Microsoft.Web/sites/{request.web_app_name}",
        ),
        (
            "Microsoft.CognitiveServices/accounts",
            (
                f"{root}/Microsoft.CognitiveServices/accounts/"
                f"{request.foundry_account_name}"
            ),
        ),
        (
            "Microsoft.CognitiveServices/accounts/projects",
            evidence.foundry_project_resource_id,
        ),
    )
    return [
        {
            "changeType": "Ignore",
            "resourceType": resource_type,
            "resourceId": resource_id,
        }
        for resource_type, resource_id in resources
    ]


def _unsupported_change(request) -> dict[str, object]:
    change = _exact_change(request)
    change["changeType"] = "Unsupported"
    return change


def _live_shape_changes(request) -> list[dict[str, object]]:
    changes = _known_ignore_changes(request)
    assignment = _exact_change(request)
    assignment["changeType"] = "Unsupported"
    changes.append(assignment)
    return changes


def _bounded_action_only_changes(request) -> list[dict[str, object]]:
    evidence = request.approved_evidence
    assert evidence is not None
    return [
        *({"changeType": "Ignore"} for _ in range(10)),
        {
            "changeType": "Unsupported",
            "after": {
                "properties": {
                    "principalId": evidence.web_app_principal_id,
                    "roleDefinitionId": evidence.role_definition_id,
                }
            },
        },
    ]


def _preview_result(request, changes: list[object]):
    return deployment.deploy_foundry_agent_consumer_rbac(
        replace(request, mode="what-if"),
        runner=FakeRunner(
            deployment.CommandResult(0, json.dumps({"changes": changes}), "")
        ),
    )


def test_known_ignore_plus_unsupported_topology_requires_manual_review(
    rbac_request,
) -> None:
    result = _preview_result(
        rbac_request,
        [*_known_ignore_changes(rbac_request), _unsupported_change(rbac_request)],
    )

    assert result.ok is True
    assert result.category == "success"
    assert result.preview_topology == "expected_ignore_plus_unsupported"
    assert result.assignment_contents_proved is True
    assert result.ignore_count == 10
    assert result.unsupported_count == 1
    assert result.manual_review_required is True
    assert result.delete_review_required is False
    assert result.what_if_diagnostic is None
    assignment = result.change_evidence[-1]
    assert assignment.action == "Unsupported"
    assert assignment.logical_category == "consumer_role_assignment"
    assert assignment.resource_type == "role_assignment"
    assert assignment.approved_boundary is False
    assert assignment.expected_identity_match is True
    assert assignment.expected_parent_match is True
    assert assignment.expected_scope_match is True
    assert assignment.expected_multiplicity_match is True


def test_live_shape_without_resource_types_is_not_independent_topology_proof(
    rbac_request,
) -> None:
    changes = _live_shape_changes(rbac_request)
    for change in changes:
        change.pop("resourceType")

    result = _preview_result(rbac_request, changes)

    assert result.ok is False
    assert result.category == "what_if_parse_failed"
    assert result.deployment_request_accepted is False


def test_bounded_action_only_live_topology_is_rejected(
    rbac_request,
) -> None:
    result = _preview_result(
        rbac_request,
        _bounded_action_only_changes(rbac_request),
    )

    assert result.ok is False
    assert result.category == "what_if_parse_failed"
    assert result.deployment_request_accepted is False


def test_exact_create_derives_omitted_resource_type_from_identity(
    rbac_request,
) -> None:
    change = _exact_change(rbac_request)
    change.pop("resourceType")

    result = _preview_result(rbac_request, [change])

    assert result.ok is True
    assert result.preview_topology == "exact_create"
    assert result.what_if_diagnostic is None


def test_contradictory_resource_type_fails_closed_with_precise_reason(
    rbac_request,
) -> None:
    change = _exact_change(rbac_request)
    change["resourceType"] = "Microsoft.Storage/storageAccounts"

    result = _preview_result(rbac_request, [change])

    assert result.category == "what_if_parse_failed"
    diagnostic = result.what_if_diagnostic
    assert diagnostic is not None
    assert diagnostic.record_shapes[0].resource_id_shape_valid is True
    assert diagnostic.record_shapes[0].safe_resource_type == "role_assignment"
    assert "resource_type_mismatch" in diagnostic.failure_reasons


@pytest.mark.parametrize(
    "case",
    [
        "wrong_account",
        "wrong_child_project",
        "wrong_parent_relationship",
        "wrong_project_scope",
        "wrong_assignment_name",
        "wrong_assignment_resource_type",
        "wrong_principal",
        "wrong_role",
        "missing_expected_ignore",
        "additional_unrelated_ignore",
        "duplicate_ignore",
        "additional_unsupported",
    ],
)
def test_bounded_unsupported_rejects_incorrect_identity_details(
    rbac_request, case: str
) -> None:
    baseline = _preview_result(
        rbac_request,
        _live_shape_changes(rbac_request),
    )
    assert baseline.ok is True
    assert baseline.preview_topology == "expected_ignore_plus_unsupported"

    changes = _live_shape_changes(rbac_request)
    assignment = changes[-1]
    if case == "wrong_account":
        assignment["resourceId"] = str(assignment["resourceId"]).replace(
            f"/accounts/{rbac_request.foundry_account_name}/",
            "/accounts/unrelated-account/",
        )
    elif case == "wrong_child_project":
        assignment["resourceId"] = str(assignment["resourceId"]).replace(
            f"/projects/{rbac_request.foundry_project_name}/",
            "/projects/unrelated-project/",
        )
    elif case == "wrong_parent_relationship":
        assignment["resourceId"] = str(assignment["resourceId"]).replace(
            f"/projects/{rbac_request.foundry_project_name}",
            "",
        )
    elif case == "wrong_project_scope":
        assignment["resourceId"] = str(assignment["resourceId"]).replace(
            f"/resourceGroups/{rbac_request.resource_group}/",
            "/resourceGroups/unrelated-resource-group/",
        )
    elif case == "wrong_assignment_name":
        assignment["resourceId"] = f"{assignment['resourceId']}-other"
    elif case == "wrong_assignment_resource_type":
        assignment["resourceType"] = "Microsoft.Authorization/locks"
    elif case == "wrong_principal":
        assignment["after"]["properties"]["principalId"] = "wrong-principal"
    elif case == "wrong_role":
        assignment["after"]["properties"]["roleDefinitionId"] = "wrong-role"
    elif case == "missing_expected_ignore":
        changes.pop(0)
    elif case == "additional_unrelated_ignore":
        changes.insert(
            -1,
            {
                "changeType": "Ignore",
                "resourceType": "Microsoft.Authorization/locks",
                "resourceId": (
                    f"/subscriptions/{rbac_request.approved_evidence.subscription_id}/"
                    f"resourceGroups/{rbac_request.resource_group}/providers/"
                    "Microsoft.Authorization/locks/unrelated-lock"
                ),
            },
        )
    elif case == "duplicate_ignore":
        changes.insert(-1, dict(changes[0]))
    else:
        changes.append(dict(assignment))

    result = _preview_result(rbac_request, changes)

    assert result.ok is False
    assert result.category == "what_if_parse_failed"
    assert result.deployment_request_accepted is False


def test_exact_assignment_preview_sets_every_required_match_flag(rbac_request) -> None:
    result = deployment.deploy_foundry_agent_consumer_rbac(
        replace(rbac_request, mode="what-if"),
        runner=FakeRunner(
            deployment.CommandResult(
                0, json.dumps({"changes": [_exact_change(rbac_request)]}), ""
            )
        ),
    )

    assert result.ok is True
    assert result.preview_topology == "exact_create"
    assert result.assignment_contents_proved is True
    assert result.manual_review_required is False
    assert result.what_if_diagnostic is None
    assert len(result.change_evidence) == 1
    evidence = result.change_evidence[0]
    assert evidence.approved_boundary is True
    assert evidence.expected_identity_match is True
    assert evidence.expected_parent_match is True
    assert evidence.expected_scope_match is True
    assert evidence.expected_multiplicity_match is True


def test_consumer_preview_decodes_azure_json_exactly_once(
    rbac_request, monkeypatch: pytest.MonkeyPatch
) -> None:
    stdout = json.dumps({"changes": [_exact_change(rbac_request)]})
    original_loads = json.loads
    decode_calls = 0

    def counted_loads(value):
        nonlocal decode_calls
        decode_calls += 1
        return original_loads(value)

    monkeypatch.setattr(deployment.json, "loads", counted_loads)

    result = deployment.deploy_foundry_agent_consumer_rbac(
        replace(rbac_request, mode="what-if"),
        runner=FakeRunner(deployment.CommandResult(0, stdout, "")),
    )

    assert result.ok is True
    assert result.what_if_diagnostic is None
    assert decode_calls == 1


@pytest.mark.parametrize("shape", ["duplicate", "missing_identity", "malformed_id"])
def test_exact_preview_rejects_duplicate_missing_or_malformed_identity_evidence(
    rbac_request, shape: str
) -> None:
    change = _exact_change(rbac_request, include_properties=shape != "missing_identity")
    if shape == "duplicate":
        changes = [change, dict(change)]
    elif shape == "malformed_id":
        change["resourceId"] = "not-an-arm-resource-id"
        changes = [change]
    else:
        changes = [change]

    result = deployment.deploy_foundry_agent_consumer_rbac(
        replace(rbac_request, mode="what-if"),
        runner=FakeRunner(
            deployment.CommandResult(0, json.dumps({"changes": changes}), "")
        ),
    )

    assert result.ok is False
    assert result.category == "what_if_parse_failed"
    assert result.change_evidence == ()


def test_incomplete_assignment_path_is_authoritatively_malformed(
    rbac_request,
) -> None:
    evidence = rbac_request.approved_evidence
    assert evidence is not None
    change = _exact_change(rbac_request)
    change["resourceId"] = (
        f"/subscriptions/{evidence.subscription_id}/resourceGroups/"
        f"{rbac_request.resource_group}/providers/"
        "Microsoft.Authorization/roleAssignments"
    )

    result = _preview_result(rbac_request, [change])

    assert result.category == "what_if_parse_failed"
    diagnostic = result.what_if_diagnostic
    assert diagnostic is not None
    assert diagnostic.record_shapes[0].resource_id_shape_valid is False
    assert "resource_id_malformed" in diagnostic.failure_reasons
    assert result.change_evidence == ()


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
            "approvedWebAppPrincipalId=00000000-0000-0000-0000-000000000002",
            "approvedFoundryProjectResourceId=/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/fictional-resource-group/providers/Microsoft.CognitiveServices/accounts/fictional-foundry-account/projects/fictional-foundry-project",
            "approvedRoleAssignmentName=16f4c29e-cc74-5373-8223-e478a3a63851",
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


def _invalid_topology(request, case: str) -> list[object]:
    ignores = _known_ignore_changes(request)
    unsupported = _unsupported_change(request)
    if case == "nine_ignores":
        return [*ignores[:-1], unsupported]
    if case == "eleven_ignores":
        return [*ignores, dict(ignores[0]), unsupported]
    if case == "unrelated_ignore":
        ignores[3]["resourceId"] = str(ignores[3]["resourceId"]) + "-other"
        return [*ignores, unsupported]
    if case == "duplicate_assignment":
        return [*ignores, unsupported, dict(unsupported)]
    if case == "missing_assignment":
        return ignores
    if case == "wrong_scope":
        unsupported["resourceId"] = str(unsupported["resourceId"]).replace(
            f"/resourceGroups/{request.resource_group}/",
            "/resourceGroups/other-resource-group/",
        )
        return [*ignores, unsupported]
    if case == "wrong_assignment_name":
        unsupported["resourceId"] = str(unsupported["resourceId"]) + "-other"
        return [*ignores, unsupported]
    if case == "wrong_resource_type":
        unsupported["resourceType"] = "Microsoft.Storage/storageAccounts"
        return [*ignores, unsupported]
    if case == "unrelated_unsupported":
        ignores[0]["changeType"] = "Unsupported"
        return [*ignores, unsupported]
    if case == "create_wrong_principal":
        create = _exact_change(request)
        create["after"]["properties"]["principalId"] = "wrong-principal"
        return [create]
    if case == "create_wrong_role":
        create = _exact_change(request)
        create["after"]["properties"]["roleDefinitionId"] = (
            "/subscriptions/private/providers/"
            "Microsoft.Authorization/roleDefinitions/wrong-role"
        )
        return [create]
    if case == "create_plus_ignore":
        return [_exact_change(request), ignores[0]]
    if case == "non_object":
        return [*ignores[:-1], None, unsupported]
    if case in {
        "Create",
        "Delete",
        "Modify",
        "Replacement",
        "Deploy",
        "unknown",
    }:
        ignores[0]["changeType"] = (
            "UnexpectedFutureType" if case == "unknown" else case
        )
        return [*ignores, unsupported]
    raise AssertionError(f"unhandled case: {case}")


@pytest.mark.parametrize(
    "case",
    [
        "nine_ignores",
        "eleven_ignores",
        "duplicate_assignment",
        "missing_assignment",
        "unrelated_unsupported",
        "Create",
        "Delete",
        "Modify",
        "Replacement",
        "Deploy",
        "unknown",
        "non_object",
    ],
)
def test_unsafe_or_unrelated_preview_topologies_fail_closed(
    rbac_request, case: str
) -> None:
    result = _preview_result(rbac_request, _invalid_topology(rbac_request, case))

    assert result.ok is False
    assert result.category == "what_if_parse_failed"
    assert result.deployment_request_accepted is False
    assert result.change_evidence == ()


def test_rejected_preview_reports_closed_action_and_resource_structure(
    rbac_request,
) -> None:
    changes = [*_known_ignore_changes(rbac_request), _unsupported_change(rbac_request)]
    changes[0]["changeType"] = "NoChange"

    result = _preview_result(rbac_request, changes)

    assert result.category == "what_if_parse_failed"
    diagnostic = result.what_if_diagnostic
    assert diagnostic is not None
    public = diagnostic.to_json_dict()
    assert public["change_record_count"] == 11
    assert public["action_counts"]["Ignore"] == 9
    assert public["action_counts"]["NoChange"] == 1
    assert public["action_counts"]["Unsupported"] == 1
    assert public["resource_type_counts"]["role_assignment"] == 1
    assert public["resource_type_counts"]["foundry_account"] == 1
    assert public["resource_type_counts"]["foundry_project"] == 1
    assert public["resource_type_counts"]["web_app"] == 1
    assert public["resource_type_counts"]["app_service_plan"] == 1
    assert public["resource_type_counts"]["other_known"] == 6
    assert public["resembles_expected_ignore_plus_unsupported"] is True
    assert "ignore_set_incomplete" in public["failure_reasons"]
    assert "unexpected_record" in public["failure_reasons"]
    assert "unsupported_topology_mismatch" in public["failure_reasons"]
    assert "no_supported_topology_matched" in public["failure_reasons"]


def test_rejected_assignment_shape_reports_presence_and_content_predicates(
    rbac_request,
) -> None:
    change = _exact_change(rbac_request)
    change["after"] = {"properties": {}}

    result = _preview_result(rbac_request, [change])

    diagnostic = result.what_if_diagnostic
    assert diagnostic is not None
    shape = diagnostic.record_shapes[0]
    assert shape.action == "Create"
    assert shape.safe_resource_type == "role_assignment"
    assert shape.after_present is True
    assert shape.properties_present is True
    assert shape.principal_id_present is False
    assert shape.role_definition_id_present is False
    assert shape.expected_resource_match is True
    assert shape.expected_parent_match is True
    assert shape.expected_scope_match is True
    assert shape.expected_identity_match is True
    assert "principal_evidence_missing" in diagnostic.failure_reasons
    assert "role_evidence_missing" in diagnostic.failure_reasons
    assert "create_topology_mismatch" in diagnostic.failure_reasons


@pytest.mark.parametrize(
    "after",
    [
        "malformed",
        {"properties": "malformed"},
        {"properties": {"principalId": 7}},
        {"properties": {"principalId": "wrong-principal"}},
        {"properties": {"roleDefinitionId": 7}},
        {"properties": {"roleDefinitionId": "wrong-role"}},
    ],
)
def test_bounded_unsupported_requires_complete_exact_evidence(
    rbac_request, after: object
) -> None:
    assignment = _unsupported_change(rbac_request)
    assignment["after"] = after

    result = _preview_result(
        rbac_request,
        [*_known_ignore_changes(rbac_request), assignment],
    )

    assert result.ok is False
    assert result.category == "what_if_parse_failed"
    assert result.deployment_request_accepted is False


def test_unsupported_null_evidence_is_rejected(
    rbac_request,
) -> None:
    assignment = _unsupported_change(rbac_request)
    assignment["after"] = {
        "properties": {
            "principalId": None,
            "roleDefinitionId": None,
        }
    }

    result = _preview_result(
        rbac_request,
        [*_known_ignore_changes(rbac_request), assignment],
    )

    assert result.ok is False
    assert result.category == "what_if_parse_failed"


@pytest.mark.parametrize(
    ("case", "expected_reason"),
    [
        ("nine_ignores", "ignore_set_incomplete"),
        ("eleven_ignores", "ignore_set_has_extra_record"),
    ],
)
def test_rejected_ignore_sets_report_missing_or_extra_without_identities(
    rbac_request, case: str, expected_reason: str
) -> None:
    result = _preview_result(rbac_request, _invalid_topology(rbac_request, case))

    assert result.what_if_diagnostic is not None
    assert expected_reason in result.what_if_diagnostic.failure_reasons


def test_rejected_nested_deployment_uses_only_safe_type_classification(
    rbac_request,
) -> None:
    evidence = rbac_request.approved_evidence
    assert evidence is not None
    nested = {
        "changeType": "Deploy",
        "resourceType": "Microsoft.Resources/deployments",
        "resourceId": (
            f"/subscriptions/{evidence.subscription_id}/resourceGroups/"
            f"{rbac_request.resource_group}/providers/"
            "Microsoft.Resources/deployments/private-deployment-name"
        ),
    }

    result = _preview_result(rbac_request, [_exact_change(rbac_request), nested])

    diagnostic = result.what_if_diagnostic
    assert diagnostic is not None
    assert dict(diagnostic.resource_type_counts)["nested_deployment"] == 1
    assert diagnostic.record_shapes[1].safe_resource_type == "nested_deployment"
    assert "unexpected_record" in diagnostic.failure_reasons


@pytest.mark.parametrize(
    ("stdout", "flags", "reason"),
    [
        ("[]", (False, False, False, None), "payload_not_object"),
        ("{}", (True, False, False, None), "changes_missing"),
        (
            '{"changes":{}}',
            (True, True, False, None),
            "changes_not_list",
        ),
        (
            '{"changes":[null]}',
            (True, True, True, 1),
            "change_record_not_object",
        ),
    ],
)
def test_malformed_top_level_shapes_receive_closed_diagnostics(
    rbac_request, stdout: str, flags: tuple[object, ...], reason: str
) -> None:
    result = deployment.deploy_foundry_agent_consumer_rbac(
        replace(rbac_request, mode="what-if"),
        runner=FakeRunner(deployment.CommandResult(0, stdout, "")),
    )

    diagnostic = result.what_if_diagnostic
    assert diagnostic is not None
    assert (
        diagnostic.payload_is_object,
        diagnostic.changes_present,
        diagnostic.changes_is_list,
        diagnostic.change_record_count,
    ) == flags
    assert reason in diagnostic.failure_reasons


def test_nonobject_record_reports_only_evaluated_and_collection_reasons(
    rbac_request,
) -> None:
    result = _preview_result(rbac_request, [None])

    diagnostic = result.what_if_diagnostic
    assert diagnostic is not None
    assert diagnostic.failure_reasons == (
        "change_record_not_object",
        "no_supported_topology_matched",
    )


def test_parse_failure_diagnostic_excludes_raw_azure_values_everywhere(
    rbac_request,
) -> None:
    evidence = rbac_request.approved_evidence
    assert evidence is not None
    change = _exact_change(rbac_request)
    change["changeType"] = "Replacement"
    result = _preview_result(rbac_request, [change])

    diagnostic = result.what_if_diagnostic
    assert diagnostic is not None
    public = "\n".join(
        (
            repr(diagnostic),
            repr(result),
            json.dumps(result.to_json_dict()),
            result.message,
            result.recommended_next_step,
        )
    )
    forbidden = (
        evidence.subscription_id,
        evidence.web_app_principal_id,
        evidence.role_definition_id,
        evidence.role_assignment_name,
        rbac_request.resource_group,
        rbac_request.web_app_name,
        rbac_request.foundry_account_name,
        rbac_request.foundry_project_name,
        evidence.foundry_project_resource_id,
    )
    assert all(value not in public for value in forbidden)
    assert dict(diagnostic.action_counts)["Replacement"] == 1


def test_parse_failure_record_shapes_are_bounded_but_all_records_aggregate(
    rbac_request,
) -> None:
    evidence = rbac_request.approved_evidence
    assert evidence is not None
    beyond_cap = {
        "changeType": "Deploy",
        "resourceType": "Microsoft.Resources/deployments",
        "resourceId": (
            f"/subscriptions/{evidence.subscription_id}/resourceGroups/"
            f"{rbac_request.resource_group}/providers/"
            "Microsoft.Resources/deployments/private-deployment"
        ),
    }
    result = _preview_result(
        rbac_request,
        [None] * 20 + [beyond_cap] + [None] * 4,
    )

    diagnostic = result.what_if_diagnostic
    assert diagnostic is not None
    assert diagnostic.change_record_count == 25
    assert len(diagnostic.record_shapes) == 20
    assert diagnostic.record_shapes_truncated is True
    assert all(
        shape.action != "Deploy"
        and shape.safe_resource_type != "nested_deployment"
        for shape in diagnostic.record_shapes
    )
    assert dict(diagnostic.action_counts)["Deploy"] == 1
    assert dict(diagnostic.resource_type_counts)["nested_deployment"] == 1
    assert "unexpected_record" in diagnostic.failure_reasons


def test_json_integer_conversion_value_error_is_sanitized(rbac_request) -> None:
    oversized_integer = "9" * 5000
    stdout = f'{{"changes":[{oversized_integer}]}}'

    result = deployment.deploy_foundry_agent_consumer_rbac(
        replace(rbac_request, mode="what-if"),
        runner=FakeRunner(deployment.CommandResult(0, stdout, "")),
    )

    assert result.category == "what_if_parse_failed"
    assert result.azure_operation_attempted is True
    assert result.what_if_diagnostic is not None
    assert result.what_if_diagnostic.failure_reasons == (
        "diagnostic_generation_failed",
        "no_supported_topology_matched",
    )
    assert oversized_integer not in json.dumps(result.to_json_dict())


def test_normalizer_exception_is_sanitized(
    rbac_request, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_normalization(*_args, **_kwargs):
        raise RuntimeError("private normalization detail")

    monkeypatch.setattr(
        deployment,
        "normalize_sanitized_what_if_payload",
        fail_normalization,
    )

    result = _preview_result(rbac_request, [_exact_change(rbac_request)])

    assert result.category == "what_if_parse_failed"
    assert result.what_if_diagnostic is not None
    assert result.what_if_diagnostic.failure_reasons == (
        "diagnostic_generation_failed",
        "no_supported_topology_matched",
    )
    assert "private normalization detail" not in json.dumps(result.to_json_dict())


def test_diagnostic_construction_exception_is_sanitized(
    rbac_request, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_diagnostic(*_args, **_kwargs):
        raise RuntimeError("private diagnostic detail")

    monkeypatch.setattr(deployment, "_build_what_if_diagnostic", fail_diagnostic)
    change = _exact_change(rbac_request)
    change["changeType"] = "Modify"

    result = _preview_result(rbac_request, [change])

    assert result.category == "what_if_parse_failed"
    assert result.what_if_diagnostic is not None
    assert result.what_if_diagnostic.failure_reasons == (
        "diagnostic_generation_failed",
        "no_supported_topology_matched",
    )
    assert "private diagnostic detail" not in json.dumps(result.to_json_dict())


def test_runtime_closed_record_shape_rejects_arbitrary_classifications(
    rbac_request,
) -> None:
    change = _exact_change(rbac_request)
    change["changeType"] = "Modify"
    result = _preview_result(rbac_request, [change])
    assert result.what_if_diagnostic is not None
    shape = result.what_if_diagnostic.record_shapes[0]

    with pytest.raises(ValueError):
        replace(shape, action="arbitrary_action")
    with pytest.raises(ValueError):
        replace(shape, safe_resource_type="private_resource_type")


def test_runtime_closed_diagnostic_rejects_arbitrary_keys_and_reasons(
    rbac_request,
) -> None:
    change = _exact_change(rbac_request)
    change["changeType"] = "Modify"
    result = _preview_result(rbac_request, [change])
    diagnostic = result.what_if_diagnostic
    assert diagnostic is not None

    with pytest.raises(ValueError):
        replace(
            diagnostic,
            action_counts=(
                ("arbitrary_action", diagnostic.action_counts[0][1]),
                *diagnostic.action_counts[1:],
            ),
        )
    with pytest.raises(ValueError):
        replace(
            diagnostic,
            resource_type_counts=(
                (
                    "private_resource_type",
                    diagnostic.resource_type_counts[0][1],
                ),
                *diagnostic.resource_type_counts[1:],
            ),
        )
    with pytest.raises(ValueError):
        replace(
            diagnostic,
            failure_reasons=(
                *diagnostic.failure_reasons,
                "private_failure_reason",
            ),
        )


def _sanitized_preview_binding(result) -> str:
    payload = {
        "create_count": result.create_count,
        "modify_count": result.modify_count,
        "no_change_count": result.no_change_count,
        "delete_count": result.delete_count,
        "ignore_count": result.ignore_count,
        "deploy_count": result.deploy_count,
        "unsupported_count": result.unsupported_count,
        "changes": [change.to_json_dict() for change in result.change_evidence],
    }
    return hashlib.sha256(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def test_equivalent_key_order_produces_stable_sanitized_evidence_and_binding(
    rbac_request,
) -> None:
    changes = [*_known_ignore_changes(rbac_request), _unsupported_change(rbac_request)]
    reordered = [
        dict(reversed(tuple(change.items())))
        for change in changes
    ]

    first = _preview_result(rbac_request, changes)
    second = _preview_result(rbac_request, reordered)

    assert first.change_evidence == second.change_evidence
    assert _sanitized_preview_binding(first) == _sanitized_preview_binding(second)


def test_identity_only_changes_do_not_become_azure_assignment_proof(
    rbac_request,
) -> None:
    valid = _preview_result(
        rbac_request,
        [*_known_ignore_changes(rbac_request), _unsupported_change(rbac_request)],
    )
    changed = _invalid_topology(rbac_request, "unrelated_ignore")

    changed_result = _preview_result(rbac_request, changed)

    assert valid.ok is True
    assert changed_result.ok is False
    assert changed_result.category == "what_if_parse_failed"
    assert _sanitized_preview_binding(valid) != _sanitized_preview_binding(
        changed_result
    )


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
        "preview_topology",
        "assignment_contents_proved",
        "delete_review_required",
        "manual_review_required",
            "recommended_next_step",
            "change_evidence",
        }
