"""Large Frame WebSocket Agent Adapter for Scenario evaluation.

Connects Scenario's multi-turn voice evaluation framework to the Gemini Live
WebSocket server. Handles 32 MB frame buffers, transport-native barge-in
interruptions, and real-time turn-by-turn transcript logging.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar, Optional

from scenario.voice.adapters.websocket import WebSocketAgentAdapter
from scenario.voice.capabilities import AdapterCapabilities
from scenario.voice.messages import extract_audio
from protocol import JsonAudioWebSocketProtocol

logger = logging.getLogger("langwatch_test.adapter")


class LargeFrameWebSocketAgentAdapter(WebSocketAgentAdapter):
    """WebSocket adapter configured with 32 MB frame limit, barge-in, and transcript logging."""

    capabilities: ClassVar[AdapterCapabilities] = AdapterCapabilities(
        streaming_transcripts=False,
        native_vad=False,
        dtmf=False,
        interruption=True,  # Enables native barge-in / interrupt signal
        input_formats=["pcm16/24000"],
        output_formats=["pcm16/24000"],
    )

    def __init__(
        self,
        url: str = "ws://127.0.0.1:8765",
        protocol: Optional[JsonAudioWebSocketProtocol] = None,
        transcript_path: Optional[Path] = None,
    ) -> None:
        super().__init__(url=url, protocol=protocol or JsonAudioWebSocketProtocol())
        self.transcript_path = transcript_path
        self.response_timeout = 90.0  # Generous budget for real-time network streaming
        self._turn_index = 0

    def _append_transcript(self, entry: str) -> None:
        """Immediately append turn text to transcript file and flush to disk in real time."""
        if self.transcript_path:
            with open(self.transcript_path, "a", encoding="utf-8") as f:
                f.write(entry + "\n\n")
                f.flush()

    async def connect(self) -> None:
        """Connect to WebSocket server with large frame buffer."""
        import websockets

        self._ws = await websockets.connect(
            self.url,
            max_size=32 * 1024 * 1024,  # 32 MB frame limit
            ping_interval=None,         # Disables keepalive ping timeout
        )
        logger.info("[WebSocket Client] Connected to %s", self.url)

    async def interrupt(self) -> None:
        """Send native cancellation signal over WebSocket to cancel agent speech."""
        t_str = datetime.now().strftime("%H:%M:%S")
        self._append_transcript(f"[{t_str}] ⚡ [BARGE-IN / INTERRUPTION]: Caller interrupted the support agent mid-speech!")
        logger.info("[BARGE-IN] Sent interruption signal to WebSocket server.")

        if self._ws is not None:
            await self._ws.send(json.dumps({"type": "interrupt"}))

    async def call(self, input: Any, *args, **kwargs) -> Any:
        """Forward audio to WebSocket server, drain reply, and record in real-time transcript."""
        self._turn_index += 1
        curr_turn = self._turn_index

        # 1. Forward audio to WebSocket server and collect response
        msg = await super().call(input, *args, **kwargs)

        # 2. Extract transcript and audio info from the response
        agent_text = None
        content = msg.get("content") if isinstance(msg, dict) else None
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    agent_text = part.get("text")
                    break

        agent_chunk = extract_audio(msg) if isinstance(msg, dict) else None
        if not agent_text and agent_chunk and agent_chunk.transcript:
            agent_text = agent_chunk.transcript

        has_audio = agent_chunk is not None and bool(agent_chunk.data)
        if has_audio and not agent_text:
            agent_text = "(spoken audio response)"

        if agent_text:
            t_now = datetime.now().strftime("%H:%M:%S")
            self._append_transcript(f"[{t_now}] [Turn {curr_turn}] 🤖 Gemini Support Agent:\n{agent_text}")
            logger.info("[Live Transcript] Agent [Turn %d]: %s", curr_turn, agent_text)

            # Ensure text is in content for JudgeAgent evaluation
            if isinstance(content, list):
                has_text = any(isinstance(p, dict) and p.get("type") == "text" for p in content)
                if not has_text:
                    content.insert(0, {"type": "text", "text": agent_text})

        return msg
