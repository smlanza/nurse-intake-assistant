from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
import re
import time
from typing import Callable, Protocol
from uuid import UUID

from src.app.services.daily_azure_environment_rebuild import (
    RESOURCE_GROUP_PURPOSE,
    DailyAzureConfig,
    _foundry_account_candidate_matches_base,
    validate_local_orchestration_contract,
)


CLEANUP_OPERATION = "cleanup_daily_azure_environment"
_SUPPORTED_FOUNDRY_KINDS = frozenset({"AIServices", "OpenAI"})
_SPEECH_KIND = "SpeechServices"
_SPEECH_NAME_PATTERN = re.compile(r"nurse-intake-speech-[0-9]{8}")
_SPEECH_PURPOSE = "nurse-intake-speech"
_SPEECH_ENVIRONMENT = "capstone"
_COGNITIVE_ACCOUNT_TYPE = "Microsoft.CognitiveServices/accounts"
_COGNITIVE_DELETED_ACCOUNT_TYPE = (
    "Microsoft.CognitiveServices/deletedAccounts"
)
_REUSABLE_RESOURCE_GROUP_STATE = "Succeeded"
_STALE_RESOURCE_GROUP_STATES = frozenset({"Canceled", "Deleting", "Failed"})


@dataclass(frozen=True)
class _ResourceGroupDeleteReconciliationPolicy:
    max_attempts: int
    max_elapsed_seconds: float
    backoff_seconds: float


_RESOURCE_GROUP_DELETE_RECONCILIATION_POLICY = (
    _ResourceGroupDeleteReconciliationPolicy(
        max_attempts=61,
        max_elapsed_seconds=1_800.0,
        backoff_seconds=30.0,
    )
)


class CleanupPurpose(str, Enum):
    STARTUP_PREFLIGHT = "startup_preflight"
    END_OF_DAY = "end_of_day"


@dataclass(frozen=True)
class CleanupCommandResult:
    return_code: int
    stdout: str
    stderr: str
    timed_out: bool = False


class CleanupCommandRunner(Protocol):
    def run(self, args: list[str]) -> CleanupCommandResult: ...


@dataclass(frozen=True, repr=False)
class VerifiedAzureAccount:
    subscription_id: str
    tenant_id: str
    subscription_name: str


@dataclass(frozen=True)
class CleanupApprovalSummary:
    purpose: CleanupPurpose
    owned_resource_group_present: bool
    resource_group_deletion_required: bool
    soft_deleted_foundry_account_count: int
    foundry_purge_required: bool
    healthy_reusable_environment: bool
    soft_deleted_speech_account_count: int = 0
    speech_purge_required: bool = False

    @property
    def manual_review_required(self) -> bool:
        return False

    @property
    def destructive_changes(self) -> bool:
        return (
            self.resource_group_deletion_required
            or self.foundry_purge_required
            or self.speech_purge_required
        )


@dataclass(frozen=True)
class CleanupResult:
    ok: bool
    category: str
    purpose: str
    account_verified: bool = False
    inspection_completed: bool = False
    cleanup_required: bool = False
    cleanup_approved: bool = False
    cleanup_attempted: bool = False
    resource_group_present: bool = False
    resource_group_owned: bool = False
    resource_group_deletion_required: bool = False
    resource_group_delete_attempted: bool = False
    resource_group_absent: bool = False
    soft_deleted_foundry_accounts_found: bool = False
    soft_deleted_foundry_account_count: int = 0
    foundry_purge_required: bool = False
    foundry_purge_attempted: bool = False
    foundry_tombstones_absent: bool = False
    speech_tombstones_absent: bool = False
    soft_deleted_speech_account_count: int = 0
    soft_deleted_speech_accounts_found: bool = False
    speech_purge_required: bool = False
    speech_purge_attempted: bool = False
    active_name_conflict_found: bool = False
    manual_review_required: bool = False
    daily_environment_clean: bool = False
    azure_mutation_made: bool | None = False
    next_step: str = (
        "Review the sanitized category and rerun only through an explicit new command."
    )

    @classmethod
    def local_contract_valid(cls) -> "CleanupResult":
        return cls(
            ok=True,
            category="local_contract_valid",
            purpose="local_check",
            next_step="Run an explicit live inspection before cleanup.",
        )

    @classmethod
    def already_clean(
        cls,
        purpose: CleanupPurpose,
        *,
        account_verified: bool = True,
    ) -> "CleanupResult":
        return cls(
            ok=True,
            category="already_clean",
            purpose=purpose.value,
            account_verified=account_verified,
            inspection_completed=True,
            resource_group_absent=True,
            foundry_tombstones_absent=True,
            speech_tombstones_absent=True,
            daily_environment_clean=True,
            next_step="No cleanup action is required.",
        )

    @classmethod
    def cleanup_completed(cls, purpose: CleanupPurpose) -> "CleanupResult":
        return cls(
            ok=True,
            category="cleanup_completed",
            purpose=purpose.value,
            account_verified=True,
            inspection_completed=True,
            cleanup_required=True,
            cleanup_approved=True,
            cleanup_attempted=True,
            resource_group_owned=True,
            resource_group_deletion_required=True,
            resource_group_delete_attempted=True,
            resource_group_absent=True,
            foundry_purge_required=True,
            foundry_purge_attempted=True,
            foundry_tombstones_absent=True,
            speech_tombstones_absent=True,
            speech_purge_required=True,
            speech_purge_attempted=True,
            daily_environment_clean=True,
            azure_mutation_made=True,
            next_step="The approved cleanup completed and final state was verified.",
        )

    def to_json_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "category": self.category,
            "operation": CLEANUP_OPERATION,
            "purpose": self.purpose,
            "account_verified": self.account_verified,
            "inspection_completed": self.inspection_completed,
            "cleanup_required": self.cleanup_required,
            "cleanup_approved": self.cleanup_approved,
            "cleanup_attempted": self.cleanup_attempted,
            "resource_group_present": self.resource_group_present,
            "resource_group_owned": self.resource_group_owned,
            "resource_group_deletion_required": (
                self.resource_group_deletion_required
            ),
            "resource_group_delete_attempted": (
                self.resource_group_delete_attempted
            ),
            "resource_group_absent": self.resource_group_absent,
            "soft_deleted_foundry_accounts_found": (
                self.soft_deleted_foundry_accounts_found
            ),
            "soft_deleted_foundry_account_count": (
                self.soft_deleted_foundry_account_count
            ),
            "foundry_purge_required": self.foundry_purge_required,
            "foundry_purge_attempted": self.foundry_purge_attempted,
            "foundry_tombstones_absent": self.foundry_tombstones_absent,
            "speech_tombstones_absent": self.speech_tombstones_absent,
            "soft_deleted_speech_account_count": (
                self.soft_deleted_speech_account_count
            ),
            "soft_deleted_speech_accounts_found": (
                self.soft_deleted_speech_accounts_found
            ),
            "speech_purge_required": self.speech_purge_required,
            "speech_purge_attempted": self.speech_purge_attempted,
            "active_name_conflict_found": self.active_name_conflict_found,
            "manual_review_required": self.manual_review_required,
            "daily_environment_clean": self.daily_environment_clean,
            "azure_mutation_made": self.azure_mutation_made,
            "next_step": self.next_step,
        }


@dataclass(frozen=True, repr=False)
class _ResourceGroupEvidence:
    resource_id: str
    name: str
    location: str
    provisioning_state: str
    ownership_tag: str


@dataclass(frozen=True, repr=False)
class _FoundryAccountEvidence:
    resource_id: str
    name: str
    resource_group: str
    location: str
    subscription_id: str
    kind: str
    resource_type: str


@dataclass(frozen=True, repr=False)
class _SpeechAccountEvidence:
    resource_id: str
    name: str
    resource_group: str
    location: str
    subscription_id: str
    kind: str
    resource_type: str
    purpose_tag: str | None
    environment_tag: str | None


@dataclass(frozen=True, repr=False)
class _CleanupPlan:
    purpose: CleanupPurpose
    account: VerifiedAzureAccount
    resource_group: _ResourceGroupEvidence | None
    delete_resource_group: bool
    active_owned_accounts: tuple[_FoundryAccountEvidence, ...]
    deleted_accounts: tuple[_FoundryAccountEvidence, ...]
    deleted_speech_accounts: tuple[_SpeechAccountEvidence, ...]

    @property
    def resource_group_deletion_required(self) -> bool:
        return self.delete_resource_group

    @property
    def foundry_purge_required(self) -> bool:
        return bool(self.deleted_accounts or self.active_owned_accounts)

    @property
    def speech_purge_required(self) -> bool:
        return bool(self.deleted_speech_accounts)

    @property
    def approved_account_names(self) -> frozenset[str]:
        return frozenset(
            evidence.name
            for evidence in (
                *self.active_owned_accounts,
                *self.deleted_accounts,
            )
        )

    @property
    def approved_speech_account_names(self) -> frozenset[str]:
        return frozenset(
            evidence.name for evidence in self.deleted_speech_accounts
        )


@dataclass(frozen=True, repr=False)
class _Inspection:
    result: CleanupResult
    plan: _CleanupPlan | None = None


class _ApprovalSession:
    def __init__(
        self,
        *,
        environment_binding: str,
        approver: Callable[[CleanupApprovalSummary], bool] | None,
    ) -> None:
        self._nonce = os.urandom(32)
        self._binding = hashlib.sha256(environment_binding.encode()).digest()
        self._approver = approver
        self._used = False
        self._consumed: bytes | None = None

    def request(
        self,
        summary: CleanupApprovalSummary,
        plan: _CleanupPlan,
    ) -> bool:
        fingerprint = hashlib.sha256(
            self._nonce
            + self._binding
            + _private_plan_binding(plan)
            + repr(summary).encode()
        ).digest()
        if (
            self._used
            or self._approver is None
            or self._consumed == fingerprint
        ):
            return False
        self._used = True
        try:
            approved = self._approver(summary) is True
        except (EOFError, KeyboardInterrupt, OSError, TimeoutError):
            return False
        if approved:
            self._consumed = fingerprint
        return approved


class DailyAzureEnvironmentCleanup:
    def __init__(
        self,
        config: DailyAzureConfig,
        *,
        repository_root: Path,
        runner_factory: Callable[[], CleanupCommandRunner] | None = None,
        local_contract_checker: Callable[[Path], tuple[str, ...]] = (
            validate_local_orchestration_contract
        ),
        monotonic_clock: Callable[[], float] | None = None,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        self.config = config
        self.repository_root = repository_root
        self.runner_factory = runner_factory
        self.local_contract_checker = local_contract_checker
        self.monotonic_clock = monotonic_clock or time.monotonic
        self.sleeper = sleeper or time.sleep

    def check(self) -> CleanupResult:
        try:
            failures = self.local_contract_checker(self.repository_root)
        except Exception:
            failures = ("local_contract_invalid",)
        if failures:
            return CleanupResult(
                ok=False,
                category="local_contract_invalid",
                purpose="local_check",
            )
        return CleanupResult.local_contract_valid()

    def inspect(
        self,
        purpose: CleanupPurpose,
        *,
        runner: CleanupCommandRunner | None = None,
    ) -> CleanupResult:
        live_runner = self._runner(runner)
        if live_runner is None:
            return self._failure(purpose, "runner_unavailable")
        account = self._verify_account(live_runner)
        if account is None:
            return self._failure(
                purpose,
                "account_verification_failed",
            )
        return self._inspect(live_runner, purpose, account).result

    def startup_preflight(
        self,
        runner: CleanupCommandRunner,
        account: VerifiedAzureAccount,
        *,
        approver: Callable[[CleanupApprovalSummary], bool] | None,
    ) -> CleanupResult:
        if not self._account_matches_config(account):
            return self._failure(
                CleanupPurpose.STARTUP_PREFLIGHT,
                "account_verification_failed",
            )
        return self._cleanup_with_verified_account(
            CleanupPurpose.STARTUP_PREFLIGHT,
            runner,
            account,
            approver,
        )

    def cleanup(
        self,
        purpose: CleanupPurpose,
        *,
        runner: CleanupCommandRunner | None = None,
        approver: Callable[[CleanupApprovalSummary], bool] | None,
    ) -> CleanupResult:
        live_runner = self._runner(runner)
        if live_runner is None:
            return self._failure(purpose, "runner_unavailable")
        account = self._verify_account(live_runner)
        if account is None:
            return self._failure(purpose, "account_verification_failed")
        return self._cleanup_with_verified_account(
            purpose,
            live_runner,
            account,
            approver,
        )

    def _runner(
        self,
        runner: CleanupCommandRunner | None,
    ) -> CleanupCommandRunner | None:
        if runner is not None:
            return runner
        if self.runner_factory is None:
            return None
        try:
            return self.runner_factory()
        except Exception:
            return None

    def _verify_account(
        self,
        runner: CleanupCommandRunner,
    ) -> VerifiedAzureAccount | None:
        outcome = runner.run(
            [
                "az",
                "account",
                "show",
                "--query",
                (
                    "{id:id,tenantId:tenantId,subscription:name,"
                    "state:state,isDefault:isDefault}"
                ),
                "--output",
                "json",
                "--only-show-errors",
            ]
        )
        payload = _json_object(outcome) if outcome.return_code == 0 else None
        if (
            payload is None
            or set(payload)
            != {"id", "tenantId", "subscription", "state", "isDefault"}
            or not _uuid_string(payload.get("id"))
            or not _uuid_string(payload.get("tenantId"))
            or payload.get("subscription") != self.config.subscription_name
            or payload.get("state") != "Enabled"
            or payload.get("isDefault") is not True
        ):
            return None
        return VerifiedAzureAccount(
            subscription_id=str(payload["id"]),
            tenant_id=str(payload["tenantId"]),
            subscription_name=str(payload["subscription"]),
        )

    def _account_matches_config(self, account: VerifiedAzureAccount) -> bool:
        return bool(
            _uuid_string(account.subscription_id)
            and _uuid_string(account.tenant_id)
            and account.subscription_name == self.config.subscription_name
        )

    def _inspect(
        self,
        runner: CleanupCommandRunner,
        purpose: CleanupPurpose,
        account: VerifiedAzureAccount,
    ) -> _Inspection:
        group, group_category = self._inspect_resource_group(runner, account)
        if group_category is not None:
            return _Inspection(
                self._failure(
                    purpose,
                    group_category,
                    account_verified=True,
                    inspection_completed=True,
                    resource_group_present=group_category
                    not in {"cleanup_inspection_failed"},
                    manual_review_required=True,
                )
            )
        accounts = self._inspect_accounts(runner, account)
        if isinstance(accounts, str):
            return _Inspection(
                self._failure(
                    purpose,
                    accounts,
                    account_verified=True,
                    inspection_completed=True,
                    resource_group_present=group is not None,
                    resource_group_owned=group is not None,
                    manual_review_required=True,
                    active_name_conflict_found=(
                        accounts
                        == "active_foundry_name_conflict_requires_manual_review"
                    ),
                )
            )
        active_owned, deleted, deleted_speech = accounts
        plan = _CleanupPlan(
            purpose=purpose,
            account=account,
            resource_group=group,
            delete_resource_group=bool(
                group is not None
                and (
                    purpose is CleanupPurpose.END_OF_DAY
                    or group.provisioning_state
                    in _STALE_RESOURCE_GROUP_STATES
                )
            ),
            active_owned_accounts=active_owned,
            deleted_accounts=deleted,
            deleted_speech_accounts=deleted_speech,
        )
        if group is None and active_owned:
            return _Inspection(
                self._failure(
                    purpose,
                    "cleanup_inspection_failed",
                    account_verified=True,
                    inspection_completed=True,
                    manual_review_required=True,
                )
            )
        reusable = bool(
            group is not None
            and group.provisioning_state == _REUSABLE_RESOURCE_GROUP_STATE
            and not deleted
            and not deleted_speech
        )
        if (
            group is not None
            and group.provisioning_state
            not in {
                _REUSABLE_RESOURCE_GROUP_STATE,
                *_STALE_RESOURCE_GROUP_STATES,
            }
        ):
            return _Inspection(
                self._failure(
                    purpose,
                    "manual_cleanup_required",
                    account_verified=True,
                    inspection_completed=True,
                    resource_group_present=True,
                    resource_group_owned=True,
                    manual_review_required=True,
                )
            )
        cleanup_required = bool(
            deleted
            or deleted_speech
            or (
                group is not None
                and (
                    purpose is CleanupPurpose.END_OF_DAY
                    or group.provisioning_state
                    in _STALE_RESOURCE_GROUP_STATES
                )
            )
        )
        if not cleanup_required:
            if reusable:
                return _Inspection(
                    CleanupResult(
                        ok=True,
                        category="healthy_environment_reusable",
                        purpose=purpose.value,
                        account_verified=True,
                        inspection_completed=True,
                        resource_group_present=True,
                        resource_group_owned=True,
                        resource_group_absent=False,
                        foundry_tombstones_absent=True,
                        speech_tombstones_absent=True,
                        daily_environment_clean=False,
                        next_step=(
                            "Continue through the verified environment reuse path."
                        ),
                    ),
                    plan,
                )
            return _Inspection(
                CleanupResult.already_clean(purpose),
                plan,
            )
        result = CleanupResult(
            ok=True,
            category="cleanup_required",
            purpose=purpose.value,
            account_verified=True,
            inspection_completed=True,
            cleanup_required=True,
            resource_group_present=group is not None,
            resource_group_owned=group is not None,
            resource_group_deletion_required=(
                plan.resource_group_deletion_required
            ),
            resource_group_absent=group is None,
            soft_deleted_foundry_accounts_found=bool(deleted),
            soft_deleted_foundry_account_count=len(deleted),
            foundry_purge_required=plan.foundry_purge_required,
            foundry_tombstones_absent=not deleted,
            speech_tombstones_absent=not deleted_speech,
            soft_deleted_speech_account_count=len(deleted_speech),
            soft_deleted_speech_accounts_found=bool(deleted_speech),
            speech_purge_required=plan.speech_purge_required,
            next_step=(
                "Review the current sanitized cleanup summary; approval defaults to no."
            ),
        )
        return _Inspection(result, plan)

    def _cleanup_with_verified_account(
        self,
        purpose: CleanupPurpose,
        runner: CleanupCommandRunner,
        account: VerifiedAzureAccount,
        approver: Callable[[CleanupApprovalSummary], bool] | None,
    ) -> CleanupResult:
        inspection = self._inspect(runner, purpose, account)
        if not inspection.result.ok or not inspection.result.cleanup_required:
            return inspection.result
        assert inspection.plan is not None
        plan = inspection.plan
        summary = CleanupApprovalSummary(
            purpose=purpose,
            owned_resource_group_present=plan.resource_group is not None,
            resource_group_deletion_required=(
                plan.resource_group_deletion_required
            ),
            soft_deleted_foundry_account_count=len(plan.deleted_accounts),
            foundry_purge_required=plan.foundry_purge_required,
            healthy_reusable_environment=False,
            soft_deleted_speech_account_count=(
                len(plan.deleted_speech_accounts)
            ),
            speech_purge_required=plan.speech_purge_required,
        )
        approvals = _ApprovalSession(
            environment_binding=self._environment_binding(),
            approver=approver,
        )
        if not approvals.request(summary, plan):
            return replace(
                inspection.result,
                ok=False,
                category="cleanup_approval_declined",
                cleanup_approved=False,
                next_step="No mutation occurred; rerun for a fresh inspection.",
            )
        fresh = self._inspect(runner, purpose, account)
        if (
            not fresh.result.ok
            or fresh.plan is None
            or fresh.plan != plan
        ):
            return replace(
                inspection.result,
                ok=False,
                category="cleanup_evidence_changed",
                cleanup_approved=True,
                next_step="Evidence changed; rerun for a new approval.",
            )
        mutation_made: bool | None = False
        delete_attempted = False
        if plan.resource_group_deletion_required:
            assert plan.resource_group is not None
            delete_attempted = True
            deleted = runner.run(
                [
                    "az",
                    "group",
                    "delete",
                    "--name",
                    plan.resource_group.name,
                    "--yes",
                    "--only-show-errors",
                ]
            )
            delete_timed_out = bool(
                getattr(deleted, "timed_out", False)
            )
            if deleted.return_code != 0 and not delete_timed_out:
                return replace(
                    inspection.result,
                    ok=False,
                    category="resource_group_delete_failed",
                    cleanup_approved=True,
                    cleanup_attempted=True,
                    resource_group_delete_attempted=True,
                    azure_mutation_made=(
                        False if deleted.return_code == 127 else None
                    ),
                )
            mutation_made = None if delete_timed_out else True
            group_absent, group_category = (
                self._reconcile_resource_group_absence(
                    runner,
                    account,
                )
            )
            if group_category is not None:
                return replace(
                    inspection.result,
                    ok=False,
                    category="cleanup_inspection_failed",
                    cleanup_approved=True,
                    cleanup_attempted=True,
                    resource_group_delete_attempted=True,
                    azure_mutation_made=mutation_made,
                )
            if not group_absent:
                return replace(
                    inspection.result,
                    ok=False,
                    category="resource_group_still_present",
                    cleanup_approved=True,
                    cleanup_attempted=True,
                    resource_group_delete_attempted=True,
                    azure_mutation_made=mutation_made,
                    next_step=(
                        "Inspect the exact resource group later; rerun cleanup "
                        "only through a fresh explicit command."
                    ),
                )
            mutation_made = True
        post_accounts = self._inspect_accounts(runner, account)
        if isinstance(post_accounts, str):
            return replace(
                inspection.result,
                ok=False,
                category=post_accounts,
                cleanup_approved=True,
                cleanup_attempted=delete_attempted,
                resource_group_delete_attempted=delete_attempted,
                azure_mutation_made=mutation_made,
            )
        active_after, deleted_after, deleted_speech_after = post_accounts
        if (
            plan.resource_group_deletion_required
            and active_after
        ):
            return replace(
                inspection.result,
                ok=False,
                category="resource_group_still_present",
                cleanup_approved=True,
                cleanup_attempted=delete_attempted,
                resource_group_delete_attempted=delete_attempted,
                azure_mutation_made=mutation_made,
            )
        if (
            not plan.resource_group_deletion_required
            and active_after != plan.active_owned_accounts
        ):
            return replace(
                inspection.result,
                ok=False,
                category="cleanup_evidence_changed",
                cleanup_approved=True,
                cleanup_attempted=False,
                azure_mutation_made=mutation_made,
            )
        if any(
            evidence.name not in plan.approved_account_names
            for evidence in deleted_after
        ):
            return replace(
                inspection.result,
                ok=False,
                category="cleanup_evidence_changed",
                cleanup_approved=True,
                cleanup_attempted=delete_attempted,
                resource_group_delete_attempted=delete_attempted,
                azure_mutation_made=mutation_made,
            )
        if any(
            evidence.name not in plan.approved_speech_account_names
            for evidence in deleted_speech_after
        ):
            return replace(
                inspection.result,
                ok=False,
                category="cleanup_evidence_changed",
                cleanup_approved=True,
                cleanup_attempted=delete_attempted,
                resource_group_delete_attempted=delete_attempted,
                azure_mutation_made=mutation_made,
            )
        foundry_purge_attempted = False
        for evidence in sorted(deleted_after, key=lambda item: item.name):
            foundry_purge_attempted = True
            purged = runner.run(
                [
                    "az",
                    "cognitiveservices",
                    "account",
                    "purge",
                    "--name",
                    evidence.name,
                    "--resource-group",
                    evidence.resource_group,
                    "--location",
                    evidence.location,
                    "--only-show-errors",
                ]
            )
            if purged.return_code != 0:
                return replace(
                    inspection.result,
                    ok=False,
                    category="foundry_purge_failed",
                    cleanup_approved=True,
                    cleanup_attempted=True,
                    resource_group_delete_attempted=delete_attempted,
                    foundry_purge_attempted=True,
                    azure_mutation_made=None,
                )
            mutation_made = True
        speech_purge_attempted = False
        for evidence in sorted(
            deleted_speech_after,
            key=lambda item: item.name,
        ):
            speech_purge_attempted = True
            purged = runner.run(
                [
                    "az",
                    "cognitiveservices",
                    "account",
                    "purge",
                    "--name",
                    evidence.name,
                    "--resource-group",
                    evidence.resource_group,
                    "--location",
                    evidence.location,
                    "--only-show-errors",
                ]
            )
            if (
                not isinstance(purged, CleanupCommandResult)
                or type(purged.return_code) is not int
                or purged.return_code != 0
                or not isinstance(purged.stdout, str)
                or not isinstance(purged.stderr, str)
                or type(purged.timed_out) is not bool
                or purged.timed_out
            ):
                return replace(
                    inspection.result,
                    ok=False,
                    category="speech_purge_failed",
                    cleanup_approved=True,
                    cleanup_attempted=True,
                    resource_group_delete_attempted=delete_attempted,
                    foundry_purge_attempted=foundry_purge_attempted,
                    speech_purge_attempted=True,
                    azure_mutation_made=None,
                )
            mutation_made = True
        final = self._inspect(runner, purpose, account)
        if not final.result.ok:
            return replace(
                inspection.result,
                ok=False,
                category=final.result.category,
                cleanup_approved=True,
                cleanup_attempted=True,
                resource_group_delete_attempted=delete_attempted,
                foundry_purge_attempted=foundry_purge_attempted,
                speech_purge_attempted=speech_purge_attempted,
                azure_mutation_made=mutation_made,
            )
        if (
            plan.resource_group_deletion_required
            and not final.result.resource_group_absent
        ):
            return replace(
                inspection.result,
                ok=False,
                category="resource_group_still_present",
                cleanup_approved=True,
                cleanup_attempted=True,
                resource_group_delete_attempted=delete_attempted,
                foundry_purge_attempted=foundry_purge_attempted,
                speech_purge_attempted=speech_purge_attempted,
                azure_mutation_made=mutation_made,
            )
        if not final.result.foundry_tombstones_absent:
            return replace(
                inspection.result,
                ok=False,
                category="foundry_tombstone_still_present",
                cleanup_approved=True,
                cleanup_attempted=True,
                resource_group_delete_attempted=delete_attempted,
                foundry_purge_attempted=foundry_purge_attempted,
                speech_purge_attempted=speech_purge_attempted,
                azure_mutation_made=mutation_made,
            )
        if not final.result.speech_tombstones_absent:
            return replace(
                inspection.result,
                ok=False,
                category="speech_tombstone_still_present",
                cleanup_approved=True,
                cleanup_attempted=True,
                resource_group_delete_attempted=delete_attempted,
                foundry_purge_attempted=foundry_purge_attempted,
                speech_purge_attempted=speech_purge_attempted,
                azure_mutation_made=mutation_made,
            )
        expected_final_category = (
            "healthy_environment_reusable"
            if plan.resource_group is not None
            and not plan.resource_group_deletion_required
            else "already_clean"
        )
        if final.result.category != expected_final_category:
            return replace(
                inspection.result,
                ok=False,
                category="cleanup_evidence_changed",
                cleanup_approved=True,
                cleanup_attempted=True,
                foundry_purge_attempted=foundry_purge_attempted,
                speech_purge_attempted=speech_purge_attempted,
                azure_mutation_made=mutation_made,
            )
        return CleanupResult(
            ok=True,
            category="cleanup_completed",
            purpose=purpose.value,
            account_verified=True,
            inspection_completed=True,
            cleanup_required=True,
            cleanup_approved=True,
            cleanup_attempted=True,
            resource_group_present=inspection.result.resource_group_present,
            resource_group_owned=inspection.result.resource_group_owned,
            resource_group_deletion_required=(
                inspection.result.resource_group_deletion_required
            ),
            resource_group_delete_attempted=delete_attempted,
            resource_group_absent=final.result.resource_group_absent,
            soft_deleted_foundry_accounts_found=(
                inspection.result.soft_deleted_foundry_accounts_found
            ),
            soft_deleted_foundry_account_count=(
                inspection.result.soft_deleted_foundry_account_count
            ),
            foundry_purge_required=inspection.result.foundry_purge_required,
            foundry_purge_attempted=foundry_purge_attempted,
            foundry_tombstones_absent=True,
            speech_tombstones_absent=True,
            soft_deleted_speech_account_count=(
                inspection.result.soft_deleted_speech_account_count
            ),
            soft_deleted_speech_accounts_found=(
                inspection.result.soft_deleted_speech_accounts_found
            ),
            speech_purge_required=inspection.result.speech_purge_required,
            speech_purge_attempted=speech_purge_attempted,
            daily_environment_clean=final.result.daily_environment_clean,
            azure_mutation_made=mutation_made,
            next_step="The approved cleanup completed and final state was verified.",
        )

    def _reconcile_resource_group_absence(
        self,
        runner: CleanupCommandRunner,
        account: VerifiedAzureAccount,
    ) -> tuple[bool, str | None]:
        policy = _RESOURCE_GROUP_DELETE_RECONCILIATION_POLICY
        reconciliation_started = self.monotonic_clock()
        for attempt in range(policy.max_attempts):
            group_after, group_category = self._inspect_resource_group(
                runner,
                account,
            )
            if group_category is not None:
                return False, group_category
            if group_after is None:
                return True, None
            if attempt + 1 >= policy.max_attempts:
                break
            elapsed = self.monotonic_clock() - reconciliation_started
            if elapsed + policy.backoff_seconds > policy.max_elapsed_seconds:
                break
            self.sleeper(policy.backoff_seconds)
        return False, None

    def _inspect_resource_group(
        self,
        runner: CleanupCommandRunner,
        account: VerifiedAzureAccount,
    ) -> tuple[_ResourceGroupEvidence | None, str | None]:
        exists = runner.run(
            [
                "az",
                "group",
                "exists",
                "--name",
                self.config.resource_group,
                "--output",
                "tsv",
                "--only-show-errors",
            ]
        )
        if exists.return_code != 0:
            return None, "cleanup_inspection_failed"
        normalized = exists.stdout.strip().casefold()
        if normalized == "false":
            return None, None
        if normalized != "true":
            return None, "cleanup_inspection_failed"
        shown = runner.run(
            [
                "az",
                "group",
                "show",
                "--name",
                self.config.resource_group,
                "--query",
                (
                    "{id:id,name:name,location:location,"
                    "provisioningState:properties.provisioningState,"
                    "ownershipTag:tags.purpose}"
                ),
                "--output",
                "json",
                "--only-show-errors",
            ]
        )
        payload = _json_object(shown) if shown.return_code == 0 else None
        expected_keys = {
            "id",
            "name",
            "location",
            "provisioningState",
            "ownershipTag",
        }
        if payload is None or set(payload) != expected_keys:
            return None, "cleanup_inspection_failed"
        evidence = _resource_group_evidence(payload, account)
        if evidence is None:
            return None, "resource_group_not_owned"
        if (
            evidence.name != self.config.resource_group
            or evidence.location != self.config.location
            or evidence.ownership_tag != RESOURCE_GROUP_PURPOSE
        ):
            return None, "resource_group_not_owned"
        return evidence, None

    def _inspect_accounts(
        self,
        runner: CleanupCommandRunner,
        account: VerifiedAzureAccount,
    ) -> tuple[
        tuple[_FoundryAccountEvidence, ...],
        tuple[_FoundryAccountEvidence, ...],
        tuple[_SpeechAccountEvidence, ...],
    ] | str:
        active_outcome = runner.run(
            [
                "az",
                "cognitiveservices",
                "account",
                "list",
                "--query",
                (
                    "[].{id:id,name:name,resourceGroup:resourceGroup,"
                    "location:location,kind:kind,type:type}"
                ),
                "--output",
                "json",
                "--only-show-errors",
            ]
        )
        deleted_outcome = runner.run(
            [
                "az",
                "cognitiveservices",
                "account",
                "list-deleted",
                "--query",
                (
                    "[].{id:id,name:name,resourceGroup:resourceGroup,"
                    "location:location,subscriptionId:subscriptionId,"
                    "kind:kind,type:type,tags:tags}"
                ),
                "--output",
                "json",
                "--only-show-errors",
            ]
        )
        active_payload = (
            _json_list(active_outcome)
            if active_outcome.return_code == 0
            else None
        )
        deleted_payload = (
            _json_list(deleted_outcome)
            if deleted_outcome.return_code == 0
            else None
        )
        if active_payload is None or deleted_payload is None:
            return "cleanup_inspection_failed"
        active = self._select_active_accounts(active_payload, account)
        if isinstance(active, str):
            return active
        deleted = self._select_deleted_accounts(deleted_payload, account)
        if isinstance(deleted, str):
            return deleted
        deleted_foundry, deleted_speech = deleted
        return active, deleted_foundry, deleted_speech

    def _select_active_accounts(
        self,
        records: list[object],
        account: VerifiedAzureAccount,
    ) -> tuple[_FoundryAccountEvidence, ...] | str:
        selected: list[_FoundryAccountEvidence] = []
        for record in records:
            if not isinstance(record, dict):
                return "cleanup_inspection_failed"
            name = record.get("name")
            if not isinstance(name, str) or not name:
                return "cleanup_inspection_failed"
            if not self._daily_foundry_name(name):
                continue
            evidence = _active_account_evidence(record, account)
            if evidence is None:
                return "cleanup_inspection_failed"
            if evidence.resource_group != self.config.resource_group:
                return (
                    "active_foundry_name_conflict_requires_manual_review"
                )
            if evidence.location != self.config.location:
                return "cleanup_inspection_failed"
            selected.append(evidence)
        if _duplicate_account_evidence(selected):
            return "cleanup_inspection_failed"
        return tuple(sorted(selected, key=lambda item: item.name))

    def _select_deleted_accounts(
        self,
        records: list[object],
        account: VerifiedAzureAccount,
    ) -> tuple[
        tuple[_FoundryAccountEvidence, ...],
        tuple[_SpeechAccountEvidence, ...],
    ] | str:
        selected_foundry: list[_FoundryAccountEvidence] = []
        selected_speech: list[_SpeechAccountEvidence] = []
        seen_speech_names: set[str] = set()
        for record in records:
            if not isinstance(record, dict):
                return "cleanup_inspection_failed"
            kind = record.get("kind")
            if kind == _SPEECH_KIND:
                evidence = _deleted_speech_account_evidence(record)
                if evidence is None:
                    return "deleted_speech_account_ambiguous"
                owned_speech = self._owned_speech_account(evidence, account)
                near_owned_speech = self._near_owned_speech_account(
                    evidence,
                    account,
                )
                if _speech_evidence_appears_owned(evidence):
                    if evidence.name in seen_speech_names:
                        return "deleted_speech_account_ambiguous"
                    seen_speech_names.add(evidence.name)
                if owned_speech:
                    selected_speech.append(evidence)
                elif near_owned_speech:
                    return "deleted_speech_account_ambiguous"
                continue
            if kind not in _SUPPORTED_FOUNDRY_KINDS:
                if _record_appears_speech_owned(record):
                    return "deleted_speech_account_ambiguous"
                name = record.get("name")
                if isinstance(name, str) and self._daily_foundry_name(name):
                    return "deleted_foundry_account_ambiguous"
                continue
            evidence = _deleted_account_evidence(record)
            if evidence is None:
                return "deleted_foundry_account_ambiguous"
            if self._daily_foundry_name(evidence.name) and (
                evidence.subscription_id.casefold()
                == account.subscription_id.casefold()
                and evidence.resource_group == self.config.resource_group
                and evidence.location == self.config.location
            ):
                selected_foundry.append(evidence)
        if _duplicate_account_evidence(selected_foundry):
            return "deleted_foundry_account_ambiguous"
        return (
            tuple(sorted(selected_foundry, key=lambda item: item.name)),
            tuple(sorted(selected_speech, key=lambda item: item.name)),
        )

    def _owned_speech_account(
        self,
        evidence: _SpeechAccountEvidence,
        account: VerifiedAzureAccount,
    ) -> bool:
        return bool(
            evidence.subscription_id.casefold()
            == account.subscription_id.casefold()
            and evidence.resource_group == self.config.resource_group
            and evidence.location == self.config.location
            and _SPEECH_NAME_PATTERN.fullmatch(evidence.name)
            and evidence.purpose_tag == _SPEECH_PURPOSE
            and evidence.environment_tag == _SPEECH_ENVIRONMENT
        )

    def _near_owned_speech_account(
        self,
        evidence: _SpeechAccountEvidence,
        account: VerifiedAzureAccount,
    ) -> bool:
        in_current_subscription = (
            evidence.subscription_id.casefold()
            == account.subscription_id.casefold()
        )
        configured_group = (
            evidence.resource_group == self.config.resource_group
        )
        matching_name = bool(_SPEECH_NAME_PATTERN.fullmatch(evidence.name))
        matching_tags = bool(
            evidence.purpose_tag == _SPEECH_PURPOSE
            and evidence.environment_tag == _SPEECH_ENVIRONMENT
        )
        return bool(
            in_current_subscription
            and configured_group
            and (matching_name or matching_tags)
        )

    def _daily_foundry_name(self, name: str) -> bool:
        return bool(
            name == self.config.configured_foundry_account_name
            or _foundry_account_candidate_matches_base(
                name,
                self.config.configured_foundry_account_name,
            )
        )

    def _environment_binding(self) -> str:
        return json.dumps(
            {
                "subscription_name": self.config.subscription_name,
                "location": self.config.location,
                "resource_group": self.config.resource_group,
                "ownership_tag": RESOURCE_GROUP_PURPOSE,
                "foundry_account_name": (
                    self.config.configured_foundry_account_name
                ),
                "speech_kind": _SPEECH_KIND,
                "speech_name_pattern": _SPEECH_NAME_PATTERN.pattern,
                "speech_purpose": _SPEECH_PURPOSE,
                "speech_environment": _SPEECH_ENVIRONMENT,
            },
            separators=(",", ":"),
            sort_keys=True,
        )

    @staticmethod
    def _failure(
        purpose: CleanupPurpose,
        category: str,
        **facts: object,
    ) -> CleanupResult:
        allowed = CleanupResult.__dataclass_fields__
        return CleanupResult(
            ok=False,
            category=category,
            purpose=purpose.value,
            **{key: value for key, value in facts.items() if key in allowed},
        )


def _json_object(outcome: CleanupCommandResult) -> dict[str, object] | None:
    if not isinstance(outcome.stdout, str) or not outcome.stdout.strip():
        return None
    try:
        payload = json.loads(outcome.stdout)
    except (TypeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _json_list(outcome: CleanupCommandResult) -> list[object] | None:
    if not isinstance(outcome.stdout, str) or not outcome.stdout.strip():
        return None
    try:
        payload = json.loads(outcome.stdout)
    except (TypeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, list) else None


def _uuid_string(value: object) -> bool:
    if not isinstance(value, str) or value != value.strip():
        return False
    try:
        return str(UUID(value)) == value.casefold()
    except ValueError:
        return False


def _resource_group_evidence(
    payload: dict[str, object],
    account: VerifiedAzureAccount,
) -> _ResourceGroupEvidence | None:
    values = tuple(payload.get(name) for name in (
        "id",
        "name",
        "location",
        "provisioningState",
        "ownershipTag",
    ))
    if not all(
        isinstance(value, str) and value and value == value.strip()
        for value in values
    ):
        return None
    resource_id, name, location, state, tag = (
        str(value) for value in values
    )
    parts = resource_id.split("/")
    if (
        len(parts) != 5
        or parts[0] != ""
        or parts[1].casefold() != "subscriptions"
        or parts[2].casefold() != account.subscription_id.casefold()
        or parts[3].casefold() != "resourcegroups"
        or parts[4] != name
    ):
        return None
    return _ResourceGroupEvidence(
        resource_id,
        name,
        location,
        state,
        tag,
    )


def _active_account_evidence(
    payload: dict[str, object],
    account: VerifiedAzureAccount,
) -> _FoundryAccountEvidence | None:
    expected = {"id", "name", "resourceGroup", "location", "kind", "type"}
    if set(payload) != expected:
        return None
    values = tuple(payload.get(name) for name in expected)
    if not all(
        isinstance(value, str) and value and value == value.strip()
        for value in values
    ):
        return None
    resource_id = str(payload["id"])
    name = str(payload["name"])
    group = str(payload["resourceGroup"])
    parts = resource_id.split("/")
    if (
        len(parts) != 9
        or parts[0] != ""
        or parts[1].casefold() != "subscriptions"
        or parts[2].casefold() != account.subscription_id.casefold()
        or parts[3].casefold() != "resourcegroups"
        or parts[4] != group
        or parts[5].casefold() != "providers"
        or parts[6].casefold() != "microsoft.cognitiveservices"
        or parts[7].casefold() != "accounts"
        or parts[8] != name
        or payload["kind"] not in _SUPPORTED_FOUNDRY_KINDS
        or payload["type"] != _COGNITIVE_ACCOUNT_TYPE
    ):
        return None
    return _FoundryAccountEvidence(
        resource_id=resource_id,
        name=name,
        resource_group=group,
        location=str(payload["location"]),
        subscription_id=account.subscription_id,
        kind=str(payload["kind"]),
        resource_type=str(payload["type"]),
    )


def _deleted_account_evidence(
    payload: dict[str, object],
) -> _FoundryAccountEvidence | None:
    projected_fields = {
        "id",
        "name",
        "resourceGroup",
        "location",
        "subscriptionId",
        "kind",
        "type",
        "tags",
    }
    if (
        not set(payload).issubset(projected_fields)
        or not {"id", "kind"}.issubset(payload)
    ):
        return None
    tags = payload.get("tags")
    if tags is not None and not isinstance(tags, dict):
        return None
    required_values = tuple(payload.get(field) for field in ("id", "kind"))
    optional_values = tuple(
        payload.get(field)
        for field in (
            "name",
            "resourceGroup",
            "location",
            "subscriptionId",
            "type",
        )
    )
    if not all(
        isinstance(value, str) and value and value == value.strip()
        for value in required_values
    ) or not all(
        value is None
        or (
            isinstance(value, str)
            and value
            and value == value.strip()
        )
        for value in optional_values
    ):
        return None
    resource_id = str(payload["id"])
    parts = resource_id.split("/")
    if (
        len(parts) != 11
        or parts[0] != ""
        or parts[1] != "subscriptions"
        or not _uuid_string(parts[2])
        or parts[3] != "providers"
        or parts[4] != "Microsoft.CognitiveServices"
        or parts[5] != "locations"
        or not parts[6]
        or parts[7] != "resourceGroups"
        or not parts[8]
        or parts[9] != "deletedAccounts"
        or not parts[10]
        or payload["kind"] not in _SUPPORTED_FOUNDRY_KINDS
    ):
        return None
    subscription_id = parts[2]
    location = parts[6]
    group = parts[8]
    name = parts[10]
    if (
        payload.get("name") is not None
        and payload["name"] != name
    ) or (
        payload.get("resourceGroup") is not None
        and payload["resourceGroup"] != group
    ) or (
        payload.get("location") is not None
        and payload["location"] != location
    ) or (
        payload.get("subscriptionId") is not None
        and (
            not _uuid_string(payload["subscriptionId"])
            or str(payload["subscriptionId"]).casefold()
            != subscription_id.casefold()
        )
    ) or (
        payload.get("type") is not None
        and payload["type"] != _COGNITIVE_DELETED_ACCOUNT_TYPE
    ):
        return None
    return _FoundryAccountEvidence(
        resource_id=resource_id,
        name=name,
        resource_group=group,
        location=location,
        subscription_id=subscription_id,
        kind=str(payload["kind"]),
        resource_type=_COGNITIVE_DELETED_ACCOUNT_TYPE,
    )


def _deleted_speech_account_evidence(
    payload: dict[str, object],
) -> _SpeechAccountEvidence | None:
    projected_fields = {
        "id",
        "name",
        "resourceGroup",
        "location",
        "subscriptionId",
        "kind",
        "type",
        "tags",
    }
    if (
        not set(payload).issubset(projected_fields)
        or not {"id", "kind"}.issubset(payload)
        or payload.get("kind") != _SPEECH_KIND
    ):
        return None
    required_values = (payload.get("id"), payload.get("kind"))
    optional_values = tuple(
        payload.get(field)
        for field in (
            "name",
            "resourceGroup",
            "location",
            "subscriptionId",
            "type",
        )
    )
    if not all(
        isinstance(value, str) and value and value == value.strip()
        for value in required_values
    ) or not all(
        value is None
        or (isinstance(value, str) and value and value == value.strip())
        for value in optional_values
    ):
        return None
    tags = payload.get("tags")
    if tags is not None and not isinstance(tags, dict):
        return None
    purpose_tag = tags.get("purpose") if isinstance(tags, dict) else None
    environment_tag = (
        tags.get("environment") if isinstance(tags, dict) else None
    )
    if (
        purpose_tag is not None and not isinstance(purpose_tag, str)
    ) or (
        environment_tag is not None
        and not isinstance(environment_tag, str)
    ):
        return None
    resource_id = str(payload["id"])
    parts = resource_id.split("/")
    if (
        len(parts) != 11
        or parts[0] != ""
        or parts[1] != "subscriptions"
        or not _uuid_string(parts[2])
        or parts[3] != "providers"
        or parts[4] != "Microsoft.CognitiveServices"
        or parts[5] != "locations"
        or not parts[6]
        or parts[7] != "resourceGroups"
        or not parts[8]
        or parts[9] != "deletedAccounts"
        or not parts[10]
    ):
        return None
    subscription_id = parts[2]
    location = parts[6]
    group = parts[8]
    name = parts[10]
    if (
        payload.get("name") is not None and payload["name"] != name
    ) or (
        payload.get("resourceGroup") is not None
        and payload["resourceGroup"] != group
    ) or (
        payload.get("location") is not None
        and payload["location"] != location
    ) or (
        payload.get("subscriptionId") is not None
        and (
            not _uuid_string(payload["subscriptionId"])
            or str(payload["subscriptionId"]).casefold()
            != subscription_id.casefold()
        )
    ) or (
        payload.get("type") is not None
        and payload["type"] != _COGNITIVE_DELETED_ACCOUNT_TYPE
    ):
        return None
    return _SpeechAccountEvidence(
        resource_id=resource_id,
        name=name,
        resource_group=group,
        location=location,
        subscription_id=subscription_id,
        kind=_SPEECH_KIND,
        resource_type=_COGNITIVE_DELETED_ACCOUNT_TYPE,
        purpose_tag=purpose_tag,
        environment_tag=environment_tag,
    )


def _record_appears_speech_owned(payload: dict[str, object]) -> bool:
    name = payload.get("name")
    tags = payload.get("tags")
    return bool(
        isinstance(name, str) and _SPEECH_NAME_PATTERN.fullmatch(name)
        or isinstance(tags, dict)
        and (
            tags.get("purpose") == _SPEECH_PURPOSE
            or tags.get("environment") == _SPEECH_ENVIRONMENT
        )
    )


def _speech_evidence_appears_owned(
    evidence: _SpeechAccountEvidence,
) -> bool:
    return bool(
        _SPEECH_NAME_PATTERN.fullmatch(evidence.name)
        or evidence.purpose_tag == _SPEECH_PURPOSE
        or evidence.environment_tag == _SPEECH_ENVIRONMENT
    )


def _duplicate_account_evidence(
    evidence: list[_FoundryAccountEvidence],
) -> bool:
    identities = {
        (item.resource_id.casefold(), item.name)
        for item in evidence
    }
    return len(identities) != len(evidence)


def _private_plan_binding(plan: _CleanupPlan) -> bytes:
    group = plan.resource_group
    payload = {
        "purpose": plan.purpose.value,
        "account": {
            "subscription_id": plan.account.subscription_id,
            "tenant_id": plan.account.tenant_id,
            "subscription_name": plan.account.subscription_name,
        },
        "resource_group": (
            None
            if group is None
            else {
                "resource_id": group.resource_id,
                "name": group.name,
                "location": group.location,
                "provisioning_state": group.provisioning_state,
                "ownership_tag": group.ownership_tag,
            }
        ),
        "delete_resource_group": plan.delete_resource_group,
        "active_owned_accounts": [
            _private_account_binding(account)
            for account in plan.active_owned_accounts
        ],
        "deleted_accounts": [
            _private_account_binding(account)
            for account in plan.deleted_accounts
        ],
        "deleted_speech_accounts": [
            _private_speech_account_binding(account)
            for account in plan.deleted_speech_accounts
        ],
    }
    return hashlib.sha256(
        json.dumps(
            payload,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).digest()


def _private_account_binding(
    account: _FoundryAccountEvidence,
) -> dict[str, str]:
    return {
        "resource_id": account.resource_id,
        "name": account.name,
        "resource_group": account.resource_group,
        "location": account.location,
        "subscription_id": account.subscription_id,
        "kind": account.kind,
        "resource_type": account.resource_type,
    }


def _private_speech_account_binding(
    account: _SpeechAccountEvidence,
) -> dict[str, str | None]:
    return {
        "resource_id": account.resource_id,
        "name": account.name,
        "resource_group": account.resource_group,
        "location": account.location,
        "subscription_id": account.subscription_id,
        "kind": account.kind,
        "resource_type": account.resource_type,
        "purpose_tag": account.purpose_tag,
        "environment_tag": account.environment_tag,
    }
