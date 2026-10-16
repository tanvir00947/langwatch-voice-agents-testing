"""Generic WebSocket Agent Adapter for Voice & IVA Testing.

Supports:
- JSON Base64 audio streaming (standard for Gemini Live and conversational voice agents).
- Binary PCM streaming.
- Real-time barge-in interruption signal dispatch.
- Millisecond-accurate TTFB and turn response latency measurement.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from typing import Any, Callable, Dict, Optional

import websockets
from websockets.client import WebSocketClientProtocol

from voice_agent_testing_platform.adapters.base import BaseAgentAdapter
from voice_agent_testing_platform.core.models import AudioChunk

logger = logging.getLogger("platform.adapter.websocket")


class WebSocketAgentAdapter(BaseAgentAdapter):
    """Adapter connecting to WebSocket voice agents (e.g., Gemini Live WS server)."""

    def __init__(
        self,
        url: str = "ws://127.0.0.1:8765",
        name: str = "WebSocketAgentAdapter",
        protocol_type: str = "json_base64",
        max_frame_size: int = 32 * 1024 * 1024,  # 32 MB frame limit
        config: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(name=name, config=config)
        self.url = url
        self.protocol_type = protocol_type
        self.max_frame_size = max_frame_size
        self._ws: Optional[WebSocketClientProtocol] = None
        self.last_latency_ms: Optional[float] = None

    async def connect(self) -> None:
        """Connect to target WebSocket voice agent."""
        logger.info("[WebSocket Adapter] Connecting to %s ...", self.url)
        self._ws = await websockets.connect(
            self.url,
            max_size=self.max_frame_size,
            ping_interval=None,
        )
        self.is_connected = True
        logger.info("[WebSocket Adapter] Connected successfully to %s", self.url)

    async def send_audio(self, chunk: AudioChunk) -> None:
        """Send audio to the WebSocket agent."""
        if not self._ws:
            raise RuntimeError("WebSocket adapter is not connected.")

        if self.protocol_type == "json_base64":
            b64_str = base64.b64encode(chunk.data).decode("utf-8")
            payload = json.dumps({"type": "audio", "data": b64_str})
            await self._ws.send(payload)
        elif self.protocol_type == "raw_binary":
            await self._ws.send(chunk.data)
        else:
            raise ValueError(f"Unknown protocol type: {self.protocol_type}")

    async def receive_response(self, timeout: float = 60.0) -> AudioChunk:
        """Collect the agent's complete audio response and transcript for the current turn."""
        if not self._ws:
            raise RuntimeError("WebSocket adapter is not connected.")

        start_time = time.monotonic()
        first_byte_time: Optional[float] = None
        accumulated_audio = bytearray()
        accumulated_transcript = ""

        try:
            while True:
                remaining_time = timeout - (time.monotonic() - start_time)
                if remaining_time <= 0:
                    break

                try:
                    raw_msg = await asyncio.wait_for(self._ws.recv(), timeout=remaining_time)
                except asyncio.TimeoutError:
                    break

                if first_byte_time is None:
                    first_byte_time = time.monotonic()
                    self.last_latency_ms = (first_byte_time - start_time) * 1000.0

                if isinstance(raw_msg, str):
                    try:
                        payload = json.loads(raw_msg)
                        msg_type = payload.get("type")
                        t_text = payload.get("transcript")
                        if t_text:
                            accumulated_transcript += t_text

                        if msg_type == "audio":
                            b64_data = payload.get("data", "")
                            if b64_data:
                                chunk_bytes = base64.b64decode(b64_data)
                                accumulated_audio.extend(chunk_bytes)
                            else:
                                # Empty data chunk signals end of speech turn in some agents
                                if accumulated_audio:
                                    break

                        elif msg_type == "turn_complete":
                            # End of agent turn marker
                            break

                        elif msg_type == "interrupted":
                            # Agent acknowledged interruption
                            break

                    except json.JSONDecodeError:
                        logger.warning("Received unparseable JSON frame: %r", raw_msg[:100])

                elif isinstance(raw_msg, bytes):
                    accumulated_audio.extend(raw_msg)
                    # If using raw binary, use short debounce
                    try:
                        while True:
                            next_chunk = await asyncio.wait_for(self._ws.recv(), timeout=0.8)
                            if isinstance(next_chunk, bytes):
                                accumulated_audio.extend(next_chunk)
                    except asyncio.TimeoutError:
                        break
                    break

        except Exception as exc:
            logger.error("Error while receiving response: %s", exc)

        audio_bytes = bytes(accumulated_audio)
        duration_s = (len(audio_bytes) / 2.0) / 24000.0 if audio_bytes else 0.0

        return AudioChunk(
            data=audio_bytes,
            sample_rate=24000,
            format="pcm16",
            transcript=accumulated_transcript.strip() or None,
            duration_seconds=duration_s,
        )

    async def interrupt(self) -> None:
        """Send native cancellation / barge-in signal to the agent."""
        if not self._ws:
            return
        logger.info("[WebSocket Adapter] ⚡ Sending interruption signal...")
        try:
            await self._ws.send(json.dumps({"type": "interrupt"}))
        except Exception as e:
            logger.warning("Failed to send interrupt frame: %s", e)

    async def send_dtmf(self, digits: str) -> None:
        """Send DTMF digit frame to the agent if supported."""
        if not self._ws:
            return
        logger.info("[WebSocket Adapter] 📞 Sending DTMF digits: %s", digits)
        try:
            await self._ws.send(json.dumps({"type": "dtmf", "digits": digits}))
        except Exception as e:
            logger.warning("Failed to send DTMF frame: %s", e)

    async def disconnect(self) -> None:
        """Teardown WebSocket connection."""
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
        self.is_connected = False
        logger.info("[WebSocket Adapter] Disconnected.")

