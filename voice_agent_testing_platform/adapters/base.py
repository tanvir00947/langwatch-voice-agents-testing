"""Base interface and contract for Voice Agent & Telephony Adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from voice_agent_testing_platform.core.models import AudioChunk


class BaseAgentAdapter(ABC):
    """Abstract Base Class for connecting the test framework to an Agent Under Test."""

    def __init__(self, name: str = "BaseAgentAdapter", config: Optional[Dict[str, Any]] = None):
        self.name = name
        self.config = config or {}
        self.is_connected: bool = False

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to the voice agent server or telephony provider."""
        pass

    @abstractmethod
    async def send_audio(self, chunk: AudioChunk) -> None:
        """Send synthesized caller audio data to the agent under test."""
        pass

    @abstractmethod
    async def receive_response(self, timeout: float = 30.0) -> AudioChunk:
        """Wait for and accumulate the agent's complete audio response and/or transcript."""
        pass

    @abstractmethod
    async def interrupt(self) -> None:
        """Send real-time barge-in / speech cancellation signal to interrupt the agent."""
        pass

    async def send_dtmf(self, digits: str) -> None:
        """Send DTMF keypress digits if supported by the adapter (e.g. for IVR testing)."""
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """Gracefully terminate connection and release resources."""
        pass

