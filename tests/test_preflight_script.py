from types import SimpleNamespace

import pytest


def _settings(
    ai_provider: str = "mock",
    foundry_endpoint: str | None = None,
    foundry_deployment: str | None = None,
    speech_provider: str = "mock",
    speech_endpoint: str | None = None,
    speech_region: str | None = None,
    email_provider: str = "mock",
    email_connection_string: str | None = None,
    email_sender_address: str | None = None,
    nurse_email: str | None = None,
    sms_provider: str = "mock",
    sms_connection_string: str | None = None,
    sms_from_phone_number: str | None = None,
    nurse_phone_number: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        ai_provider_normalized=ai_provider,
        azure_ai_foundry_project_endpoint=foundry_endpoint,
        azure_ai_foundry_model_deployment_name=foundry_deployment,
        speech_provider_normalized=speech_provider,
        azure_speech_endpoint=speech_endpoint,
        azure_speech_region=speech_region,
        email_provider_normalized=email_provider,
        acs_email_connection_string=email_connection_string,
        acs_email_sender_address=email_sender_address,
        nurse_notification_email=nurse_email,
        sms_provider_normalized=sms_provider,
        acs_sms_connection_string=sms_connection_string,
        acs_sms_from_phone_number=sms_from_phone_number,
        nurse_notification_phone_number=nurse_phone_number,
    )


def _patch_settings(monkeypatch: pytest.MonkeyPatch, settings: SimpleNamespace) -> None:
    import scripts.preflight as script

    monkeypatch.setattr(script, "AppSettings", lambda: settings)


def _patch_sdk_visibility(monkeypatch: pytest.MonkeyPatch) -> None:
    import scripts.preflight as script

    monkeypatch.setattr(script, "foundry_live_sdk_available", lambda: True)
    monkeypatch.setattr(script, "azure_speech_sdk_available", lambda: True)
    monkeypatch.setattr(script, "acs_email_sdk_available", lambda: True)
    monkeypatch.setattr(script, "acs_sms_sdk_available", lambda: True)


def test_preflight_all_skips_default_mock_providers(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.preflight as script

    _patch_settings(monkeypatch, _settings())
    _patch_sdk_visibility(monkeypatch)

    exit_code = script.main(["--all"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Nurse Intake Assistant Preflight" in captured.out
    assert "Foundry" in captured.out
    assert "Azure Speech" in captured.out
    assert "ACS Email" in captured.out
    assert "ACS SMS" in captured.out
    assert captured.out.count("SKIP") == 4
    assert "PASS" not in captured.out
    assert "FAIL" not in captured.out
    assert captured.err == ""


def test_preflight_all_skips_azure_speech_when_speech_provider_is_mock(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.preflight as script

    _patch_settings(monkeypatch, _settings(speech_provider="mock"))
    _patch_sdk_visibility(monkeypatch)

    exit_code = script.main(["--all"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "SKIP Azure Speech" in captured.out
    assert "SPEECH_PROVIDER is not azure" in captured.out
    assert "Keep SPEECH_PROVIDER=mock for local demo" in captured.out
    assert "No Azure clients" in captured.out
    assert "audio processing" in captured.out
    assert captured.err == ""


def test_preflight_all_fails_safely_when_azure_speech_config_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.preflight as script

    _patch_settings(monkeypatch, _settings(speech_provider="azure"))
    monkeypatch.setattr(
        script,
        "azure_speech_sdk_available",
        lambda: pytest.fail("SDK check should not run after invalid Speech config"),
    )

    exit_code = script.main(["--all"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "FAIL Azure Speech" in captured.out
    assert "AZURE_SPEECH_ENDPOINT" in captured.out
    assert "AZURE_SPEECH_REGION" in captured.out
    assert "Set missing Azure Speech variables or restore SPEECH_PROVIDER=mock" in captured.out
    assert "Traceback" not in captured.out
    assert captured.err == ""


def test_preflight_all_passes_configured_azure_speech_without_live_calls(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.preflight as script
    import src.app.services.speech_transcription_factory as speech_factory
    import src.app.services.speech_transcription_service as speech_service

    _patch_settings(
        monkeypatch,
        _settings(
            speech_provider="azure",
            speech_endpoint="https://placeholder-speech.example.invalid",
            speech_region="placeholder-region",
        ),
    )
    _patch_sdk_visibility(monkeypatch)
    monkeypatch.setattr(
        speech_factory,
        "create_speech_transcription_service",
        lambda settings: pytest.fail("Speech service should not be created"),
    )
    monkeypatch.setattr(
        speech_service.AzureSpeechTranscriptionService,
        "transcribe_text",
        lambda *args, **kwargs: pytest.fail("Speech transcription should not run"),
    )

    exit_code = script.main(["--all"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PASS Azure Speech" in captured.out
    assert "Required Speech configuration is present" in captured.out
    assert "No Speech client was created" in captured.out
    assert "no audio was processed" in captured.out
    assert "no Azure call was made" in captured.out
    assert captured.err == ""


def test_preflight_all_passes_configured_acs_email_and_sms(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.preflight as script

    _patch_settings(
        monkeypatch,
        _settings(
            email_provider="acs",
            email_connection_string=(
                "endpoint=https://secret-email.communication.azure.com/;"
                "accesskey=secret-email-key"
            ),
            email_sender_address="sender@clinic.example.com",
            nurse_email="nurse@clinic.example.com",
            sms_provider="acs",
            sms_connection_string=(
                "endpoint=https://secret-sms.communication.azure.com/;"
                "accesskey=secret-sms-key"
            ),
            sms_from_phone_number="+15555550100",
            nurse_phone_number="+15555550123",
        ),
    )
    _patch_sdk_visibility(monkeypatch)

    exit_code = script.main(["--all"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "ACS Email" in captured.out
    assert "ACS SMS" in captured.out
    assert captured.out.count("PASS") == 2
    assert captured.out.count("SKIP") == 2
    assert "FAIL" not in captured.out
    assert captured.err == ""


def test_preflight_all_fails_when_applicable_provider_config_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.preflight as script

    _patch_settings(monkeypatch, _settings(email_provider="acs"))
    monkeypatch.setattr(
        script,
        "acs_email_sdk_available",
        lambda: pytest.fail("SDK check should not run after invalid config"),
    )

    exit_code = script.main(["--all"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "ACS Email" in captured.out
    assert "FAIL" in captured.out
    assert "ACS_EMAIL_CONNECTION_STRING" in captured.out
    assert "SKIP" in captured.out
    assert captured.err == ""


def test_preflight_all_does_not_print_configured_secret_or_contact_values(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.preflight as script

    settings = _settings(
        ai_provider="foundry",
        foundry_endpoint="https://secret-foundry.services.ai.azure.com/api/projects/demo",
        foundry_deployment="secret-model-deployment",
        speech_provider="azure",
        speech_endpoint="https://secret-speech.cognitiveservices.azure.com/",
        speech_region="secret-region",
        email_provider="acs",
        email_connection_string=(
            "endpoint=https://secret-email.communication.azure.com/;"
            "accesskey=secret-email-key"
        ),
        email_sender_address="sender@clinic.example.com",
        nurse_email="nurse@clinic.example.com",
        sms_provider="acs",
        sms_connection_string=(
            "endpoint=https://secret-sms.communication.azure.com/;"
            "accesskey=secret-sms-key"
        ),
        sms_from_phone_number="+15555550100",
        nurse_phone_number="+15555550123",
    )
    _patch_settings(monkeypatch, settings)
    _patch_sdk_visibility(monkeypatch)

    exit_code = script.main(["--all"])

    captured = capsys.readouterr()
    combined_output = captured.out + captured.err
    assert exit_code == 0
    assert settings.azure_ai_foundry_project_endpoint not in combined_output
    assert settings.azure_ai_foundry_model_deployment_name not in combined_output
    assert settings.azure_speech_endpoint not in combined_output
    assert settings.azure_speech_region not in combined_output
    assert settings.acs_email_connection_string not in combined_output
    assert settings.acs_email_sender_address not in combined_output
    assert settings.nurse_notification_email not in combined_output
    assert settings.acs_sms_connection_string not in combined_output
    assert settings.acs_sms_from_phone_number not in combined_output
    assert settings.nurse_notification_phone_number not in combined_output
    assert "secret-foundry" not in combined_output
    assert "secret-model-deployment" not in combined_output
    assert "secret-speech" not in combined_output
    assert "secret-region" not in combined_output
    assert "secret-email" not in combined_output
    assert "sender@clinic.example.com" not in combined_output
    assert "nurse@clinic.example.com" not in combined_output
    assert "secret-sms" not in combined_output
    assert "+15555550100" not in combined_output
    assert "+15555550123" not in combined_output


def test_preflight_all_does_not_print_speech_secret_like_values(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.preflight as script

    settings = _settings(
        speech_provider="azure",
        speech_endpoint="https://speech-resource.example.invalid/?token=secret-speech-token",
        speech_region="secret-speech-region",
    )
    _patch_settings(monkeypatch, settings)
    _patch_sdk_visibility(monkeypatch)

    exit_code = script.main(["--all"])

    captured = capsys.readouterr()
    combined_output = captured.out + captured.err
    assert exit_code == 0
    assert "PASS Azure Speech" in combined_output
    assert settings.azure_speech_endpoint not in combined_output
    assert settings.azure_speech_region not in combined_output
    assert "secret-speech-token" not in combined_output
    assert "secret-speech-region" not in combined_output
    assert "token=" not in combined_output


def test_preflight_all_does_not_create_clients_or_send_or_call_live_services(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.preflight as script
    import src.app.services.email_notification_sender as email_sender
    import src.app.services.sms_notification_sender as sms_sender
    import src.app.services.ai_service_factory as ai_factory

    _patch_settings(
        monkeypatch,
        _settings(
            ai_provider="foundry",
            foundry_endpoint="https://placeholder-foundry.example.invalid",
            foundry_deployment="placeholder-deployment",
            speech_provider="azure",
            speech_endpoint="https://placeholder-speech.example.invalid",
            speech_region="placeholder-region",
            email_provider="acs",
            email_connection_string="endpoint=https://placeholder-email.example.invalid/;accesskey=placeholder",
            email_sender_address="sender-placeholder@example.invalid",
            nurse_email="nurse-placeholder@example.invalid",
            sms_provider="acs",
            sms_connection_string="endpoint=https://placeholder-sms.example.invalid/;accesskey=placeholder",
            sms_from_phone_number="+15555550100",
            nurse_phone_number="+15555550123",
        ),
    )
    _patch_sdk_visibility(monkeypatch)
    monkeypatch.setattr(
        ai_factory,
        "create_ai_service",
        lambda settings: pytest.fail("AI service should not be created"),
    )
    monkeypatch.setattr(
        email_sender,
        "create_acs_email_client",
        lambda connection_string: pytest.fail("ACS Email client should not be created"),
    )
    monkeypatch.setattr(
        email_sender.AcsEmailNotificationSender,
        "send_case_notification",
        lambda *args, **kwargs: pytest.fail("Email should not be sent"),
    )
    monkeypatch.setattr(
        sms_sender,
        "create_acs_sms_client",
        lambda connection_string: pytest.fail("ACS SMS client should not be created"),
    )
    monkeypatch.setattr(
        sms_sender.AcsSmsNotificationSender,
        "send_case_notification",
        lambda *args, **kwargs: pytest.fail("SMS should not be sent"),
    )

    exit_code = script.main(["--all"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PASS" in captured.out
    assert captured.err == ""
