import importlib
import io
import json
from pathlib import Path


import pytest


@pytest.mark.parametrize("answer", ["", "\n", "n\n", "maybe\n", None])
def test_archive_defaults_no_on_eof_empty_or_explicit_decline(
    monkeypatch, capsys, tmp_path: Path, answer: object
) -> None:
    script = importlib.import_module(
        "scripts.recover_hosted_foundry_agent_webjob_state"
    )
    called: list[bool] = []
    monkeypatch.setattr(script.sys.stdin, "readline", lambda: answer)
    monkeypatch.setattr(
        script,
        "recover_hosted_webjob_state",
        lambda *_args, **_kwargs: called.append(True),
    )

    code = script.main(
        [
            "--archive",
            "--source-root",
            str(tmp_path),
            "--manifest-digest",
            "a" * 64,
            "--reason",
            "stale_environment_evidence",
            "--json",
        ]
    )

    output = json.loads(capsys.readouterr().out)
    assert code != 0
    assert output["category"] == "approval_required"
    assert called == []


def test_recovery_cli_has_no_force_or_coordinator_skip_mode(tmp_path: Path) -> None:
    script = importlib.import_module(
        "scripts.recover_hosted_foundry_agent_webjob_state"
    )

    with pytest.raises(SystemExit):
        script.main(
            [
                "--inspect",
                "--source-root",
                str(tmp_path),
                "--force",
                "--json",
            ]
        )


@pytest.mark.parametrize("failure", [OSError("raw secret"), ValueError("raw secret")])
def test_archive_defaults_no_when_stdin_read_raises(
    monkeypatch, capsys, tmp_path: Path, failure: Exception
) -> None:
    script = importlib.import_module(
        "scripts.recover_hosted_foundry_agent_webjob_state"
    )
    called: list[bool] = []
    monkeypatch.setattr(
        script.sys.stdin,
        "readline",
        lambda: (_ for _ in ()).throw(failure),
    )
    monkeypatch.setattr(
        script,
        "recover_hosted_webjob_state",
        lambda *_args, **_kwargs: called.append(True),
    )

    code = script.main(
        [
            "--archive",
            "--source-root",
            str(tmp_path),
            "--manifest-digest",
            "a" * 64,
            "--reason",
            "stale_environment_evidence",
            "--json",
        ]
    )

    captured = capsys.readouterr()
    assert code != 0
    assert json.loads(captured.out)["category"] == "approval_required"
    assert "raw secret" not in captured.out + captured.err
    assert called == []


def test_archive_defaults_no_when_stdin_is_closed(
    monkeypatch, capsys, tmp_path: Path
) -> None:
    script = importlib.import_module(
        "scripts.recover_hosted_foundry_agent_webjob_state"
    )
    closed = io.StringIO()
    closed.close()
    called: list[bool] = []
    monkeypatch.setattr(script.sys, "stdin", closed)
    monkeypatch.setattr(
        script,
        "recover_hosted_webjob_state",
        lambda *_args, **_kwargs: called.append(True),
    )

    code = script.main(
        [
            "--archive",
            "--source-root",
            str(tmp_path),
            "--manifest-digest",
            "a" * 64,
            "--reason",
            "stale_environment_evidence",
            "--json",
        ]
    )

    captured = capsys.readouterr()
    assert code != 0
    assert json.loads(captured.out)["category"] == "approval_required"
    assert called == []


@pytest.mark.parametrize("target", ["inside", "outside", "parent"])
def test_cli_rejects_symlinked_caller_source_root(
    monkeypatch, capsys, tmp_path: Path, target: str
) -> None:
    script = importlib.import_module(
        "scripts.recover_hosted_foundry_agent_webjob_state"
    )
    real_root = tmp_path / "real-root"
    real_root.mkdir()
    if target == "parent":
        real_parent = tmp_path / "real-parent"
        source = tmp_path / "linked-parent" / "source"
        (real_parent / "source").mkdir(parents=True)
        source.parent.symlink_to(real_parent, target_is_directory=True)
    else:
        destination = real_root if target == "inside" else tmp_path.parent
        source = tmp_path / f"{target}-source-link"
        source.symlink_to(destination, target_is_directory=True)
    observed: list[Path] = []
    original = script.inspect_hosted_webjob_state

    def inspect(request):
        observed.append(request.source_root)
        return original(request)

    monkeypatch.setattr(script, "inspect_hosted_webjob_state", inspect)
    code = script.main(
        ["--inspect", "--source-root", str(source), "--json"]
    )

    payload = json.loads(capsys.readouterr().out)
    assert code != 0
    assert payload["category"] == "unsafe_path"
    assert observed == [source]
