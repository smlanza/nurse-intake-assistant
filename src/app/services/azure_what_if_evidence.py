from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field, replace
import json
from typing import Callable, Generic, Literal, Mapping, TypeVar


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
_MAX_ARM_PATH_COUNT = 20

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
    "invalid_reference_path",
    "unexpected_reference_identity",
    "unexpected_reference_scope",
    "unexpected_reference_multiplicity",
]
ArmIdParseStatus = Literal[
    "parsed",
    "malformed",
    "unsupported_scope",
    "incomplete_provider_chain",
]
ArmScopeKind = Literal[
    "resource_group",
    "subscription",
    "tenant",
    "management_group",
    "resource",
    "unknown",
]
ProviderMarkerSelection = Literal["first", "last", "only", "none", "ambiguous"]
ProviderNamespaceClass = Literal[
    "microsoft_resources",
    "approved_application_provider",
    "other",
    "missing",
    "malformed",
]
ResourceTypeClass = Literal[
    "deployments",
    "approved_application_resource",
    "other",
    "missing",
    "malformed",
]
NormalizedAction = Literal[
    "Create",
    "Modify",
    "NoChange",
    "Delete",
    "Ignore",
    "Deploy",
    "Unsupported",
    "Replacement",
    "unknown",
]
_NormalizedRecordT = TypeVar("_NormalizedRecordT")


@dataclass(frozen=True)
class SanitizedArmPathDiagnostic:
    arm_id_parse_status: ArmIdParseStatus
    scope_kind: ArmScopeKind
    path_segment_count: int
    path_segment_count_truncated: bool
    provider_marker_count: int
    provider_marker_count_truncated: bool
    selected_provider_marker: ProviderMarkerSelection
    nested_provider_chain_present: bool
    provider_chain_depth: int
    provider_chain_depth_truncated: bool
    selected_provider_namespace_class: ProviderNamespaceClass
    selected_resource_type_class: ResourceTypeClass
    segments_after_selected_provider_count: int
    segments_after_selected_provider_count_truncated: bool
    resource_type_segment_count: int
    resource_type_segment_count_truncated: bool
    resource_name_segment_count: int
    resource_name_segment_count_truncated: bool
    type_name_pairing_valid: bool
    multiple_provider_namespaces_present: bool
    extension_resource_shape: bool
    trailing_unmatched_segment_present: bool

    def to_json_dict(self) -> dict[str, object]:
        return {
            "arm_id_parse_status": self.arm_id_parse_status,
            "scope_kind": self.scope_kind,
            "path_segment_count": self.path_segment_count,
            "path_segment_count_truncated": self.path_segment_count_truncated,
            "provider_marker_count": self.provider_marker_count,
            "provider_marker_count_truncated": (
                self.provider_marker_count_truncated
            ),
            "selected_provider_marker": self.selected_provider_marker,
            "nested_provider_chain_present": self.nested_provider_chain_present,
            "provider_chain_depth": self.provider_chain_depth,
            "provider_chain_depth_truncated": self.provider_chain_depth_truncated,
            "selected_provider_namespace_class": (
                self.selected_provider_namespace_class
            ),
            "selected_resource_type_class": self.selected_resource_type_class,
            "segments_after_selected_provider_count": (
                self.segments_after_selected_provider_count
            ),
            "segments_after_selected_provider_count_truncated": (
                self.segments_after_selected_provider_count_truncated
            ),
            "resource_type_segment_count": self.resource_type_segment_count,
            "resource_type_segment_count_truncated": (
                self.resource_type_segment_count_truncated
            ),
            "resource_name_segment_count": self.resource_name_segment_count,
            "resource_name_segment_count_truncated": (
                self.resource_name_segment_count_truncated
            ),
            "type_name_pairing_valid": self.type_name_pairing_valid,
            "multiple_provider_namespaces_present": (
                self.multiple_provider_namespaces_present
            ),
            "extension_resource_shape": self.extension_resource_shape,
            "trailing_unmatched_segment_present": (
                self.trailing_unmatched_segment_present
            ),
        }


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
    arm_path: SanitizedArmPathDiagnostic

    def to_json_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
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
        result["arm_path"] = self.arm_path.to_json_dict()
        return result


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
    resource_name: str = ""
    canonical_resource_id: str = field(default="", repr=False)
    parent_resource_id: str = field(default="", repr=False)
    scope_resource_id: str = field(default="", repr=False)
    extension_resource: bool = False
    provider_segments: tuple[tuple[str, ...], ...] = field(
        default=(),
        repr=False,
    )


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


@dataclass(frozen=True, repr=False)
class _AuthoritativeWhatIfRecord:
    record_is_object: bool
    action: NormalizedAction
    action_is_supported: bool
    action_is_canonical: bool
    resource_id_present: bool
    resource_id_shape_valid: bool
    resource_type_present: bool
    resource_type_consistent: bool
    identity: WhatIfResourceIdentity | None = field(default=None, repr=False)
    resource_id: str | None = field(default=None, repr=False)

    @property
    def resource_type(self) -> str | None:
        return self.identity.resource_type if self.identity is not None else None

    def resource_id_matches(self, expected: str) -> bool:
        return bool(
            self.identity is not None
            and self.identity.canonical_resource_id.casefold()
            == expected.casefold()
        )

    def parent_matches(self, expected_parent: str) -> bool:
        return bool(
            self.identity is not None
            and self.identity.parent_resource_id.casefold()
            == expected_parent.casefold()
        )

    def scope_matches(self, subscription_id: str, resource_group: str) -> bool:
        return bool(
            self.identity is not None
            and self.identity.subscription.casefold() == subscription_id.casefold()
            and self.identity.resource_group.casefold() == resource_group.casefold()
        )

    def resource_scope_matches(self, expected_scope: str) -> bool:
        return bool(
            self.identity is not None
            and self.identity.scope_resource_id.casefold()
            == expected_scope.casefold()
        )


@dataclass(frozen=True)
class NormalizedWhatIfPayload(Generic[_NormalizedRecordT]):
    payload_is_object: bool
    changes_present: bool
    changes_is_list: bool
    change_record_count: int | None
    records: tuple[_NormalizedRecordT, ...]
    sanitized_summary: SanitizedWhatIfSummary | None


def parse_sanitized_what_if(
    stdout: str,
    *,
    boundary: str,
    expected_resources: tuple[ExpectedWhatIfResource, ...] | None = None,
    allowlisted_resource_types: Mapping[str, str] | None = None,
    sanitized_additional_resource_types: Mapping[str, str] | None = None,
    expected_ignored_resources: tuple[ExpectedWhatIfResource, ...] = (),
    allow_expected_ignored_resources_absent: bool = False,
    allow_expected_ignored_resource_subsets: bool = False,
    allowed_unidentified_ignore_counts: frozenset[int] = frozenset({0}),
    automatically_approved_actions: frozenset[str] = frozenset(
        {"Create", "NoChange", "Ignore"}
    ),
) -> SanitizedWhatIfSummary | None:
    try:
        payload = json.loads(stdout)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    return normalize_sanitized_what_if_payload(
        payload,
        boundary=boundary,
        record_factory=lambda _ordinal, _raw, _facts: None,
        expected_resources=expected_resources,
        allowlisted_resource_types=allowlisted_resource_types,
        sanitized_additional_resource_types=sanitized_additional_resource_types,
        expected_ignored_resources=expected_ignored_resources,
        allow_expected_ignored_resources_absent=(
            allow_expected_ignored_resources_absent
        ),
        allow_expected_ignored_resource_subsets=(
            allow_expected_ignored_resource_subsets
        ),
        allowed_unidentified_ignore_counts=allowed_unidentified_ignore_counts,
        automatically_approved_actions=automatically_approved_actions,
    ).sanitized_summary


def normalize_sanitized_what_if_payload(
    payload: object,
    *,
    boundary: str,
    record_factory: Callable[
        [int, object, _AuthoritativeWhatIfRecord], _NormalizedRecordT
    ],
    expected_resources: tuple[ExpectedWhatIfResource, ...] | None = None,
    allowlisted_resource_types: Mapping[str, str] | None = None,
    sanitized_additional_resource_types: Mapping[str, str] | None = None,
    expected_ignored_resources: tuple[ExpectedWhatIfResource, ...] = (),
    allow_expected_ignored_resources_absent: bool = False,
    allow_expected_ignored_resource_subsets: bool = False,
    allowed_unidentified_ignore_counts: frozenset[int] = frozenset({0}),
    automatically_approved_actions: frozenset[str] = frozenset(
        {"Create", "NoChange", "Ignore"}
    ),
) -> NormalizedWhatIfPayload[_NormalizedRecordT]:
    if not isinstance(payload, dict):
        return NormalizedWhatIfPayload(False, False, False, None, (), None)
    if "changes" not in payload:
        return NormalizedWhatIfPayload(True, False, False, None, (), None)
    raw_changes = payload.get("changes")
    if not isinstance(raw_changes, list):
        return NormalizedWhatIfPayload(True, True, False, None, (), None)

    approved_diagnostic_types = frozenset(
        item.resource_type.casefold() for item in (expected_resources or ())
    ) | frozenset(
        item.resource_type.casefold() for item in expected_ignored_resources
    ) | frozenset(
        item.casefold() for item in (allowlisted_resource_types or {})
    ) | frozenset(
        item.casefold() for item in (sanitized_additional_resource_types or {})
    )
    actions: list[str] = []
    identities: list[WhatIfResourceIdentity] = []
    ignore_diagnostics: list[SanitizedIgnoreDiagnostic | None] = []
    records: list[_NormalizedRecordT] = []
    records_parseable = True
    for ordinal, raw_change in enumerate(raw_changes, start=1):
        if not isinstance(raw_change, dict):
            facts = _AuthoritativeWhatIfRecord(
                record_is_object=False,
                action="unknown",
                action_is_supported=False,
                action_is_canonical=False,
                resource_id_present=False,
                resource_id_shape_valid=False,
                resource_type_present=False,
                resource_type_consistent=False,
            )
            records.append(record_factory(ordinal, raw_change, facts))
            records_parseable = False
            continue
        raw_action = raw_change.get("changeType")
        action_key = raw_action.casefold() if isinstance(raw_action, str) else ""
        action_is_supported = action_key in _ACTIONS
        if action_is_supported:
            action: NormalizedAction = _ACTIONS[action_key]
        elif action_key == "replacement":
            action = "Replacement"
        else:
            action = "unknown"
        identity = _resource_identity(raw_change.get("resourceId"))
        raw_resource_type = raw_change.get("resourceType")
        resource_type_present = "resourceType" in raw_change
        resource_type_consistent = bool(
            identity is not None
            and (
                not resource_type_present
                or (
                    isinstance(raw_resource_type, str)
                    and raw_resource_type.casefold()
                    == identity.resource_type.casefold()
                )
            )
        )
        facts = _AuthoritativeWhatIfRecord(
            record_is_object=True,
            action=action,
            action_is_supported=action_is_supported,
            action_is_canonical=bool(
                action_is_supported and raw_action == action
            ),
            resource_id_present="resourceId" in raw_change,
            resource_id_shape_valid=identity is not None,
            resource_type_present=resource_type_present,
            resource_type_consistent=resource_type_consistent,
            identity=identity,
            resource_id=(
                raw_change.get("resourceId")
                if isinstance(raw_change.get("resourceId"), str)
                else None
            ),
        )
        records.append(record_factory(ordinal, raw_change, facts))
        if not action_is_supported:
            records_parseable = False
            continue
        if resource_type_present and not resource_type_consistent:
            records_parseable = False
        normalized_identity = identity or WhatIfResourceIdentity(
            "unidentified", "", "", ()
        )
        actions.append(action)
        identities.append(normalized_identity)
        ignore_diagnostics.append(
            _ignore_shape_diagnostic(
                raw_change,
                normalized_identity,
                approved_resource_types=approved_diagnostic_types,
            )
            if action == "Ignore"
            else None
        )

    summary = (
        _summarize_normalized_what_if(
            tuple(actions),
            tuple(identities),
            tuple(ignore_diagnostics),
            boundary=boundary,
            expected_resources=expected_resources,
            allowlisted_resource_types=allowlisted_resource_types,
            sanitized_additional_resource_types=(
                sanitized_additional_resource_types or {}
            ),
            expected_ignored_resources=expected_ignored_resources,
            allow_expected_ignored_resources_absent=(
                allow_expected_ignored_resources_absent
            ),
            allow_expected_ignored_resource_subsets=(
                allow_expected_ignored_resource_subsets
            ),
            allowed_unidentified_ignore_counts=(
                allowed_unidentified_ignore_counts
            ),
            automatically_approved_actions=automatically_approved_actions,
        )
        if records_parseable
        else None
    )
    return NormalizedWhatIfPayload(
        payload_is_object=True,
        changes_present=True,
        changes_is_list=True,
        change_record_count=len(raw_changes),
        records=tuple(records),
        sanitized_summary=summary,
    )


def _summarize_normalized_what_if(
    actions: tuple[str, ...],
    identities: tuple[WhatIfResourceIdentity, ...],
    ignore_diagnostics: tuple[SanitizedIgnoreDiagnostic | None, ...],
    *,
    boundary: str,
    expected_resources: tuple[ExpectedWhatIfResource, ...] | None,
    allowlisted_resource_types: Mapping[str, str] | None,
    sanitized_additional_resource_types: Mapping[str, str],
    expected_ignored_resources: tuple[ExpectedWhatIfResource, ...],
    allow_expected_ignored_resources_absent: bool,
    allow_expected_ignored_resource_subsets: bool,
    allowed_unidentified_ignore_counts: frozenset[int],
    automatically_approved_actions: frozenset[str],
) -> SanitizedWhatIfSummary | None:
    if expected_resources is not None:
        return _exact_summary(
            actions,
            identities,
            ignore_diagnostics,
            boundary=boundary,
            expected_resources=expected_resources,
            automatically_approved_actions=automatically_approved_actions,
            sanitized_additional_resource_types=sanitized_additional_resource_types,
            expected_ignored_resources=expected_ignored_resources,
            allow_expected_ignored_resources_absent=(
                allow_expected_ignored_resources_absent
            ),
            allow_expected_ignored_resource_subsets=(
                allow_expected_ignored_resource_subsets
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
    allow_expected_ignored_resource_subsets: bool,
    allowed_unidentified_ignore_counts: frozenset[int],
) -> SanitizedWhatIfSummary:
    expected_keys = Counter(_expected_key(item) for item in expected_resources)
    additional_types = {
        resource_type.casefold(): (resource_type, category)
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
        (action, identity, diagnostic)
        for action, identity, diagnostic in zip(
            actions,
            identities,
            ignore_diagnostics,
            strict=True,
        )
        if identity.resource_type.casefold() in additional_types
    )
    identified_additional_keys = Counter(
        _identity_key(identity) for _, identity, _ in identified_additional
    )
    identified_additional_membership_matches = bool(
        (
            allow_expected_ignored_resource_subsets
            and all(
                count <= expected_ignored_keys[key]
                for key, count in identified_additional_keys.items()
            )
        )
        or identified_additional_keys == expected_ignored_keys
    )
    expected_ignored_resources_match = bool(
        expected_ignored_resources
        and (
            (
                not identified_additional
                and allow_expected_ignored_resources_absent
            )
            or (
                bool(identified_additional)
                and identified_additional_membership_matches
                and all(
                    action == "Ignore"
                    and diagnostic is not None
                    and _direct_resource_group_reference_path(diagnostic)
                    for action, _, diagnostic in identified_additional
                )
                and len(expected_subscriptions) == 1
                and all(
                    identity.subscription.casefold() in expected_subscriptions
                    for _, identity, _ in identified_additional
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
        additional = additional_types.get(identity.resource_type.casefold())
        if additional is not None:
            canonical_resource_type, additional_category = additional
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
                    "unexpected_resource",
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
                        resource_type=canonical_resource_type,
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
                    resource_type=canonical_resource_type,
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


def _direct_resource_group_reference_path(
    diagnostic: SanitizedIgnoreDiagnostic,
) -> bool:
    arm_path = diagnostic.arm_path
    return bool(
        arm_path.arm_id_parse_status == "parsed"
        and arm_path.scope_kind == "resource_group"
        and not arm_path.path_segment_count_truncated
        and arm_path.provider_marker_count == 1
        and not arm_path.provider_marker_count_truncated
        and arm_path.selected_provider_marker == "only"
        and arm_path.provider_chain_depth == 1
        and not arm_path.provider_chain_depth_truncated
        and arm_path.type_name_pairing_valid
        and not arm_path.nested_provider_chain_present
        and not arm_path.multiple_provider_namespaces_present
        and not arm_path.extension_resource_shape
        and not arm_path.trailing_unmatched_segment_present
    )


def _parse_payload(
    stdout: str,
    *,
    approved_resource_types: frozenset[str] = frozenset(),
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
            _ignore_shape_diagnostic(
                raw_change,
                identity,
                approved_resource_types=approved_resource_types,
            )
            if action == "Ignore"
            else None
        )
    return tuple(actions), tuple(identities), tuple(ignore_diagnostics)


def _ignore_shape_diagnostic(
    raw_change: dict[str, object],
    identity: WhatIfResourceIdentity,
    *,
    approved_resource_types: frozenset[str],
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
        arm_path=_arm_path_diagnostic(
            raw_change.get("resourceId"),
            identity,
            approved_resource_types=approved_resource_types,
        ),
    )


def _bounded_count(value: int) -> tuple[int, bool]:
    return min(value, _MAX_ARM_PATH_COUNT), value > _MAX_ARM_PATH_COUNT


def _arm_path_diagnostic(
    value: object,
    identity: WhatIfResourceIdentity,
    *,
    approved_resource_types: frozenset[str],
) -> SanitizedArmPathDiagnostic:
    is_path = isinstance(value, str) and value.startswith("/")
    parts = tuple(part for part in value.split("/") if part) if is_path else ()
    provider_indexes = tuple(
        index for index, part in enumerate(parts) if part.casefold() == "providers"
    )
    selected_index = provider_indexes[-1] if provider_indexes else None
    after_provider = parts[selected_index + 1 :] if selected_index is not None else ()
    namespace = after_provider[0] if after_provider else None
    type_name_segments = after_provider[1:] if after_provider else ()
    type_segments = type_name_segments[::2]
    name_segments = type_name_segments[1::2]
    pairing_valid = bool(
        namespace
        and len(type_name_segments) >= 2
        and len(type_name_segments) % 2 == 0
    )
    trailing_unmatched = bool(type_name_segments) and len(type_name_segments) % 2 == 1

    if (
        len(parts) >= 5
        and parts[0].casefold() == "subscriptions"
        and parts[2].casefold() == "resourcegroups"
    ):
        scope_kind: ArmScopeKind = "resource_group"
    elif len(parts) >= 2 and parts[0].casefold() == "subscriptions":
        scope_kind = "subscription"
    elif (
        len(parts) >= 4
        and parts[0].casefold() == "providers"
        and parts[1].casefold() == "microsoft.management"
        and parts[2].casefold() == "managementgroups"
    ):
        scope_kind = "management_group"
    elif parts and parts[0].casefold() in {"tenants", "tenant"}:
        scope_kind = "tenant"
    elif is_path and provider_indexes:
        scope_kind = "resource"
    else:
        scope_kind = "unknown"

    if identity.resource_type != "unidentified":
        parse_status: ArmIdParseStatus = "parsed"
    elif not is_path:
        parse_status = "malformed"
    elif scope_kind != "resource_group":
        parse_status = "unsupported_scope"
    elif provider_indexes and not pairing_valid:
        parse_status = "incomplete_provider_chain"
    else:
        parse_status = "malformed"

    if not provider_indexes:
        selected_marker: ProviderMarkerSelection = "none"
    elif len(provider_indexes) == 1:
        selected_marker = "only"
    else:
        selected_marker = "last"

    if namespace is None:
        provider_class: ProviderNamespaceClass = "missing"
    elif not namespace:
        provider_class = "malformed"
    elif namespace.casefold() == "microsoft.resources":
        provider_class = "microsoft_resources"
    elif any(
        resource_type.startswith(namespace.casefold() + "/")
        for resource_type in approved_resource_types
    ):
        provider_class = "approved_application_provider"
    else:
        provider_class = "other"

    selected_resource_type = (
        "/".join((namespace, *type_segments)).casefold()
        if namespace is not None and pairing_valid
        else None
    )
    if not pairing_valid or not type_segments or not name_segments:
        resource_type_class: ResourceTypeClass = "missing"
    elif selected_resource_type == "microsoft.resources/deployments":
        resource_type_class = "deployments"
    elif selected_resource_type in approved_resource_types:
        resource_type_class = "approved_application_resource"
    else:
        resource_type_class = "other"

    path_count, path_truncated = _bounded_count(len(parts))
    marker_count, marker_truncated = _bounded_count(len(provider_indexes))
    after_count, after_truncated = _bounded_count(len(after_provider))
    type_count, type_truncated = _bounded_count(len(type_segments))
    name_count, name_truncated = _bounded_count(len(name_segments))
    return SanitizedArmPathDiagnostic(
        arm_id_parse_status=parse_status,
        scope_kind=scope_kind,
        path_segment_count=path_count,
        path_segment_count_truncated=path_truncated,
        provider_marker_count=marker_count,
        provider_marker_count_truncated=marker_truncated,
        selected_provider_marker=selected_marker,
        nested_provider_chain_present=len(provider_indexes) > 1,
        provider_chain_depth=marker_count,
        provider_chain_depth_truncated=marker_truncated,
        selected_provider_namespace_class=provider_class,
        selected_resource_type_class=resource_type_class,
        segments_after_selected_provider_count=after_count,
        segments_after_selected_provider_count_truncated=after_truncated,
        resource_type_segment_count=type_count,
        resource_type_segment_count_truncated=type_truncated,
        resource_name_segment_count=name_count,
        resource_name_segment_count_truncated=name_truncated,
        type_name_pairing_valid=pairing_valid,
        multiple_provider_namespaces_present=len(provider_indexes) > 1,
        extension_resource_shape=len(provider_indexes) > 1,
        trailing_unmatched_segment_present=trailing_unmatched,
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
    expected_types = {item.resource_type.casefold() for item in expected}
    expected_providers = {
        item.resource_type.split("/", 1)[0].casefold() for item in expected
    }
    resource_type_parts = identity.resource_type.split("/", 1)
    if identity.resource_type == "unidentified":
        candidate = False
        reason: IgnoreRejectionReason = "malformed_resource_id"
    elif resource_type_parts[0].casefold() not in expected_providers:
        candidate = False
        reason = "unexpected_resource_provider"
    elif identity.resource_type.casefold() not in expected_types:
        candidate = False
        reason = "unexpected_resource_type"
    elif not _direct_resource_group_reference_path(diagnostic):
        candidate = False
        reason = "invalid_reference_path"
    elif identity.resource_group.casefold() not in expected_groups:
        candidate = False
        reason = "unexpected_reference_scope"
    elif identity.subscription.casefold() not in expected_subscriptions:
        candidate = False
        reason = "unexpected_reference_scope"
    elif _identity_key(identity) not in expected_keys:
        candidate = False
        reason = "unexpected_reference_identity"
    elif not multiplicity_match:
        candidate = True
        reason = "unexpected_reference_multiplicity"
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
    split_parts = value.split("/")
    if split_parts[0] or any(not part for part in split_parts[1:]):
        return None
    parts = tuple(split_parts[1:])
    if (
        len(parts) < 8
        or parts[0].casefold() != "subscriptions"
        or not parts[1]
        or parts[2].casefold() != "resourcegroups"
        or not parts[3]
        or parts[4].casefold() != "providers"
    ):
        return None

    provider_segments: list[tuple[str, ...]] = []
    current_provider: list[str] = []
    for part in parts[5:]:
        if part.casefold() == "providers":
            if not current_provider:
                return None
            provider_segments.append(tuple(current_provider))
            current_provider = []
        else:
            current_provider.append(part)
    if not current_provider:
        return None
    provider_segments.append(tuple(current_provider))
    if any(
        len(segment) < 3 or len(segment) % 2 == 0
        for segment in provider_segments
    ):
        return None

    final_provider = provider_segments[-1]
    namespace = final_provider[0]
    type_segments = final_provider[1::2]
    name_segments = final_provider[2::2]
    extension_resource = len(provider_segments) > 1
    if len(final_provider) > 3:
        parent_parts = parts[:-2]
    elif extension_resource:
        final_provider_marker = max(
            index
            for index, part in enumerate(parts)
            if part.casefold() == "providers"
        )
        parent_parts = parts[:final_provider_marker]
    else:
        parent_parts = parts[:4]
    canonical_resource_id = f"/{'/'.join(parts)}"
    parent_resource_id = f"/{'/'.join(parent_parts)}"
    return WhatIfResourceIdentity(
        resource_type="/".join((namespace, *type_segments)),
        subscription=parts[1],
        resource_group=parts[3],
        name_segments=tuple(name_segments),
        resource_name=name_segments[-1],
        canonical_resource_id=canonical_resource_id,
        parent_resource_id=parent_resource_id,
        scope_resource_id=parent_resource_id,
        extension_resource=extension_resource,
        provider_segments=tuple(provider_segments),
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
