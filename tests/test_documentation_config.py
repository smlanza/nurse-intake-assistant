from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_env_example_documents_acs_email_configuration() -> None:
    env_example = (PROJECT_ROOT / ".env.example").read_text()

    assert "EMAIL_PROVIDER=mock" in env_example
    assert "AI_PROVIDER=mock" in env_example
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
    assert "AI_PROVIDER=mock" in env_example
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


def test_env_example_documents_foundry_ai_placeholders() -> None:
    env_example = (PROJECT_ROOT / ".env.example").read_text()

    assert "AI_PROVIDER=mock" in env_example
    assert "AI_PROVIDER=foundry" in env_example
    assert "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT=" in env_example
    assert "AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT_NAME=" in env_example
    assert "Do not commit" in env_example
    assert "Azure AI keys" in env_example


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
    assert "AI_PROVIDER=mock" in guide
    assert "EMAIL_PROVIDER=mock" in guide
    assert "SMS_PROVIDER=mock" in guide
    assert "DEMO_SUPPRESS_NOTIFICATIONS=false" in guide
    assert "POST /demo/reset" in guide
    assert "POST /intake/text" in guide
    assert "empty" in guide
    assert "whitespace-only" in guide
    assert "too-short" in guide
    assert "does not create cases or notifications" in guide
    assert "Jane Doe" in guide
    assert "medication refill" in guide
    assert "`GET /cases`" in guide
    assert "GET /cases?reviewStatus=PendingReview" in guide
    assert "GET /cases?urgency=Urgent" in guide
    assert "GET /cases?fromDate=YYYY-MM-DD&toDate=YYYY-MM-DD" in guide
    assert "GET /cases/summary" in guide
    assert "GET /cases/summary?fromDate=YYYY-MM-DD&toDate=YYYY-MM-DD" in guide
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
    assert "Mock mode sends no real email or SMS" in guide
    assert "Do not commit" in guide
    assert "connection strings" in guide
    assert "real phone numbers" in guide
    assert "Live ACS SMS" in guide
    assert "toll-free verification" in guide
    assert "Cosmos" in guide
    assert "list/summary" in guide
    assert "future enhancement" in guide


def test_readme_documents_local_mock_demo_walkthrough() -> None:
    readme = (PROJECT_ROOT / "README.md").read_text()

    assert "Local Mock Demo Walkthrough" in readme
    assert "local mock/demo only" in readme
    assert "no production clinical use" in readme
    assert "AI output requires human nurse review" in readme
    assert "uvicorn src.app.main:app --reload" in readme
    assert "http://127.0.0.1:8000/demo" in readme
    assert "APP_MODE=mock" in readme
    assert "AI_PROVIDER=mock" in readme
    assert "EMAIL_PROVIDER=mock" in readme
    assert "SMS_PROVIDER=mock" in readme
    assert "DEMO_SUPPRESS_NOTIFICATIONS=false" in readme
    assert "no real email or SMS" in readme
    assert "Seed Demo Data" in readme
    assert "Load Recent Cases" in readme
    assert "Load Queue Summary" in readme
    assert "Select for Review" in readme
    assert "submit the nurse review" in readme
    assert "submit a text intake" in readme
    assert "submit a voicemail transcript intake" in readme
    assert "mock email/SMS notifications" in readme
    assert "reset demo state" in readme
    assert "docs/demo-smoke-test.md" in readme
    assert "Azure Speech" in readme
    assert "live Azure AI Foundry" in readme
    assert "ACS SMS delivery tracking" in readme


def test_demo_page_smoke_test_guide_exists() -> None:
    guide_path = PROJECT_ROOT / "docs" / "demo-smoke-test.md"

    assert guide_path.exists()

    guide = guide_path.read_text()
    assert "Demo Page Smoke Test" in guide
    assert "uvicorn src.app.main:app --reload" in guide
    assert "http://127.0.0.1:8000/demo" in guide
    assert "submit a text intake" in guide
    assert "submit a voicemail transcript intake" in guide
    assert "confirm recent cases refresh" in guide
    assert "mark a case reviewed" in guide
    assert "confirm the reviewed state is visible" in guide
    assert "reset the demo" in guide
    assert "clean state" in guide
    assert "POST /intake/text" in guide
    assert "GET /cases/summary" in guide
    assert "GET /cases?limit=10" in guide
    assert "POST /cases/{case_id}/review" in guide
    assert "POST /demo/reset" in guide
    assert "returns 200" in guide


def test_progress_links_manual_acs_email_smoke_test() -> None:
    docs_text = (PROJECT_ROOT / "docs" / "progress.md").read_text()

    assert "docs/manual-acs-email-smoke-test.md" in docs_text


def test_progress_workflow_documents_future_tdd_guardrails() -> None:
    docs_text = (PROJECT_ROOT / "docs" / "progress.md").read_text()

    assert "Every future TDD slice must include a `docs/progress.md` update" in docs_text
    assert "ChatGPT should recommend the Codex model and reasoning level" in docs_text
    assert "Model: GPT-5.5" in docs_text
    assert "Reasoning: Medium for normal TDD slices" in docs_text
    assert (
        "Reasoning: High for cross-cutting architecture, risky integration, "
        "or multi-layer refactors"
    ) in docs_text
    assert "Reasoning: Light for docs-only or tiny single-file cleanup" in docs_text
