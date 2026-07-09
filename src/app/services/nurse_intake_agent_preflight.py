from typing import Any

from pydantic import BaseModel


FOUNDRY_AGENT_CONFIGURATION_ONLY_WARNING = (
    "Foundry Agent readiness is configuration-only; live Azure validation was not attempted."
)
FOUNDRY_AGENT_MANUAL_VALIDATION_COMMAND = (
    "python scripts/smoke_foundry_agent.py "
    "--env-file .env.foundry-agent.local --live --json"
)
UNSUPPORTED_AGENT_PROVIDER_WARNING = (
    "Unsupported AGENT_PROVIDER; restore AGENT_PROVIDER=mock for local demo readiness."
)


class NurseIntakeAgentStatus(BaseModel):
    provider: str
    ready: bool
    mode: str
    missingSettings: list[str]


class AgentProviderStatus(BaseModel):
    provider: str
    configured: bool
    liveValidation: str
    manualValidationAvailable: bool
    manualValidationCommand: str | None
    missingSettings: list[str]
    warnings: list[str]


def build_nurse_intake_agent_status(settings: Any) -> NurseIntakeAgentStatus:
    """Report agent provider readiness without creating live clients."""

    provider = _safe_agent_provider(
        _settings_value(settings, "agent_provider_normalized", "mock")
    )

    if provider == "mock":
        return NurseIntakeAgentStatus(
            provider="mock",
            ready=True,
            mode="mock",
            missingSettings=[],
        )

    if provider in {"foundry", "foundry-agent"}:
        missing_settings = _missing_foundry_agent_settings(settings)
        return NurseIntakeAgentStatus(
            provider=provider,
            ready=not missing_settings,
            mode="configuration-only",
            missingSettings=missing_settings,
        )

    return NurseIntakeAgentStatus(
        provider="unsupported",
        ready=False,
        mode="unsupported",
        missingSettings=[],
    )


def build_agent_provider_status(settings: Any) -> AgentProviderStatus:
    """Report safe structured agent provider readiness for demo status."""

    provider = _safe_agent_provider(
        _settings_value(settings, "agent_provider_normalized", "mock")
    )

    if provider == "mock":
        return AgentProviderStatus(
            provider="mock",
            configured=True,
            liveValidation="not_attempted",
            manualValidationAvailable=False,
            manualValidationCommand=None,
            missingSettings=[],
            warnings=[],
        )

    if provider in {"foundry", "foundry-agent"}:
        missing_settings = _missing_foundry_agent_provider_settings(settings)
        return AgentProviderStatus(
            provider=provider,
            configured=not missing_settings,
            liveValidation="not_attempted",
            manualValidationAvailable=True,
            manualValidationCommand=FOUNDRY_AGENT_MANUAL_VALIDATION_COMMAND,
            missingSettings=missing_settings,
            warnings=[FOUNDRY_AGENT_CONFIGURATION_ONLY_WARNING],
        )

    return AgentProviderStatus(
        provider="unsupported",
        configured=False,
        liveValidation="not_attempted",
        manualValidationAvailable=False,
        manualValidationCommand=None,
        missingSettings=[],
        warnings=[UNSUPPORTED_AGENT_PROVIDER_WARNING],
    )


def _missing_foundry_agent_settings(settings: Any) -> list[str]:
    missing_settings: list[str] = []
    project_endpoint = _settings_value(
        settings,
        "azure_ai_foundry_agent_project_endpoint",
    )
    agent_name = _settings_value(settings, "azure_ai_foundry_agent_name")
    agent_version = _settings_value(settings, "azure_ai_foundry_agent_version")

    if project_endpoint is None:
        missing_settings.append("AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT")
    if agent_name is None:
        missing_settings.append("AZURE_AI_FOUNDRY_AGENT_NAME")
    if agent_version is None:
        missing_settings.append("AZURE_AI_FOUNDRY_AGENT_VERSION")

    return missing_settings


def _missing_foundry_agent_provider_settings(settings: Any) -> list[str]:
    missing_settings: list[str] = []
    project_endpoint = _settings_value(
        settings,
        "azure_ai_foundry_agent_project_endpoint",
    )
    agent_name = _settings_value(settings, "azure_ai_foundry_agent_name")
    agent_version = _settings_value(settings, "azure_ai_foundry_agent_version")

    if project_endpoint is None:
        missing_settings.append("AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT")
    if agent_name is None:
        missing_settings.append("AZURE_AI_FOUNDRY_AGENT_NAME")
    if agent_version is None:
        missing_settings.append("AZURE_AI_FOUNDRY_AGENT_VERSION")

    return missing_settings


def _safe_agent_provider(provider: str | None) -> str:
    if provider in {"mock", "foundry", "foundry-agent"}:
        return provider
    return "unsupported"


def _settings_value(
    settings: Any,
    name: str,
    default: str | None = None,
) -> str | None:
    value = getattr(settings, name, default)
    if isinstance(value, str):
        stripped_value = value.strip()
        if name.endswith("_normalized"):
            return stripped_value.lower() or default
        return stripped_value or default
    return value
