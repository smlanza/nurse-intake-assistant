from types import SimpleNamespace

import pytest


def _settings(
    email_provider: str = "acs",
    connection_string: str | None = (
        "endpoint=https://secret-resource.communication.azure.com/;"
        "accesskey=secret-access-key"
    ),
    sender_address: str | None = "alerts.sender@clinic.example.com",
    nurse_email: str | None = "triage.nurse@clinic.example.com",
) -> SimpleNamespace:
    return SimpleNamespace(
        email_provider_normalized=email_provider,
        acs_email_connection_string=connection_string,
        acs_email_sender_address=sender_address,
        nurse_notification_email=nurse_email,
    )


def _patch_settings(monkeypatch: pytest.MonkeyPatch, settings: SimpleNamespace) -> None:
    import scripts.smoke_acs_email as script

    monkeypatch.setattr(script, "AppSettings", lambda: settings)


def test_acs_email_smoke_script_check_succeeds_with_required_config(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_acs_email as script

    _patch_settings(monkeypatch, _settings())
    monkeypatch.setattr(script, "acs_email_sdk_available", lambda: True)

    exit_code = script.main(["--check"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "preflight passed" in captured.out
    assert "No ACS Email client was created" in captured.out
    assert "no Azure call was made" in captured.out
    assert "no email was sent" in captured.out
    assert "SDK package appears importable" in captured.out
    assert "EMAIL_PROVIDER=mock" in captured.out
    assert captured.err == ""


def test_acs_email_smoke_script_check_refuses_non_acs_provider(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_acs_email as script

    _patch_settings(monkeypatch, _settings(email_provider="mock"))
    monkeypatch.setattr(
        script,
        "acs_email_sdk_available",
        lambda: pytest.fail("SDK check should not run after invalid config"),
    )

    exit_code = script.main(["--check"])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "EMAIL_PROVIDER=acs" in captured.err
    assert "EMAIL_PROVIDER=mock" in captured.err
    assert captured.out == ""


@pytest.mark.parametrize(
    "settings,expected_message",
    [
        (_settings(connection_string=None), "ACS_EMAIL_CONNECTION_STRING"),
        (_settings(sender_address=None), "ACS_EMAIL_SENDER_ADDRESS"),
        (_settings(nurse_email=None), "NURSE_NOTIFICATION_EMAIL"),
    ],
)
def test_acs_email_smoke_script_check_refuses_missing_configuration(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    settings: SimpleNamespace,
    expected_message: str,
) -> None:
    import scripts.smoke_acs_email as script

    _patch_settings(monkeypatch, settings)
    monkeypatch.setattr(
        script,
        "acs_email_sdk_available",
        lambda: pytest.fail("SDK check should not run after invalid config"),
    )

    exit_code = script.main(["--check"])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert expected_message in captured.err
    assert "secret-resource" not in captured.err
    assert "secret-access-key" not in captured.err
    assert "alerts.sender@clinic.example.com" not in captured.err
    assert "triage.nurse@clinic.example.com" not in captured.err
    assert captured.out == ""


def test_acs_email_smoke_script_check_does_not_print_configured_secrets(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_acs_email as script

    settings = _settings()
    _patch_settings(monkeypatch, settings)
    monkeypatch.setattr(script, "acs_email_sdk_available", lambda: False)

    exit_code = script.main(["--check"])

    captured = capsys.readouterr()
    combined_output = captured.out + captured.err
    assert exit_code == 0
    assert settings.acs_email_connection_string not in combined_output
    assert settings.acs_email_sender_address not in combined_output
    assert settings.nurse_notification_email not in combined_output
    assert "secret-resource" not in combined_output
    assert "secret-access-key" not in combined_output
    assert "alerts.sender@clinic.example.com" not in combined_output
    assert "triage.nurse@clinic.example.com" not in combined_output


def test_acs_email_smoke_script_check_does_not_create_client_or_send_email(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_acs_email as script
    import src.app.services.email_notification_sender as email_sender

    _patch_settings(monkeypatch, _settings())
    monkeypatch.setattr(script, "acs_email_sdk_available", lambda: True)
    monkeypatch.setattr(
        email_sender,
        "create_acs_email_client",
        lambda connection_string: pytest.fail("ACS client should not be created"),
    )
    monkeypatch.setattr(
        email_sender.AcsEmailNotificationSender,
        "send_case_notification",
        lambda *args, **kwargs: pytest.fail("Email should not be sent"),
    )

    exit_code = script.main(["--check"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "No ACS Email client was created" in captured.out
    assert "no email was sent" in captured.out
    assert captured.err == ""


def test_acs_email_sdk_available_handles_missing_namespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scripts.smoke_acs_email as script

    def raise_missing_namespace(module_name: str) -> object:
        assert module_name == "azure.communication.email"
        raise ModuleNotFoundError("No module named 'azure.communication'")

    monkeypatch.setattr(script.importlib.util, "find_spec", raise_missing_namespace)

    assert script.acs_email_sdk_available() is False


def test_acs_email_smoke_script_without_check_is_deferred_and_safe(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_acs_email as script

    _patch_settings(monkeypatch, _settings())
    monkeypatch.setattr(
        script,
        "acs_email_sdk_available",
        lambda: pytest.fail("SDK check should not run outside --check"),
    )

    exit_code = script.main([])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "live ACS Email smoke mode is not implemented" in captured.err
    assert "--check" in captured.err
    assert "EMAIL_PROVIDER=mock" in captured.err
    assert captured.out == ""
