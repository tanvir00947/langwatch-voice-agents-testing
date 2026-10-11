"""WebSocket audio protocol connecting Scenario to our voice agent server.

Adheres to scenario.voice.adapters.websocket.WebSocketProtocol.
Wire format is JSON:
- Client to Server: {"type": "audio", "data": "<base64 PCM16>"}
- Server to Client: {"type": "audio", "data": "<base64 PCM16>", "transcript": "..."}
"""

from __future__ import annotations

import base64
import json
import logging
from typing import Any, Optional

from scenario.voice.adapters.websocket import WebSocketProtocol
from scenario.voice.audio_chunk import AudioChunk

logger = logging.getLogger("ws_voice_agent.protocol")


class JsonAudioWebSocketProtocol(WebSocketProtocol):
    """Protocol for exchanging base64-encoded PCM16 audio in JSON frames."""

    def encode_audio(self, audio: bytes) -> str:
        """Convert Scenario's PCM16 24kHz audio into a JSON wire message."""
        b64_audio = base64.b64encode(audio).decode("utf-8")
        return json.dumps({
            "type": "audio",
            "data": b64_audio,
        })

    def decode_response(self, message: Any) -> Optional[AudioChunk]:
        """Parse incoming server message into an AudioChunk."""
        if not isinstance(message, str):
            logger.warning("Received unexpected non-string message: %r", message)
            return None

        try:
            payload = json.loads(message)
        except json.JSONDecodeError:
            logger.warning("Received invalid JSON: %r", message)
            return None

        msg_type = payload.get("type")
        if msg_type == "audio":
            b64_data = payload.get("data", "")
            raw_pcm = base64.b64decode(b64_data)
            return AudioChunk(data=raw_pcm)

        # Ignore ping / metadata / non-audio messages
        return None
