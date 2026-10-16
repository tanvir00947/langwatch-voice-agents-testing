"""Audio Bridge Abstraction Layer.

Decouples the Twilio Media Stream WebSocket from the audio consumer/producer.
This modular architecture allows seamlessly swapping between:
1. LaptopAudioBridge: Laptop mic and speakers (initial implementation).
2. LangWatchScenarioBridge: LangWatch Scenario voice model caller/judge (future integration).
3. MockAudioBridge: Automated testing and dry-run simulations.
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Optional

from twilio_agent.phone_audio_bridge.audio_io import LaptopAudioEngine

logger = logging.getLogger("phone_audio_bridge.bridge")


class AudioBridge(ABC):
    """Abstract Base Class for two-way audio streaming with Twilio."""

    @abstractmethod
    async def start(self) -> None:
        """Initialize and start audio resources."""
        pass

    @abstractmethod
    async def on_audio_from_phone(self, pcm_chunk: bytes) -> None:
        """Handle incoming audio chunk received from the phone (8kHz linear PCM16)."""
        pass

    @abstractmethod
    async def get_audio_to_phone(self) -> Optional[bytes]:
        """Fetch next audio chunk to stream to the phone (8kHz linear PCM16)."""
        pass

    @abstractmethod
    async def stop(self) -> None:
        """Clean up audio resources."""
        pass


class LaptopAudioBridge(AudioBridge):
    """Bridges phone audio directly to laptop microphone and speakers."""

    def __init__(self, sample_rate: int = 8000, chunk_size: int = 160):
        self.engine = LaptopAudioEngine(sample_rate=sample_rate, chunk_size=chunk_size)
        self._is_active = False

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        self.engine.start(loop=loop)
        self._is_active = True
        logger.info("LaptopAudioBridge active: Laptop mic and speakers connected to phone call.")

    async def on_audio_from_phone(self, pcm_chunk: bytes) -> None:
        """Play incoming caller voice on laptop speakers."""
        if self._is_active and pcm_chunk:
            self.engine.play_speaker_chunk(pcm_chunk)

    async def get_audio_to_phone(self) -> Optional[bytes]:
        """Stream laptop microphone input back to the caller's phone."""
        if not self._is_active:
            return None
        try:
            return await asyncio.wait_for(self.engine.get_mic_chunk(), timeout=0.1)
        except asyncio.TimeoutError:
            return None

    async def stop(self) -> None:
        self._is_active = False
        self.engine.stop()
        logger.info("LaptopAudioBridge stopped.")


class MockAudioBridge(AudioBridge):
    """In-memory mock bridge for dry-run simulations and automated test suites.

    Guarantees no hardware access and no external phone calls are made.
    """

    def __init__(self):
        self.received_chunks: list[bytes] = []
        self._outgoing_queue: asyncio.Queue[bytes] = asyncio.Queue()
        self.active = False

    async def start(self) -> None:
        self.active = True

    async def on_audio_from_phone(self, pcm_chunk: bytes) -> None:
        if self.active and pcm_chunk:
            self.received_chunks.append(pcm_chunk)

    async def get_audio_to_phone(self) -> Optional[bytes]:
        if not self.active:
            return None
        try:
            return self._outgoing_queue.get_nowait()
        except asyncio.QueueEmpty:
            return None

    def inject_mock_audio(self, pcm_chunk: bytes) -> None:
        """Queue mock audio chunk to be sent to the phone/client."""
        self._outgoing_queue.put_nowait(pcm_chunk)

    async def stop(self) -> None:
        self.active = False

