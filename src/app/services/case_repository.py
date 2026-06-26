from datetime import date
from typing import Protocol, runtime_checkable

from src.app.models.case import CaseDocument, ReviewStatus, Urgency


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

    async def list_cases(
        self,
        review_status: ReviewStatus | None = None,
        urgency: Urgency | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[CaseDocument]:
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

    def clear(self) -> None:
        self._cases.clear()

    async def list_cases(
        self,
        review_status: ReviewStatus | None = None,
        urgency: Urgency | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[CaseDocument]:
        cases = list(self._cases.values())

        if review_status is not None:
            cases = [case for case in cases if case.reviewStatus == review_status]

        if urgency is not None:
            cases = [case for case in cases if case.urgency == urgency]

        if from_date is not None:
            cases = [
                case
                for case in cases
                if case.createdDate >= from_date.isoformat()
            ]

        if to_date is not None:
            cases = [
                case
                for case in cases
                if case.createdDate <= to_date.isoformat()
            ]

        return cases
