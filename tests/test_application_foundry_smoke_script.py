import asyncio
import importlib
import inspect
import json
import os
from types import SimpleNamespace

import pytest

from src.app.models.case import CaseDocument
from src.app.services.case_repository import InMemoryCaseRepository
from src.app.services.email_notification_sender import MockEmailNotificationSender
from src.app.services.foundry_ai_service import FoundryAiService
from src.app.services.sms_notification_sender import MockSmsNotificationSender


SECRET_ENDPOINT = (
    "https://secret-foundry.services.ai.azure.com/api/projects/fictional-project"
)
SECRET_MODEL = "secret-model-deployment"
PRIVATE_MARKER = "private-provider-exception-marker"


def _script():
    return importlib.import_module("scripts.smoke_application_foundry_extraction")


def _settings(**overrides):
    values = {
        "app_mode": "mock",
        "demo_suppress_notifications": True,
        "email_provider": "mock",
        "email_provider_normalized": "mock",
        "ai_provider": "foundry",
        "ai_provider_normalized": "foundry",
        "agent_provider": "mock",
        "agent_provider_normalized": "mock",
        "sms_provider": "mock",
        "sms_provider_normalized": "mock",
        "azure_ai_foundry_project_endpoint": SECRET_ENDPOINT,
        "azure_ai_foundry_model_deployment_name": SECRET_MODEL,
        "cosmos_endpoint": None,
        "cosmos_key": None,
        "cosmos_database_name": "nurse-intake",
        "cosmos_container_name": "cases",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _valid_model_response() -> str:
    return json.dumps(
        {
            "patient": {
                "name": "Fictional Avery Example",
                "date_of_birth": "2000-01-01",
                "callback_number": "fictional-callback",
            },
            "reason_for_calling": "new symptoms",
            "symptoms": ["chest discomfort"],
            "summary": "Fictional intake summary.",
            "urgency": "Routine",
            "urgency_rationale": "The model returned a routine advisory result.",
            "advisory_disclaimer": (
                "Advisory urgency only; nurse review and clinical judgment "
                "are required."
            ),
            "missing_fields": [],
            "uncertain_fields": [],
        }
    )


class RecordingFoundryClient:
    def __init__(self, response: str | None = None, error: BaseException | None = None):
        self.response = response if response is not None else _valid_model_response()
        self.error = error
        self.calls: list[dict[str, str]] = []
        self.close_calls = 0

    def complete_structured_extraction(
        self,
        prompt: str,
        model_deployment_name: str,
    ) -> str:
        self.calls.append(
            {
                "prompt": prompt,
                "model_deployment_name": model_deployment_name,
            }
        )
        if self.error is not None:
            raise self.error
        return self.response

    def close(self) -> None:
        self.close_calls += 1


class RecordingEmailSender(MockEmailNotificationSender):
    def __init__(self) -> None:
        super().__init__()
        self.attempt_count = 0

    def send_case_notification(self, *args, **kwargs):
        self.attempt_count += 1
        return super().send_case_notification(*args, **kwargs)


class RecordingSmsSender(MockSmsNotificationSender):
    def __init__(self) -> None:
        super().__init__()
        self.attempt_count = 0

    def send_case_notification(self, *args, **kwargs):
        self.attempt_count += 1
        return super().send_case_notification(*args, **kwargs)


class StatusCodeError(RuntimeError):
    def __init__(self, status_code: int) -> None:
        super().__init__(PRIVATE_MARKER)
        self.status_code = status_code


class AuthenticationClientConstructionError(RuntimeError):
    pass


def _foundry_service(client: RecordingFoundryClient):
    return FoundryAiService(
        project_endpoint=SECRET_ENDPOINT,
        model_deployment_name=SECRET_MODEL,
        client=client,
    )


def _configuration(script, settings=None):
    receipt = SimpleNamespace(
        foundry_account_name="fictional-account",
        foundry_project_name="fictional-project",
    )
    return SimpleNamespace(
        settings=settings or _settings(),
        daily_config=SimpleNamespace(model_deployment_name=SECRET_MODEL),
        readiness_receipt=receipt,
    )


def _install_safe_composition(
    monkeypatch: pytest.MonkeyPatch,
    script,
    *,
    client: RecordingFoundryClient | None = None,
):
    from src.app.services import (
        ai_service_factory,
        email_notification_sender_factory,
        nurse_intake_agent_factory,
        repository_factory,
        sms_notification_sender_factory,
    )

    active_client = client or RecordingFoundryClient()
    repository = InMemoryCaseRepository()
    email_sender = MockEmailNotificationSender()
    sms_sender = MockSmsNotificationSender()
    monkeypatch.setattr(
        ai_service_factory,
        "create_ai_service",
        lambda settings: _foundry_service(active_client),
    )
    monkeypatch.setattr(
        nurse_intake_agent_factory,
        "create_optional_nurse_intake_agent",
        lambda settings: None,
    )
    monkeypatch.setattr(
        repository_factory,
        "create_case_repository",
        lambda settings: repository,
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
    configuration = _configuration(script)
    monkeypatch.setattr(
        script,
        "load_matching_daily_azure_readiness_receipt",
        lambda path, config: configuration.readiness_receipt,
    )
    return configuration, active_client, repository, email_sender, sms_sender


def test_check_is_offline_and_has_no_composition_side_effects(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = _script()
    from src.app.services import foundry_live_client

    def fail_if_constructed() -> object:
        raise AssertionError("check mode must not construct Foundry SDK resources")

    monkeypatch.setattr(
        foundry_live_client,
        "_get_default_credential_class",
        fail_if_constructed,
    )
    monkeypatch.setattr(
        foundry_live_client,
        "_get_ai_project_client_class",
        fail_if_constructed,
    )
    monkeypatch.setattr(
        script,
        "_load_application_configuration",
        lambda path: _configuration(script),
    )
    monkeypatch.setattr(
        script,
        "run_application_foundry_smoke",
        lambda settings: pytest.fail("live composition must not run in check mode"),
    )
    monkeypatch.setattr(
        script,
        "compose_application",
        lambda settings: pytest.fail("composition must not run in check mode"),
    )

    exit_code = script.main(["--check", "--config", "ignored", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["mode"] == "check"
    assert payload["foundry_invocation_attempted"] is False
    assert payload["case_persisted_in_memory"] is False
    assert payload["notification_attempted"] is False
    assert payload["azure_mutation_attempted"] is False


def test_daily_config_and_readiness_receipt_build_safe_application_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = _script()
    config = SimpleNamespace(model_deployment_name="configured-model")
    receipt = SimpleNamespace(
        foundry_account_name="fictional-account",
        foundry_project_name="fictional-project",
    )
    observed: dict[str, object] = {}

    def load_config(path, *, repository_root):
        observed["path"] = path
        observed["repository_root"] = repository_root
        return config

    def load_receipt(path, config_arg):
        observed["receipt_path"] = path
        observed["config"] = config_arg
        return receipt

    monkeypatch.setenv("AI_PROVIDER", "ambient-unsafe-value")
    monkeypatch.setattr(script, "load_daily_azure_config", load_config)
    monkeypatch.setattr(
        script,
        "load_matching_daily_azure_readiness_receipt",
        load_receipt,
    )

    loaded = script._load_application_configuration("ignored-config")
    settings = loaded.settings

    assert observed["path"] == "ignored-config"
    assert observed["repository_root"] == script.PROJECT_ROOT
    assert observed["config"] is config
    assert settings.app_mode == "mock"
    assert settings.ai_provider_normalized == "foundry"
    assert settings.agent_provider_normalized == "mock"
    assert settings.email_provider_normalized == "mock"
    assert settings.sms_provider_normalized == "mock"
    assert settings.demo_suppress_notifications is True
    assert settings.azure_ai_foundry_project_endpoint.endswith(
        "/api/projects/fictional-project"
    )
    assert settings.azure_ai_foundry_model_deployment_name == "configured-model"
    assert os.environ["AI_PROVIDER"] == "ambient-unsafe-value"
    assert loaded.daily_config is config
    assert loaded.readiness_receipt is receipt


def test_missing_readiness_receipt_fails_without_composition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = _script()
    monkeypatch.setattr(
        script,
        "load_daily_azure_config",
        lambda path, repository_root: SimpleNamespace(
            model_deployment_name="configured-model"
        ),
    )
    monkeypatch.setattr(
        script,
        "load_matching_daily_azure_readiness_receipt",
        lambda path, config: None,
    )

    with pytest.raises(script.SmokeConfigurationError) as error:
        script._load_application_configuration("ignored-config")

    assert error.value.category == "readiness_receipt_invalid"


def test_cli_requires_an_explicit_mode() -> None:
    script = _script()

    with pytest.raises(script._InvalidArgumentsError):
        script._parse_args(["--config", "ignored", "--json"])


def test_live_requires_json_output() -> None:
    script = _script()

    with pytest.raises(script._InvalidArgumentsError):
        script._parse_args(["--live", "--config", "ignored"])


def test_fixed_payload_cannot_be_replaced_from_the_cli() -> None:
    script = _script()

    with pytest.raises(script._InvalidArgumentsError):
        script._parse_args(
            [
                "--live",
                "--config",
                "ignored",
                "--json",
                "--text",
                "arbitrary patient text",
            ]
        )


def test_fixed_payload_is_fictional_and_contains_a_deterministic_red_flag() -> None:
    script = _script()

    assert "fictional" in script.FIXED_FICTIONAL_INTAKE.casefold()
    assert "chest pain" in script.FIXED_FICTIONAL_INTAKE.casefold()
    assert "shortness of breath" in script.FIXED_FICTIONAL_INTAKE.casefold()
    assert "+1" not in script.FIXED_FICTIONAL_INTAKE
    assert "555" not in script.FIXED_FICTIONAL_INTAKE
    assert "@" not in script.FIXED_FICTIONAL_INTAKE


@pytest.mark.parametrize(
    "overrides,unsafe_setting",
    [
        (
            {"ai_provider": "mock", "ai_provider_normalized": "mock"},
            "AI_PROVIDER",
        ),
        (
            {"app_mode": "cosmos"},
            "APP_MODE",
        ),
        (
            {"email_provider": "acs", "email_provider_normalized": "acs"},
            "EMAIL_PROVIDER",
        ),
        (
            {"sms_provider": "acs", "sms_provider_normalized": "acs"},
            "SMS_PROVIDER",
        ),
        (
            {"demo_suppress_notifications": False},
            "DEMO_SUPPRESS_NOTIFICATIONS",
        ),
        (
            {"agent_provider": "foundry", "agent_provider_normalized": "foundry"},
            "AGENT_PROVIDER",
        ),
        (
            {
                "agent_provider": "foundry-agent",
                "agent_provider_normalized": "foundry-agent",
            },
            "AGENT_PROVIDER",
        ),
    ],
)
def test_unsafe_provider_combinations_fail_before_invocation(
    overrides: dict[str, object],
    unsafe_setting: str,
) -> None:
    script = _script()
    result = script.run_application_foundry_smoke(
        _configuration(script, _settings(**overrides))
    )

    assert result.ok is False
    assert result.category == "unsafe_configuration"
    assert unsafe_setting in result.unsafe_settings
    assert result.foundry_invocation_attempted is False


@pytest.mark.parametrize(
    "overrides,missing_setting",
    [
        ({"azure_ai_foundry_project_endpoint": None}, "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT"),
        (
            {"azure_ai_foundry_model_deployment_name": None},
            "AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT_NAME",
        ),
    ],
)
def test_missing_foundry_settings_fail_closed(
    overrides: dict[str, object],
    missing_setting: str,
) -> None:
    script = _script()

    readiness = script.build_application_foundry_smoke_readiness(
        _settings(**overrides)
    )

    assert readiness.ready is False
    assert readiness.category == "missing_configuration"
    assert missing_setting in readiness.missing_settings


def test_real_ai_factory_selects_foundry_service() -> None:
    from src.app.services import ai_service_factory

    service = ai_service_factory.create_ai_service(_settings())

    assert isinstance(service, FoundryAiService)
    assert service.client is None
    assert service.client_factory is not None


def test_smoke_composes_case_processing_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = _script()
    configuration, _, _, _, _ = _install_safe_composition(
        monkeypatch,
        script,
    )
    result = script.run_application_foundry_smoke(configuration)

    assert result.ok is True
    assert result.case_processing_service_used is True


def test_one_live_call_maps_models_runs_rules_and_requires_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = _script()
    client = RecordingFoundryClient()
    configuration, _, _, _, _ = _install_safe_composition(
        monkeypatch,
        script,
        client=client,
    )
    result = script.run_application_foundry_smoke(configuration)

    assert result.ok is True
    assert len(client.calls) == 1
    assert client.close_calls == 1
    assert script.FIXED_FICTIONAL_INTAKE in client.calls[0]["prompt"]
    assert result.ai_provider_verified is True
    assert result.foundry_invocation_attempted is True
    assert result.foundry_output_valid is True
    assert result.deterministic_rules_evaluated is True
    assert result.rules_promoted_urgency is True
    assert result.case_document_valid is True
    assert result.case_persisted_in_memory is True
    assert result.nurse_review_required is True
    assert result.notifications_suppressed is True
    assert result.notification_attempted is False
    assert result.azure_mutation_attempted is False


def test_case_is_persisted_only_to_in_memory_repository(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = _script()
    configuration, _, repository, _, _ = _install_safe_composition(
        monkeypatch,
        script,
    )
    result = script.run_application_foundry_smoke(configuration)

    assert result.ok is True
    assert isinstance(repository, InMemoryCaseRepository)
    cases = asyncio.run(repository.list_cases())
    assert len(cases) == 1
    assert all(isinstance(case, CaseDocument) for case in cases)


def test_email_and_sms_are_not_attempted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = _script()
    configuration, _, _, email_sender, sms_sender = _install_safe_composition(
        monkeypatch,
        script,
    )
    result = script.run_application_foundry_smoke(configuration)

    assert result.ok is True
    assert email_sender.sent_notifications == []
    assert sms_sender.sent_notifications == []


@pytest.mark.parametrize(
    "response",
    [
        "{not-json",
        json.dumps(
            {
                "patient": {},
                "urgency": "Routine",
                "urgency_rationale": "Missing the required summary.",
            }
        ),
    ],
)
def test_invalid_or_schema_invalid_model_output_fails_safely(
    response: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = _script()
    configuration, _, _, _, _ = _install_safe_composition(
        monkeypatch,
        script,
        client=RecordingFoundryClient(response=response),
    )
    result = script.run_application_foundry_smoke(configuration)

    assert result.ok is False
    assert result.category == "model_response_invalid"
    assert result.foundry_invocation_attempted is True
    assert result.foundry_output_valid is False
    assert PRIVATE_MARKER not in json.dumps(result.to_json_dict())


@pytest.mark.parametrize(
    "error,category",
    [
        (StatusCodeError(401), "authentication_failed"),
        (StatusCodeError(403), "authorization_failed"),
        (StatusCodeError(400), "provider_request_failed"),
        (StatusCodeError(404), "provider_request_failed"),
        (StatusCodeError(422), "provider_request_failed"),
        (StatusCodeError(500), "provider_request_failed"),
        (
            AuthenticationClientConstructionError(PRIVATE_MARKER),
            "provider_request_failed",
        ),
        (RuntimeError(PRIVATE_MARKER), "provider_request_failed"),
    ],
)
def test_provider_failures_use_allowlisted_sanitized_categories(
    error: BaseException,
    category: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = _script()
    configuration, _, _, _, _ = _install_safe_composition(
        monkeypatch,
        script,
        client=RecordingFoundryClient(error=error),
    )
    result = script.run_application_foundry_smoke(configuration)

    serialized = json.dumps(result.to_json_dict())
    assert result.ok is False
    assert result.category == category
    assert result.foundry_invocation_attempted is True
    assert PRIVATE_MARKER not in serialized
    assert SECRET_ENDPOINT not in serialized
    assert SECRET_MODEL not in serialized


@pytest.mark.parametrize(
    "error_name",
    [
        "ClientAuthenticationError",
        "AuthenticationRequiredError",
        "CredentialUnavailableError",
    ],
)
def test_token_acquisition_failures_map_to_sanitized_authentication_category(
    error_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from azure.core.exceptions import ClientAuthenticationError
    from azure.identity import AuthenticationRequiredError, CredentialUnavailableError

    errors = {
        "ClientAuthenticationError": ClientAuthenticationError(PRIVATE_MARKER),
        "AuthenticationRequiredError": AuthenticationRequiredError(
            ["https://ai.azure.com/.default"],
            message=PRIVATE_MARKER,
        ),
        "CredentialUnavailableError": CredentialUnavailableError(PRIVATE_MARKER),
    }
    script = _script()
    configuration, _, _, _, _ = _install_safe_composition(
        monkeypatch,
        script,
        client=RecordingFoundryClient(error=errors[error_name]),
    )

    result = script.run_application_foundry_smoke(configuration)

    serialized = json.dumps(result.to_json_dict())
    assert result.category == "authentication_failed"
    assert PRIVATE_MARKER not in serialized
    assert "ai.azure.com" not in serialized


def test_provider_result_omits_all_private_provider_material(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = _script()
    private_values = (
        SECRET_ENDPOINT,
        SECRET_MODEL,
        "private-response-content",
        "private-exception-text",
        "private-bearer-token",
        "private-request-headers",
    )
    configuration, _, _, _, _ = _install_safe_composition(
        monkeypatch,
        script,
        client=RecordingFoundryClient(
            error=RuntimeError(" ".join(private_values)),
        ),
    )

    result = script.run_application_foundry_smoke(configuration)

    serialized = json.dumps(result.to_json_dict())
    assert result.category == "provider_request_failed"
    assert all(value not in serialized for value in private_values)


def test_json_output_is_allowlisted_and_contains_no_private_values(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = _script()
    configuration, _, _, _, _ = _install_safe_composition(
        monkeypatch,
        script,
    )
    monkeypatch.setattr(
        script,
        "_load_application_configuration",
        lambda path: configuration,
    )

    exit_code = script.main(["--live", "--config", "ignored", "--json"])

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert exit_code == 0
    assert set(payload) == script.SAFE_RESULT_FIELDS
    for private_value in (
        script.FIXED_FICTIONAL_INTAKE,
        "Fictional Avery Example",
        "new symptoms",
        "Fictional intake summary.",
        SECRET_ENDPOINT,
        SECRET_MODEL,
        PRIVATE_MARKER,
        "Return JSON only",
        "token",
    ):
        assert private_value not in output


def test_live_result_proves_no_mutation_and_one_inference_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = _script()
    client = RecordingFoundryClient()
    configuration, _, _, _, _ = _install_safe_composition(
        monkeypatch,
        script,
        client=client,
    )
    result = script.run_application_foundry_smoke(configuration)

    assert result.ok is True
    assert len(client.calls) == 1
    assert result.foundry_invocation_attempted is True
    assert result.azure_mutation_attempted is False
    assert result.notification_attempted is False


@pytest.mark.parametrize(
    "argv",
    [
        [
            "--check",
            "--config",
            "ignored",
            "--json",
            "--unknown-option",
            "private-parser-marker",
        ],
        [
            "--check",
            "--config",
            "ignored",
            "--json",
            "--text",
            "private-patient-marker",
        ],
        ["--check", "--config", "--json"],
    ],
)
def test_json_parser_failures_are_single_sanitized_objects(
    argv: list[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = _script()

    exit_code = script.main(argv)

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 2
    assert captured.err == ""
    assert set(payload) == script.SAFE_RESULT_FIELDS
    assert payload["category"] == "invalid_arguments"
    assert "private-parser-marker" not in captured.out
    assert "private-patient-marker" not in captured.out
    assert "--unknown-option" not in captured.out
    assert "--text" not in captured.out
    assert "--config" not in captured.out


def test_non_json_parser_failure_uses_fixed_generic_wording(
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = _script()

    exit_code = script.main(
        [
            "--check",
            "--config",
            "ignored",
            "--unknown-option",
            "private-non-json-marker",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert captured.err == "Application Foundry smoke invocation failed.\n"
    assert "private-non-json-marker" not in captured.err


def test_unexpected_settings_failure_is_sanitized(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = _script()
    monkeypatch.setattr(
        script,
        "_load_application_configuration",
        lambda path: (_ for _ in ()).throw(
            RuntimeError("private-settings-exception-marker")
        ),
    )

    exit_code = script.main(["--check", "--config", "ignored", "--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 1
    assert captured.err == ""
    assert payload["category"] == "unexpected_error"
    assert "private-settings-exception-marker" not in captured.out
    assert "RuntimeError" not in captured.out
    assert "Traceback" not in captured.out


def test_unexpected_app_settings_construction_failure_is_sanitized(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = _script()
    receipt = SimpleNamespace(
        foundry_account_name="fictional-account",
        foundry_project_name="fictional-project",
    )
    monkeypatch.setattr(
        script,
        "load_daily_azure_config",
        lambda path, repository_root: SimpleNamespace(
            model_deployment_name="fictional-model"
        ),
    )
    monkeypatch.setattr(
        script,
        "load_matching_daily_azure_readiness_receipt",
        lambda path, config: receipt,
    )
    monkeypatch.setattr(
        script,
        "AppSettings",
        lambda: (_ for _ in ()).throw(
            RuntimeError("private-app-settings-marker")
        ),
    )

    exit_code = script.main(["--check", "--config", "ignored", "--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 1
    assert captured.err == ""
    assert payload["category"] == "unexpected_error"
    assert "private-app-settings-marker" not in captured.out
    assert "RuntimeError" not in captured.out
    assert "Traceback" not in captured.out


def test_unexpected_composer_failure_is_sanitized(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = _script()
    configuration = _configuration(script)
    monkeypatch.setattr(
        script,
        "_load_application_configuration",
        lambda path: configuration,
    )
    monkeypatch.setattr(
        script,
        "compose_application",
        lambda settings: (_ for _ in ()).throw(
            RuntimeError("private-composer-marker")
        ),
    )

    exit_code = script.main(["--live", "--config", "ignored", "--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 1
    assert captured.err == ""
    assert payload["category"] == "composition_failed"
    assert "private-composer-marker" not in captured.out
    assert "RuntimeError" not in captured.out
    assert "Traceback" not in captured.out


def test_unexpected_postcondition_failure_is_sanitized(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = _script()
    configuration, _, repository, _, _ = _install_safe_composition(
        monkeypatch,
        script,
    )
    monkeypatch.setattr(
        script,
        "_load_application_configuration",
        lambda path: configuration,
    )

    async def fail_inspection(*args, **kwargs):
        raise RuntimeError("private-postcondition-marker")

    monkeypatch.setattr(repository, "list_cases", fail_inspection)

    exit_code = script.main(["--live", "--config", "ignored", "--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 1
    assert captured.err == ""
    assert payload["category"] == "unexpected_error"
    assert "private-postcondition-marker" not in captured.out
    assert SECRET_ENDPOINT not in captured.out
    assert SECRET_MODEL not in captured.out
    assert script.FIXED_FICTIONAL_INTAKE not in captured.out
    assert "RuntimeError" not in captured.out
    assert "Traceback" not in captured.out


def test_unexpected_result_emission_failure_uses_sanitized_fallback(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = _script()
    monkeypatch.setattr(
        script,
        "_load_application_configuration",
        lambda path: _configuration(script),
    )
    monkeypatch.setattr(
        script,
        "_print_result",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("private-serialization-marker")
        ),
    )

    exit_code = script.main(["--check", "--config", "ignored", "--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 1
    assert captured.err == ""
    assert payload["category"] == "unexpected_error"
    assert "private-serialization-marker" not in captured.out
    assert "RuntimeError" not in captured.out
    assert "Traceback" not in captured.out


def test_smoke_uses_shared_composer_without_local_service_construction() -> None:
    script = _script()
    source = inspect.getsource(script.run_application_foundry_smoke)

    assert "compose_application(" in source
    assert "CaseProcessingService(" not in source
    assert "create_ai_service(" not in source
    assert "create_case_repository(" not in source
    assert "create_email_notification_sender(" not in source
    assert "create_sms_notification_sender(" not in source


def test_final_receipt_revocation_stops_before_processing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = _script()
    receipt_checks: list[object] = []
    client = RecordingFoundryClient()
    configuration, _, repository, email_sender, sms_sender = (
        _install_safe_composition(
            monkeypatch,
            script,
            client=client,
        )
    )
    monkeypatch.setattr(
        script,
        "load_matching_daily_azure_readiness_receipt",
        lambda path, config: receipt_checks.append(config) or None,
    )

    result = script.run_application_foundry_smoke(configuration)

    assert result.ok is False
    assert result.category == "readiness_receipt_invalid"
    assert client.calls == []
    assert asyncio.run(repository.list_cases()) == []
    assert email_sender.sent_notifications == []
    assert sms_sender.sent_notifications == []
    assert receipt_checks == [configuration.daily_config]
    assert result.foundry_invocation_attempted is False


def test_authoritative_readiness_validator_is_used_initially_and_before_inference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = _script()
    config = SimpleNamespace(model_deployment_name="fictional-model")
    receipt = SimpleNamespace(
        foundry_account_name="fictional-account",
        foundry_project_name="fictional-project",
    )
    receipt_checks: list[object] = []
    monkeypatch.setattr(
        script,
        "load_daily_azure_config",
        lambda path, repository_root: config,
    )
    monkeypatch.setattr(
        script,
        "load_matching_daily_azure_readiness_receipt",
        lambda path, checked_config: receipt_checks.append(checked_config) or receipt,
    )
    loaded = script._load_application_configuration("ignored")
    from src.app.services import (
        ai_service_factory,
        email_notification_sender_factory,
        nurse_intake_agent_factory,
        repository_factory,
        sms_notification_sender_factory,
    )

    client = RecordingFoundryClient()
    monkeypatch.setattr(
        ai_service_factory,
        "create_ai_service",
        lambda settings: _foundry_service(client),
    )
    monkeypatch.setattr(
        nurse_intake_agent_factory,
        "create_optional_nurse_intake_agent",
        lambda settings: None,
    )
    monkeypatch.setattr(
        repository_factory,
        "create_case_repository",
        lambda settings: InMemoryCaseRepository(),
    )
    monkeypatch.setattr(
        email_notification_sender_factory,
        "create_email_notification_sender",
        lambda settings: MockEmailNotificationSender(),
    )
    monkeypatch.setattr(
        sms_notification_sender_factory,
        "create_sms_notification_sender",
        lambda settings: MockSmsNotificationSender(),
    )

    result = script.run_application_foundry_smoke(loaded)

    assert result.ok is True
    assert receipt_checks == [config, config]
    assert len(client.calls) == 1
