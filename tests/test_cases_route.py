from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.app.main import app
from src.app.models.case import CaseDocument


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
    assert retrieved_case["summary"]
    assert retrieved_case["patient"]
    assert retrieved_case["createdUtc"]


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


def test_get_case_returns_404_when_case_does_not_exist() -> None:
    response = client.get("/cases/nonexistent-case-id")

    assert response.status_code == 404
