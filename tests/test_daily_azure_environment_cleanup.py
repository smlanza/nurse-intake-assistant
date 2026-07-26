import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.app.services.daily_azure_environment_cleanup import (
    CleanupCommandResult,
    CleanupPurpose,
    DailyAzureEnvironmentCleanup,
    VerifiedAzureAccount,
    _RESOURCE_GROUP_DELETE_RECONCILIATION_POLICY,
)
from src.app.services.daily_azure_environment_rebuild import (
    RESOURCE_GROUP_PURPOSE,
    load_daily_azure_config,
)


SUBSCRIPTION_ID = "00000000-0000-0000-0000-000000000001"
TENANT_ID = "00000000-0000-0000-0000-000000000002"
CONFIG = {
    "AZURE_SUBSCRIPTION_NAME": "Fictional Development",
    "AZURE_LOCATION": "eastus2",
    "AZURE_RESOURCE_GROUP": "fictional-daily-rg",
    "AZURE_ENVIRONMENT_NAME": "daily",
    "AZURE_PROJECT_NAME": "nurse-intake",
    "AZURE_FOUNDRY_ACCOUNT_NAME": "fictional-intake-foundry",
    "AZURE_FOUNDRY_PROJECT_NAME": "fictional-intake-project",
    "AZURE_FOUNDRY_MODEL_DEPLOYMENT_NAME": "nurse-intake-gpt-5-mini",
    "AZURE_FOUNDRY_MODEL_NAME": "gpt-5-mini",
    "AZURE_FOUNDRY_MODEL_VERSION": "2025-08-07",
    "AZURE_FOUNDRY_MODEL_SKU": "GlobalStandard",
    "AZURE_FOUNDRY_MODEL_CAPACITY": "1",
    "AZURE_FOUNDRY_AGENT_NAME": "nurse-intake-agent",
    "AZURE_WEB_APP_NAME": "fictional-nurse-intake-web",
    "AZURE_WEB_APP_SKU": "B1",
    "ENABLE_HOSTED_FOUNDRY_VERIFIER": "true",
    "DISCOVER_HOSTED_FOUNDRY_WEBJOB": "true",
}


def _config(tmp_path: Path):
    (tmp_path / ".gitignore").write_text(".env.*\n")
    path = tmp_path / ".env.daily-azure.local"
    path.write_text("".join(f"{key}={value}\n" for key, value in CONFIG.items()))
    return load_daily_azure_config(
        path,
        repository_root=tmp_path,
        repository_state_checker=lambda _root, _path: True,
    )


class ScriptedRunner:
    def __init__(self, outcomes: list[CleanupCommandResult]) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[list[str]] = []

    def run(self, args: list[str]) -> CleanupCommandResult:
        self.calls.append(args)
        if not self.outcomes:
            raise AssertionError(f"Unexpected command: {args}")
        return self.outcomes.pop(0)


class FakeCleanupClock:
    def __init__(self) -> None:
        self.elapsed_seconds = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.elapsed_seconds

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.elapsed_seconds += seconds


def _ok(payload: object) -> CleanupCommandResult:
    return CleanupCommandResult(0, json.dumps(payload), "")


def _account() -> CleanupCommandResult:
    return _ok(
        {
            "id": SUBSCRIPTION_ID,
            "tenantId": TENANT_ID,
            "subscription": CONFIG["AZURE_SUBSCRIPTION_NAME"],
            "state": "Enabled",
            "isDefault": True,
        }
    )


def _verified_account() -> VerifiedAzureAccount:
    return VerifiedAzureAccount(
        subscription_id=SUBSCRIPTION_ID,
        tenant_id=TENANT_ID,
        subscription_name=CONFIG["AZURE_SUBSCRIPTION_NAME"],
    )


def _group(
    *,
    location: str = "eastus2",
    state: str = "Succeeded",
    tag: object = RESOURCE_GROUP_PURPOSE,
) -> dict[str, object]:
    return {
        "id": (
            f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/"
            f"{CONFIG['AZURE_RESOURCE_GROUP']}"
        ),
        "name": CONFIG["AZURE_RESOURCE_GROUP"],
        "location": location,
        "provisioningState": state,
        "ownershipTag": tag,
    }


def _active(
    name: str = "fictional-intake-foundry",
    *,
    resource_group: str = "fictional-daily-rg",
    location: str = "eastus2",
) -> dict[str, object]:
    return {
        "id": (
            f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/{resource_group}/"
            f"providers/Microsoft.CognitiveServices/accounts/{name}"
        ),
        "name": name,
        "resourceGroup": resource_group,
        "location": location,
        "kind": "AIServices",
        "type": "Microsoft.CognitiveServices/accounts",
    }


def _deleted(
    name: str = "fictional-intake-foundry",
    *,
    resource_group: str = "fictional-daily-rg",
    location: str = "eastus2",
    subscription_id: str = SUBSCRIPTION_ID,
) -> dict[str, object]:
    return {
        "id": (
            f"/subscriptions/{subscription_id}/providers/"
            f"Microsoft.CognitiveServices/locations/{location}/resourceGroups/"
            f"{resource_group}/deletedAccounts/{name}"
        ),
        "name": name,
        "resourceGroup": resource_group,
        "location": location,
        "subscriptionId": subscription_id,
        "kind": "AIServices",
        "type": "Microsoft.CognitiveServices/accounts",
    }


def _azure_deleted(
    name: str = "fictional-intake-foundry",
    **identity: str,
) -> dict[str, object]:
    record = _deleted(name, **identity)
    record["resourceGroup"] = None
    record["subscriptionId"] = None
    record["type"] = None
    return record


def _inspection(
    *,
    group: dict[str, object] | None = None,
    active: list[dict[str, object]] | None = None,
    deleted: list[dict[str, object]] | None = None,
    include_account: bool = True,
) -> list[CleanupCommandResult]:
    outcomes = [_account()] if include_account else []
    outcomes.append(CleanupCommandResult(0, "true\n" if group else "false\n", ""))
    if group:
        outcomes.append(_ok(group))
    outcomes.extend((_ok(active or []), _ok(deleted or [])))
    return outcomes


def _service(
    tmp_path: Path,
    runner: ScriptedRunner,
    *,
    monotonic_clock=None,
    sleeper=None,
) -> DailyAzureEnvironmentCleanup:
    return DailyAzureEnvironmentCleanup(
        _config(tmp_path),
        repository_root=tmp_path,
        runner_factory=lambda: runner,
        local_contract_checker=lambda _root: (),
        monotonic_clock=monotonic_clock,
        sleeper=sleeper,
    )


def test_check_is_offline_and_does_not_construct_runner(tmp_path: Path) -> None:
    service = DailyAzureEnvironmentCleanup(
        _config(tmp_path),
        repository_root=tmp_path,
        runner_factory=lambda: pytest.fail("check constructed a live runner"),
        local_contract_checker=lambda _root: (),
    )

    result = service.check()

    assert result.ok is True
    assert result.category == "local_contract_valid"
    assert result.account_verified is False
    assert result.azure_mutation_made is False


def test_absent_group_and_no_tombstones_is_already_clean(tmp_path: Path) -> None:
    runner = ScriptedRunner(_inspection())

    result = _service(tmp_path, runner).inspect(CleanupPurpose.END_OF_DAY)

    assert result.ok is True
    assert result.category == "already_clean"
    assert result.daily_environment_clean is True
    assert result.resource_group_absent is True
    assert result.foundry_tombstones_absent is True
    assert all("delete" not in call and "purge" not in call for call in runner.calls)


def test_healthy_owned_group_is_reusable_only_at_startup(tmp_path: Path) -> None:
    startup_runner = ScriptedRunner(
        _inspection(
            group=_group(),
            active=[_active()],
            include_account=False,
        )
    )
    startup = _service(tmp_path, startup_runner).startup_preflight(
        startup_runner,
        _verified_account(),
        approver=lambda _summary: pytest.fail("healthy state prompted"),
    )
    end_runner = ScriptedRunner(
        _inspection(group=_group(), active=[_active()])
    )
    end = _service(tmp_path, end_runner).inspect(CleanupPurpose.END_OF_DAY)

    assert startup.category == "healthy_environment_reusable"
    assert startup.cleanup_required is False
    assert startup.daily_environment_clean is True
    assert end.category == "cleanup_required"
    assert end.cleanup_required is True
    assert end.resource_group_deletion_required is True


@pytest.mark.parametrize(
    ("group", "category"),
    [
        (_group(tag="different-purpose"), "resource_group_not_owned"),
        (_group(tag=None), "resource_group_not_owned"),
        (_group(location="westus2"), "resource_group_not_owned"),
        (
            {
                "name": CONFIG["AZURE_RESOURCE_GROUP"],
                "location": "eastus2",
                "provisioningState": "Failed",
                "ownershipTag": RESOURCE_GROUP_PURPOSE,
            },
            "cleanup_inspection_failed",
        ),
        (_group(state="Unknown"), "manual_cleanup_required"),
    ],
)
def test_group_ownership_and_shape_fail_closed(
    tmp_path: Path,
    group: dict[str, object],
    category: str,
) -> None:
    runner = ScriptedRunner(_inspection(group=group))

    result = _service(tmp_path, runner).inspect(CleanupPurpose.END_OF_DAY)

    assert result.ok is False
    assert result.category == category
    assert result.manual_review_required is True
    assert result.azure_mutation_made is False


def test_matching_deleted_accounts_are_bounded_and_unrelated_are_ignored(
    tmp_path: Path,
) -> None:
    matching_generated = _deleted("fictional-intake-foundry-aa0001")
    runner = ScriptedRunner(
        _inspection(
            deleted=[
                _deleted(),
                matching_generated,
                _deleted("fictional-intake-foundry-similar"),
                _deleted(resource_group="unrelated-rg"),
                _deleted(
                    subscription_id=(
                        "00000000-0000-0000-0000-000000000099"
                    )
                ),
            ]
        )
    )

    result = _service(tmp_path, runner).inspect(CleanupPurpose.END_OF_DAY)

    assert result.ok is True
    assert result.category == "cleanup_required"
    assert result.soft_deleted_foundry_account_count == 2
    assert result.foundry_purge_required is True


@pytest.mark.parametrize(
    "name",
    [
        "fictional-intake-foundry",
        "fictional-intake-foundry-aa0001",
    ],
)
def test_canonical_deleted_id_supplies_null_resource_group_identity(
    tmp_path: Path,
    name: str,
) -> None:
    runner = ScriptedRunner(_inspection(deleted=[_azure_deleted(name)]))

    result = _service(tmp_path, runner).inspect(CleanupPurpose.END_OF_DAY)

    assert result.ok is True
    assert result.category == "cleanup_required"
    assert result.soft_deleted_foundry_account_count == 1
    assert result.foundry_purge_required is True


def test_multiple_canonical_null_group_tombstones_share_one_cleanup_plan(
    tmp_path: Path,
) -> None:
    runner = ScriptedRunner(
        _inspection(
            deleted=[
                _azure_deleted(),
                _azure_deleted("fictional-intake-foundry-aa0001"),
            ]
        )
    )

    result = _service(tmp_path, runner).inspect(CleanupPurpose.END_OF_DAY)

    assert result.ok is True
    assert result.soft_deleted_foundry_account_count == 2
    assert result.foundry_purge_required is True


@pytest.mark.parametrize(
    "record",
    [
        _azure_deleted(resource_group="unrelated-rg"),
        _azure_deleted(location="westus2"),
        _azure_deleted(
            subscription_id="00000000-0000-0000-0000-000000000099"
        ),
    ],
)
def test_canonical_deleted_id_outside_configured_scope_is_not_selected(
    tmp_path: Path,
    record: dict[str, object],
) -> None:
    runner = ScriptedRunner(_inspection(deleted=[record]))

    result = _service(tmp_path, runner).inspect(CleanupPurpose.END_OF_DAY)

    assert result.ok is True
    assert result.category == "already_clean"
    assert result.soft_deleted_foundry_account_count == 0
    assert result.foundry_purge_required is False


@pytest.mark.parametrize(
    "record",
    [
        {
            **_azure_deleted(),
            "id": _azure_deleted()["id"].replace(
                "Microsoft.CognitiveServices",
                "Microsoft.Web",
            ),
        },
        {
            **_azure_deleted(),
            "id": _azure_deleted()["id"].replace(
                "/deletedAccounts/",
                "/accounts/",
            ),
        },
        {
            **_azure_deleted(),
            "id": _azure_deleted()["id"].replace(
                "/fictional-intake-foundry",
                "/fictional-intake-foundry-aa0001",
            ),
        },
        {**_azure_deleted(), "resourceGroup": "conflicting-rg"},
        {**_azure_deleted(), "location": "westus2"},
        {
            **_azure_deleted(),
            "subscriptionId": (
                "00000000-0000-0000-0000-000000000099"
            ),
        },
        {**_azure_deleted(), "kind": "CognitiveServices"},
        {**_azure_deleted(), "id": None},
        {**_azure_deleted(), "id": "not-an-arm-id"},
        {
            **_azure_deleted(),
            "id": (
                f"/subscriptions/{SUBSCRIPTION_ID}/subscriptions/"
                f"{SUBSCRIPTION_ID}/providers/Microsoft.CognitiveServices/"
                "locations/eastus2/resourceGroups/fictional-daily-rg/"
                "deletedAccounts/fictional-intake-foundry"
            ),
        },
    ],
)
def test_apparent_owned_deleted_account_with_ambiguous_id_fails_closed(
    tmp_path: Path,
    record: dict[str, object],
) -> None:
    runner = ScriptedRunner(_inspection(deleted=[record]))

    result = _service(tmp_path, runner).inspect(CleanupPurpose.END_OF_DAY)

    assert result.ok is False
    assert result.category == "deleted_foundry_account_ambiguous"
    assert result.manual_review_required is True
    assert result.azure_mutation_made is False


def test_similar_name_only_canonical_deleted_account_is_ignored(
    tmp_path: Path,
) -> None:
    runner = ScriptedRunner(
        _inspection(
            deleted=[_azure_deleted("fictional-intake-foundry-similar")]
        )
    )

    result = _service(tmp_path, runner).inspect(CleanupPurpose.END_OF_DAY)

    assert result.ok is True
    assert result.category == "already_clean"
    assert result.soft_deleted_foundry_account_count == 0


@pytest.mark.parametrize(
    "record",
    [
        {**_deleted(), "kind": None},
        {**_deleted(), "type": "Microsoft.Web/sites"},
        {**_deleted(), "resourceGroup": "conflicting-rg"},
    ],
)
def test_malformed_apparent_deleted_account_fails_closed(
    tmp_path: Path,
    record: dict[str, object],
) -> None:
    runner = ScriptedRunner(_inspection(deleted=[record]))

    result = _service(tmp_path, runner).inspect(CleanupPurpose.END_OF_DAY)

    assert result.ok is False
    assert result.category == "deleted_foundry_account_ambiguous"
    assert result.manual_review_required is True


def test_active_exact_name_outside_owned_group_blocks_mutation(
    tmp_path: Path,
) -> None:
    runner = ScriptedRunner(
        _inspection(active=[_active(resource_group="unrelated-rg")])
    )

    result = _service(tmp_path, runner).cleanup(
        CleanupPurpose.END_OF_DAY,
        runner=runner,
        approver=lambda _summary: pytest.fail("conflict prompted"),
    )

    assert (
        result.category
        == "active_foundry_name_conflict_requires_manual_review"
    )
    assert result.active_name_conflict_found is True
    assert result.azure_mutation_made is False


@pytest.mark.parametrize("approved", [False, None])
def test_cleanup_never_mutates_without_explicit_approval(
    tmp_path: Path,
    approved: object,
) -> None:
    runner = ScriptedRunner(_inspection(group=_group(), active=[_active()]))
    approvals = []

    result = _service(tmp_path, runner).cleanup(
        CleanupPurpose.END_OF_DAY,
        runner=runner,
        approver=lambda summary: approvals.append(summary) or approved,
    )

    assert result.category == "cleanup_approval_declined"
    assert result.cleanup_attempted is False
    assert result.azure_mutation_made is False
    assert len(approvals) == 1
    assert all("delete" not in call and "purge" not in call for call in runner.calls)


def test_changed_evidence_invalidates_one_use_approval(tmp_path: Path) -> None:
    runner = ScriptedRunner(
        _inspection(group=_group(), active=[_active()])
        + _inspection(
            group=_group(state="Failed"),
            active=[_active(), _active("fictional-intake-foundry-aa0001")],
            include_account=False,
        )
    )

    result = _service(tmp_path, runner).cleanup(
        CleanupPurpose.END_OF_DAY,
        runner=runner,
        approver=lambda _summary: True,
    )

    assert result.category == "cleanup_evidence_changed"
    assert result.cleanup_approved is True
    assert result.cleanup_attempted is False
    assert all("delete" not in call and "purge" not in call for call in runner.calls)


def test_cleanup_deletes_then_purges_and_verifies_absence(tmp_path: Path) -> None:
    runner = ScriptedRunner(
        _inspection(
            group=_group(state="Failed"),
            active=[_active()],
            deleted=[_deleted("fictional-intake-foundry-aa0001")],
        )
        + _inspection(
            group=_group(state="Failed"),
            active=[_active()],
            deleted=[_deleted("fictional-intake-foundry-aa0001")],
            include_account=False,
        )
        + [
            CleanupCommandResult(0, "", ""),  # synchronous group delete
            CleanupCommandResult(0, "false\n", ""),  # group absence
            _ok([]),  # no active accounts
            _ok([_deleted(), _deleted("fictional-intake-foundry-aa0001")]),
            CleanupCommandResult(0, "", ""),
            CleanupCommandResult(0, "", ""),
            CleanupCommandResult(0, "false\n", ""),
            _ok([]),
            _ok([]),
        ]
    )

    result = _service(tmp_path, runner).cleanup(
        CleanupPurpose.END_OF_DAY,
        runner=runner,
        approver=lambda _summary: True,
    )

    assert result.ok is True
    assert result.category == "cleanup_completed"
    assert result.resource_group_absent is True
    assert result.foundry_tombstones_absent is True
    assert result.daily_environment_clean is True
    assert result.azure_mutation_made is True
    delete_index = next(
        index
        for index, call in enumerate(runner.calls)
        if call[:3] == ["az", "group", "delete"]
    )
    purge_indexes = [
        index
        for index, call in enumerate(runner.calls)
        if call[:4] == ["az", "cognitiveservices", "account", "purge"]
    ]
    assert purge_indexes and delete_index < min(purge_indexes)
    delete_call = runner.calls[delete_index]
    assert "--no-wait" not in delete_call
    assert delete_call[delete_call.index("--name") + 1] == CONFIG[
        "AZURE_RESOURCE_GROUP"
    ]
    for index in purge_indexes:
        call = runner.calls[index]
        assert call[call.index("--resource-group") + 1] == CONFIG[
            "AZURE_RESOURCE_GROUP"
        ]
        assert call[call.index("--location") + 1] == CONFIG["AZURE_LOCATION"]


def test_timed_out_group_delete_reconciles_twenty_minutes_then_completes(
    tmp_path: Path,
) -> None:
    clock = FakeCleanupClock()
    tombstone = _deleted("fictional-intake-foundry-aa0001")
    runner = ScriptedRunner(
        _inspection(
            group=_group(state="Failed"),
            active=[_active()],
            deleted=[tombstone],
        )
        + _inspection(
            group=_group(state="Failed"),
            active=[_active()],
            deleted=[tombstone],
            include_account=False,
        )
        + [
            SimpleNamespace(
                return_code=124,
                stdout="",
                stderr="",
                timed_out=True,
            ),
            *[
                outcome
                for _ in range(40)
                for outcome in (
                    CleanupCommandResult(0, "true\n", ""),
                    _ok(_group(state="Deleting")),
                )
            ],
            CleanupCommandResult(0, "false\n", ""),
            _ok([]),
            _ok([tombstone]),
            CleanupCommandResult(0, "", ""),
            CleanupCommandResult(0, "false\n", ""),
            _ok([]),
            _ok([]),
        ]
    )

    result = _service(
        tmp_path,
        runner,
        monotonic_clock=clock.monotonic,
        sleeper=clock.sleep,
    ).cleanup(
        CleanupPurpose.END_OF_DAY,
        runner=runner,
        approver=lambda _summary: True,
    )

    assert result.ok is True
    assert result.category == "cleanup_completed"
    assert result.resource_group_delete_attempted is True
    assert result.resource_group_absent is True
    assert result.foundry_purge_attempted is True
    assert result.foundry_tombstones_absent is True
    assert result.daily_environment_clean is True
    assert result.azure_mutation_made is True
    assert clock.elapsed_seconds == pytest.approx(1_200.0)
    assert len(clock.sleeps) == 40
    delete_calls = [
        call for call in runner.calls
        if call[:3] == ["az", "group", "delete"]
    ]
    assert len(delete_calls) == 1
    purge_index = next(
        index
        for index, call in enumerate(runner.calls)
        if call[:4] == ["az", "cognitiveservices", "account", "purge"]
    )
    assert sum(
        call[:3] == ["az", "group", "exists"]
        for call in runner.calls[:purge_index]
    ) == 43


def test_end_of_day_cleanup_purges_null_group_tombstones_and_verifies_absence(
    tmp_path: Path,
) -> None:
    generated = _azure_deleted("fictional-intake-foundry-aa0001")
    runner = ScriptedRunner(
        _inspection(
            group=_group(state="Failed"),
            active=[_active()],
            deleted=[generated],
        )
        + _inspection(
            group=_group(state="Failed"),
            active=[_active()],
            deleted=[generated],
            include_account=False,
        )
        + [
            CleanupCommandResult(0, "", ""),
            CleanupCommandResult(0, "false\n", ""),
            _ok([]),
            _ok([_azure_deleted(), generated]),
            CleanupCommandResult(0, "", ""),
            CleanupCommandResult(0, "", ""),
            CleanupCommandResult(0, "false\n", ""),
            _ok([]),
            _ok([]),
        ]
    )

    result = _service(tmp_path, runner).cleanup(
        CleanupPurpose.END_OF_DAY,
        runner=runner,
        approver=lambda _summary: True,
    )

    assert result.ok is True
    assert result.category == "cleanup_completed"
    assert result.resource_group_absent is True
    assert result.foundry_tombstones_absent is True
    assert result.daily_environment_clean is True
    purge_calls = [
        call
        for call in runner.calls
        if call[:4] == ["az", "cognitiveservices", "account", "purge"]
    ]
    assert len(purge_calls) == 2
    assert {
        call[call.index("--name") + 1]
        for call in purge_calls
    } == {
        "fictional-intake-foundry",
        "fictional-intake-foundry-aa0001",
    }
    assert all(
        call[call.index("--resource-group") + 1]
        == CONFIG["AZURE_RESOURCE_GROUP"]
        for call in purge_calls
    )


def test_startup_purges_blocker_without_deleting_healthy_owned_group(
    tmp_path: Path,
) -> None:
    inspected = _inspection(
        group=_group(),
        active=[_active()],
        deleted=[_deleted("fictional-intake-foundry-aa0001")],
        include_account=False,
    )
    runner = ScriptedRunner(
        inspected
        + inspected
        + [
            _ok([_active()]),
            _ok([_deleted("fictional-intake-foundry-aa0001")]),
            CleanupCommandResult(0, "", ""),
            CleanupCommandResult(0, "true\n", ""),
            _ok(_group()),
            _ok([_active()]),
            _ok([]),
        ]
    )

    result = _service(tmp_path, runner).startup_preflight(
        runner,
        _verified_account(),
        approver=lambda _summary: True,
    )

    assert result.ok is True
    assert result.category == "cleanup_completed"
    assert result.resource_group_deletion_required is False
    assert result.resource_group_delete_attempted is False
    assert result.resource_group_absent is False
    assert result.foundry_tombstones_absent is True
    assert result.daily_environment_clean is True
    assert not any(
        call[:3] == ["az", "group", "delete"] for call in runner.calls
    )
    assert sum("purge" in call for call in runner.calls) == 1


def test_startup_cleanup_purges_null_group_tombstone_and_returns_clean_proof(
    tmp_path: Path,
) -> None:
    tombstone = _azure_deleted("fictional-intake-foundry-aa0001")
    inspected = _inspection(
        group=_group(),
        active=[_active()],
        deleted=[tombstone],
        include_account=False,
    )
    runner = ScriptedRunner(
        inspected
        + inspected
        + [
            _ok([_active()]),
            _ok([tombstone]),
            CleanupCommandResult(0, "", ""),
            CleanupCommandResult(0, "true\n", ""),
            _ok(_group()),
            _ok([_active()]),
            _ok([]),
        ]
    )

    result = _service(tmp_path, runner).startup_preflight(
        runner,
        _verified_account(),
        approver=lambda _summary: True,
    )

    assert result.ok is True
    assert result.category == "cleanup_completed"
    assert result.cleanup_approved is True
    assert result.foundry_purge_attempted is True
    assert result.foundry_tombstones_absent is True
    assert result.daily_environment_clean is True
    assert sum("purge" in call for call in runner.calls) == 1


def test_group_delete_failure_stops_before_purge(tmp_path: Path) -> None:
    runner = ScriptedRunner(
        _inspection(group=_group(state="Failed"), active=[_active()])
        + _inspection(
            group=_group(state="Failed"),
            active=[_active()],
            include_account=False,
        )
        + [CleanupCommandResult(1, "", "private failure")]
    )

    result = _service(tmp_path, runner).cleanup(
        CleanupPurpose.END_OF_DAY,
        runner=runner,
        approver=lambda _summary: True,
    )

    assert result.category == "resource_group_delete_failed"
    assert result.azure_mutation_made is None
    assert not any("purge" in call for call in runner.calls)
    assert "private failure" not in json.dumps(result.to_json_dict())


def test_group_delete_process_not_started_is_conclusive_no_mutation(
    tmp_path: Path,
) -> None:
    runner = ScriptedRunner(
        _inspection(group=_group(state="Failed"), active=[_active()])
        + _inspection(
            group=_group(state="Failed"),
            active=[_active()],
            include_account=False,
        )
        + [CleanupCommandResult(127, "", "private")]
    )

    result = _service(tmp_path, runner).cleanup(
        CleanupPurpose.END_OF_DAY,
        runner=runner,
        approver=lambda _summary: True,
    )

    assert result.category == "resource_group_delete_failed"
    assert result.resource_group_delete_attempted is True
    assert result.azure_mutation_made is False
    assert sum(
        call[:3] == ["az", "group", "delete"]
        for call in runner.calls
    ) == 1
    assert not any("purge" in call for call in runner.calls)


def test_accepted_group_delete_requires_separate_absence_proof(
    tmp_path: Path,
) -> None:
    policy = _RESOURCE_GROUP_DELETE_RECONCILIATION_POLICY
    clock = FakeCleanupClock()
    initial = _inspection(group=_group(state="Failed"), active=[_active()])
    runner = ScriptedRunner(
        initial
        + _inspection(
            group=_group(state="Failed"),
            active=[_active()],
            include_account=False,
        )
        + [
            CleanupCommandResult(0, "", ""),
            *[
                outcome
                for _ in range(policy.max_attempts)
                for outcome in (
                    CleanupCommandResult(0, "true\n", ""),
                    _ok(_group(state="Deleting")),
                )
            ],
        ]
    )

    result = _service(
        tmp_path,
        runner,
        monotonic_clock=clock.monotonic,
        sleeper=clock.sleep,
    ).cleanup(
        CleanupPurpose.END_OF_DAY,
        runner=runner,
        approver=lambda _summary: True,
    )

    assert result.category == "resource_group_still_present"
    assert result.resource_group_delete_attempted is True
    assert result.resource_group_absent is False
    assert result.foundry_purge_attempted is False
    assert result.daily_environment_clean is False
    assert result.azure_mutation_made is True
    assert clock.elapsed_seconds == pytest.approx(
        policy.max_elapsed_seconds
    )
    assert len(clock.sleeps) == policy.max_attempts - 1
    assert "rerun" in result.next_step.casefold()
    assert sum(
        call[:3] == ["az", "group", "delete"]
        for call in runner.calls
    ) == 1
    assert not any("purge" in call for call in runner.calls)


def test_purge_failure_is_sanitized_and_not_retried(tmp_path: Path) -> None:
    initial = _inspection(deleted=[_deleted()])
    runner = ScriptedRunner(
        initial
        + _inspection(deleted=[_deleted()], include_account=False)
        + [_ok([]), _ok([_deleted()]), CleanupCommandResult(1, "", "private")]
    )

    result = _service(tmp_path, runner).cleanup(
        CleanupPurpose.END_OF_DAY,
        runner=runner,
        approver=lambda _summary: True,
    )

    assert result.category == "foundry_purge_failed"
    assert result.foundry_purge_attempted is True
    assert result.azure_mutation_made is None
    assert sum("purge" in call for call in runner.calls) == 1
    assert "private" not in json.dumps(result.to_json_dict())


def test_remaining_tombstone_after_purge_fails_final_verification(
    tmp_path: Path,
) -> None:
    initial = _inspection(deleted=[_deleted()])
    runner = ScriptedRunner(
        initial
        + _inspection(deleted=[_deleted()], include_account=False)
        + [
            _ok([]),
            _ok([_deleted()]),
            CleanupCommandResult(0, "", ""),
            CleanupCommandResult(0, "false\n", ""),
            _ok([]),
            _ok([_deleted()]),
        ]
    )

    result = _service(tmp_path, runner).cleanup(
        CleanupPurpose.END_OF_DAY,
        runner=runner,
        approver=lambda _summary: True,
    )

    assert result.category == "foundry_tombstone_still_present"
    assert result.daily_environment_clean is False
    assert result.azure_mutation_made is True


@pytest.mark.parametrize(
    "outcome",
    [
        CleanupCommandResult(0, "", ""),
        CleanupCommandResult(0, "maybe\n", ""),
        CleanupCommandResult(1, "false\n", "private"),
    ],
)
def test_empty_unknown_or_nonzero_group_output_never_proves_absence(
    tmp_path: Path,
    outcome: CleanupCommandResult,
) -> None:
    runner = ScriptedRunner([_account(), outcome])

    result = _service(tmp_path, runner).inspect(CleanupPurpose.END_OF_DAY)

    assert result.ok is False
    assert result.category == "cleanup_inspection_failed"
    assert result.daily_environment_clean is False


def test_cleanup_implementation_has_only_bounded_foreground_reconciliation() -> None:
    source = Path(
        DailyAzureEnvironmentCleanup.__module__.replace(".", "/") + ".py"
    )
    repository_source = (
        Path(__file__).resolve().parents[1]
        / source
    ).read_text()

    assert "asyncio" not in repository_source
    assert "Thread" not in repository_source
    assert "--no-wait" not in repository_source
    assert "while True" not in repository_source


def test_serialized_result_contains_only_sanitized_bounded_facts(
    tmp_path: Path,
) -> None:
    runner = ScriptedRunner(
        _inspection(
            group=_group(),
            active=[_active()],
            deleted=[
                _azure_deleted(),
                _azure_deleted("fictional-intake-foundry-aa0001"),
            ],
        )
    )

    payload = _service(tmp_path, runner).inspect(
        CleanupPurpose.END_OF_DAY
    ).to_json_dict()
    serialized = json.dumps(payload)

    for forbidden in (
        CONFIG["AZURE_RESOURCE_GROUP"],
        CONFIG["AZURE_FOUNDRY_ACCOUNT_NAME"],
        "fictional-intake-foundry-aa0001",
        CONFIG["AZURE_LOCATION"],
        SUBSCRIPTION_ID,
        TENANT_ID,
        "/subscriptions/",
        "command",
        "stdout",
        "stderr",
        "exception",
    ):
        assert forbidden not in serialized
