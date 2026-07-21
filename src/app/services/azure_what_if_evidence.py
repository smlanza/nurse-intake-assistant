from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
import json
from typing import Literal, Mapping


_ACTIONS = {
    "create": "Create",
    "modify": "Modify",
    "nochange": "NoChange",
    "delete": "Delete",
    "ignore": "Ignore",
    "deploy": "Deploy",
    "unsupported": "Unsupported",
}

_SAFE_IGNORE_SHAPE_FIELDS = (
    "changeType",
    "resourceId",
    "resourceType",
    "before",
    "after",
    "delta",
    "children",
)
_MAX_NESTED_RESOURCE_CHANGE_COUNT = 20

IgnoreParserShape = Literal[
    "resource_change",
    "resource_change_with_children",
    "resource_change_with_invalid_children",
]
IgnoreRejectionReason = Literal[
    "none",
    "unidentified_ignore_count_not_allowed",
    "resource_identity_present",
    "malformed_resource_id",
    "unexpected_resource_provider",
    "unexpected_resource_type",
    "unexpected_deployment_identity",
    "unexpected_deployment_scope",
    "unexpected_deployment_multiplicity",
]


@dataclass(frozen=True)
class SanitizedIgnoreDiagnostic:
    top_level_fields_present: tuple[str, ...]
    unknown_top_level_field_count: int
    resource_id_present: bool
    resource_type_present: bool
    before_present: bool
    after_present: bool
    delta_present: bool
    children_present: bool
    nested_resource_change_count: int
    nested_resource_change_count_truncated: bool
    parser_shape: IgnoreParserShape
    bounded_ignore_candidate: bool
    bounded_ignore_rejection_reason: IgnoreRejectionReason

    def to_json_dict(self) -> dict[str, object]:
        return {
            "diagnostic_kind": "unidentified_ignore_shape",
            "top_level_fields_present": list(self.top_level_fields_present),
            "unknown_top_level_field_count": self.unknown_top_level_field_count,
            "resource_id_present": self.resource_id_present,
            "resource_type_present": self.resource_type_present,
            "before_present": self.before_present,
            "after_present": self.after_present,
            "delta_present": self.delta_present,
            "children_present": self.children_present,
            "nested_resource_change_count": self.nested_resource_change_count,
            "nested_resource_change_count_truncated": (
                self.nested_resource_change_count_truncated
            ),
            "parser_shape": self.parser_shape,
            "bounded_ignore_candidate": self.bounded_ignore_candidate,
            "bounded_ignore_rejection_reason": (
                self.bounded_ignore_rejection_reason
            ),
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
    subscription: str
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
    diagnostic: SanitizedIgnoreDiagnostic | None = None

    def to_json_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
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
        if self.diagnostic is not None:
            result["diagnostic"] = self.diagnostic.to_json_dict()
        return result


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
    sanitized_additional_resource_types: Mapping[str, str] | None = None,
    expected_ignored_resources: tuple[ExpectedWhatIfResource, ...] = (),
    allow_expected_ignored_resources_absent: bool = False,
    allowed_unidentified_ignore_counts: frozenset[int] = frozenset({0}),
    automatically_approved_actions: frozenset[str] = frozenset(
        {"Create", "NoChange", "Ignore"}
    ),
) -> SanitizedWhatIfSummary | None:
    parsed = _parse_payload(stdout)
    if parsed is None:
        return None
    actions, identities, ignore_diagnostics = parsed

    if expected_resources is not None:
        return _exact_summary(
            actions,
            identities,
            ignore_diagnostics,
            boundary=boundary,
            expected_resources=expected_resources,
            automatically_approved_actions=automatically_approved_actions,
            sanitized_additional_resource_types=(
                sanitized_additional_resource_types or {}
            ),
            expected_ignored_resources=expected_ignored_resources,
            allow_expected_ignored_resources_absent=(
                allow_expected_ignored_resources_absent
            ),
            allowed_unidentified_ignore_counts=allowed_unidentified_ignore_counts,
        )
    if allowlisted_resource_types is None:
        return None

    evidence: list[SanitizedWhatIfChange] = []
    for action, identity, diagnostic in zip(
        actions, identities, ignore_diagnostics, strict=True
    ):
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
                diagnostic=(
                    None
                    if diagnostic is None or approved
                    else _decide_ignore_diagnostic(diagnostic, count_matches=False)
                ),
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
    ignore_diagnostics: tuple[SanitizedIgnoreDiagnostic | None, ...],
    *,
    boundary: str,
    expected_resources: tuple[ExpectedWhatIfResource, ...],
    automatically_approved_actions: frozenset[str],
    sanitized_additional_resource_types: Mapping[str, str],
    expected_ignored_resources: tuple[ExpectedWhatIfResource, ...],
    allow_expected_ignored_resources_absent: bool,
    allowed_unidentified_ignore_counts: frozenset[int],
) -> SanitizedWhatIfSummary:
    expected_keys = Counter(_expected_key(item) for item in expected_resources)
    additional_types = {
        resource_type.casefold(): category
        for resource_type, category in sanitized_additional_resource_types.items()
    }
    expected_type_keys = {
        item.resource_type.casefold() for item in expected_resources
    }
    expected_ignored_keys = Counter(
        _expected_key(item) for item in expected_ignored_resources
    )
    expected_subscriptions = {
        identity.subscription.casefold()
        for identity in identities
        if _identity_key(identity) in expected_keys
    }
    unidentified_ignore_count = sum(
        action == "Ignore" and identity.resource_type == "unidentified"
        for action, identity in zip(actions, identities, strict=True)
    )
    unidentified_ignores_match = (
        unidentified_ignore_count in allowed_unidentified_ignore_counts
    )
    ordinary_identities = tuple(
        identity
        for action, identity in zip(actions, identities, strict=True)
        if identity.resource_type.casefold() not in additional_types
        and not (
            unidentified_ignores_match
            and action == "Ignore"
            and identity.resource_type == "unidentified"
        )
    )
    actual_keys = Counter(_identity_key(item) for item in ordinary_identities)
    identified_additional = tuple(
        (action, identity)
        for action, identity in zip(actions, identities, strict=True)
        if identity.resource_type.casefold() in additional_types
    )
    expected_ignored_resources_match = bool(
        expected_ignored_resources
        and (
            (
                not identified_additional
                and allow_expected_ignored_resources_absent
            )
            or (
                len(identified_additional) == len(expected_ignored_resources)
                and all(action == "Ignore" for action, _ in identified_additional)
                and Counter(
                    _identity_key(identity)
                    for _, identity in identified_additional
                )
                == expected_ignored_keys
                and len(expected_subscriptions) == 1
                and all(
                    identity.subscription.casefold() in expected_subscriptions
                    for _, identity in identified_additional
                )
            )
        )
    )
    allowed_additional = all(
        identity.resource_type.casefold() in expected_type_keys
        or identity.resource_type.casefold() in additional_types
        or (
            unidentified_ignores_match
            and action == "Ignore"
            and identity.resource_type == "unidentified"
        )
        for action, identity in zip(actions, identities, strict=True)
    )
    expected_groups = {
        item.resource_group.casefold() for item in expected_resources
    }
    additional_scopes_match = all(
        identity.resource_group.casefold() in expected_groups
        for identity in identities
        if identity.resource_type.casefold() in additional_types
    )
    expected_actions_match = all(
        action in automatically_approved_actions
        for action, identity in zip(actions, identities, strict=True)
        if identity.resource_type.casefold() in expected_type_keys
    )
    additional_topology_match = (
        expected_ignored_resources_match
        if expected_ignored_resources
        else additional_scopes_match
    )
    multiplicity_match = bool(
        actual_keys == expected_keys
        and allowed_additional
        and additional_topology_match
        and expected_actions_match
    )
    exact_topology_match = bool(expected_resources and multiplicity_match)
    evidence: list[SanitizedWhatIfChange] = []

    for action, identity, diagnostic in zip(
        actions, identities, ignore_diagnostics, strict=True
    ):
        if action == "Ignore" and identity.resource_type == "unidentified":
            approved = bool(exact_topology_match and unidentified_ignores_match)
            evidence.append(
                SanitizedWhatIfChange(
                    action=action,
                    resource_type="unidentified",
                    logical_category=(
                        "unexpected_resource"
                        if expected_ignored_resources
                        else "template_module_ignore"
                    ),
                    boundary=boundary,
                    approved_boundary=approved,
                    expected_identity_match=False,
                    expected_parent_match=False,
                    expected_scope_match=False,
                    expected_multiplicity_match=approved,
                    diagnostic=(
                        _expected_ignore_diagnostic(
                            diagnostic,
                            identity,
                            expected_ignored_resources,
                            expected_subscriptions,
                            expected_ignored_resources_match,
                        )
                        if expected_ignored_resources
                        else _decide_ignore_diagnostic(
                            diagnostic,
                            count_matches=unidentified_ignores_match,
                        )
                    ),
                )
            )
            continue
        type_expectations = [
            item
            for item in expected_resources
            if item.resource_type.casefold() == identity.resource_type.casefold()
        ]
        additional_category = additional_types.get(identity.resource_type.casefold())
        if additional_category is not None:
            ignored_expectations = [
                item
                for item in expected_ignored_resources
                if item.resource_type.casefold()
                == identity.resource_type.casefold()
            ]
            scope_match = identity.resource_group.casefold() in expected_groups
            if ignored_expectations:
                scope_match = any(
                    item.resource_group.casefold()
                    == identity.resource_group.casefold()
                    for item in ignored_expectations
                )
                parent_match = any(
                    _casefolded(item.name_segments[:-1])
                    == _casefolded(identity.name_segments[:-1])
                    for item in ignored_expectations
                )
                identity_match = any(
                    _expected_key(item) == _identity_key(identity)
                    for item in ignored_expectations
                )
                category = next(
                    (
                        item.logical_category
                        for item in ignored_expectations
                        if _expected_key(item) == _identity_key(identity)
                    ),
                    "unexpected_nested_deployment",
                )
                approved = bool(
                    exact_topology_match
                    and action == "Ignore"
                    and identity_match
                    and parent_match
                    and scope_match
                    and multiplicity_match
                )
                evidence.append(
                    SanitizedWhatIfChange(
                        action=action,
                        resource_type=identity.resource_type,
                        logical_category=category,
                        boundary=boundary,
                        approved_boundary=approved,
                        expected_identity_match=identity_match,
                        expected_parent_match=parent_match,
                        expected_scope_match=scope_match,
                        expected_multiplicity_match=multiplicity_match,
                        diagnostic=(
                            None
                            if diagnostic is None or approved
                            else _expected_ignore_diagnostic(
                                diagnostic,
                                identity,
                                expected_ignored_resources,
                                expected_subscriptions,
                                expected_ignored_resources_match,
                            )
                        ),
                    )
                )
                continue
            evidence.append(
                SanitizedWhatIfChange(
                    action=action,
                    resource_type=identity.resource_type,
                    logical_category=additional_category,
                    boundary=boundary,
                    approved_boundary=False,
                    expected_identity_match=False,
                    expected_parent_match=False,
                    expected_scope_match=scope_match,
                    expected_multiplicity_match=multiplicity_match,
                )
            )
            continue
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
                diagnostic=(
                    None
                    if diagnostic is None or approved
                    else (
                        _expected_ignore_diagnostic(
                            diagnostic,
                            identity,
                            expected_ignored_resources,
                            expected_subscriptions,
                            expected_ignored_resources_match,
                        )
                        if expected_ignored_resources
                        else _decide_ignore_diagnostic(
                            diagnostic,
                            count_matches=unidentified_ignores_match,
                        )
                    )
                ),
            )
        )
    return SanitizedWhatIfSummary(tuple(evidence), exact_topology_match)


def _parse_payload(
    stdout: str,
) -> tuple[
    tuple[str, ...],
    tuple[WhatIfResourceIdentity, ...],
    tuple[SanitizedIgnoreDiagnostic | None, ...],
] | None:
    try:
        payload = json.loads(stdout)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("changes"), list):
        return None

    actions: list[str] = []
    identities: list[WhatIfResourceIdentity] = []
    ignore_diagnostics: list[SanitizedIgnoreDiagnostic | None] = []
    for raw_change in payload["changes"]:
        if not isinstance(raw_change, dict):
            return None
        raw_action = raw_change.get("changeType")
        if not isinstance(raw_action, str) or raw_action.casefold() not in _ACTIONS:
            return None
        identity = _resource_identity(raw_change.get("resourceId"))
        if identity is None:
            identity = WhatIfResourceIdentity("unidentified", "", "", ())
        action = _ACTIONS[raw_action.casefold()]
        actions.append(action)
        identities.append(identity)
        ignore_diagnostics.append(
            _ignore_shape_diagnostic(raw_change, identity)
            if action == "Ignore"
            else None
        )
    return tuple(actions), tuple(identities), tuple(ignore_diagnostics)


def _ignore_shape_diagnostic(
    raw_change: dict[str, object],
    identity: WhatIfResourceIdentity,
) -> SanitizedIgnoreDiagnostic:
    children = raw_change.get("children")
    if "children" not in raw_change:
        parser_shape = "resource_change"
        nested_count = 0
        nested_count_truncated = False
    elif isinstance(children, list):
        parser_shape = "resource_change_with_children"
        nested_count = min(len(children), _MAX_NESTED_RESOURCE_CHANGE_COUNT)
        nested_count_truncated = len(children) > _MAX_NESTED_RESOURCE_CHANGE_COUNT
    else:
        parser_shape = "resource_change_with_invalid_children"
        nested_count = 0
        nested_count_truncated = False
    candidate = identity.resource_type == "unidentified"
    return SanitizedIgnoreDiagnostic(
        top_level_fields_present=tuple(
            name for name in _SAFE_IGNORE_SHAPE_FIELDS if name in raw_change
        ),
        unknown_top_level_field_count=sum(
            name not in _SAFE_IGNORE_SHAPE_FIELDS for name in raw_change
        ),
        resource_id_present="resourceId" in raw_change,
        resource_type_present="resourceType" in raw_change,
        before_present="before" in raw_change,
        after_present="after" in raw_change,
        delta_present="delta" in raw_change,
        children_present="children" in raw_change,
        nested_resource_change_count=nested_count,
        nested_resource_change_count_truncated=nested_count_truncated,
        parser_shape=parser_shape,
        bounded_ignore_candidate=candidate,
        bounded_ignore_rejection_reason=(
            "none" if candidate else "resource_identity_present"
        ),
    )


def _decide_ignore_diagnostic(
    diagnostic: SanitizedIgnoreDiagnostic | None,
    *,
    count_matches: bool,
) -> SanitizedIgnoreDiagnostic | None:
    if diagnostic is None or not diagnostic.bounded_ignore_candidate or count_matches:
        return diagnostic
    return replace(
        diagnostic,
        bounded_ignore_rejection_reason="unidentified_ignore_count_not_allowed",
    )


def _expected_ignore_diagnostic(
    diagnostic: SanitizedIgnoreDiagnostic | None,
    identity: WhatIfResourceIdentity,
    expected: tuple[ExpectedWhatIfResource, ...],
    expected_subscriptions: set[str],
    multiplicity_match: bool,
) -> SanitizedIgnoreDiagnostic | None:
    if diagnostic is None:
        return None
    expected_groups = {item.resource_group.casefold() for item in expected}
    expected_keys = {_expected_key(item) for item in expected}
    resource_type_parts = identity.resource_type.split("/", 1)
    if identity.resource_type == "unidentified":
        candidate = False
        reason: IgnoreRejectionReason = "malformed_resource_id"
    elif resource_type_parts[0].casefold() != "microsoft.resources":
        candidate = False
        reason = "unexpected_resource_provider"
    elif identity.resource_type.casefold() != "microsoft.resources/deployments":
        candidate = False
        reason = "unexpected_resource_type"
    elif identity.resource_group.casefold() not in expected_groups:
        candidate = False
        reason = "unexpected_deployment_scope"
    elif identity.subscription.casefold() not in expected_subscriptions:
        candidate = False
        reason = "unexpected_deployment_scope"
    elif _identity_key(identity) not in expected_keys:
        candidate = False
        reason = "unexpected_deployment_identity"
    elif not multiplicity_match:
        candidate = True
        reason = "unexpected_deployment_multiplicity"
    else:
        candidate = True
        reason = "none"
    return replace(
        diagnostic,
        bounded_ignore_candidate=candidate,
        bounded_ignore_rejection_reason=reason,
    )


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
        subscription=parts[1],
        resource_group=parts[3],
        name_segments=tuple(name_segments),
    )


def _expected_key(item: ExpectedWhatIfResource) -> tuple[str, str, tuple[str, ...]]:
    return (
        item.resource_type.casefold(),
        item.resource_group.casefold(),
        _casefolded(item.name_segments),
    )


def _identity_key(item: WhatIfResourceIdentity) -> tuple[str, str, tuple[str, ...]]:
    return (
        item.resource_type.casefold(),
        item.resource_group.casefold(),
        _casefolded(item.name_segments),
    )


def _casefolded(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(value.casefold() for value in values)
