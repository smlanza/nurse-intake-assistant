from typing import Any

from src.app.models.case import CaseDocument


class CosmosCaseRepository:
    """Persist cases through an injected Cosmos-style async container.

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
        await self.container.upsert_item(case.model_dump(mode="json"))
        return case

    async def get_by_id(self, case_id: str) -> CaseDocument | None:
        try:
            stored_case = await self.container.read_item(
                item=case_id,
                partition_key=case_id,
            )
        except self.not_found_exceptions:
            return None

        return CaseDocument.model_validate(stored_case)
