from dataclasses import FrozenInstanceError
import json
from pathlib import Path

import pytest

from src.app.services.application_insights_resource_identity import (
    ApplicationInsightsResourceIdentity,
    build_application_insights_resource_identity,
    parse_application_insights_resource_identity,
    validate_application_insights_resource_identity,
)
from src.app.services import web_app_infra_deployment


SUBSCRIPTION_ID = "11111111-1111-4111-8111-111111111111"
RESOURCE_GROUP = "fictional-daily-rg"
COMPONENT_NAME = "fictional-intake-appi"
RESOURCE_ID = (
    f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/{RESOURCE_GROUP}/"
    f"providers/Microsoft.Insights/components/{COMPONENT_NAME}"
)
CONFIGURATION_FINGERPRINT = "a" * 64
RUN_EPOCH = "b" * 32


def _identity(**changes: object) -> ApplicationInsightsResourceIdentity | None:
    values: dict[str, object] = {
        "component_name": COMPONENT_NAME,
        "resource_id": RESOURCE_ID,
        "subscription_id": SUBSCRIPTION_ID,
        "resource_group": RESOURCE_GROUP,
        "configuration_fingerprint": CONFIGURATION_FINGERPRINT,
        "run_epoch": RUN_EPOCH,
    }
    values.update(changes)
    return build_application_insights_resource_identity(**values)


def test_valid_exact_identity_is_immutable_and_private() -> None:
    identity = _identity()

    assert identity is not None
    assert validate_application_insights_resource_identity(
        identity,
        subscription_id=SUBSCRIPTION_ID,
        resource_group=RESOURCE_GROUP,
        configuration_fingerprint=CONFIGURATION_FINGERPRINT,
        run_epoch=RUN_EPOCH,
    )
    assert COMPONENT_NAME not in repr(identity)
    assert RESOURCE_ID not in repr(identity)
    assert identity.fingerprint not in repr(identity)
    with pytest.raises(FrozenInstanceError):
        identity.component_name = "changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    "changes",
    [
        {"component_name": "different-component"},
        {"subscription_id": "22222222-2222-4222-8222-222222222222"},
        {"resource_group": "different-rg"},
        {
            "resource_id": RESOURCE_ID.replace(
                "Microsoft.Insights", "Microsoft.OperationalInsights"
            )
        },
        {"resource_id": RESOURCE_ID.replace("/components/", "/workspaces/")},
        {"resource_id": RESOURCE_ID.replace(COMPONENT_NAME, "different-component")},
        {"resource_id": RESOURCE_ID + "/extra"},
        {"resource_id": RESOURCE_ID.rsplit("/", 1)[0]},
        {"component_name": f" {COMPONENT_NAME}"},
        {"resource_id": f"{RESOURCE_ID} "},
    ],
)
def test_invalid_or_contradictory_identity_is_rejected(
    changes: dict[str, object],
) -> None:
    assert _identity(**changes) is None


def test_fingerprint_is_deterministic_and_every_bound_field_matters() -> None:
    first = _identity()
    second = _identity()

    assert first is not None and second is not None
    assert first.fingerprint == second.fingerprint
    variants = (
        _identity(component_name="fictional-intake-appi-two", resource_id=RESOURCE_ID.replace(COMPONENT_NAME, "fictional-intake-appi-two")),
        _identity(resource_group="fictional-other-rg", resource_id=RESOURCE_ID.replace(RESOURCE_GROUP, "fictional-other-rg")),
        _identity(configuration_fingerprint="c" * 64),
        _identity(run_epoch="d" * 32),
    )
    assert all(item is not None for item in variants)
    assert all(item.fingerprint != first.fingerprint for item in variants if item)


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        {"component_name": COMPONENT_NAME, "resource_id": RESOURCE_ID},
        {
            "component_name": COMPONENT_NAME,
            "resource_id": RESOURCE_ID,
            "fingerprint": "c" * 64,
            "unknown": True,
        },
        {
            "component_name": None,
            "resource_id": RESOURCE_ID,
            "fingerprint": "c" * 64,
        },
    ],
)
def test_unknown_or_malformed_private_shapes_fail_closed(payload: object) -> None:
    assert parse_application_insights_resource_identity(
        payload,
        subscription_id=SUBSCRIPTION_ID,
        resource_group=RESOURCE_GROUP,
        configuration_fingerprint=CONFIGURATION_FINGERPRINT,
        run_epoch=RUN_EPOCH,
    ) is None


def test_fingerprint_never_enters_public_serialization() -> None:
    identity = _identity()
    assert identity is not None

    public = {
        "application_insights_identity_verified": True,
        "application_insights_identity_bound_to_receipt": True,
    }

    assert identity.fingerprint not in str(public)
    assert COMPONENT_NAME not in str(public)
    assert RESOURCE_ID not in str(public)


class _DeploymentRunner:
    def __init__(self, *payloads: object) -> None:
        self.payloads = list(payloads)
        self.calls: list[list[str]] = []

    def run(self, args: list[str]):
        self.calls.append(args)
        return web_app_infra_deployment.CommandResult(
            0,
            json.dumps(self.payloads.pop(0)),
            "",
        )


def _deployment_request() -> web_app_infra_deployment.WebAppInfrastructureDeploymentRequest:
    root = Path(__file__).resolve().parents[1]
    return web_app_infra_deployment.WebAppInfrastructureDeploymentRequest(
        mode="check",
        resource_group=RESOURCE_GROUP,
        location="centralus",
        environment_name="daily",
        project_name="nurse-intake",
        web_app_name="fictional-web-app",
        cosmos_database_name="nurse-intake",
        cosmos_container_name="cases",
        template_file=root / "infra/main.bicep",
    )


def test_authoritative_named_deployment_outputs_build_exact_identity() -> None:
    runner = _DeploymentRunner(
        {"componentName": COMPONENT_NAME},
        {
            "id": RESOURCE_ID,
            "name": COMPONENT_NAME,
            "type": "microsoft.insights/components",
        },
    )

    identity = web_app_infra_deployment.read_application_insights_deployment_identity(
        _deployment_request(),
        subscription_id=SUBSCRIPTION_ID,
        configuration_fingerprint=CONFIGURATION_FINGERPRINT,
        run_epoch=RUN_EPOCH,
        runner=runner,
    )

    assert identity is not None
    assert len(runner.calls) == 2
    assert runner.calls[0][:4] == ["az", "deployment", "group", "show"]
    assert runner.calls[1][:3] == ["az", "resource", "show"]
    assert all(call[:3] != ["az", "resource", "list"] for call in runner.calls)


@pytest.mark.parametrize(
    "payload",
    [
        [],
        None,
        {},
        {"componentName": COMPONENT_NAME, "extra": True},
        {"componentName": "contradictory"},
    ],
)
def test_authoritative_deployment_output_unknown_shapes_fail_closed(
    payload: object,
) -> None:
    runner = _DeploymentRunner(
        payload,
        {
            "id": RESOURCE_ID,
            "name": COMPONENT_NAME,
            "type": "Microsoft.Insights/components",
        },
    )

    assert web_app_infra_deployment.read_application_insights_deployment_identity(
        _deployment_request(),
        subscription_id=SUBSCRIPTION_ID,
        configuration_fingerprint=CONFIGURATION_FINGERPRINT,
        run_epoch=RUN_EPOCH,
        runner=runner,
    ) is None
