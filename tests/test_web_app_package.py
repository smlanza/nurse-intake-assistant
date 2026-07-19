import json
from pathlib import Path
import zipfile

import pytest

from src.app.services.web_app_package import (
    PackageSafetyError,
    build_web_app_package,
    plan_web_app_package,
)


@pytest.fixture
def source_tree(tmp_path: Path) -> Path:
    files = {
        "requirements.txt": "fastapi\nuvicorn[standard]\n",
        "src/__init__.py": "",
        "src/app/main.py": "app_name = 'fixture-app'\n",
        "src/app/config/settings.py": "APP_MODE = 'mock'\n",
        "src/app/config/red_flags.yaml": "rules: []\n",
        "src/app/static/demo.html": "<main>fixture demo</main>\n",
        "App_Data/jobs/triggered/verify-hosted-foundry-agent/run.py": (
            "from src.app.operations import verify_hosted_foundry_agent\n"
            "def run():\n"
            "    return verify_hosted_foundry_agent.main(['--live', '--json'])\n"
        ),
    }
    for relative_path, content in files.items():
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    return tmp_path


def test_plan_uses_minimal_allowlist_and_excludes_repository_content(
    source_tree: Path,
) -> None:
    excluded = {
        ".env": "PRIVATE_VALUE=do-not-package\n",
        "infra/local.bicepparam": "param secret = 'do-not-package'\n",
        "tests/test_private.py": "PRIVATE = 'do-not-package'\n",
        "docs/private.md": "do-not-package\n",
        ".github/workflows/deploy.yml": "do-not-package\n",
        "src/app/__pycache__/main.pyc": "do-not-package\n",
        ".artifacts/web-app/old.zip": "do-not-package\n",
        "App_Data/jobs/triggered/unrelated/run.py": "do-not-package\n",
    }
    for relative_path, content in excluded.items():
        path = source_tree / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    plan = plan_web_app_package(source_tree)

    assert plan.member_names == (
        "App_Data/jobs/triggered/verify-hosted-foundry-agent/run.py",
        "requirements.txt",
        "src/__init__.py",
        "src/app/config/red_flags.yaml",
        "src/app/config/settings.py",
        "src/app/main.py",
        "src/app/static/demo.html",
    )
    serialized = " ".join(plan.member_names)
    for forbidden in (".env", ".bicepparam", "tests/", "docs/", ".artifacts"):
        assert forbidden not in serialized
    assert "App_Data/jobs/triggered/unrelated" not in serialized


def test_repeated_builds_are_byte_for_byte_deterministic(source_tree: Path) -> None:
    first = build_web_app_package(source_tree)
    first_bytes = first.package_path.read_bytes()
    second = build_web_app_package(source_tree)

    assert second.sha256 == first.sha256
    assert second.package_path.read_bytes() == first_bytes
    with zipfile.ZipFile(second.package_path) as archive:
        names = archive.namelist()
        assert names == sorted(names)
        assert all(info.date_time == (1980, 1, 1, 0, 0, 0) for info in archive.infolist())
        assert all(not Path(name).is_absolute() and ".." not in Path(name).parts for name in names)


def test_changing_included_source_changes_package_hash(source_tree: Path) -> None:
    before = build_web_app_package(source_tree)
    (source_tree / "src/app/main.py").write_text("app_name = 'changed'\n")

    after = build_web_app_package(source_tree)

    assert after.sha256 != before.sha256


def test_symlink_in_allowlisted_tree_is_rejected(source_tree: Path) -> None:
    outside = source_tree.parent / "outside-secret.txt"
    outside.write_text("do-not-package")
    link = source_tree / "src/app/external.py"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks are not available")

    with pytest.raises(PackageSafetyError) as error:
        plan_web_app_package(source_tree)

    assert error.value.category == "unsafe_symlink"
    assert "do-not-package" not in str(error.value)


def test_symlink_at_fixed_webjob_entrypoint_is_rejected(source_tree: Path) -> None:
    outside = source_tree.parent / "outside-webjob.py"
    outside.write_text("do-not-package")
    entrypoint = (
        source_tree
        / "App_Data/jobs/triggered/verify-hosted-foundry-agent/run.py"
    )
    entrypoint.unlink()
    try:
        entrypoint.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks are not available")

    with pytest.raises(PackageSafetyError) as error:
        plan_web_app_package(source_tree)

    assert error.value.category == "unsafe_symlink"
    assert "do-not-package" not in str(error.value)


def test_plan_rejects_high_risk_content_without_echoing_it(source_tree: Path) -> None:
    unsafe_value = "-----BEGIN PRIVATE KEY-----"
    (source_tree / "src/app/main.py").write_text(unsafe_value)

    with pytest.raises(PackageSafetyError) as error:
        plan_web_app_package(source_tree)

    assert error.value.category == "unsafe_source_content"
    assert unsafe_value not in str(error.value)


@pytest.mark.parametrize("missing", ["requirements.txt", "src/app/main.py"])
def test_incomplete_package_is_rejected_safely(source_tree: Path, missing: str) -> None:
    (source_tree / missing).unlink()

    with pytest.raises(PackageSafetyError) as error:
        plan_web_app_package(source_tree)

    assert error.value.category == "incomplete_package"
    assert str(source_tree) not in str(error.value)


def test_package_output_and_result_are_sanitized(source_tree: Path) -> None:
    (source_tree / ".env").write_text("PRIVATE_VALUE=secret-environment-value\n")

    package = build_web_app_package(source_tree)
    payload = json.dumps(package.to_json_dict(), sort_keys=True)

    assert package.package_path.parent == source_tree / ".artifacts" / "web-app"
    assert package.package_path.name == "nurse-intake-web-app.zip"
    assert package.to_json_dict()["package_sha256"] == package.sha256
    assert str(source_tree) not in payload
    for forbidden in (
        "secret-environment-value",
        "fixture-app",
        "PRIVATE_VALUE",
        ".env",
        "package_path",
    ):
        assert forbidden not in payload


def test_custom_output_outside_artifact_root_is_rejected(source_tree: Path) -> None:
    with pytest.raises(PackageSafetyError) as error:
        plan_web_app_package(source_tree, source_tree / "dist")

    assert error.value.category == "unsafe_output_location"


def test_artifact_root_symlink_cannot_redirect_output_outside_repository(
    source_tree: Path,
) -> None:
    outside = source_tree.parent / "external-artifacts"
    outside.mkdir()
    artifact_root = source_tree / ".artifacts"
    try:
        artifact_root.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks are not available")

    with pytest.raises(PackageSafetyError) as error:
        plan_web_app_package(source_tree)

    assert error.value.category == "unsafe_output_location"
    assert str(outside) not in str(error.value)
    assert list(outside.iterdir()) == []
