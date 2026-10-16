"""Core engine module for Voice Agent & IVA Testing Platform."""

from voice_agent_testing_platform.core.models import (
    AudioChunk,
    Turn,
    TurnRole,
    TurnAction,
    ScenarioStep,
    TestScenario,
    TestResult,
    MetricScores,
    DeterministicMetrics,
)
from voice_agent_testing_platform.core.audio_utils import (
    resample_pcm,
    pcm16_to_mulaw,
    mulaw_to_pcm16,
    save_wav,
    load_wav,
    apply_telephony_filter,
    add_background_noise,
    generate_dtmf_tone,
)
from voice_agent_testing_platform.core.speech_engine import (
    synthesize_speech_pcm,
    ACCENT_PRESETS,
    pcm_to_wav_bytes,
)

__all__ = [
    "AudioChunk",
    "Turn",
    "TurnRole",
    "TurnAction",
    "ScenarioStep",
    "TestScenario",
    "TestResult",
    "MetricScores",
    "DeterministicMetrics",
    "resample_pcm",
    "pcm16_to_mulaw",
    "mulaw_to_pcm16",
    "save_wav",
    "load_wav",
    "apply_telephony_filter",
    "add_background_noise",
    "generate_dtmf_tone",
    "synthesize_speech_pcm",
    "ACCENT_PRESETS",
    "pcm_to_wav_bytes",
]
