"""Publish sanitized deterministic metrics to Foundry evaluation tracking."""

import importlib.util
import json
import shutil
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path


EVALUATION_NAME = "nurse-intake-fixed-corpus-v1"
METRICS_PER_SCENARIO = 9


@dataclass(frozen=True)
class FoundryEvaluationScenarioMetric:
    scenario_id: str
    scenario_ok: bool
    agent_output_valid: bool
    fallback_used: bool
    application_safe: bool
    urgency_matches: bool
    intake_status_matches: bool
    pending_review: bool
    notifications_suppressed: bool
    application_state_restored: bool


@dataclass(frozen=True)
class FoundryEvaluationPublishRequest:
    subscription_id: str
    resource_group_name: str
    project_name: str
    evaluation_name: str
    scenarios: tuple[FoundryEvaluationScenarioMetric, ...]


@dataclass(frozen=True)
class FoundryEvaluationPublishResult:
    ok: bool
    category: str
    foundry_tracking_requested: bool
    publication_attempted: bool
    scenario_count: int
    metric_count: int
    temporary_artifacts_removed: bool

    @classmethod
    def success(cls, scenario_count: int) -> "FoundryEvaluationPublishResult":
        return cls(
            ok=True,
            category="success",
            foundry_tracking_requested=True,
            publication_attempted=True,
            scenario_count=scenario_count,
            metric_count=scenario_count * METRICS_PER_SCENARIO,
            temporary_artifacts_removed=True,
        )

    @classmethod
    def failure(
        cls,
        category: str,
        *,
        publication_attempted: bool,
        scenario_count: int = 0,
        temporary_artifacts_removed: bool = True,
    ) -> "FoundryEvaluationPublishResult":
        return cls(
            ok=False,
            category=category,
            foundry_tracking_requested=True,
            publication_attempted=publication_attempted,
            scenario_count=scenario_count,
            metric_count=(
                scenario_count * METRICS_PER_SCENARIO
                if publication_attempted
                else 0
            ),
            temporary_artifacts_removed=temporary_artifacts_removed,
        )

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)


def foundry_evaluation_sdk_available() -> bool:
    """Return SDK visibility without constructing a client or calling Azure."""
    try:
        return importlib.util.find_spec("azure.ai.evaluation") is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def scenario_pass(*, scenario_ok: bool, **_: object) -> dict[str, int]:
    return {"value": int(scenario_ok)}


def agent_contract_valid(
    *, agent_output_valid: bool, **_: object
) -> dict[str, int]:
    return {"value": int(agent_output_valid)}


def fallback_avoided(*, fallback_used: bool, **_: object) -> dict[str, int]:
    return {"value": int(not fallback_used)}


def application_safe(*, application_safe: bool, **_: object) -> dict[str, int]:
    return {"value": int(application_safe)}


def urgency_match(*, urgency_matches: bool, **_: object) -> dict[str, int]:
    return {"value": int(urgency_matches)}


def intake_status_match(
    *, intake_status_matches: bool, **_: object
) -> dict[str, int]:
    return {"value": int(intake_status_matches)}


def pending_review(*, pending_review: bool, **_: object) -> dict[str, int]:
    return {"value": int(pending_review)}


def notifications_suppressed(
    *, notifications_suppressed: bool, **_: object
) -> dict[str, int]:
    return {"value": int(notifications_suppressed)}


def state_restored(
    *, application_state_restored: bool, **_: object
) -> dict[str, int]:
    return {"value": int(application_state_restored)}


DETERMINISTIC_EVALUATORS: dict[str, Callable[..., dict[str, int]]] = {
    "scenario_pass": scenario_pass,
    "agent_contract_valid": agent_contract_valid,
    "fallback_avoided": fallback_avoided,
    "application_safe": application_safe,
    "urgency_match": urgency_match,
    "intake_status_match": intake_status_match,
    "pending_review": pending_review,
    "notifications_suppressed": notifications_suppressed,
    "state_restored": state_restored,
}
DETERMINISTIC_EVALUATOR_CONFIG = {
    "scenario_pass": {
        "column_mapping": {"scenario_ok": "${data.scenario_ok}"}
    },
    "agent_contract_valid": {
        "column_mapping": {
            "agent_output_valid": "${data.agent_output_valid}"
        }
    },
    "fallback_avoided": {
        "column_mapping": {"fallback_used": "${data.fallback_used}"}
    },
    "application_safe": {
        "column_mapping": {"application_safe": "${data.application_safe}"}
    },
    "urgency_match": {
        "column_mapping": {"urgency_matches": "${data.urgency_matches}"}
    },
    "intake_status_match": {
        "column_mapping": {
            "intake_status_matches": "${data.intake_status_matches}"
        }
    },
    "pending_review": {
        "column_mapping": {"pending_review": "${data.pending_review}"}
    },
    "notifications_suppressed": {
        "column_mapping": {
            "notifications_suppressed": "${data.notifications_suppressed}"
        }
    },
    "state_restored": {
        "column_mapping": {
            "application_state_restored": "${data.application_state_restored}"
        }
    },
}


class FoundryEvaluationPublisher:
    """Small injectable adapter around ``azure.ai.evaluation.evaluate``."""

    def __init__(
        self,
        *,
        evaluate_fn: Callable[..., object] | None = None,
        temporary_directory_factory: Callable[[], Path] | None = None,
        cleanup_directory: Callable[[Path], None] | None = None,
    ) -> None:
        self._evaluate_fn = evaluate_fn
        self._temporary_directory_factory = (
            temporary_directory_factory or _create_temporary_directory
        )
        self._cleanup_directory = cleanup_directory or _cleanup_directory

    def publish(
        self,
        request: FoundryEvaluationPublishRequest,
    ) -> FoundryEvaluationPublishResult:
        if not _request_is_valid(request):
            return FoundryEvaluationPublishResult.failure(
                "response_contract_invalid",
                publication_attempted=False,
            )

        evaluate_fn = self._evaluate_fn
        if evaluate_fn is None:
            try:
                from azure.ai.evaluation import evaluate as sdk_evaluate
            except Exception:
                return FoundryEvaluationPublishResult.failure(
                    "evaluation_sdk_unavailable",
                    publication_attempted=False,
                )
            evaluate_fn = sdk_evaluate

        scenario_count = len(request.scenarios)
        publication_attempted = False
        category = "publication_failed"
        publish_ok = False
        temporary_artifacts_removed = True
        temporary_directory: Path | None = None
        try:
            temporary_directory = self._temporary_directory_factory()
            temporary_directory.mkdir(parents=True, exist_ok=True)
            dataset_path = temporary_directory / "sanitized-metrics.jsonl"
            output_path = temporary_directory / "evaluation-result.json"
            _write_dataset(dataset_path, request.scenarios)
            publication_attempted = True
            candidate = evaluate_fn(
                data=str(dataset_path),
                evaluators=DETERMINISTIC_EVALUATORS,
                evaluator_config=DETERMINISTIC_EVALUATOR_CONFIG,
                azure_ai_project={
                    "subscription_id": request.subscription_id,
                    "resource_group_name": request.resource_group_name,
                    "project_name": request.project_name,
                },
                evaluation_name=request.evaluation_name,
                output_path=str(output_path),
            )
            if _sdk_result_is_valid(candidate):
                category = "success"
                publish_ok = True
            else:
                category = "response_contract_invalid"
        except Exception:
            category = "publication_failed"
            publish_ok = False
        finally:
            if temporary_directory is not None:
                try:
                    self._cleanup_directory(temporary_directory)
                except Exception:
                    pass
                temporary_artifacts_removed = not temporary_directory.exists()

        if not temporary_artifacts_removed:
            category = "temporary_artifact_cleanup_failed"
            publish_ok = False
        if publish_ok:
            return FoundryEvaluationPublishResult.success(scenario_count)
        return FoundryEvaluationPublishResult.failure(
            category,
            publication_attempted=publication_attempted,
            scenario_count=scenario_count,
            temporary_artifacts_removed=temporary_artifacts_removed,
        )


def _request_is_valid(request: object) -> bool:
    if not isinstance(request, FoundryEvaluationPublishRequest):
        return False
    if (
        not isinstance(request.subscription_id, str)
        or not request.subscription_id.strip()
        or not isinstance(request.resource_group_name, str)
        or not request.resource_group_name.strip()
        or not isinstance(request.project_name, str)
        or not request.project_name.strip()
        or request.evaluation_name != EVALUATION_NAME
        or not isinstance(request.scenarios, tuple)
        or not request.scenarios
    ):
        return False
    for metric in request.scenarios:
        if not isinstance(metric, FoundryEvaluationScenarioMetric):
            return False
        values = asdict(metric)
        if not isinstance(metric.scenario_id, str) or not metric.scenario_id:
            return False
        if any(
            not isinstance(value, bool)
            for key, value in values.items()
            if key != "scenario_id"
        ):
            return False
    return True


def _write_dataset(
    path: Path,
    scenarios: tuple[FoundryEvaluationScenarioMetric, ...],
) -> None:
    with path.open("w", encoding="utf-8") as stream:
        for scenario in scenarios:
            stream.write(json.dumps(asdict(scenario), separators=(",", ":")))
            stream.write("\n")


def _sdk_result_is_valid(candidate: object) -> bool:
    return (
        isinstance(candidate, Mapping)
        and "metrics" in candidate
        and isinstance(candidate["metrics"], Mapping)
    )


def _create_temporary_directory() -> Path:
    return Path(tempfile.mkdtemp(prefix="nurse-intake-foundry-evaluation-"))


def _cleanup_directory(path: Path) -> None:
    shutil.rmtree(path)
