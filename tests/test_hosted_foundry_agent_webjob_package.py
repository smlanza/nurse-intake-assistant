import json
from pathlib import Path
import zipfile

import pytest


def _package_service():
    import src.app.services.hosted_foundry_agent_webjob_package as service

    return service


@pytest.fixture
def source_tree(tmp_path: Path) -> Path:
    entrypoint = (
        tmp_path
        / "App_Data/jobs/triggered/verify-hosted-foundry-agent/run.py"
    )
    entrypoint.parent.mkdir(parents=True)
    entrypoint.write_text(
        "def run():\n"
        "    return {'ok': True, 'category': 'success'}\n"
    )
    return tmp_path


def test_webjob_only_package_is_exact_allowlisted_and_deterministic(
    source_tree: Path,
) -> None:
    service = _package_service()
    excluded = {
        ".env": "SECRET=do-not-package",
        ".git/config": "do-not-package",
        "tests/test_private.py": "do-not-package",
        "docs/private.md": "do-not-package",
        "infra/private.bicepparam": "do-not-package",
        "src/app/main.py": "do-not-package",
        "__pycache__/run.pyc": "do-not-package",
        ".artifacts/old.zip": "do-not-package",
        "App_Data/jobs/triggered/unrelated/run.py": "do-not-package",
    }
    for relative, content in excluded.items():
        path = source_tree / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    first = service.build_hosted_foundry_agent_webjob_package(source_tree)
    first_bytes = first.package_path.read_bytes()
    second = service.build_hosted_foundry_agent_webjob_package(source_tree)

    assert first.sha256 == second.sha256
    assert second.package_path == (
        source_tree / service.WEBJOB_PACKAGE_RELATIVE_PATH
    )
    assert not (
        source_tree / ".artifacts/hosted-foundry-agent-webjob"
    ).exists()
    assert second.package_path.read_bytes() == first_bytes
    assert second.member_names == ("run.py",)
    with zipfile.ZipFile(second.package_path) as archive:
        assert archive.namelist() == ["run.py"]
        assert archive.read("run.py") == (
            source_tree
            / "App_Data/jobs/triggered/verify-hosted-foundry-agent/run.py"
        ).read_bytes()
        assert archive.getinfo("run.py").date_time == (1980, 1, 1, 0, 0, 0)
    serialized = json.dumps(second.to_json_dict())
    for forbidden in (
        str(source_tree),
        ".env",
        ".git",
        "tests/",
        "docs/",
        ".bicepparam",
        ".artifacts",
        "src/app",
        second.sha256,
    ):
        assert forbidden not in serialized


def test_webjob_package_rejects_symlinked_entrypoint(source_tree: Path) -> None:
    service = _package_service()
    entrypoint = (
        source_tree
        / "App_Data/jobs/triggered/verify-hosted-foundry-agent/run.py"
    )
    outside = source_tree.parent / "outside.py"
    outside.write_text("secret")
    entrypoint.unlink()
    try:
        entrypoint.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks are unavailable")

    with pytest.raises(service.HostedWebJobPackageError) as error:
        service.build_hosted_foundry_agent_webjob_package(source_tree)

    assert error.value.category == "unsafe_symlink"
    assert "secret" not in str(error.value)
    assert str(outside) not in str(error.value)


def test_webjob_package_authorization_is_current_run_one_use(
    source_tree: Path,
) -> None:
    service = _package_service()
    session = service.create_hosted_webjob_package_authorization_session()
    package = service.build_hosted_foundry_agent_webjob_package(
        source_tree,
        authorization_session=session,
    )

    package_bytes = service.consume_hosted_webjob_package_authorization(
        package,
        source_tree,
        session,
    )

    assert package_bytes == package.package_path.read_bytes()
    with pytest.raises(service.HostedWebJobPackageError):
        service.consume_hosted_webjob_package_authorization(
            package,
            source_tree,
            session,
        )


@pytest.mark.parametrize("change", ["mutation", "replacement", "symlink"])
def test_webjob_package_authorization_rejects_changed_package_identity(
    source_tree: Path,
    change: str,
) -> None:
    service = _package_service()
    session = service.create_hosted_webjob_package_authorization_session()
    package = service.build_hosted_foundry_agent_webjob_package(
        source_tree,
        authorization_session=session,
    )
    original = package.package_path.read_bytes()
    if change == "mutation":
        package.package_path.write_bytes(original + b"changed")
    elif change == "replacement":
        package.package_path.unlink()
        package.package_path.write_bytes(original)
        package.package_path.chmod(0o600)
    else:
        outside = source_tree / "outside-package.zip"
        package.package_path.rename(outside)
        try:
            package.package_path.symlink_to(outside)
        except OSError:
            pytest.skip("symlinks are unavailable")

    with pytest.raises(service.HostedWebJobPackageError):
        service.consume_hosted_webjob_package_authorization(
            package,
            source_tree,
            session,
        )


def test_main_web_app_package_excludes_webjob_deployment_content(
    source_tree: Path,
) -> None:
    (source_tree / "requirements.txt").write_text("fastapi\n")
    main = source_tree / "src/app/main.py"
    main.parent.mkdir(parents=True)
    (source_tree / "src/__init__.py").write_text("")
    main.write_text("app = object()\n")
    from src.app.services.web_app_package import plan_web_app_package

    plan = plan_web_app_package(source_tree)

    assert all(not name.startswith("App_Data/jobs/") for name in plan.member_names)
