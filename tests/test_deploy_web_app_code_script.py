import json
from pathlib import Path

import pytest

import scripts.deploy_web_app_code as script


class FakeRunner:
    def __init__(self, result: script.CommandResult | None = None) -> None:
        self.result = result or script.CommandResult(0, "sensitive stdout", "")
        self.calls: list[list[str]] = []

    def run(self, args: list[str]) -> script.CommandResult:
        assert isinstance(args, list)
        self.calls.append(args)
        return self.result


@pytest.fixture
def source_tree(tmp_path: Path) -> Path:
    for relative_path, content in {
        "requirements.txt": "fastapi\nuvicorn[standard]\n",
        "src/__init__.py": "",
        "src/app/main.py": "app_name = 'deploy-cli-fixture'\n",
    }.items():
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    return tmp_path


def test_check_and_package_modes_make_no_azure_command(source_tree: Path) -> None:
    for mode in ("check", "package"):
        runner = FakeRunner()
        result = script.execute(
            script.DeploymentRequest(mode=mode),
            runner=runner,
            source_root=source_tree,
        )
        assert result["ok"] is True
        assert result["azure_command_attempted"] is False
        assert result["deployment_accepted"] is False
        assert result["hosted_application_verified"] is False
        assert runner.calls == []


def test_live_requires_explicit_resource_group_web_app_and_json() -> None:
    with pytest.raises(SystemExit):
        script.main(["--live", "--json"])
    with pytest.raises(SystemExit):
        script.main(["--live", "--resource-group", "rg", "--web-app", "app"])


def test_live_uses_one_narrow_discrete_azure_deployment_command(
    source_tree: Path,
) -> None:
    runner = FakeRunner()
    result = script.execute(
        script.DeploymentRequest(
            mode="live",
            resource_group="fictional-rg",
            web_app_name="fictional-web-app",
        ),
        runner=runner,
        source_root=source_tree,
    )

    package_path = source_tree / ".artifacts/web-app/nurse-intake-web-app.zip"
    assert runner.calls == [[
        "az",
        "webapp",
        "deploy",
        "--resource-group",
        "fictional-rg",
        "--name",
        "fictional-web-app",
        "--src-path",
        str(package_path),
        "--type",
        "zip",
        "--clean",
        "true",
        "--restart",
        "true",
        "--output",
        "none",
    ]]
    assert result["ok"] is True
    assert result["azure_command_attempted"] is True
    assert result["deployment_accepted"] is True
    assert result["hosted_application_verified"] is False


@pytest.mark.parametrize(
    ("stderr", "category"),
    [
        ("Please run az login. secret-token", "authentication_or_authorization_failed"),
        ("Raw deployment failure with sensitive detail", "deployment_failed"),
    ],
)
def test_live_failure_is_stable_and_does_not_serialize_cli_output(
    source_tree: Path,
    stderr: str,
    category: str,
) -> None:
    runner = FakeRunner(script.CommandResult(1, "sensitive stdout", stderr))

    result = script.execute(
        script.DeploymentRequest("live", "fictional-rg", "fictional-app"),
        runner=runner,
        source_root=source_tree,
    )

    serialized = json.dumps(result)
    assert result["ok"] is False
    assert result["category"] == category
    assert result["azure_command_attempted"] is True
    assert result["deployment_accepted"] is False
    assert "sensitive stdout" not in serialized
    assert stderr not in serialized
    assert "secret-token" not in serialized


def test_package_failure_never_attempts_deployment(source_tree: Path) -> None:
    (source_tree / "requirements.txt").unlink()
    runner = FakeRunner()

    result = script.execute(
        script.DeploymentRequest("live", "fictional-rg", "fictional-app"),
        runner=runner,
        source_root=source_tree,
    )

    assert result["category"] == "incomplete_package"
    assert result["package_created"] is False
    assert result["azure_command_attempted"] is False
    assert runner.calls == []


def test_live_command_never_couples_forbidden_operations(source_tree: Path) -> None:
    runner = FakeRunner()
    script.execute(
        script.DeploymentRequest("live", "fictional-rg", "fictional-app"),
        runner=runner,
        source_root=source_tree,
    )

    flattened = " ".join(runner.calls[0]).lower()
    for forbidden in (
        "foundry",
        "role assignment",
        "group delete",
        "webapp delete",
        "appsettings",
        "agent",
        "invoke",
        "deployment group",
    ):
        assert forbidden not in flattened


def test_non_live_success_never_implies_acceptance_or_verification(
    source_tree: Path,
) -> None:
    result = script.execute(
        script.DeploymentRequest("package"),
        runner=FakeRunner(),
        source_root=source_tree,
    )

    assert result["package_created"] is True
    assert result["deployment_accepted"] is False
    assert result["hosted_application_verified"] is False
