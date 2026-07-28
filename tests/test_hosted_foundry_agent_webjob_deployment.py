from dataclasses import replace
from io import BytesIO
import json
from pathlib import Path
import shutil
from types import SimpleNamespace
from urllib.error import HTTPError, URLError

import pytest

from src.app.services.daily_azure_environment_rebuild import (
    DailyAzureReadinessReceipt,
)
from src.app.services.hosted_foundry_agent_webjob_execution import (
    CommandResult,
    EnvironmentGenerationEvidence,
    WEBJOB_NAME,
    environment_generation_fingerprint,
)
from src.app.services.hosted_foundry_agent_webjob_handoff import (
    HostedFoundryAgentWebJobGenerationHandoff,
)
from src.app.services.hosted_foundry_agent_webjob_package import (
    WEBJOB_PACKAGE_RELATIVE_PATH,
)


def _service():
    import src.app.services.hosted_foundry_agent_webjob_deployment as service

    return service


EVIDENCE = EnvironmentGenerationEvidence(
    resource_group_resource_id=(
        "/subscriptions/00000000-0000-0000-0000-000000000001/"
        "resourceGroups/fictional-rg"
    ),
    web_app_resource_id=(
        "/subscriptions/00000000-0000-0000-0000-000000000001/"
        "resourceGroups/fictional-rg/providers/Microsoft.Web/sites/fictional-app"
    ),
    principal_id="00000000-0000-0000-0000-000000000002",
    package_digest="a" * 64,
    foundry_project_resource_id=(
        "/subscriptions/00000000-0000-0000-0000-000000000001/"
        "resourceGroups/fictional-rg/providers/Microsoft.CognitiveServices/"
        "accounts/fictional-account/projects/fictional-project"
    ),
    agent_name="fictional-agent",
    agent_version="7",
    webjob_name=WEBJOB_NAME,
)
FINGERPRINT = environment_generation_fingerprint(EVIDENCE)


@pytest.fixture
def source_tree(tmp_path: Path) -> Path:
    repository_root = Path(__file__).parents[1]
    entrypoint = (
        tmp_path
        / "App_Data/jobs/triggered/verify-hosted-foundry-agent/run.py"
    )
    entrypoint.parent.mkdir(parents=True)
    shutil.copyfile(
        repository_root
        / "App_Data/jobs/triggered/verify-hosted-foundry-agent/run.py",
        entrypoint,
    )
    for relative in (
        "infra/main.bicep",
        "infra/modules/web-app.bicep",
        "infra/modules/hosted-foundry-verifier-config-validation.bicep",
        "src/app/services/hosted_foundry_agent_verification.py",
    ):
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(repository_root / relative, destination)
    return tmp_path


def _receipt(**changes) -> DailyAzureReadinessReceipt:
    values = {
        "schema_version": 4,
        "operation": "rebuild_daily_azure_environment",
        "ready": True,
        "configuration_fingerprint": "b" * 64,
        "run_epoch": "0" * 32,
        "correlation_fingerprint": "c" * 64,
        "requested_foundry_account_name": "fictional-account",
        "foundry_account_name": "fictional-account",
        "foundry_account_name_generated": False,
        "foundry_account_name_generation_attempts": 0,
        "foundry_account_name_conflicts": (),
        "resource_group": "fictional-rg",
        "foundry_project_name": "fictional-project",
        "web_app_name": "fictional-app",
    }
    values.update(changes)
    return DailyAzureReadinessReceipt(**values)


def _handoff(**changes) -> HostedFoundryAgentWebJobGenerationHandoff:
    values = {
        "schema_version": 1,
        "state": "prepared",
        "readiness_configuration_fingerprint": "b" * 64,
        "readiness_run_epoch": "0" * 32,
        "readiness_correlation_fingerprint": "c" * 64,
        "resource_group": "fictional-rg",
        "web_app_name": "fictional-app",
        "environment_fingerprint": FINGERPRINT,
    }
    values.update(changes)
    return HostedFoundryAgentWebJobGenerationHandoff(**values)


def _request(source_tree: Path, mode: str = "live"):
    return _service().HostedFoundryAgentWebJobDeploymentRequest(
        mode=mode,
        source_root=source_tree,
        resource_group="fictional-rg",
        web_app_name="fictional-app",
        webjob_name=WEBJOB_NAME,
    )


def _current_binding():
    return _receipt(), _handoff()


def test_check_mode_is_offline_and_proves_only_local_package(
    source_tree: Path,
) -> None:
    service = _service()

    result = service.deploy_hosted_foundry_agent_webjob(
        _request(source_tree, "check"),
        readiness_receipt=None,
        generation_handoff=None,
        evidence_reader=lambda: pytest.fail("check must not read evidence"),
        approver=lambda _summary: pytest.fail("check must not ask approval"),
        uploader_factory=lambda: pytest.fail("check must not create uploader"),
        discovery_factory=lambda: pytest.fail(
            "check must not create discoverer"
        ),
    )

    assert result.ok is True
    assert result.category == "check_complete"
    assert result.local_webjob_package_valid is True
    assert result.generation_validated is False
    assert result.upload_attempted is False
    assert result.remote_webjob_discovered is False
    assert result.trigger_attempted is False
    assert result.recommended_next_step == (
        "Stop after reviewing the offline package contract."
    )


@pytest.mark.parametrize(
    ("receipt", "handoff"),
    [
        (None, _handoff()),
        (_receipt(ready=False), _handoff()),
        (_receipt(), None),
        (_receipt(), _handoff(resource_group="other-rg")),
    ],
)
def test_invalid_ready_or_handoff_stops_before_package_and_evidence(
    source_tree: Path,
    receipt,
    handoff,
) -> None:
    service = _service()

    result = service.deploy_hosted_foundry_agent_webjob(
        _request(source_tree),
        readiness_receipt=receipt,
        generation_handoff=handoff,
        evidence_reader=lambda: pytest.fail("invalid proof must stop"),
        package_builder=lambda *_args, **_kwargs: pytest.fail(
            "invalid proof must stop"
        ),
    )

    assert result.ok is False
    assert result.upload_attempted is False
    assert result.trigger_attempted is False


def test_default_no_approval_stops_before_second_evidence_and_upload(
    source_tree: Path,
) -> None:
    service = _service()
    reads: list[bool] = []
    created: list[bool] = []

    result = service.deploy_hosted_foundry_agent_webjob(
        _request(source_tree),
        readiness_receipt=_receipt(),
        generation_handoff=_handoff(),
        evidence_reader=lambda: reads.append(True) or EVIDENCE,
        current_binding_reader=_current_binding,
        approver=lambda summary: False,
        uploader_factory=lambda: created.append(True),
    )

    assert result.category == "approval_required"
    assert result.generation_validated is True
    assert result.operator_approval_obtained is False
    assert result.upload_attempted is False
    assert reads == [True]
    assert created == []


@pytest.mark.parametrize(
    "changed",
    [
        replace(
            EVIDENCE,
            resource_group_resource_id=(
                "/subscriptions/00000000-0000-0000-0000-000000000009/"
                "resourceGroups/fictional-rg"
            ),
        ),
        replace(
            EVIDENCE,
            web_app_resource_id=EVIDENCE.web_app_resource_id + "-changed",
        ),
        replace(
            EVIDENCE,
            principal_id="00000000-0000-0000-0000-000000000003",
        ),
        replace(EVIDENCE, package_digest="d" * 64),
        replace(
            EVIDENCE,
            foundry_project_resource_id=(
                EVIDENCE.foundry_project_resource_id + "-changed"
            ),
        ),
        replace(EVIDENCE, agent_name="changed-agent"),
        replace(EVIDENCE, agent_version="8"),
        replace(EVIDENCE, webjob_name="changed-webjob"),
    ],
)
def test_changed_generation_after_approval_invalidates_before_upload(
    source_tree: Path,
    changed: EnvironmentGenerationEvidence,
) -> None:
    service = _service()
    evidence = iter((EVIDENCE, changed))
    created: list[bool] = []

    result = service.deploy_hosted_foundry_agent_webjob(
        _request(source_tree),
        readiness_receipt=_receipt(),
        generation_handoff=_handoff(),
        evidence_reader=lambda: next(evidence),
        current_binding_reader=_current_binding,
        approver=lambda _summary: True,
        uploader_factory=lambda: created.append(True),
    )

    assert result.category == "generation_changed"
    assert result.operator_approval_obtained is True
    assert result.upload_attempted is False
    assert created == []


def test_changed_webjob_source_after_approval_invalidates_before_upload(
    source_tree: Path,
) -> None:
    service = _service()
    created: list[bool] = []

    def approve(_summary) -> bool:
        entrypoint = (
            source_tree
            / "App_Data/jobs/triggered/verify-hosted-foundry-agent/run.py"
        )
        entrypoint.write_text(entrypoint.read_text() + "\n# changed\n")
        return True

    result = service.deploy_hosted_foundry_agent_webjob(
        _request(source_tree),
        readiness_receipt=_receipt(),
        generation_handoff=_handoff(),
        evidence_reader=lambda: EVIDENCE,
        current_binding_reader=_current_binding,
        approver=approve,
        uploader_factory=lambda: created.append(True),
    )

    assert result.category == "package_changed"
    assert result.upload_attempted is False
    assert created == []


@pytest.mark.parametrize(
    "current_binding",
    [
        (_receipt(run_epoch="1" * 32), _handoff()),
        (_receipt(), _handoff(environment_fingerprint="e" * 64)),
    ],
)
def test_changed_ready_or_handoff_after_approval_invalidates_before_upload(
    source_tree: Path,
    current_binding,
) -> None:
    service = _service()
    created: list[bool] = []

    result = service.deploy_hosted_foundry_agent_webjob(
        _request(source_tree),
        readiness_receipt=_receipt(),
        generation_handoff=_handoff(),
        evidence_reader=lambda: EVIDENCE,
        current_binding_reader=lambda: current_binding,
        approver=lambda _summary: True,
        uploader_factory=lambda: created.append(True),
    )

    assert result.category == "generation_changed"
    assert result.upload_attempted is False
    assert created == []


def test_upload_acceptance_and_remote_discovery_are_distinct_proofs(
    source_tree: Path,
) -> None:
    service = _service()
    upload_calls: list[tuple[str, str, bytes]] = []
    discovery_calls: list[tuple[str, str]] = []

    class Uploader:
        def upload(self, web_app_name: str, webjob_name: str, package: bytes):
            upload_calls.append((web_app_name, webjob_name, package))
            return service.KuduWebJobUploadResult.accepted()

    class Discoverer:
        def discover(self, web_app_name: str, webjob_name: str):
            discovery_calls.append((web_app_name, webjob_name))
            return service.KuduWebJobDiscoveryResult.success()

    result = service.deploy_hosted_foundry_agent_webjob(
        _request(source_tree),
        readiness_receipt=_receipt(),
        generation_handoff=_handoff(),
        evidence_reader=lambda: EVIDENCE,
        current_binding_reader=_current_binding,
        approver=lambda _summary: True,
        uploader_factory=Uploader,
        discovery_factory=Discoverer,
    )

    assert result.ok is True
    assert result.local_webjob_package_valid is True
    assert result.generation_validated is True
    assert result.upload_attempted is True
    assert result.upload_accepted is True
    assert result.remote_webjob_discovered is True
    assert result.trigger_attempted is False
    assert result.trigger_accepted is False
    assert result.correlated_execution_observed is False
    assert result.metadata_verification_proven is False
    assert result.fictional_invocation_proven is False
    assert len(upload_calls) == 1
    assert discovery_calls == [
        ("fictional-app", "verify-hosted-foundry-agent")
    ]
    assert upload_calls[0][2] == (
        source_tree / WEBJOB_PACKAGE_RELATIVE_PATH
    ).read_bytes()
    serialized = json.dumps(result.to_json_dict())
    for forbidden in (
        "fictional-rg",
        "fictional-app",
        "fictional-project",
        "fictional-agent",
        EVIDENCE.principal_id,
        EVIDENCE.package_digest,
        FINGERPRINT,
        str(source_tree),
        "triggeredwebjobs",
    ):
        assert forbidden not in serialized


def test_accepted_upload_does_not_claim_success_when_discovery_is_missing(
    source_tree: Path,
) -> None:
    service = _service()

    class Uploader:
        def upload(self, *_args):
            return service.KuduWebJobUploadResult.accepted()

    class MissingDiscoverer:
        def discover(self, _web_app_name, _webjob_name):
            return service.KuduWebJobDiscoveryResult(
                "remote_webjob_missing",
                True,
                False,
            )

    result = service.deploy_hosted_foundry_agent_webjob(
        _request(source_tree),
        readiness_receipt=_receipt(),
        generation_handoff=_handoff(),
        evidence_reader=lambda: EVIDENCE,
        current_binding_reader=_current_binding,
        approver=lambda _summary: True,
        uploader_factory=Uploader,
        discovery_factory=MissingDiscoverer,
    )

    assert result.category == "remote_webjob_missing"
    assert result.upload_accepted is True
    assert result.remote_webjob_discovered is False
    assert result.trigger_attempted is False


@pytest.mark.parametrize(
    "category",
    [
        "authentication_or_authorization_failed",
        "discovery_throttled",
        "discovery_service_failed",
        "discovery_failed",
        "discovery_ambiguous",
        "discovery_response_invalid",
    ],
)
def test_post_upload_discovery_preserves_sanitized_kudu_failure(
    source_tree: Path,
    category: str,
) -> None:
    service = _service()

    class Uploader:
        def upload(self, *_args):
            return service.KuduWebJobUploadResult.accepted()

    class Discoverer:
        def discover(self, *_args):
            return service.KuduWebJobDiscoveryResult(
                category,
                True,
                False,
            )

    result = service.deploy_hosted_foundry_agent_webjob(
        _request(source_tree),
        readiness_receipt=_receipt(),
        generation_handoff=_handoff(),
        evidence_reader=lambda: EVIDENCE,
        current_binding_reader=_current_binding,
        approver=lambda _summary: True,
        uploader_factory=Uploader,
        discovery_factory=Discoverer,
    )

    assert result.category == category
    assert result.upload_accepted is True
    assert result.remote_discovery_attempted is True
    assert result.remote_webjob_discovered is False
    assert result.trigger_attempted is False


@pytest.mark.parametrize(
    "category",
    [
        "authentication_or_authorization_failed",
        "upload_request_invalid",
        "upload_throttled",
        "upload_service_failed",
        "upload_failed",
        "upload_acceptance_ambiguous",
    ],
)
def test_sanitized_upload_failure_stops_before_discovery(
    source_tree: Path,
    category: str,
) -> None:
    service = _service()

    class Uploader:
        def upload(self, *_args):
            return service.KuduWebJobUploadResult(
                category,
                True,
                False,
            )

    result = service.deploy_hosted_foundry_agent_webjob(
        _request(source_tree),
        readiness_receipt=_receipt(),
        generation_handoff=_handoff(),
        evidence_reader=lambda: EVIDENCE,
        current_binding_reader=_current_binding,
        approver=lambda _summary: True,
        uploader_factory=Uploader,
        discovery_factory=lambda: pytest.fail(
            "failed upload must not create discoverer"
        ),
    )

    assert result.category == category
    assert result.upload_attempted is True
    assert result.upload_accepted is False
    assert result.remote_discovery_attempted is False
    assert result.trigger_attempted is False


def test_uploader_construction_failure_is_not_claimed_as_post_submission(
    source_tree: Path,
) -> None:
    service = _service()

    def fail_before_upload():
        raise RuntimeError("secret uploader construction failure")

    result = service.deploy_hosted_foundry_agent_webjob(
        _request(source_tree),
        readiness_receipt=_receipt(),
        generation_handoff=_handoff(),
        evidence_reader=lambda: EVIDENCE,
        current_binding_reader=_current_binding,
        approver=lambda _summary: True,
        uploader_factory=fail_before_upload,
    )

    assert result.category == "unexpected_error"
    assert result.upload_attempted is False
    assert result.upload_accepted is False
    assert result.remote_discovery_attempted is False
    assert "secret" not in json.dumps(result.to_json_dict())


@pytest.mark.parametrize("accepted_status", [200, 201, 202, 204])
def test_kudu_uploader_uses_supported_replacing_triggered_webjob_zip_contract(
    tmp_path: Path,
    accepted_status: int,
) -> None:
    service = _service()
    requests = []
    token_calls = []

    class TokenRunner:
        def run(self, args):
            token_calls.append(args)
            return SimpleNamespace(
                return_code=0,
                stdout="header.payload.signature\n",
                stderr="secret stderr",
            )

    class Response:
        status = accepted_status

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    class Opener:
        def open(self, request, timeout):
            requests.append((request, timeout))
            return Response()

    uploader = service.KuduTriggeredWebJobUploader(
        token_runner=TokenRunner(),
        opener=Opener(),
    )

    result = uploader.upload(
        "fictional-app",
        WEBJOB_NAME,
        b"PK\x03\x04fictional-zip",
    )

    assert result.upload_accepted is True
    assert token_calls == [
        [
            "az",
            "account",
            "get-access-token",
            "--resource",
            "https://management.azure.com/",
            "--query",
            "accessToken",
            "--output",
            "tsv",
            "--only-show-errors",
        ]
    ]
    assert len(requests) == 1
    request, _timeout = requests[0]
    assert request.method == "PUT"
    assert request.full_url.endswith(
        "/api/triggeredwebjobs/verify-hosted-foundry-agent"
    )
    assert {
        name.casefold(): value
        for name, value in request.header_items()
    } == {
        "authorization": "Bearer header.payload.signature",
        "content-type": "application/zip",
        "content-disposition": (
            'attachment; filename="verify-hosted-foundry-agent.zip"'
        ),
    }
    assert request.data == b"PK\x03\x04fictional-zip"
    assert "header.payload.signature" not in json.dumps(result.to_json_dict())


@pytest.mark.parametrize(
    ("status", "expected_category"),
    [
        (400, "upload_request_invalid"),
        (401, "authentication_or_authorization_failed"),
        (403, "authentication_or_authorization_failed"),
        (404, "upload_request_invalid"),
        (405, "upload_request_invalid"),
        (409, "upload_request_invalid"),
        (413, "upload_request_invalid"),
        (415, "upload_request_invalid"),
        (422, "upload_request_invalid"),
        (429, "upload_throttled"),
        (500, "upload_service_failed"),
        (502, "upload_service_failed"),
        (503, "upload_service_failed"),
        (504, "upload_service_failed"),
        (418, "upload_failed"),
    ],
)
def test_kudu_uploader_maps_http_rejections_to_fixed_sanitized_categories(
    status: int,
    expected_category: str,
) -> None:
    service = _service()

    class TokenRunner:
        def run(self, _args):
            return SimpleNamespace(
                return_code=0,
                stdout="header.payload.signature\n",
                stderr="secret token stderr",
            )

    class RejectingOpener:
        def open(self, _request, timeout):
            assert timeout > 0
            raise HTTPError(
                "https://secret-host.example/secret-path",
                status,
                "secret exception text",
                {"X-Secret": "secret response header"},
                BytesIO(b"secret response body"),
            )

    result = service.KuduTriggeredWebJobUploader(
        token_runner=TokenRunner(),
        opener=RejectingOpener(),
    ).upload(
        "fictional-app",
        WEBJOB_NAME,
        b"PK\x03\x04secret-package-bytes",
    )

    assert result.category == expected_category
    assert result.upload_attempted is True
    assert result.upload_accepted is False
    serialized = json.dumps(result.to_json_dict())
    for forbidden in (
        "header.payload.signature",
        "secret-host",
        "secret-path",
        "secret exception",
        "secret response",
        "secret-package",
        str(status),
    ):
        assert forbidden not in serialized


@pytest.mark.parametrize(
    "failure",
    [
        URLError("secret transport reason"),
        TimeoutError("secret timeout"),
        OSError("secret interrupted transport"),
        RuntimeError("secret unknown post-submission outcome"),
    ],
)
def test_kudu_uploader_reserves_ambiguous_for_transport_or_unknown_outcome(
    failure: Exception,
) -> None:
    service = _service()

    class TokenRunner:
        def run(self, _args):
            return SimpleNamespace(
                return_code=0,
                stdout="header.payload.signature\n",
                stderr="",
            )

    class FailingOpener:
        def open(self, _request, timeout):
            assert timeout > 0
            raise failure

    result = service.KuduTriggeredWebJobUploader(
        token_runner=TokenRunner(),
        opener=FailingOpener(),
    ).upload(
        "fictional-app",
        WEBJOB_NAME,
        b"PK\x03\x04secret-package-bytes",
    )

    assert result.category == "upload_acceptance_ambiguous"
    assert result.upload_attempted is True
    assert result.upload_accepted is False
    assert "secret" not in json.dumps(result.to_json_dict())


def test_kudu_uploader_treats_missing_response_status_as_ambiguous() -> None:
    service = _service()

    class TokenRunner:
        def run(self, _args):
            return SimpleNamespace(
                return_code=0,
                stdout="header.payload.signature\n",
                stderr="",
            )

    class Response:
        status = None

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    class Opener:
        def open(self, _request, timeout):
            assert timeout > 0
            return Response()

    result = service.KuduTriggeredWebJobUploader(
        token_runner=TokenRunner(),
        opener=Opener(),
    ).upload(
        "fictional-app",
        WEBJOB_NAME,
        b"PK\x03\x04secret-package-bytes",
    )

    assert result.category == "upload_acceptance_ambiguous"
    assert result.upload_attempted is True
    assert result.upload_accepted is False


@pytest.mark.parametrize(
    "relative",
    [
        "scripts/deploy_web_app_code.py",
        "scripts/rebuild_daily_azure_environment.py",
        "src/app/main.py",
        "src/app/services/web_app_package.py",
    ],
)
def test_ordinary_application_paths_cannot_implicitly_deploy_the_webjob(
    relative: str,
) -> None:
    source = (Path(__file__).parents[1] / relative).read_text()

    assert "deploy_hosted_foundry_agent_webjob" not in source
    assert "/api/triggeredwebjobs" not in source
