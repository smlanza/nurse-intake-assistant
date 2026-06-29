from types import SimpleNamespace

import pytest

from src.app.models.ai_outputs import (
    ExtractionSummaryResult,
    PatientInfo,
    UrgencyClassificationResult,
)


def _settings(
    ai_provider: str = "foundry",
    endpoint: str | None = "https://secret-endpoint.example.invalid/api/projects/demo",
    deployment: str | None = "secret-deployment",
) -> SimpleNamespace:
    return SimpleNamespace(
        ai_provider_normalized=ai_provider,
        azure_ai_foundry_project_endpoint=endpoint,
        azure_ai_foundry_model_deployment_name=deployment,
    )


def _patch_settings(monkeypatch: pytest.MonkeyPatch, settings: SimpleNamespace) -> None:
    import scripts.smoke_foundry_extraction as script

    monkeypatch.setattr(script, "AppSettings", lambda: settings)


def test_foundry_smoke_script_refuses_mock_provider(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_foundry_extraction as script

    _patch_settings(monkeypatch, _settings(ai_provider="mock"))

    exit_code = script.main()

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "AI_PROVIDER=foundry" in captured.err
    assert "AI_PROVIDER=mock" in captured.err


@pytest.mark.parametrize(
    "settings,expected_message",
    [
        (
            _settings(endpoint=None),
            "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT",
        ),
        (
            _settings(deployment=None),
            "AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT_NAME",
        ),
    ],
)
def test_foundry_smoke_script_refuses_missing_foundry_configuration(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    settings: SimpleNamespace,
    expected_message: str,
) -> None:
    import scripts.smoke_foundry_extraction as script

    _patch_settings(monkeypatch, settings)

    exit_code = script.main()

    captured = capsys.readouterr()
    assert exit_code == 2
    assert expected_message in captured.err
    assert "secret-endpoint" not in captured.err
    assert "secret-deployment" not in captured.err


def test_foundry_smoke_script_calls_fake_ai_service_and_prints_safe_result(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_foundry_extraction as script

    fake_service = FakeAiService()
    _patch_settings(monkeypatch, _settings())
    monkeypatch.setattr(script, "create_ai_service", lambda settings: fake_service)

    exit_code = script.main()

    captured = capsys.readouterr()
    assert exit_code == 0
    assert fake_service.extraction_texts == [script.FICTIONAL_INTAKE_TEXT]
    assert fake_service.urgency_texts == [script.FICTIONAL_INTAKE_TEXT]
    assert "Demo Patient" in captured.out
    assert "medication refill" in captured.out
    assert "fatigue" in captured.out
    assert "patient.callback_number" in captured.out
    assert "Routine" in captured.out
    assert "nurse review" in captured.out
    assert "secret-endpoint" not in captured.out
    assert "secret-deployment" not in captured.out
    assert "Return JSON only" not in captured.out
    assert captured.err == ""


def test_foundry_smoke_script_uses_fictional_input_only() -> None:
    import scripts.smoke_foundry_extraction as script

    assert "Demo Patient" in script.FICTIONAL_INTAKE_TEXT
    assert "demo-callback-001" in script.FICTIONAL_INTAKE_TEXT
    assert "+1" not in script.FICTIONAL_INTAKE_TEXT
    assert "555" not in script.FICTIONAL_INTAKE_TEXT
    assert "@" not in script.FICTIONAL_INTAKE_TEXT


def test_foundry_smoke_script_failure_uses_safe_message(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_foundry_extraction as script

    _patch_settings(monkeypatch, _settings())
    monkeypatch.setattr(
        script,
        "create_ai_service",
        lambda settings: FailingAiService(),
    )

    exit_code = script.main()

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Foundry smoke test failed" in captured.err
    assert "private failure marker" not in captured.err
    assert "secret-endpoint" not in captured.err
    assert "secret-deployment" not in captured.err
    assert "Return JSON only" not in captured.err
    assert captured.out == ""


class FakeAiService:
    def __init__(self) -> None:
        self.extraction_texts: list[str] = []
        self.urgency_texts: list[str] = []

    async def extract_and_summarize(self, raw_text: str) -> ExtractionSummaryResult:
        self.extraction_texts.append(raw_text)
        return ExtractionSummaryResult(
            patient=PatientInfo(
                name="Demo Patient",
                date_of_birth="1980-04-15",
                callback_number=None,
            ),
            reason_for_calling="medication refill",
            symptoms=["fatigue"],
            summary="Demo patient requests a medication refill.",
            missing_fields=["patient.callback_number"],
            uncertain_fields=[],
        )

    async def classify_urgency(self, raw_text: str) -> UrgencyClassificationResult:
        self.urgency_texts.append(raw_text)
        return UrgencyClassificationResult(
            urgency="Routine",
            urgency_rationale="No urgent symptoms were described.",
            advisory_disclaimer=(
                "Advisory urgency only; nurse review and clinical judgment "
                "are required."
            ),
        )


class FailingAiService:
    async def extract_and_summarize(self, raw_text: str) -> ExtractionSummaryResult:
        raise RuntimeError("private failure marker")

    async def classify_urgency(self, raw_text: str) -> UrgencyClassificationResult:
        raise RuntimeError("private failure marker")
