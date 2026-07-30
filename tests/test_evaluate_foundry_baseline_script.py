from importlib import import_module
import inspect
import json
from pathlib import Path
import socket

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _script():
    try:
        return import_module("scripts.evaluate_foundry_baseline")
    except ModuleNotFoundError:
        pytest.fail("The offline Foundry baseline CLI is not implemented.")


def test_json_success_emits_one_parseable_document(
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = _script()

    exit_code = script.main(["--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert captured.err == ""
    assert payload["ok"] is True
    assert payload["category"] == "success"
    assert payload["operation"] == "evaluate_foundry_baseline"
    assert payload["dataset_id"] == "evaluation/fictional-intake-baseline-v1.json"


def test_default_paths_are_repository_owned_and_stable() -> None:
    script = _script()

    assert script.DEFAULT_DATASET_PATH == (
        PROJECT_ROOT / "evaluation" / "fictional-intake-baseline-v1.json"
    )
    assert script.DEFAULT_CANDIDATE_FIXTURE_PATH == (
        PROJECT_ROOT
        / "evaluation"
        / "fictional-intake-baseline-v1-candidates.json"
    )
    assert script.DEFAULT_DATASET_PATH.is_relative_to(PROJECT_ROOT)
    assert script.DEFAULT_CANDIDATE_FIXTURE_PATH.is_relative_to(PROJECT_ROOT)


def test_default_fixture_has_intentional_errors_and_nonperfect_metrics(
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = _script()
    candidates = script.load_candidate_fixture(
        script.DEFAULT_CANDIDATE_FIXTURE_PATH
    )

    exit_code = script.main(["--json"])

    payload = json.loads(capsys.readouterr().out)
    metrics = payload["metrics"]
    assert exit_code == 0
    assert any(
        not candidate.get("contract_valid", False)
        for candidate in candidates.values()
    )
    assert metrics["candidate_contract_valid_rate"] < 1.0
    assert metrics["symptom_f1"] < 1.0
    assert metrics["final_urgency_accuracy"] < 1.0


def test_default_invalid_candidate_uses_safe_unknown_urgency() -> None:
    script = _script()
    candidates = script.load_candidate_fixture(
        script.DEFAULT_CANDIDATE_FIXTURE_PATH
    )
    invalid_candidates = [
        candidate
        for candidate in candidates.values()
        if candidate["contract_valid"] is False
    ]

    assert len(invalid_candidates) == 1
    invalid_candidate = invalid_candidates[0]
    assert invalid_candidate["advisory_ai_urgency"] == "Unknown"
    assert invalid_candidate["final_application_urgency"] == "Unknown"
    assert invalid_candidate["deterministic_rule_result"] == "Routine"
    assert invalid_candidate["nurse_review_required"] is True


def test_repeated_unchanged_runs_emit_equivalent_json(
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = _script()

    first_code = script.main(["--json"])
    first = json.loads(capsys.readouterr().out)
    second_code = script.main(["--json"])
    second = json.loads(capsys.readouterr().out)

    assert first_code == second_code == 0
    assert first == second


def test_dataset_validation_failure_is_sanitized_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = _script()
    private_path = tmp_path / "private-dataset-marker.json"
    monkeypatch.setattr(script, "DEFAULT_DATASET_PATH", private_path)

    exit_code = script.main(["--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code != 0
    assert captured.err == ""
    assert payload == {
        "category": "missing_dataset",
        "dataset_id": "evaluation/fictional-intake-baseline-v1.json",
        "ok": False,
        "operation": "evaluate_foundry_baseline",
    }
    assert str(private_path) not in captured.out
    assert "Traceback" not in captured.out
    assert "FileNotFoundError" not in captured.out


def test_unexpected_failure_does_not_echo_raw_exception(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = _script()
    monkeypatch.setattr(
        script,
        "load_evaluation_dataset",
        lambda path: (_ for _ in ()).throw(
            RuntimeError("private-exception-marker")
        ),
    )

    exit_code = script.main(["--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 1
    assert captured.err == ""
    assert payload["category"] == "unexpected_error"
    assert "private-exception-marker" not in captured.out
    assert "RuntimeError" not in captured.out
    assert "Traceback" not in captured.out


def test_cli_is_offline_and_has_no_side_effect_boundaries(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = _script()
    from azure import identity
    from src.app.services.case_repository import InMemoryCaseRepository
    from src.app.services.email_notification_sender import MockEmailNotificationSender
    from src.app.services.sms_notification_sender import MockSmsNotificationSender

    def forbidden(*args, **kwargs):
        raise AssertionError("offline CLI attempted a forbidden side effect")

    monkeypatch.setattr(identity, "DefaultAzureCredential", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(InMemoryCaseRepository, "save", forbidden)
    monkeypatch.setattr(MockEmailNotificationSender, "send_case_notification", forbidden)
    monkeypatch.setattr(MockSmsNotificationSender, "send_case_notification", forbidden)

    exit_code = script.main(["--json"])

    assert exit_code == 0
    json.loads(capsys.readouterr().out)
    source = inspect.getsource(script)
    assert "azure." not in source
    assert "httpx" not in source
    assert "requests" not in source
