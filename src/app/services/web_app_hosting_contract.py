from types import MappingProxyType
from typing import Final, Mapping

from src.app.services.foundry_agent_client import (
    is_valid_stable_agent_endpoint,
    stable_agent_endpoint_matches_configuration,
)


SAFE_HOSTED_SETTINGS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "APP_MODE": "mock",
        "AI_PROVIDER": "mock",
        "AGENT_PROVIDER": "mock",
        "SPEECH_PROVIDER": "mock",
        "EMAIL_PROVIDER": "mock",
        "SMS_PROVIDER": "mock",
        "DEMO_SUPPRESS_NOTIFICATIONS": "true",
    }
)
REMOTE_BUILD_SETTING: Final = "SCM_DO_BUILD_DURING_DEPLOYMENT"
REMOTE_BUILD_VALUE: Final = "true"

HOSTED_VERIFIER_BICEP_PROPERTIES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT": "projectEndpoint",
        "AZURE_AI_FOUNDRY_AGENT_ENDPOINT": "agentEndpoint",
        "AZURE_AI_FOUNDRY_AGENT_NAME": "agentName",
        "AZURE_AI_FOUNDRY_AGENT_VERSION": "agentVersion",
        "AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT_NAME": (
            "modelDeploymentName"
        ),
    }
)
HOSTED_VERIFIER_BICEP_PARAMETERS: Final = HOSTED_VERIFIER_BICEP_PROPERTIES
HOSTED_VERIFIER_SETTING_NAMES: Final = tuple(HOSTED_VERIFIER_BICEP_PROPERTIES)


def hosted_verifier_settings_valid(values: Mapping[str, object]) -> bool:
    """Validate the exact non-secret settings consumed by the hosted verifier."""

    if set(values) != set(HOSTED_VERIFIER_SETTING_NAMES):
        return False
    if not all(
        isinstance(value, str)
        and bool(value)
        and value == value.strip()
        and len(value) <= 2048
        and not any(character in value for character in "\x00\r\n\t")
        for value in values.values()
    ):
        return False

    project_endpoint = values["AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT"]
    stable_endpoint = values["AZURE_AI_FOUNDRY_AGENT_ENDPOINT"]
    agent_name = values["AZURE_AI_FOUNDRY_AGENT_NAME"]
    agent_version = values["AZURE_AI_FOUNDRY_AGENT_VERSION"]
    model_name = values["AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT_NAME"]
    if not all(
        isinstance(value, str) and len(value) <= 256
        for value in (agent_name, agent_version, model_name)
    ):
        return False
    return bool(
        is_valid_stable_agent_endpoint(stable_endpoint)
        and stable_agent_endpoint_matches_configuration(
            project_endpoint=project_endpoint,
            stable_agent_endpoint=stable_endpoint,
            agent_name=agent_name,
        )
    )
