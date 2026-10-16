"""Scripted Caller for deterministic step-by-step test execution."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from voice_agent_testing_platform.callers.base_caller import BaseCaller
from voice_agent_testing_platform.core.audio_utils import generate_dtmf_tone, load_wav
from voice_agent_testing_platform.core.models import AudioChunk, ScenarioStep, Turn, TurnAction
from voice_agent_testing_platform.core.speech_engine import synthesize_speech_pcm

logger = logging.getLogger("platform.caller.scripted")


class ScriptedCaller(BaseCaller):
    """Executes a defined sequence of scripted turns, interruptions, and DTMF tones."""

    def __init__(
        self,
        steps: List[ScenarioStep],
        accent: str = "us_male",
        background_noise: Optional[str] = None,
        noise_volume: float = 0.15,
        apply_telephony_distortion: bool = False,
        sample_rate: int = 24000,
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
        self.steps = steps
        self._current_step_idx = 0

    async def get_next_action(
        self,
        turn_index: int,
        history: List[Turn],
    ) -> Tuple[Optional[AudioChunk], TurnAction, Optional[str]]:
        """Fetch the next scripted step and prepare its audio chunk and action."""
        if self._current_step_idx >= len(self.steps):
            return None, TurnAction.WAIT, None

        step = self.steps[self._current_step_idx]
        self._current_step_idx += 1

        logger.info(
            "[Scripted Caller] Step %d/%d: action=%s, dtmf=%s, text=%r",
            self._current_step_idx,
            len(self.steps),
            step.action.value,
            step.dtmf_digit,
            (step.text or "")[:40],
        )

        # 1. DTMF Step
        if step.action == TurnAction.DTMF or step.dtmf_digit:
            digit = step.dtmf_digit or "1"
            dtmf_tone = generate_dtmf_tone(digit, duration_seconds=0.3, sample_rate=self.sample_rate)
            chunk = AudioChunk(
                data=dtmf_tone,
                sample_rate=self.sample_rate,
                format="pcm16",
                transcript=f"[DTMF {digit}]",
                duration_seconds=0.3,
            )
            return chunk, TurnAction.DTMF, digit

        # 2. Utterance Step (SAY or INTERRUPT)
        pcm_bytes = b""
        transcript = step.text or ""

        if step.audio_file:
            pcm_bytes, sr = load_wav(step.audio_file)
        elif step.text:
            pcm_bytes = await synthesize_speech_pcm(
                text=step.text,
                accent_or_voice=self.accent,
                sample_rate=self.sample_rate,
            )

        # Apply acoustic noise and telephony bandpass filter
        processed_pcm = self.apply_acoustic_effects(pcm_bytes)
        duration_s = (len(processed_pcm) / 2.0) / float(self.sample_rate) if processed_pcm else 0.0

        chunk = AudioChunk(
            data=processed_pcm,
            sample_rate=self.sample_rate,
            format="pcm16",
            transcript=transcript,
            duration_seconds=duration_s,
        )

        return chunk, step.action, None

