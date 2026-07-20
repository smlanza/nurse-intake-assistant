import json

from src.app.services.azure_what_if_evidence import (
    ExpectedWhatIfResource,
    parse_sanitized_what_if,
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
