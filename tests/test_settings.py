import pytest


def test_demo_suppress_notifications_defaults_to_false(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.app.config.settings import AppSettings

    monkeypatch.delenv("DEMO_SUPPRESS_NOTIFICATIONS", raising=False)

    settings = AppSettings()

    assert settings.demo_suppress_notifications is False


def test_demo_suppress_notifications_reads_true(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.app.config.settings import AppSettings

    monkeypatch.setenv("DEMO_SUPPRESS_NOTIFICATIONS", "true")

    assert AppSettings().demo_suppress_notifications is True


def test_demo_suppress_notifications_reads_false(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.app.config.settings import AppSettings

    monkeypatch.setenv("DEMO_SUPPRESS_NOTIFICATIONS", "false")

    assert AppSettings().demo_suppress_notifications is False


@pytest.mark.parametrize("value", ["1", "true", "yes", "on"])
def test_demo_suppress_notifications_accepts_truthy_values(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    from src.app.config.settings import AppSettings

    monkeypatch.setenv("DEMO_SUPPRESS_NOTIFICATIONS", value)

    assert AppSettings().demo_suppress_notifications is True


@pytest.mark.parametrize("value", ["0", "false", "no", "off"])
def test_demo_suppress_notifications_accepts_falsey_values(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    from src.app.config.settings import AppSettings

    monkeypatch.setenv("DEMO_SUPPRESS_NOTIFICATIONS", value)

    assert AppSettings().demo_suppress_notifications is False


def test_app_mode_defaults_to_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.app.config.settings import AppSettings

    monkeypatch.delenv("APP_MODE", raising=False)

    assert AppSettings().app_mode == "mock"


def test_app_mode_reads_environment_value(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.app.config.settings import AppSettings

    monkeypatch.setenv("APP_MODE", "azure")

    assert AppSettings().app_mode == "azure"
