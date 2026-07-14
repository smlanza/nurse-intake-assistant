import asyncio
import json
from types import SimpleNamespace

import pytest


STABLE_ENDPOINT = (
    "https://fictional.services.ai.azure.com/api/projects/demo/agents/"
    "nurse-intake/endpoint/protocols/openai"
)
PROJECT_ENDPOINT = "https://fictional.services.ai.azure.com/api/projects/demo"


def _client_settings(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "agent_provider_normalized": "foundry-agent",
        "azure_ai_foundry_agent_endpoint": STABLE_ENDPOINT,
        "azure_ai_foundry_agent_use_project_endpoint_compatibility": False,
        "azure_ai_foundry_agent_project_endpoint": PROJECT_ENDPOINT,
        "azure_ai_foundry_agent_name": "nurse-intake",
        "azure_ai_foundry_agent_version": "7",
        "azure_ai_foundry_managed_identity_client_id": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _agent_details(
    *,
    identity: object | None = None,
    endpoint: object | None = None,
) -> SimpleNamespace:
    if identity is None:
        identity = SimpleNamespace(client_id="safe-presence-only")
    if endpoint is None:
        endpoint = SimpleNamespace(
            version_selector=SimpleNamespace(
                version_selection_rules=[
                    SimpleNamespace(
                        type="FixedRatio",
                        agent_version="7",
                        traffic_percentage=100,
                    )
                ]
            ),
            protocols=["responses"],
        )
    return SimpleNamespace(
        id="agent-object-id",
        name="nurse-intake",
        instance_identity=identity,
        agent_endpoint=endpoint,
    )


def _agent_version() -> SimpleNamespace:
    from src.app.services.nurse_intake_agent_instructions import (
        build_nurse_intake_agent_instructions,
    )

    return SimpleNamespace(
        id="agent-version-id",
        name="nurse-intake",
        version="7",
        definition=SimpleNamespace(
            model="gpt-demo",
            instructions=build_nurse_intake_agent_instructions(),
        ),
    )


def _verification_request(**overrides: object):
    from src.app.services.foundry_agent_verification import (
        FoundryAgentVerificationRequest,
    )
    from src.app.services.nurse_intake_agent_instructions import (
        build_nurse_intake_agent_instructions,
    )

    values: dict[str, object] = {
        "project_endpoint": PROJECT_ENDPOINT,
        "stable_agent_endpoint": STABLE_ENDPOINT,
        "agent_name": "nurse-intake",
        "agent_version": "7",
        "model_deployment_name": "gpt-demo",
        "instructions": build_nurse_intake_agent_instructions(),
    }
    values.update(overrides)
    return FoundryAgentVerificationRequest(**values)


class _FakeAgents:
    def __init__(self, details: SimpleNamespace) -> None:
        self.details = details
        self.get_calls: list[str] = []
        self.get_version_calls: list[tuple[str, str]] = []

    def get(self, agent_name: str) -> SimpleNamespace:
        self.get_calls.append(agent_name)
        return self.details

    def get_version(self, agent_name: str, agent_version: str) -> SimpleNamespace:
        self.get_version_calls.append((agent_name, agent_version))
        return _agent_version()


def _verify(details: SimpleNamespace):
    from src.app.services.foundry_agent_verification import FoundryAgentVerification

    agents = _FakeAgents(details)
    service = FoundryAgentVerification(
        project_client_factory=lambda endpoint: SimpleNamespace(agents=agents)
    )
    return service.verify(_verification_request()), agents


def test_valid_new_model_agent_metadata_and_immutable_version_are_accepted() -> None:
    result, agents = _verify(_agent_details())

    assert result.ok is True
    assert result.category == "success"
    assert result.agent_identity_present is True
    assert result.stable_endpoint_present is True
    assert result.stable_endpoint_matches_configuration is True
    assert result.version_selector_present is True
    assert result.configured_version_traffic_percentage == 100
    assert result.responses_protocol_present is True
    assert result.immutable_version_verified is True
    assert agents.get_calls == ["nurse-intake"]
    assert agents.get_version_calls == [("nurse-intake", "7")]


def test_null_agent_instance_identity_is_categorized_as_legacy_safely() -> None:
    details = _agent_details()
    details.instance_identity = None
    result, _ = _verify(details)

    payload = json.dumps(result.to_json_dict())
    assert result.ok is False
    assert result.category == "legacy_agent_model"
    assert result.agent_identity_present is False
    assert result.stable_endpoint_present is True
    assert result.stable_endpoint_matches_configuration is True
    assert result.version_selector_present is True
    assert result.responses_protocol_present is True
    assert result.configured_version_traffic_percentage == 100
    assert result.immutable_version_verified is False
    assert "recreated" in result.recommended_next_step
    assert "safe-presence-only" not in payload
    assert PROJECT_ENDPOINT not in payload


def test_missing_remote_agent_endpoint_metadata_is_rejected_safely() -> None:
    details = _agent_details()
    details.agent_endpoint = None

    result, _ = _verify(details)

    assert result.ok is False
    assert result.category == "stable_endpoint_missing"
    assert result.agent_identity_present is True
    assert result.stable_endpoint_present is False
    assert result.stable_endpoint_matches_configuration is False


def test_identity_ids_are_never_serialized_when_identity_is_present() -> None:
    details = _agent_details(
        identity=SimpleNamespace(
            client_id="secret-client-id",
            principal_id="secret-principal-id",
        )
    )

    result, _ = _verify(details)

    payload = json.dumps(result.to_json_dict())
    assert result.ok is True
    assert result.agent_identity_present is True
    assert "secret-client-id" not in payload
    assert "secret-principal-id" not in payload


def test_configured_version_must_receive_all_endpoint_traffic() -> None:
    details = _agent_details()
    details.agent_endpoint.version_selector.version_selection_rules = [
        SimpleNamespace(
            type="FixedRatio",
            agent_version="8",
            traffic_percentage=100,
        )
    ]

    result, agents = _verify(details)

    assert result.ok is False
    assert result.category == "version_routing_mismatch"
    assert result.version_selector_present is True
    assert result.configured_version_traffic_percentage is None
    assert result.immutable_version_verified is False
    assert agents.get_version_calls == []


def _rule(version: object, traffic: object, *, rule_type: object = "FixedRatio"):
    return SimpleNamespace(
        type=rule_type,
        agent_version=version,
        traffic_percentage=traffic,
    )


def test_exclusive_routing_helper_accepts_one_configured_version_at_100() -> None:
    from src.app.services.foundry_agent_verification import (
        validate_exclusive_immutable_version_routing,
    )

    result = validate_exclusive_immutable_version_routing([_rule("7", 100)], "7")

    assert result.valid is True
    assert result.configured_version_traffic_percentage == 100


@pytest.mark.parametrize(
    ("rules", "expected_configured_traffic"),
    [
        ([_rule("7", 50), _rule("8", 50)], 50),
        ([_rule("7", 100), _rule("8", 1)], 100),
        ([_rule("7", 0), _rule("8", 100)], 0),
        ([_rule("8", 100)], None),
        ([], None),
        ([SimpleNamespace(type="FixedRatio", agent_version="7")], None),
        ([_rule("7", -1)], None),
        ([_rule("7", 101)], None),
        ([_rule("7", 99)], 99),
        ([_rule("7", 100), _rule("8", 0), _rule("9", 1)], 100),
        ([_rule("7", 100, rule_type="Unsupported")], None),
        ([object()], None),
        ([_rule("7", 50), _rule("7", 50)], 50),
    ],
)
def test_exclusive_routing_helper_fails_closed(
    rules: list[object],
    expected_configured_traffic: int | None,
) -> None:
    from src.app.services.foundry_agent_verification import (
        validate_exclusive_immutable_version_routing,
    )

    result = validate_exclusive_immutable_version_routing(rules, "7")

    assert result.valid is False
    assert (
        result.configured_version_traffic_percentage
        == expected_configured_traffic
    )


def test_routing_mismatch_diagnostics_do_not_serialize_remote_values() -> None:
    details = _agent_details()
    details.agent_endpoint.version_selector.version_selection_rules = [
        _rule("secret-configured-version", 50),
        _rule("secret-other-version", 50),
    ]

    result, _ = _verify_with_request(
        details,
        _verification_request(agent_version="secret-configured-version"),
    )

    payload = json.dumps(result.to_json_dict())
    assert result.category == "version_routing_mismatch"
    assert result.configured_version_traffic_percentage == 50
    assert "secret-configured-version" not in payload
    assert "secret-other-version" not in payload


def test_compatibility_verification_does_not_claim_stable_routing() -> None:
    result, agents = _verify_with_request(
        _agent_details(),
        _verification_request(stable_agent_endpoint=None),
    )

    assert result.ok is True
    assert result.agent_definition_matches is True
    assert result.configured_version_traffic_percentage is None
    assert result.immutable_version_verified is False
    assert agents.get_calls == []
    assert agents.get_version_calls == [("nurse-intake", "7")]


@pytest.mark.parametrize(
    ("stable_endpoint", "expected_category"),
    [
        (
            "https://fictional.services.ai.azure.com/api/projects/demo/agents/"
            "other-agent/endpoint/protocols/openai",
            "stable_endpoint_mismatch",
        ),
        (
            "https://fictional.services.ai.azure.com/api/projects/other/agents/"
            "nurse-intake/endpoint/protocols/openai",
            "stable_endpoint_mismatch",
        ),
        (
            "https://other.services.ai.azure.com/api/projects/demo/agents/"
            "nurse-intake/endpoint/protocols/openai",
            "stable_endpoint_mismatch",
        ),
        (
            "https://fictional.services.ai.azure.com/api/projects/demo/agents/"
            "%6eurse-intake/endpoint/protocols/openai",
            "stable_endpoint_invalid",
        ),
        (
            "https://fictional.services.ai.azure.com/api/projects/demo/agents//"
            "nurse-intake/endpoint/protocols/openai",
            "stable_endpoint_invalid",
        ),
    ],
)
def test_verification_rejects_endpoint_not_bound_to_configured_agent(
    stable_endpoint: str,
    expected_category: str,
) -> None:
    result, _ = _verify_with_request(
        _agent_details(),
        _verification_request(stable_agent_endpoint=stable_endpoint),
    )

    payload = json.dumps(result.to_json_dict())
    assert result.ok is False
    assert result.category == expected_category
    assert result.stable_endpoint_matches_configuration is False
    assert stable_endpoint not in payload


def _verify_with_request(details: SimpleNamespace, request: object):
    from src.app.services.foundry_agent_verification import FoundryAgentVerification

    agents = _FakeAgents(details)
    service = FoundryAgentVerification(
        project_client_factory=lambda endpoint: SimpleNamespace(agents=agents)
    )
    return service.verify(request), agents


def test_endpoint_binding_accepts_harmless_trailing_slashes() -> None:
    from src.app.services.foundry_agent_client import (
        stable_agent_endpoint_matches_configuration,
    )

    assert stable_agent_endpoint_matches_configuration(
        project_endpoint=f"{PROJECT_ENDPOINT}/",
        stable_agent_endpoint=f"{STABLE_ENDPOINT}/",
        agent_name="nurse-intake",
    ) is True


@pytest.mark.parametrize(
    "stable_endpoint",
    [
        STABLE_ENDPOINT.replace("nurse-intake", "other-agent"),
        STABLE_ENDPOINT.replace("/projects/demo/", "/projects/other/"),
        STABLE_ENDPOINT.replace("fictional.services", "other.services"),
        STABLE_ENDPOINT.replace("nurse-intake", "%6eurse-intake"),
        STABLE_ENDPOINT.replace("/agents/", "/agents//"),
        STABLE_ENDPOINT.replace("/agents/", "/agents/../agents/"),
    ],
)
def test_endpoint_binding_rejects_mismatched_or_ambiguous_paths(
    stable_endpoint: str,
) -> None:
    from src.app.services.foundry_agent_client import (
        stable_agent_endpoint_matches_configuration,
    )

    assert stable_agent_endpoint_matches_configuration(
        project_endpoint=PROJECT_ENDPOINT,
        stable_agent_endpoint=stable_endpoint,
        agent_name="nurse-intake",
    ) is False


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://fictional.example/agents/demo/endpoint/protocols/openai",
        "not-a-url",
        "https://fictional.example/openai/v1",
        "https://user:password@fictional.example/agents/demo/endpoint/protocols/openai",
    ],
)
def test_malformed_or_non_https_stable_endpoint_is_rejected_before_sdk_use(
    endpoint: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.services import foundry_agent_client
    from src.app.services.foundry_agent_client import FoundryAgentClientError

    monkeypatch.setattr(
        foundry_agent_client,
        "foundry_agent_sdk_available",
        lambda: pytest.fail("invalid endpoint must fail before SDK inspection"),
    )

    with pytest.raises(FoundryAgentClientError) as exc:
        foundry_agent_client.create_foundry_agent_client(
            _client_settings(azure_ai_foundry_agent_endpoint=endpoint),
            enable_live=True,
        )

    assert exc.value.category == "stable_endpoint_invalid"
    assert endpoint not in str(exc.value)


def test_stable_endpoint_is_preferred_when_compatibility_is_also_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.services import foundry_agent_client

    monkeypatch.setattr(foundry_agent_client, "foundry_agent_sdk_available", lambda: True)

    client = foundry_agent_client.create_foundry_agent_client(
        _client_settings(
            azure_ai_foundry_agent_use_project_endpoint_compatibility=True
        ),
        enable_live=True,
    )

    assert client.stable_agent_endpoint == STABLE_ENDPOINT
    assert client.invocation_mode == "stable_agent_endpoint"


def test_stable_mode_missing_project_endpoint_fails_before_sdk_or_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.services import foundry_agent_client
    from src.app.services.foundry_agent_client import FoundryAgentClientError

    monkeypatch.setattr(
        foundry_agent_client,
        "foundry_agent_sdk_available",
        lambda: pytest.fail("missing project endpoint must fail before SDK inspection"),
    )
    monkeypatch.setattr(
        foundry_agent_client,
        "FoundryCredentialFactory",
        lambda *args, **kwargs: pytest.fail(
            "missing project endpoint must not construct a credential factory"
        ),
    )

    with pytest.raises(FoundryAgentClientError) as exc:
        foundry_agent_client.create_foundry_agent_client(
            _client_settings(azure_ai_foundry_agent_project_endpoint=None),
            enable_live=True,
        )

    assert exc.value.category == "foundry-agent-missing-configuration"
    assert "AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT" in str(exc.value)


def test_project_endpoint_requires_intentional_compatibility_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.services import foundry_agent_client
    from src.app.services.foundry_agent_client import FoundryAgentClientError

    monkeypatch.setattr(foundry_agent_client, "foundry_agent_sdk_available", lambda: True)
    settings = _client_settings(azure_ai_foundry_agent_endpoint=None)

    with pytest.raises(FoundryAgentClientError) as exc:
        foundry_agent_client.create_foundry_agent_client(settings, enable_live=True)

    assert exc.value.category == "stable_endpoint_missing"

    settings.azure_ai_foundry_agent_use_project_endpoint_compatibility = True
    client = foundry_agent_client.create_foundry_agent_client(
        settings,
        enable_live=True,
    )
    assert client.invocation_mode == "project_endpoint_compatibility"


def test_missing_compatibility_attribute_does_not_enable_project_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.services import foundry_agent_client
    from src.app.services.foundry_agent_client import FoundryAgentClientError

    monkeypatch.setattr(foundry_agent_client, "foundry_agent_sdk_available", lambda: True)
    settings = _client_settings(azure_ai_foundry_agent_endpoint=None)
    del settings.azure_ai_foundry_agent_use_project_endpoint_compatibility

    with pytest.raises(FoundryAgentClientError) as exc:
        foundry_agent_client.create_foundry_agent_client(settings, enable_live=True)

    assert exc.value.category == "stable_endpoint_missing"


def test_stable_endpoint_client_uses_shared_credential_and_sdk_agent_name() -> None:
    from src.app.services import foundry_agent_client
    from src.app.services.foundry_credential_factory import FoundryCredentialFactory

    calls: list[dict[str, object]] = []
    credential = object()

    class FakeProjectClient:
        def __init__(self, *, endpoint, credential, allow_preview):
            calls.append(
                {
                    "sdk_endpoint": endpoint,
                    "credential": credential,
                    "allow_preview": allow_preview,
                }
            )

        def get_openai_client(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(responses=object())

    client = foundry_agent_client._create_stable_responses_client(
        stable_agent_endpoint=STABLE_ENDPOINT,
        agent_name="nurse-intake",
        project_endpoint=PROJECT_ENDPOINT,
        managed_identity_client_id="user-assigned-secret-id",
        credential_factory=FoundryCredentialFactory(
            credential_constructor=lambda **kwargs: calls.append(kwargs) or credential
        ),
        project_client_class=FakeProjectClient,
    )

    assert client.responses is not None
    assert calls[0] == {"managed_identity_client_id": "user-assigned-secret-id"}
    assert calls[1]["credential"] is credential
    assert calls[1]["sdk_endpoint"] == PROJECT_ENDPOINT
    assert calls[1]["allow_preview"] is True
    assert calls[2] == {"agent_name": "nurse-intake"}
    assert "base_url" not in calls[2]
    assert "default_query" not in calls[2]
    assert "agentVersion" not in calls[2]
    assert "user-assigned-secret-id" not in json.dumps(
        {"category": "success", "client_created": True}
    )


def test_stable_endpoint_success_parses_through_existing_application_contract() -> None:
    from src.app.services.foundry_agent_client import (
        AzureAiFoundryAgentLiveClient,
        FoundryAgentRequest,
    )
    from src.app.services.foundry_agent_contract import (
        normalize_foundry_agent_intake_response,
    )

    content = json.dumps(
        {
            "extraction": {
                "patient": {
                    "name": "Fictional Patient",
                    "date_of_birth": None,
                    "callback_number": None,
                },
                "reason_for_calling": "fictional refill",
                "symptoms": [],
                "summary": "Fictional refill request.",
                "missing_fields": ["date_of_birth", "callback_number"],
                "uncertain_fields": [],
                "extraction_notes": "Fictional test input only.",
            },
            "urgency": {
                "urgency": "Routine",
                "urgency_rationale": "No urgent symptoms were reported.",
                "advisory_disclaimer": "Nurse review is required.",
            },
        }
    )
    client = AzureAiFoundryAgentLiveClient(
        stable_agent_endpoint=STABLE_ENDPOINT,
        project_endpoint=PROJECT_ENDPOINT,
        agent_name="nurse-intake",
        agent_version="7",
    )
    client._responses_client = SimpleNamespace(
        responses=SimpleNamespace(create=lambda **kwargs: SimpleNamespace(output_text=content))
    )

    response = asyncio.run(
        client.invoke_agent(
            FoundryAgentRequest(
                intake_text="Fictional intake.",
                instructions="Return JSON only.",
            )
        )
    )
    normalized = normalize_foundry_agent_intake_response(response.content)

    assert normalized.extraction.summary == "Fictional refill request."
    assert normalized.urgency.urgency == "Routine"
    assert response.metadata["endpointMode"] == "stable_agent_endpoint"


@pytest.mark.parametrize(
    "error",
    [
        RuntimeError("Bearer secret-token authentication failure"),
        RuntimeError("403 authorization raw-body"),
        RuntimeError("timeout https://secret.example"),
    ],
)
def test_stable_endpoint_request_failures_are_sanitized(error: Exception) -> None:
    from src.app.services.foundry_agent_client import (
        AzureAiFoundryAgentLiveClient,
        FoundryAgentClientError,
        FoundryAgentRequest,
    )

    def fail(**kwargs: object) -> None:
        raise error

    client = AzureAiFoundryAgentLiveClient(
        stable_agent_endpoint=STABLE_ENDPOINT,
        project_endpoint=PROJECT_ENDPOINT,
        agent_name="nurse-intake",
        agent_version="7",
    )
    client._responses_client = SimpleNamespace(
        responses=SimpleNamespace(create=fail)
    )

    with pytest.raises(FoundryAgentClientError) as exc:
        asyncio.run(
            client.invoke_agent(
                FoundryAgentRequest(
                    intake_text="Fictional intake.",
                    instructions="Return JSON only.",
                )
            )
        )

    assert exc.value.category == "stable_endpoint_request_failed"
    assert "secret" not in str(exc.value)
    assert "token" not in str(exc.value).lower()


def test_guarded_smoke_success_reports_stable_endpoint_and_immutable_version() -> None:
    import scripts.smoke_foundry_agent_intake as script
    from src.app.services.foundry_agent_verification import (
        FoundryAgentVerificationResult,
    )

    result = script.ApplicationIntakeSmokeResult(
        ok=True,
        mode="live",
        category="success",
        message=script.SAFE_MESSAGES["success"],
        agent_attempted=True,
        agent_output_valid=True,
        fallback_used=False,
        case_saved=True,
        intake_status="Complete",
        review_status="PendingReview",
        urgency_present=True,
        handoff_note_present=True,
        processing_trace_present=True,
        notifications_suppressed=True,
        recommended_next_step=script.SAFE_NEXT_STEPS["success"],
        extraction_present=True,
        stable_endpoint_used=True,
    )

    payload = script._live_result_payload(
        result,
        verification_requested=True,
        verification_result=FoundryAgentVerificationResult.success(
            agent_identity_present=True,
            stable_endpoint_present=True,
            stable_endpoint_matches_configuration=True,
            version_selector_present=True,
            responses_protocol_present=True,
            configured_version_traffic_percentage=100,
        ),
        invocation_attempted=True,
        application_intake_attempted=True,
    )

    assert payload["stable_endpoint_used"] is True
    assert payload["immutable_version_verified"] is True
    assert payload["notifications_suppressed"] is True
    assert payload["review_status"] == "PendingReview"
    assert payload["expected_safe_output_fields_present"] == [
        "extraction",
        "urgency",
        "handoffNote",
    ]
