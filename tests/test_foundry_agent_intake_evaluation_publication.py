import json
from types import SimpleNamespace

import pytest

from scripts.smoke_foundry_agent_intake import (
    ApplicationIntakeScenarioExecution,
    ApplicationIntakeSmokeResult,
)
from src.app.services.foundry_agent_verification import (
    FoundryAgentVerificationResult,
)
from src.app.services.foundry_evaluation_publisher import (
    FoundryEvaluationPublishResult,
)


PUBLISH_ARGS = [
    "--live",
    "--json",
    "--verify-agent-version",
    "--publish-foundry-evaluation",
]
SCENARIO_IDS = [
    "urgent-red-flag",
    "routine-non-red-flag",
    "incomplete-follow-up",
]


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        app_mode="mock",
        ai_provider_normalized="mock",
        agent_provider_normalized="foundry-agent",
        email_provider_normalized="mock",
        sms_provider_normalized="mock",
        demo_suppress_notifications=True,
        azure_ai_foundry_agent_project_endpoint=(
            "https://secret.example/api/projects/evaluation"
        ),
        azure_ai_foundry_agent_endpoint=(
            "https://secret.example/api/projects/evaluation/agents/secret-agent/"
            "endpoint/protocols/openai"
        ),
        azure_ai_foundry_agent_use_project_endpoint_compatibility=False,
        azure_ai_foundry_agent_name="secret-agent",
        azure_ai_foundry_agent_version="17",
        azure_ai_foundry_model_deployment_name="secret-model",
        azure_subscription_id="secret-subscription-id",
        azure_ai_foundry_resource_group_name="secret-resource-group",
        azure_ai_foundry_project_name="secret-project-name",
    )


class SuccessfulVerification:
    def verify(self, request: object) -> FoundryAgentVerificationResult:
        return FoundryAgentVerificationResult.success()


def _execution(
    *,
    fallback_used: bool = False,
    restored: bool = True,
    urgency: str = "Routine",
    intake_status: str = "Complete",
) -> ApplicationIntakeScenarioExecution:
    return ApplicationIntakeScenarioExecution(
        result=ApplicationIntakeSmokeResult(
            ok=True,
            mode="live",
            category="safe_fallback_used" if fallback_used else "success",
            message="static",
            agent_attempted=True,
            agent_output_valid=not fallback_used,
            fallback_used=fallback_used,
            case_saved=True,
            intake_status=intake_status,
            review_status="PendingReview",
            urgency_present=True,
            handoff_note_present=True,
            processing_trace_present=True,
            notifications_suppressed=True,
            recommended_next_step="static",
            extraction_present=True,
        ),
        invocation_attempted=True,
        application_intake_attempted=True,
        temporary_application_state_restored=restored,
        actual_urgency=urgency,
        expected_safe_output_fields_present=["extraction", "urgency", "handoffNote"],
    )


class RecordingPublisher:
    def __init__(
        self,
        events: list[str],
        result: FoundryEvaluationPublishResult | None = None,
    ) -> None:
        self.events = events
        self.requests: list[object] = []
        self.result = result or FoundryEvaluationPublishResult.success(3)

    def publish(self, request: object) -> FoundryEvaluationPublishResult:
        self.events.append("publish")
        self.requests.append(request)
        return self.result


def _configure_live(
    monkeypatch: pytest.MonkeyPatch,
    publisher: RecordingPublisher,
    *,
    executions: list[ApplicationIntakeScenarioExecution] | None = None,
) -> list[str]:
    import scripts.evaluate_foundry_agent_intake as script

    events = publisher.events
    configured_executions = executions or [
        _execution(urgency="Urgent"),
        _execution(),
        _execution(intake_status="NeedsFollowUp"),
    ]
    monkeypatch.setattr(script, "AppSettings", _settings)
    monkeypatch.setattr(script, "foundry_agent_verification_sdk_available", lambda: True)
    monkeypatch.setattr(script, "foundry_evaluation_sdk_available", lambda: True)
    monkeypatch.setattr(script, "_create_verification_service", SuccessfulVerification)
    monkeypatch.setattr(script, "_create_live_agent", lambda settings: events.append("create-agent") or object())
    monkeypatch.setattr(script, "_create_evaluation_publisher", lambda: publisher)

    def run(agent: object, *, intake_text: str, source_system: str) -> ApplicationIntakeScenarioExecution:
        index = sum(event.startswith("scenario-") for event in events)
        events.append(f"scenario-{index + 1}")
        return configured_executions[index]

    monkeypatch.setattr(script, "run_foundry_agent_intake_scenario", run)
    return events


def test_publish_option_requires_live_json_and_verification() -> None:
    import scripts.evaluate_foundry_agent_intake as script

    invalid = [
        ["--check", "--json", "--publish-foundry-evaluation"],
        ["--live", "--publish-foundry-evaluation"],
        ["--live", "--json", "--publish-foundry-evaluation"],
    ]
    for argv in invalid:
        with pytest.raises(SystemExit) as exc_info:
            script.main(argv)
        assert exc_info.value.code == 2


def test_check_and_legacy_live_paths_never_touch_publication(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.evaluate_foundry_agent_intake as script

    monkeypatch.setattr(script, "AppSettings", _settings)
    monkeypatch.setattr(script, "foundry_agent_verification_sdk_available", lambda: True)
    monkeypatch.setattr(
        script,
        "foundry_evaluation_sdk_available",
        lambda: pytest.fail("legacy paths must not inspect publication SDK"),
    )
    monkeypatch.setattr(
        script,
        "_create_evaluation_publisher",
        lambda: pytest.fail("legacy paths must not construct a publisher"),
    )

    assert script.main(["--check", "--json"]) == 0
    check_payload = json.loads(capsys.readouterr().out)
    assert "publication" not in check_payload


@pytest.mark.parametrize(
    "failure",
    ["verification", "malformed_verification", "client", "restoration"],
)
def test_guard_failures_prevent_publication(
    failure: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.evaluate_foundry_agent_intake as script

    events: list[str] = []
    publisher = RecordingPublisher(events)
    executions = [
        _execution(urgency="Urgent", restored=failure != "restoration"),
        _execution(),
        _execution(intake_status="NeedsFollowUp"),
    ]
    _configure_live(monkeypatch, publisher, executions=executions)
    if failure == "verification":
        class FailedVerification:
            def verify(self, request: object) -> FoundryAgentVerificationResult:
                return FoundryAgentVerificationResult.failure(
                    "definition_mismatch",
                    agent_name_present=True,
                    agent_version_present=True,
                    model_deployment_name_present=True,
                    azure_lookup_attempted=True,
                )
        monkeypatch.setattr(script, "_create_verification_service", FailedVerification)
    elif failure == "malformed_verification":
        class MalformedVerification:
            def verify(self, request: object) -> SimpleNamespace:
                return SimpleNamespace(
                    ok=True,
                    category="success",
                    raw_response="Bearer malformed-secret raw response",
                )

        monkeypatch.setattr(
            script,
            "_create_verification_service",
            MalformedVerification,
        )
    elif failure == "client":
        monkeypatch.setattr(script, "_create_live_agent", lambda settings: (_ for _ in ()).throw(RuntimeError("Bearer secret")))

    assert script.main(PUBLISH_ARGS) == 1
    payload = json.loads(capsys.readouterr().out)
    assert publisher.requests == []
    assert payload["publication"]["publication_attempted"] is False
    assert "secret.example" not in json.dumps(payload)


@pytest.mark.parametrize("failure", ["invalid_corpus"])
def test_preflight_failures_prevent_publication(
    failure: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.evaluate_foundry_agent_intake as script

    monkeypatch.setattr(
        script,
        "load_evaluation_corpus",
        lambda: (_ for _ in ()).throw(script.EvaluationCorpusError()),
    )
    monkeypatch.setattr(
        script,
        "foundry_evaluation_sdk_available",
        lambda: pytest.fail("preflight failure must not inspect publication SDK"),
    )
    monkeypatch.setattr(
        script,
        "_create_evaluation_publisher",
        lambda: pytest.fail("preflight failure must not construct publisher"),
    )

    assert script.main(PUBLISH_ARGS) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["category"] == failure
    assert payload["publication"]["publication_attempted"] is False


@pytest.mark.parametrize(
    "missing_attribute",
    [
        "azure_subscription_id",
        "azure_ai_foundry_resource_group_name",
        "azure_ai_foundry_project_name",
    ],
)
def test_missing_project_scope_prevents_client_and_publication(
    missing_attribute: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.evaluate_foundry_agent_intake as script

    settings = _settings()
    setattr(settings, missing_attribute, None)
    monkeypatch.setattr(script, "AppSettings", lambda: settings)
    monkeypatch.setattr(script, "foundry_agent_verification_sdk_available", lambda: True)
    monkeypatch.setattr(
        script,
        "foundry_evaluation_sdk_available",
        lambda: pytest.fail("missing scope must fail before SDK readiness"),
    )
    monkeypatch.setattr(
        script,
        "_create_verification_service",
        lambda: pytest.fail("missing scope must prevent verification"),
    )
    monkeypatch.setattr(
        script,
        "_create_live_agent",
        lambda settings: pytest.fail("missing scope must prevent client creation"),
    )
    monkeypatch.setattr(
        script,
        "_create_evaluation_publisher",
        lambda: pytest.fail("missing scope must prevent publisher creation"),
    )

    assert script.main(PUBLISH_ARGS) == 2
    output = capsys.readouterr().out
    payload = json.loads(output)
    assert payload["category"] == "missing_configuration"
    assert payload["agent_client_created"] is False
    assert payload["publication"]["publication_attempted"] is False
    for value in (
        "secret-subscription-id",
        "secret-resource-group",
        "secret-project-name",
    ):
        assert value not in output


def test_success_publishes_once_after_all_scenarios_with_sanitized_metrics(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.evaluate_foundry_agent_intake as script

    events: list[str] = []
    publisher = RecordingPublisher(events)
    _configure_live(monkeypatch, publisher)

    exit_code = script.main(PUBLISH_ARGS)

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert exit_code == 0
    assert events == ["create-agent", "scenario-1", "scenario-2", "scenario-3", "publish"]
    assert len(publisher.requests) == 1
    request = publisher.requests[0]
    assert request.evaluation_name == "nurse-intake-fixed-corpus-v1"
    assert request.subscription_id == "secret-subscription-id"
    assert request.resource_group_name == "secret-resource-group"
    assert request.project_name == "secret-project-name"
    assert [metric.scenario_id for metric in request.scenarios] == SCENARIO_IDS
    assert all(not hasattr(metric, "intake_text") for metric in request.scenarios)
    assert payload["publication"] == {
        "foundry_tracking_requested": True,
        "publication_attempted": True,
        "ok": True,
        "category": "success",
        "scenario_count": 3,
        "metric_count": 27,
        "temporary_artifacts_removed": True,
    }
    assert payload["agent_invocation_count"] == 3
    assert payload["application_intake_count"] == 3
    assert "secret.example" not in output
    assert "secret-subscription-id" not in output
    assert "secret-resource-group" not in output
    assert "secret-project-name" not in output
    assert "intake_text" not in output


def test_safe_fallback_still_publishes_metrics_but_cli_fails(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    events: list[str] = []
    publisher = RecordingPublisher(events)
    _configure_live(
        monkeypatch,
        publisher,
        executions=[
            _execution(fallback_used=True, urgency="Urgent"),
            _execution(),
            _execution(intake_status="NeedsFollowUp"),
        ],
    )

    import scripts.evaluate_foundry_agent_intake as script
    assert script.main(PUBLISH_ARGS) == 1
    payload = json.loads(capsys.readouterr().out)
    assert len(publisher.requests) == 1
    first = publisher.requests[0].scenarios[0]
    assert first.scenario_ok is False
    assert first.agent_output_valid is False
    assert first.fallback_used is True
    assert first.application_safe is True
    assert payload["category"] == "evaluation_failed"
    assert payload["publication"]["ok"] is True


@pytest.mark.parametrize(
    "publish_result",
    [
        FoundryEvaluationPublishResult.failure(
            "publication_failed",
            publication_attempted=True,
            scenario_count=3,
            temporary_artifacts_removed=True,
        ),
        FoundryEvaluationPublishResult.failure(
            "response_contract_invalid",
            publication_attempted=True,
            scenario_count=3,
            temporary_artifacts_removed=True,
        ),
    ],
)
def test_publication_failure_is_sanitized_without_erasing_scenarios(
    publish_result: FoundryEvaluationPublishResult,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    events: list[str] = []
    publisher = RecordingPublisher(events, publish_result)
    _configure_live(monkeypatch, publisher)

    import scripts.evaluate_foundry_agent_intake as script
    assert script.main(PUBLISH_ARGS) == 1
    output = capsys.readouterr().out
    payload = json.loads(output)
    assert len(payload["scenarios"]) == 3
    assert payload["category"] == publish_result.category
    assert payload["publication"]["ok"] is False
    assert "secret.example" not in output
    assert "Traceback" not in output


def test_publication_sdk_unavailable_prevents_clients_and_scenarios(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.evaluate_foundry_agent_intake as script

    monkeypatch.setattr(script, "AppSettings", _settings)
    monkeypatch.setattr(script, "foundry_agent_verification_sdk_available", lambda: True)
    monkeypatch.setattr(script, "foundry_evaluation_sdk_available", lambda: False)
    monkeypatch.setattr(script, "_create_verification_service", lambda: pytest.fail("SDK readiness must fail first"))
    monkeypatch.setattr(script, "_create_live_agent", lambda settings: pytest.fail("SDK readiness must block client"))
    monkeypatch.setattr(script, "run_foundry_agent_intake_scenario", lambda *args, **kwargs: pytest.fail("SDK readiness must block scenarios"))

    assert script.main(PUBLISH_ARGS) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["category"] == "evaluation_sdk_unavailable"
    assert payload["agent_client_created"] is False
    assert payload["publication"]["publication_attempted"] is False
