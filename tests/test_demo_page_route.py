from fastapi.testclient import TestClient

from src.app.main import app


client = TestClient(app)


def test_demo_page_is_served_in_default_mock_mode() -> None:
    response = client.get("/demo")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_demo_page_includes_title_disclaimer_and_existing_endpoints() -> None:
    response = client.get("/demo")

    assert response.status_code == 200
    html = response.text
    assert "Nurse Intake Assistant" in html
    assert "demo intake assistant" in html
    assert "not medical advice" in html
    assert "not for emergencies" in html
    assert "AI output requires nurse review" in html
    assert "/intake/text" in html
    assert "/intake/voicemail-transcript" in html
    assert "/cases/summary" in html
    assert "/cases?limit=10" in html
    assert "/demo/seed" in html
    assert "/demo/reset" in html
    assert "/review" in html


def test_demo_page_includes_guided_workflow_and_sections() -> None:
    response = client.get("/demo")

    assert response.status_code == 200
    html = response.text
    assert "Demo Workflow" in html
    assert "Leave all filters set to Any" in html
    for heading in [
        "Submit Intake",
        "Last Created Case",
        "Nurse Queue",
        "Recent Cases",
        "Queue Summary",
        "Nurse Review",
        "Demo Reset",
    ]:
        assert heading in html


def test_demo_page_includes_seed_demo_data_button() -> None:
    response = client.get("/demo")

    assert response.status_code == 200
    html = response.text
    assert "Seed Demo Data" in html
    assert "seedDemo" in html


def test_demo_page_includes_voicemail_transcript_fields() -> None:
    response = client.get("/demo")

    assert response.status_code == 200
    html = response.text
    assert "Voicemail Transcript Intake" in html
    assert "transcript" in html
    assert "sourceCallId" in html
    assert "sourceRecordingId" in html
    assert "audioBlobName" in html
    assert "callerPhoneNumber" in html
    assert "idempotencyKey" in html


def test_demo_page_includes_queue_filter_controls() -> None:
    response = client.get("/demo")

    assert response.status_code == 200
    html = response.text
    assert "Nurse Queue Filters" in html
    assert "sourceSystem" in html
    assert "caseType" in html
    assert "urgency" in html
    assert "reviewStatus" in html
    assert "intakeComplete" in html
    assert "notificationEmailStatus" in html
    assert "notificationSmsStatus" in html
    assert "notificationSmsDeliveryConfirmed" in html
    assert "URLSearchParams" in html


def test_demo_page_recent_cases_include_select_for_review_affordance() -> None:
    response = client.get("/demo")

    assert response.status_code == 200
    html = response.text
    assert 'data-case-id="${item.id}"' in html
    assert "Select for Review" in html


def test_demo_page_select_for_review_populates_review_case_id() -> None:
    response = client.get("/demo")

    assert response.status_code == 200
    html = response.text
    assert 'const button = event.target.closest("[data-case-id]");' in html
    assert "selectedCaseId.value = button.dataset.caseId;" in html


def test_demo_page_select_for_review_shows_selected_case_status() -> None:
    response = client.get("/demo")

    assert response.status_code == 200
    html = response.text
    assert "Selected case" in html
    assert "for review." in html
