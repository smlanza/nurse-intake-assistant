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


def test_env_example_documents_foundry_agent_placeholders() -> None:
    env_example = (PROJECT_ROOT / ".env.example").read_text()

    assert "AGENT_PROVIDER=mock" in env_example
    assert "AGENT_PROVIDER=foundry-agent" in env_example
    assert "AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT=" in env_example
    assert "AZURE_AI_FOUNDRY_AGENT_ID=" in env_example
    assert "offline-safe client boundary" in env_example
    assert "Do not commit" in env_example
    assert "PHI" in env_example
    assert "AZURE_AI_FOUNDRY_AGENT_ID=agent-" not in env_example
    assert "services.ai.azure.com/api/projects/" not in env_example
    assert "accesskey=" not in env_example.lower()


def test_foundry_local_env_example_documents_openai_endpoint_placeholder() -> None:
    env_example = (PROJECT_ROOT / ".env.foundry.local.example").read_text()

    assert "AI_PROVIDER=foundry" in env_example
    assert "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT=" in env_example
    assert (
        "AZURE_OPENAI_ENDPOINT=https://example-openai-resource.openai.azure.com/"
        in env_example
    )
    assert "AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT_NAME=" in env_example
    assert "API_KEY" not in env_example
    assert "accesskey=" not in env_example.lower()


def test_foundry_agent_local_env_example_documents_placeholders() -> None:
    env_example_path = PROJECT_ROOT / ".env.foundry-agent.local.example"

    assert env_example_path.exists()

    env_example = env_example_path.read_text()
    assert "AGENT_PROVIDER=foundry-agent" in env_example
    assert (
        "AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT="
        "<your-foundry-agent-project-endpoint>"
    ) in env_example
    assert "AZURE_AI_FOUNDRY_AGENT_ID=<your-foundry-agent-id>" in env_example
    assert "Do not commit real values" in env_example
    assert "services.ai.azure.com/api/projects/" not in env_example
    assert "secret" not in env_example.lower()
    assert "accesskey=" not in env_example.lower()
    assert "bearer" not in env_example.lower()


def test_env_example_documents_speech_placeholders() -> None:
    env_example = (PROJECT_ROOT / ".env.example").read_text()

    assert "SPEECH_PROVIDER=mock" in env_example
    assert "SPEECH_PROVIDER=azure" in env_example
    assert "AZURE_SPEECH_ENDPOINT=" in env_example
    assert "AZURE_SPEECH_REGION=" in env_example
    assert "already-transcribed text" in env_example
    assert "Live Azure Speech transcription/audio processing is deferred" in env_example
    assert "keys" in env_example


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
    normalized_checklist = " ".join(checklist.split())
    assert "Manual ACS Email Smoke Test" in checklist
    assert "EMAIL_PROVIDER=acs" in checklist
    assert "ACS_EMAIL_CONNECTION_STRING" in checklist
    assert "ACS_EMAIL_SENDER_ADDRESS" in checklist
    assert "NURSE_NOTIFICATION_EMAIL" in checklist
    assert "python scripts/smoke_acs_email.py --check" in checklist
    assert "creates no ACS Email client" in normalized_checklist
    assert "makes no Azure calls" in normalized_checklist
    assert "sends no email" in normalized_checklist
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
    normalized_checklist = " ".join(checklist.split())
    assert "Manual ACS SMS Smoke Test" in checklist
    assert "Live ACS SMS" in checklist
    assert "not implemented yet" in checklist
    assert "placeholder" in checklist
    assert "future live ACS SMS verification" in checklist
    assert "SMS_PROVIDER=acs" in checklist
    assert "ACS_SMS_CONNECTION_STRING" in checklist
    assert "ACS_SMS_FROM_PHONE_NUMBER" in checklist
    assert "NURSE_NOTIFICATION_PHONE_NUMBER" in checklist
    assert "python scripts/smoke_acs_sms.py --check" in checklist
    assert "creates no ACS SMS client" in normalized_checklist
    assert "makes no Azure network call" in normalized_checklist
    assert "sends no SMS" in normalized_checklist
    assert "toll-free verification, carrier, and Azure regulatory workflow" in checklist
    assert "DEMO_SUPPRESS_NOTIFICATIONS=false" in checklist
    assert "SMS_PROVIDER=mock" in checklist
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
    assert "python -m venv .venv" in readme
    assert "source .venv/bin/activate" in readme
    assert "pip install -r requirements.txt" in readme
    assert "python -m pytest" in readme
    assert "uvicorn src.app.main:app --reload" in readme
    assert "http://127.0.0.1:8000/demo" in readme
    assert "APP_MODE=mock" in readme
    assert "AI_PROVIDER=mock" in readme
    assert "SPEECH_PROVIDER=mock" in readme
    assert "EMAIL_PROVIDER=mock" in readme
    assert "SMS_PROVIDER=mock" in readme
    assert "DEMO_SUPPRESS_NOTIFICATIONS=false" in readme
    assert "does not call Azure" in readme
    assert "does not call models" in readme
    assert "does not process audio" in readme
    assert "no real email or SMS" in readme
    assert "explicit provider environment variables and credentials" in readme
    assert "no real Azure resource identifiers" in readme
    assert "Seed Demo Data" in readme
    assert "Load Recent Cases" in readme
    assert "Load Queue Summary" in readme
    assert "Select for Review" in readme
    assert "Load Handoff Note" in readme
    assert "submit the nurse review" in readme
    assert "submit a text intake" in readme
    assert "submit a voicemail transcript intake" in readme
    assert "mock email/SMS notifications" in readme
    assert "reset demo state" in readme
    assert "docs/system-overview.md" in readme
    assert "docs/demo-smoke-test.md" in readme
    assert "python scripts/preflight.py --all" in readme
    assert "Azure Speech" in readme
    assert "live Azure AI Foundry" in readme
    assert "ACS SMS delivery tracking" in readme


def test_readme_documents_current_live_smoke_status() -> None:
    readme = (PROJECT_ROOT / "README.md").read_text()
    normalized_readme = " ".join(readme.split())

    assert "## Current Status" in readme
    assert "mock mode remains the primary interview/demo path" in readme
    assert "Automated tests: offline only" in readme
    assert "no Azure calls" in readme
    assert "Live Azure OpenAI / Foundry structured extraction" in readme
    assert "manually smoke-tested with fictional medication-refill input" in normalized_readme
    assert "--live-client-mode azure-openai-endpoint" in readme
    assert "not production clinical software" in readme
    assert "requires nurse review before any clinical action" in readme
    assert "do not use real PHI" in readme
    assert "real endpoint values" in normalized_readme
    assert "no Azure calls, model calls" in normalized_readme
    assert "docs/demo-readiness-checklist.md" in readme


def test_demo_readiness_checklist_exists() -> None:
    checklist_path = PROJECT_ROOT / "docs" / "demo-readiness-checklist.md"

    assert checklist_path.exists()

    checklist = checklist_path.read_text()
    normalized_checklist = " ".join(checklist.split())
    assert "Demo Readiness Checklist" in checklist
    assert "local mock demo" in checklist
    assert "source .venv/bin/activate" in checklist
    assert "pip install -r requirements.txt" in checklist
    assert "python -m pytest" in checklist
    assert "uvicorn src.app.main:app --reload" in checklist
    assert "http://127.0.0.1:8000/demo" in checklist
    assert "demo reset" in checklist
    assert "Submit a fictional text intake" in checklist
    assert "Load the nurse handoff note" in checklist
    assert "mock email/SMS notifications" in checklist
    assert "Manual Azure OpenAI / Foundry structured extraction smoke" in checklist
    assert "--live-client-mode azure-openai-endpoint" in checklist
    assert "manual smoke script only" in checklist
    assert "Automated tests remain offline" in checklist
    assert "Nurse review is required" in checklist
    assert "Urgency output is advisory only" in checklist
    assert "no real PHI" in checklist
    assert "Do Not Claim" in checklist
    assert "Do not claim production readiness" in checklist
    assert "replaces nurse judgment" in checklist
    assert "Do not claim Azure hosting unless separately deployed" in checklist
    assert "If tests fail, do not demo live changes" in checklist
    assert "endpoint values" in checklist
    assert "deployment names" in checklist


def test_readme_documents_current_demo_claims_boundary() -> None:
    readme = (PROJECT_ROOT / "README.md").read_text()

    assert "## Demo Claims" in readme
    assert "human nurse review is required" in readme
    assert "fictional/demo data only" in readme
    assert "no secrets or PHI" in readme
    assert "local text intake" in readme
    assert "already-transcribed voicemail transcript intake" in readme
    assert "deterministic mock AI extraction" in readme
    assert "urgency classification" in readme
    assert "nurse review workflow" in readme
    assert "queue/recent case views and summary counts" in readme
    assert "deterministic handoff notes" in readme
    assert "mock email/SMS notification inspection" in readme
    assert "offline-safe consolidated preflight checks" in readme
    assert "must not claim production clinical readiness" in readme
    assert "autonomous medical decision-making" in readme
    assert "live Azure AI Foundry extraction" in readme
    assert "live Azure Speech transcription" in readme
    assert "live phone intake/call automation" in readme
    assert "confirmed ACS SMS handset delivery" in readme
    assert "hosting/auth/Key Vault/retry/durable processing" in readme
    assert "default mock mode makes no Azure calls" in readme
    assert "model calls" in readme
    assert "audio processing" in readme
    assert "repository reads/writes/queries" in readme
    assert "email sends" in readme
    assert "SMS sends" in readme


def test_readme_documents_consolidated_preflight_output() -> None:
    readme = (PROJECT_ROOT / "README.md").read_text()
    normalized_readme = " ".join(readme.split()).lower()

    assert "Cosmos Repository" in readme
    assert "Foundry Agent" in readme
    assert "SKIP Cosmos Repository" in readme
    assert "SKIP Foundry Agent" in readme
    assert "SKIP is expected and safe" in readme
    assert "Guidance:" in readme
    assert "Guidance: Keep" not in readme
    assert (
        "For the local demo, keep APP_MODE, AI_PROVIDER, AGENT_PROVIDER, "
        "SPEECH_PROVIDER, EMAIL_PROVIDER, and SMS_PROVIDER set to mock."
    ) in readme
    assert (
        "Enable one live provider at a time only for explicit manual smoke testing."
        in readme
    )
    assert "This preflight remains offline-safe and does not call Azure." in readme
    assert "Next step:" not in readme
    assert "Preflight summary:" in readme
    assert "PASS=0, SKIP=6, FAIL=0" in readme
    assert "python scripts/preflight.py --foundry-agent" in readme
    assert "No Foundry Agent client" in readme
    assert "no agent was invoked" in normalized_readme
    assert "Completed safely with no failed checks" in readme
    assert "No Azure clients" in readme
    assert "Azure calls" in readme
    assert "model calls" in readme
    assert "agent calls" in readme
    assert "audio processing" in readme
    assert "repository reads/writes/queries" in readme
    assert "email sends" in readme
    assert "SMS sends" in readme


def test_readme_documents_consolidated_preflight_safe_failure_output() -> None:
    readme = (PROJECT_ROOT / "README.md").read_text()

    assert "FAIL means required configuration is missing" in readme
    assert "explicitly enabled provider" in readme
    assert "not that a live service call failed" in readme
    assert "APP_MODE=cosmos" in readme
    assert "FAIL Cosmos Repository" in readme
    assert "COSMOS_ENDPOINT" in readme
    assert "COSMOS_KEY" in readme
    assert "COSMOS_DATABASE_NAME" in readme
    assert "COSMOS_CONTAINER_NAME" in readme
    assert "Guidance:" in readme
    assert "Preflight summary:" in readme
    assert "PASS=0, SKIP=5, FAIL=1" in readme
    assert "FAIL=1" in readme
    assert "- Cosmos Repository: Set missing Cosmos variables or restore APP_MODE=mock." in readme
    assert (
        "A FAIL result means required local configuration is missing; this "
        "preflight did not call Azure."
    ) in readme
    assert "exit code 1" in readme
    assert "missing variable names" in readme
    assert "secret values are not printed" in readme
    assert "No Azure clients" in readme
    assert "Azure calls" in readme
    assert "model calls" in readme
    assert "audio processing" in readme
    assert "repository reads/writes/queries" in readme
    assert "email sends" in readme
    assert "SMS sends" in readme


def test_readme_documents_provider_mode_matrix() -> None:
    readme = (PROJECT_ROOT / "README.md").read_text()

    assert "## Provider Mode Matrix" in readme
    for scenario in [
        "Default local demo mode",
        "Foundry Agent smoke-test mode",
        "ACS Email smoke-test mode",
        "ACS SMS smoke-test mode",
        "Azure Speech smoke-test mode",
        "Cosmos persistence smoke-test mode",
    ]:
        assert scenario in readme
    for setting_name in [
        "APP_MODE",
        "AI_PROVIDER",
        "AGENT_PROVIDER",
        "SPEECH_PROVIDER",
        "EMAIL_PROVIDER",
        "SMS_PROVIDER",
    ]:
        assert setting_name in readme


def test_readme_documents_independent_provider_toggles() -> None:
    readme = (PROJECT_ROOT / "README.md").read_text()
    normalized_readme = " ".join(readme.split())

    assert "provider settings are independent adapter toggles" in normalized_readme
    assert "not an all-or-nothing Azure switch" in normalized_readme
    assert (
        "APP_MODE selects the app runtime/storage posture; it does not "
        "automatically switch every provider to Azure"
    ) in normalized_readme
    assert "Do not introduce APP_MODE=azure" in readme


def test_readme_documents_foundry_agent_smoke_mode_with_mock_providers() -> None:
    readme = (PROJECT_ROOT / "README.md").read_text()
    normalized_readme = " ".join(readme.split())

    assert "Foundry Agent smoke-test mode" in readme
    assert "AGENT_PROVIDER=foundry-agent" in readme
    assert "AGENT_PROVIDER=foundry" in readme
    assert "APP_MODE=mock" in readme
    assert "AI_PROVIDER=mock" in readme
    assert "EMAIL_PROVIDER=mock" in readme
    assert "SMS_PROVIDER=mock" in readme
    assert "SPEECH_PROVIDER=mock" in readme
    assert (
        "AGENT_PROVIDER=foundry-agent or the AGENT_PROVIDER=foundry smoke "
        "alias while APP_MODE, AI_PROVIDER, EMAIL_PROVIDER, SMS_PROVIDER, and "
        "SPEECH_PROVIDER remain mock"
    ) in normalized_readme


def test_manual_foundry_doc_documents_agent_smoke_cli_safety() -> None:
    doc = (PROJECT_ROOT / "docs" / "manual-foundry-smoke-test.md").read_text()
    normalized_doc = " ".join(doc.split())

    assert "Foundry Agent Smoke CLI" in doc
    assert "python scripts/smoke_foundry_agent.py --print-agent-instructions" in doc
    assert "versioned instruction pack" in normalized_doc
    assert "safe to copy into Azure AI Foundry Agent configuration" in normalized_doc
    assert "local `NurseIntakeAgent` output contract" in doc
    assert "Human nurse review remains mandatory" in doc
    assert "python scripts/smoke_foundry_agent.py --check" in doc
    assert "python scripts/smoke_foundry_agent.py --live" in doc
    assert (
        "python scripts/smoke_foundry_agent.py --env-file "
        ".env.foundry-agent.local --check"
    ) in doc
    assert (
        "python scripts/smoke_foundry_agent.py --env-file "
        ".env.foundry-agent.local --live"
    ) in doc
    assert "Shell environment variables override env-file values" in doc
    assert "--check does not call Azure" in doc
    assert "No Foundry Agent client is created in --check mode" in normalized_doc
    assert "--live remains manual and opt-in" in doc
    assert "fictional data only" in normalized_doc
    assert "default local demo remains mock/offline" in normalized_doc
    assert "--live --json" in doc
    assert "--live --diagnose" in doc
    assert "az login" in doc
    assert "safe root-cause exception class name" in doc
    assert "safe status code from the exception chain" in normalized_doc
    assert "endpoint, agent ID, SDK compatibility, agent availability, or request shape" in normalized_doc
    assert "agent_output_valid" in doc
    assert "recommended_next_step" in doc
    assert "Do not claim live Foundry Agent behavior" in doc
    assert "authentication_or_authorization_failed" in doc
    assert "azure_request_failed" in doc
    assert "unexpected_error" in doc
    assert "sdk_unavailable" in doc
    assert "contract_invalid" in doc
    assert "does not make the app production clinical software" in normalized_doc
    assert "AGENT_PROVIDER=mock" in doc


def test_readme_documents_smoke_scripts_are_explicitly_invoked_checks() -> None:
    readme = (PROJECT_ROOT / "README.md").read_text()
    normalized_readme = " ".join(readme.split())

    assert "Smoke-test scripts are automated checks that are manually invoked" in readme
    assert "unless wired into CI/CD" in readme
    for script_name in [
        "scripts/smoke_foundry_agent.py",
        "scripts/smoke_acs_email.py",
        "scripts/smoke_acs_sms.py",
        "scripts/smoke_speech_transcription.py",
        "docs/manual-cosmos-smoke-test.md",
    ]:
        assert script_name in readme
    assert "not run by app startup, /demo, or /demo/status" in normalized_readme


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


def test_manual_foundry_smoke_test_guide_exists() -> None:
    guide_path = PROJECT_ROOT / "docs" / "manual-foundry-smoke-test.md"

    assert guide_path.exists()

    guide = guide_path.read_text()
    normalized_guide = " ".join(guide.split())
    assert "Manual Foundry Smoke Test" in guide
    assert "automated test suite must remain offline" in normalized_guide
    assert "must not call Azure" in normalized_guide
    assert "AI_PROVIDER=mock" in guide
    assert "AI_PROVIDER=foundry" in guide
    assert "scripts/smoke_foundry_extraction.py" in guide
    assert "--check" in guide
    assert "--live" in guide
    assert "--env-file .env.foundry.local --check" in guide
    assert "--env-file .env.foundry.local --live" in guide
    assert "--env-file .env.foundry.local --live --diagnose" in guide
    assert "Troubleshoot With Diagnose" in guide
    assert "endpoint shape classification" in guide
    assert "foundry-project-endpoint" in guide
    assert "endpoint/client compatibility" in normalized_guide
    assert "services.ai.azure.com" in guide
    assert "openai.azure.com" in guide
    assert "azure-openai-endpoint" in guide
    assert "--live --diagnose --live-client-mode azure-openai-endpoint" in guide
    assert "API key support is not added" in guide
    assert "Microsoft Entra bearer-token provider auth" in normalized_guide
    assert "Azure OpenAI v1 path shape" in guide
    assert "/openai/v1/" in guide
    assert "provided with or without `/openai/v1`" in guide
    assert "OpenAI `model` parameter" in guide
    assert "openai-v1" in guide
    assert "openai.azure.com/openai/v1" in guide
    assert "model parameter source" in normalized_guide
    assert "sanitized `404`" in guide
    assert "validated live path is `--live-client-mode azure-openai-endpoint`" in guide
    assert "completed structured extraction and urgency classification" in normalized_guide
    assert "manual path validated for this capstone is `azure-openai-endpoint`" in guide
    assert "A successful live smoke response should" in guide
    assert "entra-bearer-token-provider" in guide
    assert "cognitiveservices.default" in guide
    assert "token provider details are never printed" in normalized_guide
    assert "RBAC/resource authentication configuration" in guide
    assert "required endpoint present" in normalized_guide
    assert "Azure CLI token probe status" in normalized_guide
    assert "failure phase" in guide
    assert "root exception class names" in normalized_guide
    assert "exception-chain class names" in normalized_guide
    assert "safe HTTP status category" in normalized_guide
    assert "raw exception messages" in guide
    assert ".env.foundry.local.example" in guide
    assert "existing shell environment variables still win" in guide
    assert "validates local Foundry configuration" in normalized_guide
    assert "reports optional SDK visibility" in normalized_guide
    assert "without creating the AI service" in normalized_guide
    assert "making a model call" in normalized_guide
    assert "does not persist cases" in normalized_guide
    assert "does not send notifications" in normalized_guide
    assert "does not call FastAPI routes" in normalized_guide
    assert "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT" in guide
    assert "AZURE_OPENAI_ENDPOINT" in guide
    assert "AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT_NAME" in guide
    assert "Automated tests use fake SDK/client objects only" in guide
    assert "real Azure AI Foundry smoke test has not been performed yet" not in guide
    assert "Do not use real patient data" in guide
    assert "medication refill" in guide
    assert "chest pain" in guide
    assert "missing_fields" in guide
    assert "Restore mock defaults" in guide
    assert "Restore or verify `AI_PROVIDER=mock`" in guide


def test_developer_handoff_documents_current_integration_status() -> None:
    handoff = (PROJECT_ROOT / "docs" / "developer-handoff.md").read_text()
    normalized_handoff = " ".join(handoff.split())

    assert "Current Integration Status" in handoff
    assert "Mock demo is the primary interview/demo path" in handoff
    assert "--live-client-mode azure-openai-endpoint" in handoff
    assert "AZURE_OPENAI_ENDPOINT" in handoff
    assert "/openai/v1/" in handoff
    assert "Entra bearer-token provider auth" in handoff
    assert "not wired into the default demo" in handoff
    assert "Azure Speech remains scaffolded" in handoff
    assert "ACS Email/SMS" in handoff
    assert "Cosmos has repository seams" in handoff
    assert "Production hosting" in handoff
    assert "out of scope for this MVP" in normalized_handoff
    assert "docs/demo-readiness-checklist.md" in handoff


def test_manual_speech_smoke_test_guide_exists() -> None:
    guide_path = PROJECT_ROOT / "docs" / "manual-speech-smoke-test.md"

    assert guide_path.exists()

    guide = guide_path.read_text()
    normalized_guide = " ".join(guide.split())
    assert "Manual Azure Speech Smoke-Test Preparation" in guide
    assert "automated test suite must remain offline" in normalized_guide
    assert "must not call Azure Speech" in normalized_guide
    assert "SPEECH_PROVIDER=mock" in guide
    assert "SPEECH_PROVIDER=azure" in guide
    assert "AZURE_SPEECH_ENDPOINT" in guide
    assert "AZURE_SPEECH_REGION" in guide
    assert "python scripts/smoke_speech_transcription.py --check" in guide
    assert "--env-file .env.speech.local --check" in guide
    assert ".env.speech.local.example" in guide
    assert "Existing shell environment variables still win" in guide
    assert "preflight/config validation only" in guide
    assert "No Speech client was created" in guide
    assert "process audio" in guide
    assert "make an Azure network call" in guide
    assert "SDK check is informational" in guide
    assert "Manual/live Azure Speech transcription remains deferred" in guide
    assert "Do not use PHI or real patient data" in guide
    assert "production clinical use" in guide
    assert "Do not commit" in guide


def test_system_overview_exists() -> None:
    guide_path = PROJECT_ROOT / "docs" / "system-overview.md"

    assert guide_path.exists()

    guide = guide_path.read_text()
    assert "System Overview" in guide
    assert "local mock/demo capstone project" in guide
    assert "no production clinical use" in guide
    assert "POST /intake/text" in guide
    assert "POST /intake/voicemail-transcript" in guide
    assert "CaseProcessingService" in guide
    assert "Provider Boundaries" in guide
    assert "APP_MODE=mock" in guide
    assert "AI_PROVIDER=foundry" in guide
    assert "SPEECH_PROVIDER=azure" in guide
    assert "Mock vs Azure-Ready vs Deferred" in guide
    assert "Documentation Map" in guide
    assert "scripts/preflight.py --all" in guide
    assert "Demo Claims" in guide
    assert "Do not claim complete" in guide
    assert "Next-Slice Guidance" in guide
    assert "Live Azure Speech transcription" in guide


def test_architecture_documents_current_mvp_boundaries() -> None:
    architecture = (PROJECT_ROOT / "docs" / "architecture.md").read_text()
    normalized_architecture = " ".join(architecture.split())

    assert "local mock/demo FastAPI application" in normalized_architecture
    assert "AI-generated" in architecture
    assert "extraction" in architecture
    assert "summary" in architecture
    assert "urgency output" in normalized_architecture
    assert "advisory only" in architecture
    assert "requires human nurse review" in normalized_architecture
    assert "MockAiService" in architecture
    assert "FoundryAiService" in architecture
    assert "Speech transcription services" in architecture
    assert "already-transcribed text only" in normalized_architecture
    assert "live Azure Speech transcription/audio processing" in normalized_architecture
    assert "live extraction is deferred" in normalized_architecture
    assert "InMemoryCaseRepository" in architecture
    assert "CosmosCaseRepository" in architecture
    assert "partition key `/createdDate`" in normalized_architecture
    assert "notificationEmailSent" in architecture
    assert "notificationSmsDeliveryConfirmed" in architecture
    assert "does not prove final SMS handset delivery" in normalized_architecture
    assert "Live Azure AI Foundry extraction" in normalized_architecture
    assert "Azure Speech / voice intake" in normalized_architecture
    assert "Hosting" in architecture
    assert "Authentication / RBAC" in architecture
    assert "Key Vault" in architecture


def test_architecture_documents_agent_contract_safety_flow() -> None:
    architecture = (PROJECT_ROOT / "docs" / "architecture.md").read_text()
    normalized_architecture = " ".join(architecture.split())

    assert "NurseIntakeAgent is treated as an external reasoning boundary" in architecture
    assert "agent contract validation" in architecture
    assert "application-owned contract" in architecture
    assert "safe fallback" in architecture
    assert "deterministic red-flag rules" in architecture
    assert "processing_trace" in architecture
    assert "final urgency source" in architecture
    assert (
        "Raw intake -> Agent/AI analysis -> agent contract validation -> safe fallback if needed -> deterministic red-flag rules -> persisted case -> notification/review"
        in normalized_architecture
    )


def test_ai_103_mapping_documents_current_scope_and_roi_order() -> None:
    mapping = (PROJECT_ROOT / "docs" / "ai-103-mapping.md").read_text()
    normalized_mapping = " ".join(mapping.split())

    assert "local mock/demo FastAPI app" in normalized_mapping
    assert "not production clinical software" in mapping
    assert "AI_PROVIDER=mock" in mapping
    assert "MockAiService" in mapping
    assert "FoundryAiService" in mapping
    assert (
        "lazy live adapter implemented; live Foundry extraction deferred"
        in mapping
    )
    assert "AI output requires human nurse review" in mapping
    assert "Azure Speech transcription service" in mapping
    assert "ACS phone intake/call automation" in mapping
    assert "Confirmed ACS SMS handset delivery is not implemented" in normalized_mapping
    assert "Live Azure AI Foundry structured extraction" in mapping
    assert "Foundry prompt/schema/evaluation notes" in mapping
    assert "Azure Speech transcription service boundary" in mapping
    assert mapping.index("1. Live Azure AI Foundry structured extraction") < mapping.index(
        "8. ACS phone intake"
    )


def test_ai_103_mapping_documents_agent_safety_boundary() -> None:
    mapping = (PROJECT_ROOT / "docs" / "ai-103-mapping.md").read_text()

    assert "Azure AI Foundry / agent orchestration readiness" in mapping
    assert "responsible AI pattern" in mapping
    assert "validation before trusting model/agent output" in mapping
    assert "agent contract validation" in mapping
    assert "safe fallback" in mapping
    assert "human review and deterministic safety rules" in mapping
    assert "processing trace" in mapping
    assert "final urgency source" in mapping


def test_progress_links_manual_acs_email_smoke_test() -> None:
    docs_text = (PROJECT_ROOT / "docs" / "progress.md").read_text()

    assert "docs/manual-acs-email-smoke-test.md" in docs_text


def test_progress_active_resume_links_archived_history() -> None:
    progress_path = PROJECT_ROOT / "docs" / "progress.md"
    archive_path = PROJECT_ROOT / "docs" / "archive" / "progress-2026-06.md"

    assert progress_path.exists()
    assert archive_path.exists()

    progress = progress_path.read_text()
    archive = archive_path.read_text()
    progress_line_count = len(progress.splitlines())
    archive_line_count = len(archive.splitlines())

    assert progress_line_count <= 400
    assert progress_line_count < archive_line_count
    assert "docs/archive/progress-2026-06.md" in progress
    assert "Latest verified test baseline" in progress
    assert "passed" in progress
    assert "StarletteDeprecationWarning" in progress
    assert "Local mock/demo only" in progress
    assert "No production clinical use" in progress
    assert "Mock mode sends no real email or SMS" in progress
    assert "AI output requires human nurse review" in progress
    assert "Authentication" in progress
    assert "Hosting" in progress
    assert "Key Vault" in progress
    assert "Azure Speech" in progress
    assert "Azure AI Foundry" in progress
    assert "ACS SMS delivery tracking" in progress
    assert "Retry logic" in progress
    assert "Every future TDD slice must include a `docs/progress.md` update" in progress
    assert "Testing Guidance" in progress
    assert (
        "Agent output contract validation added with safe fallback behavior and processing trace warnings."
        in progress
    )

    assert "Detailed historical progress through June 2026" in archive
    assert "README local mock demo walkthrough polish is complete" in archive
    assert "Live ACS Email smoke testing is complete" in archive
    assert "Manual Cosmos smoke test" in archive


def test_progress_current_resume_point_keeps_live_azure_scope_honest() -> None:
    progress = (PROJECT_ROOT / "docs" / "progress.md").read_text()

    assert "## Current Resume Point" in progress
    assert "Safe to demo today" in progress
    assert "default demo mock/offline" in progress
    assert "Live Azure AI Foundry smoke testing or live Foundry extraction" in progress
    assert "Live Azure Speech transcription, audio upload, or audio processing" in progress


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
