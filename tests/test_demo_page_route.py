from types import SimpleNamespace

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


def test_demo_page_includes_local_mock_demo_safety_banner() -> None:
    response = client.get("/demo")

    assert response.status_code == 200
    html = response.text
    assert 'class="demo-banner"' in html
    assert 'aria-label="Demo status"' in html
    assert "Local mock demo" in html
    assert "Not for production clinical use" in html
    assert "Mock mode sends no real email or SMS" in html
    assert "AI output requires human review" in html
    assert "HIPAA" not in html


def test_demo_page_displays_active_provider_configuration() -> None:
    response = client.get("/demo")

    assert response.status_code == 200
    html = response.text
    assert "Active Provider Configuration" in html
    assert "APP_MODE" in html
    assert "AI_PROVIDER" in html
    assert "SPEECH_PROVIDER" in html
    assert "EMAIL_PROVIDER" in html
    assert "SMS_PROVIDER" in html
    assert 'data-provider-name="APP_MODE"' in html
    assert 'data-provider-value="mock"' in html
    assert 'data-provider-name="AI_PROVIDER"' in html
    assert 'data-provider-name="SPEECH_PROVIDER"' in html
    assert 'data-provider-name="EMAIL_PROVIDER"' in html
    assert 'data-provider-name="SMS_PROVIDER"' in html


def test_demo_page_provider_configuration_reflects_active_settings(monkeypatch) -> None:
    demo_endpoint = next(
        child_route.endpoint
        for route in app.routes
        for child_route in getattr(getattr(route, "original_router", None), "routes", [])
        if getattr(child_route, "path", None) == "/demo"
    )

    monkeypatch.setitem(
        demo_endpoint.__globals__,
        "settings",
        SimpleNamespace(
            app_mode="cosmos",
            ai_provider="foundry",
            speech_provider="azure",
            email_provider="acs",
            sms_provider="acs",
        ),
    )

    response = client.get("/demo")

    assert response.status_code == 200
    html = response.text
    assert 'data-provider-name="APP_MODE" data-provider-value="cosmos"' in html
    assert 'data-provider-name="AI_PROVIDER" data-provider-value="foundry"' in html
    assert 'data-provider-name="SPEECH_PROVIDER" data-provider-value="azure"' in html
    assert 'data-provider-name="EMAIL_PROVIDER" data-provider-value="acs"' in html
    assert 'data-provider-name="SMS_PROVIDER" data-provider-value="acs"' in html


def test_demo_page_displays_mock_local_mode_safety_status() -> None:
    response = client.get("/demo")

    assert response.status_code == 200
    html = response.text
    assert "Mock/local mode is active." in html
    assert "Mock/local mode does not call Azure." in html
    assert "Mock/local mode does not call models." in html
    assert "Mock/local mode does not send real email or SMS." in html


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
        "Mock Notifications",
    ]:
        assert heading in html


def test_demo_page_workflow_is_unnumbered_clickable_navigation() -> None:
    response = client.get("/demo")

    assert response.status_code == 200
    html = response.text
    assert 'id="demo-workflow-section"' in html
    workflow_html = html[
        html.index('aria-labelledby="workflow-heading"') : html.index(
            'id="demo-controls-section"'
        )
    ]
    assert 'class="section-number"' not in workflow_html
    assert 'href="#demo-controls-section"' in workflow_html
    assert 'href="#queue-summary-section"' in workflow_html
    assert 'href="#recent-cases-section"' in workflow_html
    assert 'href="#nurse-review-section"' in workflow_html
    assert 'href="#text-intake-section"' in workflow_html
    assert 'href="#voicemail-intake-section"' in workflow_html
    assert 'href="#mock-notifications-section"' in workflow_html
    assert 'href="#reset-section"' in workflow_html


def test_demo_page_numbered_sections_link_back_to_workflow() -> None:
    response = client.get("/demo")

    assert response.status_code == 200
    html = response.text
    assert html.count('href="#demo-workflow-section"') == 8
    assert html.count("Back to Demo Workflow") == 8
    workflow_html = html[
        html.index('id="demo-workflow-section"') : html.index(
            'id="demo-controls-section"'
        )
    ]
    assert "Back to Demo Workflow" not in workflow_html


def test_demo_page_section_numbers_match_workflow_targets() -> None:
    response = client.get("/demo")

    assert response.status_code == 200
    html = response.text
    expected_sections = [
        ('id="demo-controls-section"', '<span class="section-number">1</span>'),
        ('id="queue-summary-section"', '<span class="section-number">2</span>'),
        ('id="recent-cases-section"', '<span class="section-number">3</span>'),
        ('id="nurse-review-section"', '<span class="section-number">4</span>'),
        ('id="text-intake-section"', '<span class="section-number">5</span>'),
        ('id="voicemail-intake-section"', '<span class="section-number">6</span>'),
        ('id="mock-notifications-section"', '<span class="section-number">7</span>'),
        ('id="reset-section"', '<span class="section-number">8</span>'),
    ]
    for section_id, section_number in expected_sections:
        section_start = html.index(section_id)
        section_html = html[section_start : section_start + 260]
        assert section_number in section_html


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


def test_demo_page_uses_screenshot_safe_fictional_sample_data() -> None:
    response = client.get("/demo")

    assert response.status_code == 200
    html = response.text
    assert "Demo Patient" in html
    assert "Voicemail Demo Patient" in html
    assert "000-000-0000" in html
    assert "000-000-0001" in html
    assert "Jane Doe" not in html
    assert "Alex Lee" not in html
    assert "555" not in html


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


def test_demo_page_includes_mock_notification_inspection_controls() -> None:
    response = client.get("/demo")

    assert response.status_code == 200
    html = response.text
    assert 'id="mock-notifications-section"' in html
    assert "Mock mode sends no real email or SMS." in html
    assert "Load Mock Email Notifications" in html
    assert "Load Mock SMS Notifications" in html
    assert 'id="loadEmailNotifications"' in html
    assert 'id="loadSmsNotifications"' in html
    assert 'id="emailNotifications"' in html
    assert 'id="smsNotifications"' in html


def test_demo_page_loads_existing_mock_notification_inspection_endpoints() -> None:
    response = client.get("/demo")

    assert response.status_code == 200
    html = response.text
    assert 'requestJson("/notifications/email")' in html
    assert 'requestJson("/notifications/sms")' in html
    assert "No mock email notifications recorded." in html
    assert "No mock SMS notifications recorded." in html
    assert "renderNotifications" in html
    assert "escapeHtml" in html


def test_demo_page_recent_cases_include_select_for_review_affordance() -> None:
    response = client.get("/demo")

    assert response.status_code == 200
    html = response.text
    assert 'data-case-id="${item.id}"' in html
    assert "Select for Review" in html


def test_demo_page_recent_cases_include_demo_friendly_case_summary_labels() -> None:
    response = client.get("/demo")

    assert response.status_code == 200
    html = response.text
    assert "Case ID" in html
    assert "Status" in html
    assert "Priority" in html
    assert "Intake channel" in html
    assert "Reported symptoms" in html
    assert "Summary preview" in html
    assert "Nurse review completed" in html


def test_demo_page_recent_cases_include_handoff_note_action() -> None:
    response = client.get("/demo")

    assert response.status_code == 200
    html = response.text
    assert 'data-handoff-case-id="${item.id}"' in html
    assert "Load Handoff Note" in html
    assert 'event.target.closest("[data-handoff-case-id]")' in html
    assert "loadHandoffNoteForCase(handoffButton.dataset.handoffCaseId)" in html


def test_demo_page_recent_cases_render_review_metadata_when_present() -> None:
    response = client.get("/demo")

    assert response.status_code == 200
    html = response.text
    assert "item.reviewedBy || item.reviewedAt || item.reviewNotes" in html
    assert "<strong>reviewedBy:</strong> ${escapeHtml(item.reviewedBy)}" in html
    assert "<strong>reviewedAt:</strong> ${escapeHtml(item.reviewedAt)}" in html
    assert "<strong>reviewNotes:</strong> ${escapeHtml(item.reviewNotes)}" in html


def test_demo_page_recent_cases_escape_user_controlled_review_text() -> None:
    response = client.get("/demo")

    assert response.status_code == 200
    html = response.text
    assert "function escapeHtml(value)" in html
    assert '${escapeHtml(item.summary || "No summary returned.")}' in html


def test_demo_page_select_for_review_populates_review_case_id() -> None:
    response = client.get("/demo")

    assert response.status_code == 200
    html = response.text
    assert 'const button = event.target.closest("[data-case-id]");' in html
    assert "selectedCaseId.value = button.dataset.caseId;" in html


def test_demo_page_includes_selected_case_context_panel() -> None:
    response = client.get("/demo")

    assert response.status_code == 200
    html = response.text
    assert "Selected Case Context" in html
    assert "Use this read-only context to compare the mock AI summary with nurse review notes." in html
    assert 'id="selectedCaseContext"' in html
    assert "No case selected for review." in html


def test_demo_page_includes_nurse_handoff_note_controls() -> None:
    response = client.get("/demo")

    assert response.status_code == 200
    html = response.text
    assert "Nurse Handoff Note" in html
    assert "Load Handoff Note" in html
    assert 'id="loadHandoffNote"' in html
    assert 'id="handoffNoteDisplay"' in html
    assert "<pre" in html
    assert "/handoff-note" in html


def test_demo_page_handoff_note_workflow_has_stable_messages() -> None:
    response = client.get("/demo")

    assert response.status_code == 200
    html = response.text
    assert "Select a saved case before loading a handoff note." in html
    assert "Could not load handoff note" in html
    assert "No handoff note loaded." in html
    assert "handoffNoteDisplay.textContent = data.handoffNote;" in html


def test_demo_page_select_for_review_renders_selected_case_context() -> None:
    response = client.get("/demo")

    assert response.status_code == 200
    html = response.text
    assert "let recentCases = [];" in html
    assert "recentCases = data;" in html
    assert "const selectedCase = recentCases.find((item) => item.id === button.dataset.caseId);" in html
    assert "renderSelectedCaseContext(selectedCase);" in html
    assert "function renderSelectedCaseContext(item)" in html
    assert "${escapeHtml(item.id)}" in html
    assert "${escapeHtml(item.intakeStatus || item.processingStatus || \"\")}" in html
    assert "${escapeHtml(item.urgency)}" in html
    assert "${escapeHtml(formatIntakeChannel(item))}" in html
    assert "${escapeHtml(formatReviewCompleted(item))}" in html
    assert "${escapeHtml(item.reviewStatus)}" in html
    assert "${escapeHtml(formatSymptoms(item))}" in html
    assert '${escapeHtml(item.summary || "No summary returned.")}' in html


def test_demo_page_selected_case_context_renders_review_metadata_when_present() -> None:
    response = client.get("/demo")

    assert response.status_code == 200
    html = response.text
    context_renderer = html[
        html.index("function renderSelectedCaseContext(item)") : html.index(
            "function showCase"
        )
    ]
    assert "item.reviewedBy || item.reviewedAt || item.reviewNotes" in context_renderer
    assert (
        "<strong>reviewedBy:</strong> ${escapeHtml(item.reviewedBy)}"
        in context_renderer
    )
    assert (
        "<strong>reviewedAt:</strong> ${escapeHtml(item.reviewedAt)}"
        in context_renderer
    )
    assert (
        "<strong>reviewNotes:</strong> ${escapeHtml(item.reviewNotes)}"
        in context_renderer
    )


def test_demo_page_reset_clears_selected_case_context() -> None:
    response = client.get("/demo")

    assert response.status_code == 200
    html = response.text
    assert "renderSelectedCaseContext(null);" in html


def test_demo_page_select_for_review_clears_stale_review_notes() -> None:
    response = client.get("/demo")

    assert response.status_code == 200
    html = response.text
    assert 'const reviewNotes = document.querySelector("#reviewNotes");' in html
    assert 'reviewNotes.value = "";' in html
    assert "reviewNotes.value = selectedCase.reviewNotes" not in html
    assert "reviewNotes.value = item.reviewNotes" not in html


def test_demo_page_select_for_review_jumps_to_nurse_review_and_focuses_input() -> None:
    response = client.get("/demo")

    assert response.status_code == 200
    html = response.text
    assert 'document.querySelector("#nurse-review-section").scrollIntoView' in html
    assert 'selectedCaseId.focus();' in html


def test_demo_page_select_for_review_shows_selected_case_status() -> None:
    response = client.get("/demo")

    assert response.status_code == 200
    html = response.text
    assert "Selected case" in html
    assert "for review." in html


def test_demo_page_successful_review_refreshes_cases_and_summary() -> None:
    response = client.get("/demo")

    assert response.status_code == 200
    html = response.text
    assert "showCase(reviewResult, item);" in html
    assert "await loadSummary();" in html
    assert "await loadCases();" in html


def test_demo_page_successful_review_shows_refreshed_queue_status() -> None:
    response = client.get("/demo")

    assert response.status_code == 200
    html = response.text
    assert "Review saved and queue refreshed." in html
