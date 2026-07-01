from types import SimpleNamespace

import pytest


def _settings(
    sms_provider: str = "acs",
    connection_string: str | None = (
        "endpoint=https://secret-sms-resource.communication.azure.com/;"
        "accesskey=secret-sms-access-key"
    ),
    from_phone_number: str | None = "+15555550100",
    nurse_phone_number: str | None = "+15555550123",
) -> SimpleNamespace:
    return SimpleNamespace(
        sms_provider_normalized=sms_provider,
        acs_sms_connection_string=connection_string,
        acs_sms_from_phone_number=from_phone_number,
        nurse_notification_phone_number=nurse_phone_number,
    )


def _patch_settings(monkeypatch: pytest.MonkeyPatch, settings: SimpleNamespace) -> None:
    import scripts.smoke_acs_sms as script

    monkeypatch.setattr(script, "AppSettings", lambda: settings)


def test_acs_sms_smoke_script_check_succeeds_with_required_config(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_acs_sms as script

    _patch_settings(monkeypatch, _settings())
    monkeypatch.setattr(script, "acs_sms_sdk_available", lambda: True)

    exit_code = script.main(["--check"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "preflight passed" in captured.out
    assert "No ACS SMS client was created" in captured.out
    assert "no Azure call was made" in captured.out
    assert "no SMS was sent" in captured.out
    assert "SDK package appears importable" in captured.out
    assert "SMS_PROVIDER=mock" in captured.out
    assert captured.err == ""


def test_acs_sms_smoke_script_check_refuses_non_acs_provider(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_acs_sms as script

    _patch_settings(monkeypatch, _settings(sms_provider="mock"))
    monkeypatch.setattr(
        script,
        "acs_sms_sdk_available",
        lambda: pytest.fail("SDK check should not run after invalid config"),
    )

    exit_code = script.main(["--check"])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "SMS_PROVIDER=acs" in captured.err
    assert "SMS_PROVIDER=mock" in captured.err
    assert captured.out == ""


@pytest.mark.parametrize(
    "settings,expected_message",
    [
        (_settings(connection_string=None), "ACS_SMS_CONNECTION_STRING"),
        (_settings(from_phone_number=None), "ACS_SMS_FROM_PHONE_NUMBER"),
        (_settings(nurse_phone_number=None), "NURSE_NOTIFICATION_PHONE_NUMBER"),
    ],
)
def test_acs_sms_smoke_script_check_refuses_missing_configuration(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    settings: SimpleNamespace,
    expected_message: str,
) -> None:
    import scripts.smoke_acs_sms as script

    _patch_settings(monkeypatch, settings)
    monkeypatch.setattr(
        script,
        "acs_sms_sdk_available",
        lambda: pytest.fail("SDK check should not run after invalid config"),
    )

    exit_code = script.main(["--check"])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert expected_message in captured.err
    assert "secret-sms-resource" not in captured.err
    assert "secret-sms-access-key" not in captured.err
    assert "+15555550100" not in captured.err
    assert "+15555550123" not in captured.err
    assert captured.out == ""


def test_acs_sms_smoke_script_check_does_not_print_configured_secrets_or_numbers(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_acs_sms as script

    settings = _settings()
    _patch_settings(monkeypatch, settings)
    monkeypatch.setattr(script, "acs_sms_sdk_available", lambda: False)

    exit_code = script.main(["--check"])

    captured = capsys.readouterr()
    combined_output = captured.out + captured.err
    assert exit_code == 0
    assert settings.acs_sms_connection_string not in combined_output
    assert settings.acs_sms_from_phone_number not in combined_output
    assert settings.nurse_notification_phone_number not in combined_output
    assert "secret-sms-resource" not in combined_output
    assert "secret-sms-access-key" not in combined_output
    assert "+15555550100" not in combined_output
    assert "+15555550123" not in combined_output


def test_acs_sms_smoke_script_check_does_not_create_client_or_send_sms(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_acs_sms as script
    import src.app.services.sms_notification_sender as sms_sender

    _patch_settings(monkeypatch, _settings())
    monkeypatch.setattr(script, "acs_sms_sdk_available", lambda: True)
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

    exit_code = script.main(["--check"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "No ACS SMS client was created" in captured.out
    assert "no SMS was sent" in captured.out
    assert captured.err == ""


def test_acs_sms_sdk_available_handles_missing_namespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scripts.smoke_acs_sms as script

    def raise_missing_namespace(module_name: str) -> object:
        assert module_name == "azure.communication.sms"
        raise ModuleNotFoundError("No module named 'azure.communication'")

    monkeypatch.setattr(script.importlib.util, "find_spec", raise_missing_namespace)

    assert script.acs_sms_sdk_available() is False


def test_acs_sms_smoke_script_without_check_is_deferred_and_safe(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_acs_sms as script

    _patch_settings(monkeypatch, _settings())
    monkeypatch.setattr(
        script,
        "acs_sms_sdk_available",
        lambda: pytest.fail("SDK check should not run outside --check"),
    )

    exit_code = script.main([])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "live ACS SMS smoke mode is not implemented" in captured.err
    assert "--check" in captured.err
    assert "SMS_PROVIDER=mock" in captured.err
    assert captured.out == ""
