from dataclasses import dataclass
import hashlib
from pathlib import Path, PurePosixPath
import tempfile
import zipfile


PACKAGE_FILENAME = "nurse-intake-web-app.zip"
FIXED_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
REQUIRED_MEMBERS = (
    "requirements.txt",
    "src/__init__.py",
    "src/app/main.py",
)
HIGH_RISK_CONTENT_MARKERS = (
    b"-----BEGIN " + b"PRIVATE KEY-----",
    b"-----BEGIN RSA " + b"PRIVATE KEY-----",
    b"-----BEGIN OPENSSH " + b"PRIVATE KEY-----",
    b"Account" + b"Key=",
    b"SharedAccess" + b"Key=",
)


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


@dataclass(frozen=True)
class WebAppPackage:
    package_path: Path
    file_count: int
    size_bytes: int
    sha256: str

    def to_json_dict(self) -> dict[str, object]:
        return {
            "ok": True,
            "operation": "package_web_app",
            "category": "success",
            "package_created": True,
            "package_filename": self.package_path.name,
            "package_size_bytes": self.size_bytes,
            "package_file_count": self.file_count,
            "package_sha256": self.sha256,
            "package_sha256_present": True,
        }


def _is_allowlisted(relative_path: PurePosixPath) -> bool:
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
        resolved_root,
        artifact_directory,
    )
    requirements = resolved_root / "requirements.txt"
    src_root = resolved_root / "src"
    if requirements.is_symlink() or src_root.is_symlink():
        raise PackageSafetyError("unsafe_symlink")
    if not requirements.is_file() or not src_root.is_dir():
        raise PackageSafetyError("incomplete_package")

    selected: list[str] = ["requirements.txt"]
    for path in src_root.rglob("*"):
        if path.is_symlink():
            raise PackageSafetyError("unsafe_symlink")
        if not path.is_file():
            continue
        try:
            relative = PurePosixPath(path.relative_to(resolved_root).as_posix())
        except ValueError as error:
            raise PackageSafetyError("unsafe_package_member") from error
        if _is_allowlisted(relative):
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
        source_root=resolved_root,
        artifact_directory=resolved_artifact_directory,
        package_path=package_path,
        member_names=member_names,
    )
    for name in plan.member_names:
        _read_safe_member(plan, name)
    return plan


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


def build_web_app_package(
    source_root: Path,
    artifact_directory: Path | None = None,
) -> WebAppPackage:
    plan = plan_web_app_package(source_root, artifact_directory)
    contents = [(name, _read_safe_member(plan, name)) for name in plan.member_names]
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
                for name, content in contents:
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

    return WebAppPackage(
        package_path=plan.package_path,
        file_count=len(plan.member_names),
        size_bytes=len(package_bytes),
        sha256=hashlib.sha256(package_bytes).hexdigest(),
    )
