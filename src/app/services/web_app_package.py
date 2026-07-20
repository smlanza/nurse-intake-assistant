from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import os
from pathlib import Path, PurePosixPath
import secrets
import stat
import tempfile
import zipfile

from src.app.services.application_artifact import (
    ARTIFACT_MARKER_FILENAME,
    build_application_artifact_marker,
)


PACKAGE_FILENAME = "nurse-intake-web-app.zip"
FIXED_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
HOSTED_VERIFIER_WEBJOB_ENTRYPOINT = (
    "App_Data/jobs/triggered/verify-hosted-foundry-agent/run.py"
)
ARTIFACT_MARKER_MEMBER = f"src/app/{ARTIFACT_MARKER_FILENAME}"
REQUIRED_MEMBERS = (
    "requirements.txt",
    "src/__init__.py",
    "src/app/main.py",
    HOSTED_VERIFIER_WEBJOB_ENTRYPOINT,
    ARTIFACT_MARKER_MEMBER,
)
HIGH_RISK_CONTENT_MARKERS = (
    b"-----BEGIN " + b"PRIVATE KEY-----",
    b"-----BEGIN RSA " + b"PRIVATE KEY-----",
    b"-----BEGIN OPENSSH " + b"PRIVATE KEY-----",
    b"Account" + b"Key=",
    b"SharedAccess" + b"Key=",
)
_CONSTRUCTION_SENTINEL = object()


class PackageSafetyError(Exception):
    def __init__(self, category: str) -> None:
        self.category = category
        super().__init__(category)


@dataclass(frozen=True)
class WebAppPackagePlan:
    source_root: Path
    artifact_directory: Path
    package_path: Path
    member_names: tuple[str, ...]


class PackageAuthorizationSession:
    __slots__ = ("_nonce", "_issued")

    def __init__(self, sentinel: object) -> None:
        if sentinel is not _CONSTRUCTION_SENTINEL:
            raise TypeError("Package authorization sessions are factory-issued.")
        self._nonce = secrets.token_bytes(32)
        self._issued: dict[str, str] = {}

    def _issue(self, fingerprint: str) -> str:
        self._issued.clear()
        token = secrets.token_hex(32)
        authorized = hashlib.sha256(
            self._nonce + token.encode() + fingerprint.encode()
        ).hexdigest()
        self._issued[token] = authorized
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


class WebAppPackage:
    __slots__ = (
        "_package_path",
        "_file_count",
        "_size_bytes",
        "_sha256",
        "_artifact_digest",
        "_authorization_session",
        "_authorization_token",
    )

    def __init__(
        self,
        *,
        package_path: Path,
        file_count: int,
        size_bytes: int,
        sha256: str,
        artifact_digest: str,
        authorization_session: PackageAuthorizationSession,
        authorization_token: str,
        _sentinel: object,
    ) -> None:
        if _sentinel is not _CONSTRUCTION_SENTINEL:
            raise TypeError("Web application packages are service-issued.")
        self._package_path = package_path
        self._file_count = file_count
        self._size_bytes = size_bytes
        self._sha256 = sha256
        self._artifact_digest = artifact_digest
        self._authorization_session = authorization_session
        self._authorization_token = authorization_token

    @property
    def package_path(self) -> Path:
        return self._package_path

    @property
    def file_count(self) -> int:
        return self._file_count

    @property
    def size_bytes(self) -> int:
        return self._size_bytes

    @property
    def sha256(self) -> str:
        return self._sha256

    def to_json_dict(self) -> dict[str, object]:
        return {
            "ok": True,
            "operation": "package_web_app",
            "category": "success",
            "package_created": True,
            "package_filename": self.package_path.name,
            "package_size_bytes": self.size_bytes,
            "package_file_count": self.file_count,
            "package_sha256_present": True,
        }


@dataclass(frozen=True)
class ImmutableDeploymentArtifact:
    path: Path
    sha256: str
    directory: Path
    deployment_root: Path
    _sentinel: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._sentinel is not _CONSTRUCTION_SENTINEL:
            raise TypeError("Deployment artifacts are service-issued.")


def create_package_authorization_session() -> PackageAuthorizationSession:
    return PackageAuthorizationSession(_CONSTRUCTION_SENTINEL)


def _is_allowlisted(relative_path: PurePosixPath) -> bool:
    if relative_path.as_posix() == HOSTED_VERIFIER_WEBJOB_ENTRYPOINT:
        return True
    parts = relative_path.parts
    if relative_path.as_posix() == "requirements.txt":
        return True
    if not parts or parts[0] != "src":
        return False
    if relative_path.suffix == ".py":
        return True
    if parts[:3] == ("src", "app", "config"):
        return relative_path.suffix in {".yaml", ".yml"}
    if parts[:3] == ("src", "app", "static"):
        return relative_path.suffix in {".css", ".html", ".js"}
    return False


def _safe_artifact_directory(source_root: Path, requested: Path | None) -> Path:
    artifact_root = source_root / ".artifacts"
    artifact_directory = requested or artifact_root / "web-app"
    if artifact_root.is_symlink():
        raise PackageSafetyError("unsafe_output_location")
    resolved_artifact_root = artifact_root.resolve(strict=False)
    if not resolved_artifact_root.is_relative_to(source_root):
        raise PackageSafetyError("unsafe_output_location")
    try:
        relative_directory = artifact_directory.relative_to(artifact_root)
    except ValueError as error:
        raise PackageSafetyError("unsafe_output_location") from error
    if ".." in relative_directory.parts:
        raise PackageSafetyError("unsafe_output_location")
    current = artifact_root
    for part in relative_directory.parts:
        current = current / part
        if current.is_symlink():
            raise PackageSafetyError("unsafe_output_location")
    resolved_directory = artifact_directory.resolve(strict=False)
    if not resolved_directory.is_relative_to(resolved_artifact_root) or not (
        resolved_directory.is_relative_to(source_root)
    ):
        raise PackageSafetyError("unsafe_output_location")
    return resolved_directory


def plan_web_app_package(
    source_root: Path,
    artifact_directory: Path | None = None,
) -> WebAppPackagePlan:
    if source_root.is_symlink():
        raise PackageSafetyError("unsafe_symlink")
    try:
        resolved_root = source_root.resolve(strict=True)
    except OSError as error:
        raise PackageSafetyError("incomplete_package") from error
    if not resolved_root.is_dir():
        raise PackageSafetyError("incomplete_package")
    resolved_artifact_directory = _safe_artifact_directory(
        resolved_root, artifact_directory
    )
    requirements = resolved_root / "requirements.txt"
    src_root = resolved_root / "src"
    if requirements.is_symlink() or src_root.is_symlink():
        raise PackageSafetyError("unsafe_symlink")
    if not requirements.is_file() or not src_root.is_dir():
        raise PackageSafetyError("incomplete_package")
    webjob_entrypoint = resolved_root / HOSTED_VERIFIER_WEBJOB_ENTRYPOINT
    current = resolved_root
    for part in PurePosixPath(HOSTED_VERIFIER_WEBJOB_ENTRYPOINT).parts:
        current = current / part
        if current.is_symlink():
            raise PackageSafetyError("unsafe_symlink")
    if not webjob_entrypoint.is_file():
        raise PackageSafetyError("incomplete_package")
    selected = [
        "requirements.txt",
        HOSTED_VERIFIER_WEBJOB_ENTRYPOINT,
        ARTIFACT_MARKER_MEMBER,
    ]
    for path in src_root.rglob("*"):
        if path.is_symlink():
            raise PackageSafetyError("unsafe_symlink")
        if not path.is_file():
            continue
        try:
            relative = PurePosixPath(path.relative_to(resolved_root).as_posix())
        except ValueError as error:
            raise PackageSafetyError("unsafe_package_member") from error
        if relative.as_posix() != ARTIFACT_MARKER_MEMBER and _is_allowlisted(relative):
            selected.append(relative.as_posix())
    member_names = tuple(sorted(set(selected)))
    if not set(REQUIRED_MEMBERS).issubset(member_names):
        raise PackageSafetyError("incomplete_package")
    for name in member_names:
        member = PurePosixPath(name)
        if member.is_absolute() or ".." in member.parts:
            raise PackageSafetyError("unsafe_package_member")
        lowered = name.lower()
        if (
            "/.env" in f"/{lowered}"
            or lowered.endswith(".bicepparam")
            or lowered.startswith(".artifacts/")
        ):
            raise PackageSafetyError("unsafe_package_member")
    package_path = resolved_artifact_directory / PACKAGE_FILENAME
    if package_path.is_symlink():
        raise PackageSafetyError("unsafe_output_location")
    plan = WebAppPackagePlan(
        resolved_root,
        resolved_artifact_directory,
        package_path,
        member_names,
    )
    for name in _source_member_names(plan):
        _read_safe_member(plan, name)
    return plan


def _source_member_names(plan: WebAppPackagePlan) -> tuple[str, ...]:
    return tuple(name for name in plan.member_names if name != ARTIFACT_MARKER_MEMBER)


def _read_safe_member(plan: WebAppPackagePlan, name: str) -> bytes:
    path = plan.source_root / name
    if path.is_symlink():
        raise PackageSafetyError("unsafe_symlink")
    try:
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise PackageSafetyError("incomplete_package") from error
    if not resolved.is_relative_to(plan.source_root) or not resolved.is_file():
        raise PackageSafetyError("unsafe_package_member")
    try:
        content = resolved.read_bytes()
    except OSError as error:
        raise PackageSafetyError("package_read_failed") from error
    root_marker = str(plan.source_root).encode()
    if root_marker in content or any(marker in content for marker in HIGH_RISK_CONTENT_MARKERS):
        raise PackageSafetyError("unsafe_source_content")
    return content


def _source_contents(plan: WebAppPackagePlan) -> tuple[tuple[str, bytes], ...]:
    return tuple(
        (name, _read_safe_member(plan, name)) for name in _source_member_names(plan)
    )


def _source_artifact_digest(contents: tuple[tuple[str, bytes], ...]) -> str:
    digest = hashlib.sha256()
    for name, content in contents:
        encoded_name = name.encode()
        digest.update(len(encoded_name).to_bytes(8, "big"))
        digest.update(encoded_name)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def build_web_app_package(
    source_root: Path,
    artifact_directory: Path | None = None,
    *,
    authorization_session: PackageAuthorizationSession | None = None,
) -> WebAppPackage:
    plan = plan_web_app_package(source_root, artifact_directory)
    contents = _source_contents(plan)
    artifact_digest = _source_artifact_digest(contents)
    archive_contents = tuple(
        sorted(
            (*contents, (ARTIFACT_MARKER_MEMBER, build_application_artifact_marker(artifact_digest))),
            key=lambda item: item[0],
        )
    )
    temporary_path: Path | None = None
    try:
        plan.artifact_directory.mkdir(parents=True, exist_ok=True)
        if (
            _safe_artifact_directory(plan.source_root, plan.artifact_directory)
            != plan.artifact_directory
            or plan.package_path.is_symlink()
        ):
            raise PackageSafetyError("unsafe_output_location")
        with tempfile.NamedTemporaryFile(
            mode="w+b",
            prefix=f".{PACKAGE_FILENAME}.",
            suffix=".tmp",
            dir=plan.artifact_directory,
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            with zipfile.ZipFile(
                temporary_file,
                mode="w",
                compression=zipfile.ZIP_DEFLATED,
                compresslevel=9,
            ) as archive:
                for name, content in archive_contents:
                    info = zipfile.ZipInfo(name, FIXED_ZIP_TIMESTAMP)
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info.create_system = 3
                    info.external_attr = 0o100644 << 16
                    archive.writestr(info, content, compresslevel=9)
        if plan.package_path.is_symlink():
            raise PackageSafetyError("unsafe_output_location")
        temporary_path.replace(plan.package_path)
        temporary_path = None
        package_bytes = plan.package_path.read_bytes()
    except PackageSafetyError:
        raise
    except Exception as error:
        raise PackageSafetyError("package_write_failed") from error
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
    session = authorization_session or create_package_authorization_session()
    values = (
        plan.package_path,
        len(plan.member_names),
        len(package_bytes),
        hashlib.sha256(package_bytes).hexdigest(),
        artifact_digest,
    )
    fingerprint = _package_fingerprint(plan, *values[1:])
    token = session._issue(fingerprint)
    return WebAppPackage(
        package_path=values[0],
        file_count=values[1],
        size_bytes=values[2],
        sha256=values[3],
        artifact_digest=values[4],
        authorization_session=session,
        authorization_token=token,
        _sentinel=_CONSTRUCTION_SENTINEL,
    )


def validate_web_app_package(
    package: WebAppPackage,
    source_root: Path,
    authorization_session: PackageAuthorizationSession | None = None,
) -> WebAppPackage:
    if not isinstance(package, WebAppPackage) or authorization_session is None:
        raise PackageSafetyError("package_proof_invalid")
    plan = plan_web_app_package(source_root)
    if package.package_path != plan.package_path or package.package_path.is_symlink():
        raise PackageSafetyError("package_proof_invalid")
    contents = _source_contents(plan)
    artifact_digest = _source_artifact_digest(contents)
    if artifact_digest != package._artifact_digest:
        raise PackageSafetyError("package_proof_invalid")
    fingerprint = _package_fingerprint(
        plan,
        package.file_count,
        package.size_bytes,
        package.sha256,
        artifact_digest,
    )
    if (
        package._authorization_session is not authorization_session
        or not authorization_session._valid(package._authorization_token, fingerprint)
    ):
        raise PackageSafetyError("package_proof_invalid")
    expected = dict(contents)
    expected[ARTIFACT_MARKER_MEMBER] = build_application_artifact_marker(
        artifact_digest
    )
    try:
        package_bytes = package.package_path.read_bytes()
        if (
            len(package_bytes) != package.size_bytes
            or hashlib.sha256(package_bytes).hexdigest() != package.sha256
        ):
            raise PackageSafetyError("package_proof_invalid")
        with zipfile.ZipFile(package.package_path) as archive:
            names = tuple(sorted(archive.namelist()))
            if names != plan.member_names or package.file_count != len(names):
                raise PackageSafetyError("package_proof_invalid")
            for name in names:
                if archive.read(name) != expected[name]:
                    raise PackageSafetyError("package_proof_invalid")
    except PackageSafetyError:
        raise
    except Exception as error:
        raise PackageSafetyError("package_proof_invalid") from error
    return package


def consume_web_app_package_authorization(
    package: WebAppPackage,
    source_root: Path,
    authorization_session: PackageAuthorizationSession,
) -> None:
    validate_web_app_package(package, source_root, authorization_session)
    plan = plan_web_app_package(source_root)
    fingerprint = _package_fingerprint(
        plan,
        package.file_count,
        package.size_bytes,
        package.sha256,
        package._artifact_digest,
    )
    if not authorization_session._consume(package._authorization_token, fingerprint):
        raise PackageSafetyError("package_proof_invalid")


def materialize_immutable_deployment_artifact(
    package: WebAppPackage,
    source_root: Path,
    authorization_session: PackageAuthorizationSession,
) -> ImmutableDeploymentArtifact:
    validate_web_app_package(package, source_root, authorization_session)
    resolved_root = source_root.resolve(strict=True)
    deployment_root = _safe_artifact_directory(
        resolved_root,
        resolved_root / ".artifacts/web-app/deployments",
    )
    deployment_root.mkdir(parents=True, exist_ok=True)
    if deployment_root.is_symlink():
        raise PackageSafetyError("unsafe_deployment_artifact")
    os.chmod(deployment_root, 0o700)

    source_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        source_descriptor = os.open(package.package_path, source_flags)
        with os.fdopen(source_descriptor, "rb") as source_stream:
            if not stat.S_ISREG(os.fstat(source_stream.fileno()).st_mode):
                raise PackageSafetyError("package_proof_invalid")
            package_bytes = source_stream.read()
    except PackageSafetyError:
        raise
    except OSError as error:
        raise PackageSafetyError("package_proof_invalid") from error
    if (
        len(package_bytes) != package.size_bytes
        or hashlib.sha256(package_bytes).hexdigest() != package.sha256
    ):
        raise PackageSafetyError("package_proof_invalid")

    try:
        directory = Path(tempfile.mkdtemp(prefix="deployment-", dir=deployment_root))
        os.chmod(directory, 0o700)
        artifact_path = directory / PACKAGE_FILENAME
        flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0)
        )
        descriptor = os.open(artifact_path, flags, 0o400)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(package_bytes)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(artifact_path, 0o400)
        artifact = ImmutableDeploymentArtifact(
            artifact_path,
            package.sha256,
            directory,
            deployment_root,
            _CONSTRUCTION_SENTINEL,
        )
        verify_immutable_deployment_artifact(artifact)
        return artifact
    except PackageSafetyError:
        raise
    except OSError as error:
        raise PackageSafetyError("unsafe_deployment_artifact") from error


def verify_immutable_deployment_artifact(
    artifact: ImmutableDeploymentArtifact,
) -> None:
    if (
        not isinstance(artifact, ImmutableDeploymentArtifact)
        or artifact.path.parent != artifact.directory
        or artifact.directory.parent != artifact.deployment_root
        or not artifact.directory.name.startswith("deployment-")
        or artifact.path.is_symlink()
        or artifact.directory.is_symlink()
        or artifact.deployment_root.is_symlink()
    ):
        raise PackageSafetyError("unsafe_deployment_artifact")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(artifact.path, flags)
        with os.fdopen(descriptor, "rb") as stream:
            metadata = os.fstat(stream.fileno())
            content = stream.read()
    except OSError as error:
        raise PackageSafetyError("unsafe_deployment_artifact") from error
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_mode & 0o777 != 0o400
        or hashlib.sha256(content).hexdigest() != artifact.sha256
    ):
        raise PackageSafetyError("unsafe_deployment_artifact")


def discard_immutable_deployment_artifact(
    artifact: ImmutableDeploymentArtifact,
) -> None:
    if (
        not isinstance(artifact, ImmutableDeploymentArtifact)
        or artifact._sentinel is not _CONSTRUCTION_SENTINEL
        or artifact.path.parent != artifact.directory
        or artifact.directory.parent != artifact.deployment_root
        or not artifact.directory.name.startswith("deployment-")
        or artifact.directory.is_symlink()
        or artifact.deployment_root.is_symlink()
    ):
        return
    try:
        os.unlink(artifact.path)
    except FileNotFoundError:
        pass
    try:
        os.rmdir(artifact.directory)
    except OSError:
        pass


def authorized_application_artifact_digest(
    package: WebAppPackage,
    source_root: Path,
    authorization_session: PackageAuthorizationSession,
) -> str:
    validate_web_app_package(package, source_root, authorization_session)
    return package._artifact_digest


def _package_fingerprint(
    plan: WebAppPackagePlan,
    file_count: int,
    size_bytes: int,
    package_sha256: str,
    artifact_digest: str,
) -> str:
    payload = "\0".join(
        (
            str(plan.source_root),
            str(plan.package_path),
            "\n".join(plan.member_names),
            str(file_count),
            str(size_bytes),
            package_sha256,
            artifact_digest,
        )
    ).encode()
    return hashlib.sha256(payload).hexdigest()
