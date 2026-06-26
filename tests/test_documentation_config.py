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


def test_env_example_documents_sms_configuration() -> None:
    env_example = (PROJECT_ROOT / ".env.example").read_text()

    assert "APP_MODE=mock" in env_example
    assert "EMAIL_PROVIDER=mock" in env_example
    assert "ACS_EMAIL_CONNECTION_STRING=" in env_example
    assert "COSMOS_ENDPOINT=" in env_example
    assert "COSMOS_DATABASE_NAME=nurse-intake" in env_example
    assert "SMS_PROVIDER=mock" in env_example
    assert "ACS_SMS_CONNECTION_STRING=" in env_example
    assert "ACS_SMS_FROM_PHONE_NUMBER=" in env_example
    assert "NURSE_NOTIFICATION_PHONE_NUMBER=" in env_example
    assert "SMS_PROVIDER=acs" in env_example
    assert "only required" in env_example
    assert "accesskey=" not in env_example.lower()
    assert "+1" not in env_example
    assert "555" not in env_example


def test_project_docs_explain_acs_email_configuration() -> None:
    docs_text = (PROJECT_ROOT / "docs" / "progress.md").read_text()

    assert "Mock email remains the default" in docs_text
    assert "EMAIL_PROVIDER=acs" in docs_text
    assert "ACS_EMAIL_CONNECTION_STRING" in docs_text
    assert "ACS_EMAIL_SENDER_ADDRESS" in docs_text
    assert "NURSE_NOTIFICATION_EMAIL" in docs_text
    assert "Live ACS Email smoke testing is complete" in docs_text
    assert "Do not commit" in docs_text
    assert "connection strings" in docs_text


def test_requirements_include_acs_email_sdk() -> None:
    requirements = (PROJECT_ROOT / "requirements.txt").read_text()

    assert "azure-communication-email" in requirements


def test_requirements_document_acs_sms_sdk_dependency() -> None:
    requirements = (PROJECT_ROOT / "requirements.txt").read_text()

    assert "fastapi" in requirements
    assert "uvicorn[standard]" in requirements
    assert "pytest" in requirements
    assert "httpx" in requirements
    assert "azure-communication-email" in requirements
    assert "azure-communication-sms" in requirements


def test_manual_acs_email_smoke_test_checklist_exists() -> None:
    checklist_path = PROJECT_ROOT / "docs" / "manual-acs-email-smoke-test.md"

    assert checklist_path.exists()

    checklist = checklist_path.read_text()
    assert "Manual ACS Email Smoke Test" in checklist
    assert "EMAIL_PROVIDER=acs" in checklist
    assert "ACS_EMAIL_CONNECTION_STRING" in checklist
    assert "ACS_EMAIL_SENDER_ADDRESS" in checklist
    assert "NURSE_NOTIFICATION_EMAIL" in checklist
    assert "uvicorn" in checklist
    assert "POST /intake/text" in checklist
    assert "EMAIL_PROVIDER=mock" in checklist
    assert "Do not commit" in checklist
    assert "connection strings" in checklist
    assert "manual" in checklist
    assert "automated tests" in checklist


def test_manual_acs_sms_smoke_test_checklist_exists() -> None:
    checklist_path = PROJECT_ROOT / "docs" / "manual-acs-sms-smoke-test.md"

    assert checklist_path.exists()

    checklist = checklist_path.read_text()
    assert "Manual ACS SMS Smoke Test" in checklist
    assert "Live ACS SMS" in checklist
    assert "not implemented yet" in checklist
    assert "placeholder" in checklist
    assert "future live ACS SMS verification" in checklist
    assert "SMS_PROVIDER=acs" in checklist
    assert "ACS_SMS_CONNECTION_STRING" in checklist
    assert "ACS_SMS_FROM_PHONE_NUMBER" in checklist
    assert "NURSE_NOTIFICATION_PHONE_NUMBER" in checklist
    assert "DEMO_SUPPRESS_NOTIFICATIONS=false" in checklist
    assert "Do not commit" in checklist
    assert "connection strings" in checklist
    assert "access keys" in checklist
    assert "real phone numbers" in checklist
    assert "uvicorn" in checklist
    assert "POST /intake/text" in checklist
    assert "notificationSmsSent=true" in checklist
    assert "notificationEmailSent" in checklist
    assert "independent" in checklist
    assert "should not crash intake processing" in checklist
    assert "notificationSmsSent=false" in checklist
    assert "Azure SMS SDK" in checklist
    assert "create_acs_sms_client" in checklist
    assert "live ACS SMS smoke testing has not been completed" in checklist


def test_manual_local_mock_demo_guide_exists() -> None:
    guide_path = PROJECT_ROOT / "docs" / "manual-local-mock-demo.md"

    assert guide_path.exists()

    guide = guide_path.read_text()
    assert "Local Mock Demo" in guide
    assert "uvicorn" in guide
    assert "APP_MODE=mock" in guide
    assert "EMAIL_PROVIDER=mock" in guide
    assert "SMS_PROVIDER=mock" in guide
    assert "DEMO_SUPPRESS_NOTIFICATIONS=false" in guide
    assert "POST /intake/text" in guide
    assert "Jane Doe" in guide
    assert "medication refill" in guide
    assert "`GET /cases`" in guide
    assert "GET /cases?reviewStatus=PendingReview" in guide
    assert "GET /cases/{case_id}" in guide
    assert "POST /cases/{case_id}/review" in guide
    assert "GET /cases?reviewStatus=Reviewed" in guide
    assert "GET /notifications/email" in guide
    assert "GET /notifications/sms" in guide
    assert "reviewStatus" in guide
    assert "PendingReview" in guide
    assert "Reviewed" in guide
    assert "notificationEmailSent=true" in guide
    assert "notificationSmsSent=true" in guide
    assert "no real email or SMS is sent" in guide
    assert "Do not commit" in guide
    assert "connection strings" in guide
    assert "real phone numbers" in guide
    assert "Live ACS SMS" in guide
    assert "not implemented" in guide


def test_progress_links_manual_acs_email_smoke_test() -> None:
    docs_text = (PROJECT_ROOT / "docs" / "progress.md").read_text()

    assert "docs/manual-acs-email-smoke-test.md" in docs_text
