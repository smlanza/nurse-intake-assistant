from typing import Protocol

from src.app.models.case import CaseDocument


class CaseRepository(Protocol):
    async def save(self, case: CaseDocument) -> CaseDocument:
        ...

    async def get_by_id(self, case_id: str) -> CaseDocument | None:
        ...


class InMemoryCaseRepository:
    def __init__(self) -> None:
        self._cases: dict[str, CaseDocument] = {}

    async def save(self, case: CaseDocument) -> CaseDocument:
        self._cases[case.id] = case
        return case

    async def get_by_id(self, case_id: str) -> CaseDocument | None:
        return self._cases.get(case_id)
