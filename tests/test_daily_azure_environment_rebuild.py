import json
import os
import inspect
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.app.services import daily_azure_environment_rebuild as daily_rebuild_service
from src.app.services import foundry_agent_consumer_rbac_deployment
from src.app.services import foundry_agent_consumer_rbac_verification
from src.app.services import hosted_foundry_agent_webjob_execution
from src.app.services import web_app_infra_deployment as web_app_deployment
from src.app.services.daily_azure_environment_rebuild import (
    ApprovalSummary,
    ChangeEvidence,
    ConsumerRbacPlan,
    ConsumerRbacPreviewProof,
    REBUILD_OPERATION,
    ConfigValidationError,
    DailyAzureEnvironmentRebuild,
    DailyAzureEnvironmentRebuildResult,
    DailyAzureRuntimeContext,
    GuidedPlanDiagnostic,
    PlanResult,
    RepositoryDailyAzureStageRunner,
    RuntimeUpdates,
    StageResult,
    _plan_from_mapping,
    load_daily_azure_config,
    safe_automatic_plan,
    safe_guided_plan,
    safe_web_app_plan,
    safe_web_app_reconciliation_plan,
    write_runtime_session_file,
)
from src.app.services.foundry_agent_consumer_rbac_deployment import (
    deterministic_role_assignment_name,
)


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
PACKAGE_DIGEST = "a" * 64


def _config_file(tmp_path: Path, values: dict[str, str] | None = None) -> Path:
    (tmp_path / ".gitignore").write_text(".env.*\n!.env.daily-azure.example\n")
    path = tmp_path / ".env.daily-azure.local"
    merged = CONFIG if values is None else values
    path.write_text("".join(f"{key}={value}\n" for key, value in merged.items()))
    return path


def _config(tmp_path: Path):
    return load_daily_azure_config(
        _config_file(tmp_path),
        repository_root=tmp_path,
        repository_state_checker=lambda _root, _path: True,
    )


def _package_source_tree(tmp_path: Path) -> Path:
    files = {
        "requirements.txt": "fastapi\nuvicorn[standard]\n",
        "src/__init__.py": "",
        "src/app/main.py": "app_name = 'fixture-app'\n",
        "src/app/config/settings.py": "APP_MODE = 'mock'\n",
        "src/app/config/red_flags.yaml": "rules: []\n",
        "src/app/static/demo.html": "<main>fixture demo</main>\n",
        "App_Data/jobs/triggered/verify-hosted-foundry-agent/run.py": (
            "from src.app.operations import verify_hosted_foundry_agent\n"
            "def run():\n"
            "    return verify_hosted_foundry_agent.main(['--live', '--json'])\n"
        ),
    }
    for relative_path, content in files.items():
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    return tmp_path


def test_daily_azure_environment_rebuild_boundary_exists() -> None:
    assert REBUILD_OPERATION == "rebuild_daily_azure_environment"


@pytest.mark.parametrize(
    ("change", "category"),
    [
        ({"AZURE_LOCATION": ""}, "invalid_configuration"),
        ({"AZURE_LOCATION": " eastus2"}, "invalid_configuration"),
        ({"AZURE_LOCATION": "East US 2"}, "invalid_configuration"),
        ({"AZURE_RESOURCE_GROUP": "<daily-resource-group-name>"}, "placeholder_value"),
        ({"AZURE_WEB_APP_NAME": "-invalid"}, "invalid_configuration"),
        ({"ENABLE_HOSTED_FOUNDRY_VERIFIER": "false"}, "incompatible_options"),
    ],
)
def test_configuration_rejects_unsafe_values(
    tmp_path: Path, change: dict[str, str], category: str
) -> None:
    values = {**CONFIG, **change}
    with pytest.raises(ConfigValidationError) as error:
        load_daily_azure_config(
            _config_file(tmp_path, values),
            repository_root=tmp_path,
            repository_state_checker=lambda _root, _path: True,
        )
    assert error.value.category == category


def test_configuration_can_disable_optional_webjob_discovery(tmp_path: Path) -> None:
    values = {**CONFIG, "DISCOVER_HOSTED_FOUNDRY_WEBJOB": "false"}

    config = load_daily_azure_config(
        _config_file(tmp_path, values),
        repository_root=tmp_path,
        repository_state_checker=lambda _root, _path: True,
    )

    assert config.discover_hosted_foundry_webjob is False


def test_verified_ready_does_not_require_optional_hosted_workflows() -> None:
    proofs = {
        "local_orchestration_ready": True,
        "account_verified": True,
        "resource_group_ready": True,
        "foundry_infrastructure_verified": True,
        "prompt_agent_verified": True,
        "immutable_routing_verified": True,
        "web_app_configuration_verified": True,
        "application_package_created": True,
        "application_artifact_current": True,
        "application_deployment_attempted": True,
        "application_deployment_accepted": True,
        "hosted_readiness_verified": True,
    }

    result = DailyAzureEnvironmentRebuildResult._verified_ready(
        proofs,
        azure_mutation_made=False,
    )

    assert result.daily_environment_ready is True
    assert result.consumer_rbac_verified is False
    assert result.webjob_discovered is False
    assert result.webjob_triggered is False
    assert result.webjob_status_read is False
    assert result.managed_identity_verification_performed is False
    assert result.agent_invoked is False


def test_configuration_rejects_missing_file_and_setting(tmp_path: Path) -> None:
    with pytest.raises(ConfigValidationError) as missing_file:
        load_daily_azure_config(
            tmp_path / ".env.daily-azure.local", repository_root=tmp_path
        )
    assert missing_file.value.category == "missing_configuration"

    values = dict(CONFIG)
    values.pop("AZURE_WEB_APP_NAME")
    with pytest.raises(ConfigValidationError) as missing_setting:
        load_daily_azure_config(
            _config_file(tmp_path, values),
            repository_root=tmp_path,
            repository_state_checker=lambda _root, _path: True,
        )
    assert missing_setting.value.category == "missing_configuration"


@pytest.mark.parametrize(
    "unsafe_key",
    [
        "AZURE_CLIENT_SECRET",
        "AZURE_SUBSCRIPTION_ID",
        "AZURE_TENANT_ID",
        "IDENTITY_HEADER",
        "CONNECTION_STRING",
        "AZURE_AI_FOUNDRY_AGENT_ENDPOINT",
    ],
)
def test_configuration_rejects_secret_or_dynamic_settings(
    tmp_path: Path, unsafe_key: str
) -> None:
    values = {**CONFIG, unsafe_key: "must-not-be-here"}
    with pytest.raises(ConfigValidationError) as error:
        load_daily_azure_config(
            _config_file(tmp_path, values),
            repository_root=tmp_path,
            repository_state_checker=lambda _root, _path: True,
        )
    assert error.value.category == "forbidden_setting"


def test_configuration_rejects_nonlocal_or_unignored_source(tmp_path: Path) -> None:
    path = _config_file(tmp_path)
    unsafe = tmp_path / "daily.env"
    unsafe.write_text(path.read_text())
    with pytest.raises(ConfigValidationError) as error:
        load_daily_azure_config(unsafe, repository_root=tmp_path)
    assert error.value.category == "committed_config_risk"


def test_configuration_rejects_tracked_or_staged_local_source(tmp_path: Path) -> None:
    path = _config_file(tmp_path)
    calls: list[tuple[Path, Path]] = []

    def tracked(root: Path, candidate: Path) -> bool:
        calls.append((root, candidate))
        return False

    with pytest.raises(ConfigValidationError) as error:
        load_daily_azure_config(
            path,
            repository_root=tmp_path,
            repository_state_checker=tracked,
        )

    assert error.value.category == "committed_config_risk"
    assert calls == [(tmp_path.resolve(), path.resolve())]


def test_check_mode_is_offline_and_does_not_construct_runner(tmp_path: Path) -> None:
    runner_constructed = False

    def forbidden_factory():
        nonlocal runner_constructed
        runner_constructed = True
        raise AssertionError("check mode must not construct a live runner")

    service = DailyAzureEnvironmentRebuild(
        _config(tmp_path),
        repository_root=tmp_path,
        runner_factory=forbidden_factory,
        local_contract_checker=lambda _root: (),
    )
    result = service.check()

    assert result.ok is True
    assert result.local_orchestration_ready is True
    assert result.daily_environment_ready is False
    assert result.azure_mutation_made is False
    assert result.agent_invoked is False
    assert runner_constructed is False
    assert not (tmp_path / ".artifacts").exists()


def test_repository_local_contract_check_succeeds_without_live_runner(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    service = DailyAzureEnvironmentRebuild(
        _config(tmp_path),
        repository_root=repository_root,
        runner_factory=lambda: pytest.fail("check must not construct live runner"),
    )

    result = service.check()

    assert result.ok is True
    assert result.local_orchestration_ready is True
    assert result.azure_mutation_made is False


class FakeRunner:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.fail_at: str | None = None
        self.fail_on_occurrence: dict[str, int] = {}
        self.foundry_absent = True
        self.web_app_absent = True
        self.rbac_absent = True
        self.rbac_plan = ConsumerRbacPlan(
            subscription_id="00000000-0000-0000-0000-000000000001",
            resource_group="fictional-daily-rg",
            web_app_name="fictional-nurse-intake-web",
            principal_id="00000000-0000-0000-0000-000000000002",
            web_app_resource_id=(
                "/subscriptions/00000000-0000-0000-0000-000000000001/"
                "resourceGroups/fictional-daily-rg/providers/"
                "Microsoft.Web/sites/fictional-nurse-intake-web"
            ),
            foundry_account_name="fictional-account",
            foundry_account_resource_id=(
                "/subscriptions/00000000-0000-0000-0000-000000000001/"
                "resourceGroups/fictional-daily-rg/providers/"
                "Microsoft.CognitiveServices/accounts/fictional-account"
            ),
            foundry_project_name="fictional-intake-project",
            foundry_project_resource_id=(
                "/subscriptions/00000000-0000-0000-0000-000000000001/"
                "resourceGroups/fictional-daily-rg/providers/"
                "Microsoft.CognitiveServices/accounts/fictional-account/"
                "projects/fictional-intake-project"
            ),
            role_name="Foundry Agent Consumer",
            role_definition_id=(
                "/subscriptions/00000000-0000-0000-0000-000000000001/"
                "providers/Microsoft.Authorization/roleDefinitions/"
                "eed3b665-ab3a-47b6-8f48-c9382fb1dad6"
            ),
            role_assignment_name="8a94d128-4835-5946-b256-d79e2024c53c",
            deployment_name="foundry-agent-consumer-rbac",
            existing_matching_assignments=0,
        )
        self.resource_group_absent = True
        self.plan_overrides: dict[str, PlanResult] = {}
        self.contexts: dict[str, DailyAzureRuntimeContext] = {}
        self.rbac_preview_binding = "preview-a"
        self.fresh_rbac_preview_binding: str | None = None
        self.fresh_package_binding: str | None = None

    def _stage(self, name: str, context: DailyAzureRuntimeContext) -> StageResult:
        self.calls.append(name)
        self.contexts[name] = context
        if (
            self.fail_at == name
            or self.fail_on_occurrence.get(name) == self.calls.count(name)
        ):
            return StageResult.failure("stage_failed")
        return StageResult.success()

    def verify_account(self, context):
        return self._stage("verify_account", context)

    def inspect_resource_group(self, context):
        result = self._stage("inspect_resource_group", context)
        if result.ok and self.resource_group_absent:
            return StageResult.absent("resource_group_absent")
        return result

    def create_resource_group(self, context):
        result = self._stage("create_resource_group", context)
        if result.ok:
            self.resource_group_absent = False
            return replace(result, mutation_made=True, attempted=True, accepted=True)
        return result

    def verify_foundry(self, context):
        result = self._stage("verify_foundry", context)
        if result.ok and self.foundry_absent:
            return StageResult.absent("foundry_absent")
        return result

    def plan_foundry(self, context):
        self._stage("plan_foundry", context)
        return self.plan_overrides.get(
            "plan_foundry",
            PlanResult(
                create_count=1,
                exact_topology_match=True,
                change_evidence=(
                    _exact_change("Create", "foundry_account", "foundry"),
                ),
            ),
        )

    def deploy_foundry(self, context):
        result = self._stage("deploy_foundry", context)
        if result.ok:
            self.foundry_absent = False
            return replace(
                result,
                updates=RuntimeUpdates(
                    foundry_account_name="fictional-account",
                    project_endpoint=(
                        "https://fictional-account.services.ai.azure.com/"
                        "api/projects/fictional-intake-project"
                    ),
                ),
                mutation_made=True,
            )
        return result

    def provision_agent(self, context):
        result = self._stage("provision_agent", context)
        if not result.ok:
            return result
        return replace(
            result,
            updates=RuntimeUpdates(
                immutable_agent_version="7",
                stable_agent_endpoint=(
                    f"{context.project_endpoint}/agents/nurse-intake-agent/"
                    "endpoint/protocols/openai"
                ),
            ),
            mutation_made=True,
        )

    def configure_agent_routing(self, context):
        return self._stage("configure_agent_routing", context)

    def verify_agent(self, context):
        return self._stage("verify_agent", context)

    def verify_web_app_configuration(self, context):
        result = self._stage("verify_web_app_configuration", context)
        if result.ok and self.web_app_absent:
            return StageResult.absent("web_app_absent")
        return result

    def plan_web_app(self, context):
        self._stage("plan_web_app", context)
        return self.plan_overrides.get(
            "plan_web_app",
            PlanResult(
                create_count=1,
                exact_topology_match=True,
                change_evidence=(
                    _exact_change("Create", "web_app", "web_app"),
                ),
            ),
        )

    def deploy_web_app(self, context):
        result = self._stage("deploy_web_app", context)
        if result.ok:
            self.web_app_absent = False
            return replace(result, mutation_made=True)
        return result

    def plan_web_app_reconciliation(self, context):
        self._stage("plan_web_app_reconciliation", context)
        return self.plan_overrides.get(
            "plan_web_app_reconciliation",
            _web_app_reconciliation_modify_plan(),
        )

    def deploy_web_app_reconciliation(self, context):
        result = self._stage("deploy_web_app_reconciliation", context)
        return replace(result, mutation_made=True) if result.ok else result

    def build_package(self, context):
        result = self._stage("build_package", context)
        binding = (
            self.fresh_package_binding
            if self.calls.count("build_package") > 1
            and self.fresh_package_binding is not None
            else PACKAGE_DIGEST
        )
        return replace(result, approval_binding=binding) if result.ok else result

    def deploy_code(self, context):
        result = self._stage("deploy_code", context)
        if result.ok:
            return replace(
                result,
                mutation_made=True,
                attempted=True,
                accepted=True,
            )
        return result

    def verify_readiness(self, context):
        result = self._stage("verify_readiness", context)
        return replace(result, artifact_current=True) if result.ok else result

    def verify_rbac(self, context):
        result = self._stage("verify_rbac", context)
        account_id = (
            "/subscriptions/00000000-0000-0000-0000-000000000001/"
            f"resourceGroups/{context.resource_group}/providers/"
            "Microsoft.CognitiveServices/accounts/"
            f"{context.foundry_account_name}"
        )
        plan = replace(
            self.rbac_plan,
            resource_group=context.resource_group,
            web_app_name=context.web_app_name,
            foundry_account_name=context.foundry_account_name,
            foundry_account_resource_id=account_id,
            foundry_project_name=context.foundry_project_name,
            foundry_project_resource_id=(
                f"{account_id}/projects/{context.foundry_project_name}"
            ),
            role_assignment_name=deterministic_role_assignment_name(
                f"{account_id}/projects/{context.foundry_project_name}",
                self.rbac_plan.principal_id,
                self.rbac_plan.role_definition_id,
            ),
        )
        if result.ok and self.rbac_absent:
            return replace(
                StageResult.absent("consumer_rbac_assignment_required"),
                consumer_rbac_plan=plan,
            )
        return replace(
            result,
            consumer_rbac_plan=replace(
                plan,
                existing_matching_assignments=1,
            ),
        )

    def deploy_rbac(self, context, preview_binding, plan):
        if preview_binding != self.rbac_preview_binding:
            return StageResult.failure("consumer_rbac_preview_changed")
        result = self._stage("deploy_rbac", context)
        if result.ok:
            self.rbac_absent = False
            return replace(result, mutation_made=True, attempted=True, accepted=True)
        return result

    def preview_rbac(self, context, plan):
        result = self._stage("preview_rbac", context)
        binding = (
            self.fresh_rbac_preview_binding
            if self.calls.count("preview_rbac") > 1
            and self.fresh_rbac_preview_binding is not None
            else self.rbac_preview_binding
        )
        return replace(
            result,
            approval_binding=binding,
            consumer_rbac_preview=ConsumerRbacPreviewProof(
                topology="exact_create",
                assignment_contents_proved=True,
                manual_review_required=False,
                record_count=1,
                create_count=1,
                modify_count=0,
                no_change_count=0,
                delete_count=0,
                ignore_count=0,
                deploy_count=0,
                unsupported_count=0,
            ),
        ) if result.ok else result

    def discover_webjob(self, context):
        return self._stage("discover_webjob", context)

    def trigger_webjob(self, context):
        result = self._stage("trigger_webjob", context)
        return replace(
            result,
            attempted=True,
            accepted=True,
            webjob_triggered=True,
        ) if result.ok else result

    def verify_hosted_agent(self, context):
        result = self._stage("verify_hosted_agent", context)
        return replace(
            result,
            webjob_status_read=True,
            managed_identity_verification_performed=True,
            agent_invoked=True,
        ) if result.ok else result


def _consumer_rbac_verifier_result(
    context: DailyAzureRuntimeContext,
    **overrides: object,
):
    subscription_id = "00000000-0000-0000-0000-000000000001"
    account_id = (
        f"/subscriptions/{subscription_id}/resourceGroups/{context.resource_group}/"
        "providers/Microsoft.CognitiveServices/accounts/"
        f"{context.foundry_account_name}"
    )
    values: dict[str, object] = {
        "ok": False,
        "category": "assignment_missing",
        "operation": "verify_foundry_agent_consumer_rbac",
        "mode": "live",
        "local_contract_validated": True,
        "azure_request_attempted": True,
        "web_app_identity_present": True,
        "foundry_project_scope_resolved": True,
        "consumer_assignment_present": False,
        "consumer_assignment_scope_matches": False,
        "consumer_role_matches": False,
        "recommended_next_step": "Review the guarded Consumer RBAC what-if.",
        "principal_id": "00000000-0000-0000-0000-000000000002",
        "web_app_resource_id": (
            f"/subscriptions/{subscription_id}/resourceGroups/"
            f"{context.resource_group}/providers/Microsoft.Web/sites/"
            f"{context.web_app_name}"
        ),
        "subscription_id": subscription_id,
        "foundry_account_resource_id": account_id,
        "foundry_project_resource_id": (
            f"{account_id}/projects/{context.foundry_project_name}"
        ),
        "role_definition_id": (
            f"/subscriptions/{subscription_id}/providers/"
            "Microsoft.Authorization/roleDefinitions/"
            "eed3b665-ab3a-47b6-8f48-c9382fb1dad6"
        ),
        "matching_assignment_count": 0,
    }
    values.update(overrides)
    return foundry_agent_consumer_rbac_verification.FoundryAgentConsumerRbacVerificationResult(
        **values
    )


def _repository_rbac_stage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    verifier_result: object,
) -> StageResult:
    monkeypatch.setattr(
        foundry_agent_consumer_rbac_verification,
        "verify_foundry_agent_consumer_rbac",
        lambda _request, *, runner: verifier_result,
    )
    runner = RepositoryDailyAzureStageRunner(
        _config(tmp_path),
        repository_root=Path(__file__).resolve().parents[1],
        command_runner=CommandRunner([]),
    )
    return runner.verify_rbac(_rbac_preview_context(tmp_path))


def test_repository_rbac_discovery_accepts_valid_assignment_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = _rbac_preview_context(tmp_path)

    result = _repository_rbac_stage(
        tmp_path,
        monkeypatch,
        _consumer_rbac_verifier_result(context),
    )

    assert result.state == "absent"
    assert result.category == "consumer_rbac_assignment_required"
    assert result.consumer_rbac_plan is not None
    assert result.consumer_rbac_plan.mutation_required is True


@pytest.mark.parametrize(
    "overrides",
    [
        {"category": "authentication_or_authorization_failed"},
        {"category": "azure_request_failed"},
        {"category": "response_parse_failed"},
        {"category": "prerequisite_missing"},
        {"category": "unexpected_error"},
        {"category": "unsupported_category"},
        {"local_contract_validated": False},
        {"web_app_identity_present": False},
        {"foundry_project_scope_resolved": False},
        {"consumer_assignment_present": True},
        {"consumer_assignment_scope_matches": True},
        {"consumer_role_matches": True},
        {"matching_assignment_count": 1},
        {"principal_id": None},
    ],
)
def test_invalid_or_contradictory_consumer_rbac_discovery_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    overrides: dict[str, object],
) -> None:
    context = _rbac_preview_context(tmp_path)

    result = _repository_rbac_stage(
        tmp_path,
        monkeypatch,
        _consumer_rbac_verifier_result(context, **overrides),
    )

    assert result.state == "failed"
    assert result.consumer_rbac_plan is None


def test_malformed_consumer_rbac_discovery_object_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = _repository_rbac_stage(tmp_path, monkeypatch, object())

    assert result.state == "failed"
    assert result.category == "consumer_rbac_discovery_failed"
    assert result.consumer_rbac_plan is None


def test_existing_direct_consumer_assignment_reuses_verification_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = _rbac_preview_context(tmp_path)
    verifier_result = _consumer_rbac_verifier_result(
        context,
        ok=True,
        category="success",
        consumer_assignment_present=True,
        consumer_assignment_scope_matches=True,
        consumer_role_matches=True,
        matching_assignment_count=1,
    )

    result = _repository_rbac_stage(tmp_path, monkeypatch, verifier_result)

    assert result.state == "verified"
    assert result.reused is True
    assert result.consumer_rbac_plan is not None
    assert result.consumer_rbac_plan.mutation_required is False


def test_full_rebuild_has_exact_order_and_sanitized_ready_result(tmp_path: Path) -> None:
    runner = FakeRunner()
    runner.rbac_absent = False
    service = DailyAzureEnvironmentRebuild(
        _config(tmp_path),
        repository_root=tmp_path,
        local_contract_checker=lambda _root: (),
    )
    approval_stages: list[str] = []

    result = service.live(
        runner,
        approver=lambda summary: approval_stages.append(summary.stage) is None,
    )

    assert runner.calls == [
        "verify_account",
        "inspect_resource_group",
        "create_resource_group",
        "verify_foundry",
        "plan_foundry",
        "deploy_foundry",
        "verify_foundry",
        "provision_agent",
        "configure_agent_routing",
        "verify_agent",
        "verify_web_app_configuration",
        "plan_web_app",
        "plan_web_app",
        "deploy_web_app",
        "verify_web_app_configuration",
        "build_package",
        "deploy_code",
        "verify_readiness",
    ]
    payload = result.to_json_dict()
    assert payload["ok"] is True
    assert payload["daily_environment_ready"] is True
    assert payload["application_artifact_current"] is True
    assert payload["application_deployment_attempted"] is True
    assert payload["application_deployment_accepted"] is True
    assert payload["application_deployment_reused"] is False
    assert payload["readiness_declaration"] == "DAILY AZURE ENVIRONMENT READY"
    assert payload["consumer_rbac_verified"] is False
    assert payload["agent_invoked"] is False
    assert payload["webjob_discovered"] is False
    assert payload["webjob_triggered"] is False
    assert payload["webjob_status_read"] is False
    assert payload["managed_identity_verification_performed"] is False
    assert approval_stages == [
        "resource_group",
        "foundry_deployment",
        "web_app_deployment",
        "application_code_deployment",
    ]
    serialized = json.dumps(payload)
    for hidden in (
        "fictional-nurse-intake-web",
        "api/projects",
        "/agents/",
        '"7"',
    ):
        assert hidden not in serialized
    assert "consumer_rbac_assignment_scope" not in payload


def test_existing_environment_reuses_without_optional_hosted_workflows(
    tmp_path: Path,
) -> None:
    runner = FakeRunner()
    runner.foundry_absent = False
    runner.web_app_absent = False
    runner.rbac_absent = False
    runner.resource_group_absent = False

    result = DailyAzureEnvironmentRebuild(
        _config(tmp_path),
        repository_root=tmp_path,
        local_contract_checker=lambda _root: (),
    ).live(runner, approver=lambda _summary: True)

    assert result.ok is True
    assert "plan_foundry" not in runner.calls
    assert "deploy_foundry" not in runner.calls
    assert "plan_web_app" not in runner.calls
    assert "deploy_web_app" not in runner.calls
    assert "verify_rbac" not in runner.calls
    assert "preview_rbac" not in runner.calls
    assert "deploy_rbac" not in runner.calls
    assert "discover_webjob" not in runner.calls
    assert "trigger_webjob" not in runner.calls
    assert "verify_hosted_agent" not in runner.calls


def test_missing_package_binding_stops_before_application_deployment(
    tmp_path: Path,
) -> None:
    runner = FakeRunner()
    runner.resource_group_absent = False
    runner.foundry_absent = False
    runner.web_app_absent = False
    runner.rbac_absent = False

    def unbound_package(context):
        return runner._stage("build_package", context)

    runner.build_package = unbound_package
    result = DailyAzureEnvironmentRebuild(
        _config(tmp_path),
        repository_root=tmp_path,
        local_contract_checker=lambda _root: (),
    ).live(runner, approver=lambda _summary: pytest.fail("unexpected approval"))

    assert result.category == "package_proof_invalid"
    assert result.web_app_configuration_verified is True
    assert result.application_package_created is True
    assert result.application_deployment_attempted is False
    assert "deploy_code" not in runner.calls


def test_valid_package_binding_reaches_application_deployment_approval(
    tmp_path: Path,
) -> None:
    runner = FakeRunner()
    runner.resource_group_absent = False
    runner.foundry_absent = False
    runner.web_app_absent = False
    runner.rbac_absent = False
    approvals: list[ApprovalSummary] = []

    result = DailyAzureEnvironmentRebuild(
        _config(tmp_path),
        repository_root=tmp_path,
        local_contract_checker=lambda _root: (),
    ).live(
        runner,
        approver=lambda summary: approvals.append(summary) is not None,
    )

    assert result.category == "application_code_deployment_approval_required"
    assert result.web_app_configuration_verified is True
    assert result.application_package_created is True
    assert result.application_deployment_attempted is False
    assert [summary.stage for summary in approvals] == [
        "application_code_deployment"
    ]
    assert approvals[0].heading == "APPLICATION CODE DEPLOYMENT"
    assert approvals[0].evidence_binding == PACKAGE_DIGEST
    assert PACKAGE_DIGEST not in json.dumps(result.to_json_dict())
    assert "deploy_code" not in runner.calls


def test_accepting_package_approval_invokes_application_deployment_once(
    tmp_path: Path,
) -> None:
    runner = FakeRunner()
    runner.resource_group_absent = False
    runner.foundry_absent = False
    runner.web_app_absent = False
    runner.rbac_absent = False
    approvals: list[str] = []

    result = DailyAzureEnvironmentRebuild(
        _config(tmp_path),
        repository_root=tmp_path,
        local_contract_checker=lambda _root: (),
    ).live(
        runner,
        approver=lambda summary: approvals.append(summary.stage) is None,
    )

    assert result.ok is True
    assert approvals == ["application_code_deployment"]
    assert runner.calls.count("build_package") == 1
    assert runner.calls.count("deploy_code") == 1


def test_absent_resource_group_without_approval_never_mutates(tmp_path: Path) -> None:
    runner = FakeRunner()

    result = DailyAzureEnvironmentRebuild(
        _config(tmp_path),
        repository_root=tmp_path,
        local_contract_checker=lambda _root: (),
    ).live(runner)

    assert result.category == "resource_group_approval_required"
    assert runner.calls == ["verify_account", "inspect_resource_group"]
    assert result.azure_mutation_made is False


@pytest.mark.parametrize(
    "case",
    (
        "delete",
        "modify",
        "unknown-action",
        "unrelated",
        "wrong-boundary",
        "wrong-scope",
        "wrong-parent",
        "wrong-identity",
        "wrong-multiplicity",
        "count-mismatch",
        "nested-only",
        "malformed",
    ),
)
def test_unsafe_foundry_plan_stops_without_prompt_or_deployment(
    tmp_path: Path,
    case: str,
) -> None:
    runner = FakeRunner()
    runner.resource_group_absent = False
    evidence = _exact_change("Create", "foundry_account", "foundry")
    plan = PlanResult(
        create_count=1,
        exact_topology_match=True,
        change_evidence=(evidence,),
    )
    if case == "delete":
        plan = replace(
            plan,
            create_count=0,
            delete_count=1,
            change_evidence=(replace(evidence, action="Delete"),),
        )
    elif case == "modify":
        plan = replace(
            plan,
            create_count=0,
            modify_count=1,
            change_evidence=(replace(evidence, action="Modify"),),
        )
    elif case == "unknown-action":
        plan = replace(
            plan,
            create_count=0,
            change_evidence=(replace(evidence, action="Replacement"),),
        )
    elif case == "unrelated":
        plan = replace(
            plan,
            unrelated_resource_count=1,
            change_evidence=(
                replace(
                    evidence,
                    logical_category="unexpected_resource",
                    approved_boundary=False,
                ),
            ),
        )
    elif case == "wrong-boundary":
        plan = replace(
            plan,
            change_evidence=(replace(evidence, boundary="web_app"),),
        )
    elif case == "wrong-scope":
        plan = replace(
            plan,
            change_evidence=(replace(evidence, expected_scope_match=False),),
        )
    elif case == "wrong-parent":
        plan = replace(
            plan,
            change_evidence=(replace(evidence, expected_parent_match=False),),
        )
    elif case == "wrong-identity":
        plan = replace(
            plan,
            change_evidence=(replace(evidence, expected_identity_match=False),),
        )
    elif case == "wrong-multiplicity":
        plan = replace(
            plan,
            change_evidence=(
                replace(evidence, expected_multiplicity_match=False),
            ),
        )
    elif case == "count-mismatch":
        plan = replace(plan, create_count=2)
    elif case == "nested-only":
        plan = replace(
            plan,
            create_count=0,
            deploy_count=1,
            change_evidence=(
                ChangeEvidence(
                    "Deploy",
                    "nested_deployment",
                    "foundry",
                    False,
                    False,
                    False,
                    True,
                    True,
                    "Microsoft.Resources/deployments",
                ),
            ),
        )
    else:
        plan = replace(plan, malformed=True)
    runner.plan_overrides["plan_foundry"] = plan
    prompts: list[str] = []

    result = DailyAzureEnvironmentRebuild(
        _config(tmp_path),
        repository_root=tmp_path,
        local_contract_checker=lambda _root: (),
    ).live(
        runner,
        approver=lambda summary: prompts.append(summary.stage) is None,
    )

    assert result.category == "unsafe_foundry_plan"
    assert prompts == []
    assert "deploy_foundry" not in runner.calls


def test_created_resource_group_state_is_preserved_when_foundry_plan_is_unsafe(
    tmp_path: Path,
) -> None:
    runner = FakeRunner()
    runner.plan_overrides["plan_foundry"] = PlanResult(malformed=True)
    prompts: list[str] = []

    result = DailyAzureEnvironmentRebuild(
        _config(tmp_path),
        repository_root=tmp_path,
        local_contract_checker=lambda _root: (),
    ).live(
        runner,
        approver=lambda summary: prompts.append(summary.stage) is None,
    )

    assert result.category == "unsafe_foundry_plan"
    assert result.azure_mutation_made is True
    assert result.resource_group_ready is True
    assert result.daily_environment_ready is False
    assert prompts == ["resource_group"]
    assert "deploy_foundry" not in runner.calls
    diagnostic = result.to_json_dict()["foundry_plan_diagnostic"]
    assert diagnostic == {
        "safe_guided_plan": False,
        "expected_boundary": "foundry",
        "require_create": True,
        "failed_predicates": [
            "plan_well_formed",
            "exact_topology_match",
            "required_create_present",
            "evidence_present",
        ],
        "plan_result": {
            "create_count": 0,
            "modify_count": 0,
            "no_change_count": 0,
            "delete_count": 0,
            "ignore_count": 0,
            "deploy_count": 0,
            "unsupported_count": 0,
            "unknown_count": 0,
            "unrelated_resource_count": 0,
            "malformed": True,
            "exact_topology_match": False,
            "source_failure_category": None,
            "change_evidence": [],
        },
    }


def test_unsafe_foundry_plan_diagnostic_contains_only_sanitized_evidence(
    tmp_path: Path,
) -> None:
    runner = FakeRunner()
    runner.resource_group_absent = False
    runner.plan_overrides["plan_foundry"] = PlanResult(
        ignore_count=1,
        unrelated_resource_count=1,
        exact_topology_match=False,
        change_evidence=(
            ChangeEvidence(
                "Ignore",
                "unexpected_resource",
                "foundry",
                False,
                False,
                False,
                False,
                False,
                "unidentified",
            ),
        ),
    )

    result = DailyAzureEnvironmentRebuild(
        _config(tmp_path),
        repository_root=tmp_path,
        local_contract_checker=lambda _root: (),
    ).live(runner, approver=lambda _summary: pytest.fail("unexpected approval"))

    diagnostic = result.to_json_dict()["foundry_plan_diagnostic"]
    assert diagnostic["failed_predicates"] == [
        "exact_topology_match",
        "unrelated_resources_absent",
        "required_create_present",
        "change[0].allowed_evidence_shape",
    ]
    assert diagnostic["plan_result"]["change_evidence"] == [
        {
            "action": "Ignore",
            "logical_category": "unexpected_resource",
            "boundary": "foundry",
            "approved_boundary": False,
            "expected_identity_match": False,
            "expected_parent_match": False,
            "expected_scope_match": False,
            "expected_multiplicity_match": False,
            "resource_type": "unidentified",
        }
    ]
    serialized = json.dumps(diagnostic)
    assert "/subscriptions/" not in serialized
    assert "fictional-daily-rg" not in serialized
    assert "fictional-intake-foundry" not in serialized


def test_actual_clean_start_failed_plan_fixture_preserves_adapter_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = json.loads(
        (
            Path(__file__).parent
            / "fixtures/foundry_clean_start_live_plan.json"
        ).read_text()
    )
    config = _config(tmp_path)
    repository_root = Path(__file__).resolve().parents[1]
    repository_runner = RepositoryDailyAzureStageRunner(
        config,
        repository_root=repository_root,
        command_runner=CommandRunner([]),
    )
    repository_runner._foundry_parameters = _foundry_parameters(
        tmp_path,
        repository_root,
    )
    monkeypatch.setattr(
        "scripts.deploy_foundry_infra.execute",
        lambda *args, **kwargs: fixture["adapter_result"],
    )
    context = DailyAzureEnvironmentRebuild(
        config,
        repository_root=tmp_path,
        local_contract_checker=lambda _root: (),
    )._initial_context()

    plan = repository_runner.plan_foundry(context)

    assert plan.source_failure_category == "foundry_account_name_unavailable"
    diagnostic = GuidedPlanDiagnostic(
        plan,
        expected_boundary="foundry",
        require_create=True,
    ).to_json_dict()
    assert diagnostic["plan_result"] == fixture["normalized_plan"]
    assert diagnostic["failed_predicates"] == fixture["failed_predicates"]
    assert safe_guided_plan(
        plan,
        expected_boundary="foundry",
        require_create=True,
    ) is False


def test_plan_mapping_does_not_expose_unrecognized_adapter_failure_category() -> None:
    plan = _plan_from_mapping(
        {
            "ok": False,
            "category": "private-/subscriptions/private-sub/resourceGroups/private-rg",
        }
    )

    assert plan.malformed is True
    assert plan.source_failure_category == "foundry_plan_failed"
    serialized = json.dumps(
        GuidedPlanDiagnostic(
            plan,
            expected_boundary="foundry",
            require_create=True,
        ).to_json_dict()
    )
    assert "private-sub" not in serialized
    assert "private-rg" not in serialized


def test_foundry_adapter_failure_is_not_mislabeled_as_unsafe_plan(
    tmp_path: Path,
) -> None:
    runner = FakeRunner()
    runner.plan_overrides["plan_foundry"] = PlanResult(
        malformed=True,
        source_failure_category="foundry_account_name_unavailable",
    )
    prompts: list[str] = []

    result = DailyAzureEnvironmentRebuild(
        _config(tmp_path),
        repository_root=tmp_path,
        local_contract_checker=lambda _root: (),
    ).live(
        runner,
        approver=lambda summary: prompts.append(summary.stage) is None,
    )

    assert result.category == "foundry_account_name_unavailable"
    assert result.resource_group_ready is True
    assert result.daily_environment_ready is False
    assert result.azure_mutation_made is True
    assert prompts == ["resource_group"]
    assert runner.calls[:5] == [
        "verify_account",
        "inspect_resource_group",
        "create_resource_group",
        "verify_foundry",
        "plan_foundry",
    ]
    assert "deploy_foundry" not in runner.calls
    assert result.to_json_dict()["foundry_plan_diagnostic"][
        "safe_guided_plan"
    ] is False


def test_inexact_web_app_topology_still_stops_before_deployment(tmp_path: Path) -> None:
    runner = FakeRunner()
    runner.resource_group_absent = False
    runner.foundry_absent = False
    runner.plan_overrides["plan_web_app"] = PlanResult(
        create_count=8,
        ignore_count=2,
        exact_topology_match=False,
        change_evidence=(
            *(
                _exact_change("Create", f"expected-{index}", "web_app")
                for index in range(8)
            ),
            ChangeEvidence("Ignore", "unexpected_resource", "web_app", False),
            ChangeEvidence("Ignore", "unexpected_resource", "web_app", False),
        ),
    )

    result = DailyAzureEnvironmentRebuild(
        _config(tmp_path),
        repository_root=tmp_path,
        local_contract_checker=lambda _root: (),
    ).live(runner, approver=lambda _summary: True)

    assert result.category == "unsafe_web_app_plan"
    assert "deploy_web_app" not in runner.calls
    assert result.daily_environment_ready is False


def test_exact_web_app_topology_reaches_only_the_existing_approval_prompt(
    tmp_path: Path,
) -> None:
    runner = FakeRunner()
    runner.resource_group_absent = False
    runner.foundry_absent = False
    runner.plan_overrides["plan_web_app"] = PlanResult(
        create_count=8,
        ignore_count=2,
        exact_topology_match=True,
        change_evidence=(
            *(
                _exact_change("Create", f"expected-{index}", "web_app")
                for index in range(8)
            ),
            replace(
                _exact_change("Ignore", "foundry_account_reference", "web_app"),
                resource_type="Microsoft.CognitiveServices/accounts",
            ),
            replace(
                _exact_change("Ignore", "foundry_project_reference", "web_app"),
                resource_type="Microsoft.CognitiveServices/accounts/projects",
            ),
        ),
    )
    prompts: list[str] = []

    result = DailyAzureEnvironmentRebuild(
        _config(tmp_path),
        repository_root=tmp_path,
        local_contract_checker=lambda _root: (),
    ).live(
        runner,
        approver=lambda summary: (
            prompts.append(summary.stage) is None
            and summary.stage != "web_app_deployment"
        ),
    )

    assert result.category == "web_app_deployment_approval_required"
    assert prompts == ["web_app_deployment"]
    assert "deploy_web_app" not in runner.calls




def test_existing_web_app_drift_remains_fail_closed_without_reconciliation(
    tmp_path: Path,
) -> None:
    runner = FakeRunner()
    runner.resource_group_absent = False
    runner.foundry_absent = False
    runner.web_app_absent = False
    runner.rbac_absent = False
    def verify_web_app_configuration(context):
        runner.calls.append("verify_web_app_configuration")
        runner.contexts["verify_web_app_configuration"] = context
        return StageResult.absent("web_app_configuration_not_current")

    runner.verify_web_app_configuration = verify_web_app_configuration
    approvals: list[ApprovalSummary] = []

    result = DailyAzureEnvironmentRebuild(
        _config(tmp_path),
        repository_root=tmp_path,
        local_contract_checker=lambda _root: (),
    ).live(
        runner,
        approver=lambda summary: approvals.append(summary) is None,
    )

    assert result.ok is False
    assert result.category == "web_app_configuration_not_current"
    assert runner.calls.count("verify_web_app_configuration") == 1
    assert "plan_web_app_reconciliation" not in runner.calls
    assert "deploy_web_app_reconciliation" not in runner.calls
    assert "plan_web_app" not in runner.calls
    assert "deploy_web_app" not in runner.calls
    assert "build_package" not in runner.calls
    assert "verify_readiness" not in runner.calls
    assert approvals == []
    assert result.recommended_next_step == (
        "Recreate the disposable resource group through the normal fresh-build "
        "path or use the separate supervised Web App deployment workflow."
    )


@pytest.mark.parametrize(
    "mutation",
    (
        "unrecognized-property",
        "detached-optional-settings",
        "relative-child",
        "optional-variable-string-decoy",
        "conditional-relative-child",
    ),
)
def test_invalid_web_app_bicep_contract_blocks_modify_approval(
    tmp_path: Path,
    mutation: str,
) -> None:
    source_root = Path(__file__).resolve().parents[1]
    for relative in (
        Path("infra/main.bicep"),
        Path("infra/modules/web-app.bicep"),
        Path("infra/modules/hosted-foundry-verifier-config-validation.bicep"),
    ):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        source = (source_root / relative).read_text()
        if relative.name == "web-app.bicep":
            if mutation == "unrecognized-property":
                source = source.replace(
                    "    httpsOnly: true\n",
                    "    httpsOnly: true\n"
                    "    publicNetworkAccess: 'Enabled'\n",
                    1,
                )
            elif mutation == "detached-optional-settings":
                source = source.replace(
                    "      appSettings: concat([\n",
                    "      appSettings: [\n",
                    1,
                ).replace(
                    "      ], hostedFoundryVerifierAppSettings)\n",
                    "      ]\n",
                    1,
                )
                source += (
                    "\nvar decoy = {\n"
                    "  appSettings: concat([], hostedFoundryVerifierAppSettings)\n"
                    "}\n"
                )
            elif mutation == "relative-child":
                source += (
                    "\nresource webAppConfig 'config@2024-04-01' = {\n"
                    "  parent: webApp\n"
                    "  name: 'web'\n"
                    "  properties: {}\n"
                    "}\n"
                )
            elif mutation == "optional-variable-string-decoy":
                marker = (
                    "var hostedFoundryVerifierAppSettings = "
                    "validatedHostedFoundryVerifierConfiguration.mode "
                    "== 'enabled' ? [\n"
                )
                declaration_start = source.index(marker)
                declaration_end = (
                    source.index("] : []\n", declaration_start)
                    + len("] : []\n")
                )
                declaration = source[declaration_start:declaration_end]
                empty_declaration = (
                    marker + "] : []\n"
                )
                source = (
                    source[:declaration_start]
                    + "var decoyOptionalText = '''\n"
                    + declaration
                    + "'''\n"
                    + empty_declaration
                    + source[declaration_end:]
                )
            else:
                source += (
                    "\nresource webAppConfig 'config@2024-04-01' = "
                    "if (contains({}, 'x')) {\n"
                    "  parent: webApp\n"
                    "  name: 'web'\n"
                    "  properties: {}\n"
                    "}\n"
                )
        target.write_text(source)

    runner = FakeRunner()
    runner.resource_group_absent = False
    runner.foundry_absent = False
    runner.web_app_absent = False
    runner.plan_overrides[
        "plan_web_app_reconciliation"
    ] = _web_app_reconciliation_modify_plan()
    approvals: list[str] = []

    result = DailyAzureEnvironmentRebuild(
        _config(tmp_path),
        repository_root=tmp_path,
        local_contract_checker=lambda root: (
            ()
            if web_app_deployment.web_app_infrastructure_local_contract_valid(
                root / "infra/main.bicep"
            )
            else ("web_app_infrastructure_contract_invalid",)
        ),
    ).live(
        runner,
        approver=lambda summary: approvals.append(summary.stage) is None,
    )

    assert result.category == "local_contract_invalid"
    assert approvals == []
    assert runner.calls == []


def _web_app_hosting_modify_plan() -> PlanResult:
    expected = (
        ("Microsoft.DocumentDB/databaseAccounts", "cosmos_account"),
        (
            "Microsoft.DocumentDB/databaseAccounts/sqlDatabases",
            "cosmos_database",
        ),
        (
            "Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers",
            "cosmos_container",
        ),
        ("Microsoft.Storage/storageAccounts", "storage_account"),
        ("Microsoft.OperationalInsights/workspaces", "log_analytics"),
        ("Microsoft.Insights/components", "application_insights"),
        ("Microsoft.Web/serverfarms", "app_service_plan"),
    )
    no_change = tuple(
        replace(
            _exact_change("NoChange", category, "web_app"),
            resource_type=resource_type,
        )
        for resource_type, category in expected
    )
    modify = replace(
        _exact_change("Modify", "web_app", "web_app"),
        resource_type="Microsoft.Web/sites",
    )
    references = (
        replace(
            _exact_change("Ignore", "foundry_account_reference", "web_app"),
            resource_type="Microsoft.CognitiveServices/accounts",
        ),
        replace(
            _exact_change("Ignore", "foundry_project_reference", "web_app"),
            resource_type="Microsoft.CognitiveServices/accounts/projects",
        ),
    )
    return PlanResult(
        modify_count=1,
        no_change_count=7,
        ignore_count=2,
        exact_topology_match=True,
        change_evidence=(*no_change, modify, *references),
    )


def _web_app_reconciliation_modify_plan() -> PlanResult:
    return PlanResult(
        modify_count=1,
        exact_topology_match=True,
        change_evidence=(
            replace(
                _exact_change("Modify", "web_app", "web_app_reconciliation"),
                resource_type="Microsoft.Web/sites",
            ),
        ),
    )


def test_web_app_plan_policy_preserves_create_nochange_and_exact_modify() -> None:
    create = PlanResult(
        create_count=1,
        exact_topology_match=True,
        change_evidence=(
            replace(
                _exact_change("Create", "web_app", "web_app"),
                resource_type="Microsoft.Web/sites",
            ),
        ),
    )
    modify = _web_app_hosting_modify_plan()
    no_change_evidence = tuple(
        replace(change, action="NoChange")
        if change.action == "Modify"
        else change
        for change in modify.change_evidence
    )
    no_change = replace(
        modify,
        modify_count=0,
        no_change_count=8,
        change_evidence=no_change_evidence,
    )

    assert safe_web_app_plan(create) is True
    assert safe_web_app_plan(no_change) is True
    assert safe_web_app_plan(modify) is True
    assert safe_guided_plan(
        modify,
        expected_boundary="web_app",
        require_create=False,
    ) is False


@pytest.mark.parametrize(
    "case",
    (
        "unrelated-web-app",
        "app-service-plan",
        "cosmos",
        "storage",
        "foundry",
        "unrecognized-child",
        "mixed-delete",
        "mixed-deploy",
        "mixed-unsupported",
        "unknown-action",
        "multiple-modify",
        "missing-evidence",
        "malformed",
        "wrong-category",
        "wrong-scope",
        "wrong-identity",
        "wrong-boundary",
        "wrong-multiplicity",
    ),
)
def test_web_app_modify_policy_rejects_unrelated_or_ambiguous_evidence(
    case: str,
) -> None:
    plan = _web_app_hosting_modify_plan()
    changes = list(plan.change_evidence)
    modify_index = next(
        index for index, change in enumerate(changes) if change.action == "Modify"
    )
    modifying = changes[modify_index]
    if case == "unrelated-web-app":
        changes[modify_index] = replace(
            modifying,
            approved_boundary=False,
            expected_identity_match=False,
        )
    elif case == "app-service-plan":
        changes[modify_index] = replace(
            modifying,
            logical_category="app_service_plan",
            resource_type="Microsoft.Web/serverfarms",
        )
    elif case == "cosmos":
        changes[modify_index] = replace(
            modifying,
            logical_category="cosmos_account",
            resource_type="Microsoft.DocumentDB/databaseAccounts",
        )
    elif case == "storage":
        changes[modify_index] = replace(
            modifying,
            logical_category="storage_account",
            resource_type="Microsoft.Storage/storageAccounts",
        )
    elif case == "foundry":
        changes[modify_index] = replace(
            modifying,
            logical_category="foundry_account",
            resource_type="Microsoft.CognitiveServices/accounts",
        )
    elif case == "unrecognized-child":
        changes[modify_index] = replace(
            modifying,
            logical_category="web_app_configuration",
            resource_type="Microsoft.Web/sites/config",
        )
    elif case in {"mixed-delete", "mixed-deploy", "mixed-unsupported"}:
        action = {
            "mixed-delete": "Delete",
            "mixed-deploy": "Deploy",
            "mixed-unsupported": "Unsupported",
        }[case]
        changes[0] = replace(changes[0], action=action)
        plan = replace(
            plan,
            no_change_count=6,
            delete_count=int(action == "Delete"),
            deploy_count=int(action == "Deploy"),
            unsupported_count=int(action == "Unsupported"),
        )
    elif case == "unknown-action":
        changes[0] = replace(changes[0], action="Replacement")
        plan = replace(plan, no_change_count=6, unknown_count=1)
    elif case == "multiple-modify":
        changes[0] = replace(changes[0], action="Modify")
        plan = replace(plan, modify_count=2, no_change_count=6)
    elif case == "missing-evidence":
        plan = replace(plan, change_evidence=())
        changes = []
    elif case == "malformed":
        plan = replace(plan, malformed=True)
    elif case == "wrong-category":
        changes[modify_index] = replace(
            modifying,
            logical_category="unexpected_resource",
        )
    elif case == "wrong-scope":
        changes[modify_index] = replace(
            modifying,
            expected_scope_match=False,
        )
    elif case == "wrong-identity":
        changes[modify_index] = replace(
            modifying,
            expected_identity_match=False,
        )
    elif case == "wrong-boundary":
        changes[modify_index] = replace(modifying, boundary="foundry")
    else:
        changes[modify_index] = replace(
            modifying,
            expected_multiplicity_match=False,
        )

    plan = replace(plan, change_evidence=tuple(changes))

    assert safe_web_app_plan(plan) is False






def test_repository_webjob_hosting_mismatch_is_not_reused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verifier_result = SimpleNamespace(
        ok=False,
        category="webjob_hosting_configuration_invalid",
        hosted_verifier_configuration_verified=False,
    )
    monkeypatch.setattr(
        "src.app.services.web_app_configuration_verification."
        "verify_web_app_configuration",
        lambda *_args, **_kwargs: verifier_result,
    )
    runner = RepositoryDailyAzureStageRunner(
        _config(tmp_path),
        repository_root=Path(__file__).resolve().parents[1],
        command_runner=CommandRunner([]),
    )

    result = runner.verify_web_app_configuration(_rbac_preview_context(tmp_path))

    assert result.ok is False
    assert result.state == "absent"
    assert result.category == "web_app_configuration_not_current"


def test_repository_reconciliation_request_is_explicit_and_never_uses_main(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    runner = RepositoryDailyAzureStageRunner(
        _config(tmp_path),
        repository_root=repository_root,
        command_runner=CommandRunner([]),
    )
    context = _rbac_preview_context(tmp_path)

    initial = runner._web_app_request("what-if", context)
    reconciliation = runner._web_app_request(
        "what-if",
        context,
        purpose="existing_web_app_reconciliation",
    )

    assert initial.purpose == "initial_create"
    assert initial.template_file == repository_root / "infra/main.bicep"
    assert reconciliation.purpose == "existing_web_app_reconciliation"
    assert (
        reconciliation.template_file
        == repository_root / "infra/modules/web-app.bicep"
    )
    assert reconciliation.template_file != initial.template_file


def test_guided_plan_accepts_sanitized_nested_deployment_for_operator_review() -> None:
    plan = PlanResult(
        create_count=1,
        deploy_count=1,
        exact_topology_match=True,
        change_evidence=(
            _exact_change("Create", "foundry_account", "foundry"),
            ChangeEvidence(
                "Deploy",
                "nested_deployment",
                "foundry",
                False,
                False,
                False,
                True,
                True,
                "Microsoft.Resources/deployments",
            ),
        ),
    )

    assert safe_guided_plan(
        plan, expected_boundary="foundry", require_create=True
    ) is True
    assert safe_automatic_plan(plan, expected_boundary="foundry") is False

    nested_only_create = PlanResult(
        create_count=1,
        exact_topology_match=True,
        change_evidence=(
            replace(plan.change_evidence[1], action="Create"),
        ),
    )
    assert safe_guided_plan(
        nested_only_create, expected_boundary="foundry", require_create=True
    ) is False


@pytest.mark.parametrize(
    ("present", "expected_deploy", "unexpected_deploys"),
    [
        ((False, True, True), "deploy_foundry", ("deploy_web_app", "deploy_rbac")),
        ((True, False, True), "deploy_web_app", ("deploy_foundry", "deploy_rbac")),
    ],
)
def test_partial_reconstruction_runs_only_missing_safe_stages(
    tmp_path: Path,
    present: tuple[bool, bool, bool],
    expected_deploy: str,
    unexpected_deploys: tuple[str, ...],
) -> None:
    runner = FakeRunner()
    foundry_present, web_present, rbac_present = present
    runner.foundry_absent = not foundry_present
    runner.web_app_absent = not web_present
    runner.rbac_absent = not rbac_present

    result = DailyAzureEnvironmentRebuild(
        _config(tmp_path),
        repository_root=tmp_path,
        local_contract_checker=lambda _root: (),
    ).live(runner, approver=lambda _summary: True)

    assert result.ok is True
    assert expected_deploy in runner.calls
    assert all(name not in runner.calls for name in unexpected_deploys)


@pytest.mark.parametrize(
    "plan",
    [
        PlanResult(modify_count=1),
        PlanResult(delete_count=1),
        PlanResult(deploy_count=1),
        PlanResult(unknown_count=1),
        PlanResult(malformed=True),
        PlanResult(create_count=1, unrelated_resource_count=1),
        PlanResult(unsupported_count=1),
    ],
)
def test_generic_what_if_policy_fails_closed(plan: PlanResult) -> None:
    assert safe_automatic_plan(plan) is False


def test_safe_what_if_policy_accepts_only_create_nochange_ignore_and_exact_rbac() -> None:
    evidence = (
        _exact_change("Create", "foundry_account", "foundry"),
        _exact_change("Create", "foundry_project", "foundry"),
    )
    assert safe_automatic_plan(
        PlanResult(
            create_count=2,
            change_evidence=evidence,
            exact_topology_match=True,
        )
    ) is True
    assert safe_automatic_plan(PlanResult(create_count=2)) is False
    assert safe_automatic_plan(PlanResult(unsupported_count=1)) is False


def test_exact_evidence_still_rejects_count_disagreement() -> None:
    evidence = (
        _exact_change("Create", "foundry_account", "foundry"),
        _exact_change("Create", "foundry_project", "foundry"),
    )
    plan = PlanResult(
        create_count=1,
        change_evidence=evidence,
        exact_topology_match=True,
    )

    assert safe_automatic_plan(plan, expected_boundary="foundry") is False


@pytest.mark.parametrize("resource_type", (None, 7, ["unexpected"]))
def test_plan_mapping_rejects_missing_or_invalid_resource_type(
    resource_type: object,
) -> None:
    evidence = {
        "action": "Create",
        "logical_category": "foundry_account",
        "boundary": "foundry",
        "approved_boundary": True,
        "expected_identity_match": True,
        "expected_parent_match": True,
        "expected_scope_match": True,
        "expected_multiplicity_match": True,
    }
    if resource_type is not None:
        evidence["resource_type"] = resource_type
    result = _plan_from_mapping(
        {
            "ok": True,
            "create_count": 1,
            "modify_count": 0,
            "no_change_count": 0,
            "delete_count": 0,
            "ignore_count": 0,
            "deploy_count": 0,
            "unsupported_count": 0,
            "change_evidence": [evidence],
            "exact_topology_match": True,
        }
    )

    assert result.malformed is True
    assert safe_guided_plan(
        result,
        expected_boundary="foundry",
        require_create=True,
    ) is False


def test_unrelated_create_only_evidence_stops_automatic_continuation() -> None:
    plan = PlanResult(
        create_count=1,
        change_evidence=(
            ChangeEvidence("Create", "unexpected_resource", "foundry", False),
        ),
    )

    assert safe_automatic_plan(plan) is False
    no_change = PlanResult(
        no_change_count=1,
        exact_topology_match=True,
        change_evidence=(
            _exact_change("NoChange", "foundry_account", "foundry"),
        ),
    )
    assert safe_automatic_plan(no_change, require_create=True) is False




def test_public_coordinator_result_has_no_canonical_rbac_identifiers(
    tmp_path: Path,
) -> None:
    runner = FakeRunner()
    runner.rbac_absent = False
    result = DailyAzureEnvironmentRebuild(
        _config(tmp_path),
        repository_root=tmp_path,
        local_contract_checker=lambda _root: (),
    ).live(runner, approver=lambda _summary: True)

    assert not hasattr(result, "consumer_rbac_assignment_scope")
    public = f"{result!r}\n{json.dumps(result.to_json_dict())}"
    assert "/subscriptions/" not in public
    assert "/providers/" not in public
    assert runner.rbac_plan.principal_id not in public
    assert "/subscriptions/" not in repr(runner.rbac_plan)
    assert runner.rbac_plan.principal_id not in repr(
        replace(
            StageResult.success(),
            consumer_rbac_plan=runner.rbac_plan,
        )
    )




def _exact_change(action: str, category: str, boundary: str) -> ChangeEvidence:
    return ChangeEvidence(
        action,
        category,
        boundary,
        True,
        True,
        True,
        True,
        True,
    )


@pytest.mark.parametrize(
    "failure_stage",
    [
        "verify_account",
        "inspect_resource_group",
        "create_resource_group",
        "verify_foundry",
        "deploy_foundry",
        "provision_agent",
        "configure_agent_routing",
        "verify_agent",
        "verify_web_app_configuration",
        "deploy_web_app",
        "build_package",
        "deploy_code",
        "verify_readiness",
    ],
)
def test_major_stage_failures_stop_all_later_work(
    tmp_path: Path, failure_stage: str
) -> None:
    runner = FakeRunner()
    runner.rbac_absent = False
    runner.fail_at = failure_stage

    result = DailyAzureEnvironmentRebuild(
        _config(tmp_path),
        repository_root=tmp_path,
        local_contract_checker=lambda _root: (),
    ).live(runner, approver=lambda _summary: True)

    assert result.ok is False
    assert runner.calls[-1] == failure_stage
    assert result.agent_invoked is False
    assert result.webjob_triggered is False


def test_dynamic_context_flows_without_aggregate_leakage(tmp_path: Path) -> None:
    runner = FakeRunner()
    result = DailyAzureEnvironmentRebuild(
        _config(tmp_path),
        repository_root=tmp_path,
        local_contract_checker=lambda _root: (),
    ).live(runner, approver=lambda _summary: True)

    routing_context = runner.contexts["configure_agent_routing"]
    assert routing_context.immutable_agent_version == "7"
    assert routing_context.project_endpoint.endswith("fictional-intake-project")
    assert routing_context.stable_agent_endpoint.endswith("protocols/openai")
    readiness_context = runner.contexts["verify_readiness"]
    assert readiness_context.hosted_origin == (
        "https://fictional-nurse-intake-web.azurewebsites.net"
    )
    assert "verify_rbac" not in runner.contexts
    assert not hasattr(result, "consumer_rbac_assignment_scope")


def test_live_reruns_local_contract_before_constructing_runner(tmp_path: Path) -> None:
    runner_constructed = False

    def forbidden_runner():
        nonlocal runner_constructed
        runner_constructed = True
        raise AssertionError

    result = DailyAzureEnvironmentRebuild(
        _config(tmp_path),
        repository_root=tmp_path,
        runner_factory=forbidden_runner,
        local_contract_checker=lambda _root: ("contract:invalid",),
    ).live()

    assert result.category == "local_contract_invalid"
    assert result.local_orchestration_ready is False
    assert result.azure_mutation_made is False
    assert runner_constructed is False


def test_failed_stage_preserves_confirmed_or_ambiguous_mutation(tmp_path: Path) -> None:
    for mutation_state in (True, None):
        runner = FakeRunner()

        def failed_group(_context, state=mutation_state):
            runner.calls.append("create_resource_group")
            return StageResult.failure(
                "resource_group_creation_failed",
                mutation_made=state,
                attempted=True,
            )

        runner.create_resource_group = failed_group
        result = DailyAzureEnvironmentRebuild(
            _config(tmp_path),
            repository_root=tmp_path,
            local_contract_checker=lambda _root: (),
        ).live(runner, approver=lambda _summary: True)

        assert result.azure_mutation_made is mutation_state


def test_successful_stage_and_ready_result_reject_ambiguous_mutation() -> None:
    with pytest.raises(ValueError):
        StageResult.success(mutation_made=None)

    with pytest.raises(ValueError):
        DailyAzureEnvironmentRebuildResult(
            ok=True,
            category="success",
            mode="live",
            daily_environment_ready=True,
            azure_mutation_made=None,
        )


def test_stage_result_success_preserves_approval_binding() -> None:
    result = StageResult.success(approval_binding="digest-a")

    assert result.ok is True
    assert result.approval_binding == "digest-a"


def test_stage_result_success_defaults_and_existing_fields_are_preserved() -> None:
    default = StageResult.success()
    updates = RuntimeUpdates(immutable_agent_version="7")
    populated = StageResult.success(
        reused=True,
        mutation_made=True,
        updates=updates,
        attempted=True,
        accepted=True,
        artifact_current=True,
    )

    assert default == StageResult(
        ok=True,
        state="verified",
        category="success",
        mutation_made=False,
        approval_binding=None,
    )
    assert populated.ok is True
    assert populated.state == "verified"
    assert populated.category == "success"
    assert populated.reused is True
    assert populated.mutation_made is True
    assert populated.updates is updates
    assert populated.attempted is True
    assert populated.accepted is True
    assert populated.artifact_current is True
    assert populated.approval_binding is None
    assert StageResult.absent("resource_absent") == StageResult(
        ok=False,
        state="absent",
        category="resource_absent",
    )
    assert StageResult.failure(
        "stage_failed",
        mutation_made=True,
        attempted=True,
    ) == StageResult(
        ok=False,
        state="failed",
        category="stage_failed",
        mutation_made=True,
        attempted=True,
    )


def test_routing_mutation_survives_later_verification_failure(tmp_path: Path) -> None:
    runner = FakeRunner()
    runner.foundry_absent = False
    runner.web_app_absent = False
    runner.rbac_absent = False

    def mutated_routing(context):
        runner.calls.append("configure_agent_routing")
        runner.contexts["configure_agent_routing"] = context
        return StageResult.success(mutation_made=True)

    runner.configure_agent_routing = mutated_routing
    runner.fail_at = "verify_agent"

    result = DailyAzureEnvironmentRebuild(
        _config(tmp_path),
        repository_root=tmp_path,
        local_contract_checker=lambda _root: (),
    ).live(runner, approver=lambda _summary: True)

    assert result.ok is False
    assert result.category == "stage_failed"
    assert result.azure_mutation_made is True


def test_confirmed_routing_mutation_followed_by_ambiguous_failure_never_succeeds(
    tmp_path: Path,
) -> None:
    runner = FakeRunner()
    runner.foundry_absent = False
    runner.web_app_absent = False
    runner.rbac_absent = False

    def mutated_routing(context):
        runner.calls.append("configure_agent_routing")
        runner.contexts["configure_agent_routing"] = context
        return StageResult.success(mutation_made=True)

    def ambiguous_verification(context):
        runner.calls.append("verify_agent")
        runner.contexts["verify_agent"] = context
        return StageResult.failure("agent_verification_ambiguous", mutation_made=None)

    runner.configure_agent_routing = mutated_routing
    runner.verify_agent = ambiguous_verification

    result = DailyAzureEnvironmentRebuild(
        _config(tmp_path),
        repository_root=tmp_path,
        local_contract_checker=lambda _root: (),
    ).live(runner, approver=lambda _summary: True)

    assert result.ok is False
    assert result.category == "agent_verification_ambiguous"
    assert result.azure_mutation_made is True
    assert "verify_web_app_configuration" not in runner.calls
    assert result.daily_environment_ready is False


@pytest.mark.parametrize(
    "category",
    [
        "malformed_json",
        "unexpected_error",
        "unsafe_hosted_posture",
        "http_request_failed",
        "unexpected_http_status",
        "response_contract_mismatch",
    ],
)
def test_ambiguous_readiness_stops_without_any_follow_on_mutation(
    tmp_path: Path,
    category: str,
) -> None:
    runner = FakeRunner()
    runner.rbac_absent = False

    def failed_readiness(context):
        runner.calls.append("verify_readiness")
        runner.contexts["verify_readiness"] = context
        return StageResult.failure(category)

    runner.verify_readiness = failed_readiness
    result = DailyAzureEnvironmentRebuild(
        _config(tmp_path),
        repository_root=tmp_path,
        local_contract_checker=lambda _root: (),
    ).live(runner, approver=lambda _summary: True)

    assert result.category == category
    assert runner.calls.count("deploy_code") == 1
    assert runner.calls[-1] == "verify_readiness"
    assert "verify_rbac" not in runner.calls
    assert result.application_artifact_current is False


def test_successful_stage_without_deployment_or_artifact_proof_cannot_be_ready(
    tmp_path: Path,
) -> None:
    runner = FakeRunner()
    runner.rbac_absent = False

    def unproven_code(context):
        runner.calls.append("deploy_code")
        runner.contexts["deploy_code"] = context
        return StageResult.success()

    runner.deploy_code = unproven_code
    result = DailyAzureEnvironmentRebuild(
        _config(tmp_path),
        repository_root=tmp_path,
        local_contract_checker=lambda _root: (),
    ).live(runner, approver=lambda _summary: True)

    assert result.category == "application_provenance_invalid"
    assert result.daily_environment_ready is False
    assert "verify_readiness" not in runner.calls


def test_current_package_can_be_safely_reused_before_hosted_readiness_proof(
    tmp_path: Path,
) -> None:
    runner = FakeRunner()
    runner.rbac_absent = False

    def reused_code(context):
        runner.calls.append("deploy_code")
        runner.contexts["deploy_code"] = context
        return StageResult.success(reused=True, artifact_current=True)

    runner.deploy_code = reused_code
    result = DailyAzureEnvironmentRebuild(
        _config(tmp_path),
        repository_root=tmp_path,
        local_contract_checker=lambda _root: (),
    ).live(runner, approver=lambda _summary: True)

    assert result.category == "success"
    assert result.application_deployment_reused is True
    assert result.application_deployment_attempted is False
    assert result.application_deployment_accepted is False
    assert result.application_artifact_current is True
    assert result.daily_environment_ready is True
    assert runner.calls[-1] == "verify_readiness"


def test_accepted_deployment_with_old_hosted_worker_cannot_be_ready(
    tmp_path: Path,
) -> None:
    runner = FakeRunner()
    runner.rbac_absent = False

    def stale_worker(context):
        runner.calls.append("verify_readiness")
        runner.contexts["verify_readiness"] = context
        return StageResult.success(artifact_current=False)

    runner.verify_readiness = stale_worker
    result = DailyAzureEnvironmentRebuild(
        _config(tmp_path),
        repository_root=tmp_path,
        local_contract_checker=lambda _root: (),
    ).live(runner, approver=lambda _summary: True)

    assert result.application_deployment_accepted is True
    assert result.category == "application_artifact_mismatch"
    assert result.application_artifact_current is False
    assert result.daily_environment_ready is False
    assert "verify_rbac" not in runner.calls


def test_runtime_session_file_is_atomic_restrictive_and_rejects_symlink(
    tmp_path: Path,
) -> None:
    path = tmp_path / ".artifacts/daily-azure-rebuild/current-session.env"
    context = DailyAzureRuntimeContext(
        resource_group="fictional-rg",
        location="eastus2",
        foundry_account_name="fictional-account",
        foundry_project_name="fictional-project",
        project_endpoint="https://fictional.example/api/projects/demo",
        model_deployment_name="fictional-model",
        agent_name="fictional-agent",
        immutable_agent_version="7",
        stable_agent_endpoint="https://fictional.example/agents/a/endpoint/protocols/openai",
        web_app_name="fictional-web",
        hosted_origin="https://fictional-web.azurewebsites.net",
    )
    write_runtime_session_file(path, context)

    assert path.is_file()
    assert os.stat(path).st_mode & 0o777 == 0o600
    contents = path.read_text()
    assert "TOKEN" not in contents
    assert "SECRET" not in contents
    assert "IDENTITY_HEADER" not in contents
    write_runtime_session_file(
        path,
        replace(context, immutable_agent_version="8"),
    )
    assert "AZURE_AI_FOUNDRY_AGENT_VERSION=8\n" in path.read_text()
    assert "AZURE_AI_FOUNDRY_AGENT_VERSION=7\n" not in path.read_text()
    assert list(path.parent.glob(".current-session.*.tmp")) == []

    path.unlink()
    target = tmp_path / "outside.env"
    target.write_text("preserve=true\n")
    path.symlink_to(target)
    with pytest.raises(OSError):
        write_runtime_session_file(path, context)
    assert target.read_text() == "preserve=true\n"


class CommandRunner:
    def __init__(self, results: list[tuple[int, str, str]]) -> None:
        self.results = list(results)
        self.calls: list[list[str]] = []

    def run(self, args: list[str]):
        from types import SimpleNamespace

        self.calls.append(args)
        return_code, stdout, stderr = self.results.pop(0)
        return SimpleNamespace(
            return_code=return_code,
            stdout=stdout,
            stderr=stderr,
        )


class ExactCoordinatorCommandRunner:
    def __init__(
        self,
        results: list[daily_rebuild_service._CommandResult],
    ) -> None:
        self.results = list(results)
        self.calls: list[list[str]] = []

    def run(self, args: list[str]):
        self.calls.append(args)
        return self.results.pop(0)


class RaisingCoordinatorCommandRunner:
    def __init__(self, error: Exception) -> None:
        self.error = error
        self.calls: list[list[str]] = []

    def run(self, args: list[str]):
        self.calls.append(args)
        raise self.error


def _rbac_preview_context(tmp_path: Path) -> DailyAzureRuntimeContext:
    context = DailyAzureEnvironmentRebuild(
        _config(tmp_path), repository_root=tmp_path
    )._initial_context()
    return replace(
        context,
        foundry_account_name="fictional-intake-foundry",
        immutable_agent_version="7",
        environment_fingerprint="a" * 64,
    )


def _rbac_preview_plan(tmp_path: Path) -> ConsumerRbacPlan:
    context = _rbac_preview_context(tmp_path)
    subscription_id = "00000000-0000-0000-0000-000000000001"
    principal_id = "00000000-0000-0000-0000-000000000002"
    account_id = (
        f"/subscriptions/{subscription_id}/resourceGroups/{context.resource_group}/"
        "providers/Microsoft.CognitiveServices/accounts/"
        f"{context.foundry_account_name}"
    )
    project_id = f"{account_id}/projects/{context.foundry_project_name}"
    role_id = (
        f"/subscriptions/{subscription_id}/providers/"
        "Microsoft.Authorization/roleDefinitions/"
        "eed3b665-ab3a-47b6-8f48-c9382fb1dad6"
    )
    return ConsumerRbacPlan(
        subscription_id=subscription_id,
        resource_group=context.resource_group,
        web_app_name=context.web_app_name,
        principal_id=principal_id,
        web_app_resource_id=(
            f"/subscriptions/{subscription_id}/resourceGroups/{context.resource_group}/"
            f"providers/Microsoft.Web/sites/{context.web_app_name}"
        ),
        foundry_account_name=context.foundry_account_name,
        foundry_account_resource_id=account_id,
        foundry_project_name=context.foundry_project_name,
        foundry_project_resource_id=project_id,
        role_name="Foundry Agent Consumer",
        role_definition_id=role_id,
        role_assignment_name=deterministic_role_assignment_name(
            project_id, principal_id, role_id
        ),
        deployment_name="foundry-agent-consumer-rbac",
        existing_matching_assignments=0,
    )


def test_hosted_webjob_boundary_rejects_unadapted_coordinator_result() -> None:
    hosted = hosted_foundry_agent_webjob_execution
    command_runner = ExactCoordinatorCommandRunner(
        [
            daily_rebuild_service._CommandResult(
                0,
                json.dumps([{"name": hosted.WEBJOB_NAME}]),
                "",
            )
        ]
    )

    result = hosted.execute_hosted_foundry_agent_webjob(
        hosted.HostedFoundryAgentWebJobExecutionRequest(
            "live-discover",
            "fictional-daily-rg",
            "fictional-nurse-intake-web",
            Path(__file__).resolve().parents[1],
            "a" * 64,
        ),
        runner=command_runner,
    )

    assert result.ok is False
    assert result.category == "unexpected_error"
    assert result.remote_webjob_discovered is False
    assert len(command_runner.calls) == 1


def test_repository_webjob_discovery_adapts_result_and_parses_valid_output(
    tmp_path: Path,
) -> None:
    hosted = hosted_foundry_agent_webjob_execution
    command_runner = ExactCoordinatorCommandRunner(
        [
            daily_rebuild_service._CommandResult(
                0,
                json.dumps([{"name": hosted.WEBJOB_NAME}]),
                "ignored stderr",
            )
        ]
    )
    runner = RepositoryDailyAzureStageRunner(
        _config(tmp_path),
        repository_root=Path(__file__).resolve().parents[1],
        command_runner=command_runner,
    )
    context = _rbac_preview_context(tmp_path)

    result = runner.discover_webjob(context)

    assert result.ok is True
    assert result.reused is True
    assert result.webjob_triggered is False
    assert result.agent_invoked is False
    assert command_runner.calls == [
        [
            "az",
            "webapp",
            "webjob",
            "triggered",
            "list",
            "--resource-group",
            context.resource_group,
            "--name",
            context.web_app_name,
            "--query",
            "[].{name:name}",
            "--only-show-errors",
            "--output",
            "json",
        ]
    ]


def test_repository_webjob_adapter_preserves_strict_rejection_and_exceptions(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    context = _rbac_preview_context(tmp_path)
    structural_runner = CommandRunner(
        [
            (
                0,
                json.dumps(
                    [{"name": hosted_foundry_agent_webjob_execution.WEBJOB_NAME}]
                ),
                "",
            )
        ]
    )
    structural_result = RepositoryDailyAzureStageRunner(
        _config(tmp_path),
        repository_root=repository_root,
        command_runner=structural_runner,
    ).discover_webjob(context)
    raising_runner = RaisingCoordinatorCommandRunner(
        RuntimeError("sensitive runner failure")
    )
    raising_result = RepositoryDailyAzureStageRunner(
        _config(tmp_path),
        repository_root=repository_root,
        command_runner=raising_runner,
    ).discover_webjob(context)

    assert structural_result.category == "unexpected_error"
    assert raising_result.category == "unexpected_error"
    assert len(structural_runner.calls) == 1
    assert len(raising_runner.calls) == 1


@pytest.mark.parametrize(
    ("return_code", "stdout", "stderr", "category"),
    [
        (0, "[]", "", "remote_webjob_missing"),
        (
            0,
            json.dumps(
                [
                    {"name": "verify-hosted-foundry-agent"},
                    {"name": "verify-hosted-foundry-agent"},
                ]
            ),
            "",
            "remote_webjob_ambiguous",
        ),
        (0, "not-json", "", "response_parse_failed"),
        (127, "", "", "azure_cli_unavailable"),
        (1, "", "authorization denied", "authentication_or_authorization_failed"),
        (1, "", "request failed", "azure_request_failed"),
    ],
)
def test_repository_webjob_discovery_preserves_hosted_failure_categories(
    tmp_path: Path,
    return_code: int,
    stdout: str,
    stderr: str,
    category: str,
) -> None:
    command_runner = ExactCoordinatorCommandRunner(
        [daily_rebuild_service._CommandResult(return_code, stdout, stderr)]
    )
    runner = RepositoryDailyAzureStageRunner(
        _config(tmp_path),
        repository_root=Path(__file__).resolve().parents[1],
        command_runner=command_runner,
    )

    result = runner.discover_webjob(_rbac_preview_context(tmp_path))

    assert result.ok is False
    assert result.category == category
    assert len(command_runner.calls) == 1


@pytest.mark.parametrize(
    "method_name",
    ["discover_webjob", "trigger_webjob", "verify_hosted_agent"],
)
def test_every_repository_webjob_path_supplies_exact_hosted_result_type(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    method_name: str,
) -> None:
    hosted = hosted_foundry_agent_webjob_execution
    command_runner = ExactCoordinatorCommandRunner(
        [daily_rebuild_service._CommandResult(0, "opaque stdout", "opaque stderr")]
    )
    runner = RepositoryDailyAzureStageRunner(
        _config(tmp_path),
        repository_root=Path(__file__).resolve().parents[1],
        command_runner=command_runner,
    )
    adapted_runners = []

    def fake_execute(request, *, runner):
        adapted_runners.append(runner)
        outcome = runner.run(["boundary-command", request.mode])
        assert type(outcome) is hosted.CommandResult
        assert outcome == hosted.CommandResult(
            0, "opaque stdout", "opaque stderr"
        )
        return SimpleNamespace(
            ok=False,
            category="expected_test_stop",
            trigger_request_accepted=False,
            azure_operation_attempted=False,
        )

    monkeypatch.setattr(
        hosted,
        "execute_hosted_foundry_agent_webjob",
        fake_execute,
    )

    result = getattr(runner, method_name)(_rbac_preview_context(tmp_path))

    assert result.ok is False
    assert result.category == "expected_test_stop"
    assert len(adapted_runners) == 1
    expected_mode = {
        "discover_webjob": "live-discover",
        "trigger_webjob": "live-trigger",
        "verify_hosted_agent": "live-status",
    }[method_name]
    assert command_runner.calls == [["boundary-command", expected_mode]]


def _rbac_preview_payload(
    change_type: str,
    resource_type: str,
    *,
    subscription_id: str = "00000000-0000-0000-0000-000000000001",
    resource_group: str = "fictional-daily-rg",
    account_name: str = "fictional-intake-foundry",
    project_name: str = "fictional-intake-project",
    assignment_name: str = "6d2bb5b6-e3dc-5091-917e-1a8dae03329d",
    principal_id: str = "00000000-0000-0000-0000-000000000002",
    role_definition_id: str | None = None,
) -> str:
    role_definition_id = role_definition_id or (
        f"/subscriptions/{subscription_id}/providers/"
        "Microsoft.Authorization/roleDefinitions/"
        "eed3b665-ab3a-47b6-8f48-c9382fb1dad6"
    )
    return json.dumps(
        {
            "changes": [
                {
                    "changeType": change_type,
                    "resourceType": resource_type,
                    "resourceId": (
                        f"/subscriptions/{subscription_id}/"
                        f"resourceGroups/{resource_group}/providers/"
                        f"Microsoft.CognitiveServices/accounts/{account_name}/"
                        f"projects/{project_name}/providers/"
                        "Microsoft.Authorization/roleAssignments/"
                        f"{assignment_name}"
                    ),
                    "after": {
                        "properties": {
                            "principalId": principal_id,
                            "roleDefinitionId": role_definition_id,
                        }
                    },
                }
            ]
        }
    )


def test_repository_rbac_preview_accepts_only_one_exact_assignment_create(
    tmp_path: Path,
) -> None:
    command_runner = CommandRunner(
        [
            (
                0,
                _rbac_preview_payload(
                    "Create", "Microsoft.Authorization/roleAssignments"
                ),
                "",
            )
        ]
    )
    runner = RepositoryDailyAzureStageRunner(
        _config(tmp_path),
        repository_root=Path(__file__).resolve().parents[1],
        command_runner=command_runner,
    )

    result = runner.preview_rbac(
        _rbac_preview_context(tmp_path), _rbac_preview_plan(tmp_path)
    )

    assert result.ok is True
    assert result.approval_binding is not None
    assert len(result.approval_binding) == 64
    assert len(command_runner.calls) == 1
    assert "what-if" in command_runner.calls[0]


def test_repository_rbac_preview_binding_is_stable_for_json_object_key_order(
    tmp_path: Path,
) -> None:
    original = json.loads(
        _rbac_preview_payload(
            "Create", "Microsoft.Authorization/roleAssignments"
        )
    )
    reordered = {
        "changes": [
            dict(reversed(tuple(original["changes"][0].items())))
        ]
    }
    bindings = []
    for payload in (original, reordered):
        runner = RepositoryDailyAzureStageRunner(
            _config(tmp_path),
            repository_root=Path(__file__).resolve().parents[1],
            command_runner=CommandRunner([(0, json.dumps(payload), "")]),
        )
        result = runner.preview_rbac(
            _rbac_preview_context(tmp_path), _rbac_preview_plan(tmp_path)
        )
        bindings.append(result.approval_binding)

    assert bindings[0] is not None
    assert bindings[0] == bindings[1]


def test_production_rbac_preview_binding_includes_topology_and_manual_review() -> None:
    proof = ConsumerRbacPreviewProof(
        topology="exact_create",
        assignment_contents_proved=True,
        manual_review_required=False,
        record_count=1,
        create_count=1,
        modify_count=0,
        no_change_count=0,
        delete_count=0,
        ignore_count=0,
        deploy_count=0,
        unsupported_count=0,
    )
    binding = daily_rebuild_service._consumer_rbac_preview_binding(
        proof,
        (),
        delete_review_required=False,
    )
    changed_topology = daily_rebuild_service._consumer_rbac_preview_binding(
        replace(proof, topology="expected_ignore_plus_unsupported"),
        (),
        delete_review_required=False,
    )
    changed_manual_review = daily_rebuild_service._consumer_rbac_preview_binding(
        replace(proof, manual_review_required=True),
        (),
        delete_review_required=False,
    )

    assert len({binding, changed_topology, changed_manual_review}) == 3
    assert daily_rebuild_service._consumer_rbac_preview_proof_valid(
        replace(proof, topology="expected_ignore_plus_unsupported")
    ) is False
    assert daily_rebuild_service._consumer_rbac_preview_proof_valid(
        replace(proof, manual_review_required=True)
    ) is False
    assert daily_rebuild_service._consumer_rbac_preview_proof_valid(
        replace(proof, topology="unknown")
    ) is False


def test_repository_rbac_preview_consumes_parser_topology_without_copying_matrix() -> None:
    source = inspect.getsource(RepositoryDailyAzureStageRunner.preview_rbac)

    assert "preview_topology" in source
    assert "cosmos_account" not in source
    assert "foundry_project_reference" not in source
    assert "expected_ignores" not in source


@pytest.mark.parametrize(
    "overrides",
    [
        {"subscription_id": "00000000-0000-0000-0000-000000000099"},
        {"resource_group": "unrelated-rg"},
        {"account_name": "unrelated-account"},
        {"project_name": "unrelated-project"},
        {"assignment_name": "00000000-0000-0000-0000-000000000099"},
        {
            "role_definition_id": (
                "/subscriptions/00000000-0000-0000-0000-000000000001/"
                "providers/Microsoft.Authorization/roleDefinitions/"
                "00000000-0000-0000-0000-000000000099"
            )
        },
        {"principal_id": "00000000-0000-0000-0000-000000000099"},
    ],
)
def test_repository_rbac_preview_rejects_same_type_with_wrong_exact_identity(
    tmp_path: Path, overrides: dict[str, str]
) -> None:
    runner = RepositoryDailyAzureStageRunner(
        _config(tmp_path),
        repository_root=Path(__file__).resolve().parents[1],
        command_runner=CommandRunner(
            [
                (
                    0,
                    _rbac_preview_payload(
                        "Create",
                        "Microsoft.Authorization/roleAssignments",
                        **overrides,
                    ),
                    "",
                )
            ]
        ),
    )

    result = runner.preview_rbac(
        _rbac_preview_context(tmp_path), _rbac_preview_plan(tmp_path)
    )

    assert result.ok is False
    assert result.category == "what_if_parse_failed"


def test_repository_rbac_deployment_consumes_only_the_exact_current_preview_binding(
    tmp_path: Path,
) -> None:
    command_runner = CommandRunner(
        [
            (
                0,
                _rbac_preview_payload(
                    "Create", "Microsoft.Authorization/roleAssignments"
                ),
                "",
            )
        ]
    )
    runner = RepositoryDailyAzureStageRunner(
        _config(tmp_path),
        repository_root=Path(__file__).resolve().parents[1],
        command_runner=command_runner,
    )
    context = _rbac_preview_context(tmp_path)
    plan = _rbac_preview_plan(tmp_path)
    preview = runner.preview_rbac(context, plan)
    assert preview.approval_binding is not None

    changed = runner.deploy_rbac(context, "b" * 64, plan)

    assert changed.category == "consumer_rbac_preview_changed"
    assert len(command_runner.calls) == 1


@pytest.mark.parametrize(
    ("stdout", "expected_category"),
    [
        ("not-json", "what_if_parse_failed"),
        (
            _rbac_preview_payload(
                "Delete", "Microsoft.Authorization/roleAssignments"
            ),
            "what_if_parse_failed",
        ),
        (
            json.dumps(
                {
                    "changes": [
                        {
                            "changeType": "Create",
                            "resourceType": "Microsoft.Storage/storageAccounts",
                            "resourceId": (
                                "/subscriptions/00000000-0000-0000-0000-000000000001/"
                                "resourceGroups/fictional-daily-rg/providers/"
                                "Microsoft.Storage/storageAccounts/unrelated"
                            ),
                        }
                    ]
                }
            ),
            "what_if_parse_failed",
        ),
        (
            _rbac_preview_payload(
                "Unsupported", "Microsoft.Authorization/roleAssignments"
            ),
            "what_if_parse_failed",
        ),
    ],
)
def test_repository_rbac_preview_rejects_malformed_delete_unrelated_or_unknown(
    tmp_path: Path, stdout: str, expected_category: str
) -> None:
    runner = RepositoryDailyAzureStageRunner(
        _config(tmp_path),
        repository_root=Path(__file__).resolve().parents[1],
        command_runner=CommandRunner([(0, stdout, "raw stderr")]),
    )

    result = runner.preview_rbac(
        _rbac_preview_context(tmp_path), _rbac_preview_plan(tmp_path)
    )

    assert result.ok is False
    assert result.category == expected_category
    assert result.approval_binding is None


def test_repository_runner_verifies_exact_active_subscription(tmp_path: Path) -> None:
    command_runner = CommandRunner(
        [(0, '{"subscription":"Fictional Development","state":"Enabled","isDefault":true}', "")]
    )
    runner = RepositoryDailyAzureStageRunner(
        _config(tmp_path), repository_root=tmp_path, command_runner=command_runner
    )

    result = runner.verify_account(
        DailyAzureEnvironmentRebuild(_config(tmp_path), repository_root=tmp_path)._initial_context()
    )

    assert result.ok is True
    assert command_runner.calls[0][:3] == ["az", "account", "show"]
    assert "--query" in command_runner.calls[0]
    assert "--only-show-errors" in command_runner.calls[0]


def test_repository_runner_creates_absent_resource_group_exactly_once(
    tmp_path: Path,
) -> None:
    command_runner = CommandRunner(
        [
            (0, "false\n", ""),
            (0, "false\n", ""),
            (
                0,
                '{"location":"eastus2","provisioningState":"Succeeded",'
                '"ownershipTag":"fictional-daily-validation"}',
                "",
            ),
        ]
    )
    config = _config(tmp_path)
    runner = RepositoryDailyAzureStageRunner(
        config, repository_root=tmp_path, command_runner=command_runner
    )
    context = DailyAzureEnvironmentRebuild(
        config, repository_root=tmp_path
    )._initial_context()

    inspected = runner.inspect_resource_group(context)
    result = runner.create_resource_group(context)

    assert inspected.state == "absent"
    assert result.ok is True
    assert result.mutation_made is True
    assert [call[:3] for call in command_runner.calls] == [
        ["az", "group", "exists"],
        ["az", "group", "exists"],
        ["az", "group", "create"],
    ]


def test_repository_runner_reuses_only_matching_resource_group_location(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    context = DailyAzureEnvironmentRebuild(
        config, repository_root=tmp_path
    )._initial_context()
    matching = CommandRunner(
        [
            (0, "true\n", ""),
            (
                0,
                '{"location":"East US 2","provisioningState":"Succeeded",'
                '"ownershipTag":"fictional-daily-validation"}',
                "",
            ),
        ]
    )
    result = RepositoryDailyAzureStageRunner(
        config, repository_root=tmp_path, command_runner=matching
    ).inspect_resource_group(context)
    assert result.ok is True
    assert result.reused is True
    assert all(call[:3] != ["az", "group", "create"] for call in matching.calls)

    mismatch = CommandRunner(
        [
            (0, "true\n", ""),
            (0, '{"location":"centralus","provisioningState":"Succeeded"}', ""),
        ]
    )
    failed = RepositoryDailyAzureStageRunner(
        config, repository_root=tmp_path, command_runner=mismatch
    ).inspect_resource_group(context)
    assert failed.category == "resource_group_location_mismatch"


@pytest.mark.parametrize("ownership", (None, "different-purpose", 7))
def test_repository_runner_never_adopts_unowned_resource_group(
    tmp_path: Path,
    ownership: object,
) -> None:
    config = _config(tmp_path)
    context = DailyAzureEnvironmentRebuild(
        config, repository_root=tmp_path
    )._initial_context()
    command_runner = CommandRunner(
        [
            (0, "true\n", ""),
            (
                0,
                json.dumps(
                    {
                        "location": "eastus2",
                        "provisioningState": "Succeeded",
                        "ownershipTag": ownership,
                    }
                ),
                "",
            ),
        ]
    )

    result = RepositoryDailyAzureStageRunner(
        config, repository_root=tmp_path, command_runner=command_runner
    ).inspect_resource_group(context)

    assert result.category == "resource_group_ownership_approval_required"
    assert all(call[:3] != ["az", "group", "create"] for call in command_runner.calls)


def test_repository_preview_adapters_require_real_allowlisted_resource_evidence(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    config = _config(tmp_path)
    context = DailyAzureEnvironmentRebuild(
        config,
        repository_root=repository_root,
    )._initial_context()
    base = (
        "/subscriptions/private/resourceGroups/fictional-daily-rg/providers/"
        "Microsoft.CognitiveServices/accounts/fictional-intake-foundry"
    )
    expected_changes = [
        {"changeType": "Create", "resourceId": base},
        {
            "changeType": "Create",
            "resourceId": f"{base}/projects/fictional-intake-project",
        },
        {
            "changeType": "Create",
            "resourceId": f"{base}/deployments/nurse-intake-gpt-5-mini",
        },
    ]
    unrelated_id = (
        "/subscriptions/private/resourceGroups/private/providers/"
        "Microsoft.KeyVault/vaults/unexpected"
    )

    expected_runner = RepositoryDailyAzureStageRunner(
        config,
        repository_root=repository_root,
        command_runner=CommandRunner(
                [(0, json.dumps({"changes": expected_changes}), "")]
        ),
    )
    expected_runner._foundry_parameters = _foundry_parameters(tmp_path, repository_root)
    expected = expected_runner.plan_foundry(context)

    unrelated_runner = RepositoryDailyAzureStageRunner(
        config,
        repository_root=repository_root,
        command_runner=CommandRunner(
            [(0, json.dumps({"changes": [{"changeType": "Create", "resourceId": unrelated_id}]}), "")]
        ),
    )
    unrelated_runner._foundry_parameters = _foundry_parameters(tmp_path, repository_root)
    unrelated = unrelated_runner.plan_foundry(context)

    assert safe_automatic_plan(expected) is True
    assert safe_automatic_plan(unrelated) is False


def test_repository_adapter_marks_deployment_parse_failure_mutation_ambiguous(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config(tmp_path)
    repository_root = Path(__file__).resolve().parents[1]
    runner = RepositoryDailyAzureStageRunner(config, repository_root=repository_root)
    runner._foundry_parameters = (
        repository_root / "infra/foundry-only.example.bicepparam"
    )
    monkeypatch.setattr(
        "scripts.deploy_foundry_infra.execute",
        lambda *args, **kwargs: {
            "ok": False,
            "category": "deployment_output_invalid",
        },
    )
    context = DailyAzureEnvironmentRebuild(
        config,
        repository_root=repository_root,
    )._initial_context()

    result = runner.deploy_foundry(context)

    assert result.ok is False
    assert result.attempted is True
    assert result.mutation_made is None


def test_repository_package_adapter_returns_validated_package_binding(
    tmp_path: Path,
) -> None:
    repository_root = _package_source_tree(tmp_path)
    config = _config(tmp_path)
    command_runner = CommandRunner([])
    runner = RepositoryDailyAzureStageRunner(
        config,
        repository_root=repository_root,
        command_runner=command_runner,
    )
    context = DailyAzureEnvironmentRebuild(
        config,
        repository_root=repository_root,
        local_contract_checker=lambda _root: (),
    )._initial_context()

    result = runner.build_package(context)

    assert result.ok is True
    assert result.category == "success"
    assert result.approval_binding is not None
    assert len(result.approval_binding) == 64
    assert runner._package is not None
    assert result.approval_binding == runner._package.sha256
    assert runner._expected_application_artifact_digest is not None
    assert len(runner._expected_application_artifact_digest) == 64
    assert command_runner.calls == []


def test_repository_package_adapter_preserves_package_safety_category(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    command_runner = CommandRunner([])
    runner = RepositoryDailyAzureStageRunner(
        config,
        repository_root=tmp_path,
        command_runner=command_runner,
    )
    context = DailyAzureEnvironmentRebuild(
        config,
        repository_root=tmp_path,
        local_contract_checker=lambda _root: (),
    )._initial_context()

    result = runner.build_package(context)

    assert result.ok is False
    assert result.category == "incomplete_package"
    assert result.approval_binding is None
    assert command_runner.calls == []


def _foundry_parameters(tmp_path: Path, repository_root: Path) -> Path:
    path = tmp_path / "foundry-only.bicepparam"
    path.write_text(
        f"using '{repository_root / 'infra/foundry-only.bicep'}'\n"
        "param foundryAccountName = 'fictional-intake-foundry'\n"
        "param foundryProjectName = 'fictional-intake-project'\n"
        "param modelDeploymentName = 'nurse-intake-gpt-5-mini'\n"
        "param modelName = 'gpt-5-mini'\n"
        "param modelVersion = '2025-08-07'\n"
        "param modelPublisherFormat = 'OpenAI'\n"
        "param modelSkuName = 'GlobalStandard'\n"
        "param modelCapacity = 1\n"
    )
    return path


def test_coordinator_source_has_no_forbidden_operation_path() -> None:
    source = Path(
        "src/app/services/daily_azure_environment_rebuild.py"
    ).read_text()
    for forbidden in (
        "invoke_hosted",
        "delete_resource_group",
        "sleep(",
        "shell=True",
    ):
        assert forbidden not in source
