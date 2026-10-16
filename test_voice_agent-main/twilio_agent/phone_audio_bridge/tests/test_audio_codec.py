"""Unit tests for G.711 mu-law and PCM audio codec utilities."""

import numpy as np
import pytest

from twilio_agent.phone_audio_bridge.audio_codec import (
    mulaw_to_pcm16,
    pcm16_to_mulaw,
    calculate_rms,
    resample_pcm,
)


def test_mulaw_pcm_roundtrip():
    """Verify that linear PCM audio encoded to mu-law and decoded back preserves waveform."""
    # Generate 1 second of 440Hz sine wave at 8000Hz (16-bit PCM)
    t = np.linspace(0, 1.0, 8000, endpoint=False)
    orig_signal = (np.sin(2 * np.pi * 440 * t) * 15000).astype(np.int16)
    orig_bytes = orig_signal.tobytes()

    # Encode to mu-law
    mulaw_bytes = pcm16_to_mulaw(orig_bytes)
    assert len(mulaw_bytes) == 8000  # 1 byte per sample in mu-law

    # Decode back to PCM16
    decoded_bytes = mulaw_to_pcm16(mulaw_bytes)
    assert len(decoded_bytes) == 16000  # 2 bytes per sample in PCM16

    decoded_signal = np.frombuffer(decoded_bytes, dtype=np.int16)

    # Mu-law is lossy compression (logarithmic), but signal-to-noise ratio should be very high
    # Correlation between original and decoded should be > 0.99
    correlation = np.corrcoef(orig_signal, decoded_signal)[0, 1]
    assert correlation > 0.99


def test_empty_buffers():
    """Verify handling of empty or edge-case byte sequences."""
    assert mulaw_to_pcm16(b"") == b""
    assert pcm16_to_mulaw(b"") == b""
    assert calculate_rms(b"") == 0
    assert resample_pcm(b"", 8000, 16000) == b""


def test_calculate_rms():
    """Verify RMS volume level calculation."""
    # Silence
    silence = np.zeros(160, dtype=np.int16).tobytes()
    assert calculate_rms(silence) == 0

    # Constant amplitude
    const_amp = (np.ones(160, dtype=np.int16) * 1000).tobytes()
    assert calculate_rms(const_amp) == 1000


def test_resample_pcm():
    """Verify resampling up and down."""
    # 8000Hz (160 samples -> 20ms)
    pcm_8k = (np.ones(160, dtype=np.int16) * 500).tobytes()
    assert len(pcm_8k) == 320

    # Resample 8k -> 16k (should double the number of samples)
    pcm_16k = resample_pcm(pcm_8k, 8000, 16000)
    assert len(pcm_16k) == 640

    # Resample 16k -> 8k
    back_to_8k = resample_pcm(pcm_16k, 16000, 8000)
    assert len(back_to_8k) == 320

