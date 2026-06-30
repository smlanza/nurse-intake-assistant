from types import SimpleNamespace

import pytest


def _settings(
    speech_provider: str = "azure",
    endpoint: str | None = "https://secret-speech.example.invalid/",
    region: str | None = "secret-region",
) -> SimpleNamespace:
    return SimpleNamespace(
        speech_provider_normalized=speech_provider,
        azure_speech_endpoint=endpoint,
        azure_speech_region=region,
    )


def _patch_settings(monkeypatch: pytest.MonkeyPatch, settings: SimpleNamespace) -> None:
    import scripts.smoke_speech_transcription as script

    monkeypatch.setattr(script, "AppSettings", lambda: settings)


def test_speech_smoke_script_check_refuses_mock_provider(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_speech_transcription as script

    _patch_settings(monkeypatch, _settings(speech_provider="mock"))
    monkeypatch.setattr(
        script,
        "azure_speech_sdk_available",
        lambda: pytest.fail("SDK check should not run after invalid config"),
    )

    exit_code = script.main(["--check"])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "SPEECH_PROVIDER=azure" in captured.err
    assert "SPEECH_PROVIDER=mock" in captured.err
    assert captured.out == ""


@pytest.mark.parametrize(
    "settings,expected_message",
    [
        (
            _settings(endpoint=None),
            "AZURE_SPEECH_ENDPOINT",
        ),
        (
            _settings(region=None),
            "AZURE_SPEECH_REGION",
        ),
    ],
)
def test_speech_smoke_script_check_refuses_missing_configuration(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    settings: SimpleNamespace,
    expected_message: str,
) -> None:
    import scripts.smoke_speech_transcription as script

    _patch_settings(monkeypatch, settings)
    monkeypatch.setattr(
        script,
        "azure_speech_sdk_available",
        lambda: pytest.fail("SDK check should not run after invalid config"),
    )

    exit_code = script.main(["--check"])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert expected_message in captured.err
    assert "secret-speech" not in captured.err
    assert "secret-region" not in captured.err
    assert captured.out == ""


def test_speech_smoke_script_check_succeeds_without_live_client_construction(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_speech_transcription as script

    _patch_settings(monkeypatch, _settings())
    monkeypatch.setattr(script, "azure_speech_sdk_available", lambda: True)

    exit_code = script.main(["--check"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "preflight passed" in captured.out
    assert "No Speech client was created" in captured.out
    assert "no Azure call was made" in captured.out
    assert "SDK package appears importable" in captured.out
    assert "SPEECH_PROVIDER=mock" in captured.out
    assert "secret-speech" not in captured.out
    assert "secret-region" not in captured.out
    assert captured.err == ""


def test_speech_smoke_script_check_reports_missing_sdk_gracefully(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_speech_transcription as script

    _patch_settings(monkeypatch, _settings())
    monkeypatch.setattr(script, "azure_speech_sdk_available", lambda: False)

    exit_code = script.main(["--check"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "preflight passed" in captured.out
    assert "SDK package is not importable" in captured.out
    assert "live transcription remains deferred" in captured.out
    assert captured.err == ""


def test_azure_speech_sdk_available_handles_missing_namespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scripts.smoke_speech_transcription as script

    def raise_missing_namespace(module_name: str) -> object:
        assert module_name == "azure.cognitiveservices.speech"
        raise ModuleNotFoundError("No module named 'azure.cognitiveservices'")

    monkeypatch.setattr(script.importlib.util, "find_spec", raise_missing_namespace)

    assert script.azure_speech_sdk_available() is False


def test_speech_smoke_script_without_check_is_deferred_and_safe(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_speech_transcription as script

    _patch_settings(monkeypatch, _settings())
    monkeypatch.setattr(
        script,
        "azure_speech_sdk_available",
        lambda: pytest.fail("SDK check should not run outside --check"),
    )

    exit_code = script.main([])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "live transcription is deferred" in captured.err
    assert "--check" in captured.err
    assert "SPEECH_PROVIDER=mock" in captured.err
    assert captured.out == ""
