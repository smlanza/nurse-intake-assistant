from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_env_example_documents_acs_email_configuration() -> None:
    env_example = (PROJECT_ROOT / ".env.example").read_text()

    assert "EMAIL_PROVIDER=mock" in env_example
    assert "ACS_EMAIL_CONNECTION_STRING=" in env_example
    assert "ACS_EMAIL_SENDER_ADDRESS=" in env_example
    assert "NURSE_NOTIFICATION_EMAIL=" in env_example
    assert "EMAIL_PROVIDER=acs" in env_example
    assert "only required" in env_example


def test_project_docs_explain_acs_email_configuration() -> None:
    docs_text = (PROJECT_ROOT / "docs" / "progress.md").read_text()

    assert "Mock email remains the default" in docs_text
    assert "EMAIL_PROVIDER=acs" in docs_text
    assert "ACS_EMAIL_CONNECTION_STRING" in docs_text
    assert "ACS_EMAIL_SENDER_ADDRESS" in docs_text
    assert "NURSE_NOTIFICATION_EMAIL" in docs_text
    assert "Real ACS Email sending is not implemented yet" in docs_text
    assert "Do not commit" in docs_text
    assert "connection strings" in docs_text
