import argparse
import json
from pathlib import Path
import sys
from types import SimpleNamespace


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.app.services.foundry_agent_client import FoundryAgentResponse
from src.app.services.foundry_application_evaluation import (
    ApplicationEvaluationMode,
    FoundryApplicationEvaluationError,
    run_foundry_application_evaluation,
)
from src.app.services.foundry_evaluation import (
    DEFAULT_DATASET_ID,
    EvaluationCase,
    EvaluationDataset,
    EvaluationValidationError,
    load_evaluation_dataset,
)


OPERATION = "evaluate_foundry_application"
DEFAULT_DATASET_PATH = (
    PROJECT_ROOT / "evaluation" / "fictional-intake-baseline-v1.json"
)
_MALFORMED_AGENT_CASE_ID = "invalid-candidate-output"


class _OfflineDatasetClient:
    """Return deterministic application-contract responses for one dataset."""

    def __init__(self, dataset: EvaluationDataset) -> None:
        self._cases_by_intake = {
            evaluation_case.intake_text: evaluation_case
            for evaluation_case in dataset.cases
        }

    def complete_structured_extraction(
        self,
        prompt: str,
        model_deployment_name: str,
    ) -> str:
        del model_deployment_name
        evaluation_case = self._case_from_prompt(prompt)
        return json.dumps(
            _structured_response(evaluation_case),
            separators=(",", ":"),
            sort_keys=True,
        )

    async def invoke_agent(self, request: object) -> FoundryAgentResponse:
        intake_text = getattr(request, "intake_text", None)
        evaluation_case = self._cases_by_intake.get(intake_text)
        if evaluation_case is None:
            raise ValueError("Offline evaluation request did not match the dataset.")
        if evaluation_case.case_id == _MALFORMED_AGENT_CASE_ID:
            content = "offline malformed Agent response"
        else:
            content = json.dumps(
                _agent_response(evaluation_case),
                separators=(",", ":"),
                sort_keys=True,
            )
        return FoundryAgentResponse(
            content=content,
            metadata={"provider": "foundry-agent", "agentMode": "fake"},
        )

    def _case_from_prompt(self, prompt: str) -> EvaluationCase:
        matches = [
            evaluation_case
            for intake_text, evaluation_case in self._cases_by_intake.items()
            if json.dumps(intake_text, ensure_ascii=True) in prompt
        ]
        if len(matches) != 1:
            raise ValueError("Offline evaluation prompt did not match one dataset case.")
        return matches[0]


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if not args.json:
        return 2

    mode = args.mode[0]
    try:
        dataset = load_evaluation_dataset(DEFAULT_DATASET_PATH)
        report = run_foundry_application_evaluation(
            mode=mode,
            dataset=dataset,
            settings=_offline_settings(),
            fake_client=_OfflineDatasetClient(dataset),
        )
        serialized = _serialize(report.to_json_dict())
    except EvaluationValidationError as error:
        _write_json(_failure_result(error.category, mode))
        return 2
    except FoundryApplicationEvaluationError as error:
        _write_json(_failure_result(error.category, mode))
        return 2
    except Exception:
        _write_json(_failure_result("unexpected_error", mode))
        return 1

    sys.stdout.write(serialized + "\n")
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate one application-composed Foundry mode using deterministic "
            "offline provider behavior."
        )
    )
    parser.add_argument(
        "--mode",
        action="append",
        choices=[mode.value for mode in ApplicationEvaluationMode],
        required=True,
        help="Select exactly one offline application evaluation mode.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit exactly one sanitized deterministic JSON document.",
    )
    args = parser.parse_args(argv)
    if len(args.mode) != 1:
        parser.error("--mode must be supplied exactly once")
    return args


def _offline_settings() -> SimpleNamespace:
    return SimpleNamespace(
        azure_ai_foundry_project_endpoint="offline-evaluation-project",
        azure_ai_foundry_model_deployment_name="offline-evaluation-model",
    )


def _structured_response(evaluation_case: EvaluationCase) -> dict[str, object]:
    expected = evaluation_case.expected
    return {
        "patient": {
            "name": expected.structured_fields.patient_name,
            "date_of_birth": expected.structured_fields.date_of_birth,
            "callback_number": expected.structured_fields.callback_identifier,
        },
        "reason_for_calling": expected.structured_fields.reason_for_calling,
        "symptoms": list(expected.symptoms),
        "summary": f"Fictional offline summary for {evaluation_case.case_id}.",
        "urgency": expected.advisory_ai_urgency,
        "urgency_rationale": "Deterministic offline advisory result.",
        "advisory_disclaimer": "Advisory only; nurse review required.",
        "missing_fields": list(expected.missing_fields),
        "uncertain_fields": [],
    }


def _agent_response(evaluation_case: EvaluationCase) -> dict[str, object]:
    response = _structured_response(evaluation_case)
    return {
        "extraction": {
            field: response[field]
            for field in (
                "patient",
                "reason_for_calling",
                "symptoms",
                "summary",
                "missing_fields",
                "uncertain_fields",
            )
        },
        "urgency": {
            field: response[field]
            for field in (
                "urgency",
                "urgency_rationale",
                "advisory_disclaimer",
            )
        },
    }


def _failure_result(category: str, mode: str) -> dict[str, object]:
    return {
        "ok": False,
        "category": category,
        "operation": OPERATION,
        "dataset_id": DEFAULT_DATASET_ID,
        "mode": mode,
    }


def _serialize(payload: dict[str, object]) -> str:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def _write_json(payload: dict[str, object]) -> None:
    sys.stdout.write(_serialize(payload) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
