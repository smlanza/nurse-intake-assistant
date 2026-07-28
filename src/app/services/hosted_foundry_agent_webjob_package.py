from dataclasses import dataclass
import hashlib
from io import BytesIO
import os
from pathlib import Path
import secrets
import stat
import tempfile
import zipfile


WEBJOB_NAME = "verify-hosted-foundry-agent"
WEBJOB_SOURCE_RELATIVE_PATH = Path(
    "App_Data/jobs/triggered/verify-hosted-foundry-agent/run.py"
)
WEBJOB_ARCHIVE_MEMBER = "run.py"
WEBJOB_PACKAGE_FILENAME = "verify-hosted-foundry-agent.zip"
WEBJOB_PACKAGE_RELATIVE_PATH = (
    Path(".artifacts/hosted-foundry-agent-webjob-package")
    / WEBJOB_PACKAGE_FILENAME
)
FIXED_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
MAX_ENTRYPOINT_SIZE = 128 * 1024
MAX_PACKAGE_SIZE = 256 * 1024
HIGH_RISK_CONTENT_MARKERS = (
    b"-----BEGIN " + b"PRIVATE KEY-----",
    b"-----BEGIN RSA " + b"PRIVATE KEY-----",
    b"-----BEGIN OPENSSH " + b"PRIVATE KEY-----",
    b"Account" + b"Key=",
    b"SharedAccess" + b"Key=",
)
_CONSTRUCTION_SENTINEL = object()


class HostedWebJobPackageError(Exception):
    def __init__(self, category: str) -> None:
        self.category = category
        super().__init__(category)


class HostedWebJobPackageAuthorizationSession:
    __slots__ = ("_nonce", "_issued")

    def __init__(self, sentinel: object) -> None:
        if sentinel is not _CONSTRUCTION_SENTINEL:
            raise TypeError("Package authorization sessions are factory-issued.")
        self._nonce = secrets.token_bytes(32)
        self._issued: dict[str, str] = {}

    def _issue(self, fingerprint: str) -> str:
        self._issued.clear()
        token = secrets.token_hex(32)
        self._issued[token] = hashlib.sha256(
            self._nonce + token.encode() + fingerprint.encode()
        ).hexdigest()
        return token

    def _valid(self, token: str, fingerprint: str) -> bool:
        expected = hashlib.sha256(
            self._nonce + token.encode() + fingerprint.encode()
        ).hexdigest()
        return self._issued.get(token) == expected

    def _consume(self, token: str, fingerprint: str) -> bool:
        if not self._valid(token, fingerprint):
            return False
        del self._issued[token]
        return True


@dataclass(frozen=True)
class HostedFoundryAgentWebJobPackagePlan:
    source_root: Path
    artifact_directory: Path
    package_path: Path
    source_path: Path
    member_names: tuple[str, ...] = (WEBJOB_ARCHIVE_MEMBER,)


class HostedFoundryAgentWebJobPackage:
    __slots__ = (
        "_package_path",
        "_size_bytes",
        "_sha256",
        "_source_digest",
        "_device",
        "_inode",
        "_authorization_session",
        "_authorization_token",
    )

    def __init__(
        self,
        *,
        package_path: Path,
        size_bytes: int,
        sha256: str,
        source_digest: str,
        device: int,
        inode: int,
        authorization_session: HostedWebJobPackageAuthorizationSession,
        authorization_token: str,
        _sentinel: object,
    ) -> None:
        if _sentinel is not _CONSTRUCTION_SENTINEL:
            raise TypeError("WebJob packages are service-issued.")
        self._package_path = package_path
        self._size_bytes = size_bytes
        self._sha256 = sha256
        self._source_digest = source_digest
        self._device = device
        self._inode = inode
        self._authorization_session = authorization_session
        self._authorization_token = authorization_token

    @property
    def package_path(self) -> Path:
        return self._package_path

    @property
    def size_bytes(self) -> int:
        return self._size_bytes

    @property
    def sha256(self) -> str:
        return self._sha256

    @property
    def member_names(self) -> tuple[str, ...]:
        return (WEBJOB_ARCHIVE_MEMBER,)

    def to_json_dict(self) -> dict[str, object]:
        return {
            "ok": True,
            "operation": "package_hosted_foundry_agent_webjob",
            "category": "success",
            "package_created": True,
            "package_file_count": 1,
            "package_sha256_present": True,
            "runtime_binding": "validated_platform_python_prefix",
        }


def create_hosted_webjob_package_authorization_session(
) -> HostedWebJobPackageAuthorizationSession:
    return HostedWebJobPackageAuthorizationSession(_CONSTRUCTION_SENTINEL)


def _safe_artifact_directory(source_root: Path) -> Path:
    artifact_directory = source_root / WEBJOB_PACKAGE_RELATIVE_PATH.parent
    current = source_root
    for part in artifact_directory.relative_to(source_root).parts:
        current = current / part
        if current.is_symlink():
            raise HostedWebJobPackageError("unsafe_output_location")
    resolved = artifact_directory.resolve(strict=False)
    if not resolved.is_relative_to(source_root):
        raise HostedWebJobPackageError("unsafe_output_location")
    return resolved


def _safe_package_bytes(path: Path) -> tuple[bytes, os.stat_result]:
    descriptor: int | None = None
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY
            | os.O_NOFOLLOW
            | getattr(os, "O_CLOEXEC", 0),
        )
        details = os.fstat(descriptor)
        if (
            not stat.S_ISREG(details.st_mode)
            or stat.S_IMODE(details.st_mode) != 0o600
            or details.st_size <= 0
            or details.st_size > MAX_PACKAGE_SIZE
        ):
            raise HostedWebJobPackageError("package_proof_invalid")
        chunks: list[bytes] = []
        remaining = MAX_PACKAGE_SIZE + 1
        while remaining:
            chunk = os.read(descriptor, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        if len(payload) != details.st_size or len(payload) > MAX_PACKAGE_SIZE:
            raise HostedWebJobPackageError("package_proof_invalid")
        return payload, details
    except HostedWebJobPackageError:
        raise
    except OSError as error:
        raise HostedWebJobPackageError("package_proof_invalid") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def plan_hosted_foundry_agent_webjob_package(
    source_root: Path,
) -> HostedFoundryAgentWebJobPackagePlan:
    if source_root.is_symlink():
        raise HostedWebJobPackageError("unsafe_symlink")
    try:
        resolved_root = source_root.resolve(strict=True)
    except OSError as error:
        raise HostedWebJobPackageError("incomplete_package") from error
    if not resolved_root.is_dir():
        raise HostedWebJobPackageError("incomplete_package")
    source_path = resolved_root / WEBJOB_SOURCE_RELATIVE_PATH
    current = resolved_root
    for part in WEBJOB_SOURCE_RELATIVE_PATH.parts:
        current = current / part
        if current.is_symlink():
            raise HostedWebJobPackageError("unsafe_symlink")
    try:
        details = source_path.stat()
    except OSError as error:
        raise HostedWebJobPackageError("incomplete_package") from error
    if (
        not source_path.is_file()
        or not stat.S_ISREG(details.st_mode)
        or details.st_size <= 0
        or details.st_size > MAX_ENTRYPOINT_SIZE
    ):
        raise HostedWebJobPackageError("incomplete_package")
    artifact_directory = _safe_artifact_directory(resolved_root)
    return HostedFoundryAgentWebJobPackagePlan(
        source_root=resolved_root,
        artifact_directory=artifact_directory,
        package_path=resolved_root / WEBJOB_PACKAGE_RELATIVE_PATH,
        source_path=source_path,
    )


def _safe_source(plan: HostedFoundryAgentWebJobPackagePlan) -> bytes:
    try:
        descriptor = os.open(
            plan.source_path,
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
        )
        with os.fdopen(descriptor, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise HostedWebJobPackageError("unsafe_source")
            content = stream.read(MAX_ENTRYPOINT_SIZE + 1)
    except HostedWebJobPackageError:
        raise
    except OSError as error:
        raise HostedWebJobPackageError("unsafe_source") from error
    if (
        not content
        or len(content) > MAX_ENTRYPOINT_SIZE
        or str(plan.source_root).encode() in content
        or any(marker in content for marker in HIGH_RISK_CONTENT_MARKERS)
    ):
        raise HostedWebJobPackageError("unsafe_source")
    return content


def _package_fingerprint(
    plan: HostedFoundryAgentWebJobPackagePlan,
    *,
    size_bytes: int,
    sha256: str,
    source_digest: str,
) -> str:
    values = (
        str(plan.source_root),
        str(plan.package_path),
        WEBJOB_ARCHIVE_MEMBER,
        str(size_bytes),
        sha256,
        source_digest,
    )
    return hashlib.sha256("\0".join(values).encode()).hexdigest()


def build_hosted_foundry_agent_webjob_package(
    source_root: Path,
    *,
    authorization_session: HostedWebJobPackageAuthorizationSession | None = None,
) -> HostedFoundryAgentWebJobPackage:
    plan = plan_hosted_foundry_agent_webjob_package(source_root)
    source = _safe_source(plan)
    source_digest = hashlib.sha256(source).hexdigest()
    temporary_path: Path | None = None
    try:
        plan.artifact_directory.mkdir(parents=True, exist_ok=True)
        if (
            _safe_artifact_directory(plan.source_root)
            != plan.artifact_directory
            or plan.package_path.is_symlink()
        ):
            raise HostedWebJobPackageError("unsafe_output_location")
        os.chmod(plan.artifact_directory, 0o700)
        with tempfile.NamedTemporaryFile(
            mode="w+b",
            prefix=f".{WEBJOB_PACKAGE_FILENAME}.",
            suffix=".tmp",
            dir=plan.artifact_directory,
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            with zipfile.ZipFile(
                temporary,
                mode="w",
                compression=zipfile.ZIP_DEFLATED,
                compresslevel=9,
            ) as archive:
                info = zipfile.ZipInfo(
                    WEBJOB_ARCHIVE_MEMBER,
                    FIXED_ZIP_TIMESTAMP,
                )
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                archive.writestr(info, source, compresslevel=9)
        temporary_path.replace(plan.package_path)
        temporary_path = None
        os.chmod(plan.package_path, 0o600)
        package_bytes, package_details = _safe_package_bytes(
            plan.package_path
        )
    except HostedWebJobPackageError:
        raise
    except Exception as error:
        raise HostedWebJobPackageError("package_write_failed") from error
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
    sha256 = hashlib.sha256(package_bytes).hexdigest()
    session = (
        authorization_session
        or create_hosted_webjob_package_authorization_session()
    )
    fingerprint = _package_fingerprint(
        plan,
        size_bytes=len(package_bytes),
        sha256=sha256,
        source_digest=source_digest,
    )
    token = session._issue(fingerprint)
    return HostedFoundryAgentWebJobPackage(
        package_path=plan.package_path,
        size_bytes=len(package_bytes),
        sha256=sha256,
        source_digest=source_digest,
        device=package_details.st_dev,
        inode=package_details.st_ino,
        authorization_session=session,
        authorization_token=token,
        _sentinel=_CONSTRUCTION_SENTINEL,
    )


def validate_hosted_foundry_agent_webjob_package(
    package: HostedFoundryAgentWebJobPackage,
    source_root: Path,
    authorization_session: HostedWebJobPackageAuthorizationSession,
) -> HostedFoundryAgentWebJobPackage:
    if (
        not isinstance(package, HostedFoundryAgentWebJobPackage)
        or not isinstance(
            authorization_session,
            HostedWebJobPackageAuthorizationSession,
        )
    ):
        raise HostedWebJobPackageError("package_proof_invalid")
    plan = plan_hosted_foundry_agent_webjob_package(source_root)
    source = _safe_source(plan)
    source_digest = hashlib.sha256(source).hexdigest()
    try:
        package_bytes, package_details = _safe_package_bytes(
            package.package_path
        )
        with zipfile.ZipFile(BytesIO(package_bytes)) as archive:
            if (
                archive.namelist() != [WEBJOB_ARCHIVE_MEMBER]
                or archive.read(WEBJOB_ARCHIVE_MEMBER) != source
            ):
                raise HostedWebJobPackageError("package_proof_invalid")
    except HostedWebJobPackageError:
        raise
    except Exception as error:
        raise HostedWebJobPackageError("package_proof_invalid") from error
    sha256 = hashlib.sha256(package_bytes).hexdigest()
    fingerprint = _package_fingerprint(
        plan,
        size_bytes=len(package_bytes),
        sha256=sha256,
        source_digest=source_digest,
    )
    if (
        package.package_path != plan.package_path
        or package.package_path.is_symlink()
        or package._device != package_details.st_dev
        or package._inode != package_details.st_ino
        or package.size_bytes != len(package_bytes)
        or package.sha256 != sha256
        or package._source_digest != source_digest
        or package._authorization_session is not authorization_session
        or not authorization_session._valid(
            package._authorization_token,
            fingerprint,
        )
    ):
        raise HostedWebJobPackageError("package_proof_invalid")
    return package


def consume_hosted_webjob_package_authorization(
    package: HostedFoundryAgentWebJobPackage,
    source_root: Path,
    authorization_session: HostedWebJobPackageAuthorizationSession,
) -> bytes:
    validate_hosted_foundry_agent_webjob_package(
        package,
        source_root,
        authorization_session,
    )
    plan = plan_hosted_foundry_agent_webjob_package(source_root)
    source = _safe_source(plan)
    source_digest = hashlib.sha256(source).hexdigest()
    try:
        package_bytes, package_details = _safe_package_bytes(
            package.package_path
        )
        with zipfile.ZipFile(BytesIO(package_bytes)) as archive:
            archive_valid = bool(
                archive.namelist() == [WEBJOB_ARCHIVE_MEMBER]
                and archive.read(WEBJOB_ARCHIVE_MEMBER) == source
            )
    except Exception as error:
        raise HostedWebJobPackageError("package_proof_invalid") from error
    if (
        not archive_valid
        or package._device != package_details.st_dev
        or package._inode != package_details.st_ino
        or source_digest != package._source_digest
        or len(package_bytes) != package.size_bytes
        or hashlib.sha256(package_bytes).hexdigest() != package.sha256
    ):
        raise HostedWebJobPackageError("package_proof_invalid")
    fingerprint = _package_fingerprint(
        plan,
        size_bytes=package.size_bytes,
        sha256=package.sha256,
        source_digest=source_digest,
    )
    if not authorization_session._consume(
        package._authorization_token,
        fingerprint,
    ):
        raise HostedWebJobPackageError("package_proof_invalid")
    return package_bytes
