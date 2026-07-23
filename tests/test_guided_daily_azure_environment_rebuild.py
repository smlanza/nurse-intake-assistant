from io import StringIO

import pytest

from scripts.rebuild_daily_azure_environment import prompt_for_stage_approval
from scripts.rebuild_daily_azure_environment import _parse_args
from src.app.services.daily_azure_environment_rebuild import (
    ApprovalSummary,
    DailyAzureEnvironmentRebuildResult,
    GuidedApprovalSession,
)


def _summary(stage: str = "foundry_deployment", binding: str = "preview-a") -> ApprovalSummary:
    return ApprovalSummary(
        stage=stage,
        heading="FOUNDRY DEPLOYMENT",
        facts=(("Creates", "3"), ("Deletes", "0")),
        evidence_binding=binding,
    )


@pytest.mark.parametrize("response", ("", "n\n", "maybe\n", "y later\n"))
def test_terminal_approval_defaults_to_no_for_eof_or_malformed_input(response: str) -> None:
    output = StringIO()

    assert prompt_for_stage_approval(
        _summary(), input_stream=StringIO(response), output_stream=output
    ) is False
    assert "FOUNDRY DEPLOYMENT" in output.getvalue()
    assert "preview-a" not in output.getvalue()


def test_terminal_approval_accepts_only_explicit_yes() -> None:
    assert prompt_for_stage_approval(
        _summary(), input_stream=StringIO("y\n"), output_stream=StringIO()
    ) is True


def test_cli_has_no_approve_all_escape_hatch() -> None:
    with pytest.raises(SystemExit):
        _parse_args(
            [
                "--live",
                "--json",
                "--config",
                ".env.daily-azure.local",
                "--yes",
            ]
        )


def test_approval_is_current_run_stage_specific_evidence_bound_and_one_use() -> None:
    approved: list[ApprovalSummary] = []
    session = GuidedApprovalSession(
        environment_binding="environment-a",
        approver=lambda summary: approved.append(summary) is None,
    )

    assert session.request(_summary()) is True
    assert session.request(_summary()) is False
    assert session.request(_summary(binding="preview-b")) is False
    assert session.request(_summary(stage="web_app_deployment")) is True
    assert len(approved) == 2

    next_session = GuidedApprovalSession(
        environment_binding="environment-a",
        approver=lambda _summary: True,
    )
    assert next_session.request(_summary()) is True

    changed_environment = GuidedApprovalSession(
        environment_binding="environment-b",
        approver=None,
    )
    assert changed_environment.request(_summary()) is False


def test_public_ready_construction_is_rejected() -> None:
    with pytest.raises(ValueError):
        DailyAzureEnvironmentRebuildResult(
            ok=True,
            category="success",
            mode="live",
            daily_environment_ready=True,
            azure_mutation_made=False,
        )


def test_ready_factory_requires_application_hosting_proofs_only() -> None:
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
    ready = DailyAzureEnvironmentRebuildResult._verified_ready(
        proofs, azure_mutation_made=False
    )
    assert ready.daily_environment_ready is True

    proofs["hosted_readiness_verified"] = False
    with pytest.raises(ValueError):
        DailyAzureEnvironmentRebuildResult._verified_ready(
            proofs, azure_mutation_made=False
        )
