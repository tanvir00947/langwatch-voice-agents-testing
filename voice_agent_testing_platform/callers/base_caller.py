"""Base interface and common acoustic processing for simulated callers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple

from voice_agent_testing_platform.core.audio_utils import (
    add_background_noise,
    apply_telephony_filter,
)
from voice_agent_testing_platform.core.models import AudioChunk, Turn, TurnAction


class BaseCaller(ABC):
    """Abstract Base Class for caller simulation agents."""

    def __init__(
        self,
        accent: str = "us_male",
        background_noise: Optional[str] = None,
        noise_volume: float = 0.15,
        apply_telephony_distortion: bool = False,
        sample_rate: int = 24000,
        config: Optional[Dict[str, Any]] = None,
    ):
        self.accent = accent
        self.background_noise = background_noise
        self.noise_volume = noise_volume
        self.apply_telephony_distortion = apply_telephony_distortion
        self.sample_rate = sample_rate
        self.config = config or {}

    def apply_acoustic_effects(self, raw_pcm: bytes) -> bytes:
        """Apply configured background noise and telephony bandpass filters to speech."""
        if not raw_pcm:
            return raw_pcm

        processed = raw_pcm
        # 1. Apply telephony bandpass filter if enabled
        if self.apply_telephony_distortion:
            processed = apply_telephony_filter(processed, sample_rate=self.sample_rate)

        # 2. Inject environmental background noise (cafe, office, static)
        if self.background_noise and self.background_noise != "none":
            processed = add_background_noise(
                processed,
                noise_type=self.background_noise,
                volume=self.noise_volume,
                sample_rate=self.sample_rate,
            )

        return processed

    @abstractmethod
    async def get_next_action(
        self,
        turn_index: int,
        history: List[Turn],
    ) -> Tuple[Optional[AudioChunk], TurnAction, Optional[str]]:
        """Determine next action for the caller.

        Returns:
            (audio_chunk, action, dtmf_digit)
        """
        pass

    async def teardown(self) -> None:
        """Cleanup any background sessions or audio streams."""
        pass

