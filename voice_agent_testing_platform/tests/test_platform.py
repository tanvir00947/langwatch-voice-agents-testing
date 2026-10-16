"""Unit and Integration tests for Voice Agent Testing Platform core components."""

from __future__ import annotations

import asyncio
from pathlib import Path
import sys

PLATFORM_DIR = Path(__file__).resolve().parent.parent
if str(PLATFORM_DIR.parent) not in sys.path:
    sys.path.insert(0, str(PLATFORM_DIR.parent))

import pytest
import numpy as np

from voice_agent_testing_platform.core.audio_utils import (
    add_background_noise,
    apply_telephony_filter,
    generate_dtmf_tone,
    mulaw_to_pcm16,
    pcm16_to_mulaw,
    resample_pcm,
)
from voice_agent_testing_platform.core.speech_engine import synthesize_speech_pcm
from voice_agent_testing_platform.core.models import ScenarioStep, Turn, TurnAction, TurnRole
from voice_agent_testing_platform.evaluator.deterministic import DeterministicEvaluator
from voice_agent_testing_platform.adapters.telephony.mock_telephony_adapter import MockTelephonyAdapter


def test_audio_codecs_and_resampling():
    """Verify G.711 mu-law round-trip and PCM resampling."""
    # Generate 1 second of 440Hz sine wave at 24000Hz
    t = np.linspace(0, 1.0, 24000, endpoint=False)
    sine = (np.sin(2 * np.pi * 440 * t) * 15000).astype("<i2").tobytes()

    # 1. Resample to 8000Hz
    downsampled = resample_pcm(sine, 24000, 8000)
    assert len(downsampled) == 8000 * 2  # 16000 bytes

    # 2. Resample back to 24000Hz
    upsampled = resample_pcm(downsampled, 8000, 24000)
    assert len(upsampled) == 24000 * 2

    # 3. G.711 mu-law encode & decode round trip
    mulaw = pcm16_to_mulaw(downsampled)
    assert len(mulaw) == 8000  # 1 byte per sample in mu-law
    restored_pcm = mulaw_to_pcm16(mulaw)
    assert len(restored_pcm) == 8000 * 2


def test_acoustic_filters():
    """Verify telephony bandpass filter and environmental noise injection."""
    t = np.linspace(0, 0.5, 12000, endpoint=False)
    sine = (np.sin(2 * np.pi * 1000 * t) * 10000).astype("<i2").tobytes()

    filtered = apply_telephony_filter(sine, sample_rate=24000)
    assert len(filtered) == len(sine)

    noisy = add_background_noise(sine, noise_type="cafe", volume=0.2, sample_rate=24000)
    assert len(noisy) == len(sine)
    assert noisy != sine


def test_dtmf_tone_generation():
    """Verify DTMF audio tone synthesis."""
    dtmf_pcm = generate_dtmf_tone("5", duration_seconds=0.2, sample_rate=8000)
    assert len(dtmf_pcm) == int(0.2 * 8000) * 2


@pytest.mark.asyncio
async def test_speech_synthesis_engine():
    """Verify neural TTS speech generation with regional accents."""
    text = "Testing voice synthesis with Indian accent."
    pcm = await synthesize_speech_pcm(text, accent_or_voice="indian_male", sample_rate=24000)
    assert len(pcm) > 1000  # Generated valid audio bytes
    assert len(pcm) % 2 == 0


@pytest.mark.asyncio
async def test_mock_telephony_adapter():
    """Verify mock telephone adapter connects, sends greeting, and processes DTMF."""
    adapter = MockTelephonyAdapter()
    await adapter.connect()
    assert adapter.is_connected

    # Receive IVR greeting
    resp = await adapter.receive_response()
    assert "Acme" in resp.transcript

    # Send DTMF 1
    await adapter.send_dtmf("1")
    assert adapter.current_state == "dtmf_1"

    # Receive routing confirmation
    resp2 = await adapter.receive_response()
    assert "Technical Support" in resp2.transcript

    await adapter.disconnect()
    assert not adapter.is_connected


def test_deterministic_evaluator():
    """Verify latency calculation, keyword matching, and barge-in tracking."""
    turns = [
        Turn(turn_index=1, timestamp="12:00:00", role=TurnRole.CALLER, text="Can you schedule a demo?"),
        Turn(turn_index=2, timestamp="12:00:01", role=TurnRole.AGENT, text="Yes, we can schedule a live demo this week.", latency_ms=450.0),
        Turn(turn_index=3, timestamp="12:00:02", role=TurnRole.CALLER, text="Wait!", is_interruption=True),
        Turn(turn_index=4, timestamp="12:00:03", role=TurnRole.AGENT, text="I am listening, please go ahead.", latency_ms=300.0),
    ]

    steps = [
        ScenarioStep(action=TurnAction.SAY, text="Can you schedule a demo?", expected_keywords=["demo", "week"]),
    ]

    metrics = DeterministicEvaluator.evaluate(turns, steps=steps)
    assert metrics.avg_latency_ms == 375.0
    assert metrics.barge_in_tested is True
    assert metrics.barge_in_successful is True
    assert metrics.keywords_matched is True
    assert len(metrics.unmatched_keywords) == 0

