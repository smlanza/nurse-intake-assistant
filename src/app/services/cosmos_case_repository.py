import inspect
from datetime import date
from typing import Any

from src.app.models.case import CaseDocument, IntakeStatus, ReviewStatus, Urgency


class MissingCasePartitionKeyError(ValueError):
    """Raised when Cosmos case lookup is missing the createdDate partition key."""


class CaseListNotSupportedError(NotImplementedError):
    """Raised when a repository cannot safely support case list queries yet."""


class CosmosCaseRepository:
    """Persist cases through an injected Cosmos-style container.

    Container injection keeps repository tests independent of Azure and its SDK.
    """

    def __init__(
        self,
        container: Any,
        not_found_exceptions: tuple[type[Exception], ...] = (),
    ) -> None:
        self.container = container
        self.not_found_exceptions = not_found_exceptions

    async def save(self, case: CaseDocument) -> CaseDocument:
        await _maybe_await(self.container.upsert_item(case.model_dump(mode="json")))
        return case

    async def get_by_id(
        self,
        case_id: str,
        created_date: str | None = None,
    ) -> CaseDocument | None:
        if created_date is None:
            raise MissingCasePartitionKeyError(
                "created_date is required for Cosmos case lookup with the "
                "/createdDate partition key"
            )

        try:
            stored_case = await _maybe_await(
                self.container.read_item(
                    item=case_id,
                    partition_key=created_date,
                )
            )
        except self.not_found_exceptions:
            return None

        return CaseDocument.model_validate(stored_case)

    async def get_by_idempotency_key(
        self,
        idempotency_key: str,
    ) -> CaseDocument | None:
        raise NotImplementedError(
            "Cosmos idempotencyKey lookup requires cross-partition query support "
            "and is not implemented in this slice."
        )

    async def list_cases(
        self,
        review_status: ReviewStatus | None = None,
        urgency: Urgency | None = None,
        intake_status: IntakeStatus | None = None,
        intake_complete: bool | None = None,
        source_system: str | None = None,
        case_type: str | None = None,
        notification_email_status: str | None = None,
        notification_sms_status: str | None = None,
        notification_sms_delivery_confirmed: bool | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[CaseDocument]:
        unsupported_filters = {
            "intake_complete": intake_complete,
            "source_system": source_system,
            "case_type": case_type,
            "notification_email_status": notification_email_status,
            "notification_sms_status": notification_sms_status,
            "notification_sms_delivery_confirmed": (
                notification_sms_delivery_confirmed
            ),
        }
        requested_unsupported_filters = [
            name for name, value in unsupported_filters.items() if value is not None
        ]
        if requested_unsupported_filters:
            raise CaseListNotSupportedError(
                "Cosmos case list queries do not yet support filters: "
                + ", ".join(requested_unsupported_filters)
            )

        predicates: list[str] = []
        parameters: list[dict[str, Any]] = []
        if review_status is not None:
            predicates.append("c.reviewStatus = @reviewStatus")
            parameters.append({"name": "@reviewStatus", "value": review_status})
        if urgency is not None:
            predicates.append("c.urgency = @urgency")
            parameters.append({"name": "@urgency", "value": urgency})
        if intake_status is not None:
            predicates.append("c.intakeStatus = @intakeStatus")
            parameters.append({"name": "@intakeStatus", "value": intake_status})
        if from_date is not None:
            predicates.append("c.createdDate >= @fromDate")
            parameters.append({"name": "@fromDate", "value": from_date.isoformat()})
        if to_date is not None:
            predicates.append("c.createdDate <= @toDate")
            parameters.append({"name": "@toDate", "value": to_date.isoformat()})

        query = "SELECT * FROM c"
        if predicates:
            query += " WHERE " + " AND ".join(predicates)
        query += " ORDER BY c.createdUtc DESC"

        query_results = await _maybe_await(
            self.container.query_items(
                query=query,
                parameters=parameters,
                enable_cross_partition_query=True,
            )
        )
        stored_cases = await _collect_items(query_results)
        return [CaseDocument.model_validate(stored_case) for stored_case in stored_cases]


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


async def _collect_items(items: Any) -> list[Any]:
    if hasattr(items, "__aiter__"):
        return [item async for item in items]
    return list(items)
