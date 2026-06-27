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
    assert "/cases/summary" in html
    assert "/cases?limit=10" in html
    assert "/demo/reset" in html
    assert "/review" in html
