from types import SimpleNamespace

import pytest

from src.app.models.ai_outputs import (
    ExtractionSummaryResult,
    PatientInfo,
    UrgencyClassificationResult,
)
from src.app.services.foundry_extraction_contract import FoundryExtractionContractError


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


def _clear_foundry_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in [
        "AI_PROVIDER",
        "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT",
        "AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT_NAME",
    ]:
        monkeypatch.delenv(name, raising=False)


def _write_foundry_env_file(
    tmp_path,
    endpoint: str = "https://secret-env-file-endpoint.example.invalid/api/projects/demo",
    deployment: str = "secret-env-file-deployment",
):
    env_file = tmp_path / ".env.foundry.local"
    env_file.write_text(
        "\n".join(
            [
                "# local manual smoke settings",
                "",
                "AI_PROVIDER=foundry",
                f"AZURE_AI_FOUNDRY_PROJECT_ENDPOINT={endpoint}",
                f"AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT_NAME={deployment}",
                "",
            ]
        )
    )
    return env_file


class FakeHttpError(RuntimeError):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


def test_foundry_smoke_script_refuses_mock_provider(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_foundry_extraction as script

    _patch_settings(monkeypatch, _settings(ai_provider="mock"))

    exit_code = script.main(["--check"])

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

    exit_code = script.main(["--check"])

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
    monkeypatch.setattr(script, "foundry_live_sdk_available", lambda: True)
    monkeypatch.setattr(script, "create_ai_service", lambda settings: fake_service)

    exit_code = script.main(["--live"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert fake_service.extraction_texts == [script.FICTIONAL_INTAKE_TEXT]
    assert fake_service.urgency_texts == [script.FICTIONAL_INTAKE_TEXT]
    assert "manual Azure AI Foundry smoke test" in captured.out
    assert "Alex Morgan" in captured.out
    assert "medication refill" in captured.out
    assert "fatigue" in captured.out
    assert "patient.date_of_birth" in captured.out
    assert "Routine" in captured.out
    assert "nurse review" in captured.out
    assert "secret-endpoint" not in captured.out
    assert "secret-deployment" not in captured.out
    assert "Return JSON only" not in captured.out
    assert captured.err == ""


def test_foundry_smoke_script_uses_fictional_input_only() -> None:
    import scripts.smoke_foundry_extraction as script

    assert "Alex Morgan" in script.FICTIONAL_INTAKE_TEXT
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
    monkeypatch.setattr(script, "foundry_live_sdk_available", lambda: True)
    monkeypatch.setattr(
        script,
        "create_ai_service",
        lambda settings: FailingAiService(),
    )

    exit_code = script.main(["--live"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Foundry smoke test failed" in captured.err
    assert "private failure marker" not in captured.err
    assert "secret-endpoint" not in captured.err
    assert "secret-deployment" not in captured.err
    assert "Return JSON only" not in captured.err
    assert "Safe failure category: unknown live smoke failure" in captured.err
    assert "Next check:" in captured.err
    assert "not part of automated pytest" in captured.out


def test_foundry_smoke_script_check_refuses_mock_provider(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_foundry_extraction as script

    _patch_settings(monkeypatch, _settings(ai_provider="mock"))
    monkeypatch.setattr(
        script,
        "create_ai_service",
        lambda settings: pytest.fail("create_ai_service should not be called"),
    )

    exit_code = script.main(["--check"])

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
def test_foundry_smoke_script_check_refuses_missing_foundry_configuration(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    settings: SimpleNamespace,
    expected_message: str,
) -> None:
    import scripts.smoke_foundry_extraction as script

    _patch_settings(monkeypatch, settings)
    monkeypatch.setattr(
        script,
        "create_ai_service",
        lambda settings: pytest.fail("create_ai_service should not be called"),
    )

    exit_code = script.main(["--check"])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert expected_message in captured.err
    assert "secret-endpoint" not in captured.err
    assert "secret-deployment" not in captured.err


def test_foundry_smoke_script_check_succeeds_without_model_call(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_foundry_extraction as script

    _patch_settings(monkeypatch, _settings())
    monkeypatch.setattr(script, "foundry_live_sdk_available", lambda: True)
    monkeypatch.setattr(
        script,
        "create_ai_service",
        lambda settings: pytest.fail("create_ai_service should not be called"),
    )

    exit_code = script.main(["--check"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "preflight passed" in captured.out
    assert "No AI service was created" in captured.out
    assert "No model call was made" in captured.out
    assert "AI_PROVIDER=mock" in captured.out
    assert captured.err == ""
    assert "secret-endpoint" not in captured.out
    assert "secret-deployment" not in captured.out
    assert "Return JSON only" not in captured.out


def test_foundry_smoke_script_check_loads_missing_values_from_env_file(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path,
) -> None:
    import scripts.smoke_foundry_extraction as script

    _clear_foundry_env(monkeypatch)
    env_file = _write_foundry_env_file(tmp_path)
    monkeypatch.setattr(script, "foundry_live_sdk_available", lambda: True)
    monkeypatch.setattr(
        script,
        "create_ai_service",
        lambda settings: pytest.fail("create_ai_service should not be called"),
    )

    exit_code = script.main(["--env-file", str(env_file), "--check"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert f"Loaded environment file: {env_file}" in captured.out
    assert "preflight passed" in captured.out
    assert "No AI service was created" in captured.out
    assert "No model call was made" in captured.out
    assert "secret-env-file-endpoint" not in captured.out
    assert "secret-env-file-deployment" not in captured.out
    assert captured.err == ""


def test_foundry_smoke_script_env_file_missing_path_fails_safely(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path,
) -> None:
    import scripts.smoke_foundry_extraction as script

    _clear_foundry_env(monkeypatch)
    missing_env_file = tmp_path / ".env.foundry.local"
    monkeypatch.setattr(
        script,
        "create_ai_service",
        lambda settings: pytest.fail("create_ai_service should not be called"),
    )

    exit_code = script.main(["--env-file", str(missing_env_file), "--check"])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "env file not found" in captured.err
    assert "No Azure call was made" in captured.err
    assert "secret-env-file-endpoint" not in captured.err
    assert captured.out == ""


def test_foundry_smoke_script_shell_environment_overrides_env_file(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path,
) -> None:
    import scripts.smoke_foundry_extraction as script

    _clear_foundry_env(monkeypatch)
    monkeypatch.setenv("AI_PROVIDER", "mock")
    env_file = _write_foundry_env_file(tmp_path)

    exit_code = script.main(["--env-file", str(env_file), "--check"])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "AI_PROVIDER=foundry" in captured.err
    assert "secret-env-file-endpoint" not in captured.out
    assert "secret-env-file-endpoint" not in captured.err
    assert "secret-env-file-deployment" not in captured.out
    assert "secret-env-file-deployment" not in captured.err


def test_foundry_smoke_script_live_uses_env_file_with_fake_service(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path,
) -> None:
    import scripts.smoke_foundry_extraction as script

    _clear_foundry_env(monkeypatch)
    env_file = _write_foundry_env_file(tmp_path)
    fake_service = FakeAiService()
    monkeypatch.setattr(script, "foundry_live_sdk_available", lambda: True)
    monkeypatch.setattr(script, "create_ai_service", lambda settings: fake_service)

    exit_code = script.main(["--env-file", str(env_file), "--live"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert fake_service.extraction_texts == [script.FICTIONAL_INTAKE_TEXT]
    assert "manual Azure AI Foundry smoke test" in captured.out
    assert "Alex Morgan" in captured.out
    assert "secret-env-file-endpoint" not in captured.out
    assert "secret-env-file-deployment" not in captured.out
    assert captured.err == ""


def test_foundry_smoke_script_existing_inline_environment_still_works(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_foundry_extraction as script

    _clear_foundry_env(monkeypatch)
    monkeypatch.setenv("AI_PROVIDER", "foundry")
    monkeypatch.setenv(
        "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT",
        "https://secret-inline-endpoint.example.invalid/api/projects/demo",
    )
    monkeypatch.setenv(
        "AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT_NAME",
        "secret-inline-deployment",
    )
    monkeypatch.setattr(script, "foundry_live_sdk_available", lambda: True)
    monkeypatch.setattr(
        script,
        "create_ai_service",
        lambda settings: pytest.fail("create_ai_service should not be called"),
    )

    exit_code = script.main(["--check"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "preflight passed" in captured.out
    assert "secret-inline-endpoint" not in captured.out
    assert "secret-inline-deployment" not in captured.out


def test_foundry_smoke_script_check_reports_sdk_unavailable_without_model_call(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_foundry_extraction as script

    _patch_settings(monkeypatch, _settings())
    monkeypatch.setattr(script, "foundry_live_sdk_available", lambda: False)
    monkeypatch.setattr(
        script,
        "create_ai_service",
        lambda settings: pytest.fail("create_ai_service should not be called"),
    )

    exit_code = script.main(["--check"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Optional Foundry SDK imports are unavailable" in captured.out
    assert "No model call was made" in captured.out
    assert "AI_PROVIDER=mock" in captured.out
    assert "secret-endpoint" not in captured.out
    assert "secret-deployment" not in captured.out
    assert "Return JSON only" not in captured.out
    assert captured.err == ""


def test_foundry_smoke_script_live_fails_safely_when_sdk_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_foundry_extraction as script

    _patch_settings(monkeypatch, _settings())
    monkeypatch.setattr(script, "foundry_live_sdk_available", lambda: False)
    monkeypatch.setattr(
        script,
        "create_ai_service",
        lambda settings: pytest.fail("create_ai_service should not be called"),
    )

    exit_code = script.main(["--live"])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "Optional Foundry SDK support is unavailable for --live" in captured.err
    assert "AI_PROVIDER=mock" in captured.err
    assert "secret-endpoint" not in captured.err
    assert "secret-deployment" not in captured.err
    assert captured.out == ""


@pytest.mark.parametrize(
    "error,expected_category",
    [
        (
            RuntimeError("DefaultAzureCredential failed to retrieve a token"),
            "Azure credential unavailable",
        ),
        (FakeHttpError(401, "Bearer token expired"), "authentication failed"),
        (
            FakeHttpError(403, "Caller lacks project role assignment"),
            "authorization/RBAC failed",
        ),
        (
            FakeHttpError(404, "Deployment secret-deployment not found"),
            "deployment or model not found",
        ),
        (FakeHttpError(400, "Endpoint rejected request"), "endpoint rejected request"),
        (
            FoundryExtractionContractError("not valid JSON"),
            "model response parsing failed",
        ),
        (RuntimeError("private failure marker"), "unknown live smoke failure"),
    ],
)
def test_classify_live_smoke_failure_returns_safe_categories(
    error: BaseException,
    expected_category: str,
) -> None:
    import scripts.smoke_foundry_extraction as script

    assert script.classify_live_smoke_failure(error) == expected_category


def test_classify_live_smoke_failure_uses_nested_status_code() -> None:
    import scripts.smoke_foundry_extraction as script

    try:
        raise FakeHttpError(404, "model secret-deployment not found")
    except FakeHttpError as exc:
        wrapped_error = RuntimeError("Azure AI Foundry structured extraction failed")
        wrapped_error.__cause__ = exc

    assert (
        script.classify_live_smoke_failure(wrapped_error)
        == "deployment or model not found"
    )


def test_foundry_smoke_script_live_failure_prints_safe_category_only(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_foundry_extraction as script

    _patch_settings(monkeypatch, _settings())
    monkeypatch.setattr(script, "foundry_live_sdk_available", lambda: True)
    monkeypatch.setattr(
        script,
        "create_ai_service",
        lambda settings: RaisingAiService(
            FakeHttpError(
                403,
                (
                    "Forbidden for https://secret-endpoint.example.invalid "
                    "deployment secret-deployment token secret-token prompt "
                    "Return JSON only"
                ),
            )
        ),
    )

    exit_code = script.main(["--live"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Safe failure category: authorization/RBAC failed" in captured.err
    assert "Next check:" in captured.err
    assert "secret-endpoint" not in captured.err
    assert "secret-deployment" not in captured.err
    assert "secret-token" not in captured.err
    assert "Return JSON only" not in captured.err
    assert "Forbidden" not in captured.err


class FakeAiService:
    def __init__(self) -> None:
        self.extraction_texts: list[str] = []
        self.urgency_texts: list[str] = []

    async def extract_and_summarize(self, raw_text: str) -> ExtractionSummaryResult:
        self.extraction_texts.append(raw_text)
        return ExtractionSummaryResult(
            patient=PatientInfo(
                name="Alex Morgan",
                date_of_birth=None,
                callback_number="demo-callback-001",
            ),
            reason_for_calling="medication refill",
            symptoms=["fatigue"],
            summary="Demo patient requests a medication refill.",
            missing_fields=["patient.date_of_birth"],
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


class RaisingAiService:
    def __init__(self, error: BaseException) -> None:
        self.error = error

    async def extract_and_summarize(self, raw_text: str) -> ExtractionSummaryResult:
        raise self.error

    async def classify_urgency(self, raw_text: str) -> UrgencyClassificationResult:
        raise self.error
