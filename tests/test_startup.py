import pytest
from autollm_admin.main import build, check_startup_config


@pytest.mark.parametrize("env,mock,ok", [("production", "1", False), ("PRODUCTION", "1", False), ("production", "0", True),
                                          ("development", "1", True), ("", "1", True)])
def test_mock_payment_guard(monkeypatch, env, mock, ok):
    monkeypatch.setenv("ENV", env)
    monkeypatch.setenv("ENABLE_MOCK_PAYMENT", mock)
    monkeypatch.setenv("SESSION_SECRET", "x" * 40)
    if ok:
        check_startup_config()
    else:
        with pytest.raises(RuntimeError, match="ENABLE_MOCK_PAYMENT"):
            check_startup_config()


def test_build_refuses_in_production_with_mock(monkeypatch, master_key):
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("ENABLE_MOCK_PAYMENT", "1")
    with pytest.raises(RuntimeError):
        build("sqlite://", master_key)


def test_production_requires_session_secret(monkeypatch):
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("ENABLE_MOCK_PAYMENT", "0")
    monkeypatch.delenv("SESSION_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="SESSION_SECRET"):
        check_startup_config()
