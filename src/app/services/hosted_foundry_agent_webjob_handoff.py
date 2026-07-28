from collections.abc import Callable
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import secrets
import stat
from typing import Any, Literal, Protocol
from urllib.parse import urlsplit

from src.app.services.daily_azure_environment_rebuild import (
    DailyAzureReadinessReceipt,
    REBUILD_OPERATION,
)
from src.app.services.hosted_foundry_agent_webjob_execution import (
    EnvironmentGenerationEvidence,
    TRIGGER_STATE_DIRECTORY,
    WEBJOB_NAME,
    environment_generation_fingerprint,
)


GENERATION_HANDOFF_SCHEMA_VERSION = 1
GENERATION_HANDOFF_RELATIVE_PATH = (
    TRIGGER_STATE_DIRECTORY / "generation-handoff.json"
)
HandoffMode = Literal["check", "live"]
HandoffCategory = Literal[
    "check_complete",
    "success",
    "invalid_request",
    "readiness_receipt_invalid",
    "generation_evidence_invalid",
    "current_session_binding_invalid",
    "local_package_binding_invalid",
    "hosted_artifact_current_verification_failed",
    "web_app_identity_read_failed",
    "web_app_identity_invalid",
    "foundry_project_read_failed",
    "foundry_project_invalid",
    "environment_fingerprint_invalid",
    "generation_handoff_invalid",
    "generation_handoff_conflict",
    "generation_handoff_write_failed",
    "unexpected_error",
]
GenerationEvidenceFailureCategory = Literal[
    "current_session_binding_invalid",
    "local_package_binding_invalid",
    "hosted_artifact_current_verification_failed",
    "web_app_identity_read_failed",
    "web_app_identity_invalid",
    "foundry_project_read_failed",
    "foundry_project_invalid",
]


class GenerationHandoffError(Exception):
    pass


class GenerationEvidenceReadError(GenerationHandoffError):
    def __init__(
        self,
        category: GenerationEvidenceFailureCategory,
        *,
        azure_read_attempted: bool,
    ) -> None:
        super().__init__()
        self.category = category
        self.azure_read_attempted = azure_read_attempted


@dataclass(frozen=True)
class HostedFoundryAgentWebJobHandoffRequest:
    mode: str
    source_root: Path
    resource_group: str
    web_app_name: str


@dataclass(frozen=True)
class HostedFoundryAgentWebJobGenerationHandoff:
    schema_version: int
    state: Literal["prepared"]
    readiness_configuration_fingerprint: str
    readiness_run_epoch: str
    readiness_correlation_fingerprint: str
    resource_group: str
    web_app_name: str
    environment_fingerprint: str

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "state": self.state,
            "readiness_configuration_fingerprint": (
                self.readiness_configuration_fingerprint
            ),
            "readiness_run_epoch": self.readiness_run_epoch,
            "readiness_correlation_fingerprint": (
                self.readiness_correlation_fingerprint
            ),
            "resource_group": self.resource_group,
            "web_app_name": self.web_app_name,
            "environment_fingerprint": self.environment_fingerprint,
        }


class HostedFoundryAgentWebJobHandoffStore(Protocol):
    def read(self) -> HostedFoundryAgentWebJobGenerationHandoff | None: ...

    def write(self, handoff: HostedFoundryAgentWebJobGenerationHandoff) -> None: ...


class AzureCliRunner(Protocol):
    def run(self, args: list[str]) -> object: ...


@dataclass(frozen=True)
class _CurrentSessionBinding:
    agent_name: str
    agent_version: str
    hosted_origin: str


@dataclass(frozen=True)
class HostedFoundryAgentWebJobHandoffResult:
    ok: bool
    category: HandoffCategory
    operation: str
    mode: str
    local_contract_validated: bool
    readiness_receipt_validated: bool
    evidence_read_attempted: bool
    generation_evidence_validated: bool
    handoff_persisted: bool
    handoff_reused: bool
    azure_read_attempted: bool
    webjob_operation_attempted: bool
    recommended_next_step: str

    def to_json_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "category": self.category,
            "operation": self.operation,
            "mode": self.mode,
            "local_contract_validated": self.local_contract_validated,
            "readiness_receipt_validated": self.readiness_receipt_validated,
            "evidence_read_attempted": self.evidence_read_attempted,
            "generation_evidence_validated": (
                self.generation_evidence_validated
            ),
            "handoff_persisted": self.handoff_persisted,
            "handoff_reused": self.handoff_reused,
            "azure_read_attempted": self.azure_read_attempted,
            "webjob_operation_attempted": self.webjob_operation_attempted,
            "recommended_next_step": self.recommended_next_step,
        }


def _result(
    request: HostedFoundryAgentWebJobHandoffRequest,
    category: HandoffCategory,
    *,
    ok: bool = False,
    local_contract_validated: bool = False,
    readiness_receipt_validated: bool = False,
    evidence_read_attempted: bool = False,
    generation_evidence_validated: bool = False,
    handoff_persisted: bool = False,
    handoff_reused: bool = False,
    azure_read_attempted: bool = False,
) -> HostedFoundryAgentWebJobHandoffResult:
    return HostedFoundryAgentWebJobHandoffResult(
        ok=ok,
        category=category,
        operation="prepare_hosted_foundry_agent_webjob_handoff",
        mode=request.mode if request.mode in {"check", "live"} else "invalid",
        local_contract_validated=local_contract_validated,
        readiness_receipt_validated=readiness_receipt_validated,
        evidence_read_attempted=evidence_read_attempted,
        generation_evidence_validated=generation_evidence_validated,
        handoff_persisted=handoff_persisted,
        handoff_reused=handoff_reused,
        azure_read_attempted=azure_read_attempted,
        webjob_operation_attempted=False,
        recommended_next_step=(
            "Review the sanitized result, then run one separate WebJob discovery."
            if ok and request.mode == "live"
            else "Run explicit live preparation after current daily READY proof."
            if ok
            else "Stop and review the sanitized category without running a WebJob."
        ),
    )


def _safe_name(value: object) -> bool:
    return bool(
        isinstance(value, str)
        and value == value.strip()
        and re.fullmatch(r"[A-Za-z0-9_.()\-]+", value)
    )


def _valid_fingerprint(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _valid_request(request: HostedFoundryAgentWebJobHandoffRequest) -> bool:
    return bool(
        request.mode in {"check", "live"}
        and request.source_root.is_absolute()
        and _safe_name(request.resource_group)
        and _safe_name(request.web_app_name)
    )


def _receipt_matches(
    receipt: object,
    request: HostedFoundryAgentWebJobHandoffRequest,
) -> bool:
    return bool(
        type(receipt) is DailyAzureReadinessReceipt
        and receipt.operation == REBUILD_OPERATION
        and receipt.ready is True
        and receipt.resource_group == request.resource_group
        and receipt.web_app_name == request.web_app_name
        and _valid_fingerprint(receipt.configuration_fingerprint)
        and _valid_fingerprint(receipt.correlation_fingerprint)
        and isinstance(receipt.run_epoch, str)
        and bool(receipt.run_epoch)
    )


def _handoff_for(
    receipt: DailyAzureReadinessReceipt,
    request: HostedFoundryAgentWebJobHandoffRequest,
    environment_fingerprint: str,
) -> HostedFoundryAgentWebJobGenerationHandoff:
    return HostedFoundryAgentWebJobGenerationHandoff(
        schema_version=GENERATION_HANDOFF_SCHEMA_VERSION,
        state="prepared",
        readiness_configuration_fingerprint=receipt.configuration_fingerprint,
        readiness_run_epoch=receipt.run_epoch,
        readiness_correlation_fingerprint=receipt.correlation_fingerprint,
        resource_group=request.resource_group,
        web_app_name=request.web_app_name,
        environment_fingerprint=environment_fingerprint,
    )


def _handoff_valid(
    handoff: object,
    receipt: DailyAzureReadinessReceipt,
    resource_group: str,
    web_app_name: str,
) -> bool:
    return bool(
        type(handoff) is HostedFoundryAgentWebJobGenerationHandoff
        and handoff.schema_version == GENERATION_HANDOFF_SCHEMA_VERSION
        and handoff.state == "prepared"
        and handoff.readiness_configuration_fingerprint
        == receipt.configuration_fingerprint
        and handoff.readiness_run_epoch == receipt.run_epoch
        and handoff.readiness_correlation_fingerprint
        == receipt.correlation_fingerprint
        and handoff.resource_group == resource_group == receipt.resource_group
        and handoff.web_app_name == web_app_name == receipt.web_app_name
        and _valid_fingerprint(handoff.environment_fingerprint)
    )


def prepare_hosted_foundry_agent_webjob_handoff(
    request: HostedFoundryAgentWebJobHandoffRequest,
    *,
    readiness_receipt: DailyAzureReadinessReceipt | None,
    evidence_reader: Callable[[], EnvironmentGenerationEvidence],
    handoff_store: HostedFoundryAgentWebJobHandoffStore,
) -> HostedFoundryAgentWebJobHandoffResult:
    if not _valid_request(request):
        return _result(request, "invalid_request")
    if request.mode == "check":
        return _result(
            request,
            "check_complete",
            ok=True,
            local_contract_validated=True,
        )
    if not _receipt_matches(readiness_receipt, request):
        return _result(
            request,
            "readiness_receipt_invalid",
            local_contract_validated=True,
        )
    assert readiness_receipt is not None
    try:
        evidence = evidence_reader()
    except GenerationEvidenceReadError as error:
        return _result(
            request,
            error.category,
            local_contract_validated=True,
            readiness_receipt_validated=True,
            evidence_read_attempted=True,
            azure_read_attempted=error.azure_read_attempted,
        )
    except Exception:
        return _result(
            request,
            "generation_evidence_invalid",
            local_contract_validated=True,
            readiness_receipt_validated=True,
            evidence_read_attempted=True,
            azure_read_attempted=(
                getattr(evidence_reader, "azure_read_attempted", False) is True
            ),
        )
    azure_read_attempted = (
        getattr(evidence_reader, "azure_read_attempted", False) is True
    )
    try:
        fingerprint = environment_generation_fingerprint(evidence)
    except (AttributeError, TypeError, ValueError):
        return _result(
            request,
            "environment_fingerprint_invalid",
            local_contract_validated=True,
            readiness_receipt_validated=True,
            evidence_read_attempted=True,
            azure_read_attempted=azure_read_attempted,
        )
    handoff = _handoff_for(readiness_receipt, request, fingerprint)
    try:
        existing = handoff_store.read()
    except Exception:
        return _result(
            request,
            "generation_handoff_invalid",
            local_contract_validated=True,
            readiness_receipt_validated=True,
            evidence_read_attempted=True,
            generation_evidence_validated=True,
            azure_read_attempted=azure_read_attempted,
        )
    if existing is not None:
        return _result(
            request,
            "success" if existing == handoff else "generation_handoff_conflict",
            ok=existing == handoff,
            local_contract_validated=True,
            readiness_receipt_validated=True,
            evidence_read_attempted=True,
            generation_evidence_validated=True,
            handoff_persisted=existing == handoff,
            handoff_reused=existing == handoff,
            azure_read_attempted=azure_read_attempted,
        )
    try:
        handoff_store.write(handoff)
    except FileExistsError:
        return _result(
            request,
            "generation_handoff_conflict",
            local_contract_validated=True,
            readiness_receipt_validated=True,
            evidence_read_attempted=True,
            generation_evidence_validated=True,
            azure_read_attempted=azure_read_attempted,
        )
    except Exception:
        return _result(
            request,
            "generation_handoff_write_failed",
            local_contract_validated=True,
            readiness_receipt_validated=True,
            evidence_read_attempted=True,
            generation_evidence_validated=True,
            azure_read_attempted=azure_read_attempted,
        )
    return _result(
        request,
        "success",
        ok=True,
        local_contract_validated=True,
        readiness_receipt_validated=True,
        evidence_read_attempted=True,
        generation_evidence_validated=True,
        handoff_persisted=True,
        azure_read_attempted=azure_read_attempted,
    )


class FileHostedFoundryAgentWebJobHandoffStore:
    def __init__(self, source_root: Path) -> None:
        self._source_root = source_root

    @staticmethod
    def _directory_flags() -> int:
        if any(
            not hasattr(os, name)
            for name in ("O_DIRECTORY", "O_NOFOLLOW")
        ):
            raise GenerationHandoffError()
        return (
            os.O_RDONLY
            | os.O_DIRECTORY
            | os.O_NOFOLLOW
            | getattr(os, "O_CLOEXEC", 0)
        )

    def _open_state_directory(self, *, create: bool) -> int:
        descriptor: int | None = None
        try:
            descriptor = os.open(
                self._source_root,
                self._directory_flags(),
            )
            if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
                raise GenerationHandoffError()
            for part in TRIGGER_STATE_DIRECTORY.parts:
                if create:
                    try:
                        os.mkdir(part, mode=0o700, dir_fd=descriptor)
                    except FileExistsError:
                        pass
                next_descriptor = os.open(
                    part,
                    self._directory_flags(),
                    dir_fd=descriptor,
                )
                os.close(descriptor)
                descriptor = next_descriptor
            if create:
                os.fchmod(descriptor, 0o700)
            return descriptor
        except FileNotFoundError:
            if descriptor is not None:
                os.close(descriptor)
            raise
        except GenerationHandoffError:
            if descriptor is not None:
                os.close(descriptor)
            raise
        except Exception as error:
            if descriptor is not None:
                os.close(descriptor)
            raise GenerationHandoffError() from error

    def read(self) -> HostedFoundryAgentWebJobGenerationHandoff | None:
        try:
            directory = self._open_state_directory(create=False)
        except FileNotFoundError:
            return None
        descriptor: int | None = None
        try:
            try:
                descriptor = os.open(
                    GENERATION_HANDOFF_RELATIVE_PATH.name,
                    os.O_RDONLY
                    | os.O_NOFOLLOW
                    | os.O_NONBLOCK
                    | getattr(os, "O_CLOEXEC", 0),
                    dir_fd=directory,
                )
            except FileNotFoundError:
                return None
            details = os.fstat(descriptor)
            if not stat.S_ISREG(details.st_mode) or details.st_size > 16384:
                raise GenerationHandoffError()
            raw = os.read(descriptor, 16385)
            if len(raw) > 16384:
                raise GenerationHandoffError()
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict) or set(payload) != {
                field
                for field in HostedFoundryAgentWebJobGenerationHandoff.__dataclass_fields__
            }:
                raise GenerationHandoffError()
            handoff = HostedFoundryAgentWebJobGenerationHandoff(**payload)
            if not (
                handoff.schema_version == GENERATION_HANDOFF_SCHEMA_VERSION
                and handoff.state == "prepared"
                and _valid_fingerprint(handoff.readiness_configuration_fingerprint)
                and _valid_fingerprint(handoff.readiness_correlation_fingerprint)
                and _valid_fingerprint(handoff.environment_fingerprint)
                and _safe_name(handoff.resource_group)
                and _safe_name(handoff.web_app_name)
                and isinstance(handoff.readiness_run_epoch, str)
                and bool(handoff.readiness_run_epoch)
            ):
                raise GenerationHandoffError()
            return handoff
        except GenerationHandoffError:
            raise
        except Exception as error:
            raise GenerationHandoffError() from error
        finally:
            if descriptor is not None:
                os.close(descriptor)
            os.close(directory)

    def write(self, handoff: HostedFoundryAgentWebJobGenerationHandoff) -> None:
        directory = self._open_state_directory(create=True)
        temporary = f".generation-handoff.{secrets.token_hex(16)}.tmp"
        descriptor: int | None = None
        try:
            if os.listdir(directory):
                raise FileExistsError()
            descriptor = os.open(
                temporary,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | os.O_NOFOLLOW
                | getattr(os, "O_CLOEXEC", 0),
                0o600,
                dir_fd=directory,
            )
            payload = json.dumps(
                handoff.to_json_dict(),
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
            offset = 0
            while offset < len(payload):
                written = os.write(descriptor, payload[offset:])
                if written <= 0:
                    raise GenerationHandoffError()
                offset += written
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = None
            os.link(
                temporary,
                GENERATION_HANDOFF_RELATIVE_PATH.name,
                src_dir_fd=directory,
                dst_dir_fd=directory,
                follow_symlinks=False,
            )
            os.fsync(directory)
        except FileExistsError:
            raise
        except Exception as error:
            raise GenerationHandoffError() from error
        finally:
            if descriptor is not None:
                os.close(descriptor)
            try:
                os.unlink(temporary, dir_fd=directory)
            except FileNotFoundError:
                pass
            except OSError:
                pass
            os.close(directory)


def load_hosted_foundry_agent_webjob_handoff(
    source_root: Path,
    readiness_receipt: DailyAzureReadinessReceipt,
    *,
    resource_group: str,
    web_app_name: str,
) -> HostedFoundryAgentWebJobGenerationHandoff | None:
    try:
        handoff = FileHostedFoundryAgentWebJobHandoffStore(source_root).read()
    except Exception:
        return None
    if handoff is None or not _handoff_valid(
        handoff,
        readiness_receipt,
        resource_group,
        web_app_name,
    ):
        return None
    return handoff


_SESSION_FIELDS = (
    "AZURE_RESOURCE_GROUP",
    "AZURE_LOCATION",
    "AZURE_REQUESTED_FOUNDRY_ACCOUNT_NAME",
    "AZURE_FOUNDRY_ACCOUNT_NAME",
    "AZURE_FOUNDRY_PROJECT_NAME",
    "AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT",
    "AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT_NAME",
    "AZURE_AI_FOUNDRY_AGENT_NAME",
    "AZURE_AI_FOUNDRY_AGENT_VERSION",
    "AZURE_AI_FOUNDRY_AGENT_ENDPOINT",
    "AZURE_WEB_APP_NAME",
    "AZURE_WEB_APP_ORIGIN",
)


def _load_current_session_binding(
    source_root: Path,
    config: Any,
    receipt: DailyAzureReadinessReceipt,
) -> _CurrentSessionBinding:
    from src.app.services.daily_azure_environment_rebuild import SESSION_FILE

    path = source_root / SESSION_FILE
    if path.is_symlink() or not path.is_file():
        raise GenerationHandoffError()
    try:
        lines = path.read_text().splitlines()
    except (OSError, UnicodeError) as error:
        raise GenerationHandoffError() from error
    values: dict[str, str] = {}
    for line in lines:
        if "=" not in line:
            raise GenerationHandoffError()
        name, value = line.split("=", 1)
        if name in values or name not in _SESSION_FIELDS:
            raise GenerationHandoffError()
        if (
            not value
            or value != value.strip()
            or any(ord(character) < 32 or ord(character) == 127 for character in value)
        ):
            raise GenerationHandoffError()
        values[name] = value
    if set(values) != set(_SESSION_FIELDS):
        raise GenerationHandoffError()
    expected = {
        "AZURE_RESOURCE_GROUP": receipt.resource_group,
        "AZURE_LOCATION": getattr(config, "location", None),
        "AZURE_REQUESTED_FOUNDRY_ACCOUNT_NAME": (
            receipt.requested_foundry_account_name
        ),
        "AZURE_FOUNDRY_ACCOUNT_NAME": receipt.foundry_account_name,
        "AZURE_FOUNDRY_PROJECT_NAME": receipt.foundry_project_name,
        "AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT_NAME": getattr(
            config, "model_deployment_name", None
        ),
        "AZURE_AI_FOUNDRY_AGENT_NAME": getattr(config, "agent_name", None),
        "AZURE_WEB_APP_NAME": receipt.web_app_name,
    }
    if any(values.get(name) != expected_value for name, expected_value in expected.items()):
        raise GenerationHandoffError()
    agent_version = values["AZURE_AI_FOUNDRY_AGENT_VERSION"]
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.\-]{0,63}", agent_version) is None:
        raise GenerationHandoffError()
    origin = values["AZURE_WEB_APP_ORIGIN"]
    parsed_origin = urlsplit(origin)
    if not (
        parsed_origin.scheme == "https"
        and parsed_origin.hostname
        and parsed_origin.username is None
        and parsed_origin.password is None
        and parsed_origin.path in {"", "/"}
        and not parsed_origin.query
        and not parsed_origin.fragment
    ):
        raise GenerationHandoffError()
    return _CurrentSessionBinding(
        agent_name=values["AZURE_AI_FOUNDRY_AGENT_NAME"],
        agent_version=agent_version,
        hosted_origin=origin.rstrip("/"),
    )


def _build_current_package_binding(source_root: Path) -> tuple[str, str]:
    from src.app.services.web_app_package import (
        authorized_application_artifact_digest,
        build_web_app_package,
        create_package_authorization_session,
    )

    session = create_package_authorization_session()
    package = build_web_app_package(
        source_root,
        authorization_session=session,
    )
    return (
        package.sha256,
        authorized_application_artifact_digest(
            package,
            source_root,
            session,
        ),
    )


def _current_package_is_hosted(origin: str, artifact_digest: str) -> bool:
    from src.app.services.web_app_readiness_verification import (
        UrllibWebAppReadinessTransport,
        verify_web_app_readiness,
    )

    result = verify_web_app_readiness(
        origin,
        transport_factory=UrllibWebAppReadinessTransport,
        expected_application_artifact_digest=artifact_digest,
    )
    return bool(
        result.ok
        and result.application_artifact_matches
    )


class RepositoryEnvironmentGenerationEvidenceReader:
    """Read only the current identity/project generation and local package binding."""

    def __init__(
        self,
        *,
        source_root: Path,
        config: Any,
        readiness_receipt: DailyAzureReadinessReceipt,
        runner: AzureCliRunner,
        session_reader: Callable[
            [Path, Any, DailyAzureReadinessReceipt], _CurrentSessionBinding
        ] = _load_current_session_binding,
        package_reader: Callable[[Path], tuple[str, str]] = (
            _build_current_package_binding
        ),
        hosted_package_verifier: Callable[[str, str], bool] = (
            _current_package_is_hosted
        ),
    ) -> None:
        self._source_root = source_root
        self._config = config
        self._receipt = readiness_receipt
        self._runner = runner
        self._session_reader = session_reader
        self._package_reader = package_reader
        self._hosted_package_verifier = hosted_package_verifier
        self._azure_read_attempted = False

    @property
    def azure_read_attempted(self) -> bool:
        return self._azure_read_attempted

    def _json_read(
        self,
        command: list[str],
        category: GenerationEvidenceFailureCategory,
    ) -> object:
        try:
            self._azure_read_attempted = True
            outcome = self._runner.run(command)
            if (
                type(getattr(outcome, "return_code", None)) is not int
                or outcome.return_code != 0
                or not isinstance(getattr(outcome, "stdout", None), str)
            ):
                raise GenerationEvidenceReadError(
                    category,
                    azure_read_attempted=True,
                )
            return json.loads(outcome.stdout)
        except GenerationEvidenceReadError:
            raise
        except Exception as error:
            raise GenerationEvidenceReadError(
                category,
                azure_read_attempted=True,
            ) from error

    def __call__(self) -> EnvironmentGenerationEvidence:
        from src.app.services.foundry_agent_consumer_rbac_verification import (
            FOUNDRY_PROJECT_QUERY,
            WEB_APP_IDENTITY_QUERY,
            FoundryAgentConsumerRbacVerificationRequest,
            _project_scope,
            _system_identity,
        )

        self._azure_read_attempted = False
        try:
            session = self._session_reader(
                self._source_root,
                self._config,
                self._receipt,
            )
        except Exception as error:
            raise GenerationEvidenceReadError(
                "current_session_binding_invalid",
                azure_read_attempted=False,
            ) from error
        try:
            package_digest, artifact_digest = self._package_reader(
                self._source_root
            )
        except Exception as error:
            raise GenerationEvidenceReadError(
                "local_package_binding_invalid",
                azure_read_attempted=False,
            ) from error
        if not (
            _valid_fingerprint(package_digest)
            and _valid_fingerprint(artifact_digest)
        ):
            raise GenerationEvidenceReadError(
                "local_package_binding_invalid",
                azure_read_attempted=False,
            )
        try:
            hosted_package_current = self._hosted_package_verifier(
                session.hosted_origin,
                artifact_digest,
            )
        except Exception as error:
            raise GenerationEvidenceReadError(
                "hosted_artifact_current_verification_failed",
                azure_read_attempted=False,
            ) from error
        if hosted_package_current is not True:
            raise GenerationEvidenceReadError(
                "hosted_artifact_current_verification_failed",
                azure_read_attempted=False,
            )
        request = FoundryAgentConsumerRbacVerificationRequest(
            mode="live",
            resource_group=self._receipt.resource_group,
            web_app_name=self._receipt.web_app_name,
            foundry_account_name=self._receipt.foundry_account_name,
            foundry_project_name=self._receipt.foundry_project_name,
        )
        identity = self._json_read(
            [
                "az",
                "webapp",
                "show",
                "--resource-group",
                request.resource_group,
                "--name",
                request.web_app_name,
                "--query",
                WEB_APP_IDENTITY_QUERY,
                "--output",
                "json",
                "--only-show-errors",
            ],
            "web_app_identity_read_failed",
        )
        try:
            identity_values = _system_identity(identity, request)
        except Exception as error:
            raise GenerationEvidenceReadError(
                "web_app_identity_invalid",
                azure_read_attempted=True,
            ) from error
        if identity_values is None:
            raise GenerationEvidenceReadError(
                "web_app_identity_invalid",
                azure_read_attempted=True,
            )
        principal_id, web_app_resource_id, subscription_id = identity_values
        project = self._json_read(
            [
                "az",
                "cognitiveservices",
                "account",
                "project",
                "show",
                "--resource-group",
                request.resource_group,
                "--name",
                request.foundry_account_name,
                "--project-name",
                request.foundry_project_name,
                "--query",
                FOUNDRY_PROJECT_QUERY,
                "--output",
                "json",
                "--only-show-errors",
            ],
            "foundry_project_read_failed",
        )
        try:
            project_resource_id = _project_scope(
                project,
                request,
                subscription_id,
            )
        except Exception as error:
            raise GenerationEvidenceReadError(
                "foundry_project_invalid",
                azure_read_attempted=True,
            ) from error
        if project_resource_id is None:
            raise GenerationEvidenceReadError(
                "foundry_project_invalid",
                azure_read_attempted=True,
            )
        resource_group_resource_id = project_resource_id.split(
            "/providers/",
            1,
        )[0]
        return EnvironmentGenerationEvidence(
            resource_group_resource_id=resource_group_resource_id,
            web_app_resource_id=web_app_resource_id,
            principal_id=principal_id,
            package_digest=package_digest,
            foundry_project_resource_id=project_resource_id,
            agent_name=session.agent_name,
            agent_version=session.agent_version,
            webjob_name=WEBJOB_NAME,
        )
