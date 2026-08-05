from dataclasses import fields, replace
import hashlib
import json
import os
from pathlib import Path

from src.app.services.application_insights_resource_identity import (
    build_application_insights_resource_identity,
)
from src.app.services import daily_azure_environment_rebuild as service


def test_receipt_schema_requires_private_application_insights_identity() -> None:
    assert service.READINESS_RECEIPT_SCHEMA_VERSION == 5
    assert "application_insights_identity" in {
        field.name for field in fields(service.DailyAzureReadinessReceipt)
    }


def test_legacy_receipt_without_identity_is_contract_incompatible(
    tmp_path: Path,
) -> None:
    config = service.DailyAzureConfig(
        subscription_name="Fictional Development",
        location="eastus2",
        resource_group="fictional-daily-rg",
        environment_name="daily",
        project_name="nurse-intake",
        foundry_account_name="fictional-intake-foundry",
        foundry_project_name="fictional-intake-project",
        model_deployment_name="fictional-model",
        model_name="gpt-5-mini",
        model_version="2025-08-07",
        model_sku="GlobalStandard",
        model_capacity=1,
        agent_name="fictional-agent",
        web_app_name="fictional-web-app",
        web_app_sku="B1",
        enable_hosted_foundry_verifier=True,
        discover_hosted_foundry_webjob=True,
    )
    receipt_path = tmp_path / service.READINESS_RECEIPT_FILE
    receipt_path.parent.mkdir(parents=True)
    run_epoch = "b" * 32
    configuration_fingerprint = service.daily_azure_configuration_fingerprint(config)
    state = service.DailyAzureReadinessState(
        schema_version=service.READINESS_STATE_SCHEMA_VERSION,
        operation=service.REBUILD_OPERATION,
        configuration_fingerprint=configuration_fingerprint,
        run_epoch=run_epoch,
        state="ready",
    )
    service.write_daily_azure_readiness_state(
        service.daily_azure_readiness_state_path(receipt_path, config),
        state,
    )
    correlation_values = {
        "configuration_fingerprint": configuration_fingerprint,
        "run_epoch": run_epoch,
        "requested_foundry_account_name": config.foundry_account_name,
        "foundry_account_name": config.foundry_account_name,
        "foundry_account_name_generated": False,
        "foundry_account_name_generation_attempts": 0,
        "foundry_account_name_conflicts": [],
        "resource_group": config.resource_group,
        "foundry_project_name": config.foundry_project_name,
        "web_app_name": config.web_app_name,
    }
    legacy = {
        "schema_version": 4,
        "operation": service.REBUILD_OPERATION,
        "ready": True,
        "correlation_fingerprint": hashlib.sha256(
            json.dumps(
                correlation_values,
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
        ).hexdigest(),
        **correlation_values,
    }
    receipt_path.write_text(json.dumps(legacy))

    assert service.load_matching_daily_azure_readiness_receipt(receipt_path, config) is None


def _config() -> service.DailyAzureConfig:
    return service.DailyAzureConfig(
        subscription_name="Fictional Development",
        location="eastus2",
        resource_group="fictional-daily-rg",
        environment_name="daily",
        project_name="nurse-intake",
        foundry_account_name="fictional-intake-foundry",
        foundry_project_name="fictional-intake-project",
        model_deployment_name="fictional-model",
        model_name="gpt-5-mini",
        model_version="2025-08-07",
        model_sku="GlobalStandard",
        model_capacity=1,
        agent_name="fictional-agent",
        web_app_name="fictional-web-app",
        web_app_sku="B1",
        enable_hosted_foundry_verifier=True,
        discover_hosted_foundry_webjob=True,
    )


def _context(config: service.DailyAzureConfig) -> service.DailyAzureRuntimeContext:
    return service.DailyAzureRuntimeContext(
        resource_group=config.resource_group,
        location=config.location,
        foundry_account_name=config.foundry_account_name,
        foundry_project_name=config.foundry_project_name,
        project_endpoint="https://fictional.invalid/api/projects/fictional",
        model_deployment_name=config.model_deployment_name,
        agent_name=config.agent_name,
        immutable_agent_version="1",
        stable_agent_endpoint="https://fictional.invalid/agents/one",
        web_app_name=config.web_app_name,
        hosted_origin="https://fictional.invalid",
        configured_foundry_account_name=config.foundry_account_name,
    )


def _identity(
    config: service.DailyAzureConfig,
    run_epoch: str,
    *,
    component_name: str = "fictional-intake-appi",
):
    subscription_id = "11111111-1111-4111-8111-111111111111"
    resource_id = (
        f"/subscriptions/{subscription_id}/resourceGroups/"
        f"{config.resource_group}/providers/Microsoft.Insights/"
        f"components/{component_name}"
    )
    identity = build_application_insights_resource_identity(
        component_name=component_name,
        resource_id=resource_id,
        subscription_id=subscription_id,
        resource_group=config.resource_group,
        configuration_fingerprint=service.daily_azure_configuration_fingerprint(config),
        run_epoch=run_epoch,
    )
    assert identity is not None
    return identity


def _write_compatible_receipt(tmp_path: Path):
    config = _config()
    run_epoch = "d" * 32
    receipt = service.build_daily_azure_readiness_receipt(
        config,
        _context(config),
        run_epoch,
        application_insights_identity=_identity(config, run_epoch),
    )
    path = tmp_path / service.READINESS_RECEIPT_FILE
    service.write_daily_azure_readiness_receipt(path, receipt)
    service.write_daily_azure_readiness_state(
        service.daily_azure_readiness_state_path(path, config),
        service.DailyAzureReadinessState(
            schema_version=service.READINESS_STATE_SCHEMA_VERSION,
            operation=service.REBUILD_OPERATION,
            configuration_fingerprint=receipt.configuration_fingerprint,
            run_epoch=receipt.run_epoch,
            state="ready",
        ),
    )
    return config, receipt, path


def test_compatible_receipt_round_trips_private_identity_with_restrictive_permissions(
    tmp_path: Path,
) -> None:
    config, receipt, path = _write_compatible_receipt(tmp_path)

    loaded = service.load_matching_daily_azure_readiness_receipt(path, config)

    assert loaded is not None
    assert loaded.to_json_dict() == receipt.to_json_dict()
    assert loaded.application_insights_identity == receipt.application_insights_identity
    assert os.stat(path).st_mode & 0o777 == 0o600


def test_replaced_identity_or_fingerprint_fails_closed(tmp_path: Path) -> None:
    config, receipt, path = _write_compatible_receipt(tmp_path)
    replacement = _identity(
        config,
        receipt.run_epoch,
        component_name="fictional-intake-appi-two",
    )
    payload = json.loads(path.read_text())
    payload["application_insights_identity"] = replacement.to_private_json_dict()
    path.write_text(json.dumps(payload))

    assert service.load_matching_daily_azure_readiness_receipt(path, config) is None

    payload = receipt.to_json_dict()
    payload["application_insights_identity"]["fingerprint"] = "0" * 64
    path.write_text(json.dumps(payload))
    assert service.load_matching_daily_azure_readiness_receipt(path, config) is None


def test_unknown_identity_field_and_stale_correlations_fail_closed(
    tmp_path: Path,
) -> None:
    config, receipt, path = _write_compatible_receipt(tmp_path)
    payload = receipt.to_json_dict()
    payload["application_insights_identity"]["unknown"] = True
    path.write_text(json.dumps(payload))
    assert service.load_matching_daily_azure_readiness_receipt(path, config) is None

    service.write_daily_azure_readiness_receipt(path, receipt)
    stale = replace(config, location="centralus")
    assert service.load_matching_daily_azure_readiness_receipt(path, stale) is None


def test_public_ready_result_contains_only_identity_booleans() -> None:
    result = service.DailyAzureEnvironmentRebuildResult(
        ok=False,
        category="application_insights_identity_invalid",
        mode="live",
        application_insights_identity_verified=False,
        application_insights_identity_bound_to_receipt=False,
    ).to_json_dict()

    serialized = json.dumps(result, sort_keys=True)
    assert result["application_insights_identity_verified"] is False
    assert result["application_insights_identity_bound_to_receipt"] is False
    for forbidden in (
        "fictional-intake-appi",
        "/subscriptions/",
        "fingerprint",
        "resource_id",
        "component_name",
    ):
        assert forbidden not in serialized
