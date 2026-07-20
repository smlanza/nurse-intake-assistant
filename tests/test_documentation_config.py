from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (PROJECT_ROOT / relative_path).read_text()


def test_progress_has_one_current_hosted_verifier_state_and_baseline() -> None:
    progress = _read("docs/progress.md")
    active = progress.split("## Current Slice Status", 1)[1].split(
        "### Historical Slice Results", 1
    )[0]
    normalized_active = _normalized(active).casefold()

    assert "missing hosted execution and configuration boundaries" not in normalized_active
    assert progress.count("Latest verified test baseline:") == 1
    assert "offline-tested only" in progress
    assert "preferred daily path" in progress.casefold()
    assert "later agent invocation" in progress.casefold()
    assert len(progress.splitlines()) <= 500


def _normalized(text: str) -> str:
    return " ".join(text.split())


def _env_values(relative_path: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in _read(relative_path).splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        values[name] = value
    return values


def _assert_contains_all(text: str, expected: set[str]) -> None:
    missing = sorted(token for token in expected if token not in text)
    assert not missing, f"Missing documented contract tokens: {missing}"


def test_main_env_example_has_safe_defaults_and_required_placeholders() -> None:
    values = _env_values(".env.example")

    assert {
        name: values[name]
        for name in {
            "APP_MODE",
            "AI_PROVIDER",
            "AGENT_PROVIDER",
            "SPEECH_PROVIDER",
            "EMAIL_PROVIDER",
            "SMS_PROVIDER",
        }
    } == {
        "APP_MODE": "mock",
        "AI_PROVIDER": "mock",
        "AGENT_PROVIDER": "mock",
        "SPEECH_PROVIDER": "mock",
        "EMAIL_PROVIDER": "mock",
        "SMS_PROVIDER": "mock",
    }
    assert values["DEMO_SUPPRESS_NOTIFICATIONS"] == "false"

    required_placeholders = {
        "COSMOS_ENDPOINT",
        "COSMOS_KEY",
        "ACS_EMAIL_CONNECTION_STRING",
        "ACS_EMAIL_SENDER_ADDRESS",
        "NURSE_NOTIFICATION_EMAIL",
        "ACS_SMS_CONNECTION_STRING",
        "ACS_SMS_FROM_PHONE_NUMBER",
        "NURSE_NOTIFICATION_PHONE_NUMBER",
        "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT",
        "AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT_NAME",
        "AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT",
        "AZURE_AI_FOUNDRY_AGENT_ENDPOINT",
        "AZURE_AI_FOUNDRY_AGENT_ID",
        "AZURE_AI_FOUNDRY_AGENT_NAME",
        "AZURE_AI_FOUNDRY_AGENT_VERSION",
        "AZURE_AI_FOUNDRY_MANAGED_IDENTITY_CLIENT_ID",
        "AZURE_SUBSCRIPTION_ID",
        "AZURE_AI_FOUNDRY_RESOURCE_GROUP_NAME",
        "AZURE_AI_FOUNDRY_PROJECT_NAME",
        "AZURE_SPEECH_ENDPOINT",
        "AZURE_SPEECH_REGION",
    }
    assert required_placeholders <= values.keys()
    assert all(values[name] == "" for name in required_placeholders)
    assert values["AZURE_AI_FOUNDRY_AGENT_USE_PROJECT_ENDPOINT_COMPATIBILITY"] == "false"


def test_foundry_env_examples_are_explicit_and_keep_unrelated_providers_mock() -> None:
    extraction = _env_values(".env.foundry.local.example")
    agent = _env_values(".env.foundry-agent.local.example")

    assert extraction == {
        "AI_PROVIDER": "foundry",
        "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT": (
            "https://your-foundry-project-endpoint.example.invalid"
        ),
        "AZURE_OPENAI_ENDPOINT": (
            "https://example-openai-resource.openai.azure.com/"
        ),
        "AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT_NAME": "your-model-deployment-name",
        "EMAIL_PROVIDER": "mock",
        "SMS_PROVIDER": "mock",
    }
    assert agent["AGENT_PROVIDER"] == "foundry-agent"
    assert agent["AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT"].startswith("<your-")
    assert agent["AZURE_AI_FOUNDRY_AGENT_ENDPOINT"].startswith("<your-")
    assert agent["AZURE_AI_FOUNDRY_AGENT_NAME"] == "<your-foundry-agent-name>"
    assert agent["AZURE_AI_FOUNDRY_AGENT_VERSION"] == "<your-foundry-agent-version>"
    assert agent["AZURE_AI_FOUNDRY_AGENT_USE_PROJECT_ENDPOINT_COMPATIBILITY"] == "false"
    assert "AZURE_AI_FOUNDRY_AGENT_ID" not in agent
    assert {
        name: agent[name]
        for name in {
            "APP_MODE",
            "AI_PROVIDER",
            "SPEECH_PROVIDER",
            "EMAIL_PROVIDER",
            "SMS_PROVIDER",
        }
    } == {
        "APP_MODE": "mock",
        "AI_PROVIDER": "mock",
        "SPEECH_PROVIDER": "mock",
        "EMAIL_PROVIDER": "mock",
        "SMS_PROVIDER": "mock",
    }
    assert agent["DEMO_SUPPRESS_NOTIFICATIONS"] == "true"


def test_environment_examples_use_placeholders_and_warn_against_real_values() -> None:
    example_paths = {
        ".env.example",
        ".env.foundry.local.example",
        ".env.foundry-agent.local.example",
        ".env.speech.local.example",
    }

    for path in example_paths:
        text = _read(path)
        lowered = text.lower()
        assert "accesskey=" not in lowered
        assert "bearer " not in lowered
        assert "+1" not in text
        assert "555" not in text
        assert "@" not in text
        assert "DOB" not in text

    _assert_contains_all(
        _read(".env.example"),
        {"Do not commit", "real endpoints", "real ACS connection strings", "PHI"},
    )
    assert "Do not commit real values" in _read(".env.foundry.local.example")
    assert "Do not commit real values" in _read(".env.foundry-agent.local.example")


def test_requirements_include_documented_runtime_and_azure_dependencies() -> None:
    requirements = set(_read("requirements.txt").splitlines())

    assert {
        "fastapi",
        "uvicorn[standard]",
        "pytest",
        "httpx",
        "azure-communication-email",
        "azure-communication-sms",
    } <= requirements


def test_manual_acs_email_guide_documents_safe_operator_contract() -> None:
    guide = _normalized(_read("docs/manual-acs-email-smoke-test.md"))

    _assert_contains_all(
        guide,
        {
            "Manual ACS Email Smoke Test",
            "EMAIL_PROVIDER=acs",
            "ACS_EMAIL_CONNECTION_STRING",
            "ACS_EMAIL_SENDER_ADDRESS",
            "NURSE_NOTIFICATION_EMAIL",
            "python scripts/smoke_acs_email.py --check",
            "creates no ACS Email client",
            "makes no Azure calls",
            "sends no email",
            "EMAIL_PROVIDER=mock",
            "Do not commit",
        },
    )


def test_manual_acs_sms_guide_documents_safe_operator_contract() -> None:
    guide = _normalized(_read("docs/manual-acs-sms-smoke-test.md"))

    _assert_contains_all(
        guide,
        {
            "Manual ACS SMS Smoke Test",
            "SMS_PROVIDER=acs",
            "ACS_SMS_CONNECTION_STRING",
            "ACS_SMS_FROM_PHONE_NUMBER",
            "NURSE_NOTIFICATION_PHONE_NUMBER",
            "python scripts/smoke_acs_sms.py --check",
            "creates no ACS SMS client",
            "makes no Azure network call",
            "sends no SMS",
            "SMS_PROVIDER=mock",
            "does not prove handset delivery",
            "Do not paste or commit",
        },
    )


def test_manual_local_demo_guide_documents_mock_safety_and_review_flow() -> None:
    guide = _read("docs/manual-local-mock-demo.md")

    _assert_contains_all(
        guide,
        {
            "Local Mock Demo",
            "APP_MODE=mock",
            "AI_PROVIDER=mock",
            "EMAIL_PROVIDER=mock",
            "SMS_PROVIDER=mock",
            "POST /intake/text",
            "GET /cases/summary",
            "POST /cases/{case_id}/review",
            "GET /notifications/email",
            "GET /notifications/sms",
            "PendingReview",
            "Reviewed",
            "Mock mode sends no real email or SMS",
            "Do not commit",
        },
    )


def test_readme_documents_safe_local_demo_and_claims_boundary() -> None:
    readme = _normalized(_read("README.md"))

    _assert_contains_all(
        readme,
        {
            "Local Mock Demo Walkthrough",
            "local mock/demo only",
            "no production clinical use",
            "AI output requires human nurse review",
            "APP_MODE=mock",
            "AI_PROVIDER=mock",
            "AGENT_PROVIDER=mock",
            "SPEECH_PROVIDER=mock",
            "EMAIL_PROVIDER=mock",
            "SMS_PROVIDER=mock",
            "default mock mode makes no Azure calls",
            "human nurse review is required",
            "fictional/demo data only",
            "no secrets or PHI",
            "must not claim production clinical readiness",
        },
    )


def test_readme_documents_explicit_provider_and_preflight_operations() -> None:
    readme = _normalized(_read("README.md"))

    _assert_contains_all(
        readme,
        {
            "Provider Mode Matrix",
            "provider settings are independent adapter toggles",
            "not an all-or-nothing Azure switch",
            "Do not introduce APP_MODE=azure",
            "Foundry Agent smoke-test mode",
            "AGENT_PROVIDER=foundry-agent",
            "APP_MODE=mock",
            "python scripts/preflight.py --all",
            "python scripts/preflight.py --foundry-agent",
            "SKIP is expected and safe",
            "This preflight remains offline-safe and does not call Azure.",
            "FAIL means required configuration is missing",
            "not that a live service call failed",
            "Smoke-test scripts are automated checks that are manually invoked",
            "not run by app startup, /demo, or /demo/status",
        },
    )


def test_demo_readiness_checklist_preserves_human_review_and_claim_limits() -> None:
    checklist = _normalized(_read("docs/demo-readiness-checklist.md"))

    _assert_contains_all(
        checklist,
        {
            "Demo Readiness Checklist",
            "local mock demo",
            "Automated tests remain offline",
            "Nurse review is required",
            "Urgency output is advisory only",
            "no real PHI",
            "Do not claim production readiness",
            "Do not claim Azure hosting unless separately deployed",
            "manual smoke script only",
        },
    )


def test_manual_foundry_guide_separates_check_live_and_agent_operations() -> None:
    guide = _normalized(_read("docs/manual-foundry-smoke-test.md"))

    _assert_contains_all(
        guide,
        {
            "Manual Foundry Smoke Test",
            "automated test suite must remain offline",
            "must not call Azure",
            "AI_PROVIDER=mock",
            "scripts/smoke_foundry_extraction.py",
            "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT",
            "AZURE_OPENAI_ENDPOINT",
            "AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT_NAME",
            "--env-file .env.foundry.local --check",
            "--env-file .env.foundry.local --live",
            "Foundry Agent Smoke CLI",
            "AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT",
            "AZURE_AI_FOUNDRY_AGENT_NAME",
            "AZURE_AI_FOUNDRY_AGENT_VERSION",
            "python scripts/smoke_foundry_agent.py --check",
            "python scripts/smoke_foundry_agent.py --live",
            "--check does not call Azure",
            "--live remains manual and opt-in",
            "Human nurse review remains mandatory",
            "fictional data only",
            "default local demo remains mock/offline",
            "Do not claim live Foundry Agent behavior",
            "Restore or verify `AI_PROVIDER=mock`",
        },
    )


def test_manual_foundry_guide_success_example_is_sanitized() -> None:
    guide = _read("docs/manual-foundry-smoke-test.md")
    marker = "Sanitized successful result example:"
    assert marker in guide
    success_section = guide.split(marker, 1)[1].split("`--live --diagnose`", 1)[0]

    _assert_contains_all(
        success_section,
        {
            '"ok": true',
            '"category": "success"',
            '"agent_attempted": true',
            '"agent_output_valid": true',
            '"fallback_used": false',
            '"fields_present": ["extraction", "urgency", "handoffNote"]',
        },
    )
    for unsafe_text in {
        "services.ai.azure.com/api/projects/",
        "openai.azure.com",
        "AZURE_AI_FOUNDRY_AGENT_ID=",
        "raw prompt",
        "raw model output",
        "Bearer ",
        "request_id",
        "@",
        "+1",
        "555",
        "DOB",
    }:
        assert unsafe_text not in success_section


def test_demo_page_smoke_guide_covers_review_and_reset_workflow() -> None:
    guide = _read("docs/demo-smoke-test.md")

    _assert_contains_all(
        guide,
        {
            "Demo Page Smoke Test",
            "http://127.0.0.1:8000/demo",
            "submit a text intake",
            "submit a voicemail transcript intake",
            "mark a case reviewed",
            "confirm the reviewed state is visible",
            "reset the demo",
            "POST /cases/{case_id}/review",
            "POST /demo/reset",
        },
    )


def test_manual_speech_guide_keeps_check_mode_offline_and_live_work_deferred() -> None:
    guide = _normalized(_read("docs/manual-speech-smoke-test.md"))

    _assert_contains_all(
        guide,
        {
            "Manual Azure Speech Smoke-Test Preparation",
            "automated test suite must remain offline",
            "must not call Azure Speech",
            "SPEECH_PROVIDER=mock",
            "SPEECH_PROVIDER=azure",
            "AZURE_SPEECH_ENDPOINT",
            "AZURE_SPEECH_REGION",
            "python scripts/smoke_speech_transcription.py --check",
            "No Speech client was created",
            "Manual/live Azure Speech transcription remains deferred",
            "Do not use PHI or real patient data",
            "Do not commit",
        },
    )


def test_architecture_documents_local_safety_and_agent_validation() -> None:
    architecture = _normalized(_read("docs/architecture.md"))

    _assert_contains_all(
        architecture,
        {
            "local mock/demo FastAPI application",
            "advisory only",
            "requires human nurse review",
            "MockAiService",
            "FoundryAiService",
            "APP_MODE=mock",
            "AI_PROVIDER=mock",
            "InMemoryCaseRepository",
            "NurseIntakeAgent is treated as an external reasoning boundary",
            "agent contract validation",
            "safe fallback",
            "deterministic red-flag rules",
            "processing_trace",
            "final urgency source",
        },
    )


def test_architecture_documents_separate_foundry_and_web_app_proof_boundaries() -> None:
    architecture = _normalized(_read("docs/architecture.md"))

    _assert_contains_all(
        architecture,
        {
            "Provisioning never invokes the agent",
            "invocation remains a separate explicit smoke command",
            "separate verification CLI",
            "explicit live verification creates no version",
            "deployApp=true` (default `false`)",
            "scripts/deploy_web_app_infra.py",
            "Check mode validates required safe arguments",
            "Explicit `--what-if` or `--live` mode issues exactly one argument-list",
            "the CLI never creates the group",
            "shared hosting-contract module owns the exact seven",
            "missing, extra, duplicate, conflicting, commented-only, and overriding settings fail",
            "reduces the active change collection to sanitized",
            "Proposed deletes are surfaced for manual review",
            "preview mode never invokes live mode",
            "SCM_DO_BUILD_DURING_DEPLOYMENT=true",
            "scripts/verify_web_app_configuration.py",
            "Check mode validates the local contract without creating an Azure CLI runner",
            "three read-only Azure CLI commands with explicit JSON output projections",
            "JMESPath `--query` shapes the JSON emitted to the Python verifier",
            "it does not limit what Azure reads",
            "scripts/verify_web_app_readiness.py",
            "Check mode validates an explicit absolute HTTPS origin",
            "Only explicit `--live --json` creates the standard-library transport",
            "/health",
            "/version",
            "/demo/status",
            "Deployment-request acceptance, configuration proof, code deployment, and hosted startup remain separate proof boundaries",
            "Code deployment does not provision infrastructure",
            "Hosted defaults remain mock-only with notifications suppressed",
            "human nurse review remains mandatory",
            "succeeded on July 15, 2026",
            "validation created no Azure resources",
            "live Web App infrastructure deployment request completed successfully",
            "Live read-only verification succeeded for this complete hosting contract",
            "explicit live code-deployment request completed successfully",
            "Separate live verification subsequently proved `/health`, `/version`, and `/demo/status`",
        },
    )


def test_ai_103_mapping_documents_scope_safety_and_priority() -> None:
    mapping = _read("docs/ai-103-mapping.md")
    normalized = _normalized(mapping)

    _assert_contains_all(
        normalized,
        {
            "local mock/demo FastAPI app",
            "not production clinical software",
            "AI_PROVIDER=mock",
            "validation before trusting model/agent output",
            "safe fallback",
            "AI output requires human nurse review",
            "Offline tests use fakes and make no Azure calls",
            "scripts/verify_web_app_configuration.py",
            "scripts/verify_web_app_readiness.py",
            "Check modes make no Azure or HTTP call",
            "Configuration verification does not prove code deployment",
            "Package creation and deployment-request acceptance do not imply hosted health",
            "Live Azure AI Foundry structured extraction",
        },
    )
    assert mapping.index("1. Live Azure AI Foundry structured extraction") < mapping.index(
        "7. ACS phone intake"
    )


def test_infrastructure_docs_keep_operator_boundaries_manual_and_explicit() -> None:
    infra = _normalized(_read("infra/README.md"))
    progress = _normalized(_read("docs/progress.md"))
    gitignore = set(_read(".gitignore").splitlines())

    _assert_contains_all(
        infra,
        {
            "APP_MODE=mock",
            "AI_PROVIDER=mock",
            "AGENT_PROVIDER=mock",
            "SPEECH_PROVIDER=mock",
            "EMAIL_PROVIDER=mock",
            "SMS_PROVIDER=mock",
            "DEMO_SUPPRESS_NOTIFICATIONS=true",
            "scripts/deploy_web_app_infra.py",
            "always pass `deployApp=true` and `deployFoundry=false`",
            "Resource-group creation and cleanup remain manual and explicit",
            "Validation created no Azure resources",
            "The new CLI is offline-tested only",
            "compares its seven provider and notification-suppression entries",
            "Missing, extra, duplicate, conflicting, commented-only, or later overriding settings fail",
            "What-if requests machine-readable JSON",
            "Malformed or structurally invalid output fails safely",
            "Proposed deletes are surfaced with an explicit manual-review warning",
            "What-if remains preview-only",
            "live deployment remains a separate explicit choice",
            "Application packaging and code deployment are separate from infrastructure",
            "RBAC, prompt-agent provisioning, startup verification, and invocation",
            "check and package modes never create a runner or invoke Azure CLI",
            "scripts/verify_web_app_configuration.py",
            "Offline check mode validates the application-owned contract",
            "Only explicit live JSON mode performs Azure reads",
            "three sequential read-only Azure CLI commands with explicit JSON output projections",
            "The app-settings command emits only the eight Bicep-owned settings to the verifier",
            "The application never returns, logs, or serializes raw unfiltered Azure CLI output",
            "Configuration verification does not prove code deployment",
            "scripts/verify_web_app_readiness.py",
            "/health",
            "/version",
            "/demo/status",
            "Check mode validates and normalizes an explicit HTTPS origin",
            "Only explicit live mode creates the standard-library transport",
            "No live hosted verification was run in this slice",
            "hosted readiness does not prove RBAC, managed-identity authentication, Foundry access, or agent invocation",
            "Only `--live` creates or reuses the group and deploys Foundry",
            "Cleanup is manual and explicit",
            "no script or template automatically deletes a resource group",
            "deployApp`: optionally create the Web App runtime; defaults to `false`",
            "Do not commit `.env` or real Cosmos keys",
            "Mandatory nurse review remains unchanged",
            "not production clinical infrastructure",
        },
    )
    _assert_contains_all(
        progress,
        {
            "foundry-only.bicepparam` is ignored, operator-local, and must not be committed",
            "Keep infrastructure deployment separate from prompt-agent creation",
            "Keep cleanup manual and explicit",
            "scripts/deploy_web_app_infra.py",
            "succeeded July 15, 2026, and created no resources",
            "live Web App infrastructure deployment request succeeded",
            "acceptance does not prove configuration",
            "Live read-only configuration verification then proved",
            "explicit code deployment, and separate hosted",
        },
    )
    assert {".env", ".env.*", "infra/foundry-only.bicepparam"} <= gitignore
    assert {
        "!.env.example",
        "!.env.foundry.local.example",
        "!.env.foundry-agent.local.example",
        "!.env.daily-azure.example",
        "!.env.speech.local.example",
    } <= gitignore


def test_progress_is_active_resume_with_honest_safety_and_history_boundaries() -> None:
    progress = _read("docs/progress.md")
    archive = _read("docs/archive/progress-2026-06.md")
    normalized = _normalized(progress)

    assert len(progress.splitlines()) <= 500
    assert len(progress.splitlines()) < len(archive.splitlines())
    _assert_contains_all(
        normalized,
        {
            "docs/archive/progress-2026-06.md",
            "Latest verified test baseline",
            "Local mock/demo only",
            "No production clinical use",
            "Mock mode sends no real email or SMS",
            "AI output requires human nurse review",
            "default demo mock/offline",
            "No live Azure behavior is claimed for `/demo` by default",
            "AGENT_PROVIDER=mock` remains the safe local/demo default",
            "human nurse review remains mandatory",
            "docs/manual-acs-email-smoke-test.md",
            "Live ACS Email smoke testing is complete",
        },
    )
    _assert_contains_all(
        archive,
        {
            "Detailed historical progress through June 2026",
            "README local mock demo walkthrough polish is complete",
            "Manual Cosmos smoke test",
        },
    )


def test_progress_documents_future_tdd_and_test_maintenance_guardrails() -> None:
    progress = _read("docs/progress.md")

    _assert_contains_all(
        progress,
        {
            "Every future TDD slice must include a `docs/progress.md` update",
            "Model: GPT-5.5",
            "Reasoning: Medium for normal TDD slices",
            "Reasoning: High for cross-cutting architecture",
            "Reasoning: Light for docs-only or tiny single-file cleanup",
            "Documentation tests should verify important project guardrails",
            "avoid adding many brittle string-matching tests",
            "Prefer a small number of high-value guardrail tests",
        },
    )


def test_progress_enforces_the_architecture_document_change_gate() -> None:
    raw_progress = _read("docs/progress.md")
    progress = _normalized(raw_progress)

    assert raw_progress.count("## Architecture Document Change Gate\n") == 1
    _assert_contains_all(
        progress,
        {
            "authoritative, present-tense description of the current system design",
            "durable system-level architectural contract",
            "If no durable architectural contract changed",
            "Update the existing authoritative section",
            "Architecture impact: none.",
            "Architecture impact: updated <existing section> because <durable architectural contract changed>.",
            "Do not modify `docs/architecture.md` unless the Architecture Document Change Gate is satisfied.",
            "periodic focused documentation reviews",
        },
    )


def test_progress_enforces_the_daily_disposable_azure_environment_gate() -> None:
    progress = _normalized(_read("docs/progress.md"))

    _assert_contains_all(
        progress,
        {
            "Daily Disposable Azure Environment Gate",
            "docs/runbooks/daily-disposable-azure-environment-rebuild.md",
            "offline-only",
            "Azure-dependent",
            "assume the resource group and all dependent resources are absent",
            "Deleting the resource group expires all prior evidence",
            "current session",
            "must not be recommended or started",
            "do not issue the dependent prompt",
            "repeated blocked slices",
            "scripts/rebuild_daily_azure_environment.py",
            "daily_environment_ready=true",
            "preferred daily path",
        },
    )


def test_daily_azure_coordinator_docs_define_the_automated_safe_path() -> None:
    runbook = _normalized(
        _read("docs/runbooks/daily-disposable-azure-environment-rebuild.md")
    )
    architecture = _normalized(_read("docs/architecture.md"))
    values = _env_values(".env.daily-azure.example")

    _assert_contains_all(
        runbook,
        {
            "Normal Daily Automated Path",
            "scripts/rebuild_daily_azure_environment.py",
            "--check",
            "--live",
            "daily_environment_ready=true",
            "troubleshooting, recovery, audit",
            "does not trigger or read WebJob execution",
            "category=manual_rbac_action_required",
            "coordinator contains no live RBAC deployment path",
            "exact expected identity, scope, parent topology, and multiplicity",
        },
    )
    _assert_contains_all(
        architecture,
        {
            "preferred authoritative daily orchestration layer",
            "independent deployment",
            "manual",
            "cannot trigger or read a WebJob run",
            "healthy old worker cannot produce READY",
            "never previews or deploys RBAC itself",
            "exact expected identity",
        },
    )
    assert set(values) == {
        "AZURE_SUBSCRIPTION_NAME",
        "AZURE_LOCATION",
        "AZURE_RESOURCE_GROUP",
        "AZURE_ENVIRONMENT_NAME",
        "AZURE_PROJECT_NAME",
        "AZURE_FOUNDRY_ACCOUNT_NAME",
        "AZURE_FOUNDRY_PROJECT_NAME",
        "AZURE_FOUNDRY_MODEL_DEPLOYMENT_NAME",
        "AZURE_FOUNDRY_MODEL_NAME",
        "AZURE_FOUNDRY_MODEL_VERSION",
        "AZURE_FOUNDRY_MODEL_SKU",
        "AZURE_FOUNDRY_MODEL_CAPACITY",
        "AZURE_FOUNDRY_AGENT_NAME",
        "AZURE_WEB_APP_NAME",
        "AZURE_WEB_APP_SKU",
        "ENABLE_HOSTED_FOUNDRY_VERIFIER",
        "DISCOVER_HOSTED_FOUNDRY_WEBJOB",
    }


def test_daily_disposable_azure_runbook_has_ordered_stage_boundaries() -> None:
    runbook = _normalized(
        _read("docs/runbooks/daily-disposable-azure-environment-rebuild.md")
    )
    ordered_stages = [
        "Purpose and lifecycle",
        "Required operator inputs",
        "Local preflight",
        "Authentication and subscription",
        "Resource group creation",
        "Foundry infrastructure",
        "Prompt-agent provisioning and immutable-version proof",
        "Web App infrastructure",
        "Web App configuration verification",
        "Package creation",
        "Web App code deployment",
        "Hosted readiness verification",
        "Consumer RBAC deployment",
        "Consumer RBAC verification",
        "Optional WebJob discovery",
        "Daily environment-ready declaration",
        "End-of-session cleanup and evidence expiry",
        "Fail-fast rules",
        "Cost control",
    ]
    positions = [runbook.index(stage) for stage in ordered_stages]
    assert positions == sorted(positions)


def test_daily_disposable_azure_runbook_separates_procedure_and_live_evidence() -> None:
    runbook = _normalized(
        _read("docs/runbooks/daily-disposable-azure-environment-rebuild.md")
    )

    _assert_contains_all(
        runbook,
        {
            "durable checked-in procedure",
            "fresh current-session evidence",
            "READY",
            "NOT READY",
            "Deletion immediately returns the environment to NOT READY",
            "Never commit subscription IDs, tenant IDs, principal IDs",
            "complete ARM resource IDs",
            "access tokens, bearer tokens",
            "scripts/deploy_foundry_infra.py",
            "scripts/verify_foundry_infra.py",
            "scripts/deploy_foundry_agent.py",
            "scripts/configure_foundry_agent_endpoint_routing.py",
            "scripts/verify_foundry_agent.py",
            "scripts/deploy_web_app_infra.py",
            "scripts/verify_web_app_configuration.py",
            "scripts/package_web_app.py",
            "scripts/deploy_web_app_code.py",
            "scripts/verify_web_app_readiness.py",
            "scripts/deploy_foundry_agent_consumer_rbac.py",
            "scripts/verify_foundry_agent_consumer_rbac.py",
            "scripts/run_hosted_foundry_agent_verification.py",
            "Discovery does not authorize a trigger, status read, managed-identity access, metadata verification, or agent invocation",
        },
    )

    agent_stage = runbook.split(
        "Prompt-agent provisioning and immutable-version proof", 1
    )[1].split("Web App infrastructure", 1)[0]
    stage_positions = [
        agent_stage.index("scripts/deploy_foundry_agent.py"),
        agent_stage.index("scripts/configure_foundry_agent_endpoint_routing.py"),
        agent_stage.index("scripts/verify_foundry_agent.py"),
    ]
    assert stage_positions == sorted(stage_positions)


def test_hosted_foundry_verification_runbook_enforces_prerequisite_gate() -> None:
    path = (
        PROJECT_ROOT
        / "docs/runbooks/live-hosted-foundry-agent-verification-prerequisites.md"
    )
    assert path.is_file(), "The hosted Foundry verification runbook must be checked in."

    runbook = _normalized(path.read_text())
    _assert_contains_all(
        runbook,
        {
            "az login",
            "az account show",
            "subscription:name,state:state,isDefault:isDefault",
            "Exact operator-approved inventory",
            "Exact immutable prompt-agent version",
            "read-only prompt-agent metadata verification",
            "system-assigned managed identity",
            "current prerequisite",
            "does not invoke the agent or model",
            "Metadata verification and invocation remain separate",
            "repository-owned execution mechanism",
            "repository-owned configuration boundary",
            "offline-tested only",
            "Fail-fast stop conditions",
            "Historical output",
            "portal screenshots",
            "inferred resource",
            "General-purpose shell polling loops",
            "repeated sleeps",
            "repeated verifier calls",
            "ad hoc Azure changes",
            "one explicitly authorized WebJob trigger request",
            "one separately authorized receipt-correlated status read",
            "$HOME/site/wwwroot",
            ".artifacts/hosted-foundry-agent-webjob/trigger-reservation.lock",
            "accepted-trigger.json",
            "blocked-trigger.json",
            "terminal-outcome.json",
            "not a distributed lock across workstations or checkouts",
            "trigger acceptance without treating it as verification success",
            "not to agent invocation",
        },
    )
    for unauthorized_command in {
        "python -m src.app.operations.invoke_hosted_foundry_agent",
        "az role assignment create",
        "az webapp config appsettings set",
        "az webapp ssh",
    }:
        assert unauthorized_command not in runbook
