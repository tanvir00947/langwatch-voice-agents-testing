"""Base Telephony Adapter for IVR and Telephony Voice Agent Testing."""

from __future__ import annotations

from abc import abstractmethod
from typing import Any, Dict, Optional
from voice_agent_testing_platform.adapters.base import BaseAgentAdapter
from voice_agent_testing_platform.core.audio_utils import (
    mulaw_to_pcm16,
    pcm16_to_mulaw,
    resample_pcm,
)
from voice_agent_testing_platform.core.models import AudioChunk


class BaseTelephonyAdapter(BaseAgentAdapter):
    """Abstract base adapter for telephony media stream providers (Twilio, Telnyx, Mock)."""

    def __init__(
        self,
        name: str = "BaseTelephonyAdapter",
        max_duration_seconds: int = 60,
        dry_run: bool = True,
        config: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(name=name, config=config)
        self.max_duration_seconds = max_duration_seconds
        self.dry_run = dry_run
        self.call_sid: Optional[str] = None
        self.stream_sid: Optional[str] = None
        self.telephony_rate: int = 8000
        self.caller_rate: int = 24000

    def prepare_audio_for_telephony(self, caller_pcm_chunk: AudioChunk) -> bytes:
        """Convert caller audio (24kHz PCM16) to telephony standard (8kHz mu-law)."""
        # 1. Resample 24kHz -> 8kHz
        pcm_8k = resample_pcm(caller_pcm_chunk.data, caller_pcm_chunk.sample_rate, self.telephony_rate)
        # 2. Encode to G.711 mu-law
        mulaw_data = pcm16_to_mulaw(pcm_8k)
        return mulaw_data

    def prepare_audio_from_telephony(self, mulaw_data: bytes) -> AudioChunk:
        """Convert incoming telecom audio (8kHz mu-law) to test platform format (24kHz PCM16)."""
        # 1. Decode G.711 mu-law -> 8kHz PCM16
        pcm_8k = mulaw_to_pcm16(mulaw_data)
        # 2. Resample 8kHz -> 24kHz
        pcm_24k = resample_pcm(pcm_8k, self.telephony_rate, self.caller_rate)
        duration_s = (len(pcm_24k) / 2.0) / float(self.caller_rate)
        return AudioChunk(
            data=pcm_24k,
            sample_rate=self.caller_rate,
            format="pcm16",
            duration_seconds=duration_s,
        )

    @abstractmethod
    async def hangup(self) -> None:
        """Terminate active phone call."""
        pass

