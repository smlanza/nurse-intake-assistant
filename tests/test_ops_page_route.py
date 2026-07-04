from fastapi.testclient import TestClient

from src.app.main import app


client = TestClient(app)


def test_ops_page_returns_html() -> None:
    response = client.get("/ops")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_ops_page_lists_safe_routes_and_purposes() -> None:
    response = client.get("/ops")

    assert response.status_code == 200
    html = response.text
    assert "Nurse Intake Assistant Operations" in html
    assert "/health" in html
    assert "liveness check" in html
    assert "/version" in html
    assert "safe service metadata" in html
    assert "/demo" in html
    assert "local mock demo UI" in html
    assert "/demo/status" in html
    assert "local demo readiness status" in html
    assert "/: redirects to /demo" in html


def test_ops_page_includes_safety_wording() -> None:
    response = client.get("/ops")

    assert response.status_code == 200
    html = response.text
    assert "informational only" in html
    assert "does not validate live Azure readiness" in html
    assert (
        "must not expose secrets, provider credentials, connection strings, "
        "phone numbers, email addresses, or patient data"
    ) in html


def test_ops_page_does_not_include_sensitive_examples() -> None:
    response = client.get("/ops")

    assert response.status_code == 200
    html = response.text
    for sensitive_term in [
        "connectionString",
        "key=",
        "token=",
        "password",
        "endpoint=",
        "000-000-0000",
        "555",
        "example.com",
        "nurse@",
        "providerCredential",
    ]:
        assert sensitive_term not in html
