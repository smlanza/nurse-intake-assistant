from fastapi.testclient import TestClient

from src.app.main import app


def test_static_privacy_policy_page_is_served() -> None:
    client = TestClient(app)

    response = client.get("/static/privacy.html")

    assert response.status_code == 200
    assert "Privacy Policy" in response.text
    assert "This document is not a HIPAA Notice of Privacy Practices" in response.text
    assert "[Data Retention Period]" in response.text


def test_static_terms_page_is_served() -> None:
    client = TestClient(app)

    response = client.get("/static/terms.html")

    assert response.status_code == 200
    assert "Terms of Use" in response.text
    assert "Not Medical Advice" in response.text
    assert "[Governing Law Placeholder" in response.text
