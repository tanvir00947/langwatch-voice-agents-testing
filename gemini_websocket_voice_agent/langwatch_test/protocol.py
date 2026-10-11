"""WebSocket audio protocol connecting Scenario to the Gemini Live voice agent server.

Adheres to scenario.voice.adapters.websocket.WebSocketProtocol.
Wire format is JSON:
- Client to Server: {"type": "audio", "data": "<base64 PCM16>"}
- Server to Client: {"type": "audio", "data": "<base64 PCM16>"}
                    {"type": "turn_complete", "transcript": "..."}
"""

from __future__ import annotations

import base64
import json
import logging
from typing import Any, Optional

from scenario.voice.adapters.websocket import WebSocketProtocol
from scenario.voice.audio_chunk import AudioChunk

logger = logging.getLogger("langwatch_test.protocol")


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
        transcript = payload.get("transcript")

        if msg_type == "audio":
            b64_data = payload.get("data", "")
            if not b64_data:
                # End-of-turn delimiter: carry the turn's final transcript once
                return AudioChunk(data=b"", transcript=transcript)
            raw_pcm = base64.b64decode(b64_data)
            # Intermediate streaming frames: do not duplicate cumulative transcript
            return AudioChunk(data=raw_pcm, transcript=None)

        if msg_type == "turn_complete":
            # Turn completion marker
            return AudioChunk(data=b"", transcript=transcript)

        if msg_type == "interrupted":
            # Barge-in acknowledged
            return AudioChunk(data=b"")

        # Ignore ping / unknown messages
        return None
