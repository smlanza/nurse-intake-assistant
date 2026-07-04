from src.app.config.settings import AppSettings
from src.app.services.nurse_intake_agent import MockNurseIntakeAgent, NurseIntakeAgent


class NurseIntakeAgentProviderNotImplementedError(RuntimeError):
    """Raised for future agent providers that are intentionally not wired yet."""


def create_nurse_intake_agent(settings: AppSettings) -> NurseIntakeAgent:
    """Select the configured nurse intake agent boundary."""

    provider = settings.agent_provider_normalized

    if provider == "mock":
        return MockNurseIntakeAgent()

    if provider == "foundry-agent":
        raise NurseIntakeAgentProviderNotImplementedError(
            "Azure AI Foundry Agent orchestration is not wired yet."
        )

    raise ValueError(f"Unsupported AGENT_PROVIDER: {settings.agent_provider}")
