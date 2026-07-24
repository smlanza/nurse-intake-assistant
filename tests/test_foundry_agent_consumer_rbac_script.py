import json
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import scripts.deploy_foundry_agent_consumer_rbac as script
from src.app.services.foundry_agent_consumer_rbac_deployment import (
    deterministic_role_assignment_name,
)


class Runner:
    def __init__(self, results):
        self.results = list(results)
        self.calls: list[list[str]] = []

    def run(self, args):
        self.calls.append(args)
        return self.results.pop(0)


def _receipt():
    return SimpleNamespace(
        requested_foundry_account_name="operator-base",
        foundry_account_name="operator-base-abc123",
        foundry_account_name_generated=True,
        resource_group="fictional-rg",
        foundry_project_name="fictional-project",
        web_app_name="fictional-web",
    )


def _evidence(*, principal: str = "principal-a"):
    subscription = "00000000-0000-0000-0000-000000000001"
    project = (
        f"/subscriptions/{subscription}/resourceGroups/fictional-rg/providers/"
        "Microsoft.CognitiveServices/accounts/operator-base-abc123/"
        "projects/fictional-project"
    )
    role = (
        f"/subscriptions/{subscription}/providers/"
        "Microsoft.Authorization/roleDefinitions/"
        "eed3b665-ab3a-47b6-8f48-c9382fb1dad6"
    )
    return script.FoundryAgentConsumerRbacDeploymentEvidence(
        subscription_id=subscription,
        foundry_project_resource_id=project,
        web_app_principal_id=principal,
        role_definition_id=role,
        role_assignment_name=(
            deterministic_role_assignment_name(project, principal, role)
        ),
        deployment_name=script.DEPLOYMENT_NAME,
    )


def _preview(*, ok: bool = True):
    return SimpleNamespace(
        ok=ok,
        category="success" if ok else "what_if_parse_failed",
        mode="what-if",
        template_valid=True,
        azure_operation_attempted=True,
        deployment_request_accepted=False,
        preview_topology="exact_create" if ok else None,
        assignment_contents_proved=True if ok else None,
        manual_review_required=False,
        create_count=1 if ok else None,
        modify_count=0 if ok else None,
        no_change_count=0 if ok else None,
        delete_count=0 if ok else None,
        ignore_count=0 if ok else None,
        deploy_count=0 if ok else None,
        unsupported_count=0 if ok else None,
        change_evidence=(object(),) if ok else (),
    )


def _deployment(*, accepted: bool = True):
    return SimpleNamespace(
        ok=accepted,
        category="success" if accepted else "deployment_failed",
        mode="live",
        azure_operation_attempted=True,
        deployment_request_accepted=accepted,
    )


def _verified_assignment(*, ok: bool = True, count: int = 1):
    return SimpleNamespace(
        ok=ok,
        category="success" if ok else "assignment_missing",
        web_app_identity_present=True,
        foundry_project_scope_resolved=True,
        consumer_assignment_present=ok,
        consumer_assignment_scope_matches=ok,
        consumer_role_matches=ok,
        matching_assignment_count=count,
    )


def _patch_handoff(monkeypatch) -> None:
    monkeypatch.setattr(
        script,
        "load_daily_azure_config",
        lambda path, repository_root: SimpleNamespace(
            foundry_account_name="operator-base"
        ),
    )
    monkeypatch.setattr(
        script,
        "load_matching_daily_azure_readiness_receipt",
        lambda path, config: _receipt(),
    )


def test_check_request_uses_effective_account_only_from_matching_receipt(
    monkeypatch,
    capsys,
) -> None:
    captured = {}
    monkeypatch.setattr(
        script,
        "load_daily_azure_config",
        lambda path, repository_root: SimpleNamespace(
            foundry_account_name="operator-base"
        ),
    )
    monkeypatch.setattr(
        script,
        "load_matching_daily_azure_readiness_receipt",
        lambda path, config: _receipt(),
    )

    original_deploy = script.deploy_foundry_agent_consumer_rbac

    def capture(request, **kwargs):
        captured["request"] = request
        return original_deploy(request, **kwargs)

    monkeypatch.setattr(
        script,
        "deploy_foundry_agent_consumer_rbac",
        capture,
    )

    status = script.main(
        [
            "--check",
            "--config",
            "ignored.env",
            "--readiness-receipt",
            "receipt.json",
            "--json",
        ]
    )

    assert status == 0
    request = captured["request"]
    assert request.foundry_account_name == "operator-base-abc123"
    assert request.foundry_account_name != "operator-base"
    payload = json.loads(capsys.readouterr().out)
    assert payload["rbac_handoff_validated"] is True
    assert payload["requested_foundry_account_name"] == "operator-base"
    assert payload["foundry_account_name"] == "operator-base-abc123"


def test_live_reuse_skips_preview_prompt_and_deployment(
    monkeypatch,
    capsys,
) -> None:
    _patch_handoff(monkeypatch)
    monkeypatch.setattr(script, "_create_azure_cli_runner", lambda: Runner([]))
    monkeypatch.setattr(script, "_account_matches_handoff", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        script,
        "_fresh_evidence",
        lambda *args, **kwargs: (
            None,
            "consumer_rbac_assignment_already_present",
        ),
    )
    monkeypatch.setattr(
        script,
        "prompt_for_rbac_approval",
        lambda: (_ for _ in ()).throw(AssertionError("reuse must not prompt")),
        raising=False,
    )
    monkeypatch.setattr(
        script,
        "deploy_foundry_agent_consumer_rbac",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("reuse must not preview or deploy")
        ),
    )

    status = script.main(
        ["--live", "--config", "ignored.env", "--json"]
    )

    payload = json.loads(capsys.readouterr().out)
    assert status == 0
    assert payload["assignment_reused"] is True
    assert payload["azure_mutation_made"] is False
    assert payload["deployment_request_accepted"] is False


def test_missing_assignment_runs_complete_approved_pipeline_in_order(
    monkeypatch,
    capsys,
) -> None:
    _patch_handoff(monkeypatch)
    runner = Runner([])
    monkeypatch.setattr(script, "_create_azure_cli_runner", lambda: runner)
    events: list[str] = []
    monkeypatch.setattr(
        script,
        "_account_matches_handoff",
        lambda *args, **kwargs: events.append("account") is None or True,
    )
    evidence = _evidence()
    evidence_reads = iter(((evidence, None), (evidence, None)))
    monkeypatch.setattr(
        script,
        "_fresh_evidence",
        lambda *args, **kwargs: (
            events.append("evidence"),
            next(evidence_reads),
        )[1],
    )

    def deploy(request, runner):
        events.append(request.mode)
        return _preview() if request.mode == "what-if" else _deployment()

    monkeypatch.setattr(script, "deploy_foundry_agent_consumer_rbac", deploy)
    monkeypatch.setattr(
        script,
        "prompt_for_rbac_approval",
        lambda: events.append("approval") is None or True,
        raising=False,
    )
    monkeypatch.setattr(
        script,
        "verify_foundry_agent_consumer_rbac",
        lambda request, runner: (
            events.append("post-verify"),
            _verified_assignment(),
        )[1],
    )

    status = script.main(["--live", "--config", "ignored.env", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert status == 0
    assert events == [
        "account",
        "evidence",
        "what-if",
        "approval",
        "account",
        "evidence",
        "live",
        "post-verify",
    ]
    assert payload["assignment_reused"] is False
    assert payload["assignment_verified"] is True
    assert payload["azure_mutation_made"] is True
    assert payload["deployment_request_accepted"] is True


def test_unsafe_preview_fails_before_prompt_or_mutation(
    monkeypatch,
    capsys,
) -> None:
    _patch_handoff(monkeypatch)
    monkeypatch.setattr(script, "_create_azure_cli_runner", lambda: Runner([]))
    monkeypatch.setattr(script, "_account_matches_handoff", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        script,
        "_fresh_evidence",
        lambda *args, **kwargs: (_evidence(), None),
    )
    calls: list[str] = []
    monkeypatch.setattr(
        script,
        "deploy_foundry_agent_consumer_rbac",
        lambda request, runner: (
            calls.append(request.mode),
            _preview(ok=False),
        )[1],
    )
    monkeypatch.setattr(
        script,
        "prompt_for_rbac_approval",
        lambda: (_ for _ in ()).throw(AssertionError("unsafe preview prompted")),
        raising=False,
    )

    status = script.main(["--live", "--config", "ignored.env", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert status == 2
    assert calls == ["what-if"]
    assert payload["category"] == "consumer_rbac_preview_unsafe"
    assert payload["azure_mutation_made"] is False


def test_declined_approval_makes_no_mutation(
    monkeypatch,
    capsys,
) -> None:
    _patch_handoff(monkeypatch)
    monkeypatch.setattr(script, "_create_azure_cli_runner", lambda: Runner([]))
    monkeypatch.setattr(script, "_account_matches_handoff", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        script,
        "_fresh_evidence",
        lambda *args, **kwargs: (_evidence(), None),
    )
    calls: list[str] = []
    monkeypatch.setattr(
        script,
        "deploy_foundry_agent_consumer_rbac",
        lambda request, runner: (
            calls.append(request.mode),
            _preview(),
        )[1],
    )
    monkeypatch.setattr(
        script,
        "prompt_for_rbac_approval",
        lambda: False,
        raising=False,
    )

    status = script.main(["--live", "--config", "ignored.env", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert status == 2
    assert calls == ["what-if"]
    assert payload["category"] == "consumer_rbac_operator_declined"
    assert payload["azure_mutation_made"] is False


def test_changed_approved_evidence_fails_before_deployment(
    monkeypatch,
    capsys,
) -> None:
    _patch_handoff(monkeypatch)
    monkeypatch.setattr(script, "_create_azure_cli_runner", lambda: Runner([]))
    monkeypatch.setattr(script, "_account_matches_handoff", lambda *args, **kwargs: True)
    reads = iter(((_evidence(), None), (_evidence(principal="principal-b"), None)))
    monkeypatch.setattr(
        script,
        "_fresh_evidence",
        lambda *args, **kwargs: next(reads),
    )
    calls: list[str] = []

    def deploy(request, runner):
        calls.append(request.mode)
        assert request.mode == "what-if"
        return _preview()

    monkeypatch.setattr(script, "deploy_foundry_agent_consumer_rbac", deploy)
    monkeypatch.setattr(
        script,
        "prompt_for_rbac_approval",
        lambda: True,
        raising=False,
    )

    status = script.main(["--live", "--config", "ignored.env", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert status == 2
    assert calls == ["what-if"]
    assert payload["category"] == "approval_evidence_stale"
    assert payload["azure_mutation_made"] is False


def test_deployment_acceptance_requires_successful_post_verification(
    monkeypatch,
    capsys,
) -> None:
    _patch_handoff(monkeypatch)
    monkeypatch.setattr(script, "_create_azure_cli_runner", lambda: Runner([]))
    monkeypatch.setattr(script, "_account_matches_handoff", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        script,
        "_fresh_evidence",
        lambda *args, **kwargs: (_evidence(), None),
    )
    monkeypatch.setattr(
        script,
        "deploy_foundry_agent_consumer_rbac",
        lambda request, runner: (
            _preview() if request.mode == "what-if" else _deployment()
        ),
    )
    monkeypatch.setattr(
        script,
        "prompt_for_rbac_approval",
        lambda: True,
        raising=False,
    )
    monkeypatch.setattr(
        script,
        "verify_foundry_agent_consumer_rbac",
        lambda request, runner: _verified_assignment(ok=False, count=0),
    )

    status = script.main(["--live", "--config", "ignored.env", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert status == 2
    assert payload["category"] == "consumer_rbac_verification_failed"
    assert payload["deployment_request_accepted"] is True
    assert payload["assignment_verified"] is False
    assert payload["ok"] is False


def test_approval_prompt_is_sanitized_and_uses_stderr_channel() -> None:
    source = StringIO("yes\n")
    destination = StringIO()

    assert script.prompt_for_rbac_approval(
        input_stream=source,
        output_stream=destination,
    )
    output = destination.getvalue()
    for expected in (
        "FOUNDRY AGENT CONSUMER RBAC",
        "Coordinator readiness verified: yes",
        "Web App system identity verified: yes",
        "Foundry project scope verified: yes",
        "Existing exact direct assignment: no",
        "Assignment required: yes",
        "Exact assignment independently proved: yes",
        "Other unsupported records: 0",
        "Destructive or unrelated changes: no",
        "Proceed? [y/N]",
    ):
        assert expected in output
    for sensitive in (
        "/subscriptions/",
        "principal-a",
        "roleDefinitions",
        "00000000-0000-0000-0000-000000000001",
    ):
        assert sensitive not in output


def test_focused_rbac_command_rejects_missing_or_stale_receipt(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(
        script,
        "load_daily_azure_config",
        lambda path, repository_root: SimpleNamespace(
            foundry_account_name="operator-base"
        ),
    )
    monkeypatch.setattr(
        script,
        "load_matching_daily_azure_readiness_receipt",
        lambda path, config: None,
    )

    status = script.main(
        [
            "--live",
            "--config",
            "ignored.env",
            "--readiness-receipt",
            "receipt.json",
            "--json",
        ]
    )

    assert status == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["category"] == "rbac_handoff_invalid"
    assert payload["azure_operation_attempted"] is False


def test_effective_account_is_reread_directly_and_must_match_exact_scope() -> None:
    account_id = (
        "/subscriptions/00000000-0000-0000-0000-000000000001/"
        "resourceGroups/fictional-rg/providers/"
        "Microsoft.CognitiveServices/accounts/operator-base-abc123"
    )
    runner = Runner(
        [
            SimpleNamespace(
                return_code=0,
                stdout=json.dumps(
                    {
                        "name": "operator-base-abc123",
                        "id": account_id,
                    }
                ),
                stderr="",
            )
        ]
    )

    assert script._account_matches_handoff(
        runner,
        resource_group="fictional-rg",
        foundry_account_name="operator-base-abc123",
    )
    assert runner.calls[0][:5] == [
        "az",
        "cognitiveservices",
        "account",
        "show",
        "--resource-group",
    ]

    wrong = Runner(
        [
            SimpleNamespace(
                return_code=0,
                stdout=json.dumps(
                    {
                        "name": "operator-base-abc123",
                        "id": account_id.replace(
                            "resourceGroups/fictional-rg",
                            "resourceGroups/different-rg",
                        ),
                    }
                ),
                stderr="",
            )
        ]
    )
    assert not script._account_matches_handoff(
        wrong,
        resource_group="fictional-rg",
        foundry_account_name="operator-base-abc123",
    )


def test_fresh_rbac_evidence_resolves_child_under_effective_account(
    monkeypatch,
) -> None:
    captured = {}
    subscription_id = "00000000-0000-0000-0000-000000000001"
    principal_id = "00000000-0000-0000-0000-000000000002"
    project_id = (
        f"/subscriptions/{subscription_id}/resourceGroups/fictional-rg/"
        "providers/Microsoft.CognitiveServices/accounts/"
        "operator-base-abc123/projects/fictional-project"
    )
    role_id = (
        f"/subscriptions/{subscription_id}/providers/"
        "Microsoft.Authorization/roleDefinitions/"
        "eed3b665-ab3a-47b6-8f48-c9382fb1dad6"
    )

    def verify(request, runner):
        captured["request"] = request
        return SimpleNamespace(
            ok=False,
            category="assignment_missing",
            web_app_identity_present=True,
            foundry_project_scope_resolved=True,
            matching_assignment_count=0,
            subscription_id=subscription_id,
            foundry_project_resource_id=project_id,
            principal_id=principal_id,
            role_definition_id=role_id,
        )

    monkeypatch.setattr(
        script,
        "verify_foundry_agent_consumer_rbac",
        verify,
    )
    evidence, failure = script._fresh_evidence(
        Runner([]),
        resource_group="fictional-rg",
        web_app_name="fictional-web",
        foundry_account_name="operator-base-abc123",
        foundry_project_name="fictional-project",
    )

    assert failure is None
    assert evidence is not None
    assert captured["request"].foundry_account_name == "operator-base-abc123"
    assert (
        evidence.foundry_project_resource_id
        == project_id
    )
