"""Gemini Live Voice Agent Adapter for Scenario testing.

Connects Scenario's multi-turn voice evaluation framework directly to the
Gemini Live API (gemini-2.5-flash-native-audio-latest) for bidirectional
low-latency audio streaming, native VAD, and real-time turn-by-turn transcription.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from scenario.voice.adapters.gemini_live import GeminiLiveAgentAdapter
from scenario.voice.messages import extract_audio

logger = logging.getLogger("gemini_live.adapter")


class GeminiLiveVoiceAgentAdapter(GeminiLiveAgentAdapter):
    """Scenario adapter for Gemini Live with real-time transcript logging and turn tracking."""

    def __init__(
        self,
        model: str = "gemini-2.5-flash-native-audio-latest",
        voice: str = "Algieba",  # Options: Aoede, Puck, Charon, Kore, Fenrir, Algieba
        system_instruction: str = "",
        api_key: Optional[str] = None,
        transcript_path: Optional[Path] = None,
    ) -> None:
        super().__init__(
            model=model,
            voice=voice,
            system_instruction=system_instruction,
            api_key=api_key,
        )
        self.transcript_path = transcript_path
        self._turn_index = 0

    def _append_transcript(self, entry: str) -> None:
        """Immediately append turn text to transcript file and flush to disk in real time."""
        if self.transcript_path:
            with open(self.transcript_path, "a", encoding="utf-8") as f:
                f.write(entry + "\n\n")
                f.flush()

    async def interrupt(self) -> None:
        """Handle user interruption / barge-in and record the event live."""
        t_str = datetime.now().strftime("%H:%M:%S")
        self._append_transcript(f"[{t_str}] ⚡ [BARGE-IN / INTERRUPTION]: Caller interrupted the agent mid-speech!")
        logger.info("[BARGE-IN] Recorded interruption event in live transcript.")
        await super().interrupt()

    async def call(self, input: Any, *args, **kwargs) -> Any:
        """Intercept each conversation turn: log caller, stream audio to Gemini Live, log agent reply."""
        # Clear per-turn transcript cache before starting
        self._reset_turn_transcript()

        self._turn_index += 1
        curr_turn = self._turn_index
        t_start = datetime.now().strftime("%H:%M:%S")

        # 1. Extract Caller Text
        caller_text = None
        incoming_chunk = None

        if hasattr(input, "new_messages") and input.new_messages:
            last_msg = input.new_messages[-1]
            if isinstance(last_msg, dict):
                content = last_msg.get("content")
                if isinstance(content, str):
                    caller_text = content
                elif isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            caller_text = part.get("text")
                            break

            incoming_chunk = extract_audio(last_msg)
            if not caller_text and incoming_chunk and incoming_chunk.transcript:
                caller_text = incoming_chunk.transcript

        # Only log caller turn if there was a user message
        has_user_turn = (
            hasattr(input, "new_messages")
            and input.new_messages
            and input.new_messages[-1].get("role") == "user"
        )
        if has_user_turn:
            if not caller_text:
                caller_text = "(audio spoken)"
            self._append_transcript(f"[{t_start}] [Turn {curr_turn}] 👤 Caller:\n{caller_text}")
            logger.info("[Live Transcript] Caller [Turn %d]: %s", curr_turn, caller_text)

        # 2. Forward audio to Gemini Live and drain streaming response audio
        msg = await super().call(input, *args, **kwargs)

        # 3. Extract Gemini Live's native output transcript from this turn
        agent_text = None
        content = msg.get("content") if isinstance(msg, dict) else None
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    agent_text = part.get("text")
                    break

        if not agent_text and self.last_agent_transcript:
            agent_text = self.last_agent_transcript

        agent_chunk = extract_audio(msg) if isinstance(msg, dict) else None
        has_agent_audio = agent_chunk is not None and bool(agent_chunk.data)

        if has_agent_audio and not agent_text:
            agent_text = "(audio response)"

        if agent_text:
            t_end = datetime.now().strftime("%H:%M:%S")
            self._append_transcript(f"[{t_end}] [Turn {curr_turn}] 🤖 Gemini Live:\n{agent_text}")
            logger.info("[Live Transcript] Gemini Live [Turn %d]: %s", curr_turn, agent_text)

            # Ensure the text is present in content for JudgeAgent
            if isinstance(content, list):
                has_text = any(isinstance(p, dict) and p.get("type") == "text" for p in content)
                if not has_text:
                    content.insert(0, {"type": "text", "text": agent_text})

        return msg
