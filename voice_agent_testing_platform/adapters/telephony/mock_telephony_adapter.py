"""Mock Telephony Adapter for Zero-Cost Local IVR and Phone Voice Testing.

Simulates:
- Telecom audio conditions (8kHz G.711 mu-law compression, 300Hz-3.4kHz bandpass filter).
- Automated IVR menu flows with DTMF digit detection.
- Barge-in interruptions.
- Zero telecom charges or external network dependencies.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable, Dict, List, Optional

from voice_agent_testing_platform.adapters.telephony.base_telephony import BaseTelephonyAdapter
from voice_agent_testing_platform.core.audio_utils import (
    apply_telephony_filter,
    generate_dtmf_tone,
)
from voice_agent_testing_platform.core.models import AudioChunk
from voice_agent_testing_platform.core.speech_engine import synthesize_speech_pcm

logger = logging.getLogger("platform.adapter.mock_telephony")


class MockTelephonyAdapter(BaseTelephonyAdapter):
    """Simulates a telephone line and automated IVR system locally for testing."""

    def __init__(
        self,
        name: str = "MockTelephonyAdapter",
        ivr_responses: Optional[Dict[str, str]] = None,
        config: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(name=name, max_duration_seconds=60, dry_run=True, config=config)
        self.ivr_responses = ivr_responses or {
            "initial": "Thank you for calling Acme Customer Care. Press 1 for Support, or press 2 for Sales.",
            "dtmf_1": "You have reached Technical Support. How can we help you today?",
            "dtmf_2": "Connecting you to Sales. Please hold while we transfer your call.",
            "support_answered": "Your account is active and in good standing. We have resolved your inquiry. Can I help you with anything else today?",
            "default": "I didn't catch that. Please state your query or press 1.",
        }
        self.current_state: str = "initial"
        self.received_dtmf_history: List[str] = []
        self.interrupted: bool = False
        self.last_latency_ms: Optional[float] = 120.0  # Simulated telephone network latency

    async def connect(self) -> None:
        """Initialize mock telephone line connection."""
        self.call_sid = "MOCK_TEL_CALL_1001"
        self.stream_sid = "MOCK_TEL_STREAM_2002"
        self.is_connected = True
        logger.info("[Mock Telephony] Connected to simulated telecom switch.")

    async def send_audio(self, chunk: AudioChunk) -> None:
        """Simulate sending caller audio through telecom codecs and filters."""
        if not self.is_connected:
            raise RuntimeError("Mock Telephony adapter is not connected.")

        # Simulate telecom transmission: PCM24k -> mu-law 8k -> PCM24k
        mulaw = self.prepare_audio_for_telephony(chunk)
        restored = self.prepare_audio_from_telephony(mulaw)
        # Apply telecom bandpass filter
        filtered_audio = apply_telephony_filter(restored.data, sample_rate=self.caller_rate)

        # Transition state if query received after DTMF 1
        if self.current_state == "dtmf_1":
            self.current_state = "support_answered"

        logger.info("[Mock Telephony] Audio received via telecom link (%d bytes)", len(filtered_audio))
        await asyncio.sleep(0.05)  # Simulate network propagation

    async def receive_response(self, timeout: float = 10.0) -> AudioChunk:
        """Synthesize and return the simulated IVR/Agent spoken response."""
        if not self.is_connected:
            raise RuntimeError("Mock Telephony adapter is not connected.")

        t0 = time.monotonic()
        await asyncio.sleep(0.12)  # Simulate telephone network ping latency
        self.last_latency_ms = (time.monotonic() - t0) * 1000.0

        reply_text = self.ivr_responses.get(self.current_state, self.ivr_responses["default"])
        logger.info("[Mock Telephony] IVR Speech Response: %r", reply_text)

        # Synthesize IVR prompt voice with telephony audio filter
        raw_pcm = await synthesize_speech_pcm(reply_text, accent_or_voice="us_female", sample_rate=self.caller_rate)
        telecom_pcm = apply_telephony_filter(raw_pcm, sample_rate=self.caller_rate)

        duration_s = (len(telecom_pcm) / 2.0) / float(self.caller_rate) if telecom_pcm else 0.0

        return AudioChunk(
            data=telecom_pcm,
            sample_rate=self.caller_rate,
            format="pcm16",
            transcript=reply_text,
            duration_seconds=duration_s,
        )

    async def interrupt(self) -> None:
        """Simulate caller barge-in during IVR speech."""
        logger.info("[Mock Telephony] ⚡ Caller interrupted IVR playback!")
        self.interrupted = True

    async def send_dtmf(self, digits: str) -> None:
        """Simulate caller pressing telephone keypad digits."""
        for digit in digits:
            logger.info("[Mock Telephony] 📞 Keypad DTMF detected: '%s'", digit)
            self.received_dtmf_history.append(digit)
            state_key = f"dtmf_{digit}"
            if state_key in self.ivr_responses:
                self.current_state = state_key

    async def hangup(self) -> None:
        """Simulate call termination."""
        logger.info("[Mock Telephony] Call terminated.")
        await self.disconnect()

    async def disconnect(self) -> None:
        self.is_connected = False
        logger.info("[Mock Telephony] Disconnected.")

