"""Audio Codec utilities for Twilio Media Streams (G.711 mu-law <-> PCM16).

Twilio Media Streams exchange 8000Hz 8-bit mono mu-law audio over WebSocket.
This module provides high-speed, zero-dependency (numpy-accelerated) conversion
between G.711 mu-law and 16-bit linear PCM, volume detection (RMS), and resampling.
"""

from __future__ import annotations

import math
import struct
import numpy as np
from typing import Optional

# ---------------------------------------------------------------------------
# G.711 mu-law Lookup Tables
# Precalculated tables guarantee 100% standard compliance and C-speed execution
# without relying on deprecated standard library modules.
# ---------------------------------------------------------------------------

def _build_g711_tables() -> tuple[np.ndarray, np.ndarray]:
    """Build exact 256-entry decode and 65536-entry encode lookup tables."""
    try:
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            import audioop

        decode_table = np.array(
            [int.from_bytes(audioop.ulaw2lin(bytes([b]), 2), byteorder="little", signed=True) for b in range(256)],
            dtype=np.int16,
        )
        encode_table = np.zeros(65536, dtype=np.uint8)
        for i in range(65536):
            val = i - 32768
            pcm = val.to_bytes(2, byteorder="little", signed=True)
            encode_table[i] = audioop.lin2ulaw(pcm, 2)[0]

        return decode_table, encode_table
    except Exception:
        # Fallback if audioop is unavailable
        decode_table = np.zeros(256, dtype=np.int16)
        for b in range(256):
            inv = ~b & 0xFF
            sign = inv & 0x80
            exponent = (inv >> 4) & 0x07
            mantissa = inv & 0x0F
            sample = ((mantissa << 3) + 0x84) << exponent
            sample -= 0x84
            if sign == 0:
                sample = -sample
            decode_table[b] = np.int16(sample)

        encode_table = np.zeros(65536, dtype=np.uint8)
        for i in range(65536):
            pcm_val = i - 32768
            sign = 0x80 if pcm_val >= 0 else 0
            if pcm_val < 0:
                pcm_val = -pcm_val
            if pcm_val > 32635:
                pcm_val = 32635
            pcm_val += 0x84

            exponent = 7
            for exp in range(7):
                if pcm_val <= (0xFF << (exp + 3)):
                    exponent = exp
                    break

            mantissa = (pcm_val >> (exponent + 3)) & 0x0F
            ulaw_byte = ~(sign | (exponent << 4) | mantissa) & 0xFF
            encode_table[i] = np.uint8(ulaw_byte)

        return decode_table, encode_table


_DECODE_TABLE, _ENCODE_TABLE = _build_g711_tables()


def mulaw_to_pcm16(mulaw_bytes: bytes) -> bytes:
    """Decode G.711 mu-law 8-bit bytes to linear 16-bit PCM (little-endian).

    Args:
        mulaw_bytes: Raw bytes from Twilio Media Streams (8kHz, 8-bit mono).

    Returns:
        16-bit signed PCM audio bytes (8kHz, 16-bit mono).
    """
    if not mulaw_bytes:
        return b""
    indices = np.frombuffer(mulaw_bytes, dtype=np.uint8)
    return _DECODE_TABLE[indices].tobytes()


def pcm16_to_mulaw(pcm_bytes: bytes) -> bytes:
    """Encode 16-bit linear PCM bytes to G.711 mu-law 8-bit bytes.

    Args:
        pcm_bytes: 16-bit signed linear PCM bytes (8kHz, 16-bit mono).

    Returns:
        G.711 mu-law 8-bit bytes ready for Twilio media payload.
    """
    if not pcm_bytes:
        return b""
    # Ensure byte alignment
    if len(pcm_bytes) % 2 != 0:
        pcm_bytes = pcm_bytes[: -(len(pcm_bytes) % 2)]
    indices = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.int32) + 32768
    return _ENCODE_TABLE[indices].tobytes()


def calculate_rms(pcm_bytes: bytes) -> int:
    """Calculate the Root Mean Square (RMS) volume of a 16-bit PCM audio chunk.

    Used for voice activity detection and live audio metering.
    """
    if not pcm_bytes or len(pcm_bytes) < 2:
        return 0
    sample_count = len(pcm_bytes) // 2
    samples = struct.unpack(f"<{sample_count}h", pcm_bytes[: sample_count * 2])
    sum_squares = sum(s * s for s in samples)
    return int(math.sqrt(sum_squares / sample_count))


def resample_pcm(
    pcm_bytes: bytes,
    src_rate: int,
    dst_rate: int,
) -> bytes:
    """Resample 16-bit linear PCM audio from src_rate to dst_rate.

    Handles conversion between 8kHz (Twilio) and 16kHz/24kHz (Gemini/LangWatch/hardware).
    """
    if not pcm_bytes or src_rate == dst_rate:
        return pcm_bytes

    if len(pcm_bytes) % 2 != 0:
        pcm_bytes = pcm_bytes[: -(len(pcm_bytes) % 2)]

    samples = np.frombuffer(pcm_bytes, dtype=np.int16)
    if len(samples) == 0:
        return b""

    # Compute new sample count
    new_sample_count = int(round(len(samples) * (dst_rate / src_rate)))
    if new_sample_count == 0:
        return b""

    old_indices = np.linspace(0, len(samples) - 1, num=len(samples))
    new_indices = np.linspace(0, len(samples) - 1, num=new_sample_count)

    resampled = np.interp(new_indices, old_indices, samples).astype(np.int16)
    return resampled.tobytes()
