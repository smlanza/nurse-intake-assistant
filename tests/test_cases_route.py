from fastapi.testclient import TestClient

from src.app.main import app


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


def test_get_case_returns_404_when_case_does_not_exist() -> None:
    response = client.get("/cases/nonexistent-case-id")

    assert response.status_code == 404
