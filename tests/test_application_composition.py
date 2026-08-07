from types import SimpleNamespace


def _settings() -> SimpleNamespace:
    return SimpleNamespace(demo_suppress_notifications=True)


def test_shared_composer_constructs_dependencies_without_side_effects(
    monkeypatch,
) -> None:
    import src.app.application_composition as composition_module
    from src.app.services import (
        ai_service_factory,
        email_notification_sender_factory,
        intake_telemetry_factory,
        nurse_intake_agent_factory,
        repository_factory,
        secret_provider_factory,
        sms_notification_sender_factory,
    )

    calls: list[str] = []
    ai_service = SimpleNamespace()
    repository = SimpleNamespace()
    email_sender = SimpleNamespace()
    sms_sender = SimpleNamespace()
    telemetry_sink = SimpleNamespace()
    secret_provider = SimpleNamespace()

    monkeypatch.setattr(
        ai_service_factory,
        "create_ai_service",
        lambda settings: calls.append("ai_factory") or ai_service,
    )
    monkeypatch.setattr(
        repository_factory,
        "create_case_repository",
        lambda settings: calls.append("repository_factory") or repository,
    )
    monkeypatch.setattr(
        email_notification_sender_factory,
        "create_email_notification_sender",
        lambda settings: calls.append("email_factory") or email_sender,
    )
    monkeypatch.setattr(
        sms_notification_sender_factory,
        "create_sms_notification_sender",
        lambda settings: calls.append("sms_factory") or sms_sender,
    )
    monkeypatch.setattr(
        nurse_intake_agent_factory,
        "create_optional_nurse_intake_agent",
        lambda settings: calls.append("agent_factory") or None,
    )
    monkeypatch.setattr(
        intake_telemetry_factory,
        "create_intake_telemetry_sink",
        lambda settings: calls.append("telemetry_factory") or telemetry_sink,
    )
    monkeypatch.setattr(
        secret_provider_factory,
        "create_secret_provider",
        lambda settings: calls.append("secret_factory") or secret_provider,
    )

    composition = composition_module.compose_application(_settings())

    assert calls == [
        "ai_factory",
        "agent_factory",
        "repository_factory",
        "email_factory",
        "sms_factory",
        "telemetry_factory",
        "secret_factory",
    ]
    assert composition.ai_service is ai_service
    assert composition.case_repository is repository
    assert composition.email_notification_sender is email_sender
    assert composition.sms_notification_sender is sms_sender
    assert composition.nurse_intake_agent is None
    assert composition.intake_telemetry_sink is telemetry_sink
    assert composition.secret_provider is secret_provider
    assert composition.case_processing_service.ai_service is ai_service
    assert composition.case_processing_service.case_repository is repository
    assert composition.case_processing_service.suppress_notifications is True
    assert composition.case_processing_service.telemetry_sink is telemetry_sink


def test_normal_intake_path_uses_shared_composition() -> None:
    from src.app import dependencies
    from src.app.routes import intake

    assert intake.case_processing_service is dependencies.application.case_processing_service
    assert intake.case_repository is dependencies.application.case_repository


def test_foundry_application_composition_constructs_no_credentials_or_sdk_clients(
    monkeypatch,
) -> None:
    import src.app.application_composition as composition_module
    from src.app.services import (
        email_notification_sender_factory,
        foundry_live_client,
        nurse_intake_agent_factory,
        repository_factory,
        sms_notification_sender_factory,
    )
    from src.app.services.foundry_ai_service import FoundryAiService

    def fail_if_constructed() -> object:
        raise AssertionError("Foundry SDK resources must remain lazy")

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
        nurse_intake_agent_factory,
        "create_optional_nurse_intake_agent",
        lambda settings: None,
    )
    monkeypatch.setattr(
        repository_factory,
        "create_case_repository",
        lambda settings: SimpleNamespace(),
    )
    monkeypatch.setattr(
        email_notification_sender_factory,
        "create_email_notification_sender",
        lambda settings: SimpleNamespace(),
    )
    monkeypatch.setattr(
        sms_notification_sender_factory,
        "create_sms_notification_sender",
        lambda settings: SimpleNamespace(),
    )
    settings = SimpleNamespace(
        ai_provider_normalized="foundry",
        azure_ai_foundry_project_endpoint=(
            "https://example.services.ai.azure.com/api/projects/fictional-project"
        ),
        azure_ai_foundry_model_deployment_name="configured-deployment",
        demo_suppress_notifications=True,
    )

    composition = composition_module.compose_application(settings)

    assert isinstance(composition.ai_service, FoundryAiService)
    assert composition.ai_service.client is None
