import json
from pathlib import Path

import pytest

import scripts.deploy_foundry_infra as script


class FakeRunner:
    def __init__(self, results: list[script.CommandResult] | None = None) -> None:
        self.results = list(results or [])
        self.calls: list[list[str]] = []

    def run(self, args: list[str]) -> script.CommandResult:
        assert isinstance(args, list)
        self.calls.append(args)
        return self.results.pop(0) if self.results else script.CommandResult(0, "{}", "")


@pytest.fixture
def files(tmp_path: Path) -> tuple[Path, Path, Path]:
    template = tmp_path / "foundry-only.bicep"
    module = tmp_path / "modules" / "foundry.bicep"
    parameters = tmp_path / "foundry-only.bicepparam"
    module.parent.mkdir()
    template.write_text("param modelName string\n")
    module.write_text("targetScope = 'resourceGroup'\n")
    parameters.write_text(
        "using './foundry-only.bicep'\n"
        "param foundryAccountName = 'private-account'\n"
        "param foundryProjectName = 'private-project'\n"
        "param modelDeploymentName = 'private-deployment'\n"
        "param modelName = 'private-value'\n"
        "param modelVersion = 'private-version'\n"
        "param modelPublisherFormat = 'OpenAI'\n"
        "param modelSkuName = 'PrivateSku'\n"
        "param modelCapacity = 1\n"
    )
    return template, module, parameters


def _paths(monkeypatch: pytest.MonkeyPatch, files: tuple[Path, Path, Path]) -> Path:
    template, module, parameters = files
    full_stack_template = template.parent / "main.bicep"
    full_stack_template.write_text("param deployFoundry bool\n")
    monkeypatch.setattr(
        script,
        "TEMPLATES",
        {"foundry-only": template, "full-stack": full_stack_template},
    )
    monkeypatch.setattr(script, "FOUNDRY_MODULE", module)
    return parameters


def _structured_name_conflict(
    *,
    resource_group: str = "existing-rg",
    resource_type: str = "Microsoft.CognitiveServices/accounts",
    resource_name: str = "private-account",
) -> str:
    return json.dumps(
        {
            "error": {
                "code": "CustomDomainInUse",
                "target": (
                    "/subscriptions/00000000-0000-0000-0000-000000000001/"
                    f"resourceGroups/{resource_group}/providers/"
                    f"{resource_type}/{resource_name}"
                ),
                "details": [],
            }
        }
    )


def _wrapped_structured_name_conflict(
    *,
    resource_group: str = "existing-rg",
    resource_name: str = "private-account",
) -> str:
    return json.dumps(
        {
            "status": "Failed",
            "error": {
                "code": "InvalidTemplateDeployment",
                "target": "foundry-deployment",
                "message": "private outer message",
                "details": [
                    {
                        "code": "CustomDomainInUse",
                        "target": (
                            "/subscriptions/00000000-0000-0000-0000-000000000001/"
                            f"resourceGroups/{resource_group}/providers/"
                            "Microsoft.CognitiveServices/accounts/"
                            f"{resource_name}"
                        ),
                        "message": "private account conflict message",
                    }
                ],
            },
        }
    )


def _soft_deleted_account_stderr(
    *,
    subscription_id: str = "00000000-0000-0000-0000-000000000001",
    resource_group: str = "existing-rg",
    provider: str = "Microsoft.CognitiveServices",
    resource_type: str = "accounts",
    resource_name: str = "private-account",
) -> str:
    resource_id = (
        f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}/"
        f"providers/{provider}/{resource_type}/{resource_name}"
    )
    return (
        "ERROR: (InvalidTemplateDeployment) The template deployment failed.\n"
        "Code: InvalidTemplateDeployment\n"
        "Message: Deployment validation failed.\n"
        "Details: (FlagMustBeSetForRestore) FlagMustBeSetForRestore - "
        f"An existing resource with ID '{resource_id}' has been soft-deleted. "
        "To restore the resource, set the restore property to true. "
        "If you do not want to restore it, purge the resource first."
    )


def _structured_soft_deleted_account(
    *,
    resource_group: str = "existing-rg",
    resource_name: str = "private-account",
    wrapped: bool = False,
) -> str:
    target = (
        "/subscriptions/00000000-0000-0000-0000-000000000001/"
        f"resourceGroups/{resource_group}/providers/"
        "Microsoft.CognitiveServices/accounts/"
        f"{resource_name}"
    )
    leaf = {
        "code": "FlagMustBeSetForRestore",
        "target": target,
        "message": "private soft-delete details",
    }
    error = (
        {
            "code": "InvalidTemplateDeployment",
            "message": "private wrapper details",
            "details": [leaf],
        }
        if wrapped
        else leaf
    )
    return json.dumps({"error": error})


def test_check_runs_only_local_cli_and_build_commands(
    monkeypatch: pytest.MonkeyPatch,
    files: tuple[Path, Path, Path],
) -> None:
    parameters = _paths(monkeypatch, files)
    runner = FakeRunner()
    result = script.execute(
        script.DeploymentRequest("check", "foundry-only", parameters, "rg", "eastus2"),
        runner,
    )
    assert result["ok"] is True
    assert runner.calls == [
        ["az", "version", "--output", "json"],
        ["az", "bicep", "version"],
        ["az", "bicep", "build", "--file", str(files[0]), "--stdout"],
        ["az", "bicep", "build-params", "--file", str(parameters), "--stdout"],
    ]
    flattened = " ".join(" ".join(call) for call in runner.calls)
    for forbidden in ("group create", "group show", "account show", "what-if", "deployment group create"):
        assert forbidden not in flattened
    assert "private-value" not in json.dumps(result)


def test_check_rejects_secret_like_parameter_names(
    monkeypatch: pytest.MonkeyPatch,
    files: tuple[Path, Path, Path],
) -> None:
    parameters = _paths(monkeypatch, files)
    parameters.write_text("using './foundry-only.bicep'\nparam accessToken = 'hidden'\n")
    result = script.execute(
        script.DeploymentRequest("check", "foundry-only", parameters, "rg", "eastus2"),
        FakeRunner(),
    )
    assert result["category"] == "parameter_file_invalid"
    assert "hidden" not in json.dumps(result)


def test_what_if_checks_group_then_runs_non_mutating_deployment(
    monkeypatch: pytest.MonkeyPatch,
    files: tuple[Path, Path, Path],
) -> None:
    parameters = _paths(monkeypatch, files)
    runner = FakeRunner(
        [
            script.CommandResult(0, "true", ""),
            script.CommandResult(0, json.dumps({"changes": []}), ""),
        ]
    )
    result = script.execute(
        script.DeploymentRequest("what-if", "foundry-only", parameters, "existing-rg", "eastus2"),
        runner,
    )
    assert result["category"] == "success"
    assert runner.calls[0][:3] == ["az", "group", "exists"]
    command = runner.calls[1]
    assert command == [
        "az", "deployment", "group", "what-if",
        "--resource-group", "existing-rg",
        "--parameters", str(parameters),
        "--no-pretty-print", "--output", "json",
    ]
    assert "--template-file" not in command
    assert not any(argument.startswith("@") for argument in command)


def test_internal_what_if_reuses_verified_group_without_duplicate_exists_read(
    monkeypatch: pytest.MonkeyPatch,
    files: tuple[Path, Path, Path],
) -> None:
    parameters = _paths(monkeypatch, files)
    runner = FakeRunner(
        [script.CommandResult(0, json.dumps({"changes": []}), "")]
    )

    result = script.execute(
        script.DeploymentRequest(
            "what-if", "foundry-only", parameters, "existing-rg", "eastus2"
        ),
        runner,
        verify_resource_group=False,
    )

    assert result["ok"] is True
    assert len(runner.calls) == 1
    assert runner.calls[0][:4] == ["az", "deployment", "group", "what-if"]


def test_what_if_returns_sanitized_change_counts_and_review_flags(
    monkeypatch: pytest.MonkeyPatch,
    files: tuple[Path, Path, Path],
) -> None:
    parameters = _paths(monkeypatch, files)
    preview = json.dumps(
        {
            "changes": [
                {"changeType": "Create", "resourceId": "private-resource-id"},
                {"changeType": "Modify", "delta": "private-detail"},
                {"changeType": "Delete", "before": "private-detail"},
                {"changeType": "Unsupported", "after": "private-detail"},
            ]
        }
    )
    runner = FakeRunner(
        [script.CommandResult(0, "true", ""), script.CommandResult(0, preview, "")]
    )

    result = script.execute(
        script.DeploymentRequest(
            "what-if", "foundry-only", parameters, "existing-rg", "eastus2"
        ),
        runner,
    )

    assert result["category"] == "success"
    assert result["create_count"] == 1
    assert result["modify_count"] == 1
    assert result["delete_count"] == 1
    assert result["unsupported_count"] == 1
    assert result["manual_review_required"] is True
    assert result["delete_review_required"] is True
    rendered = json.dumps(result)
    assert "private-resource-id" not in rendered
    assert "private-detail" not in rendered


def _foundry_topology_changes(
    *, resource_group: str = "existing-rg"
) -> list[dict[str, str]]:
    root = f"/subscriptions/private-sub/resourceGroups/{resource_group}/providers"
    account = f"{root}/Microsoft.CognitiveServices/accounts/private-account"
    return [
        {"changeType": "Create", "resourceId": account},
        {
            "changeType": "Create",
            "resourceId": f"{account}/projects/private-project",
        },
        {
            "changeType": "Create",
            "resourceId": f"{account}/deployments/private-deployment",
        },
    ]


def test_foundry_adapter_accepts_only_the_exact_expected_topology(
    monkeypatch: pytest.MonkeyPatch,
    files: tuple[Path, Path, Path],
) -> None:
    parameters = _paths(monkeypatch, files)
    runner = FakeRunner(
        [
            script.CommandResult(
                0,
                json.dumps({"changes": _foundry_topology_changes()}),
                "",
            )
        ]
    )

    result = script.execute(
        script.DeploymentRequest(
            "what-if", "foundry-only", parameters, "existing-rg", "eastus2"
        ),
        runner,
        verify_resource_group=False,
    )

    assert result["exact_topology_match"] is True
    assert result["manual_review_required"] is False
    assert all(change["approved_boundary"] for change in result["change_evidence"])


@pytest.mark.parametrize(
    "mutate",
    [
        lambda changes: changes.__setitem__(
            0,
            {
                **changes[0],
                "resourceId": changes[0]["resourceId"].replace(
                    "private-account", "wrong-account"
                ),
            },
        ),
        lambda changes: changes.__setitem__(
            0,
            {
                **changes[0],
                "resourceId": changes[0]["resourceId"].replace(
                    "existing-rg", "wrong-rg"
                ),
            },
        ),
        lambda changes: changes.__setitem__(
            1,
            {
                **changes[1],
                "resourceId": changes[1]["resourceId"].replace(
                    "private-account/projects", "wrong-parent/projects"
                ),
            },
        ),
        lambda changes: changes.append(dict(changes[0])),
        lambda changes: changes.append(
            {
                "changeType": "Create",
                "resourceId": changes[0]["resourceId"].replace(
                    "private-account", "extra-account"
                ),
            }
        ),
    ],
    ids=("wrong-name", "wrong-group", "wrong-parent", "duplicate", "extra"),
)
def test_foundry_adapter_rejects_inexact_same_type_topologies(
    monkeypatch: pytest.MonkeyPatch,
    files: tuple[Path, Path, Path],
    mutate,
) -> None:
    parameters = _paths(monkeypatch, files)
    changes = _foundry_topology_changes()
    mutate(changes)
    runner = FakeRunner(
        [script.CommandResult(0, json.dumps({"changes": changes}), "")]
    )

    result = script.execute(
        script.DeploymentRequest(
            "what-if", "foundry-only", parameters, "existing-rg", "eastus2"
        ),
        runner,
        verify_resource_group=False,
    )

    assert result["exact_topology_match"] is False
    assert result["manual_review_required"] is True
    assert not all(
        change["approved_boundary"] for change in result["change_evidence"]
    )


def test_what_if_missing_group_never_attempts_deployment(
    monkeypatch: pytest.MonkeyPatch,
    files: tuple[Path, Path, Path],
) -> None:
    parameters = _paths(monkeypatch, files)
    runner = FakeRunner([script.CommandResult(0, "false", "")])
    result = script.execute(
        script.DeploymentRequest("what-if", "foundry-only", parameters, "missing-rg", "eastus2"),
        runner,
    )
    assert result["category"] == "resource_group_missing"
    assert len(runner.calls) == 1


@pytest.mark.parametrize(
    ("stderr", "category"),
    [
        ("Please run az login", "authentication_or_authorization_failed"),
        ("Unexpected CLI failure", "what_if_failed"),
    ],
)
def test_what_if_group_exists_failure_never_attempts_deployment(
    monkeypatch: pytest.MonkeyPatch,
    files: tuple[Path, Path, Path],
    stderr: str,
    category: str,
) -> None:
    parameters = _paths(monkeypatch, files)
    runner = FakeRunner([script.CommandResult(1, "", stderr)])

    result = script.execute(
        script.DeploymentRequest(
            "what-if", "foundry-only", parameters, "existing-rg", "eastus2"
        ),
        runner,
    )

    assert result["category"] == category
    assert len(runner.calls) == 1
    assert runner.calls[0][:3] == ["az", "group", "exists"]


def test_internal_what_if_does_not_classify_unstructured_deleted_account_text(
    monkeypatch: pytest.MonkeyPatch,
    files: tuple[Path, Path, Path],
) -> None:
    parameters = _paths(monkeypatch, files)
    stderr = (
        "ERROR: (InvalidTemplateDeployment) Microsoft.CognitiveServices/accounts "
        "account was deleted and is not available. Purge it or use a different "
        "name. private-account-name private-subscription-id"
    )
    runner = FakeRunner([script.CommandResult(1, "private-stdout", stderr)])

    result = script.execute(
        script.DeploymentRequest(
            "what-if", "foundry-only", parameters, "existing-rg", "eastus2"
        ),
        runner,
        verify_resource_group=False,
    )

    assert result["category"] == "what_if_failed"
    assert "what_if_failure_diagnostic" not in result
    serialized = json.dumps(result)
    assert "private-account-name" not in serialized
    assert "private-subscription-id" not in serialized
    assert "private-stdout" not in serialized


def test_internal_what_if_requires_structured_exact_name_conflict(
    monkeypatch: pytest.MonkeyPatch,
    files: tuple[Path, Path, Path],
) -> None:
    parameters = _paths(monkeypatch, files)
    runner = FakeRunner(
        [
            script.CommandResult(
                1,
                "private-stdout",
                _structured_name_conflict(),
            )
        ]
    )

    result = script.execute(
        script.DeploymentRequest(
            "what-if", "foundry-only", parameters, "existing-rg", "eastus2"
        ),
        runner,
        verify_resource_group=False,
    )

    assert result["category"] == "foundry_account_name_unavailable"
    assert result["what_if_failure_diagnostic"] == {
        "azure_error_class": "custom_domain_in_use",
        "failure_kind": "custom_domain_in_use",
        "same_configuration_retry_safe": False,
    }
    assert "private-account" not in json.dumps(result)
    assert "private-subscription" not in json.dumps(result)


def test_internal_what_if_classifies_wrapped_structured_name_conflict(
    monkeypatch: pytest.MonkeyPatch,
    files: tuple[Path, Path, Path],
) -> None:
    parameters = _paths(monkeypatch, files)
    result = script.execute(
        script.DeploymentRequest(
            "what-if", "foundry-only", parameters, "existing-rg", "eastus2"
        ),
        FakeRunner(
            [
                script.CommandResult(
                    1,
                    "",
                    _wrapped_structured_name_conflict(),
                )
            ]
        ),
        verify_resource_group=False,
    )

    assert result["category"] == "foundry_account_name_unavailable"
    assert result["what_if_failure_diagnostic"] == {
        "azure_error_class": "custom_domain_in_use",
        "failure_kind": "custom_domain_in_use",
        "same_configuration_retry_safe": False,
    }
    assert "private outer message" not in json.dumps(result)
    assert "private account conflict message" not in json.dumps(result)


def test_internal_what_if_classifies_exact_soft_deleted_account_stderr(
    monkeypatch: pytest.MonkeyPatch,
    files: tuple[Path, Path, Path],
) -> None:
    parameters = _paths(monkeypatch, files)

    result = script.execute(
        script.DeploymentRequest(
            "what-if", "foundry-only", parameters, "existing-rg", "eastus2"
        ),
        FakeRunner(
            [
                script.CommandResult(
                    1,
                    "",
                    _soft_deleted_account_stderr(),
                )
            ]
        ),
        verify_resource_group=False,
    )

    assert result["category"] == "foundry_account_name_unavailable"
    assert result["what_if_failure_diagnostic"] == {
        "azure_error_class": "FlagMustBeSetForRestore",
        "failure_kind": "soft_deleted_account_name",
        "same_configuration_retry_safe": False,
    }
    serialized = json.dumps(result)
    assert "subscriptions/" not in serialized
    assert "soft-deleted" not in serialized
    assert "purge" not in serialized


@pytest.mark.parametrize("wrapped", (False, True))
@pytest.mark.parametrize("stream", ("stdout", "stderr"))
def test_internal_what_if_classifies_structured_soft_deleted_account(
    monkeypatch: pytest.MonkeyPatch,
    files: tuple[Path, Path, Path],
    wrapped: bool,
    stream: str,
) -> None:
    parameters = _paths(monkeypatch, files)
    structured = _structured_soft_deleted_account(wrapped=wrapped)
    outcome = script.CommandResult(
        1,
        structured if stream == "stdout" else "",
        structured if stream == "stderr" else "",
    )

    result = script.execute(
        script.DeploymentRequest(
            "what-if", "foundry-only", parameters, "existing-rg", "eastus2"
        ),
        FakeRunner([outcome]),
        verify_resource_group=False,
    )

    assert result["category"] == "foundry_account_name_unavailable"
    assert result["what_if_failure_diagnostic"] == {
        "azure_error_class": "FlagMustBeSetForRestore",
        "failure_kind": "soft_deleted_account_name",
        "same_configuration_retry_safe": False,
    }
    assert "private soft-delete details" not in json.dumps(result)
    assert "private wrapper details" not in json.dumps(result)


@pytest.mark.parametrize(
    "stderr",
    (
        _soft_deleted_account_stderr(resource_group="wrong-rg"),
        _soft_deleted_account_stderr(resource_name="wrong-account"),
        _soft_deleted_account_stderr(provider="Microsoft.Web"),
        _soft_deleted_account_stderr(resource_type="projects"),
        _soft_deleted_account_stderr(subscription_id="not-a-subscription-id"),
        (
            "ERROR: (FlagMustBeSetForRestore) A resource was soft-deleted; "
            "restore or purge it."
        ),
        _soft_deleted_account_stderr().replace(
            "An existing resource with ID '", "An existing resource '"
        ),
        _soft_deleted_account_stderr()
        + "\n"
        + _soft_deleted_account_stderr(resource_name="another-account"),
        "ERROR: (AuthorizationFailed) FlagMustBeSetForRestore login required",
        "ERROR: quota exceeded while checking a soft-deleted deployment",
        "ERROR: (InvalidTemplateDeployment) FlagMustBeSetForRestore - An existing",
        _soft_deleted_account_stderr() + ("x" * 16_384),
        _soft_deleted_account_stderr() + ("\nnoise" * 65),
        (
            _soft_deleted_account_stderr()
            + " unrelated /subscriptions/"
            "00000000-0000-0000-0000-000000000002/resourceGroups/other"
        ),
    ),
    ids=(
        "wrong-resource-group",
        "wrong-account",
        "wrong-provider",
        "wrong-resource-type",
        "invalid-subscription",
        "generic-restore-language",
        "missing-target-phrase",
        "multiple-errors",
        "authorization",
        "quota",
        "truncated",
        "oversized",
        "too-many-lines",
        "additional-resource-id",
    ),
)
def test_soft_deleted_stderr_requires_one_exact_attributable_account(
    monkeypatch: pytest.MonkeyPatch,
    files: tuple[Path, Path, Path],
    stderr: str,
) -> None:
    parameters = _paths(monkeypatch, files)

    result = script.execute(
        script.DeploymentRequest(
            "what-if", "foundry-only", parameters, "existing-rg", "eastus2"
        ),
        FakeRunner([script.CommandResult(1, "", stderr)]),
        verify_resource_group=False,
    )

    assert result["category"] != "foundry_account_name_unavailable"
    assert "what_if_failure_diagnostic" not in result


def test_internal_what_if_does_not_overclassify_other_template_failures(
    monkeypatch: pytest.MonkeyPatch,
    files: tuple[Path, Path, Path],
) -> None:
    parameters = _paths(monkeypatch, files)
    runner = FakeRunner(
        [
            script.CommandResult(
                1,
                "",
                "ERROR: (InvalidTemplateDeployment) model is not available",
            )
        ]
    )

    result = script.execute(
        script.DeploymentRequest(
            "what-if", "foundry-only", parameters, "existing-rg", "eastus2"
        ),
        runner,
        verify_resource_group=False,
    )

    assert result["category"] == "what_if_failed"
    assert "what_if_failure_diagnostic" not in result


@pytest.mark.parametrize(
    "stderr",
    (
        "ERROR: Conflict",
        "ERROR: DeploymentActive",
        "ERROR: policy denied",
        "ERROR: quota exceeded",
        "ERROR: timeout",
        "ERROR: unknown failure",
    ),
)
def test_live_does_not_overclassify_unrelated_failures_as_name_conflicts(
    monkeypatch: pytest.MonkeyPatch,
    files: tuple[Path, Path, Path],
    stderr: str,
) -> None:
    parameters = _paths(monkeypatch, files)
    runner = FakeRunner([script.CommandResult(1, "", stderr)])

    result = script.execute(
        script.DeploymentRequest(
            "live", "foundry-only", parameters, "existing-rg", "eastus2"
        ),
        runner,
        ensure_resource_group=False,
    )

    assert result["category"] == "deployment_failed"
    assert "deployment_failure_diagnostic" not in result


def test_live_classifies_only_custom_domain_name_conflict_safely(
    monkeypatch: pytest.MonkeyPatch,
    files: tuple[Path, Path, Path],
) -> None:
    parameters = _paths(monkeypatch, files)
    runner = FakeRunner(
        [
            script.CommandResult(
                1,
                "private output",
                _structured_name_conflict(),
            )
        ]
    )

    result = script.execute(
        script.DeploymentRequest(
            "live", "foundry-only", parameters, "existing-rg", "eastus2"
        ),
        runner,
        ensure_resource_group=False,
    )

    assert result["category"] == "foundry_account_name_unavailable"
    assert result["deployment_failure_diagnostic"] == {
        "azure_error_class": "custom_domain_in_use",
        "failure_kind": "custom_domain_in_use",
        "account_name_conflict_proven": True,
    }
    assert "private output" not in json.dumps(result)
    assert "private account details" not in json.dumps(result)


def test_live_classifies_wrapped_structured_name_conflict_safely(
    monkeypatch: pytest.MonkeyPatch,
    files: tuple[Path, Path, Path],
) -> None:
    parameters = _paths(monkeypatch, files)
    result = script.execute(
        script.DeploymentRequest(
            "live", "foundry-only", parameters, "existing-rg", "eastus2"
        ),
        FakeRunner(
            [
                script.CommandResult(
                    1,
                    "",
                    _wrapped_structured_name_conflict(),
                )
            ]
        ),
        ensure_resource_group=False,
    )

    assert result["category"] == "foundry_account_name_unavailable"
    assert result["deployment_failure_diagnostic"] == {
        "azure_error_class": "custom_domain_in_use",
        "failure_kind": "custom_domain_in_use",
        "account_name_conflict_proven": True,
    }
    assert "private outer message" not in json.dumps(result)
    assert "private account conflict message" not in json.dumps(result)


def test_live_classifies_exact_soft_deleted_account_safely(
    monkeypatch: pytest.MonkeyPatch,
    files: tuple[Path, Path, Path],
) -> None:
    parameters = _paths(monkeypatch, files)

    result = script.execute(
        script.DeploymentRequest(
            "live", "foundry-only", parameters, "existing-rg", "eastus2"
        ),
        FakeRunner(
            [
                script.CommandResult(
                    1,
                    "",
                    _soft_deleted_account_stderr(),
                )
            ]
        ),
        ensure_resource_group=False,
    )

    assert result["category"] == "foundry_account_name_unavailable"
    assert result["deployment_failure_diagnostic"] == {
        "azure_error_class": "FlagMustBeSetForRestore",
        "failure_kind": "soft_deleted_account_name",
        "account_name_conflict_proven": True,
    }
    serialized = json.dumps(result)
    assert "subscriptions/" not in serialized
    assert "soft-deleted" not in serialized
    assert "restore" not in serialized


@pytest.mark.parametrize(
    "structured",
    (
        "ERROR: (CustomDomainInUse) private-account",
        "{malformed",
        _structured_name_conflict(resource_type="Microsoft.Web/sites"),
        _structured_name_conflict(resource_name="another-account"),
        _wrapped_structured_name_conflict(resource_name="another-account"),
        _structured_soft_deleted_account(resource_group="wrong-rg"),
        _structured_soft_deleted_account(resource_name="another-account"),
        _structured_soft_deleted_account(
            wrapped=True,
            resource_name="another-account",
        ),
        json.dumps(
            {
                "error": {
                    "code": "FlagMustBeSetForRestore",
                    "message": (
                        "A resource was soft-deleted; restore or purge it."
                    ),
                }
            }
        ),
        json.dumps(
            {
                "error": {
                    **json.loads(
                        _structured_soft_deleted_account()
                    )["error"],
                    "message": (
                        "Unrelated /subscriptions/"
                        "00000000-0000-0000-0000-000000000002/"
                        "resourceGroups/other"
                    ),
                }
            }
        ),
        json.dumps(
            {
                "status": "Failed",
                "error": {
                    "code": "InvalidTemplateDeployment",
                    "details": [
                        json.loads(_structured_name_conflict())["error"],
                        {
                            "code": "QuotaExceeded",
                            "target": "model-deployment",
                        },
                    ],
                },
            }
        ),
        json.dumps(
            {
                "error": {
                    "code": "CustomDomainInUse",
                    "target": (
                        "/subscriptions/00000000-0000-0000-0000-000000000001/"
                        "resourceGroups/existing-rg/providers/"
                        "Microsoft.CognitiveServices/accounts/private-account"
                    ),
                    "details": [
                        {
                            "code": "Conflict",
                            "target": "another-operation",
                        }
                    ],
                }
            }
        ),
        json.dumps(
            {
                "error": {
                    "code": "InvalidTemplateDeployment",
                    "details": [
                        json.loads(
                            _structured_soft_deleted_account()
                        )["error"],
                        {
                            "code": "FlagMustBeSetForRestore",
                            "target": (
                                "/subscriptions/"
                                "00000000-0000-0000-0000-000000000001/"
                                "resourceGroups/existing-rg/providers/"
                                "Microsoft.CognitiveServices/accounts/"
                                "another-account"
                            ),
                        },
                    ],
                }
            }
        ),
    ),
)
def test_name_conflict_requires_one_unambiguous_structured_account_failure(
    monkeypatch: pytest.MonkeyPatch,
    files: tuple[Path, Path, Path],
    structured: str,
) -> None:
    parameters = _paths(monkeypatch, files)
    result = script.execute(
        script.DeploymentRequest(
            "what-if",
            "foundry-only",
            parameters,
            "existing-rg",
            "eastus2",
        ),
        FakeRunner([script.CommandResult(1, "", structured)]),
        verify_resource_group=False,
    )

    assert result["category"] == "what_if_failed"
    assert "what_if_failure_diagnostic" not in result


def _deployment_output() -> str:
    return json.dumps(
        {
            "foundryResourceName": {"value": "private-account"},
            "foundryProjectName": {"value": "private-project"},
            "foundryProjectEndpoint": {
                "value": "https://private-account.services.ai.azure.com/api/projects/private-project"
            },
            "modelDeploymentName": {"value": "private-deployment"},
        }
    )


@pytest.mark.parametrize("template_mode", ["foundry-only", "full-stack"])
def test_live_creates_group_then_one_deployment_and_returns_only_safe_fields(
    monkeypatch: pytest.MonkeyPatch,
    files: tuple[Path, Path, Path],
    template_mode: str,
) -> None:
    parameters = _paths(monkeypatch, files)
    if template_mode == "full-stack":
        parameters.write_text(
            files[2].read_text().replace(
                "using './foundry-only.bicep'", "using './main.bicep'"
            )
            + "param deployFoundry = true\n"
        )
    runner = FakeRunner(
        [script.CommandResult(0, "{}", "sensitive group stderr"), script.CommandResult(0, _deployment_output(), "sensitive deployment stderr")]
    )
    result = script.execute(
        script.DeploymentRequest("live", template_mode, parameters, "daily-rg", "eastus2"), runner
    )
    assert runner.calls[0][:3] == ["az", "group", "create"]
    assert runner.calls[1][:4] == ["az", "deployment", "group", "create"]
    assert len(runner.calls) == 2
    assert runner.calls[1] == [
        "az", "deployment", "group", "create",
        "--resource-group", "daily-rg",
        "--parameters", str(parameters),
        "--query", "properties.outputs", "--output", "json",
    ]
    assert "--template-file" not in runner.calls[1]
    assert not any(argument.startswith("@") for argument in runner.calls[1])
    assert set(result) == {
        "ok", "mode", "operation", "template_mode", "category",
        "resource_group_ready", "foundry_resource_created", "foundry_project_created",
        "model_deployment_created", "foundry_resource_name",
        "foundry_project_name", "project_endpoint", "model_deployment_name",
            "recommended_next_step",
            "change_evidence",
            "exact_topology_match",
        }
    assert result["foundry_resource_name"] == "private-account"
    assert result["foundry_project_name"] == "private-project"
    assert result["model_deployment_name"] == "private-deployment"
    rendered = json.dumps(result)
    for forbidden in ("stderr", "private-value", "subscription", "tenant", "resourceId", "deploy_foundry_agent.py --live"):
        assert forbidden not in rendered


def test_internal_live_reuse_skips_duplicate_resource_group_creation(
    monkeypatch: pytest.MonkeyPatch,
    files: tuple[Path, Path, Path],
) -> None:
    parameters = _paths(monkeypatch, files)
    runner = FakeRunner(
        [script.CommandResult(0, _deployment_output(), "sensitive deployment stderr")]
    )

    result = script.execute(
        script.DeploymentRequest(
            "live", "foundry-only", parameters, "daily-rg", "eastus2"
        ),
        runner,
        ensure_resource_group=False,
    )

    assert result["ok"] is True
    assert len(runner.calls) == 1
    assert runner.calls[0][:4] == ["az", "deployment", "group", "create"]


def test_live_rejects_authoritative_output_for_a_different_foundry_identity(
    monkeypatch: pytest.MonkeyPatch,
    files: tuple[Path, Path, Path],
) -> None:
    parameters = _paths(monkeypatch, files)
    wrong_output = json.loads(_deployment_output())
    wrong_output["foundryResourceName"]["value"] = "different-account"

    result = script.execute(
        script.DeploymentRequest(
            "live", "foundry-only", parameters, "daily-rg", "eastus2"
        ),
        FakeRunner(
            [script.CommandResult(0, json.dumps(wrong_output), "private stderr")]
        ),
        ensure_resource_group=False,
    )

    assert result["ok"] is False
    assert result["category"] == "foundry_deployment_identity_mismatch"
    assert result["foundry_resource_name"] is None
    assert "different-account" not in json.dumps(result)
    assert "private stderr" not in json.dumps(result)


@pytest.mark.parametrize(
    ("deployment_request", "runner", "category"),
    [
        (script.DeploymentRequest("check", "invalid", Path("missing"), "rg", "loc"), FakeRunner(), "missing_configuration"),
        (script.DeploymentRequest("check", "foundry-only", Path("missing"), "rg", "loc"), FakeRunner(), "missing_configuration"),
    ],
)
def test_configuration_failures_are_sanitized(deployment_request, runner, category) -> None:
    result = script.execute(deployment_request, runner)
    assert result["category"] == category


def test_cli_unavailable_and_build_failure_are_categorized(
    monkeypatch: pytest.MonkeyPatch,
    files: tuple[Path, Path, Path],
) -> None:
    parameters = _paths(monkeypatch, files)
    unavailable = FakeRunner([script.CommandResult(127, "", "secret")])
    assert script.execute(script.DeploymentRequest("check", "foundry-only", parameters, "rg", "loc"), unavailable)["category"] == "cli_unavailable"
    build_failure = FakeRunner([
        script.CommandResult(0, "{}", ""), script.CommandResult(0, "version", ""), script.CommandResult(1, "", "secret")
    ])
    assert script.execute(script.DeploymentRequest("check", "foundry-only", parameters, "rg", "loc"), build_failure)["category"] == "template_invalid"


def test_check_parameter_build_failure_is_categorized(
    monkeypatch: pytest.MonkeyPatch,
    files: tuple[Path, Path, Path],
) -> None:
    parameters = _paths(monkeypatch, files)
    runner = FakeRunner(
        [
            script.CommandResult(0, "{}", ""),
            script.CommandResult(0, "version", ""),
            script.CommandResult(0, "{}", ""),
            script.CommandResult(1, "", "private compiler detail"),
        ]
    )

    result = script.execute(
        script.DeploymentRequest("check", "foundry-only", parameters, "rg", "loc"),
        runner,
    )

    assert result["category"] == "parameter_file_invalid"
    assert "private compiler detail" not in json.dumps(result)


@pytest.mark.parametrize(
    ("template_mode", "using_target"),
    [("foundry-only", "./main.bicep"), ("full-stack", "./foundry-only.bicep")],
)
def test_parameter_using_target_must_match_selected_mode(
    monkeypatch: pytest.MonkeyPatch,
    files: tuple[Path, Path, Path],
    template_mode: str,
    using_target: str,
) -> None:
    parameters = _paths(monkeypatch, files)
    parameter_text = parameters.read_text().replace(
        "using './foundry-only.bicep'", f"using '{using_target}'"
    )
    if template_mode == "full-stack":
        parameter_text += "param deployFoundry = true\n"
    parameters.write_text(parameter_text)

    result = script.execute(
        script.DeploymentRequest("check", template_mode, parameters, "rg", "loc"),
        FakeRunner(),
    )

    assert result["category"] == "parameter_file_invalid"
    assert result["ok"] is False


@pytest.mark.parametrize(
    ("results", "category"),
    [
        ([script.CommandResult(1, "", "AuthorizationFailed")], "authentication_or_authorization_failed"),
        ([script.CommandResult(1, "", "other")], "resource_group_creation_failed"),
        ([script.CommandResult(0, "{}", ""), script.CommandResult(1, "", "other")], "deployment_failed"),
        ([script.CommandResult(0, "{}", ""), script.CommandResult(0, "not-json", "")], "deployment_output_invalid"),
        ([script.CommandResult(0, "{}", ""), script.CommandResult(0, "{}", "")], "deployment_output_invalid"),
    ],
)
def test_live_failures_are_sanitized(
    monkeypatch: pytest.MonkeyPatch,
    files: tuple[Path, Path, Path],
    results: list[script.CommandResult],
    category: str,
) -> None:
    parameters = _paths(monkeypatch, files)
    result = script.execute(
        script.DeploymentRequest("live", "foundry-only", parameters, "rg", "loc"),
        FakeRunner(results),
    )
    assert result["category"] == category
    assert "stderr" not in json.dumps(result)


def test_main_defaults_to_foundry_only_and_emits_one_json(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    parameters = tmp_path / "params.bicepparam"
    parameters.write_text("param modelName = 'fictional'\n")
    captured: list[script.DeploymentRequest] = []
    monkeypatch.setattr(script, "execute", lambda request, runner=None: captured.append(request) or {"ok": True})
    assert script.main(["--parameters", str(parameters), "--resource-group", "rg", "--location", "loc", "--live", "--json"]) == 0
    assert captured[0].template_mode == "foundry-only"
    assert json.loads(capsys.readouterr().out) == {"ok": True}
