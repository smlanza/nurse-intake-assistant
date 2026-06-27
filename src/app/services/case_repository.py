from datetime import date
from typing import Protocol, runtime_checkable

from src.app.models.case import CaseDocument, IntakeStatus, ReviewStatus, Urgency


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

    async def get_by_idempotency_key(
        self,
        idempotency_key: str,
    ) -> CaseDocument | None:
        ...

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

    async def get_by_idempotency_key(
        self,
        idempotency_key: str,
    ) -> CaseDocument | None:
        for case in self._cases.values():
            if case.idempotencyKey == idempotency_key:
                return case
        return None

    def clear(self) -> None:
        self._cases.clear()

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
        cases = list(self._cases.values())
        normalized_source_system = _normalize_optional_filter(source_system)
        normalized_case_type = _normalize_optional_filter(case_type)
        normalized_email_status = _normalize_optional_filter(notification_email_status)
        normalized_sms_status = _normalize_optional_filter(notification_sms_status)

        if review_status is not None:
            cases = [case for case in cases if case.reviewStatus == review_status]

        if urgency is not None:
            cases = [case for case in cases if case.urgency == urgency]

        if intake_status is not None:
            cases = [case for case in cases if case.intakeStatus == intake_status]

        if intake_complete is not None:
            cases = [
                case for case in cases if case.intakeComplete is intake_complete
            ]

        if normalized_source_system is not None:
            cases = [
                case
                for case in cases
                if _normalize_optional_filter(case.sourceSystem)
                == normalized_source_system
            ]

        if normalized_case_type is not None:
            cases = [
                case
                for case in cases
                if _normalize_optional_filter(case.caseType) == normalized_case_type
            ]

        if normalized_email_status is not None:
            cases = [
                case
                for case in cases
                if _normalize_optional_filter(case.notificationEmailStatus)
                == normalized_email_status
            ]

        if normalized_sms_status is not None:
            cases = [
                case
                for case in cases
                if _normalize_optional_filter(case.notificationSmsStatus)
                == normalized_sms_status
            ]

        if notification_sms_delivery_confirmed is not None:
            cases = [
                case
                for case in cases
                if case.notificationSmsDeliveryConfirmed
                is notification_sms_delivery_confirmed
            ]

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

        cases.sort(key=lambda case: case.id)
        cases.sort(key=lambda case: case.createdUtc, reverse=True)

        return cases


def _normalize_optional_filter(value: str | None) -> str | None:
    if value is None:
        return None

    normalized_value = value.strip().casefold()
    return normalized_value or None
