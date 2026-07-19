import json
from pathlib import Path

import pytest

import scripts.package_web_app as script
from src.app.services import web_app_package


@pytest.fixture
def source_tree(tmp_path: Path) -> Path:
    for relative_path, content in {
        "requirements.txt": "fastapi\nuvicorn[standard]\n",
        "src/__init__.py": "",
        "src/app/main.py": "app_name = 'package-cli-fixture'\n",
        "App_Data/jobs/triggered/verify-hosted-foundry-agent/run.py": (
            "from src.app.operations import verify_hosted_foundry_agent\n"
        ),
    }.items():
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    return tmp_path


def test_check_validates_without_creating_package_or_azure_command(
    source_tree: Path,
) -> None:
    result = script.execute("check", source_root=source_tree)

    assert result["ok"] is True
    assert result["mode"] == "check"
    assert result["package_created"] is False
    assert result["azure_command_attempted"] is False
    assert not (source_tree / ".artifacts").exists()


def test_package_creates_only_ignored_local_zip(source_tree: Path) -> None:
    result = script.execute("package", source_root=source_tree)

    assert result["ok"] is True
    assert result["package_created"] is True
    assert result["package_filename"] == "nurse-intake-web-app.zip"
    assert result["package_file_count"] == 4
    assert result["package_sha256_present"] is True
    assert result["azure_command_attempted"] is False
    assert result["recommended_next_step"] == (
        "Add and review App Service Python build automation before any explicit live "
        "deployment."
    )
    created_files = [
        path.relative_to(source_tree).as_posix()
        for path in source_tree.rglob("*")
        if path.is_file()
    ]
    assert ".artifacts/web-app/nurse-intake-web-app.zip" in created_files
    assert all(
        not path.endswith(".zip") or path.startswith(".artifacts/")
        for path in created_files
    )


def test_main_prints_sanitized_json(
    source_tree: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(script, "ROOT", source_tree)

    assert script.main(["--package", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["category"] == "success"
    serialized = json.dumps(payload)
    assert str(source_tree) not in serialized
    assert "package-cli-fixture" not in serialized


def test_conflicting_or_unsupported_modes_fail_safely() -> None:
    with pytest.raises(SystemExit):
        script.main(["--check", "--package"])
    with pytest.raises(SystemExit):
        script.main(["--unsupported"])


def test_failed_rebuild_leaves_no_temporary_zip_or_stale_success(
    source_tree: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = script.execute("package", source_root=source_tree)
    package_path = source_tree / ".artifacts/web-app/nurse-intake-web-app.zip"
    original_bytes = package_path.read_bytes()
    (source_tree / "src/app/main.py").write_text("app_name = 'changed'\n")

    def fail_write(*args: object, **kwargs: object) -> None:
        raise RuntimeError("sensitive package write detail")

    monkeypatch.setattr(web_app_package.zipfile.ZipFile, "writestr", fail_write)

    result = script.execute("package", source_root=source_tree)

    assert first["ok"] is True
    assert result["ok"] is False
    assert result["category"] == "package_write_failed"
    assert result["package_created"] is False
    assert package_path.read_bytes() == original_bytes
    assert list(package_path.parent.glob("*.tmp")) == []
    assert "sensitive package write detail" not in json.dumps(result)
