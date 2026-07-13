"""Run a sanitized fixed-corpus Foundry Agent application evaluation."""

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from src.app.config.settings import AppSettings
from src.app.services.foundry_agent_verification import (
    FoundryAgentVerification,
    FoundryAgentVerificationResult,
    build_foundry_agent_verification_request,
    foundry_agent_verification_sdk_available,
)
from src.app.services.nurse_intake_agent_factory import create_nurse_intake_agent

from scripts.smoke_foundry_agent_intake import (
    ApplicationIntakeScenarioExecution,
    build_foundry_agent_intake_readiness,
    run_foundry_agent_intake_scenario,
)
import scripts.smoke_foundry_agent_intake as application_smoke


CORPUS_PATH = (
    PROJECT_ROOT
    / "scripts"
    / "data"
    / "foundry_agent_intake_evaluation_cases.json"
)
SAFE_OUTPUT_FIELDS = ["extraction", "urgency", "handoffNote"]
LIVE_SUCCESS_NEXT_STEP = (
    "Review only the sanitized aggregate result, restore AGENT_PROVIDER=mock, "
    "and clean up disposable resources manually."
)
LIVE_FAILURE_NEXT_STEP = (
    "Review the sanitized failed scenario categories before any manual retry."
)
VERIFICATION_FAILURE_NEXT_STEP = (
    "Resolve the sanitized verification category before running evaluation."
)
CHECK_SUCCESS_NEXT_STEP = (
    "Run the explicit guarded live evaluation only after operator review."
)
CHECK_FAILURE_NEXT_STEP = (
    "Add the missing setting names or restore the required safe mock posture."
)


class EvaluationCorpusError(ValueError):
    """Raised when the committed fictional corpus is malformed."""


@dataclass(frozen=True)
class EvaluationScenario:
    id: str
    intake_text: str
    expected_urgency: Literal["Routine", "Urgent", "Unknown"]
    expected_intake_status: Literal["Complete", "NeedsFollowUp"]


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        scenarios = load_evaluation_corpus()
    except EvaluationCorpusError:
        _print_json(_invalid_corpus_payload("check" if args.check else "live"))
        return 2

    if args.env_file is not None and not _load_env_file(args.env_file):
        _print_json(_configuration_file_failure_payload(args, scenarios))
        return 2

    settings = AppSettings()
    readiness = build_foundry_agent_intake_readiness(
        settings,
        require_agent_version_verification=True,
    )
    sdk_available = foundry_agent_verification_sdk_available()

    if args.check:
        payload = _check_payload(
            scenarios,
            readiness=readiness,
            sdk_available=sdk_available,
        )
        _print_json(payload)
        return 0 if payload["ready"] else 2

    if readiness.required_settings_missing or readiness.unsafe_settings:
        category = (
            "missing_configuration"
            if readiness.required_settings_missing
            else "unsafe_application_configuration"
        )
        _print_json(
            _empty_live_payload(
                scenarios,
                category=category,
                verification=_verification_metadata(
                    category=category,
                    sdk_available=sdk_available,
                ),
                temporary_application_state_restored=True,
            )
        )
        return 2
    if not sdk_available:
        _print_json(
            _empty_live_payload(
                scenarios,
                category="sdk_unavailable",
                verification=_verification_metadata(
                    category="sdk_unavailable",
                    sdk_available=False,
                ),
                temporary_application_state_restored=True,
            )
        )
        return 2

    state_before_verification = application_smoke._capture_application_state_safely()
    try:
        candidate = _create_verification_service().verify(
            build_foundry_agent_verification_request(settings)
        )
    except Exception:
        _print_json(
            _empty_live_payload(
                scenarios,
                category="agent_verification_failed",
                verification=_verification_metadata(
                    category="agent_verification_failed",
                    azure_lookup_attempted=None,
                    sdk_available=None,
                ),
                temporary_application_state_restored=(
                    application_smoke._application_state_matches(
                        state_before_verification
                    )
                ),
            )
        )
        return 1

    if not isinstance(candidate, FoundryAgentVerificationResult):
        _print_json(
            _empty_live_payload(
                scenarios,
                category="response_contract_invalid",
                verification=_verification_metadata(
                    category="response_contract_invalid",
                    azure_lookup_attempted=None,
                    sdk_available=None,
                ),
                temporary_application_state_restored=(
                    application_smoke._application_state_matches(
                        state_before_verification
                    )
                ),
            )
        )
        return 1

    verification_result = candidate
    verification_category = application_smoke._verification_gate_category(
        verification_result.category
    )
    if not verification_result.ok:
        _print_json(
            _empty_live_payload(
                scenarios,
                category=verification_category,
                verification=_verification_metadata(
                    verification_result,
                    category=verification_category,
                ),
                temporary_application_state_restored=(
                    application_smoke._application_state_matches(
                        state_before_verification
                    )
                ),
            )
        )
        return 1

    try:
        agent = _create_live_agent(settings)
    except Exception:
        _print_json(
            _empty_live_payload(
                scenarios,
                category="unexpected_error",
                verification=_verification_metadata(verification_result),
                temporary_application_state_restored=(
                    application_smoke._application_state_matches(
                        state_before_verification
                    )
                ),
            )
        )
        return 1

    scenario_results: list[dict[str, object]] = []
    invocation_count = 0
    intake_count = 0
    for scenario in scenarios:
        try:
            execution = run_foundry_agent_intake_scenario(
                agent,
                intake_text=scenario.intake_text,
                source_system="foundry-agent-fixed-corpus-evaluation",
            )
        except Exception:
            execution = _unexpected_scenario_execution()
        invocation_count += int(execution.invocation_attempted)
        intake_count += int(execution.application_intake_attempted)
        scenario_results.append(_scenario_payload(scenario, execution))
        if not execution.temporary_application_state_restored:
            break

    passed_count = sum(bool(item["ok"]) for item in scenario_results)
    failed_count = len(scenario_results) - passed_count
    restoration_ok = all(
        bool(item["temporary_application_state_restored"])
        for item in scenario_results
    )
    notifications_suppressed = bool(scenario_results) and all(
        bool(item["notifications_suppressed"])
        for item in scenario_results
    )
    all_scenarios_ran = len(scenario_results) == len(scenarios)
    ok = all_scenarios_ran and failed_count == 0 and restoration_ok
    if not restoration_ok:
        category = "state_restoration_failed"
    elif not ok:
        category = "evaluation_failed"
    else:
        category = "success"

    _print_json(
        {
            "ok": ok,
            "mode": "live",
            "category": category,
            "verification": _verification_metadata(verification_result),
            "scenario_count": len(scenarios),
            "passed_count": passed_count,
            "failed_count": failed_count,
            "agent_client_created": True,
            "agent_invocation_count": invocation_count,
            "application_intake_count": intake_count,
            "notifications_suppressed": notifications_suppressed,
            "temporary_application_state_restored": restoration_ok,
            "scenarios": scenario_results,
            "recommended_next_step": (
                LIVE_SUCCESS_NEXT_STEP if ok else LIVE_FAILURE_NEXT_STEP
            ),
        }
    )
    return 0 if ok else 1


def load_evaluation_corpus(
    path: str | Path = CORPUS_PATH,
) -> list[EvaluationScenario]:
    corpus_path = Path(path)
    try:
        raw_records = json.loads(corpus_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvaluationCorpusError("The fictional evaluation corpus is invalid.") from exc
    if not isinstance(raw_records, list) or not raw_records:
        raise EvaluationCorpusError("The fictional evaluation corpus is invalid.")

    scenarios: list[EvaluationScenario] = []
    seen_ids: set[str] = set()
    for record in raw_records:
        if not isinstance(record, dict) or set(record) != {
            "id",
            "intakeText",
            "expectedUrgency",
            "expectedIntakeStatus",
        }:
            raise EvaluationCorpusError("The fictional evaluation corpus is invalid.")
        scenario_id = record["id"]
        intake_text = record["intakeText"]
        expected_urgency = record["expectedUrgency"]
        expected_intake_status = record["expectedIntakeStatus"]
        if (
            not isinstance(scenario_id, str)
            or re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", scenario_id) is None
            or scenario_id in seen_ids
            or not isinstance(intake_text, str)
            or not intake_text.strip()
            or "fictional" not in intake_text.casefold()
            or expected_urgency not in {"Routine", "Urgent", "Unknown"}
            or expected_intake_status not in {"Complete", "NeedsFollowUp"}
        ):
            raise EvaluationCorpusError("The fictional evaluation corpus is invalid.")
        seen_ids.add(scenario_id)
        scenarios.append(
            EvaluationScenario(
                id=scenario_id,
                intake_text=intake_text,
                expected_urgency=expected_urgency,
                expected_intake_status=expected_intake_status,
            )
        )
    return scenarios


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate a fixed fictional corpus through the verified Foundry "
            "Agent application intake pipeline."
        )
    )
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument(
        "--check",
        action="store_true",
        help="Validate the corpus and readiness without clients or intake.",
    )
    modes.add_argument(
        "--live",
        action="store_true",
        help="Run the guarded fixed fictional corpus evaluation.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print one sanitized JSON result; required with --live.",
    )
    parser.add_argument(
        "--verify-agent-version",
        action="store_true",
        help="Require exact immutable-version verification before evaluation.",
    )
    parser.add_argument(
        "--env-file",
        help="Load KEY=value settings for this process; existing environment wins.",
    )
    args = parser.parse_args(argv)
    if args.live and not args.json:
        parser.error("--live requires --json")
    if args.live and not args.verify_agent_version:
        parser.error("--live requires --verify-agent-version")
    return args


def _check_payload(
    scenarios: list[EvaluationScenario],
    *,
    readiness: Any,
    sdk_available: bool,
) -> dict[str, object]:
    sdk_ready = sdk_available is True
    ready = readiness.ready and sdk_ready
    category = (
        readiness.category
        if not readiness.ready
        else "sdk_unavailable"
        if not sdk_ready
        else "success"
    )
    required_names = [name for name, _ in application_smoke.VERIFICATION_REQUIRED_SETTINGS]
    return {
        "ok": ready,
        "ready": ready,
        "mode": "check",
        "category": category,
        "scenario_count": len(scenarios),
        "scenario_ids": [scenario.id for scenario in scenarios],
        "required_settings_present": [
            name for name in required_names if name not in readiness.required_settings_missing
        ],
        "required_settings_missing": readiness.required_settings_missing,
        "unsafe_application_settings": readiness.unsafe_settings,
        "verification": {
            "requested_in_live_mode": True,
            "azure_lookup_attempted": False,
            "configured_agent_version_matched": None,
            "category": "not_attempted",
            "sdk_available": sdk_available,
        },
        "agent_client_created": False,
        "agent_invocation_count": 0,
        "application_intake_count": 0,
        "case_saved_count": 0,
        "notifications_recorded": False,
        "temporary_application_state_restored": True,
        "recommended_next_step": (
            CHECK_SUCCESS_NEXT_STEP if ready else CHECK_FAILURE_NEXT_STEP
        ),
    }


def _scenario_payload(
    scenario: EvaluationScenario,
    execution: ApplicationIntakeScenarioExecution,
) -> dict[str, object]:
    result = execution.result
    fields = execution.expected_safe_output_fields_present
    application_safe = (
        result.category in {"success", "safe_fallback_used"}
        and execution.temporary_application_state_restored
    )
    ok = (
        result.ok
        and result.agent_output_valid is True
        and result.fallback_used is False
        and fields == SAFE_OUTPUT_FIELDS
        and execution.actual_urgency == scenario.expected_urgency
        and result.intake_status == scenario.expected_intake_status
        and result.review_status == "PendingReview"
        and result.notifications_suppressed
        and execution.temporary_application_state_restored
    )
    return {
        "id": scenario.id,
        "ok": ok,
        "agent_output_valid": result.agent_output_valid,
        "fallback_used": result.fallback_used,
        "application_safe": application_safe,
        "expected_urgency": scenario.expected_urgency,
        "actual_urgency": execution.actual_urgency,
        "expected_intake_status": scenario.expected_intake_status,
        "actual_intake_status": result.intake_status,
        "review_status": result.review_status,
        "notifications_suppressed": result.notifications_suppressed,
        "temporary_application_state_restored": (
            execution.temporary_application_state_restored
        ),
        "expected_safe_output_fields_present": fields,
    }


def _verification_metadata(
    result: FoundryAgentVerificationResult | None = None,
    *,
    category: str | None = None,
    azure_lookup_attempted: bool | None = False,
    sdk_available: bool | None = None,
) -> dict[str, object]:
    if result is not None:
        category = category or application_smoke._verification_gate_category(
            result.category
        )
        azure_lookup_attempted = result.azure_lookup_attempted
        configured_match = application_smoke._verification_match_status(result)
        sdk_available = result.category != "sdk_unavailable"
    else:
        configured_match = None
    return {
        "requested": True,
        "azure_lookup_attempted": azure_lookup_attempted,
        "configured_agent_version_matched": configured_match,
        "category": category or "not_attempted",
        "sdk_available": sdk_available,
    }


def _empty_live_payload(
    scenarios: list[EvaluationScenario],
    *,
    category: str,
    verification: dict[str, object],
    temporary_application_state_restored: bool,
) -> dict[str, object]:
    return {
        "ok": False,
        "mode": "live",
        "category": category,
        "verification": verification,
        "scenario_count": len(scenarios),
        "passed_count": 0,
        "failed_count": 0,
        "agent_client_created": False,
        "agent_invocation_count": 0,
        "application_intake_count": 0,
        "notifications_suppressed": False,
        "temporary_application_state_restored": (
            temporary_application_state_restored
        ),
        "scenarios": [],
        "recommended_next_step": VERIFICATION_FAILURE_NEXT_STEP,
    }


def _unexpected_scenario_execution() -> ApplicationIntakeScenarioExecution:
    result = application_smoke._empty_live_result("unexpected_error")
    return ApplicationIntakeScenarioExecution(
        result=result,
        invocation_attempted=False,
        application_intake_attempted=False,
        temporary_application_state_restored=False,
        actual_urgency=None,
        expected_safe_output_fields_present=[],
    )


def _invalid_corpus_payload(mode: str) -> dict[str, object]:
    return {
        "ok": False,
        "mode": mode,
        "category": "invalid_corpus",
        "scenario_count": 0,
        "scenario_ids": [],
        "recommended_next_step": "Repair the committed fictional corpus.",
    }


def _configuration_file_failure_payload(
    args: argparse.Namespace,
    scenarios: list[EvaluationScenario],
) -> dict[str, object]:
    if args.check:
        return {
            "ok": False,
            "ready": False,
            "mode": "check",
            "category": "missing_configuration",
            "scenario_count": len(scenarios),
            "scenario_ids": [scenario.id for scenario in scenarios],
            "recommended_next_step": CHECK_FAILURE_NEXT_STEP,
        }
    return _empty_live_payload(
        scenarios,
        category="missing_configuration",
        verification=_verification_metadata(category="missing_configuration"),
        temporary_application_state_restored=True,
    )


def _create_verification_service() -> FoundryAgentVerification:
    return FoundryAgentVerification()


def _create_live_agent(settings: AppSettings) -> object:
    return create_nurse_intake_agent(settings)


def _load_env_file(path_value: str | Path) -> bool:
    from dotenv import dotenv_values

    path = Path(path_value)
    if not path.is_file():
        return False
    for key, value in dotenv_values(path).items():
        if value is not None:
            os.environ.setdefault(key, value)
    return True


def _print_json(payload: dict[str, object]) -> None:
    print(json.dumps(payload, separators=(",", ":"), sort_keys=True))


if __name__ == "__main__":
    raise SystemExit(main())
