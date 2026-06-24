import inspect
from typing import Any

from src.app.models.case import CaseDocument


class MissingCasePartitionKeyError(ValueError):
    """Raised when Cosmos case lookup is missing the createdDate partition key."""


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


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value
