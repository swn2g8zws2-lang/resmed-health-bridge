import pytest

from resmed_health_bridge.config import Settings


def test_stdio_uses_safe_defaults(monkeypatch):
    for name in ("RESMED_MCP_TRANSPORT", "RESMED_MCP_HOST"):
        monkeypatch.delenv(name, raising=False)
    settings = Settings.from_env()
    assert settings.transport == "stdio"
    assert settings.host == "127.0.0.1"


def test_http_must_use_loopback(monkeypatch):
    monkeypatch.setenv("RESMED_MCP_TRANSPORT", "streamable-http")
    monkeypatch.setenv("RESMED_MCP_HOST", "0.0.0.0")
    with pytest.raises(ValueError, match="local-only"):
        Settings.from_env()


def test_local_http_is_allowed(monkeypatch):
    monkeypatch.setenv("RESMED_MCP_TRANSPORT", "streamable-http")
    monkeypatch.setenv("RESMED_MCP_HOST", "127.0.0.1")
    assert Settings.from_env().host == "127.0.0.1"
