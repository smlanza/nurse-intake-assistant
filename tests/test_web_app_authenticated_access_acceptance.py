import json

import pytest


PRIVATE_ORIGIN = "https://private-authenticated-host.example"
PRIVATE_IDENTITY = "operator@example.invalid"
PRIVATE_TOKEN = "private-token-value"
PRIVATE_COOKIE = "private-session-cookie"


def _evidence(**overrides: object):
    from src.app.services.web_app_authenticated_access_acceptance import (
        InteractiveAuthenticationEvidence,
    )

    values: dict[str, object] = {
        "hosted_origin": PRIVATE_ORIGIN,
        "ready_current": True,
        "exact_web_app_artifact_current": True,
        "authentication_configuration_current": True,
        "runtime_perimeter_current": True,
    }
    values.update(overrides)
    return InteractiveAuthenticationEvidence(**values)


@pytest.mark.parametrize(
    "missing_proof",
    ("authentication_configuration_current", "runtime_perimeter_current"),
)
def test_acceptance_refuses_missing_authentication_proof_before_checkpoint(
    missing_proof: str,
) -> None:
    from src.app.services.web_app_authenticated_access_acceptance import (
        accept_authenticated_application_access,
    )

    result = accept_authenticated_application_access(
        _evidence(**{missing_proof: False}),
        operator_checkpoint=lambda _prompt: pytest.fail(
            "invalid proof must stop before interactive acceptance"
        ),
    )

    assert result.ok is False
    assert result.category == "authenticated_acceptance_blocked"
    assert result.reason == "authentication_evidence_invalid"
    assert result.interactive_sign_in_attempts == 0
    assert result.authenticated_protected_get_attempts == 0


def test_verified_checkpoint_is_fixed_to_one_get_demo_and_is_sanitized() -> None:
    from src.app.services.web_app_authenticated_access_acceptance import (
        FIXED_PROTECTED_METHOD,
        FIXED_PROTECTED_ROUTE,
        accept_authenticated_application_access,
    )

    prompts: list[object] = []

    def checkpoint(prompt: object) -> str:
        prompts.append(prompt)
        assert prompt.method == "GET"
        assert prompt.route == "/demo"
        assert prompt.target_url == f"{PRIVATE_ORIGIN}/demo"
        return "verified"

    result = accept_authenticated_application_access(
        _evidence(),
        operator_checkpoint=checkpoint,
    )

    assert FIXED_PROTECTED_METHOD == "GET"
    assert FIXED_PROTECTED_ROUTE == "/demo"
    assert len(prompts) == 1
    assert result.ok is True
    assert result.category == "authenticated_application_access_verified"
    assert result.interactive_sign_in_attempts == 1
    assert result.authenticated_protected_get_attempts == 1
    assert result.application_mutations == 0
    assert result.retries is False
    payload = json.dumps(result.to_json_dict())
    assert PRIVATE_ORIGIN not in payload
    assert PRIVATE_IDENTITY not in payload
    assert PRIVATE_TOKEN not in payload
    assert PRIVATE_COOKIE not in payload
    assert "target_url" not in payload


def test_cancelled_interactive_checkpoint_fails_safely_without_retry() -> None:
    from src.app.services.web_app_authenticated_access_acceptance import (
        accept_authenticated_application_access,
    )

    checkpoints = 0

    def cancel(_prompt: object) -> str:
        nonlocal checkpoints
        checkpoints += 1
        return "cancelled"

    result = accept_authenticated_application_access(
        _evidence(),
        operator_checkpoint=cancel,
    )

    assert checkpoints == 1
    assert result.ok is False
    assert result.category == "interactive_sign_in_cancelled"
    assert result.interactive_sign_in_attempts == 1
    assert result.authenticated_protected_get_attempts == 0
    assert result.application_mutations == 0
    assert result.retries is False
