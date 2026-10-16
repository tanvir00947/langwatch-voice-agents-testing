"""Twilio Call Manager with Strict Safety Guardrails and Trial Protection.

Safeguards:
1. Mandatory interactive user confirmation before placing any real phone call.
2. Carrier-enforced 'time_limit' parameter in Twilio calls.create (automatic carrier hangup).
3. Local async watchdog timer for redundancy.
4. Instant early hangup trigger (via 'q', Ctrl+C, or /hangup endpoint).
5. Dry-run mode for testing with zero Twilio credits used.
6. Call duration metering and usage reporting.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional
from twilio.rest import Client

from twilio_agent.phone_audio_bridge.config import BridgeConfig, is_indian_number

logger = logging.getLogger("phone_audio_bridge.twilio")


class TwilioCallManager:
    """Manages Twilio outbound calls, life-cycle tracking, and emergency hangup."""

    def __init__(self, config: BridgeConfig):
        self.config = config
        self._client: Optional[Client] = None
        self.active_call_sid: Optional[str] = None
        self.call_start_time: Optional[float] = None
        self.call_end_time: Optional[float] = None
        self._watchdog_task: Optional[asyncio.Task] = None
        self._hangup_event = asyncio.Event()

    @property
    def client(self) -> Client:
        if self._client is None and not self.config.dry_run:
            self._client = Client(self.config.account_sid, self.config.auth_token)
        return self._client

    def prompt_confirmation(self) -> bool:
        """Prompt user for explicit terminal confirmation before any real call.

        Requires typing 'YES' exactly. Prevents accidental dialing.
        """
        if not self.config.require_confirmation:
            return True

        is_in = is_indian_number(self.config.to_phone_number)
        print("\n" + "=" * 70)
        print("          ⚠️  CONFIRMATION REQUIRED: TWILIO OUTBOUND CALL")
        print("=" * 70)
        print(f"  Destination Phone:  {self.config.to_phone_number}" + (" (India +91)" if is_in else ""))
        print(f"  Twilio Caller ID:   {self.config.twilio_phone_number}")
        print(f"  Max Duration Limit: {self.config.max_duration_seconds} seconds (Hard telecom carrier auto-hangup)")
        print(f"  Mode:               {'DRY RUN (Simulated)' if self.config.dry_run else '🔴 REAL TELEPHONE CALL'}")
        print("=" * 70)

        if self.config.dry_run:
            print("  [DRY RUN]: No actual phone call will be placed. Zero minutes used.")
            confirm = input("  Proceed with simulation? (Type 'YES' to proceed): ").strip()
            return confirm == "YES"

        print("  NOTICE: This will consume call minutes from your Twilio trial account.")
        print("  You can hang up early at ANY time by pressing 'q' or 'Ctrl+C' in this terminal.")
        print("-" * 70)
        confirm = input("  Are you SURE you want to place this call? (Type 'YES' to proceed): ").strip()

        if confirm == "YES":
            return True
        else:
            print("\n❌ Call placement aborted. No phone call was made. Zero credits used.\n")
            return False

    async def initiate_call(self, stream_url: str) -> Optional[str]:
        """Place outbound call to destination phone with stream TwiML and time limit."""
        if not self.prompt_confirmation():
            return None

        # Build inline TwiML with Media Stream WebSocket URL
        twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect>
        <Stream url="{stream_url}">
            <Parameter name="app" value="phone_audio_bridge" />
        </Stream>
    </Connect>
</Response>"""

        if self.config.dry_run:
            logger.info("⚡ [DRY RUN] Simulating Twilio call initiation to %s", self.config.to_phone_number)
            self.active_call_sid = "CA_MOCK_DRY_RUN_CALL_SID_12345678"
            self.call_start_time = time.time()
            self._watchdog_task = asyncio.create_task(
                self._watchdog_timer(self.active_call_sid, self.config.max_duration_seconds)
            )
            return self.active_call_sid

        try:
            logger.info(
                "Dialing %s with carrier time_limit=%ds...",
                self.config.to_phone_number,
                self.config.max_duration_seconds,
            )

            # Place outbound call via Twilio REST API
            call = self.client.calls.create(
                to=self.config.to_phone_number,
                from_=self.config.twilio_phone_number,
                twiml=twiml,
                time_limit=self.config.max_duration_seconds,  # Carrier-enforced hard cutoff
            )

            self.active_call_sid = call.sid
            self.call_start_time = time.time()
            logger.info("Call successfully placed! Call SID: %s (Status: %s)", call.sid, call.status)

            # Launch async watchdog timer for safety
            self._watchdog_task = asyncio.create_task(
                self._watchdog_timer(call.sid, self.config.max_duration_seconds)
            )

            return call.sid
        except Exception as e:
            logger.error("Failed to initiate Twilio call: %s", e)
            raise

    async def _watchdog_timer(self, call_sid: str, timeout_seconds: int) -> None:
        """Watchdog: ensures call is terminated if it reaches max_duration_seconds."""
        try:
            await asyncio.sleep(timeout_seconds)
            logger.warning(
                "⏰ Max duration limit reached (%ds). Watchdog triggering automatic hangup...",
                timeout_seconds,
            )
            await self.hangup_call()
        except asyncio.CancelledError:
            pass

    async def hangup_call(self) -> None:
        """Immediately hang up active call via Twilio REST API."""
        if not self.active_call_sid:
            return

        call_sid = self.active_call_sid
        self.active_call_sid = None
        self.call_end_time = time.time()

        if self._watchdog_task and not self._watchdog_task.done():
            self._watchdog_task.cancel()

        self._hangup_event.set()

        if self.config.dry_run or call_sid.startswith("CA_MOCK"):
            logger.info("⚡ [DRY RUN] Mock call %s terminated.", call_sid)
            self._report_duration()
            return

        try:
            logger.info("Terminating Twilio call %s via REST API...", call_sid)
            self.client.calls(call_sid).update(status="completed")
            logger.info("Call %s hung up successfully.", call_sid)
        except Exception as e:
            logger.warning("Twilio hangup returned: %s (Call may have already ended)", e)
        finally:
            self._report_duration()

    def _report_duration(self) -> None:
        """Log duration of call and estimated usage."""
        if self.call_start_time:
            end = self.call_end_time or time.time()
            elapsed_sec = int(round(end - self.call_start_time))
            mins = (elapsed_sec + 59) // 60  # Telecom billing rounds up to full minute
            print("\n" + "=" * 55)
            print("                 CALL SESSION SUMMARY")
            print("=" * 55)
            print(f"  Duration:           {elapsed_sec} seconds")
            print(f"  Twilio Billing:     ~{mins} minute(s)")
            print(f"  Status:             Completed & Closed")
            print("=" * 55 + "\n")
