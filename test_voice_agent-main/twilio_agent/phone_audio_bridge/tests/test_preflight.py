"""Tests for preflight validation, E.164 formats, and country rules."""

import pytest

from twilio_agent.phone_audio_bridge.config import (
    BridgeConfig,
    is_indian_number,
    is_valid_e164,
)


def test_e164_validation():
    """Verify standard E.164 phone number pattern matching."""
    # Valid
    assert is_valid_e164("+919876543210") is True
    assert is_valid_e164("+12025550143") is True
    assert is_valid_e164("+447911123456") is True

    # Invalid
    assert is_valid_e164("9876543210") is False  # missing +
    assert is_valid_e164("+01234567") is False   # leading 0 after +
    assert is_valid_e164("invalid") is False
    assert is_valid_e164("") is False


def test_indian_number_detection():
    """Verify detection of Indian country code (+91)."""
    assert is_indian_number("+919876543210") is True
    assert is_indian_number("+91 98765 43210") is True
    assert is_indian_number("+91-9876543210") is True
    assert is_indian_number("+12025550143") is False
    assert is_indian_number("+44123456789") is False
    assert is_indian_number("") is False


def test_config_validation_for_call():
    """Verify detection of missing configuration fields."""
    bad_cfg = BridgeConfig(
        account_sid="",
        auth_token="",
        twilio_phone_number="bad",
        to_phone_number="123",
        public_url="",
        ngrok_authtoken=None,
        host="0.0.0.0",
        port=8000,
        max_duration_seconds=60,
        require_confirmation=True,
        dry_run=False,
    )
    errors = bad_cfg.validate_for_call()
    assert len(errors) >= 4

    good_cfg = BridgeConfig(
        account_sid="AC_MOCK_ACCOUNT_SID_FOR_PREFLIGHT",
        auth_token="valid_token",
        twilio_phone_number="+12025550100",
        to_phone_number="+919876543210",
        public_url="https://myapp.ngrok.app",
        ngrok_authtoken=None,
        host="0.0.0.0",
        port=8000,
        max_duration_seconds=60,
        require_confirmation=True,
        dry_run=False,
    )
    assert len(good_cfg.validate_for_call()) == 0

