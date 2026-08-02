import os
from pathlib import Path
import shutil
import subprocess

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
WRAPPER = REPOSITORY_ROOT / "scripts" / "daily_azure.sh"


def _write_fake_python(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "#!/usr/bin/env bash\n"
        "set -u\n"
        'printf "%s\\n" "$*" >> "${FAKE_PYTHON_LOG}"\n'
        'if [[ "${1:-}" == "-m" && "${2:-}" == "json.tool" ]]; then\n'
        "  cat\n"
        '  exit "${FAKE_JSON_TOOL_STATUS:-0}"\n'
        "fi\n"
        'printf "{}\\n"\n'
        'exit "${FAKE_COMMAND_STATUS:-0}"\n'
    )
    path.chmod(0o755)


@pytest.fixture
def wrapper_repository(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = tmp_path / "repository"
    script = root / "scripts" / "daily_azure.sh"
    script.parent.mkdir(parents=True)
    shutil.copy2(WRAPPER, script)
    fake_python = root / ".venv" / "bin" / "python"
    _write_fake_python(fake_python)
    config = root / ".env.daily-azure.local"
    config.write_text("fictional test configuration\n")
    return root, script, config


def _run(
    script: Path,
    arguments: list[str],
    *,
    log: Path,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    working_directory = script.parent.parent / "unrelated-working-directory"
    working_directory.mkdir(exist_ok=True)
    return subprocess.run(
        [str(script), *arguments],
        cwd=working_directory,
        env={
            **os.environ,
            "FAKE_PYTHON_LOG": str(log),
            **(environment or {}),
        },
        text=True,
        capture_output=True,
        check=False,
    )


def _calls(log: Path) -> list[str]:
    return log.read_text().splitlines() if log.is_file() else []


def _command_calls(log: Path) -> list[str]:
    return [call for call in _calls(log) if call != "-m json.tool"]


def _assert_json_pipeline_count(log: Path, expected: int) -> None:
    assert _calls(log).count("-m json.tool") == expected


def test_wrapper_exists_is_executable_and_has_strict_shell_preamble() -> None:
    assert WRAPPER.is_file()
    assert os.access(WRAPPER, os.X_OK)
    assert WRAPPER.read_text().splitlines()[:2] == [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
    ]


def test_start_invokes_only_live_rebuild_with_startup_preflight_message(
    wrapper_repository: tuple[Path, Path, Path],
    tmp_path: Path,
) -> None:
    _root, script, config = wrapper_repository
    log = tmp_path / "calls.log"

    result = _run(script, ["start", "--config", str(config)], log=log)

    assert result.returncode == 0
    assert "authoritative startup cleanup preflight" in result.stderr
    assert _command_calls(log) == [
        (
            "scripts/rebuild_daily_azure_environment.py "
            f"--config {config} --live --json"
        ),
    ]
    _assert_json_pipeline_count(log, 1)
    assert "cleanup_daily_azure_environment.py" not in "\n".join(_calls(log))


def test_inspect_is_read_only_cleanup_inspection(
    wrapper_repository: tuple[Path, Path, Path],
    tmp_path: Path,
) -> None:
    _root, script, config = wrapper_repository
    log = tmp_path / "calls.log"

    result = _run(script, ["inspect", "--config", str(config)], log=log)

    assert result.returncode == 0
    assert "read-only" in result.stderr
    assert _command_calls(log) == [
        (
            "scripts/cleanup_daily_azure_environment.py "
            f"--config {config} --inspect --live --json"
        ),
    ]
    _assert_json_pipeline_count(log, 1)


def test_stop_uses_default_no_destructive_cleanup_without_bypass(
    wrapper_repository: tuple[Path, Path, Path],
    tmp_path: Path,
) -> None:
    _root, script, config = wrapper_repository
    log = tmp_path / "calls.log"

    result = _run(script, ["stop", "--config", str(config)], log=log)

    assert result.returncode == 0
    assert "default-no" in result.stderr
    assert "destructive end-of-day cleanup" in result.stderr
    assert _command_calls(log) == [
        (
            "scripts/cleanup_daily_azure_environment.py "
            f"--config {config} --cleanup --live --json"
        ),
    ]
    _assert_json_pipeline_count(log, 1)
    source = WRAPPER.read_text()
    assert "SpeechServices" not in source
    assert "nurse-intake-speech" not in source


def test_check_runs_cleanup_then_rebuild_offline_contracts(
    wrapper_repository: tuple[Path, Path, Path],
    tmp_path: Path,
) -> None:
    _root, script, config = wrapper_repository
    log = tmp_path / "calls.log"

    result = _run(script, ["check", "--config", str(config)], log=log)

    assert result.returncode == 0
    assert "offline" in result.stderr
    assert _command_calls(log) == [
        (
            "scripts/cleanup_daily_azure_environment.py "
            f"--config {config} --check --json"
        ),
        (
            "scripts/rebuild_daily_azure_environment.py "
            f"--config {config} --check --json"
        ),
    ]
    _assert_json_pipeline_count(log, 2)


def test_default_config_is_resolved_after_changing_to_repository_root(
    wrapper_repository: tuple[Path, Path, Path],
    tmp_path: Path,
) -> None:
    _root, script, _config = wrapper_repository
    log = tmp_path / "calls.log"

    result = _run(script, ["inspect"], log=log)

    assert result.returncode == 0
    assert "--config .env.daily-azure.local" in _command_calls(log)[0]


def test_python_bin_environment_override_is_used(
    wrapper_repository: tuple[Path, Path, Path],
    tmp_path: Path,
) -> None:
    _root, script, config = wrapper_repository
    override = tmp_path / "override-python"
    _write_fake_python(override)
    log = tmp_path / "calls.log"

    result = _run(
        script,
        ["inspect", "--config", str(config)],
        log=log,
        environment={"PYTHON_BIN": str(override)},
    )

    assert result.returncode == 0
    assert len(_calls(log)) == 2


@pytest.mark.parametrize(
    "arguments",
    [
        ["unknown"],
        ["start", "--unknown"],
        ["start", "--config"],
        ["start", "--config", "one", "extra"],
    ],
)
def test_unknown_or_incomplete_arguments_fail_without_python(
    wrapper_repository: tuple[Path, Path, Path],
    tmp_path: Path,
    arguments: list[str],
) -> None:
    _root, script, _config = wrapper_repository
    log = tmp_path / "calls.log"

    result = _run(script, arguments, log=log)

    assert result.returncode != 0
    assert _calls(log) == []
    assert result.stderr


def test_missing_configuration_fails_without_python(
    wrapper_repository: tuple[Path, Path, Path],
    tmp_path: Path,
) -> None:
    _root, script, _config = wrapper_repository
    missing = tmp_path / "missing.env"
    log = tmp_path / "calls.log"

    result = _run(script, ["start", "--config", str(missing)], log=log)

    assert result.returncode != 0
    assert "Configuration file is unavailable" in result.stderr
    assert _calls(log) == []


def test_missing_python_interpreter_fails_clearly(
    wrapper_repository: tuple[Path, Path, Path],
    tmp_path: Path,
) -> None:
    _root, script, config = wrapper_repository
    log = tmp_path / "calls.log"

    result = _run(
        script,
        ["start", "--config", str(config)],
        log=log,
        environment={"PYTHON_BIN": str(tmp_path / "missing-python")},
    )

    assert result.returncode != 0
    assert "Python interpreter is unavailable" in result.stderr
    assert _calls(log) == []


@pytest.mark.parametrize(
    ("environment", "expected_status"),
    [
        ({"FAKE_COMMAND_STATUS": "7"}, 7),
        ({"FAKE_JSON_TOOL_STATUS": "9"}, 9),
    ],
)
def test_pipeline_failures_propagate(
    wrapper_repository: tuple[Path, Path, Path],
    tmp_path: Path,
    environment: dict[str, str],
    expected_status: int,
) -> None:
    _root, script, config = wrapper_repository
    log = tmp_path / "calls.log"

    result = _run(
        script,
        ["inspect", "--config", str(config)],
        log=log,
        environment=environment,
    )

    assert result.returncode == expected_status


@pytest.mark.parametrize("command", ["start", "inspect", "stop", "check"])
def test_commands_never_add_unattended_or_sensitive_arguments(
    wrapper_repository: tuple[Path, Path, Path],
    tmp_path: Path,
    command: str,
) -> None:
    _root, script, config = wrapper_repository
    log = tmp_path / f"{command}.log"

    result = _run(script, [command, "--config", str(config)], log=log)

    assert result.returncode == 0
    rendered = " ".join(_calls(log)).casefold()
    for forbidden in (
        "--yes",
        "--force",
        "credential",
        "token",
        "endpoint",
        "subscription",
        "resourcegroups/",
    ):
        assert forbidden not in rendered


@pytest.mark.parametrize(
    "arguments",
    [["--help"], ["start", "--help"]],
)
def test_help_is_clear_and_needs_no_python_or_config(
    wrapper_repository: tuple[Path, Path, Path],
    tmp_path: Path,
    arguments: list[str],
) -> None:
    _root, script, _config = wrapper_repository
    log = tmp_path / "calls.log"

    result = _run(
        script,
        arguments,
        log=log,
        environment={"PYTHON_BIN": str(tmp_path / "missing-python")},
    )

    assert result.returncode == 0
    assert "scripts/daily_azure.sh start [--config FILE]" in result.stdout
    assert "scripts/daily_azure.sh inspect [--config FILE]" in result.stdout
    assert "scripts/daily_azure.sh stop [--config FILE]" in result.stdout
    assert "scripts/daily_azure.sh check [--config FILE]" in result.stdout
    assert _calls(log) == []
