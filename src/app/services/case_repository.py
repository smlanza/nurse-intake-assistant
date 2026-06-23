from typing import Protocol, runtime_checkable

from src.app.models.case import CaseDocument


@runtime_checkable
class CaseRepository(Protocol):
    """Define storage operations independently of the persistence provider."""

    async def save(self, case: CaseDocument) -> CaseDocument:
        ...

    async def get_by_id(
        self,
        case_id: str,
        created_date: str | None = None,
    ) -> CaseDocument | None:
        ...


class InMemoryCaseRepository:
    """Store cases in process memory for local development and tests."""

    def __init__(self) -> None:
        self._cases: dict[str, CaseDocument] = {}

    async def save(self, case: CaseDocument) -> CaseDocument:
        self._cases[case.id] = case
        return case

    async def get_by_id(
        self,
        case_id: str,
        created_date: str | None = None,
    ) -> CaseDocument | None:
        return self._cases.get(case_id)
