"""Autonomous AI Persona Caller driving realistic, dynamic test conversations."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from google import genai
from google.genai import types

from voice_agent_testing_platform.callers.base_caller import BaseCaller
from voice_agent_testing_platform.core.models import AudioChunk, Turn, TurnAction, TurnRole
from voice_agent_testing_platform.core.speech_engine import synthesize_speech_pcm

logger = logging.getLogger("platform.caller.dynamic")


class DynamicAICaller(BaseCaller):
    """Simulates an autonomous human caller using an LLM persona + multi-accent voice synthesis."""

    def __init__(
        self,
        persona: str = "An impatient customer calling customer service with high skepticism.",
        goal: str = "Ask about pricing, challenge their latency claims, and request a live demo.",
        model: str = "gemini-2.5-flash",
        api_key: Optional[str] = None,
        accent: str = "us_male",
        background_noise: Optional[str] = None,
        noise_volume: float = 0.15,
        apply_telephony_distortion: bool = False,
        sample_rate: int = 24000,
        should_interrupt_on_turn: Optional[int] = None,
        config: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            accent=accent,
            background_noise=background_noise,
            noise_volume=noise_volume,
            apply_telephony_distortion=apply_telephony_distortion,
            sample_rate=sample_rate,
            config=config,
        )
        self.persona = persona
        self.goal = goal
        self.model = model
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        self.should_interrupt_on_turn = should_interrupt_on_turn
        self._client = genai.Client(api_key=self.api_key) if self.api_key else None

    async def get_next_action(
        self,
        turn_index: int,
        history: List[Turn],
    ) -> Tuple[Optional[AudioChunk], TurnAction, Optional[str]]:
        """Synthesize next conversational utterance based on persona, goal, and conversation history."""
        # Check if this turn is planned for a barge-in interruption
        is_interruption = False
        if self.should_interrupt_on_turn is not None and turn_index == self.should_interrupt_on_turn:
            is_interruption = True

        # Extract last agent utterance from history
        last_agent_text = ""
        for t in reversed(history):
            if t.role == TurnRole.AGENT and t.text:
                last_agent_text = t.text
                break

        system_instruction = (
            f"You are roleplaying as a human caller on a real telephone call.\n"
            f"Persona: {self.persona}\n"
            f"Your Goal: {self.goal}\n"
            "Rules:\n"
            "1. Speak naturally as a human caller.\n"
            "2. Keep your spoken response to 1-2 concise conversational sentences.\n"
            "3. Do not output markdown, thought tags, or stage directions. Output only what you speak aloud.\n"
        )

        if not last_agent_text:
            prompt = "Start the phone call. State your opening inquiry according to your persona and goal."
        else:
            interruption_directive = " (Interrupt them mid-thought with urgency!)" if is_interruption else ""
            prompt = (
                f"The AI support agent just said: '{last_agent_text}'.\n"
                f"Respond naturally with your next spoken reaction{interruption_directive}."
            )

        utterance_text = "Hello, can someone help me with my account?"
        if self._client:
            try:
                resp = await self._client.aio.models.generate_content(
                    model=self.model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        temperature=0.7,
                    ),
                )
                if resp.text:
                    utterance_text = resp.text.strip().replace('"', "")
            except Exception as e:
                logger.warning("LLM dynamic caller failed to generate content: %s", e)

        logger.info("[Dynamic AI Caller] Spoken response: %r", utterance_text)

        # Synthesize audio with configured accent
        raw_pcm = await synthesize_speech_pcm(
            text=utterance_text,
            accent_or_voice=self.accent,
            sample_rate=self.sample_rate,
        )

        # Apply background noise and telephony filter
        processed_pcm = self.apply_acoustic_effects(raw_pcm)
        duration_s = (len(processed_pcm) / 2.0) / float(self.sample_rate) if processed_pcm else 0.0

        chunk = AudioChunk(
            data=processed_pcm,
            sample_rate=self.sample_rate,
            format="pcm16",
            transcript=utterance_text,
            duration_seconds=duration_s,
        )

        action = TurnAction.INTERRUPT if is_interruption else TurnAction.SAY
        return chunk, action, None

