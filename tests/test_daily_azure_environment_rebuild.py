import json
import os
from dataclasses import replace
from pathlib import Path

import pytest

from src.app.services.daily_azure_environment_rebuild import (
    ChangeEvidence,
    REBUILD_OPERATION,
    ConfigValidationError,
    DailyAzureEnvironmentRebuild,
    DailyAzureEnvironmentRebuildResult,
    DailyAzureRuntimeContext,
    PlanResult,
    RepositoryDailyAzureStageRunner,
    RuntimeUpdates,
    StageResult,
    load_daily_azure_config,
    safe_automatic_plan,
    safe_guided_plan,
    write_runtime_session_file,
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
        self.foundry_absent = True
        self.web_app_absent = True
        self.rbac_absent = True
        self.resource_group_absent = True
        self.plan_overrides: dict[str, PlanResult] = {}
        self.contexts: dict[str, DailyAzureRuntimeContext] = {}

    def _stage(self, name: str, context: DailyAzureRuntimeContext) -> StageResult:
        self.calls.append(name)
        self.contexts[name] = context
        if self.fail_at == name:
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

    def build_package(self, context):
        result = self._stage("build_package", context)
        return replace(result, approval_binding="package-a") if result.ok else result

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
        if result.ok and self.rbac_absent:
            return StageResult.absent("rbac_absent")
        return result

    def plan_rbac(self, context):
        self._stage("plan_rbac", context)
        return self.plan_overrides.get(
            "plan_rbac", PlanResult(unsupported_count=1)
        )

    def deploy_rbac(self, context):
        result = self._stage("deploy_rbac", context)
        if result.ok:
            self.rbac_absent = False
            return replace(result, mutation_made=True)
        return result

    def discover_webjob(self, context):
        return self._stage("discover_webjob", context)


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
        "deploy_web_app",
        "verify_web_app_configuration",
        "build_package",
        "deploy_code",
        "verify_readiness",
        "verify_rbac",
        "discover_webjob",
    ]
    payload = result.to_json_dict()
    assert payload["ok"] is True
    assert payload["daily_environment_ready"] is True
    assert payload["application_artifact_current"] is True
    assert payload["application_deployment_attempted"] is True
    assert payload["application_deployment_accepted"] is True
    assert payload["application_deployment_reused"] is False
    assert payload["readiness_declaration"] == "DAILY AZURE ENVIRONMENT READY"
    assert payload["agent_invoked"] is False
    assert payload["webjob_triggered"] is False
    assert approval_stages == [
        "resource_group",
        "foundry_deployment",
        "web_app_deployment",
        "application_code_deployment",
    ]
    serialized = json.dumps(payload)
    for hidden in (
        "fictional-account",
        "fictional-daily-rg",
        "fictional-nurse-intake-web",
        "api/projects",
        "/agents/",
        '"7"',
    ):
        assert hidden not in serialized


def test_existing_environment_reuses_without_infrastructure_or_rbac_mutation(
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
    assert "plan_rbac" not in runner.calls
    assert "deploy_rbac" not in runner.calls


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


def test_foundry_delete_stops_without_prompt_or_deployment(tmp_path: Path) -> None:
    runner = FakeRunner()
    runner.resource_group_absent = False
    runner.plan_overrides["plan_foundry"] = PlanResult(
        delete_count=1,
        exact_topology_match=True,
        change_evidence=(
            _exact_change("Delete", "foundry_account", "foundry"),
        ),
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

    assert result.category == "unsafe_foundry_plan"
    assert prompts == []
    assert "deploy_foundry" not in runner.calls


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


def test_missing_rbac_unsupported_preview_requires_manual_workflow(
    tmp_path: Path,
) -> None:
    runner = FakeRunner()
    runner.foundry_absent = False
    runner.web_app_absent = False

    result = DailyAzureEnvironmentRebuild(
        _config(tmp_path),
        repository_root=tmp_path,
        local_contract_checker=lambda _root: (),
    ).live(runner, approver=lambda _summary: True)

    assert result.category == "manual_rbac_action_required"
    assert "plan_rbac" not in runner.calls
    assert "deploy_rbac" not in runner.calls


@pytest.mark.parametrize(
    "plan",
    [
        PlanResult(),
        PlanResult(
            no_change_count=1,
            change_evidence=(
                ChangeEvidence("NoChange", "consumer_role_assignment", "consumer_rbac", True),
            ),
        ),
        PlanResult(
            create_count=1,
            change_evidence=(
                ChangeEvidence("Create", "consumer_role_assignment", "consumer_rbac", True),
            ),
        ),
    ],
)
def test_missing_rbac_always_stops_for_manual_workflow(
    tmp_path: Path,
    plan: PlanResult,
) -> None:
    runner = FakeRunner()
    runner.foundry_absent = False
    runner.web_app_absent = False
    runner.plan_overrides["plan_rbac"] = plan

    result = DailyAzureEnvironmentRebuild(
        _config(tmp_path),
        repository_root=tmp_path,
        local_contract_checker=lambda _root: (),
    ).live(runner, approver=lambda _summary: True)

    assert result.category == "manual_rbac_action_required"
    assert "plan_rbac" not in runner.calls
    assert "deploy_rbac" not in runner.calls
    assert result.daily_environment_ready is False


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
        "verify_rbac",
        "discover_webjob",
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
    rbac_context = runner.contexts["verify_rbac"]
    assert rbac_context.foundry_account_name == "fictional-account"
    assert json.dumps(result.to_json_dict()).find("fictional-account") == -1


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


def test_reused_package_claim_cannot_skip_current_deployment(
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

    assert result.category == "application_provenance_invalid"
    assert result.application_deployment_reused is True
    assert result.application_artifact_current is False
    assert result.daily_environment_ready is False
    assert "verify_readiness" not in runner.calls


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
        "live-trigger",
        "live-status",
        "invoke_hosted",
        "delete_resource_group",
        "sleep(",
        "shell=True",
    ):
        assert forbidden not in source
