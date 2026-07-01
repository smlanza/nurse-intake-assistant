from fastapi.testclient import TestClient

from src.app.main import app


client = TestClient(app)


def get_openapi_schema() -> dict:
    return client.get("/openapi.json").json()


def get_request_examples(schema: dict, path: str, method: str) -> dict:
    return schema["paths"][path][method]["requestBody"]["content"][
        "application/json"
    ]["examples"]


def get_query_parameters(schema: dict, path: str) -> dict:
    parameters = schema["paths"][path]["get"]["parameters"]
    return {
        parameter["name"]: parameter
        for parameter in parameters
        if parameter["in"] == "query"
    }


def test_openapi_schema_includes_intake_paths() -> None:
    schema = get_openapi_schema()

    assert "/intake/text" in schema["paths"]
    assert "/intake/voicemail-transcript" in schema["paths"]
    assert "post" in schema["paths"]["/intake/text"]
    assert "post" in schema["paths"]["/intake/voicemail-transcript"]


def test_text_intake_openapi_exposes_demo_examples() -> None:
    schema = get_openapi_schema()

    examples = get_request_examples(schema, "/intake/text", "post")

    assert "complete_routine_text_intake" in examples
    assert "urgent_text_intake" in examples
    assert "incomplete_text_intake" in examples
    assert "complete routine text intake" in examples[
        "complete_routine_text_intake"
    ]["summary"].lower()
    assert "urgent text intake" in examples["urgent_text_intake"]["summary"].lower()
    assert "incomplete text intake" in examples[
        "incomplete_text_intake"
    ]["summary"].lower()


def test_voicemail_transcript_openapi_exposes_demo_examples() -> None:
    schema = get_openapi_schema()

    examples = get_request_examples(schema, "/intake/voicemail-transcript", "post")
    example_text = str(examples)

    assert "complete_routine_voicemail_transcript" in examples
    assert "urgent_voicemail_transcript" in examples
    assert "incomplete_voicemail_transcript" in examples
    assert "idempotent_repeat_voicemail_transcript" in examples
    assert "idempotencyKey" in example_text
    assert "sourceRecordingId" in example_text
    assert "audioBlobName" in example_text


def test_cases_openapi_includes_queue_filter_query_parameters() -> None:
    schema = get_openapi_schema()

    parameters = get_query_parameters(schema, "/cases")

    for parameter_name in [
        "sourceSystem",
        "caseType",
        "notificationEmailStatus",
        "notificationSmsStatus",
        "notificationSmsDeliveryConfirmed",
    ]:
        assert parameter_name in parameters
        assert parameters[parameter_name].get("description")


def test_case_summary_openapi_includes_queue_filter_query_parameters() -> None:
    schema = get_openapi_schema()

    parameters = get_query_parameters(schema, "/cases/summary")

    for parameter_name in [
        "sourceSystem",
        "caseType",
        "notificationEmailStatus",
        "notificationSmsStatus",
        "notificationSmsDeliveryConfirmed",
    ]:
        assert parameter_name in parameters
        assert parameters[parameter_name].get("description")


def test_handoff_note_openapi_documents_response_example() -> None:
    schema = get_openapi_schema()

    operation = schema["paths"]["/cases/{case_id}/handoff-note"]["get"]
    response_200 = operation["responses"]["200"]
    response_schema = response_200["content"]["application/json"]["schema"]
    response_example = response_200["content"]["application/json"]["example"]
    operation_text = str(operation)

    assert "handoff note" in operation["summary"].lower()
    assert "deterministic plain-text nurse handoff note" in operation["description"]
    assert response_schema["$ref"].endswith("/CaseHandoffNoteResponse")
    assert response_example["caseId"] == "demo-case-001"
    assert response_example["createdDate"] == "2026-06-30"
    assert response_example["noteFormat"] == "plainText"
    assert "DEMO ONLY - Not for production clinical use" in operation_text
    assert "AI-assisted output requires nurse review" in operation_text
    for section_heading in [
        "Patient Summary",
        "Reported Symptoms",
        "Red Flags",
        "Recommended Nurse Review Priority",
        "Notification Status",
    ]:
        assert section_heading in operation_text


def test_runtime_behavior_remains_unchanged_for_intake_and_queue() -> None:
    client.post("/demo/reset")

    text_response = client.post(
        "/intake/text",
        json={
            "text": (
                "My name is Jane Doe. DOB: 1980-04-15. "
                "My callback number is +1 (555) 555-0123. "
                "I need a medication refill."
            )
        },
    )
    voicemail_response = client.post(
        "/intake/voicemail-transcript",
        json={
            "transcript": (
                "My name is Alex Lee. DOB: 1975-03-20. "
                "My callback number is +1 (555) 555-0199. "
                "I need a medication refill."
            ),
            "idempotencyKey": "demo-voicemail-openapi-001",
        },
    )
    cases_response = client.get("/cases")
    summary_response = client.get("/cases/summary")

    assert text_response.status_code == 200
    assert voicemail_response.status_code == 200
    assert cases_response.status_code == 200
    assert summary_response.status_code == 200
