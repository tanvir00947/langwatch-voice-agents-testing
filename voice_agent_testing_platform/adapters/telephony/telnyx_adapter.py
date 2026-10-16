"""Telnyx Media Streaming Telephony Adapter for Voice Agent & IVR Testing.

Supports:
- Bidirectional G.711 PCMU (mu-law) 8kHz streaming over Telnyx Media Streaming WebSocket.
- Telnyx events: 'start', 'media', 'dtmf', 'clear', 'stop'.
- Real-time barge-in buffer flush and DTMF testing.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from typing import Any, Dict, Optional

import websockets
from websockets.client import WebSocketClientProtocol

from voice_agent_testing_platform.adapters.telephony.base_telephony import BaseTelephonyAdapter
from voice_agent_testing_platform.core.models import AudioChunk

logger = logging.getLogger("platform.adapter.telnyx")


class TelnyxMediaStreamAdapter(BaseTelephonyAdapter):
    """Adapter connecting to Telnyx TeXML / Call Control Media Streaming WebSocket."""

    def __init__(
        self,
        url: str = "ws://127.0.0.1:8080/telnyx-stream",
        api_key: Optional[str] = None,
        connection_id: Optional[str] = None,
        telnyx_phone: Optional[str] = None,
        to_phone: Optional[str] = None,
        max_duration_seconds: int = 60,
        dry_run: bool = True,
        config: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            name="TelnyxMediaStreamAdapter",
            max_duration_seconds=max_duration_seconds,
            dry_run=dry_run,
            config=config,
        )
        self.url = url
        self.api_key = api_key
        self.connection_id = connection_id
        self.telnyx_phone = telnyx_phone
        self.to_phone = to_phone
        self._ws: Optional[WebSocketClientProtocol] = None
        self.last_latency_ms: Optional[float] = None

    async def connect(self) -> None:
        """Connect to Telnyx Media Stream WebSocket endpoint."""
        logger.info("[Telnyx Adapter] Connecting to Media Stream on %s ...", self.url)
        self._ws = await websockets.connect(
            self.url,
            max_size=16 * 1024 * 1024,
            ping_interval=None,
        )
        self.is_connected = True

        self.stream_sid = "TELNYX_STREAM_" + str(int(time.time()))
        self.call_sid = "TELNYX_CALL_" + str(int(time.time()))

        # Handshake frame for Telnyx stream
        start_event = {
            "event": "start",
            "stream_id": self.stream_sid,
            "call_control_id": self.call_sid,
            "media_format": {
                "encoding": "audio/x-mulaw",
                "sample_rate": 8000,
                "channels": 1,
            },
        }
        await self._ws.send(json.dumps(start_event))
        logger.info("[Telnyx Adapter] Handshake completed with stream_id=%s", self.stream_sid)

    async def send_audio(self, chunk: AudioChunk) -> None:
        """Convert caller audio to G.711 PCMU and stream to Telnyx."""
        if not self._ws:
            raise RuntimeError("Telnyx adapter is not connected.")

        mulaw_data = self.prepare_audio_for_telephony(chunk)
        frame_size = 160  # 20ms @ 8000Hz
        for i in range(0, len(mulaw_data), frame_size):
            frame = mulaw_data[i : i + frame_size]
            b64_payload = base64.b64encode(frame).decode("utf-8")
            msg = {
                "event": "media",
                "stream_id": self.stream_sid,
                "media": {
                    "payload": b64_payload,
                },
            }
            await self._ws.send(json.dumps(msg))
            await asyncio.sleep(0.005)

    async def receive_response(self, timeout: float = 30.0) -> AudioChunk:
        """Receive agent/IVR audio streamed back over the Telnyx stream."""
        if not self._ws:
            raise RuntimeError("Telnyx adapter is not connected.")

        start_time = time.monotonic()
        first_byte_time: Optional[float] = None
        accumulated_mulaw = bytearray()
        received_transcript = ""

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
                        data = json.loads(raw_msg)
                        event = data.get("event")

                        if event == "media":
                            media_data = data.get("media", {})
                            payload = media_data.get("payload")
                            if payload:
                                raw_chunk = base64.b64decode(payload)
                                accumulated_mulaw.extend(raw_chunk)

                        elif event == "clear":
                            accumulated_mulaw.clear()
                            break

                        elif event == "stop":
                            break

                        if "transcript" in data:
                            received_transcript += data["transcript"]

                    except json.JSONDecodeError:
                        pass

                if accumulated_mulaw and (time.monotonic() - first_byte_time > 1.0):
                    try:
                        peek_msg = await asyncio.wait_for(self._ws.recv(), timeout=0.3)
                        if isinstance(peek_msg, str):
                            d = json.loads(peek_msg)
                            if d.get("event") == "media":
                                p = d.get("media", {}).get("payload")
                                if p:
                                    accumulated_mulaw.extend(base64.b64decode(p))
                    except asyncio.TimeoutError:
                        break

        except Exception as exc:
            logger.error("Error receiving Telnyx media stream: %s", exc)

        result_chunk = self.prepare_audio_from_telephony(bytes(accumulated_mulaw))
        if received_transcript:
            result_chunk.transcript = received_transcript
        return result_chunk

    async def interrupt(self) -> None:
        """Send Telnyx 'clear' event to flush agent playback buffer."""
        if not self._ws:
            return
        logger.info("[Telnyx Adapter] ⚡ Sending Telnyx 'clear' event.")
        msg = {"event": "clear", "stream_id": self.stream_sid}
        await self._ws.send(json.dumps(msg))

    async def send_dtmf(self, digits: str) -> None:
        """Send DTMF keypress event to Telnyx."""
        if not self._ws:
            return
        for digit in digits:
            logger.info("[Telnyx Adapter] 📞 Sending Telnyx DTMF digit '%s'", digit)
            msg = {"event": "dtmf", "stream_id": self.stream_sid, "dtmf": {"digit": digit}}
            await self._ws.send(json.dumps(msg))
            await asyncio.sleep(0.1)

    async def hangup(self) -> None:
        """Send Telnyx 'stop' event and disconnect."""
        if self._ws:
            try:
                stop_msg = {"event": "stop", "stream_id": self.stream_sid}
                await self._ws.send(json.dumps(stop_msg))
            except Exception:
                pass
        await self.disconnect()

    async def disconnect(self) -> None:
        """Close WebSocket session."""
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
        self.is_connected = False
        logger.info("[Telnyx Adapter] Disconnected.")

