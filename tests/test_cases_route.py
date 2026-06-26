import asyncio
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.app.main import app
from src.app.models.case import CaseDocument, IntakeStatus
from src.app.services.case_repository import InMemoryCaseRepository


client = TestClient(app)


def create_case() -> dict:
    response = client.post(
        "/intake/text",
        json={
            "text": (
                "My name is Jane Doe. DOB: 1980-04-15. "
                "My callback number is +1 (555) 555-0123. "
                "I need a medication refill."
            )
        },
    )
    assert response.status_code == 200
    return response.json()


def create_local_cases_client(
    monkeypatch: pytest.MonkeyPatch,
    repository: object,
) -> TestClient:
    import src.app.routes.cases as cases_route

    monkeypatch.setattr(cases_route, "case_repository", repository)
    test_app = FastAPI()
    test_app.include_router(cases_route.router)
    return TestClient(test_app)


def build_queue_case(
    case_id: str,
    review_status: str = "PendingReview",
    urgency: str = "Routine",
    created_date: str | None = None,
    created_utc: datetime | None = None,
    intake_status: IntakeStatus = "Complete",
    intake_complete: bool = True,
) -> CaseDocument:
    if created_utc is not None:
        now = created_utc
    elif created_date is not None:
        now = datetime.fromisoformat(f"{created_date}T00:00:00+00:00")
    else:
        now = datetime.now(timezone.utc)
    return CaseDocument(
        id=case_id,
        createdDate=created_date or now.date().isoformat(),
        createdUtc=now,
        lastStatusUpdatedUtc=now,
        caseType="text-intake",
        reviewStatus=review_status,
        urgency=urgency,
        intakeStatus=intake_status,
        intakeComplete=intake_complete,
        processingStatus="Completed",
    )


def with_notification_statuses(
    case: CaseDocument,
    email_status: str = "NotAttempted",
    sms_status: str = "NotAttempted",
    sms_delivery_confirmed: bool = False,
) -> CaseDocument:
    case.notificationEmailStatus = email_status
    case.notificationSmsStatus = sms_status
    case.notificationSmsDeliveryConfirmed = sms_delivery_confirmed
    return case


async def save_cases(
    repository: InMemoryCaseRepository,
    cases: list[CaseDocument],
) -> None:
    for case in cases:
        await repository.save(case)


def test_get_case_returns_200_when_case_exists() -> None:
    created_case = create_case()

    response = client.get(f"/cases/{created_case['id']}")

    assert response.status_code == 200
    assert response.json()["id"] == created_case["id"]


def test_get_case_returns_saved_case_document_shape() -> None:
    created_case = create_case()

    response = client.get(f"/cases/{created_case['id']}")

    assert response.status_code == 200
    retrieved_case = response.json()
    assert retrieved_case == created_case
    assert retrieved_case["id"]
    assert retrieved_case["processingStatus"] == "Completed"
    assert retrieved_case["urgency"] == "Routine"
    assert retrieved_case["reviewStatus"] == "PendingReview"
    assert retrieved_case["summary"]
    assert retrieved_case["patient"]
    assert retrieved_case["createdUtc"]


def test_list_cases_returns_empty_list_when_no_cases_exist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = InMemoryCaseRepository()
    local_client = create_local_cases_client(monkeypatch, repository)

    response = local_client.get("/cases")

    assert response.status_code == 200
    assert response.json() == []


def test_list_cases_returns_saved_cases_newest_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = InMemoryCaseRepository()
    asyncio.run(
        save_cases(
            repository,
            [
                build_queue_case(
                    "oldest",
                    created_utc=datetime(2026, 6, 26, 9, 0, tzinfo=timezone.utc),
                ),
                build_queue_case(
                    "newest",
                    created_utc=datetime(2026, 6, 26, 11, 0, tzinfo=timezone.utc),
                ),
                build_queue_case(
                    "middle",
                    created_utc=datetime(2026, 6, 26, 10, 0, tzinfo=timezone.utc),
                ),
            ],
        )
    )
    local_client = create_local_cases_client(monkeypatch, repository)

    response = local_client.get("/cases")

    assert response.status_code == 200
    assert [case["id"] for case in response.json()] == ["newest", "middle", "oldest"]


def test_list_cases_applies_limit_after_sorting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = InMemoryCaseRepository()
    asyncio.run(
        save_cases(
            repository,
            [
                build_queue_case("oldest", created_date="2026-06-24"),
                build_queue_case("middle", created_date="2026-06-25"),
                build_queue_case("newest", created_date="2026-06-26"),
            ],
        )
    )
    local_client = create_local_cases_client(monkeypatch, repository)

    response = local_client.get("/cases?limit=2")

    assert response.status_code == 200
    assert [case["id"] for case in response.json()] == ["newest", "middle"]


def test_list_cases_applies_offset_after_sorting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = InMemoryCaseRepository()
    asyncio.run(
        save_cases(
            repository,
            [
                build_queue_case("oldest", created_date="2026-06-24"),
                build_queue_case("middle", created_date="2026-06-25"),
                build_queue_case("newest", created_date="2026-06-26"),
            ],
        )
    )
    local_client = create_local_cases_client(monkeypatch, repository)

    response = local_client.get("/cases?offset=1")

    assert response.status_code == 200
    assert [case["id"] for case in response.json()] == ["middle", "oldest"]


def test_list_cases_applies_limit_and_offset_together(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = InMemoryCaseRepository()
    asyncio.run(
        save_cases(
            repository,
            [
                build_queue_case("oldest", created_date="2026-06-23"),
                build_queue_case("older", created_date="2026-06-24"),
                build_queue_case("middle", created_date="2026-06-25"),
                build_queue_case("newest", created_date="2026-06-26"),
            ],
        )
    )
    local_client = create_local_cases_client(monkeypatch, repository)

    response = local_client.get("/cases?limit=2&offset=1")

    assert response.status_code == 200
    assert [case["id"] for case in response.json()] == ["middle", "older"]


def test_list_cases_applies_pagination_after_existing_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = InMemoryCaseRepository()
    asyncio.run(
        save_cases(
            repository,
            [
                build_queue_case(
                    "routine-pending-newest",
                    review_status="PendingReview",
                    urgency="Routine",
                    created_date="2026-06-27",
                ),
                build_queue_case(
                    "urgent-pending-newest",
                    review_status="PendingReview",
                    urgency="Urgent",
                    created_date="2026-06-26",
                ),
                build_queue_case(
                    "urgent-pending-middle",
                    review_status="PendingReview",
                    urgency="Urgent",
                    created_date="2026-06-25",
                ),
                build_queue_case(
                    "urgent-pending-oldest",
                    review_status="PendingReview",
                    urgency="Urgent",
                    created_date="2026-06-24",
                ),
                build_queue_case(
                    "urgent-reviewed",
                    review_status="Reviewed",
                    urgency="Urgent",
                    created_date="2026-06-23",
                ),
            ],
        )
    )
    local_client = create_local_cases_client(monkeypatch, repository)

    response = local_client.get(
        "/cases?reviewStatus=PendingReview&urgency=Urgent"
        "&fromDate=2026-06-24&toDate=2026-06-26&limit=1&offset=1"
    )

    assert response.status_code == 200
    assert [case["id"] for case in response.json()] == ["urgent-pending-middle"]


def test_list_cases_filters_by_pending_review_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = InMemoryCaseRepository()
    asyncio.run(
        save_cases(
            repository,
            [
                build_queue_case("pending", review_status="PendingReview"),
                build_queue_case("reviewed", review_status="Reviewed"),
            ],
        )
    )
    local_client = create_local_cases_client(monkeypatch, repository)

    response = local_client.get("/cases?reviewStatus=PendingReview")

    assert response.status_code == 200
    assert [case["id"] for case in response.json()] == ["pending"]


def test_list_cases_filters_by_reviewed_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = InMemoryCaseRepository()
    asyncio.run(
        save_cases(
            repository,
            [
                build_queue_case("pending", review_status="PendingReview"),
                build_queue_case("reviewed", review_status="Reviewed"),
            ],
        )
    )
    local_client = create_local_cases_client(monkeypatch, repository)

    response = local_client.get("/cases?reviewStatus=Reviewed")

    assert response.status_code == 200
    assert [case["id"] for case in response.json()] == ["reviewed"]


def test_list_cases_filters_by_needs_follow_up_intake_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = InMemoryCaseRepository()
    asyncio.run(
        save_cases(
            repository,
            [
                build_queue_case(
                    "complete",
                    intake_status="Complete",
                    intake_complete=True,
                ),
                build_queue_case(
                    "needs-follow-up",
                    intake_status="NeedsFollowUp",
                    intake_complete=False,
                ),
            ],
        )
    )
    local_client = create_local_cases_client(monkeypatch, repository)

    response = local_client.get("/cases?intakeStatus=NeedsFollowUp")

    assert response.status_code == 200
    assert [case["id"] for case in response.json()] == ["needs-follow-up"]


def test_list_cases_filters_by_complete_intake_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = InMemoryCaseRepository()
    asyncio.run(
        save_cases(
            repository,
            [
                build_queue_case(
                    "complete",
                    intake_status="Complete",
                    intake_complete=True,
                ),
                build_queue_case(
                    "needs-follow-up",
                    intake_status="NeedsFollowUp",
                    intake_complete=False,
                ),
            ],
        )
    )
    local_client = create_local_cases_client(monkeypatch, repository)

    response = local_client.get("/cases?intakeStatus=Complete")

    assert response.status_code == 200
    assert [case["id"] for case in response.json()] == ["complete"]


def test_list_cases_filters_by_incomplete_intake(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = InMemoryCaseRepository()
    asyncio.run(
        save_cases(
            repository,
            [
                build_queue_case(
                    "complete",
                    intake_status="Complete",
                    intake_complete=True,
                ),
                build_queue_case(
                    "needs-follow-up",
                    intake_status="NeedsFollowUp",
                    intake_complete=False,
                ),
            ],
        )
    )
    local_client = create_local_cases_client(monkeypatch, repository)

    response = local_client.get("/cases?intakeComplete=false")

    assert response.status_code == 200
    assert [case["id"] for case in response.json()] == ["needs-follow-up"]


def test_list_cases_filters_by_complete_intake(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = InMemoryCaseRepository()
    asyncio.run(
        save_cases(
            repository,
            [
                build_queue_case(
                    "complete",
                    intake_status="Complete",
                    intake_complete=True,
                ),
                build_queue_case(
                    "needs-follow-up",
                    intake_status="NeedsFollowUp",
                    intake_complete=False,
                ),
            ],
        )
    )
    local_client = create_local_cases_client(monkeypatch, repository)

    response = local_client.get("/cases?intakeComplete=true")

    assert response.status_code == 200
    assert [case["id"] for case in response.json()] == ["complete"]


def test_list_cases_filters_by_urgent_urgency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = InMemoryCaseRepository()
    asyncio.run(
        save_cases(
            repository,
            [
                build_queue_case("routine", urgency="Routine"),
                build_queue_case("urgent", urgency="Urgent"),
            ],
        )
    )
    local_client = create_local_cases_client(monkeypatch, repository)

    response = local_client.get("/cases?urgency=Urgent")

    assert response.status_code == 200
    assert [case["id"] for case in response.json()] == ["urgent"]


def test_list_cases_combines_review_status_and_urgency_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = InMemoryCaseRepository()
    asyncio.run(
        save_cases(
            repository,
            [
                build_queue_case(
                    "routine-pending",
                    review_status="PendingReview",
                    urgency="Routine",
                ),
                build_queue_case(
                    "urgent-pending",
                    review_status="PendingReview",
                    urgency="Urgent",
                ),
                build_queue_case(
                    "urgent-reviewed",
                    review_status="Reviewed",
                    urgency="Urgent",
                ),
            ],
        )
    )
    local_client = create_local_cases_client(monkeypatch, repository)

    response = local_client.get("/cases?reviewStatus=PendingReview&urgency=Urgent")

    assert response.status_code == 200
    assert [case["id"] for case in response.json()] == ["urgent-pending"]


def test_list_cases_filters_from_date_inclusive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = InMemoryCaseRepository()
    asyncio.run(
        save_cases(
            repository,
            [
                build_queue_case("older", created_date="2026-06-23"),
                build_queue_case("start", created_date="2026-06-24"),
                build_queue_case("newer", created_date="2026-06-25"),
            ],
        )
    )
    local_client = create_local_cases_client(monkeypatch, repository)

    response = local_client.get("/cases?fromDate=2026-06-24")

    assert response.status_code == 200
    assert [case["id"] for case in response.json()] == ["newer", "start"]


def test_list_cases_filters_to_date_inclusive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = InMemoryCaseRepository()
    asyncio.run(
        save_cases(
            repository,
            [
                build_queue_case("older", created_date="2026-06-23"),
                build_queue_case("end", created_date="2026-06-24"),
                build_queue_case("newer", created_date="2026-06-25"),
            ],
        )
    )
    local_client = create_local_cases_client(monkeypatch, repository)

    response = local_client.get("/cases?toDate=2026-06-24")

    assert response.status_code == 200
    assert [case["id"] for case in response.json()] == ["end", "older"]


def test_list_cases_filters_by_inclusive_date_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = InMemoryCaseRepository()
    asyncio.run(
        save_cases(
            repository,
            [
                build_queue_case("older", created_date="2026-06-22"),
                build_queue_case("start", created_date="2026-06-23"),
                build_queue_case("end", created_date="2026-06-25"),
                build_queue_case("newer", created_date="2026-06-26"),
            ],
        )
    )
    local_client = create_local_cases_client(monkeypatch, repository)

    response = local_client.get("/cases?fromDate=2026-06-23&toDate=2026-06-25")

    assert response.status_code == 200
    assert [case["id"] for case in response.json()] == ["end", "start"]


def test_list_cases_combines_review_status_urgency_and_date_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = InMemoryCaseRepository()
    asyncio.run(
        save_cases(
            repository,
            [
                build_queue_case(
                    "routine-pending-in-range",
                    review_status="PendingReview",
                    urgency="Routine",
                    created_date="2026-06-24",
                ),
                build_queue_case(
                    "urgent-pending-in-range",
                    review_status="PendingReview",
                    urgency="Urgent",
                    created_date="2026-06-24",
                ),
                build_queue_case(
                    "urgent-reviewed-in-range",
                    review_status="Reviewed",
                    urgency="Urgent",
                    created_date="2026-06-24",
                ),
                build_queue_case(
                    "urgent-pending-out-of-range",
                    review_status="PendingReview",
                    urgency="Urgent",
                    created_date="2026-06-26",
                ),
            ],
        )
    )
    local_client = create_local_cases_client(monkeypatch, repository)

    response = local_client.get(
        "/cases?reviewStatus=PendingReview&urgency=Urgent"
        "&fromDate=2026-06-23&toDate=2026-06-25"
    )

    assert response.status_code == 200
    assert [case["id"] for case in response.json()] == ["urgent-pending-in-range"]


def test_list_cases_combines_intake_status_with_existing_filters_and_pagination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = InMemoryCaseRepository()
    asyncio.run(
        save_cases(
            repository,
            [
                build_queue_case(
                    "routine-needs-follow-up-newest",
                    review_status="PendingReview",
                    urgency="Routine",
                    created_date="2026-06-27",
                    intake_status="NeedsFollowUp",
                    intake_complete=False,
                ),
                build_queue_case(
                    "urgent-needs-follow-up-newest",
                    review_status="PendingReview",
                    urgency="Urgent",
                    created_date="2026-06-26",
                    intake_status="NeedsFollowUp",
                    intake_complete=False,
                ),
                build_queue_case(
                    "urgent-needs-follow-up-middle",
                    review_status="PendingReview",
                    urgency="Urgent",
                    created_date="2026-06-25",
                    intake_status="NeedsFollowUp",
                    intake_complete=False,
                ),
                build_queue_case(
                    "urgent-needs-follow-up-oldest",
                    review_status="PendingReview",
                    urgency="Urgent",
                    created_date="2026-06-24",
                    intake_status="NeedsFollowUp",
                    intake_complete=False,
                ),
                build_queue_case(
                    "urgent-complete",
                    review_status="PendingReview",
                    urgency="Urgent",
                    created_date="2026-06-23",
                    intake_status="Complete",
                    intake_complete=True,
                ),
                build_queue_case(
                    "urgent-needs-follow-up-reviewed",
                    review_status="Reviewed",
                    urgency="Urgent",
                    created_date="2026-06-22",
                    intake_status="NeedsFollowUp",
                    intake_complete=False,
                ),
            ],
        )
    )
    local_client = create_local_cases_client(monkeypatch, repository)

    response = local_client.get(
        "/cases?reviewStatus=PendingReview&urgency=Urgent"
        "&intakeStatus=NeedsFollowUp&fromDate=2026-06-24&toDate=2026-06-26"
        "&limit=1&offset=1"
    )

    assert response.status_code == 200
    assert [case["id"] for case in response.json()] == [
        "urgent-needs-follow-up-middle"
    ]


def test_list_cases_rejects_invalid_review_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = InMemoryCaseRepository()
    local_client = create_local_cases_client(monkeypatch, repository)

    response = local_client.get("/cases?reviewStatus=New")

    assert response.status_code == 422


def test_list_cases_rejects_invalid_urgency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = InMemoryCaseRepository()
    local_client = create_local_cases_client(monkeypatch, repository)

    response = local_client.get("/cases?urgency=Emergent")

    assert response.status_code == 422


def test_list_cases_rejects_invalid_intake_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = InMemoryCaseRepository()
    local_client = create_local_cases_client(monkeypatch, repository)

    response = local_client.get("/cases?intakeStatus=Waiting")

    assert response.status_code == 422


def test_list_cases_rejects_invalid_intake_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = InMemoryCaseRepository()
    local_client = create_local_cases_client(monkeypatch, repository)

    response = local_client.get("/cases?intakeComplete=maybe")

    assert response.status_code == 422


def test_list_cases_rejects_invalid_from_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = InMemoryCaseRepository()
    local_client = create_local_cases_client(monkeypatch, repository)

    response = local_client.get("/cases?fromDate=not-a-date")

    assert response.status_code == 422


def test_list_cases_rejects_invalid_to_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = InMemoryCaseRepository()
    local_client = create_local_cases_client(monkeypatch, repository)

    response = local_client.get("/cases?toDate=not-a-date")

    assert response.status_code == 422


@pytest.mark.parametrize("limit", ["0", "-1", "101"])
def test_list_cases_rejects_invalid_limit(
    monkeypatch: pytest.MonkeyPatch,
    limit: str,
) -> None:
    repository = InMemoryCaseRepository()
    local_client = create_local_cases_client(monkeypatch, repository)

    response = local_client.get(f"/cases?limit={limit}")

    assert response.status_code == 422


def test_list_cases_rejects_non_integer_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = InMemoryCaseRepository()
    local_client = create_local_cases_client(monkeypatch, repository)

    response = local_client.get("/cases?limit=two")

    assert response.status_code == 422


@pytest.mark.parametrize("offset", ["-1", "one"])
def test_list_cases_rejects_invalid_offset(
    monkeypatch: pytest.MonkeyPatch,
    offset: str,
) -> None:
    repository = InMemoryCaseRepository()
    local_client = create_local_cases_client(monkeypatch, repository)

    response = local_client.get(f"/cases?offset={offset}")

    assert response.status_code == 422


def test_list_cases_rejects_date_range_when_from_date_is_after_to_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = InMemoryCaseRepository()
    local_client = create_local_cases_client(monkeypatch, repository)

    response = local_client.get("/cases?fromDate=2026-06-26&toDate=2026-06-25")

    assert response.status_code == 400
    assert "fromDate must be on or before toDate" in response.json()["detail"]


def test_list_cases_returns_clear_error_when_repository_does_not_support_listing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RepositoryWithoutListSupport:
        async def list_cases(
            self,
            review_status: str | None = None,
            urgency: str | None = None,
            intake_status: str | None = None,
            intake_complete: bool | None = None,
            from_date: str | None = None,
            to_date: str | None = None,
        ) -> list[CaseDocument]:
            raise NotImplementedError("Case list queries are not implemented.")

    local_client = create_local_cases_client(
        monkeypatch,
        RepositoryWithoutListSupport(),
    )

    response = local_client.get("/cases")

    assert response.status_code == 501
    assert "not implemented" in response.json()["detail"]


def test_case_summary_returns_zero_counts_when_no_cases_exist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = InMemoryCaseRepository()
    local_client = create_local_cases_client(monkeypatch, repository)

    response = local_client.get("/cases/summary")

    assert response.status_code == 200
    assert response.json() == {
        "total": 0,
        "pendingReview": 0,
        "reviewed": 0,
        "urgent": 0,
        "routine": 0,
        "pendingUrgent": 0,
        "completeIntakes": 0,
        "needsFollowUpIntakes": 0,
        "emailMockRecorded": 0,
        "emailAccepted": 0,
        "emailFailed": 0,
        "emailSuppressed": 0,
        "smsMockRecorded": 0,
        "smsAccepted": 0,
        "smsFailed": 0,
        "smsSuppressed": 0,
        "smsDeliveryConfirmed": 0,
    }


def test_case_summary_returns_queue_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = InMemoryCaseRepository()
    asyncio.run(
        save_cases(
            repository,
            [
                build_queue_case(
                    "urgent-pending",
                    review_status="PendingReview",
                    urgency="Urgent",
                ),
                build_queue_case(
                    "routine-pending",
                    review_status="PendingReview",
                    urgency="Routine",
                    intake_status="NeedsFollowUp",
                    intake_complete=False,
                ),
                build_queue_case(
                    "urgent-reviewed",
                    review_status="Reviewed",
                    urgency="Urgent",
                ),
                build_queue_case(
                    "routine-reviewed",
                    review_status="Reviewed",
                    urgency="Routine",
                ),
                build_queue_case(
                    "routine-pending-2",
                    review_status="PendingReview",
                    urgency="Routine",
                    intake_status="NeedsFollowUp",
                    intake_complete=False,
                ),
            ],
        )
    )
    local_client = create_local_cases_client(monkeypatch, repository)

    response = local_client.get("/cases/summary")

    assert response.status_code == 200
    assert response.json() == {
        "total": 5,
        "pendingReview": 3,
        "reviewed": 2,
        "urgent": 2,
        "routine": 3,
        "pendingUrgent": 1,
        "completeIntakes": 3,
        "needsFollowUpIntakes": 2,
        "emailMockRecorded": 0,
        "emailAccepted": 0,
        "emailFailed": 0,
        "emailSuppressed": 0,
        "smsMockRecorded": 0,
        "smsAccepted": 0,
        "smsFailed": 0,
        "smsSuppressed": 0,
        "smsDeliveryConfirmed": 0,
    }


def test_case_summary_returns_notification_status_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = InMemoryCaseRepository()
    asyncio.run(
        save_cases(
            repository,
            [
                with_notification_statuses(
                    build_queue_case("email-mock-sms-mock"),
                    email_status="MockRecorded",
                    sms_status="MockRecorded",
                ),
                with_notification_statuses(
                    build_queue_case("email-accepted-sms-accepted"),
                    email_status="Accepted",
                    sms_status="Accepted",
                    sms_delivery_confirmed=True,
                ),
                with_notification_statuses(
                    build_queue_case("email-failed-sms-failed"),
                    email_status="Failed",
                    sms_status="Failed",
                ),
                with_notification_statuses(
                    build_queue_case("email-suppressed-sms-suppressed"),
                    email_status="Suppressed",
                    sms_status="Suppressed",
                ),
            ],
        )
    )
    local_client = create_local_cases_client(monkeypatch, repository)

    response = local_client.get("/cases/summary")

    assert response.status_code == 200
    summary = response.json()
    assert summary["emailMockRecorded"] == 1
    assert summary["emailAccepted"] == 1
    assert summary["emailFailed"] == 1
    assert summary["emailSuppressed"] == 1
    assert summary["smsMockRecorded"] == 1
    assert summary["smsAccepted"] == 1
    assert summary["smsFailed"] == 1
    assert summary["smsSuppressed"] == 1
    assert summary["smsDeliveryConfirmed"] == 1


def test_case_summary_is_not_paginated_by_limit_or_offset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = InMemoryCaseRepository()
    asyncio.run(
        save_cases(
            repository,
            [
                with_notification_statuses(
                    build_queue_case("case-1"),
                    email_status="MockRecorded",
                    sms_status="MockRecorded",
                ),
                with_notification_statuses(
                    build_queue_case("case-2"),
                    email_status="Accepted",
                    sms_status="Accepted",
                    sms_delivery_confirmed=True,
                ),
                with_notification_statuses(
                    build_queue_case("case-3"),
                    email_status="Failed",
                    sms_status="Failed",
                ),
            ],
        )
    )
    local_client = create_local_cases_client(monkeypatch, repository)

    response = local_client.get("/cases/summary?limit=1&offset=1")

    assert response.status_code == 200
    assert response.json()["total"] == 3
    assert response.json()["completeIntakes"] == 3
    assert response.json()["needsFollowUpIntakes"] == 0
    assert response.json()["emailMockRecorded"] == 1
    assert response.json()["emailAccepted"] == 1
    assert response.json()["emailFailed"] == 1
    assert response.json()["smsMockRecorded"] == 1
    assert response.json()["smsAccepted"] == 1
    assert response.json()["smsFailed"] == 1
    assert response.json()["smsDeliveryConfirmed"] == 1


def test_case_summary_filters_from_date_inclusive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = InMemoryCaseRepository()
    asyncio.run(
        save_cases(
            repository,
            [
                build_queue_case("older", created_date="2026-06-23"),
                build_queue_case("start", created_date="2026-06-24"),
                build_queue_case("newer", created_date="2026-06-25"),
            ],
        )
    )
    local_client = create_local_cases_client(monkeypatch, repository)

    response = local_client.get("/cases/summary?fromDate=2026-06-24")

    assert response.status_code == 200
    assert response.json()["total"] == 2


def test_case_summary_filters_to_date_inclusive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = InMemoryCaseRepository()
    asyncio.run(
        save_cases(
            repository,
            [
                build_queue_case("older", created_date="2026-06-23"),
                build_queue_case("end", created_date="2026-06-24"),
                build_queue_case("newer", created_date="2026-06-25"),
            ],
        )
    )
    local_client = create_local_cases_client(monkeypatch, repository)

    response = local_client.get("/cases/summary?toDate=2026-06-24")

    assert response.status_code == 200
    assert response.json()["total"] == 2


def test_case_summary_filters_by_inclusive_date_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = InMemoryCaseRepository()
    asyncio.run(
        save_cases(
            repository,
            [
                build_queue_case("older", created_date="2026-06-22"),
                build_queue_case("start", created_date="2026-06-23"),
                build_queue_case("end", created_date="2026-06-25"),
                build_queue_case("newer", created_date="2026-06-26"),
            ],
        )
    )
    local_client = create_local_cases_client(monkeypatch, repository)

    response = local_client.get(
        "/cases/summary?fromDate=2026-06-23&toDate=2026-06-25"
    )

    assert response.status_code == 200
    assert response.json()["total"] == 2


def test_case_summary_intake_completion_counts_respect_date_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = InMemoryCaseRepository()
    asyncio.run(
        save_cases(
            repository,
            [
                build_queue_case(
                    "older-incomplete",
                    created_date="2026-06-22",
                    intake_status="NeedsFollowUp",
                    intake_complete=False,
                ),
                build_queue_case(
                    "start-complete",
                    created_date="2026-06-23",
                    intake_status="Complete",
                    intake_complete=True,
                ),
                build_queue_case(
                    "end-incomplete",
                    created_date="2026-06-25",
                    intake_status="NeedsFollowUp",
                    intake_complete=False,
                ),
                build_queue_case(
                    "newer-complete",
                    created_date="2026-06-26",
                    intake_status="Complete",
                    intake_complete=True,
                ),
            ],
        )
    )
    local_client = create_local_cases_client(monkeypatch, repository)

    response = local_client.get(
        "/cases/summary?fromDate=2026-06-23&toDate=2026-06-25"
    )

    assert response.status_code == 200
    assert response.json()["total"] == 2
    assert response.json()["completeIntakes"] == 1
    assert response.json()["needsFollowUpIntakes"] == 1


def test_case_summary_notification_counts_respect_date_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = InMemoryCaseRepository()
    asyncio.run(
        save_cases(
            repository,
            [
                with_notification_statuses(
                    build_queue_case("older-mock", created_date="2026-06-22"),
                    email_status="MockRecorded",
                    sms_status="MockRecorded",
                ),
                with_notification_statuses(
                    build_queue_case("start-accepted", created_date="2026-06-23"),
                    email_status="Accepted",
                    sms_status="Accepted",
                    sms_delivery_confirmed=True,
                ),
                with_notification_statuses(
                    build_queue_case("end-failed", created_date="2026-06-25"),
                    email_status="Failed",
                    sms_status="Failed",
                ),
                with_notification_statuses(
                    build_queue_case("newer-suppressed", created_date="2026-06-26"),
                    email_status="Suppressed",
                    sms_status="Suppressed",
                    sms_delivery_confirmed=True,
                ),
            ],
        )
    )
    local_client = create_local_cases_client(monkeypatch, repository)

    response = local_client.get(
        "/cases/summary?fromDate=2026-06-23&toDate=2026-06-25"
    )

    assert response.status_code == 200
    summary = response.json()
    assert summary["total"] == 2
    assert summary["emailMockRecorded"] == 0
    assert summary["emailAccepted"] == 1
    assert summary["emailFailed"] == 1
    assert summary["emailSuppressed"] == 0
    assert summary["smsMockRecorded"] == 0
    assert summary["smsAccepted"] == 1
    assert summary["smsFailed"] == 1
    assert summary["smsSuppressed"] == 0
    assert summary["smsDeliveryConfirmed"] == 1


def test_case_summary_rejects_invalid_from_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = InMemoryCaseRepository()
    local_client = create_local_cases_client(monkeypatch, repository)

    response = local_client.get("/cases/summary?fromDate=not-a-date")

    assert response.status_code == 422


def test_case_summary_rejects_invalid_to_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = InMemoryCaseRepository()
    local_client = create_local_cases_client(monkeypatch, repository)

    response = local_client.get("/cases/summary?toDate=not-a-date")

    assert response.status_code == 422


def test_case_summary_rejects_date_range_when_from_date_is_after_to_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = InMemoryCaseRepository()
    local_client = create_local_cases_client(monkeypatch, repository)

    response = local_client.get(
        "/cases/summary?fromDate=2026-06-26&toDate=2026-06-25"
    )

    assert response.status_code == 400
    assert "fromDate must be on or before toDate" in response.json()["detail"]


def test_case_summary_returns_clear_error_when_repository_does_not_support_listing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RepositoryWithoutListSupport:
        async def list_cases(
            self,
            review_status: str | None = None,
            urgency: str | None = None,
            from_date: str | None = None,
            to_date: str | None = None,
        ) -> list[CaseDocument]:
            raise NotImplementedError("Case list queries are not implemented.")

    local_client = create_local_cases_client(
        monkeypatch,
        RepositoryWithoutListSupport(),
    )

    response = local_client.get("/cases/summary")

    assert response.status_code == 501
    assert "not implemented" in response.json()["detail"]


def test_review_case_marks_case_reviewed() -> None:
    created_case = create_case()

    response = client.post(
        f"/cases/{created_case['id']}/review",
        json={
            "reviewedBy": "nurse-demo",
            "reviewNotes": "Called patient back and routed to clinic.",
        },
    )

    assert response.status_code == 200
    reviewed_case = response.json()
    assert reviewed_case["id"] == created_case["id"]
    assert reviewed_case["reviewStatus"] == "Reviewed"
    assert reviewed_case["reviewedBy"] == "nurse-demo"
    assert reviewed_case["reviewNotes"] == "Called patient back and routed to clinic."
    assert reviewed_case["reviewedAt"] is not None
    datetime.fromisoformat(reviewed_case["reviewedAt"])

    saved_response = client.get(f"/cases/{created_case['id']}")
    assert saved_response.status_code == 200
    assert saved_response.json()["reviewStatus"] == "Reviewed"


def test_review_case_allows_incomplete_intake_case() -> None:
    create_response = client.post(
        "/intake/text",
        json={"text": "I have a cough and fever."},
    )
    assert create_response.status_code == 200
    created_case = create_response.json()
    assert created_case["intakeComplete"] is False
    assert created_case["reviewStatus"] == "PendingReview"

    response = client.post(
        f"/cases/{created_case['id']}/review",
        json={
            "reviewedBy": "nurse-demo",
            "reviewNotes": "Called patient to collect missing fields.",
        },
    )

    assert response.status_code == 200
    reviewed_case = response.json()
    assert reviewed_case["id"] == created_case["id"]
    assert reviewed_case["intakeComplete"] is False
    assert reviewed_case["missingFields"] == [
        "patient.name",
        "patient.date_of_birth",
        "patient.callback_number",
    ]
    assert reviewed_case["reviewStatus"] == "Reviewed"
    assert reviewed_case["reviewedBy"] == "nurse-demo"
    assert reviewed_case["reviewedAt"] is not None


def test_review_case_trims_reviewer_and_notes() -> None:
    created_case = create_case()

    response = client.post(
        f"/cases/{created_case['id']}/review",
        json={
            "reviewedBy": "  nurse-demo  ",
            "reviewNotes": "  Called patient back.  ",
        },
    )

    assert response.status_code == 200
    reviewed_case = response.json()
    assert reviewed_case["reviewStatus"] == "Reviewed"
    assert reviewed_case["reviewedBy"] == "nurse-demo"
    assert reviewed_case["reviewNotes"] == "Called patient back."
    assert reviewed_case["reviewedAt"] is not None
    datetime.fromisoformat(reviewed_case["reviewedAt"])


@pytest.mark.parametrize("review_notes", ["", "   "])
def test_review_case_stores_blank_review_notes_as_none(
    review_notes: str,
) -> None:
    created_case = create_case()

    response = client.post(
        f"/cases/{created_case['id']}/review",
        json={
            "reviewedBy": "nurse-demo",
            "reviewNotes": review_notes,
        },
    )

    assert response.status_code == 200
    reviewed_case = response.json()
    assert reviewed_case["reviewStatus"] == "Reviewed"
    assert reviewed_case["reviewedBy"] == "nurse-demo"
    assert reviewed_case["reviewNotes"] is None
    assert reviewed_case["reviewedAt"] is not None


@pytest.mark.parametrize("reviewed_by", ["", "   "])
def test_review_case_rejects_blank_reviewer(reviewed_by: str) -> None:
    created_case = create_case()

    response = client.post(
        f"/cases/{created_case['id']}/review",
        json={
            "reviewedBy": reviewed_by,
            "reviewNotes": "Called patient back.",
        },
    )

    assert response.status_code == 422


def test_review_case_returns_404_when_case_does_not_exist() -> None:
    response = client.post(
        "/cases/nonexistent-case-id/review",
        json={
            "reviewedBy": "nurse-demo",
            "reviewNotes": "No matching case exists.",
        },
    )

    assert response.status_code == 404


def test_get_case_passes_created_date_query_parameter_to_repository(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.app.routes.cases as cases_route

    class RecordingCaseRepository:
        def __init__(self) -> None:
            self.case_id: str | None = None
            self.created_date: str | None = None

        async def get_by_id(
            self,
            case_id: str,
            created_date: str | None = None,
        ) -> CaseDocument:
            self.case_id = case_id
            self.created_date = created_date
            now = datetime.now(timezone.utc)
            return CaseDocument(
                id=case_id,
                createdDate="2026-06-23",
                createdUtc=now,
                lastStatusUpdatedUtc=now,
                caseType="text-intake",
                processingStatus="Completed",
            )

    repository = RecordingCaseRepository()
    monkeypatch.setattr(cases_route, "case_repository", repository)
    test_app = FastAPI()
    test_app.include_router(cases_route.router)
    local_client = TestClient(test_app)

    response = local_client.get("/cases/case-123?createdDate=2026-06-23")

    assert response.status_code == 200
    assert repository.case_id == "case-123"
    assert repository.created_date == "2026-06-23"


def test_get_case_returns_client_error_when_created_date_is_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.app.routes.cases as cases_route
    from src.app.services.cosmos_case_repository import MissingCasePartitionKeyError

    class CosmosStyleRepository:
        async def get_by_id(
            self,
            case_id: str,
            created_date: str | None = None,
        ) -> CaseDocument | None:
            raise MissingCasePartitionKeyError(
                "created_date is required for Cosmos case lookup with the "
                "/createdDate partition key"
            )

    monkeypatch.setattr(cases_route, "case_repository", CosmosStyleRepository())
    test_app = FastAPI()
    test_app.include_router(cases_route.router)
    local_client = TestClient(test_app)

    response = local_client.get("/cases/case-123")

    assert response.status_code == 400
    assert "createdDate" in response.json()["detail"]


def test_review_case_returns_client_error_when_created_date_is_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.app.routes.cases as cases_route
    from src.app.services.cosmos_case_repository import MissingCasePartitionKeyError

    class CosmosStyleRepository:
        async def get_by_id(
            self,
            case_id: str,
            created_date: str | None = None,
        ) -> CaseDocument | None:
            raise MissingCasePartitionKeyError(
                "created_date is required for Cosmos case lookup with the "
                "/createdDate partition key"
            )

        async def save(self, case: CaseDocument) -> CaseDocument:
            raise AssertionError("Review should not save when lookup fails")

    monkeypatch.setattr(cases_route, "case_repository", CosmosStyleRepository())
    test_app = FastAPI()
    test_app.include_router(cases_route.router)
    local_client = TestClient(test_app)

    response = local_client.post(
        "/cases/case-123/review",
        json={
            "reviewedBy": "nurse-demo",
            "reviewNotes": "Called patient back and routed to clinic.",
        },
    )

    assert response.status_code == 400
    assert "createdDate" in response.json()["detail"]


def test_review_case_passes_created_date_and_saves_updated_case(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.app.routes.cases as cases_route

    class RecordingCaseRepository:
        def __init__(self) -> None:
            self.case_id: str | None = None
            self.created_date: str | None = None
            self.saved_case: CaseDocument | None = None

        async def get_by_id(
            self,
            case_id: str,
            created_date: str | None = None,
        ) -> CaseDocument:
            self.case_id = case_id
            self.created_date = created_date
            now = datetime.now(timezone.utc)
            return CaseDocument(
                id=case_id,
                createdDate="2026-06-23",
                createdUtc=now,
                lastStatusUpdatedUtc=now,
                caseType="text-intake",
                processingStatus="Completed",
            )

        async def save(self, case: CaseDocument) -> CaseDocument:
            self.saved_case = case
            return case

    repository = RecordingCaseRepository()
    monkeypatch.setattr(cases_route, "case_repository", repository)
    test_app = FastAPI()
    test_app.include_router(cases_route.router)
    local_client = TestClient(test_app)

    response = local_client.post(
        "/cases/case-123/review?createdDate=2026-06-23",
        json={
            "reviewedBy": "nurse-demo",
            "reviewNotes": "Called patient back and routed to clinic.",
        },
    )

    assert response.status_code == 200
    assert repository.case_id == "case-123"
    assert repository.created_date == "2026-06-23"
    assert repository.saved_case is not None
    assert repository.saved_case.reviewStatus == "Reviewed"
    assert repository.saved_case.reviewedBy == "nurse-demo"
    assert repository.saved_case.reviewNotes == "Called patient back and routed to clinic."
    assert repository.saved_case.reviewedAt is not None


def test_get_case_allows_missing_created_date_when_repository_does_not_require_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.app.routes.cases as cases_route

    class MockStyleRepository:
        async def get_by_id(
            self,
            case_id: str,
            created_date: str | None = None,
        ) -> CaseDocument:
            now = datetime.now(timezone.utc)
            return CaseDocument(
                id=case_id,
                createdDate="2026-06-23",
                createdUtc=now,
                lastStatusUpdatedUtc=now,
                caseType="text-intake",
                processingStatus="Completed",
            )

    monkeypatch.setattr(cases_route, "case_repository", MockStyleRepository())
    test_app = FastAPI()
    test_app.include_router(cases_route.router)
    local_client = TestClient(test_app)

    response = local_client.get("/cases/case-123")

    assert response.status_code == 200
    assert response.json()["id"] == "case-123"


def test_get_case_returns_404_when_case_does_not_exist() -> None:
    response = client.get("/cases/nonexistent-case-id")

    assert response.status_code == 404
