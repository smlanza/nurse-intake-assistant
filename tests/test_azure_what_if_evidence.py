import json

from src.app.services.azure_what_if_evidence import (
    ExpectedWhatIfResource,
    normalize_sanitized_what_if_payload,
    parse_sanitized_what_if,
    parse_what_if_resource_identities,
)


def test_expected_foundry_changes_are_sanitized_and_allowlisted() -> None:
    raw = json.dumps(
        {
            "changes": [
                {
                    "changeType": "Create",
                    "resourceId": (
                        "/subscriptions/private/resourceGroups/private/providers/"
                        "Microsoft.CognitiveServices/accounts/demo"
                    ),
                },
                {
                    "changeType": "Create",
                    "resourceId": (
                        "/subscriptions/private/resourceGroups/private/providers/"
                        "Microsoft.CognitiveServices/accounts/demo/projects/project"
                    ),
                },
            ]
        }
    )

    summary = parse_sanitized_what_if(
        raw,
        boundary="foundry",
        allowlisted_resource_types={
            "Microsoft.CognitiveServices/accounts": "foundry_account",
            "Microsoft.CognitiveServices/accounts/projects": "foundry_project",
        },
    )

    assert summary is not None
    assert summary.all_changes_allowlisted is True
    assert [change.logical_category for change in summary.changes] == [
        "foundry_account",
        "foundry_project",
    ]
    assert "private" not in json.dumps(summary.to_json_list())


def test_unrelated_create_is_retained_only_as_unidentified_safe_evidence() -> None:
    raw = json.dumps(
        {
            "changes": [
                {
                    "changeType": "Create",
                    "resourceId": (
                        "/subscriptions/private/resourceGroups/private/providers/"
                        "Microsoft.KeyVault/vaults/unexpected"
                    ),
                }
            ]
        }
    )

    summary = parse_sanitized_what_if(
        raw,
        boundary="foundry",
        allowlisted_resource_types={
            "Microsoft.CognitiveServices/accounts": "foundry_account"
        },
    )

    assert summary is not None
    assert summary.all_changes_allowlisted is False
    assert summary.changes[0].resource_type == "unidentified"
    assert summary.changes[0].logical_category == "unexpected_resource"
    assert "KeyVault" not in json.dumps(summary.to_json_list())


def test_missing_resource_identity_is_not_automatically_allowlisted() -> None:
    summary = parse_sanitized_what_if(
        '{"changes":[{"changeType":"Create"}]}',
        boundary="web_app",
        allowlisted_resource_types={"Microsoft.Web/sites": "web_app"},
    )

    assert summary is not None
    assert summary.all_changes_allowlisted is False
    assert summary.changes[0].resource_type == "unidentified"


def test_decoded_payload_normalizer_uses_authoritative_incomplete_path_result() -> None:
    calls: list[tuple[int, bool, str | None]] = []
    payload = {
        "changes": [
            {
                "changeType": "Create",
                "resourceId": (
                    "/subscriptions/private/resourceGroups/daily-rg/providers/"
                    "Microsoft.Authorization/roleAssignments"
                ),
            }
        ]
    }

    normalized = normalize_sanitized_what_if_payload(
        payload,
        boundary="consumer_rbac",
        record_factory=lambda ordinal, _raw, facts: calls.append(
            (ordinal, facts.resource_id_shape_valid, facts.resource_type)
        ),
        allowlisted_resource_types={
            "Microsoft.Authorization/roleAssignments": "role_assignment"
        },
    )

    assert calls == [(1, False, None)]
    assert normalized.records == (None,)
    assert normalized.change_record_count == 1
    assert normalized.sanitized_summary is not None
    assert normalized.sanitized_summary.all_changes_allowlisted is False


def test_project_scoped_extension_resource_retains_canonical_parent() -> None:
    project_id = (
        "/subscriptions/00000000-0000-0000-0000-000000000001/"
        "resourceGroups/fictional-rg/providers/"
        "Microsoft.CognitiveServices/accounts/fictional-account/"
        "projects/fictional-project"
    )
    assignment_name = "00000000-0000-0000-0000-000000000002"
    assignment_id = (
        f"{project_id}/providers/Microsoft.Authorization/"
        f"roleAssignments/{assignment_name}"
    )

    identities = parse_what_if_resource_identities(
        json.dumps(
            {
                "changes": [
                    {
                        "changeType": "Unsupported",
                        "resourceId": assignment_id,
                    }
                ]
            }
        )
    )

    assert identities is not None
    assert len(identities) == 1
    identity = identities[0]
    assert identity.resource_type == "Microsoft.Authorization/roleAssignments"
    assert identity.resource_name == assignment_name
    assert identity.name_segments == (assignment_name,)
    assert identity.canonical_resource_id == assignment_id
    assert identity.parent_resource_id == project_id
    assert identity.scope_resource_id == project_id
    assert identity.extension_resource is True
    assert identity.provider_segments == (
        (
            "Microsoft.CognitiveServices",
            "accounts",
            "fictional-account",
            "projects",
            "fictional-project",
        ),
        (
            "Microsoft.Authorization",
            "roleAssignments",
            assignment_name,
        ),
    )


def test_incomplete_project_scoped_extension_resource_is_invalid() -> None:
    incomplete_id = (
        "/subscriptions/00000000-0000-0000-0000-000000000001/"
        "resourceGroups/fictional-rg/providers/"
        "Microsoft.CognitiveServices/accounts/fictional-account/"
        "projects/fictional-project/providers/"
        "Microsoft.Authorization/roleAssignments"
    )

    normalized = normalize_sanitized_what_if_payload(
        {
            "changes": [
                {
                    "changeType": "Unsupported",
                    "resourceId": incomplete_id,
                }
            ]
        },
        boundary="consumer_rbac",
        record_factory=lambda _ordinal, _raw, facts: (
            facts.resource_id_shape_valid
        ),
    )

    assert normalized.records == (False,)


def test_supplied_resource_type_must_match_canonical_extension_type() -> None:
    assignment_id = (
        "/subscriptions/00000000-0000-0000-0000-000000000001/"
        "resourceGroups/fictional-rg/providers/"
        "Microsoft.CognitiveServices/accounts/fictional-account/"
        "projects/fictional-project/providers/"
        "Microsoft.Authorization/roleAssignments/"
        "00000000-0000-0000-0000-000000000002"
    )

    normalized = normalize_sanitized_what_if_payload(
        {
            "changes": [
                {
                    "changeType": "Unsupported",
                    "resourceId": assignment_id,
                    "resourceType": "Microsoft.Storage/storageAccounts",
                }
            ]
        },
        boundary="consumer_rbac",
        record_factory=lambda _ordinal, _raw, facts: (
            facts.resource_type,
            facts.resource_type_present,
            facts.resource_type_consistent,
        ),
    )

    assert normalized.records == (
        ("Microsoft.Authorization/roleAssignments", True, False),
    )
    assert normalized.sanitized_summary is None


def test_exact_topology_rejects_same_type_wrong_name_scope_parent_and_multiplicity() -> None:
    expected = (
        ExpectedWhatIfResource(
            resource_type="Microsoft.CognitiveServices/accounts",
            logical_category="foundry_account",
            resource_group="daily-rg",
            name_segments=("expected-account",),
        ),
        ExpectedWhatIfResource(
            resource_type="Microsoft.CognitiveServices/accounts/projects",
            logical_category="foundry_project",
            resource_group="daily-rg",
            name_segments=("expected-account", "expected-project"),
        ),
    )
    cases = (
        [
            _change("Microsoft.CognitiveServices/accounts/other-account"),
            _change(
                "Microsoft.CognitiveServices/accounts/expected-account/projects/expected-project"
            ),
        ],
        [
            _change("Microsoft.CognitiveServices/accounts/expected-account", group="other-rg"),
            _change(
                "Microsoft.CognitiveServices/accounts/expected-account/projects/expected-project"
            ),
        ],
        [
            _change("Microsoft.CognitiveServices/accounts/expected-account"),
            _change(
                "Microsoft.CognitiveServices/accounts/other-account/projects/expected-project"
            ),
        ],
        [
            _change("Microsoft.CognitiveServices/accounts/expected-account"),
            _change("Microsoft.CognitiveServices/accounts/expected-account"),
            _change(
                "Microsoft.CognitiveServices/accounts/expected-account/projects/expected-project"
            ),
        ],
    )

    for changes in cases:
        summary = parse_sanitized_what_if(
            json.dumps({"changes": changes}),
            boundary="foundry",
            expected_resources=expected,
        )
        assert summary is not None
        assert summary.exact_topology_match is False
        assert summary.all_changes_allowlisted is False
        assert "daily-rg" not in json.dumps(summary.to_json_list())
        assert "expected-account" not in json.dumps(summary.to_json_list())


def test_exact_topology_requires_every_expected_resource_once() -> None:
    expected = (
        ExpectedWhatIfResource(
            "Microsoft.CognitiveServices/accounts",
            "foundry_account",
            "daily-rg",
            ("expected-account",),
        ),
        ExpectedWhatIfResource(
            "Microsoft.CognitiveServices/accounts/projects",
            "foundry_project",
            "daily-rg",
            ("expected-account", "expected-project"),
        ),
    )
    summary = parse_sanitized_what_if(
        json.dumps(
            {"changes": [_change("Microsoft.CognitiveServices/accounts/expected-account")]}
        ),
        boundary="foundry",
        expected_resources=expected,
    )

    assert summary is not None
    assert summary.exact_topology_match is False


def test_expected_ignore_subset_mode_is_opt_in_and_identity_exact() -> None:
    expected = (
        ExpectedWhatIfResource(
            "Microsoft.Web/sites",
            "web_app",
            "daily-rg",
            ("expected-web-app",),
        ),
    )
    expected_ignored = (
        ExpectedWhatIfResource(
            "Microsoft.CognitiveServices/accounts",
            "foundry_account_reference",
            "daily-rg",
            ("expected-account",),
        ),
        ExpectedWhatIfResource(
            "Microsoft.CognitiveServices/accounts/projects",
            "foundry_project_reference",
            "daily-rg",
            ("expected-account", "expected-project"),
        ),
    )
    changes = [
        {
            "changeType": "NoChange",
            "resourceId": (
                "/subscriptions/private/resourceGroups/daily-rg/providers/"
                "Microsoft.Web/sites/expected-web-app"
            ),
        },
        {
            "changeType": "Ignore",
            "resourceId": (
                "/subscriptions/private/resourceGroups/daily-rg/providers/"
                "Microsoft.CognitiveServices/accounts/expected-account"
            ),
            "before": {"id": "private-before"},
            "after": {"id": "private-after"},
            "delta": {"changes": []},
        },
    ]
    common = {
        "boundary": "web_app",
        "expected_resources": expected,
        "sanitized_additional_resource_types": {
            "Microsoft.CognitiveServices/accounts": "foundry_account_reference",
            "Microsoft.CognitiveServices/accounts/projects": (
                "foundry_project_reference"
            ),
        },
        "expected_ignored_resources": expected_ignored,
        "allow_expected_ignored_resources_absent": True,
    }

    exact_set = parse_sanitized_what_if(
        json.dumps({"changes": changes}),
        **common,
    )
    subset = parse_sanitized_what_if(
        json.dumps({"changes": changes}),
        allow_expected_ignored_resource_subsets=True,
        **common,
    )
    duplicate = parse_sanitized_what_if(
        json.dumps({"changes": [*changes, dict(changes[1])]}),
        allow_expected_ignored_resource_subsets=True,
        **common,
    )

    assert exact_set is not None
    assert exact_set.exact_topology_match is False
    assert subset is not None
    assert subset.exact_topology_match is True
    assert subset.all_changes_allowlisted is True
    assert duplicate is not None
    assert duplicate.exact_topology_match is False


def test_exact_topology_can_sanitize_nested_deployment_for_guided_review() -> None:
    expected = (
        ExpectedWhatIfResource(
            "Microsoft.CognitiveServices/accounts",
            "foundry_account",
            "daily-rg",
            ("expected-account",),
        ),
    )
    summary = parse_sanitized_what_if(
        json.dumps(
            {
                "changes": [
                    _change("Microsoft.CognitiveServices/accounts/expected-account"),
                    {
                        **_change("Microsoft.Resources/deployments/private-name"),
                        "changeType": "Deploy",
                    },
                ]
            }
        ),
        boundary="foundry",
        expected_resources=expected,
        sanitized_additional_resource_types={
            "Microsoft.Resources/deployments": "nested_deployment"
        },
    )

    assert summary is not None
    assert summary.exact_topology_match is True
    nested = summary.changes[1]
    assert nested.logical_category == "nested_deployment"
    assert nested.resource_type == "Microsoft.Resources/deployments"
    assert nested.approved_boundary is False
    assert "private-name" not in json.dumps(summary.to_json_list())


def _change(resource_path: str, *, group: str = "daily-rg") -> dict[str, str]:
    return {
        "changeType": "Create",
        "resourceId": (
            f"/subscriptions/private/resourceGroups/{group}/providers/{resource_path}"
        ),
    }
