import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.app.services.foundry_evaluation import (
    DEFAULT_DATASET_ID,
    EvaluationValidationError,
    evaluate_dataset,
    load_candidate_fixture,
    load_evaluation_dataset,
)


OPERATION = "evaluate_foundry_baseline"
DEFAULT_DATASET_PATH = (
    PROJECT_ROOT / "evaluation" / "fictional-intake-baseline-v1.json"
)
DEFAULT_CANDIDATE_FIXTURE_PATH = (
    PROJECT_ROOT
    / "evaluation"
    / "fictional-intake-baseline-v1-candidates.json"
)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if not args.json:
        return 2

    try:
        dataset = load_evaluation_dataset(DEFAULT_DATASET_PATH)
        candidates = load_candidate_fixture(DEFAULT_CANDIDATE_FIXTURE_PATH)
        report = evaluate_dataset(dataset, candidates)
    except EvaluationValidationError as error:
        _write_json(_failure_result(error.category))
        return 2
    except Exception:
        _write_json(_failure_result("unexpected_error"))
        return 1

    _write_json(report.to_json_dict())
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate the repository-owned fictional Foundry baseline using "
            "offline deterministic scoring."
        )
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit exactly one sanitized JSON evaluation report.",
    )
    return parser.parse_args(argv)


def _failure_result(category: str) -> dict[str, object]:
    return {
        "ok": False,
        "category": category,
        "operation": OPERATION,
        "dataset_id": DEFAULT_DATASET_ID,
    }


def _write_json(payload: dict[str, object]) -> None:
    print(json.dumps(payload, separators=(",", ":"), sort_keys=True))


if __name__ == "__main__":
    raise SystemExit(main())
