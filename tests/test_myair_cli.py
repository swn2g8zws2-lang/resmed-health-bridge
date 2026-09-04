"""Synthetic tests for secure local-terminal myAir MFA input."""

import getpass

import pytest

from resmed_health_bridge.myair_cli import _read_mfa_code


def test_mfa_code_uses_no_echo_terminal_prompt(monkeypatch):
    monkeypatch.delenv("MYAIR_MFA_CODE", raising=False)
    monkeypatch.setattr("resmed_health_bridge.myair_cli.sys.stdin.isatty", lambda: True)
    prompts = []

    def fake_getpass(prompt):
        prompts.append(prompt)
        return "synthetic-code"

    monkeypatch.setattr("resmed_health_bridge.myair_cli.getpass.getpass", fake_getpass)
    assert _read_mfa_code() == "synthetic-code"
    assert prompts == ["myAir email verification code: "]


def test_mfa_code_environment_support_avoids_prompt(monkeypatch):
    monkeypatch.setenv("MYAIR_MFA_CODE", "synthetic-environment-code")
    monkeypatch.setattr(
        "resmed_health_bridge.myair_cli.getpass.getpass",
        lambda _: (_ for _ in ()).throw(AssertionError("must not prompt")),
    )
    assert _read_mfa_code() == "synthetic-environment-code"


def test_mfa_code_fails_closed_without_secure_terminal(monkeypatch):
    monkeypatch.delenv("MYAIR_MFA_CODE", raising=False)
    monkeypatch.setattr("resmed_health_bridge.myair_cli.sys.stdin.isatty", lambda: False)
    monkeypatch.setattr(
        "resmed_health_bridge.myair_cli.getpass.getpass",
        lambda _: (_ for _ in ()).throw(AssertionError("must not use echoed input")),
    )
    assert _read_mfa_code() == ""


def test_mfa_code_never_uses_getpass_echo_fallback(monkeypatch):
    monkeypatch.delenv("MYAIR_MFA_CODE", raising=False)
    monkeypatch.setattr("resmed_health_bridge.myair_cli.sys.stdin.isatty", lambda: True)

    def insecure_fallback(_prompt):
        raise getpass.GetPassWarning("synthetic terminal failure")

    monkeypatch.setattr("resmed_health_bridge.myair_cli.getpass.getpass", insecure_fallback)
    with pytest.raises(getpass.GetPassWarning):
        _read_mfa_code()
