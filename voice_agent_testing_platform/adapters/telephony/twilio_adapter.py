"""Twilio Media Streams Telephony Adapter for Voice Agent & IVR Testing.

Supports:
- Bidirectional G.711 mu-law 8kHz audio streaming over Twilio Media Stream WebSocket.
- Twilio event protocols: 'connected', 'start', 'media', 'dtmf', 'clear', 'stop'.
- Real-time barge-in buffer flush via Twilio 'clear' event.
- Safe dry-run and live calling modes with automated carrier-level time limits.
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

logger = logging.getLogger("platform.adapter.twilio")


class TwilioMediaStreamAdapter(BaseTelephonyAdapter):
    """Adapter connecting to Twilio Media Stream WebSocket endpoints."""

    def __init__(
        self,
        url: str = "ws://127.0.0.1:8080/media-stream",
        account_sid: Optional[str] = None,
        auth_token: Optional[str] = None,
        twilio_phone: Optional[str] = None,
        to_phone: Optional[str] = None,
        max_duration_seconds: int = 60,
        dry_run: bool = True,
        config: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            name="TwilioMediaStreamAdapter",
            max_duration_seconds=max_duration_seconds,
            dry_run=dry_run,
            config=config,
        )
        self.url = url
        self.account_sid = account_sid
        self.auth_token = auth_token
        self.twilio_phone = twilio_phone
        self.to_phone = to_phone
        self._ws: Optional[WebSocketClientProtocol] = None
        self.last_latency_ms: Optional[float] = None

    async def connect(self) -> None:
        """Connect to Twilio Media Stream WebSocket endpoint."""
        logger.info("[Twilio Adapter] Connecting to Media Stream on %s ...", self.url)
        self._ws = await websockets.connect(
            self.url,
            max_size=16 * 1024 * 1024,
            ping_interval=None,
        )
        self.is_connected = True

        # Simulate or send initial Twilio handshake if we are simulating the Twilio side
        self.stream_sid = "MZ_SIMULATED_TWILIO_STREAM_" + str(int(time.time()))
        self.call_sid = "CA_SIMULATED_TWILIO_CALL_" + str(int(time.time()))
        start_event = {
            "event": "start",
            "sequenceNumber": "1",
            "start": {
                "streamSid": self.stream_sid,
                "accountSid": self.account_sid or "AC_TEST",
                "callSid": self.call_sid,
                "tracks": ["inbound"],
                "mediaFormat": {
                    "encoding": "audio/x-mulaw",
                    "sampleRate": 8000,
                    "channels": 1,
                },
            },
            "streamSid": self.stream_sid,
        }
        await self._ws.send(json.dumps(start_event))
        logger.info("[Twilio Adapter] Handshake completed with streamSid=%s", self.stream_sid)

    async def send_audio(self, chunk: AudioChunk) -> None:
        """Convert caller audio to G.711 mu-law chunks and stream to Twilio Media Stream."""
        if not self._ws:
            raise RuntimeError("Twilio adapter is not connected.")

        # Convert 24kHz PCM to 8kHz mu-law
        mulaw_data = self.prepare_audio_for_telephony(chunk)

        # Stream in typical 20ms frames (160 bytes @ 8kHz mu-law)
        frame_size = 160
        seq = 1
        for i in range(0, len(mulaw_data), frame_size):
            frame = mulaw_data[i : i + frame_size]
            b64_payload = base64.b64encode(frame).decode("utf-8")
            msg = {
                "event": "media",
                "sequenceNumber": str(seq),
                "media": {
                    "track": "inbound",
                    "chunk": str(seq),
                    "timestamp": str(int(time.time() * 1000)),
                    "payload": b64_payload,
                },
                "streamSid": self.stream_sid,
            }
            await self._ws.send(json.dumps(msg))
            seq += 1
            await asyncio.sleep(0.005)  # Fast stream or real-time pacing

    async def receive_response(self, timeout: float = 30.0) -> AudioChunk:
        """Receive agent/IVR audio streamed back over the Twilio Media Stream."""
        if not self._ws:
            raise RuntimeError("Twilio adapter is not connected.")

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

                        elif event == "mark":
                            # End of playback marker
                            break

                        elif event == "clear":
                            # Barge-in buffer clear event
                            accumulated_mulaw.clear()
                            break

                        elif event == "stop":
                            break

                        # Also accept custom agent transcript fields if the agent returns them
                        if "transcript" in data:
                            received_transcript += data["transcript"]

                    except json.JSONDecodeError:
                        pass

                # If silence/pause observed after receiving some audio
                if accumulated_mulaw and (time.monotonic() - first_byte_time > 1.0):
                    try:
                        # Check if any more audio comes in the next 300ms
                        peek_msg = await asyncio.wait_for(self._ws.recv(), timeout=0.3)
                        # Process peek message
                        if isinstance(peek_msg, str):
                            d = json.loads(peek_msg)
                            if d.get("event") == "media":
                                p = d.get("media", {}).get("payload")
                                if p:
                                    accumulated_mulaw.extend(base64.b64decode(p))
                    except asyncio.TimeoutError:
                        break

        except Exception as exc:
            logger.error("Error receiving Twilio media stream: %s", exc)

        # Convert telecom mu-law back to 24kHz PCM for test evaluation
        result_chunk = self.prepare_audio_from_telephony(bytes(accumulated_mulaw))
        if received_transcript:
            result_chunk.transcript = received_transcript
        return result_chunk

    async def interrupt(self) -> None:
        """Send Twilio 'clear' event to immediately flush queued agent audio."""
        if not self._ws or not self.stream_sid:
            return
        logger.info("[Twilio Adapter] ⚡ Sending Twilio 'clear' event for streamSid=%s", self.stream_sid)
        msg = {
            "event": "clear",
            "streamSid": self.stream_sid,
        }
        await self._ws.send(json.dumps(msg))

    async def send_dtmf(self, digits: str) -> None:
        """Send DTMF keypress event over Twilio Media Stream."""
        if not self._ws or not self.stream_sid:
            return
        for digit in digits:
            logger.info("[Twilio Adapter] 📞 Sending Twilio DTMF digit '%s'", digit)
            msg = {
                "event": "dtmf",
                "streamSid": self.stream_sid,
                "dtmf": {
                    "track": "inbound",
                    "digit": digit,
                },
            }
            await self._ws.send(json.dumps(msg))
            await asyncio.sleep(0.1)

    async def hangup(self) -> None:
        """Send Twilio 'stop' event and disconnect."""
        if self._ws and self.stream_sid:
            try:
                stop_msg = {
                    "event": "stop",
                    "streamSid": self.stream_sid,
                    "stop": {"callSid": self.call_sid},
                }
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
        logger.info("[Twilio Adapter] Disconnected.")

