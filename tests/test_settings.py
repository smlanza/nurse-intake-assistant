import pytest


def test_demo_suppress_notifications_defaults_to_false(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.app.config.settings import AppSettings

    monkeypatch.delenv("DEMO_SUPPRESS_NOTIFICATIONS", raising=False)

    settings = AppSettings()

    assert settings.demo_suppress_notifications is False


def test_demo_suppress_notifications_reads_true(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.app.config.settings import AppSettings

    monkeypatch.setenv("DEMO_SUPPRESS_NOTIFICATIONS", "true")

    assert AppSettings().demo_suppress_notifications is True


def test_demo_suppress_notifications_reads_false(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.app.config.settings import AppSettings

    monkeypatch.setenv("DEMO_SUPPRESS_NOTIFICATIONS", "false")

    assert AppSettings().demo_suppress_notifications is False


@pytest.mark.parametrize("value", ["1", "true", "yes", "on"])
def test_demo_suppress_notifications_accepts_truthy_values(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    from src.app.config.settings import AppSettings

    monkeypatch.setenv("DEMO_SUPPRESS_NOTIFICATIONS", value)

    assert AppSettings().demo_suppress_notifications is True


@pytest.mark.parametrize("value", ["0", "false", "no", "off"])
def test_demo_suppress_notifications_accepts_falsey_values(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    from src.app.config.settings import AppSettings

    monkeypatch.setenv("DEMO_SUPPRESS_NOTIFICATIONS", value)

    assert AppSettings().demo_suppress_notifications is False


def test_app_mode_defaults_to_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.app.config.settings import AppSettings

    monkeypatch.delenv("APP_MODE", raising=False)

    assert AppSettings().app_mode == "mock"


def test_app_mode_reads_environment_value(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.app.config.settings import AppSettings

    monkeypatch.setenv("APP_MODE", "azure")

    assert AppSettings().app_mode == "azure"


def test_cosmos_settings_use_expected_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.app.config.settings import AppSettings

    monkeypatch.setenv("APP_MODE", "mock")
    monkeypatch.delenv("COSMOS_DATABASE_NAME", raising=False)
    monkeypatch.delenv("COSMOS_CONTAINER_NAME", raising=False)
    monkeypatch.delenv("COSMOS_ENDPOINT", raising=False)
    monkeypatch.delenv("COSMOS_KEY", raising=False)

    settings = AppSettings()

    assert settings.cosmos_database_name == "nurse-intake"
    assert settings.cosmos_container_name == "cases"
    assert settings.cosmos_endpoint is None
    assert settings.cosmos_key is None


def test_mock_mode_does_not_require_cosmos_endpoint_or_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.config.settings import AppSettings
    from src.app.services.case_repository import InMemoryCaseRepository
    from src.app.services.repository_factory import create_case_repository

    monkeypatch.setenv("APP_MODE", "mock")
    monkeypatch.delenv("COSMOS_ENDPOINT", raising=False)
    monkeypatch.delenv("COSMOS_KEY", raising=False)

    repository = create_case_repository(AppSettings())

    assert isinstance(repository, InMemoryCaseRepository)


def test_cosmos_settings_read_and_trim_environment_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.config.settings import AppSettings

    monkeypatch.setenv("COSMOS_DATABASE_NAME", "  intake-db  ")
    monkeypatch.setenv("COSMOS_CONTAINER_NAME", "  intake-cases  ")
    monkeypatch.setenv("COSMOS_ENDPOINT", "  https://example.documents.azure.com  ")
    monkeypatch.setenv("COSMOS_KEY", "  secret-key  ")

    settings = AppSettings()

    assert settings.cosmos_database_name == "intake-db"
    assert settings.cosmos_container_name == "intake-cases"
    assert settings.cosmos_endpoint == "https://example.documents.azure.com"
    assert settings.cosmos_key == "secret-key"


def test_blank_optional_cosmos_settings_are_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.config.settings import AppSettings

    monkeypatch.setenv("COSMOS_ENDPOINT", "   ")
    monkeypatch.setenv("COSMOS_KEY", "   ")

    settings = AppSettings()

    assert settings.cosmos_endpoint is None
    assert settings.cosmos_key is None


def test_email_provider_defaults_to_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.app.config.settings import AppSettings

    monkeypatch.delenv("EMAIL_PROVIDER", raising=False)

    assert AppSettings().email_provider == "mock"


def test_email_provider_reads_environment_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.config.settings import AppSettings

    monkeypatch.setenv("EMAIL_PROVIDER", "  ACS  ")

    assert AppSettings().email_provider == "  ACS  "
    assert AppSettings().email_provider_normalized == "acs"


def test_acs_email_settings_default_to_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.config.settings import AppSettings

    monkeypatch.delenv("ACS_EMAIL_CONNECTION_STRING", raising=False)
    monkeypatch.delenv("ACS_EMAIL_SENDER_ADDRESS", raising=False)
    monkeypatch.delenv("NURSE_NOTIFICATION_EMAIL", raising=False)

    settings = AppSettings()

    assert settings.acs_email_connection_string is None
    assert settings.acs_email_sender_address is None
    assert settings.nurse_notification_email is None


def test_acs_email_settings_trim_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.config.settings import AppSettings

    monkeypatch.setenv("ACS_EMAIL_CONNECTION_STRING", "  endpoint=example  ")
    monkeypatch.setenv("ACS_EMAIL_SENDER_ADDRESS", "  sender@example.com  ")
    monkeypatch.setenv("NURSE_NOTIFICATION_EMAIL", "  nurse@example.com  ")

    settings = AppSettings()

    assert settings.acs_email_connection_string == "endpoint=example"
    assert settings.acs_email_sender_address == "sender@example.com"
    assert settings.nurse_notification_email == "nurse@example.com"


def test_blank_acs_email_settings_are_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.config.settings import AppSettings

    monkeypatch.setenv("ACS_EMAIL_CONNECTION_STRING", "   ")
    monkeypatch.setenv("ACS_EMAIL_SENDER_ADDRESS", "   ")
    monkeypatch.setenv("NURSE_NOTIFICATION_EMAIL", "   ")

    settings = AppSettings()

    assert settings.acs_email_connection_string is None
    assert settings.acs_email_sender_address is None
    assert settings.nurse_notification_email is None


def test_sms_provider_defaults_to_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.app.config.settings import AppSettings

    monkeypatch.delenv("SMS_PROVIDER", raising=False)

    assert AppSettings().sms_provider == "mock"


def test_sms_provider_reads_environment_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.config.settings import AppSettings

    monkeypatch.setenv("SMS_PROVIDER", "  ACS  ")

    assert AppSettings().sms_provider == "  ACS  "
    assert AppSettings().sms_provider_normalized == "acs"


def test_ai_provider_defaults_to_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.app.config.settings import AppSettings

    monkeypatch.delenv("AI_PROVIDER", raising=False)

    settings = AppSettings()

    assert settings.ai_provider == "mock"
    assert settings.ai_provider_normalized == "mock"


def test_ai_provider_reads_environment_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.config.settings import AppSettings

    monkeypatch.setenv("AI_PROVIDER", "  MOCK  ")

    settings = AppSettings()

    assert settings.ai_provider == "  MOCK  "
    assert settings.ai_provider_normalized == "mock"


def test_blank_ai_provider_normalizes_to_mock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.config.settings import AppSettings

    monkeypatch.setenv("AI_PROVIDER", "   ")

    settings = AppSettings()

    assert settings.ai_provider == "   "
    assert settings.ai_provider_normalized == "mock"


def test_foundry_ai_settings_default_to_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.config.settings import AppSettings

    monkeypatch.delenv("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT", raising=False)
    monkeypatch.delenv("AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT_NAME", raising=False)
    monkeypatch.delenv("AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT", raising=False)
    monkeypatch.delenv("AZURE_AI_FOUNDRY_AGENT_ID", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_ENDPOINT", raising=False)

    settings = AppSettings()

    assert settings.azure_ai_foundry_project_endpoint is None
    assert settings.azure_ai_foundry_model_deployment_name is None
    assert settings.azure_ai_foundry_agent_project_endpoint is None
    assert settings.azure_ai_foundry_agent_id is None
    assert settings.azure_openai_endpoint is None


def test_foundry_ai_settings_trim_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.config.settings import AppSettings

    monkeypatch.setenv(
        "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT",
        "  https://example.services.ai.azure.com/api/projects/demo  ",
    )
    monkeypatch.setenv(
        "AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT_NAME",
        "  intake-extraction  ",
    )
    monkeypatch.setenv(
        "AZURE_OPENAI_ENDPOINT",
        "  https://example-openai-resource.openai.azure.com/  ",
    )
    monkeypatch.setenv(
        "AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT",
        "  https://example-agent.services.ai.azure.com/api/projects/demo  ",
    )
    monkeypatch.setenv("AZURE_AI_FOUNDRY_AGENT_ID", "  example-agent-id  ")

    settings = AppSettings()

    assert (
        settings.azure_ai_foundry_project_endpoint
        == "https://example.services.ai.azure.com/api/projects/demo"
    )
    assert settings.azure_ai_foundry_model_deployment_name == "intake-extraction"
    assert (
        settings.azure_openai_endpoint
        == "https://example-openai-resource.openai.azure.com/"
    )
    assert (
        settings.azure_ai_foundry_agent_project_endpoint
        == "https://example-agent.services.ai.azure.com/api/projects/demo"
    )
    assert settings.azure_ai_foundry_agent_id == "example-agent-id"


def test_blank_foundry_ai_settings_are_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.config.settings import AppSettings

    monkeypatch.setenv("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT", "   ")
    monkeypatch.setenv("AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT_NAME", "   ")
    monkeypatch.setenv("AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT", "   ")
    monkeypatch.setenv("AZURE_AI_FOUNDRY_AGENT_ID", "   ")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "   ")

    settings = AppSettings()

    assert settings.azure_ai_foundry_project_endpoint is None
    assert settings.azure_ai_foundry_model_deployment_name is None
    assert settings.azure_ai_foundry_agent_project_endpoint is None
    assert settings.azure_ai_foundry_agent_id is None
    assert settings.azure_openai_endpoint is None


def test_speech_provider_defaults_to_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.app.config.settings import AppSettings

    monkeypatch.delenv("SPEECH_PROVIDER", raising=False)

    settings = AppSettings()

    assert settings.speech_provider == "mock"
    assert settings.speech_provider_normalized == "mock"


def test_blank_speech_provider_normalizes_to_mock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.config.settings import AppSettings

    monkeypatch.setenv("SPEECH_PROVIDER", "   ")

    settings = AppSettings()

    assert settings.speech_provider == "   "
    assert settings.speech_provider_normalized == "mock"


def test_azure_speech_settings_default_to_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.config.settings import AppSettings

    monkeypatch.delenv("AZURE_SPEECH_ENDPOINT", raising=False)
    monkeypatch.delenv("AZURE_SPEECH_REGION", raising=False)

    settings = AppSettings()

    assert settings.azure_speech_endpoint is None
    assert settings.azure_speech_region is None


def test_azure_speech_settings_trim_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.config.settings import AppSettings

    monkeypatch.setenv(
        "AZURE_SPEECH_ENDPOINT",
        "  https://example.cognitiveservices.azure.com  ",
    )
    monkeypatch.setenv("AZURE_SPEECH_REGION", "  eastus  ")

    settings = AppSettings()

    assert settings.azure_speech_endpoint == (
        "https://example.cognitiveservices.azure.com"
    )
    assert settings.azure_speech_region == "eastus"


def test_blank_azure_speech_settings_are_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.config.settings import AppSettings

    monkeypatch.setenv("AZURE_SPEECH_ENDPOINT", "   ")
    monkeypatch.setenv("AZURE_SPEECH_REGION", "   ")

    settings = AppSettings()

    assert settings.azure_speech_endpoint is None
    assert settings.azure_speech_region is None


def test_acs_sms_settings_default_to_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.config.settings import AppSettings

    monkeypatch.delenv("ACS_SMS_CONNECTION_STRING", raising=False)
    monkeypatch.delenv("ACS_SMS_FROM_PHONE_NUMBER", raising=False)
    monkeypatch.delenv("NURSE_NOTIFICATION_PHONE_NUMBER", raising=False)

    settings = AppSettings()

    assert settings.acs_sms_connection_string is None
    assert settings.acs_sms_from_phone_number is None
    assert settings.nurse_notification_phone_number is None


def test_acs_sms_settings_trim_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.config.settings import AppSettings

    monkeypatch.setenv("ACS_SMS_CONNECTION_STRING", "  endpoint=example  ")
    monkeypatch.setenv("ACS_SMS_FROM_PHONE_NUMBER", "  +15555550100  ")
    monkeypatch.setenv("NURSE_NOTIFICATION_PHONE_NUMBER", "  +15555550123  ")

    settings = AppSettings()

    assert settings.acs_sms_connection_string == "endpoint=example"
    assert settings.acs_sms_from_phone_number == "+15555550100"
    assert settings.nurse_notification_phone_number == "+15555550123"


def test_blank_acs_sms_settings_are_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.config.settings import AppSettings

    monkeypatch.setenv("ACS_SMS_CONNECTION_STRING", "   ")
    monkeypatch.setenv("ACS_SMS_FROM_PHONE_NUMBER", "   ")
    monkeypatch.setenv("NURSE_NOTIFICATION_PHONE_NUMBER", "   ")

    settings = AppSettings()

    assert settings.acs_sms_connection_string is None
    assert settings.acs_sms_from_phone_number is None
    assert settings.nurse_notification_phone_number is None
