from types import SimpleNamespace


def test_mock_agent_preflight_reports_ready() -> None:
    from src.app.services.nurse_intake_agent_preflight import (
        build_nurse_intake_agent_status,
    )

    status = build_nurse_intake_agent_status(
        SimpleNamespace(
            agent_provider_normalized="mock",
            azure_ai_foundry_agent_project_endpoint=None,
            azure_ai_foundry_agent_endpoint=None,
            azure_ai_foundry_agent_use_project_endpoint_compatibility=False,
            azure_ai_foundry_project_endpoint=None,
            azure_ai_foundry_agent_id=None,
            azure_ai_foundry_agent_name=None,
            azure_ai_foundry_agent_version=None,
        )
    )

    assert status.provider == "mock"
    assert status.ready is True
    assert status.mode == "mock"
    assert status.missingSettings == []


def test_foundry_agent_preflight_reports_missing_settings() -> None:
    from src.app.services.nurse_intake_agent_preflight import (
        build_nurse_intake_agent_status,
    )

    status = build_nurse_intake_agent_status(
        SimpleNamespace(
            agent_provider_normalized="foundry-agent",
            azure_ai_foundry_agent_project_endpoint=None,
            azure_ai_foundry_agent_endpoint=None,
            azure_ai_foundry_agent_use_project_endpoint_compatibility=False,
            azure_ai_foundry_project_endpoint=None,
            azure_ai_foundry_agent_id=None,
            azure_ai_foundry_agent_name=None,
            azure_ai_foundry_agent_version=None,
        )
    )

    assert status.provider == "foundry-agent"
    assert status.ready is False
    assert status.mode == "configuration-only"
    assert status.missingSettings == [
        "AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT",
        "AZURE_AI_FOUNDRY_AGENT_ENDPOINT",
        "AZURE_AI_FOUNDRY_AGENT_NAME",
        "AZURE_AI_FOUNDRY_AGENT_VERSION",
    ]


def test_foundry_agent_preflight_reports_ready_when_required_settings_present() -> None:
    from src.app.services.nurse_intake_agent_preflight import (
        build_nurse_intake_agent_status,
    )

    status = build_nurse_intake_agent_status(
        SimpleNamespace(
            agent_provider_normalized="foundry-agent",
            azure_ai_foundry_agent_project_endpoint=(
                "https://fictional-foundry.services.ai.azure.com/api/projects/demo"
            ),
            azure_ai_foundry_agent_endpoint=(
                "https://fictional-foundry.services.ai.azure.com/api/projects/demo/"
                "agents/fictional-agent-name/endpoint/protocols/openai"
            ),
            azure_ai_foundry_agent_use_project_endpoint_compatibility=False,
            azure_ai_foundry_project_endpoint=None,
            azure_ai_foundry_agent_id=None,
            azure_ai_foundry_agent_name="fictional-agent-name",
            azure_ai_foundry_agent_version="2",
        )
    )

    assert status.provider == "foundry-agent"
    assert status.ready is True
    assert status.mode == "configuration-only"
    assert status.missingSettings == []


def test_foundry_agent_preflight_requires_stable_agent_endpoint() -> None:
    from src.app.services.nurse_intake_agent_preflight import (
        build_nurse_intake_agent_status,
    )

    status = build_nurse_intake_agent_status(
        SimpleNamespace(
            agent_provider_normalized="foundry-agent",
            azure_ai_foundry_agent_project_endpoint=None,
            azure_ai_foundry_agent_endpoint=None,
            azure_ai_foundry_agent_use_project_endpoint_compatibility=False,
            azure_ai_foundry_project_endpoint=(
                "https://fictional-foundry.services.ai.azure.com/api/projects/demo"
            ),
            azure_ai_foundry_agent_id=None,
            azure_ai_foundry_agent_name="fictional-agent-name",
            azure_ai_foundry_agent_version="2",
        )
    )

    assert status.ready is False
    assert status.missingSettings == [
        "AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT",
        "AZURE_AI_FOUNDRY_AGENT_ENDPOINT",
    ]


def test_stable_endpoint_never_hides_missing_project_endpoint() -> None:
    from src.app.services.nurse_intake_agent_preflight import (
        build_nurse_intake_agent_status,
    )

    status = build_nurse_intake_agent_status(
        SimpleNamespace(
            agent_provider_normalized="foundry-agent",
            azure_ai_foundry_agent_project_endpoint=None,
            azure_ai_foundry_agent_endpoint=(
                "https://fictional.services.ai.azure.com/api/projects/demo/agents/"
                "nurse-intake/endpoint/protocols/openai"
            ),
            azure_ai_foundry_agent_use_project_endpoint_compatibility=False,
            azure_ai_foundry_agent_name="nurse-intake",
            azure_ai_foundry_agent_version="7",
        )
    )

    assert status.ready is False
    assert status.missingSettings == ["AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT"]
    assert all(name.startswith("AZURE_") for name in status.missingSettings)


def test_explicit_compatibility_mode_is_ready_without_stable_endpoint() -> None:
    from src.app.services.nurse_intake_agent_preflight import (
        build_nurse_intake_agent_status,
    )

    status = build_nurse_intake_agent_status(
        SimpleNamespace(
            agent_provider_normalized="foundry-agent",
            azure_ai_foundry_agent_project_endpoint=(
                "https://fictional.services.ai.azure.com/api/projects/demo"
            ),
            azure_ai_foundry_agent_endpoint=None,
            azure_ai_foundry_agent_use_project_endpoint_compatibility=True,
            azure_ai_foundry_agent_name="nurse-intake",
            azure_ai_foundry_agent_version="7",
        )
    )

    assert status.ready is True
    assert status.missingSettings == []


def test_missing_compatibility_attribute_does_not_enable_compatibility() -> None:
    from src.app.services.nurse_intake_agent_preflight import (
        build_nurse_intake_agent_status,
    )

    status = build_nurse_intake_agent_status(
        SimpleNamespace(
            agent_provider_normalized="foundry-agent",
            azure_ai_foundry_agent_project_endpoint=(
                "https://fictional.services.ai.azure.com/api/projects/demo"
            ),
            azure_ai_foundry_agent_endpoint=None,
            azure_ai_foundry_agent_name="nurse-intake",
            azure_ai_foundry_agent_version="7",
        )
    )

    assert status.ready is False
    assert status.missingSettings == ["AZURE_AI_FOUNDRY_AGENT_ENDPOINT"]


def test_agent_preflight_does_not_probe_foundry_sdk(
    monkeypatch,
) -> None:
    from src.app.services import foundry_agent_client
    from src.app.services.nurse_intake_agent_preflight import (
        build_nurse_intake_agent_status,
    )

    monkeypatch.setattr(
        foundry_agent_client,
        "foundry_agent_sdk_available",
        lambda: (_ for _ in ()).throw(AssertionError("SDK probe should not run")),
    )

    status = build_nurse_intake_agent_status(
        SimpleNamespace(
            agent_provider_normalized="foundry-agent",
            azure_ai_foundry_agent_project_endpoint=(
                "https://fictional-foundry.services.ai.azure.com/api/projects/demo"
            ),
            azure_ai_foundry_agent_endpoint=(
                "https://fictional-foundry.services.ai.azure.com/api/projects/demo/"
                "agents/fictional-agent-name/endpoint/protocols/openai"
            ),
            azure_ai_foundry_agent_use_project_endpoint_compatibility=False,
            azure_ai_foundry_project_endpoint=None,
            azure_ai_foundry_agent_id=None,
            azure_ai_foundry_agent_name="fictional-agent-name",
            azure_ai_foundry_agent_version="2",
        )
    )

    assert status.ready is True
