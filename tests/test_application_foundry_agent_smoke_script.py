import asyncio
import importlib
import inspect
import json
from types import SimpleNamespace

import pytest

from src.app.models.case import CaseDocument
from src.app.services.case_repository import InMemoryCaseRepository
from src.app.services.email_notification_sender import MockEmailNotificationSender
from src.app.services.foundry_agent_client import FoundryAgentResponse
from src.app.services.nurse_intake_agent import FoundryNurseIntakeAgent
from src.app.services.sms_notification_sender import MockSmsNotificationSender
from src.app.services.urgency_rules_service import RuleEvaluationResult


SECRET_PROJECT_ENDPOINT = (
    "https://secret-foundry.example/api/projects/secret-project"
)
SECRET_AGENT_ENDPOINT = (
    f"{SECRET_PROJECT_ENDPOINT}/agents/secret-agent/"
    "endpoint/protocols/openai"
)
SECRET_AGENT_NAME = "secret-agent"
SECRET_AGENT_VERSION = "42"
PRIVATE_MARKER = "private-agent-error-marker"


def _script():
    return importlib.import_module("scripts.smoke_application_foundry_agent")


def _settings(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "app_mode": "mock",
        "demo_suppress_notifications": True,
        "email_provider": "mock",
        "email_provider_normalized": "mock",
        "ai_provider": "mock",
        "ai_provider_normalized": "mock",
        "agent_provider": "foundry-agent",
        "agent_provider_normalized": "foundry-agent",
        "sms_provider": "mock",
        "sms_provider_normalized": "mock",
        "azure_ai_foundry_agent_project_endpoint": SECRET_PROJECT_ENDPOINT,
        "azure_ai_foundry_agent_endpoint": SECRET_AGENT_ENDPOINT,
        "azure_ai_foundry_agent_use_project_endpoint_compatibility": False,
        "azure_ai_foundry_agent_name": SECRET_AGENT_NAME,
        "azure_ai_foundry_agent_version": SECRET_AGENT_VERSION,
        "azure_ai_foundry_managed_identity_client_id": None,
        "cosmos_endpoint": None,
        "cosmos_key": None,
        "cosmos_database_name": "nurse-intake",
        "cosmos_container_name": "cases",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _valid_agent_response(*, urgency: str = "Routine") -> str:
    return json.dumps(
        {
            "extraction": {
                "patient": {
                    "name": "Fictional Avery Example",
                    "date_of_birth": "2000-01-01",
                    "callback_number": "fictional-callback-only",
                },
                "reason_for_calling": "new symptoms",
                "symptoms": ["chest discomfort"],
                "summary": "Fictional patient reports new symptoms.",
                "missing_fields": [],
                "uncertain_fields": [],
            },
            "urgency": {
                "urgency": urgency,
                "urgency_rationale": (
                    f"Agent returned an {urgency.casefold()} advisory result."
                ),
                "advisory_disclaimer": (
                    "Advisory urgency only; nurse review and clinical judgment "
                    "are required."
                ),
            },
        }
    )


class RecordingFoundryAgentClient:
    def __init__(
        self,
        response: str | None = None,
        error: BaseException | None = None,
    ) -> None:
        self.response = response if response is not None else _valid_agent_response()
        self.error = error
        self.requests = []

    async def invoke_agent(self, request):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return FoundryAgentResponse(content=self.response)


class StatusCodeError(RuntimeError):
    def __init__(self, status_code: int) -> None:
        super().__init__(
            f"{PRIVATE_MARKER} {SECRET_PROJECT_ENDPOINT} bearer-secret raw-response"
        )
        self.status_code = status_code


class FailingInMemoryRepository(InMemoryCaseRepository):
    async def save(self, case: CaseDocument) -> CaseDocument:
        raise RuntimeError(f"{PRIVATE_MARKER} persistence secret") from None


class FixedRulesService:
    def __init__(self, urgency: str) -> None:
        self.result = RuleEvaluationResult(
            urgency=urgency,
            matched_red_flags=[],
        )
        self.calls: list[str] = []

    def evaluate(self, raw_text: str) -> RuleEvaluationResult:
        self.calls.append(raw_text)
        return self.result


def _install_composition(
    monkeypatch: pytest.MonkeyPatch,
    script,
    *,
    client: RecordingFoundryAgentClient | None = None,
    repository: InMemoryCaseRepository | None = None,
    pre_record_notification: bool = False,
    rules_service: object | None = None,
):
    from src.app.services import (
        email_notification_sender_factory,
        nurse_intake_agent_factory,
        repository_factory,
        sms_notification_sender_factory,
    )

    active_client = client or RecordingFoundryAgentClient()
    active_repository = repository or InMemoryCaseRepository()
    email_sender = MockEmailNotificationSender()
    sms_sender = MockSmsNotificationSender()
    if pre_record_notification:
        email_sender.sent_notifications.append(
            {
                "recipient": "private@example.invalid",
                "subject": PRIVATE_MARKER,
                "body": PRIVATE_MARKER,
                "case_id": PRIVATE_MARKER,
            }
        )
    monkeypatch.setattr(
        nurse_intake_agent_factory,
        "create_optional_nurse_intake_agent",
        lambda settings: FoundryNurseIntakeAgent(
            settings=settings,
            client=active_client,
        ),
    )
    monkeypatch.setattr(
        repository_factory,
        "create_case_repository",
        lambda settings: active_repository,
    )
    monkeypatch.setattr(
        email_notification_sender_factory,
        "create_email_notification_sender",
        lambda settings: email_sender,
    )
    monkeypatch.setattr(
        sms_notification_sender_factory,
        "create_sms_notification_sender",
        lambda settings: sms_sender,
    )
    original_compose = script.compose_application
    composition_calls: list[object] = []

    def recording_compose(settings):
        composition_calls.append(settings)
        application = original_compose(settings)
        if rules_service is not None:
            application.case_processing_service.rules_service = rules_service
        return application

    monkeypatch.setattr(script, "compose_application", recording_compose)
    return (
        active_client,
        active_repository,
        email_sender,
        sms_sender,
        composition_calls,
    )


def test_check_mode_is_configuration_only_and_invokes_nothing(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = _script()
    monkeypatch.setattr(
        script,
        "_configuration_context",
        lambda path: _settings_context(_settings()),
    )
    monkeypatch.setattr(
        script,
        "compose_application",
        lambda settings: pytest.fail("check mode must not compose the application"),
    )
    monkeypatch.setattr(
        script,
        "run_application_foundry_agent_smoke",
        lambda settings: pytest.fail("check mode must not run intake"),
    )

    exit_code = script.main(["--check", "--config", "ignored", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["mode"] == "check"
    assert payload["application_composition_used"] is False
    assert payload["agent_attempted"] is False
    assert payload["case_persisted_in_memory"] is False
    assert payload["azure_mutation_made"] is False
    assert set(payload["required_agent_settings_present"]) == {
        "AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT",
        "AZURE_AI_FOUNDRY_AGENT_ENDPOINT",
        "AZURE_AI_FOUNDRY_AGENT_NAME",
        "AZURE_AI_FOUNDRY_AGENT_VERSION",
    }


def test_live_success_uses_shared_composition_and_normal_case_processing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = _script()
    client, repository, email, sms, composition_calls = _install_composition(
        monkeypatch,
        script,
    )
    settings = _settings()

    result = script.run_application_foundry_agent_smoke(settings)

    assert result.ok is True
    assert result.category == "success"
    assert composition_calls == [settings]
    assert len(client.requests) == 1
    assert client.requests[0].intake_text == script.FIXED_FICTIONAL_INTAKE
    assert "Return JSON only" in client.requests[0].instructions
    assert result.application_composition_used is True
    assert result.agent_attempted is True
    assert result.agent_output_valid is True
    assert result.fallback_used is False
    assert result.deterministic_rules_applied is True
    assert result.case_persisted_in_memory is True
    assert result.notification_email_status == "Suppressed"
    assert result.notification_sms_status == "Suppressed"
    assert result.nurse_review_required is True
    assert result.azure_mutation_made is False
    cases = asyncio.run(repository.list_cases())
    assert len(cases) == 1
    assert cases[0].processing_trace.agent_used is True
    assert cases[0].processing_trace.agent_output_valid is True
    assert cases[0].processing_trace.agent_fallback_used is False
    assert cases[0].processing_trace.rules_urgency_override is True
    assert cases[0].processing_trace.final_urgency_source == "rules"
    assert cases[0].ruleUrgency == "Urgent"
    assert cases[0].urgency == "Urgent"
    assert cases[0].reviewStatus == "PendingReview"
    assert email.sent_notifications == []
    assert sms.sent_notifications == []


def test_rules_execute_when_agent_already_returns_matching_urgent_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = _script()
    client = RecordingFoundryAgentClient(
        response=_valid_agent_response(urgency="Urgent")
    )
    _, repository, _, _, _ = _install_composition(
        monkeypatch,
        script,
        client=client,
    )

    result = script.run_application_foundry_agent_smoke(_settings())

    assert result.ok is True
    assert result.category == "success"
    assert result.deterministic_rules_applied is True
    case = asyncio.run(repository.list_cases())[0]
    assert case.aiUrgency == "Urgent"
    assert case.ruleUrgency == "Urgent"
    assert case.processing_trace.rules_urgency_override is False
    assert case.processing_trace.final_urgency_source == "agent"


def test_rules_execute_without_changing_final_urgency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = _script()
    rules = FixedRulesService("Routine")
    _, repository, _, _, _ = _install_composition(
        monkeypatch,
        script,
        rules_service=rules,
    )

    result = script.run_application_foundry_agent_smoke(_settings())

    assert rules.calls == [script.FIXED_FICTIONAL_INTAKE]
    assert result.ok is True
    assert result.category == "success"
    assert result.deterministic_rules_applied is True
    case = asyncio.run(repository.list_cases())[0]
    assert case.aiUrgency == "Routine"
    assert case.ruleUrgency == "Routine"
    assert case.urgency == "Routine"
    assert case.processing_trace.rules_urgency_override is False


def test_rules_execution_is_proven_separately_from_trace_and_promotion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = _script()
    client, _, _, _, _ = _install_composition(monkeypatch, script)
    settings = _settings()
    application = script.compose_application(settings)
    case = asyncio.run(
        application.case_processing_service.process(
            script.FIXED_FICTIONAL_INTAKE,
            "text-intake",
        )
    )
    agent_tracker = SimpleNamespace(attempt_count=1, failure_category=None)
    rules_tracker = SimpleNamespace(attempt_count=0, completed=False)

    result = script._result_from_processed_case(
        case,
        application,
        agent_tracker,
        rules_tracker,
        script.build_application_foundry_agent_readiness(settings),
    )

    assert len(client.requests) == 1
    assert "rules.apply_red_flags" in case.processing_trace.steps
    assert result.ok is False
    assert result.category == "deterministic_rules_failure"
    assert result.agent_output_valid is True
    assert result.deterministic_rules_applied is False


def test_script_does_not_assemble_parallel_dependency_graph() -> None:
    source = inspect.getsource(_script())

    assert "CaseProcessingService(" not in source
    assert "InMemoryCaseRepository(" not in source
    assert "MockEmailNotificationSender(" not in source
    assert "MockSmsNotificationSender(" not in source
    assert "FoundryNurseIntakeAgent(" not in source
    assert source.count("compose_application(") == 1


def test_environment_or_cli_cannot_replace_fixed_fictional_intake(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = _script()
    client, _, _, _, _ = _install_composition(monkeypatch, script)
    monkeypatch.setenv(
        "PATIENT_TEXT",
        "Real patient text that must never enter the application smoke.",
    )

    result = script.run_application_foundry_agent_smoke(_settings())

    assert result.ok is True
    assert len(client.requests) == 1
    assert client.requests[0].intake_text == script.FIXED_FICTIONAL_INTAKE
    with pytest.raises(Exception):
        script._parse_args(
            [
                "--live",
                "--config",
                "ignored",
                "--json",
                "--patient-text",
                "not allowed",
            ]
        )


def test_invalid_agent_output_fails_even_though_application_persists_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = _script()
    client = RecordingFoundryAgentClient(response="not-json private raw response")
    client, repository, _, _, _ = _install_composition(
        monkeypatch,
        script,
        client=client,
    )

    result = script.run_application_foundry_agent_smoke(_settings())

    assert len(client.requests) == 1
    assert result.ok is False
    assert result.category == "invalid_agent_output"
    assert result.agent_attempted is True
    assert result.agent_output_valid is False
    assert result.fallback_used is True
    assert result.deterministic_rules_applied is True
    assert len(asyncio.run(repository.list_cases())) == 1


@pytest.mark.parametrize(
    ("status_code", "expected_category"),
    [(401, "authentication_failure"), (403, "authorization_failure")],
)
def test_authentication_and_authorization_failures_are_sanitized(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
    expected_category: str,
) -> None:
    script = _script()
    client = RecordingFoundryAgentClient(error=StatusCodeError(status_code))
    _install_composition(monkeypatch, script, client=client)

    result = script.run_application_foundry_agent_smoke(_settings())
    serialized = json.dumps(result.to_json_dict())

    assert len(client.requests) == 1
    assert result.ok is False
    assert result.category == expected_category
    assert result.agent_attempted is True
    assert result.agent_output_valid is False
    assert result.fallback_used is True
    assert PRIVATE_MARKER not in serialized
    assert SECRET_PROJECT_ENDPOINT not in serialized
    assert "bearer-secret" not in serialized
    assert "raw-response" not in serialized


def test_unsafe_provider_posture_fails_before_composition_or_agent_invocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = _script()
    monkeypatch.setattr(
        script,
        "compose_application",
        lambda settings: pytest.fail("unsafe posture must fail before composition"),
    )

    result = script.run_application_foundry_agent_smoke(
        _settings(app_mode="cosmos", ai_provider_normalized="foundry")
    )

    assert result.ok is False
    assert result.category == "unsafe_provider_posture"
    assert result.agent_attempted is False
    assert set(result.unsafe_settings) == {"APP_MODE", "AI_PROVIDER"}


def test_persistence_failure_is_sanitized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = _script()
    client, _, _, _, _ = _install_composition(
        monkeypatch,
        script,
        repository=FailingInMemoryRepository(),
    )

    result = script.run_application_foundry_agent_smoke(_settings())
    serialized = json.dumps(result.to_json_dict())

    assert len(client.requests) == 1
    assert result.ok is False
    assert result.category == "persistence_failure"
    assert result.agent_output_valid is True
    assert PRIVATE_MARKER not in serialized


def test_notification_suppression_failure_is_detected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = _script()
    _install_composition(
        monkeypatch,
        script,
        pre_record_notification=True,
    )

    result = script.run_application_foundry_agent_smoke(_settings())

    assert result.ok is False
    assert result.category == "notification_suppression_failure"
    assert result.notification_email_status == "Suppressed"
    assert result.notification_sms_status == "Suppressed"


def test_nurse_review_invariant_failure_is_detected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = _script()
    _install_composition(monkeypatch, script)
    original_compose = script.compose_application

    def compose_with_review_violation(settings):
        application = original_compose(settings)
        original_process = application.case_processing_service.process

        async def process(*args, **kwargs):
            case = await original_process(*args, **kwargs)
            case.reviewStatus = "Reviewed"
            return case

        application.case_processing_service.process = process
        return application

    monkeypatch.setattr(script, "compose_application", compose_with_review_violation)

    result = script.run_application_foundry_agent_smoke(_settings())

    assert result.ok is False
    assert result.category == "nurse_review_invariant_failure"
    assert result.nurse_review_required is False


def test_output_is_allowlisted_and_contains_no_private_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = _script()
    client, _, _, _, _ = _install_composition(monkeypatch, script)

    payload = script.run_application_foundry_agent_smoke(
        _settings()
    ).to_json_dict()
    serialized = json.dumps(payload)

    assert set(payload) == script.SAFE_RESULT_FIELDS
    for forbidden in [
        script.FIXED_FICTIONAL_INTAKE,
        _valid_agent_response(),
        client.requests[0].instructions,
        SECRET_PROJECT_ENDPOINT,
        SECRET_AGENT_ENDPOINT,
        SECRET_AGENT_NAME,
        SECRET_AGENT_VERSION,
        "Fictional Avery Example",
        "Fictional patient reports new symptoms.",
        "handoff",
        "token",
        "credential",
        "Traceback",
    ]:
        assert forbidden not in serialized


def test_no_azure_mutation_or_retired_operator_boundary_is_referenced() -> None:
    source = inspect.getsource(_script()).casefold()

    for forbidden in [
        "subprocess",
        "deploy_foundry",
        "consumer_rbac",
        "webjob",
        "cleanup_daily",
        "configure_foundry_agent_endpoint_routing",
        "az cognitiveservices",
        "az deployment",
    ]:
        assert forbidden not in source


def test_check_json_is_deterministic_parseable_and_never_prints_values(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = _script()
    monkeypatch.setattr(
        script,
        "_configuration_context",
        lambda path: _settings_context(_settings()),
    )

    first_exit = script.main(["--check", "--config", "ignored", "--json"])
    first = capsys.readouterr().out
    second_exit = script.main(["--check", "--config", "ignored", "--json"])
    second = capsys.readouterr().out

    assert first_exit == second_exit == 0
    assert first == second
    assert json.loads(first)["category"] == "success"
    for secret in [
        SECRET_PROJECT_ENDPOINT,
        SECRET_AGENT_ENDPOINT,
        SECRET_AGENT_NAME,
        SECRET_AGENT_VERSION,
    ]:
        assert secret not in first


def test_malformed_or_missing_configuration_fails_closed(
    tmp_path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = _script()
    malformed = tmp_path / "malformed.env"
    malformed.write_text("APP_MODE\n", encoding="utf-8")

    malformed_exit = script.main(
        ["--check", "--config", str(malformed), "--json"]
    )
    malformed_payload = json.loads(capsys.readouterr().out)
    missing_exit = script.main(
        ["--check", "--config", str(tmp_path / "missing.env"), "--json"]
    )
    missing_payload = json.loads(capsys.readouterr().out)

    assert malformed_exit == 2
    assert malformed_payload["category"] == "invalid_configuration"
    assert missing_exit == 2
    assert missing_payload["category"] == "missing_configuration"


def test_config_context_forces_missing_notification_suppression_safe(
    tmp_path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = _script()
    config = tmp_path / "agent.env"
    config.write_text(
        "\n".join(
            [
                "APP_MODE=mock",
                "AI_PROVIDER=mock",
                "AGENT_PROVIDER=foundry-agent",
                "EMAIL_PROVIDER=mock",
                "SMS_PROVIDER=mock",
                f"AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT={SECRET_PROJECT_ENDPOINT}",
                f"AZURE_AI_FOUNDRY_AGENT_ENDPOINT={SECRET_AGENT_ENDPOINT}",
                f"AZURE_AI_FOUNDRY_AGENT_NAME={SECRET_AGENT_NAME}",
                f"AZURE_AI_FOUNDRY_AGENT_VERSION={SECRET_AGENT_VERSION}",
            ]
        ),
        encoding="utf-8",
    )

    exit_code = script.main(
        ["--check", "--config", str(config), "--json"]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["category"] == "success"
    assert payload["unsafe_settings"] == []


class _settings_context:
    def __init__(self, settings: object) -> None:
        self.settings = settings

    def __enter__(self):
        return self.settings

    def __exit__(self, exception_type, exception, traceback) -> None:
        return None
