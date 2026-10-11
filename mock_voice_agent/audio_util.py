"""Audio utility to generate or handle canonical PCM16 24kHz audio."""

import math
import struct


def generate_pcm16_chime(duration_sec: float = 1.5, sample_rate: int = 24000) -> bytes:
    """Generate a gentle 24kHz 16-bit mono chime/tone as valid PCM bytes.

    This ensures the WebSocket agent can return valid, playable PCM16 24kHz
    audio immediately without requiring external audio files or TTS models.
    """
    total_samples = int(duration_sec * sample_rate)
    buffer = bytearray()

    # Pleasant harmonious chords: 523.25 Hz (C5) and 659.25 Hz (E5)
    f1 = 523.25
    f2 = 659.25

    for i in range(total_samples):
        t = i / sample_rate
        # Exponential decay envelope for a bell/chime sound
        envelope = math.exp(-2.5 * (t / duration_sec))
        sample_val = 0.5 * math.sin(2 * math.pi * f1 * t) + 0.5 * math.sin(2 * math.pi * f2 * t)
        sample_val *= envelope

        # Scale to 16-bit signed integer range (-32768 to 32767)
        int_sample = int(sample_val * 24000)
        int_sample = max(-32767, min(32767, int_sample))

        # Pack as little-endian 16-bit signed integer
        buffer.extend(struct.pack("<h", int_sample))

    return bytes(buffer)
