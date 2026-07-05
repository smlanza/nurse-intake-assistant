from typing import Any

from pydantic import BaseModel


class NurseIntakeAgentStatus(BaseModel):
    provider: str
    ready: bool
    mode: str
    missingSettings: list[str]


def build_nurse_intake_agent_status(settings: Any) -> NurseIntakeAgentStatus:
    """Report agent provider readiness without creating live clients."""

    provider = _settings_value(settings, "agent_provider_normalized", "mock")

    if provider == "mock":
        return NurseIntakeAgentStatus(
            provider="mock",
            ready=True,
            mode="mock",
            missingSettings=[],
        )

    if provider == "foundry-agent":
        missing_settings = _missing_foundry_agent_settings(settings)
        return NurseIntakeAgentStatus(
            provider="foundry-agent",
            ready=not missing_settings,
            mode="configuration-only",
            missingSettings=missing_settings,
        )

    return NurseIntakeAgentStatus(
        provider=provider,
        ready=False,
        mode="unsupported",
        missingSettings=[],
    )


def _missing_foundry_agent_settings(settings: Any) -> list[str]:
    missing_settings: list[str] = []
    project_endpoint = _settings_value(
        settings,
        "azure_ai_foundry_agent_project_endpoint",
    ) or _settings_value(settings, "azure_ai_foundry_project_endpoint")
    agent_id = _settings_value(settings, "azure_ai_foundry_agent_id")

    if project_endpoint is None:
        missing_settings.append("AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT")
    if agent_id is None:
        missing_settings.append("AZURE_AI_FOUNDRY_AGENT_ID")

    return missing_settings


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
