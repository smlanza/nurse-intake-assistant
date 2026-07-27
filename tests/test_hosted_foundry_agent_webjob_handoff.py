import importlib
import json
import os
from pathlib import Path
from datetime import datetime, timezone

import pytest

from src.app.services.daily_azure_environment_rebuild import (
    DailyAzureReadinessReceipt,
)
from src.app.services.hosted_foundry_agent_webjob_execution import (
    EnvironmentGenerationEvidence,
    WEBJOB_NAME,
    environment_generation_fingerprint,
)


FINGERPRINT_EVIDENCE = EnvironmentGenerationEvidence(
    resource_group_resource_id=(
        "/subscriptions/00000000-0000-0000-0000-000000000001/"
        "resourceGroups/fictional-rg"
    ),
    web_app_resource_id=(
        "/subscriptions/00000000-0000-0000-0000-000000000001/"
        "resourceGroups/fictional-rg/providers/Microsoft.Web/sites/fictional-web-app"
    ),
    principal_id="00000000-0000-0000-0000-000000000002",
    package_digest="b" * 64,
    foundry_project_resource_id=(
        "/subscriptions/00000000-0000-0000-0000-000000000001/"
        "resourceGroups/fictional-rg/providers/Microsoft.CognitiveServices/"
        "accounts/fictional-account/projects/fictional-project"
    ),
    agent_name="fictional-agent",
    agent_version="7",
    webjob_name=WEBJOB_NAME,
)


def _service():
    return importlib.import_module(
        "src.app.services.hosted_foundry_agent_webjob_handoff"
    )


def _receipt(**changes: object) -> DailyAzureReadinessReceipt:
    values: dict[str, object] = {
        "schema_version": 3,
        "operation": "rebuild_daily_azure_environment",
        "ready": True,
        "configuration_fingerprint": "c" * 64,
        "run_epoch": "00000000-0000-4000-8000-000000000003",
        "correlation_fingerprint": "d" * 64,
        "requested_foundry_account_name": "fictional-account",
        "foundry_account_name": "fictional-account",
        "foundry_account_name_generated": False,
        "foundry_account_name_generation_attempts": 0,
        "foundry_account_name_conflicts": (),
        "resource_group": "fictional-rg",
        "foundry_project_name": "fictional-project",
        "web_app_name": "fictional-web-app",
    }
    values.update(changes)
    return DailyAzureReadinessReceipt(**values)


class MemoryStore:
    def __init__(self, existing=None) -> None:
        self.existing = existing
        self.writes = []

    def read(self):
        return self.existing

    def write(self, handoff) -> None:
        if self.existing is not None:
            raise FileExistsError()
        self.existing = handoff
        self.writes.append(handoff)


def _request(mode: str = "live", *, source_root: Path = Path("/repo")):
    return _service().HostedFoundryAgentWebJobHandoffRequest(
        mode=mode,
        source_root=source_root,
        resource_group="fictional-rg",
        web_app_name="fictional-web-app",
    )


def test_live_preparation_uses_existing_fingerprint_contract_and_persists_privately() -> None:
    service = _service()
    reads: list[bool] = []
    store = MemoryStore()

    result = service.prepare_hosted_foundry_agent_webjob_handoff(
        _request(),
        readiness_receipt=_receipt(),
        evidence_reader=lambda: reads.append(True) or FINGERPRINT_EVIDENCE,
        handoff_store=store,
    )

    assert result.ok is True
    assert result.handoff_persisted is True
    assert result.webjob_operation_attempted is False
    assert reads == [True]
    assert len(store.writes) == 1
    assert store.writes[0].environment_fingerprint == (
        environment_generation_fingerprint(FINGERPRINT_EVIDENCE)
    )
    serialized = json.dumps(result.to_json_dict())
    for forbidden in (
        environment_generation_fingerprint(FINGERPRINT_EVIDENCE),
        FINGERPRINT_EVIDENCE.principal_id,
        FINGERPRINT_EVIDENCE.package_digest,
        FINGERPRINT_EVIDENCE.agent_name,
        FINGERPRINT_EVIDENCE.agent_version,
        "subscriptions/",
    ):
        assert forbidden not in serialized


@pytest.mark.parametrize(
    "receipt",
    [
        None,
        _receipt(ready=False),
        _receipt(resource_group="other-rg"),
        _receipt(web_app_name="other-app"),
    ],
)
def test_invalid_or_mismatched_readiness_receipt_stops_before_evidence_reader(
    receipt,
) -> None:
    result = _service().prepare_hosted_foundry_agent_webjob_handoff(
        _request(),
        readiness_receipt=receipt,
        evidence_reader=lambda: pytest.fail("receipt must be validated first"),
        handoff_store=MemoryStore(),
    )

    assert result.ok is False
    assert result.category == "readiness_receipt_invalid"
    assert result.evidence_read_attempted is False


def test_malformed_generation_evidence_fails_without_persisting() -> None:
    malformed = EnvironmentGenerationEvidence(
        **{
            **FINGERPRINT_EVIDENCE.__dict__,
            "principal_id": "not-a-guid",
        }
    )
    store = MemoryStore()

    result = _service().prepare_hosted_foundry_agent_webjob_handoff(
        _request(),
        readiness_receipt=_receipt(),
        evidence_reader=lambda: malformed,
        handoff_store=store,
    )

    assert result.category == "generation_evidence_invalid"
    assert result.handoff_persisted is False
    assert store.writes == []


def test_existing_different_handoff_fails_closed_without_replacement() -> None:
    service = _service()
    existing = service.HostedFoundryAgentWebJobGenerationHandoff(
        schema_version=service.GENERATION_HANDOFF_SCHEMA_VERSION,
        state="prepared",
        readiness_configuration_fingerprint="c" * 64,
        readiness_run_epoch=_receipt().run_epoch,
        readiness_correlation_fingerprint="d" * 64,
        resource_group="fictional-rg",
        web_app_name="fictional-web-app",
        environment_fingerprint="e" * 64,
    )
    store = MemoryStore(existing)

    result = service.prepare_hosted_foundry_agent_webjob_handoff(
        _request(),
        readiness_receipt=_receipt(),
        evidence_reader=lambda: FINGERPRINT_EVIDENCE,
        handoff_store=store,
    )

    assert result.category == "generation_handoff_conflict"
    assert result.handoff_persisted is False
    assert store.existing is existing


def test_file_handoff_is_private_immutable_and_rejects_symlinks(
    tmp_path: Path,
) -> None:
    service = _service()
    store = service.FileHostedFoundryAgentWebJobHandoffStore(tmp_path)
    handoff = service.HostedFoundryAgentWebJobGenerationHandoff(
        schema_version=service.GENERATION_HANDOFF_SCHEMA_VERSION,
        state="prepared",
        readiness_configuration_fingerprint="c" * 64,
        readiness_run_epoch=_receipt().run_epoch,
        readiness_correlation_fingerprint="d" * 64,
        resource_group="fictional-rg",
        web_app_name="fictional-web-app",
        environment_fingerprint=environment_generation_fingerprint(
            FINGERPRINT_EVIDENCE
        ),
    )

    store.write(handoff)

    path = tmp_path / service.GENERATION_HANDOFF_RELATIVE_PATH
    assert store.read() == handoff
    assert os.stat(path.parent).st_mode & 0o777 == 0o700
    assert os.stat(path).st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        store.write(handoff)

    path.unlink()
    target = tmp_path / "outside.json"
    target.write_text("{}")
    path.symlink_to(target)
    with pytest.raises(service.GenerationHandoffError):
        store.read()
    assert target.read_text() == "{}"


def test_file_handoff_rejects_symlinked_lifecycle_directory_without_mutation(
    tmp_path: Path,
) -> None:
    service = _service()
    artifacts = tmp_path / ".artifacts"
    artifacts.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    outside.chmod(0o755)
    lifecycle = artifacts / "hosted-foundry-agent-webjob"
    lifecycle.symlink_to(outside, target_is_directory=True)
    mode_before = os.stat(outside).st_mode & 0o777
    handoff = service.HostedFoundryAgentWebJobGenerationHandoff(
        schema_version=service.GENERATION_HANDOFF_SCHEMA_VERSION,
        state="prepared",
        readiness_configuration_fingerprint="c" * 64,
        readiness_run_epoch=_receipt().run_epoch,
        readiness_correlation_fingerprint="d" * 64,
        resource_group="fictional-rg",
        web_app_name="fictional-web-app",
        environment_fingerprint=environment_generation_fingerprint(
            FINGERPRINT_EVIDENCE
        ),
    )

    with pytest.raises(service.GenerationHandoffError):
        service.FileHostedFoundryAgentWebJobHandoffStore(tmp_path).write(handoff)

    assert os.stat(outside).st_mode & 0o777 == mode_before
    assert list(outside.iterdir()) == []


def test_check_mode_is_offline_and_does_not_require_receipt_or_evidence() -> None:
    result = _service().prepare_hosted_foundry_agent_webjob_handoff(
        _request("check"),
        readiness_receipt=None,
        evidence_reader=lambda: pytest.fail("check must not read evidence"),
        handoff_store=MemoryStore(),
    )

    assert result.ok is True
    assert result.category == "check_complete"
    assert result.evidence_read_attempted is False
    assert result.handoff_persisted is False


def test_repository_reader_uses_two_projected_reads_and_no_assignment_read(
    tmp_path: Path,
) -> None:
    service = _service()

    class Outcome:
        return_code = 0
        stderr = "raw secret stderr"

        def __init__(self, stdout: str) -> None:
            self.stdout = stdout

    class Runner:
        def __init__(self) -> None:
            self.calls: list[list[str]] = []

        def run(self, args: list[str]):
            self.calls.append(args)
            if args[1:3] == ["webapp", "show"]:
                return Outcome(
                    json.dumps(
                        {
                            "principalId": FINGERPRINT_EVIDENCE.principal_id,
                            "type": "SystemAssigned",
                            "webAppId": FINGERPRINT_EVIDENCE.web_app_resource_id,
                        }
                    )
                )
            return Outcome(
                json.dumps(
                    {
                        "name": "fictional-project",
                        "id": FINGERPRINT_EVIDENCE.foundry_project_resource_id,
                    }
                )
            )

    runner = Runner()
    reader = service.RepositoryEnvironmentGenerationEvidenceReader(
        source_root=tmp_path,
        config=object(),
        readiness_receipt=_receipt(),
        runner=runner,
        session_reader=lambda *_args: service._CurrentSessionBinding(
            agent_name="fictional-agent",
            agent_version="7",
            hosted_origin="https://fictional.example",
        ),
        package_reader=lambda _root: ("b" * 64, "f" * 64),
        hosted_package_verifier=lambda _origin, _digest: True,
    )

    evidence = reader()

    assert evidence == FINGERPRINT_EVIDENCE
    assert len(runner.calls) == 2
    assert runner.calls[0][0:3] == ["az", "webapp", "show"]
    assert runner.calls[1][0:5] == [
        "az",
        "cognitiveservices",
        "account",
        "project",
        "show",
    ]
    assert all("role" not in call for args in runner.calls for call in args)


def test_recovery_inspector_recognizes_prepared_and_accepted_handoff_states(
    tmp_path: Path,
) -> None:
    service = _service()
    execution = importlib.import_module(
        "src.app.services.hosted_foundry_agent_webjob_execution"
    )
    recovery = importlib.import_module(
        "src.app.services.hosted_foundry_agent_webjob_state_recovery"
    )
    fingerprint = environment_generation_fingerprint(FINGERPRINT_EVIDENCE)
    handoff = service.HostedFoundryAgentWebJobGenerationHandoff(
        schema_version=service.GENERATION_HANDOFF_SCHEMA_VERSION,
        state="prepared",
        readiness_configuration_fingerprint="c" * 64,
        readiness_run_epoch=_receipt().run_epoch,
        readiness_correlation_fingerprint="d" * 64,
        resource_group="fictional-rg",
        web_app_name="fictional-web-app",
        environment_fingerprint=fingerprint,
    )
    service.FileHostedFoundryAgentWebJobHandoffStore(tmp_path).write(handoff)
    request = recovery.HostedWebJobStateRecoveryRequest(
        mode="inspect",
        source_root=tmp_path,
        expected_environment_fingerprint=fingerprint,
    )

    prepared = recovery.inspect_hosted_webjob_state(request)

    assert prepared.ok is True
    assert prepared.state == "prepared"

    execution.FileTriggerReceiptStore(tmp_path).write(
        execution.TriggerReceipt(
            schema_version=execution.TRIGGER_RECEIPT_SCHEMA_VERSION,
            state="accepted",
            trigger_not_before=datetime(
                2026,
                7,
                27,
                12,
                tzinfo=timezone.utc,
            ),
            resource_group="fictional-rg",
            web_app_name="fictional-web-app",
            webjob_name=WEBJOB_NAME,
            environment_fingerprint=fingerprint,
        )
    )

    accepted = recovery.inspect_hosted_webjob_state(request)

    assert accepted.ok is True
    assert accepted.state == "accepted"
