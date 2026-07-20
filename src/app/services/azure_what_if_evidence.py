from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
from typing import Mapping


_ACTIONS = {
    "create": "Create",
    "modify": "Modify",
    "nochange": "NoChange",
    "delete": "Delete",
    "ignore": "Ignore",
    "deploy": "Deploy",
    "unsupported": "Unsupported",
}


@dataclass(frozen=True)
class ExpectedWhatIfResource:
    resource_type: str
    logical_category: str
    resource_group: str
    name_segments: tuple[str, ...]


@dataclass(frozen=True)
class WhatIfResourceIdentity:
    resource_type: str
    resource_group: str
    name_segments: tuple[str, ...]


@dataclass(frozen=True)
class SanitizedWhatIfChange:
    action: str
    resource_type: str
    logical_category: str
    boundary: str
    approved_boundary: bool
    expected_identity_match: bool = False
    expected_parent_match: bool = False
    expected_scope_match: bool = False
    expected_multiplicity_match: bool = False

    def to_json_dict(self) -> dict[str, object]:
        return {
            "action": self.action,
            "resource_type": self.resource_type,
            "logical_category": self.logical_category,
            "boundary": self.boundary,
            "approved_boundary": self.approved_boundary,
            "expected_identity_match": self.expected_identity_match,
            "expected_parent_match": self.expected_parent_match,
            "expected_scope_match": self.expected_scope_match,
            "expected_multiplicity_match": self.expected_multiplicity_match,
        }


@dataclass(frozen=True)
class SanitizedWhatIfSummary:
    changes: tuple[SanitizedWhatIfChange, ...]
    exact_topology_match: bool = False

    @property
    def all_changes_allowlisted(self) -> bool:
        return bool(
            self.exact_topology_match
            and all(change.approved_boundary for change in self.changes)
        )

    def count(self, action: str) -> int:
        return sum(change.action == action for change in self.changes)

    def to_json_list(self) -> list[dict[str, object]]:
        return [change.to_json_dict() for change in self.changes]


def parse_sanitized_what_if(
    stdout: str,
    *,
    boundary: str,
    expected_resources: tuple[ExpectedWhatIfResource, ...] | None = None,
    allowlisted_resource_types: Mapping[str, str] | None = None,
    automatically_approved_actions: frozenset[str] = frozenset(
        {"Create", "NoChange", "Ignore"}
    ),
) -> SanitizedWhatIfSummary | None:
    parsed = _parse_payload(stdout)
    if parsed is None:
        return None
    actions, identities = parsed

    if expected_resources is not None:
        return _exact_summary(
            actions,
            identities,
            boundary=boundary,
            expected_resources=expected_resources,
            automatically_approved_actions=automatically_approved_actions,
        )
    if allowlisted_resource_types is None:
        return None

    evidence: list[SanitizedWhatIfChange] = []
    for action, identity in zip(actions, identities, strict=True):
        logical_category = allowlisted_resource_types.get(identity.resource_type)
        approved = bool(
            logical_category is not None
            and action in automatically_approved_actions
        )
        evidence.append(
            SanitizedWhatIfChange(
                action=action,
                resource_type=identity.resource_type if approved else "unidentified",
                logical_category=logical_category or "unexpected_resource",
                boundary=boundary,
                approved_boundary=approved,
                expected_identity_match=approved,
                expected_parent_match=approved,
                expected_scope_match=approved,
                expected_multiplicity_match=approved,
            )
        )
    return SanitizedWhatIfSummary(tuple(evidence), exact_topology_match=True)


def parse_what_if_resource_identities(
    stdout: str,
) -> tuple[WhatIfResourceIdentity, ...] | None:
    parsed = _parse_payload(stdout)
    return None if parsed is None else parsed[1]


def _exact_summary(
    actions: tuple[str, ...],
    identities: tuple[WhatIfResourceIdentity, ...],
    *,
    boundary: str,
    expected_resources: tuple[ExpectedWhatIfResource, ...],
    automatically_approved_actions: frozenset[str],
) -> SanitizedWhatIfSummary:
    expected_keys = Counter(_expected_key(item) for item in expected_resources)
    actual_keys = Counter(_identity_key(item) for item in identities)
    multiplicity_match = actual_keys == expected_keys
    exact_topology_match = bool(expected_resources and multiplicity_match)
    evidence: list[SanitizedWhatIfChange] = []

    for action, identity in zip(actions, identities, strict=True):
        type_expectations = [
            item
            for item in expected_resources
            if item.resource_type == identity.resource_type
        ]
        scope_match = any(
            item.resource_group.casefold() == identity.resource_group.casefold()
            for item in type_expectations
        )
        parent_match = any(
            _casefolded(item.name_segments[:-1])
            == _casefolded(identity.name_segments[:-1])
            for item in type_expectations
        )
        identity_match = any(
            _expected_key(item) == _identity_key(identity)
            for item in type_expectations
        )
        category = next(
            (
                item.logical_category
                for item in type_expectations
                if _expected_key(item) == _identity_key(identity)
            ),
            type_expectations[0].logical_category
            if type_expectations
            else "unexpected_resource",
        )
        approved = bool(
            exact_topology_match
            and action in automatically_approved_actions
            and identity_match
            and parent_match
            and scope_match
            and multiplicity_match
        )
        evidence.append(
            SanitizedWhatIfChange(
                action=action,
                resource_type=(
                    identity.resource_type if type_expectations else "unidentified"
                ),
                logical_category=category,
                boundary=boundary,
                approved_boundary=approved,
                expected_identity_match=identity_match,
                expected_parent_match=parent_match,
                expected_scope_match=scope_match,
                expected_multiplicity_match=multiplicity_match,
            )
        )
    return SanitizedWhatIfSummary(tuple(evidence), exact_topology_match)


def _parse_payload(
    stdout: str,
) -> tuple[tuple[str, ...], tuple[WhatIfResourceIdentity, ...]] | None:
    try:
        payload = json.loads(stdout)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("changes"), list):
        return None

    actions: list[str] = []
    identities: list[WhatIfResourceIdentity] = []
    for raw_change in payload["changes"]:
        if not isinstance(raw_change, dict):
            return None
        raw_action = raw_change.get("changeType")
        if not isinstance(raw_action, str) or raw_action.casefold() not in _ACTIONS:
            return None
        identity = _resource_identity(raw_change.get("resourceId"))
        if identity is None:
            identity = WhatIfResourceIdentity("unidentified", "", ())
        actions.append(_ACTIONS[raw_action.casefold()])
        identities.append(identity)
    return tuple(actions), tuple(identities)


def _resource_identity(value: object) -> WhatIfResourceIdentity | None:
    if not isinstance(value, str) or not value.startswith("/"):
        return None
    parts = tuple(part for part in value.split("/") if part)
    if (
        len(parts) < 8
        or parts[0].casefold() != "subscriptions"
        or not parts[1]
        or parts[2].casefold() != "resourcegroups"
        or not parts[3]
        or parts[4].casefold() != "providers"
    ):
        return None
    remaining = parts[5:]
    nested_provider_indexes = [
        index
        for index, part in enumerate(remaining)
        if part.casefold() == "providers"
    ]
    if nested_provider_indexes:
        remaining = remaining[nested_provider_indexes[-1] + 1 :]
    if len(remaining) < 3 or len(remaining) % 2 == 0:
        return None
    namespace = remaining[0]
    type_segments = remaining[1::2]
    name_segments = remaining[2::2]
    if not namespace or not all(type_segments) or not all(name_segments):
        return None
    return WhatIfResourceIdentity(
        resource_type="/".join((namespace, *type_segments)),
        resource_group=parts[3],
        name_segments=tuple(name_segments),
    )


def _expected_key(item: ExpectedWhatIfResource) -> tuple[str, str, tuple[str, ...]]:
    return (
        item.resource_type,
        item.resource_group.casefold(),
        _casefolded(item.name_segments),
    )


def _identity_key(item: WhatIfResourceIdentity) -> tuple[str, str, tuple[str, ...]]:
    return (
        item.resource_type,
        item.resource_group.casefold(),
        _casefolded(item.name_segments),
    )


def _casefolded(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(value.casefold() for value in values)
