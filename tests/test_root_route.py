from fastapi.testclient import TestClient

from src.app.main import app


client = TestClient(app)


def test_root_route_redirects_to_demo_without_following_redirects() -> None:
    response = client.get("/", follow_redirects=False)

    assert response.status_code in {302, 307}
    assert response.headers["location"] == "/demo"


def test_root_route_redirect_can_be_followed_to_demo_page() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Nurse Intake Assistant" in response.text
    assert "Demo Workflow" in response.text


def test_root_route_redirect_response_does_not_expose_sensitive_fields() -> None:
    response = client.get("/", follow_redirects=False)

    assert response.status_code in {302, 307}
    response_text = response.text
    for sensitive_name in [
        "connectionString",
        "connection_string",
        "key",
        "token",
        "secret",
        "password",
        "endpoint",
        "phoneNumber",
        "phone_number",
        "emailAddress",
        "email_address",
        "credential",
        "provider",
    ]:
        assert sensitive_name not in response_text
