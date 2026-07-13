import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.app.services.foundry_evaluation_publisher import (
    DETERMINISTIC_EVALUATOR_CONFIG,
    EVALUATION_NAME,
    FoundryEvaluationPublisher,
    FoundryEvaluationPublishRequest,
    FoundryEvaluationScenarioMetric,
    foundry_evaluation_sdk_available,
)


DATASET_KEYS = {
    "scenario_id",
    "scenario_ok",
    "agent_output_valid",
    "fallback_used",
    "application_safe",
    "urgency_matches",
    "intake_status_matches",
    "pending_review",
    "notifications_suppressed",
    "application_state_restored",
}
EVALUATOR_NAMES = {
    "scenario_pass",
    "agent_contract_valid",
    "fallback_avoided",
    "application_safe",
    "urgency_match",
    "intake_status_match",
    "pending_review",
    "notifications_suppressed",
    "state_restored",
}


def _metric(scenario_id: str, **overrides: bool) -> FoundryEvaluationScenarioMetric:
    values = {
        "scenario_ok": True,
        "agent_output_valid": True,
        "fallback_used": False,
        "application_safe": True,
        "urgency_matches": True,
        "intake_status_matches": True,
        "pending_review": True,
        "notifications_suppressed": True,
        "application_state_restored": True,
    }
    values.update(overrides)
    return FoundryEvaluationScenarioMetric(scenario_id=scenario_id, **values)


def _request(*metrics: FoundryEvaluationScenarioMetric) -> FoundryEvaluationPublishRequest:
    return FoundryEvaluationPublishRequest(
        subscription_id="secret-subscription-id",
        resource_group_name="secret-resource-group",
        project_name="secret-project-name",
        evaluation_name=EVALUATION_NAME,
        scenarios=metrics,
    )


def test_sdk_availability_check_is_import_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.app.services.foundry_evaluation_publisher as publisher_module

    calls: list[str] = []

    def find_spec(name: str) -> object:
        calls.append(name)
        return SimpleNamespace()

    monkeypatch.setattr(publisher_module.importlib.util, "find_spec", find_spec)

    assert foundry_evaluation_sdk_available() is True
    assert calls == ["azure.ai.evaluation"]


def test_publish_uses_exact_sanitized_dataset_and_deterministic_evaluators(
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    def evaluate(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        data_path = Path(str(kwargs["data"]))
        output_path = Path(str(kwargs["output_path"]))
        captured["dataset_rows"] = [
            json.loads(line) for line in data_path.read_text().splitlines()
        ]
        output_path.write_text('{"secret_sdk_result":"not returned"}')
        return {"metrics": {"scenario_pass.mean": 0.5}}

    publisher = FoundryEvaluationPublisher(
        evaluate_fn=evaluate,
        temporary_directory_factory=lambda: tmp_path / "evaluation-artifacts",
    )
    result = publisher.publish(
        _request(
            _metric("first"),
            _metric("second", scenario_ok=False, fallback_used=True),
        )
    )

    assert result.ok is True
    assert result.category == "success"
    assert result.foundry_tracking_requested is True
    assert result.publication_attempted is True
    assert result.scenario_count == 2
    assert result.metric_count == 18
    assert result.temporary_artifacts_removed is True
    assert captured["azure_ai_project"] == {
        "subscription_id": "secret-subscription-id",
        "resource_group_name": "secret-resource-group",
        "project_name": "secret-project-name",
    }
    assert captured["evaluation_name"] == "nurse-intake-fixed-corpus-v1"
    assert set(captured) >= {
        "data",
        "dataset_rows",
        "evaluators",
        "evaluator_config",
        "azure_ai_project",
        "evaluation_name",
        "output_path",
    }
    assert "model_config" not in captured
    assert "logging_enable" not in captured
    assert "target" not in captured
    assert captured["evaluator_config"] == DETERMINISTIC_EVALUATOR_CONFIG
    captured_text = repr(captured)
    assert "secret.example" not in captured_text
    assert "secret-agent" not in captured_text
    assert "secret-agent-version" not in captured_text
    assert "secret-model-deployment" not in captured_text
    rows = captured["dataset_rows"]
    assert [row["scenario_id"] for row in rows] == ["first", "second"]
    assert all(set(row) == DATASET_KEYS for row in rows)
    assert all(isinstance(value, bool) for row in rows for key, value in row.items() if key != "scenario_id")
    assert "secret_sdk_result" not in repr(result)
    evaluators = captured["evaluators"]
    assert set(evaluators) == EVALUATOR_NAMES
    first_row = rows[0]
    second_row = rows[1]
    assert all(
        evaluator(**first_row) == {"value": 1}
        for evaluator in evaluators.values()
    )
    assert evaluators["scenario_pass"](**second_row) == {"value": 0}
    assert evaluators["fallback_avoided"](**second_row) == {"value": 0}
    assert not Path(str(captured["data"])).exists()
    assert not Path(str(captured["output_path"])).exists()
    assert not (tmp_path / "evaluation-artifacts").exists()


@pytest.mark.parametrize(
    ("evaluate_result", "expected_category"),
    [
        (None, "response_contract_invalid"),
        ("https://secret.example/result", "response_contract_invalid"),
        ({"unexpected": "Bearer secret"}, "response_contract_invalid"),
    ],
)
def test_malformed_sdk_result_is_sanitized_and_artifacts_are_removed(
    evaluate_result: object,
    expected_category: str,
    tmp_path: Path,
) -> None:
    artifacts: list[Path] = []

    def evaluate(**kwargs: object) -> object:
        artifacts.extend([Path(str(kwargs["data"])), Path(str(kwargs["output_path"]))])
        return evaluate_result

    result = FoundryEvaluationPublisher(
        evaluate_fn=evaluate,
        temporary_directory_factory=lambda: tmp_path / "malformed-artifacts",
    ).publish(_request(_metric("only")))

    assert result.ok is False
    assert result.category == expected_category
    assert result.publication_attempted is True
    assert result.temporary_artifacts_removed is True
    assert all(not path.exists() for path in artifacts)
    assert "secret" not in repr(result)
    assert "http" not in repr(result)


def test_sdk_exception_is_sanitized_and_artifacts_are_removed(tmp_path: Path) -> None:
    def explode(**kwargs: object) -> object:
        raise RuntimeError(
            "Bearer publication-secret raw prompt https://secret.example Traceback"
        )

    result = FoundryEvaluationPublisher(
        evaluate_fn=explode,
        temporary_directory_factory=lambda: tmp_path / "exception-artifacts",
    ).publish(_request(_metric("only")))

    assert result.ok is False
    assert result.category == "publication_failed"
    assert result.publication_attempted is True
    assert result.temporary_artifacts_removed is True
    assert "secret" not in repr(result)
    assert "Traceback" not in repr(result)


def test_cleanup_failure_is_reported_without_returning_paths(tmp_path: Path) -> None:
    artifact_directory = tmp_path / "cleanup-failure"

    def fail_cleanup(path: Path) -> None:
        raise OSError(f"secret path: {path}")

    result = FoundryEvaluationPublisher(
        evaluate_fn=lambda **kwargs: {"metrics": {}},
        temporary_directory_factory=lambda: artifact_directory,
        cleanup_directory=fail_cleanup,
    ).publish(_request(_metric("only")))

    assert result.ok is False
    assert result.category == "temporary_artifact_cleanup_failed"
    assert result.temporary_artifacts_removed is False
    assert str(tmp_path) not in repr(result)


def test_empty_request_is_rejected_before_sdk_call() -> None:
    result = FoundryEvaluationPublisher(
        evaluate_fn=lambda **kwargs: pytest.fail("invalid request must not publish")
    ).publish(_request())

    assert result.ok is False
    assert result.category == "response_contract_invalid"
    assert result.publication_attempted is False
