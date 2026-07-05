from src.app.config.settings import AppSettings
from src.app.services.nurse_intake_agent import (
    FoundryNurseIntakeAgent,
    MockNurseIntakeAgent,
    NurseIntakeAgent,
)


class NurseIntakeAgentProviderNotImplementedError(RuntimeError):
    """Raised for future agent providers that are intentionally not wired yet."""


def create_nurse_intake_agent(settings: AppSettings) -> NurseIntakeAgent:
    """Select the configured nurse intake agent boundary."""

    provider = settings.agent_provider_normalized

    if provider == "mock":
        return MockNurseIntakeAgent()

    if provider in {"foundry", "foundry-agent"}:
        return FoundryNurseIntakeAgent(settings=settings)

    raise ValueError(f"Unsupported AGENT_PROVIDER: {settings.agent_provider}")


def create_optional_nurse_intake_agent(settings: AppSettings) -> NurseIntakeAgent | None:
    """Return an agent only when a non-mock agent provider is configured."""

    if settings.agent_provider_normalized == "mock":
        return None
    return create_nurse_intake_agent(settings)
