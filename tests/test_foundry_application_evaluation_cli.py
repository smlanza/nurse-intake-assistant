from importlib import import_module
import inspect
import json
from pathlib import Path
import socket

import pytest

from src.app.services.foundry_application_evaluation import (
    FoundryApplicationEvaluationError,
)


def _script():
    try:
        return import_module("scripts.evaluate_foundry_application")
    except ModuleNotFoundError:
        pytest.fail("The offline application evaluation CLI is not implemented.")


class FakeReport:
    def __init__(self, selected_mode: str) -> None:
        self.selected_mode = selected_mode

    def to_json_dict(self) -> dict[str, object]:
        return {
            "category": "success",
            "cases": [{"case_id": "fictional-case"}],
            "mode_proof": self.selected_mode,
            "ok": True,
        }


def _install_runner_spy(monkeypatch: pytest.MonkeyPatch, script):
    calls: list[dict[str, object]] = []

    def fake_runner(**kwargs):
        calls.append(kwargs)
        return FakeReport(str(kwargs["mode"]))

    monkeypatch.setattr(script, "run_foundry_application_evaluation", fake_runner)
    return calls


@pytest.mark.parametrize(
    "argv",
    [
        ["--json"],
        ["--mode", "unsupported", "--json"],
        ["--mode", "", "--json"],
        ["--mode", "agent", "--mode", "structured-extraction", "--json"],
    ],
    ids=["missing", "unsupported", "blank", "multiple"],
)
def test_invalid_or_missing_mode_fails_before_runner_invocation(
    argv: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = _script()
    monkeypatch.setattr(
        script,
        "run_foundry_application_evaluation",
        lambda **kwargs: pytest.fail("invalid arguments invoked the runner"),
    )

    with pytest.raises(SystemExit) as error:
        script.main(argv)

    assert error.value.code != 0


@pytest.mark.parametrize("mode", ["structured-extraction", "agent"])
def test_valid_mode_invokes_runner_exactly_once_with_exact_selection(
    mode: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = _script()
    calls = _install_runner_spy(monkeypatch, script)

    exit_code = script.main(["--mode", mode, "--json"])

    assert exit_code == 0
    assert len(calls) == 1
    assert calls[0]["mode"] == mode
    assert calls[0]["dataset"] is not None
    assert calls[0]["settings"] is not None
    assert calls[0]["fake_client"] is not None
    assert json.loads(capsys.readouterr().out)["mode_proof"] == mode


def test_success_writes_exactly_one_json_document_and_no_extra_stdout(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = _script()
    _install_runner_spy(monkeypatch, script)

    exit_code = script.main(["--mode", "structured-extraction", "--json"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.err == ""
    assert captured.out.endswith("\n")
    assert captured.out.count("\n") == 1
    assert json.loads(captured.out) == {
        "category": "success",
        "cases": [{"case_id": "fictional-case"}],
        "mode_proof": "structured-extraction",
        "ok": True,
    }
    assert captured.out == (
        '{"cases":[{"case_id":"fictional-case"}],"category":"success",'
        '"mode_proof":"structured-extraction","ok":true}\n'
    )


@pytest.mark.parametrize("mode", ["structured-extraction", "agent"])
def test_repeated_runs_are_byte_identical_and_serialization_is_stable(
    mode: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = _script()
    _install_runner_spy(monkeypatch, script)

    first_code = script.main(["--mode", mode, "--json"])
    first_output = capsys.readouterr().out
    second_code = script.main(["--mode", mode, "--json"])
    second_output = capsys.readouterr().out

    assert first_code == second_code == 0
    assert first_output.encode("utf-8") == second_output.encode("utf-8")


def test_supported_modes_remain_distinct(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = _script()
    calls = _install_runner_spy(monkeypatch, script)

    script.main(["--mode", "structured-extraction", "--json"])
    structured = capsys.readouterr().out
    script.main(["--mode", "agent", "--json"])
    agent = capsys.readouterr().out

    assert [call["mode"] for call in calls] == ["structured-extraction", "agent"]
    assert structured != agent


@pytest.mark.parametrize(
    "failure",
    [
        RuntimeError(
            "private raw marker: fictional chest pain; prompt; model response; "
            "https://private.example; token=secret"
        ),
        FoundryApplicationEvaluationError("processing_failed"),
    ],
    ids=["unexpected", "sanitized-runner"],
)
def test_runner_failure_is_sanitized_and_exits_nonzero(
    failure: Exception,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = _script()
    calls = 0

    def failing_runner(**kwargs):
        nonlocal calls
        calls += 1
        raise failure

    monkeypatch.setattr(script, "run_foundry_application_evaluation", failing_runner)

    exit_code = script.main(["--mode", "agent", "--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert calls == 1
    assert exit_code != 0
    assert captured.err == ""
    assert payload["ok"] is False
    assert payload["operation"] == "evaluate_foundry_application"
    assert payload["mode"] == "agent"
    if isinstance(failure, FoundryApplicationEvaluationError):
        assert payload["category"] == "processing_failed"
    else:
        assert payload["category"] == "unexpected_error"
    for forbidden in (
        "private raw marker",
        "fictional chest pain",
        "prompt",
        "model response",
        "private.example",
        "token",
        "secret",
        "RuntimeError",
        "Traceback",
    ):
        assert forbidden not in captured.out


def test_serialization_failure_is_sanitized(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = _script()

    class FailingReport:
        def to_json_dict(self):
            raise RuntimeError("private serialization marker")

    monkeypatch.setattr(
        script,
        "run_foundry_application_evaluation",
        lambda **kwargs: FailingReport(),
    )

    exit_code = script.main(["--mode", "structured-extraction", "--json"])

    captured = capsys.readouterr()
    assert exit_code != 0
    assert json.loads(captured.out)["category"] == "unexpected_error"
    assert "private serialization marker" not in captured.out
    assert captured.err == ""


def test_cli_introduces_no_live_or_network_dependency(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = _script()

    def forbidden(*args, **kwargs):
        raise AssertionError("offline CLI reached a live boundary")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    _install_runner_spy(monkeypatch, script)

    assert script.main(["--mode", "agent", "--json"]) == 0
    json.loads(capsys.readouterr().out)
    source = inspect.getsource(script)
    for forbidden_source in (
        "azure.",
        "requests",
        "httpx",
        "subprocess",
        "dotenv",
        ".env",
    ):
        assert forbidden_source not in source


def test_cli_writes_no_report_artifact(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = _script()

    def forbidden_write(*args, **kwargs):
        raise AssertionError("CLI attempted to write an evaluation artifact")

    monkeypatch.setattr(Path, "write_text", forbidden_write)
    monkeypatch.setattr(Path, "write_bytes", forbidden_write)
    _install_runner_spy(monkeypatch, script)

    assert script.main(["--mode", "structured-extraction", "--json"]) == 0
    json.loads(capsys.readouterr().out)
