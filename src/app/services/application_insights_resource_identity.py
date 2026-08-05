from dataclasses import dataclass
import hashlib
import json
import re
import secrets
from uuid import UUID


APPLICATION_INSIGHTS_PROVIDER = "Microsoft.Insights"
APPLICATION_INSIGHTS_RESOURCE_TYPE = "components"
_FINGERPRINT = re.compile(r"[0-9a-f]{64}")
_RUN_EPOCH = re.compile(r"[0-9a-f]{32}")
_RESOURCE_NAME = re.compile(
    r"[A-Za-z0-9](?:[A-Za-z0-9._-]{0,258}[A-Za-z0-9])?"
)


@dataclass(frozen=True, repr=False)
class ApplicationInsightsResourceIdentity:
    component_name: str
    resource_id: str
    fingerprint: str

    def to_private_json_dict(self) -> dict[str, str]:
        return {
            "component_name": self.component_name,
            "resource_id": self.resource_id,
            "fingerprint": self.fingerprint,
        }


@dataclass(frozen=True, repr=False)
class _ParsedArmIdentity:
    subscription_id: str
    resource_group: str
    provider: str
    resource_type: str
    component_name: str


def build_application_insights_resource_identity(
    *,
    component_name: object,
    resource_id: object,
    subscription_id: object,
    resource_group: object,
    configuration_fingerprint: object,
    run_epoch: object,
) -> ApplicationInsightsResourceIdentity | None:
    parsed = _parse_exact_arm_identity(resource_id)
    if (
        parsed is None
        or not _exact_component_name(component_name)
        or not _uuid(subscription_id)
        or not _resource_group(resource_group)
        or not _fingerprint(configuration_fingerprint)
        or not _run_epoch(run_epoch)
        or parsed.subscription_id.casefold() != str(subscription_id).casefold()
        or parsed.resource_group.casefold() != str(resource_group).casefold()
        or parsed.provider.casefold() != APPLICATION_INSIGHTS_PROVIDER.casefold()
        or parsed.resource_type.casefold()
        != APPLICATION_INSIGHTS_RESOURCE_TYPE.casefold()
        or parsed.component_name != component_name
    ):
        return None
    canonical_subscription = str(UUID(str(subscription_id))).casefold()
    fingerprint = _identity_fingerprint(
        subscription_id=canonical_subscription,
        resource_group=parsed.resource_group.casefold(),
        component_name=str(component_name),
        resource_id=str(resource_id),
        configuration_fingerprint=str(configuration_fingerprint),
        run_epoch=str(run_epoch),
    )
    return ApplicationInsightsResourceIdentity(
        component_name=str(component_name),
        resource_id=str(resource_id),
        fingerprint=fingerprint,
    )


def validate_application_insights_resource_identity(
    identity: object,
    *,
    subscription_id: object | None,
    resource_group: object,
    configuration_fingerprint: object,
    run_epoch: object,
) -> bool:
    if not isinstance(identity, ApplicationInsightsResourceIdentity):
        return False
    parsed = _parse_exact_arm_identity(identity.resource_id)
    if parsed is None:
        return False
    expected_subscription = (
        parsed.subscription_id if subscription_id is None else subscription_id
    )
    rebuilt = build_application_insights_resource_identity(
        component_name=identity.component_name,
        resource_id=identity.resource_id,
        subscription_id=expected_subscription,
        resource_group=resource_group,
        configuration_fingerprint=configuration_fingerprint,
        run_epoch=run_epoch,
    )
    return rebuilt is not None and _constant_time_equal(
        identity.fingerprint,
        rebuilt.fingerprint,
    )


def parse_application_insights_resource_identity(
    payload: object,
    *,
    subscription_id: object | None,
    resource_group: object,
    configuration_fingerprint: object,
    run_epoch: object,
) -> ApplicationInsightsResourceIdentity | None:
    if (
        not isinstance(payload, dict)
        or set(payload) != {"component_name", "resource_id", "fingerprint"}
        or not _fingerprint(payload.get("fingerprint"))
    ):
        return None
    parsed = _parse_exact_arm_identity(payload.get("resource_id"))
    if parsed is None:
        return None
    expected_subscription = (
        parsed.subscription_id if subscription_id is None else subscription_id
    )
    identity = ApplicationInsightsResourceIdentity(
        component_name=payload["component_name"],
        resource_id=payload["resource_id"],
        fingerprint=payload["fingerprint"],
    )
    return (
        identity
        if validate_application_insights_resource_identity(
            identity,
            subscription_id=expected_subscription,
            resource_group=resource_group,
            configuration_fingerprint=configuration_fingerprint,
            run_epoch=run_epoch,
        )
        else None
    )


def application_insights_identity_subscription_id(
    identity: ApplicationInsightsResourceIdentity,
) -> str | None:
    parsed = _parse_exact_arm_identity(identity.resource_id)
    return parsed.subscription_id if parsed is not None else None


def application_insights_component_name_valid(value: object) -> bool:
    return _exact_component_name(value)


def _identity_fingerprint(
    *,
    subscription_id: str,
    resource_group: str,
    component_name: str,
    resource_id: str,
    configuration_fingerprint: str,
    run_epoch: str,
) -> str:
    canonical = {
        "application_insights": {
            "subscription_id": subscription_id,
            "resource_group": resource_group,
            "provider": APPLICATION_INSIGHTS_PROVIDER.casefold(),
            "resource_type": APPLICATION_INSIGHTS_RESOURCE_TYPE.casefold(),
            "component_name": component_name,
            "resource_id": resource_id,
        },
        "configuration_fingerprint": configuration_fingerprint,
        "run_epoch": run_epoch,
    }
    return hashlib.sha256(
        json.dumps(canonical, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def _parse_exact_arm_identity(value: object) -> _ParsedArmIdentity | None:
    if not isinstance(value, str) or value != value.strip():
        return None
    parts = value.split("/")
    if (
        len(parts) != 9
        or parts[0] != ""
        or parts[1].casefold() != "subscriptions"
        or not _uuid(parts[2])
        or parts[3].casefold() != "resourcegroups"
        or not _resource_group(parts[4])
        or parts[5].casefold() != "providers"
        or not parts[6]
        or not parts[7]
        or not _exact_component_name(parts[8])
    ):
        return None
    return _ParsedArmIdentity(
        subscription_id=parts[2],
        resource_group=parts[4],
        provider=parts[6],
        resource_type=parts[7],
        component_name=parts[8],
    )


def _uuid(value: object) -> bool:
    if not isinstance(value, str) or value != value.strip():
        return False
    try:
        return str(UUID(value)).casefold() == value.casefold()
    except (ValueError, AttributeError):
        return False


def _resource_group(value: object) -> bool:
    return bool(
        isinstance(value, str)
        and value == value.strip()
        and re.fullmatch(r"[A-Za-z0-9._()\-]{1,90}", value)
        and not value.endswith(".")
    )


def _exact_component_name(value: object) -> bool:
    return bool(
        isinstance(value, str)
        and value == value.strip()
        and _RESOURCE_NAME.fullmatch(value)
    )


def _fingerprint(value: object) -> bool:
    return isinstance(value, str) and _FINGERPRINT.fullmatch(value) is not None


def _run_epoch(value: object) -> bool:
    return isinstance(value, str) and _RUN_EPOCH.fullmatch(value) is not None


def _constant_time_equal(left: object, right: object) -> bool:
    return bool(
        isinstance(left, str)
        and isinstance(right, str)
        and len(left) == len(right)
        and secrets.compare_digest(left, right)
    )
