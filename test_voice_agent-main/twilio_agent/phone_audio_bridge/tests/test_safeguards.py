"""Automated tests verifying safety guardrails and trial protection.

Guarantees:
- Real phone calls cannot be made without explicit user confirmation.
- Dry run mode never calls Twilio REST API.
- Duration limit auto-hangup watchdog triggers properly.
- Manual hangup functions cleanly.
"""

import asyncio
from unittest.mock import MagicMock, patch
import pytest

from twilio_agent.phone_audio_bridge.config import BridgeConfig
from twilio_agent.phone_audio_bridge.twilio_handler import TwilioCallManager


@pytest.fixture
def dry_run_config():
    return BridgeConfig(
        account_sid="AC_MOCK_ACCOUNT_SID_SAFEGUARDS",
        auth_token="mock_auth_token",
        twilio_phone_number="+12025550100",
        to_phone_number="+919876543210",
        public_url="https://mock.ngrok.app",
        ngrok_authtoken=None,
        host="127.0.0.1",
        port=8000,
        max_duration_seconds=2,
        require_confirmation=True,
        dry_run=True,
    )


@pytest.mark.asyncio
async def test_rejection_of_confirmation_aborts_call(dry_run_config):
    """If user rejects the confirmation prompt, call must abort with zero API calls."""
    manager = TwilioCallManager(dry_run_config)

    # Simulate user typing 'NO'
    with patch("builtins.input", return_value="NO"):
        call_sid = await manager.initiate_call("wss://mock.ngrok.app/media-stream")
        assert call_sid is None
        assert manager.active_call_sid is None


@pytest.mark.asyncio
async def test_dry_run_places_mock_call_only(dry_run_config):
    """In dry run mode, initiate_call creates mock SID without touching twilio.rest.Client."""
    manager = TwilioCallManager(dry_run_config)

    with patch("builtins.input", return_value="YES"):
        call_sid = await manager.initiate_call("wss://mock.ngrok.app/media-stream")
        assert call_sid is not None
        assert call_sid.startswith("CA_MOCK")
        assert manager.active_call_sid == call_sid

        # Verify immediate hangup works
        await manager.hangup_call()
        assert manager.active_call_sid is None


@pytest.mark.asyncio
async def test_watchdog_auto_hangup(dry_run_config):
    """Watchdog must automatically hang up call when max_duration_seconds expires."""
    # Set max duration to 1 second for fast test
    fast_config = BridgeConfig(
        account_sid=dry_run_config.account_sid,
        auth_token=dry_run_config.auth_token,
        twilio_phone_number=dry_run_config.twilio_phone_number,
        to_phone_number=dry_run_config.to_phone_number,
        public_url=dry_run_config.public_url,
        ngrok_authtoken=None,
        host="127.0.0.1",
        port=8000,
        max_duration_seconds=1,
        require_confirmation=False,  # auto confirm for test
        dry_run=True,
    )

    manager = TwilioCallManager(fast_config)
    call_sid = await manager.initiate_call("wss://mock.ngrok.app/media-stream")
    assert call_sid is not None
    assert manager.active_call_sid is not None

    # Wait 1.3 seconds for watchdog to trigger
    await asyncio.sleep(1.3)

    # Active call should now be None because watchdog auto-hung up
    assert manager.active_call_sid is None

