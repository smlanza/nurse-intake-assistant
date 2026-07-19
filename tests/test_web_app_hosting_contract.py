from src.app.config.settings import AppSettings
from src.app.services.hosted_foundry_agent_verification import (
    build_hosted_foundry_agent_verification_request,
)
from src.app.services.web_app_hosting_contract import (
    HOSTED_VERIFIER_SETTING_NAMES,
    hosted_verifier_settings_valid,
)


SETTINGS = {
    "AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT": (
        "https://fictional.services.ai.azure.com/api/projects/demo"
    ),
    "AZURE_AI_FOUNDRY_AGENT_ENDPOINT": (
        "https://fictional.services.ai.azure.com/api/projects/demo/agents/"
        "fictional-agent/endpoint/protocols/openai"
    ),
    "AZURE_AI_FOUNDRY_AGENT_NAME": "fictional-agent",
    "AZURE_AI_FOUNDRY_AGENT_VERSION": "7",
    "AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT_NAME": "fictional-model",
}


def test_exact_five_settings_map_from_environment_to_existing_verifier_request(
    monkeypatch,
) -> None:
    for name, value in SETTINGS.items():
        monkeypatch.setenv(name, value)

    request = build_hosted_foundry_agent_verification_request(
        AppSettings(),
        mode="check",
    )

    assert tuple(HOSTED_VERIFIER_SETTING_NAMES) == tuple(SETTINGS)
    assert request.project_endpoint == SETTINGS[
        "AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT"
    ]
    assert request.stable_agent_endpoint == SETTINGS[
        "AZURE_AI_FOUNDRY_AGENT_ENDPOINT"
    ]
    assert request.agent_name == SETTINGS["AZURE_AI_FOUNDRY_AGENT_NAME"]
    assert request.agent_version == SETTINGS["AZURE_AI_FOUNDRY_AGENT_VERSION"]
    assert request.model_deployment_name == SETTINGS[
        "AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT_NAME"
    ]
    assert hosted_verifier_settings_valid(SETTINGS) is True


def test_missing_blank_extra_or_mismatched_settings_fail_closed() -> None:
    mutations = (
        {name: value for name, value in SETTINGS.items() if "VERSION" not in name},
        {**SETTINGS, "AZURE_AI_FOUNDRY_AGENT_VERSION": ""},
        {**SETTINGS, "EXTRA_SETTING": "unsafe"},
        {**SETTINGS, "AZURE_AI_FOUNDRY_AGENT_NAME": "different-agent"},
    )

    assert all(not hosted_verifier_settings_valid(values) for values in mutations)
