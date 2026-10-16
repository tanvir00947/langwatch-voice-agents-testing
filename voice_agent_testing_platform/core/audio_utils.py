"""Audio processing utilities: resampling, G.711 mu-law codecs, acoustic filters, and DTMF synthesis."""

from __future__ import annotations

import io
import math
import struct
import wave
from typing import Optional
import numpy as np


# ====================================================================
# 1. Resampling
# ====================================================================

def resample_pcm(data: bytes, orig_sr: int, target_sr: int) -> bytes:
    """Resample 16-bit little-endian mono PCM data using numpy linear interpolation."""
    if not data or orig_sr == target_sr:
        return data

    samples = np.frombuffer(data, dtype="<i2")
    if len(samples) == 0:
        return b""

    num_output_samples = int(round(len(samples) * float(target_sr) / float(orig_sr)))
    if num_output_samples <= 0:
        return b""

    x_old = np.linspace(0.0, 1.0, len(samples))
    x_new = np.linspace(0.0, 1.0, num_output_samples)
    interpolated = np.interp(x_new, x_old, samples).astype("<i2")

    res = interpolated.tobytes()
    return res[:-1] if len(res) % 2 == 1 else res


# ====================================================================
# 2. G.711 mu-law (PCMU) Encoding and Decoding
# ====================================================================

# Precomputed mu-law expansion table (256 entries for 8-bit to 16-bit)
_MULAW_TO_PCM = np.zeros(256, dtype=np.int16)
for i in range(256):
    inv = ~i & 0xFF
    sign = (inv & 0x80)
    exponent = (inv >> 4) & 0x07
    mantissa = inv & 0x0F
    sample = ((mantissa << 3) + 0x84) << exponent
    sample -= 0x84
    if sign == 0:
        sample = -sample
    _MULAW_TO_PCM[i] = np.clip(sample, -32768, 32767)


def mulaw_to_pcm16(mulaw_bytes: bytes) -> bytes:
    """Decode G.711 mu-law (8kHz 8-bit) bytes to linear PCM16 bytes."""
    if not mulaw_bytes:
        return b""
    indices = np.frombuffer(mulaw_bytes, dtype=np.uint8)
    pcm_samples = _MULAW_TO_PCM[indices]
    return pcm_samples.tobytes()


def pcm16_to_mulaw(pcm_bytes: bytes) -> bytes:
    """Encode linear PCM16 (signed 16-bit mono) bytes into G.711 mu-law (8-bit) bytes."""
    if not pcm_bytes:
        return b""
    samples = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.int32)
    # Clip and determine signs
    signs = samples < 0
    magnitudes = np.abs(samples)
    # Clip magnitude to max 32635
    magnitudes = np.clip(magnitudes, 0, 32635)
    magnitudes += 0x84

    # Quantize to 8-bit mu-law
    exponents = np.zeros_like(magnitudes, dtype=np.uint8)
    for exp in range(7, -1, -1):
        mask = (magnitudes >= (0x84 << exp)) & (exponents == 0)
        exponents[mask] = exp

    mantissas = ((magnitudes >> (exponents + 3)) & 0x0F).astype(np.uint8)
    mulaw = ~(
        (np.where(signs, 0x00, 0x80).astype(np.uint8)) |
        (exponents << 4) |
        mantissas
    )
    return mulaw.tobytes()


# ====================================================================
# 3. Acoustic Filters & Environmental Noise Simulation
# ====================================================================

def apply_telephony_filter(pcm_bytes: bytes, sample_rate: int = 24000) -> bytes:
    """Applies a realistic PSTN / 3G telephony bandpass filter (300Hz - 3400Hz)."""
    if not pcm_bytes:
        return b""
    samples = np.frombuffer(pcm_bytes, dtype="<i2").astype(np.float32)
    if len(samples) < 32:
        return pcm_bytes

    # Simple FFT-based brickwall bandpass filter with smooth edges
    fft_vals = np.fft.rfft(samples)
    freqs = np.fft.rfftfreq(len(samples), d=1.0 / sample_rate)

    # Telecom mask between 300Hz and 3400Hz with soft rolloff
    low_cutoff, high_cutoff = 300.0, 3400.0
    mask = np.ones_like(freqs, dtype=np.float32)
    # Roll off below 300Hz
    mask[freqs < low_cutoff] = np.exp(-((low_cutoff - freqs[freqs < low_cutoff]) / 80.0) ** 2)
    # Roll off above 3400Hz
    mask[freqs > high_cutoff] = np.exp(-((freqs[freqs > high_cutoff] - high_cutoff) / 250.0) ** 2)

    filtered_fft = fft_vals * mask
    filtered_samples = np.fft.irfft(filtered_fft, n=len(samples))

    # Subtle soft telephone saturation/compression
    filtered_samples = np.tanh(filtered_samples / 26000.0) * 26000.0
    clipped = np.clip(filtered_samples, -32768, 32767).astype("<i2")
    return clipped.tobytes()


def add_background_noise(
    pcm_bytes: bytes,
    noise_type: str = "cafe",
    volume: float = 0.15,
    sample_rate: int = 24000,
) -> bytes:
    """Injects realistic synthetic background noise into PCM audio."""
    if not pcm_bytes or volume <= 0:
        return pcm_bytes

    samples = np.frombuffer(pcm_bytes, dtype="<i2").astype(np.float32)
    n_samples = len(samples)
    if n_samples == 0:
        return pcm_bytes

    t = np.linspace(0, n_samples / sample_rate, n_samples, endpoint=False)
    rng = np.random.default_rng(42)

    if noise_type == "cafe":
        # Low frequency crowd chatter murmur (150-800Hz) + occasional clatter
        pink_noise = np.cumsum(rng.standard_normal(n_samples))
        pink_noise -= np.mean(pink_noise)
        if np.max(np.abs(pink_noise)) > 0:
            pink_noise /= np.max(np.abs(pink_noise))
        chatter = (
            np.sin(2 * np.pi * 220 * t) * 0.2 +
            np.sin(2 * np.pi * 380 * t) * 0.15 +
            np.sin(2 * np.pi * 550 * t) * 0.1
        )
        noise = (pink_noise * 0.7 + chatter * 0.3) * (volume * 18000.0)

    elif noise_type == "office":
        # AC hum (50/60Hz) + subtle keyboard clicks
        ac_hum = np.sin(2 * np.pi * 60 * t) * 0.4 + np.sin(2 * np.pi * 120 * t) * 0.2
        white = rng.standard_normal(n_samples) * 0.4
        noise = (ac_hum + white) * (volume * 12000.0)

    elif noise_type == "static":
        # Telephone line static / hiss
        white = rng.standard_normal(n_samples)
        noise = white * (volume * 10000.0)

    else:
        # Default mild white noise
        noise = rng.standard_normal(n_samples) * (volume * 10000.0)

    mixed = samples + noise
    clipped = np.clip(mixed, -32768, 32767).astype("<i2")
    return clipped.tobytes()


# ====================================================================
# 4. DTMF Audio Generation
# ====================================================================

DTMF_FREQUENCIES = {
    "1": (697, 1209), "2": (697, 1336), "3": (697, 1477), "A": (697, 1633),
    "4": (770, 1209), "5": (770, 1336), "6": (770, 1477), "B": (770, 1633),
    "7": (852, 1209), "8": (852, 1336), "9": (852, 1477), "C": (852, 1633),
    "*": (941, 1209), "0": (941, 1336), "#": (941, 1477), "D": (941, 1633),
}


def generate_dtmf_tone(
    digit: str,
    duration_seconds: float = 0.2,
    sample_rate: int = 8000,
) -> bytes:
    """Generate dual-tone multi-frequency (DTMF) 16-bit mono PCM audio for a phone digit."""
    digit = digit.upper()
    freqs = DTMF_FREQUENCIES.get(digit, (0, 0))
    if freqs == (0, 0):
        # Return silence if invalid
        num_samples = int(duration_seconds * sample_rate)
        return (np.zeros(num_samples, dtype="<i2")).tobytes()

    f1, f2 = freqs
    n_samples = int(duration_seconds * sample_rate)
    t = np.linspace(0, duration_seconds, n_samples, endpoint=False)
    tone = (np.sin(2 * np.pi * f1 * t) + np.sin(2 * np.pi * f2 * t)) * 0.45 * 32767
    return tone.astype("<i2").tobytes()


# ====================================================================
# 5. WAV File Persistence
# ====================================================================

def save_wav(
    file_path: str,
    pcm_bytes: bytes,
    sample_rate: int = 24000,
    channels: int = 1,
) -> None:
    """Save raw PCM16 bytes to a standard WAV audio file."""
    with wave.open(file_path, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)


def load_wav(file_path: str) -> tuple[bytes, int]:
    """Load a WAV audio file returning (pcm_bytes, sample_rate)."""
    with wave.open(file_path, "rb") as wf:
        sample_rate = wf.getframerate()
        raw_frames = wf.readframes(wf.getnframes())
        channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()

        # If stereo, convert to mono
        return raw_frames, sample_rate


def save_stereo_wav(
    file_path: str,
    left_pcm: bytes,
    right_pcm: bytes,
    sample_rate: int = 24000,
) -> None:
    """Interleave left (Caller) and right (Agent) mono PCM16 into a 2-channel stereo WAV."""
    s_left = np.frombuffer(left_pcm, dtype="<i2")
    s_right = np.frombuffer(right_pcm, dtype="<i2")

    max_len = max(len(s_left), len(s_right))
    if max_len == 0:
        return

    # Pad with silence if necessary
    if len(s_left) < max_len:
        s_left = np.pad(s_left, (0, max_len - len(s_left)), mode="constant")
    if len(s_right) < max_len:
        s_right = np.pad(s_right, (0, max_len - len(s_right)), mode="constant")

    # Interleave channels: shape (max_len, 2)
    stereo = np.column_stack((s_left, s_right)).astype("<i2")
    save_wav(file_path, stereo.tobytes(), sample_rate=sample_rate, channels=2)


def extract_waveform_peaks(pcm_bytes: bytes, num_peaks: int = 300) -> list[float]:
    """Downsample PCM16 mono bytes into normalized peak values (0.0 to 1.0) for waveform visualization."""
    if not pcm_bytes:
        return [0.0] * num_peaks

    samples = np.frombuffer(pcm_bytes, dtype="<i2").astype(np.float32)
    if len(samples) == 0:
        return [0.0] * num_peaks

    # Absolute values normalized to 0.0 - 1.0
    abs_samples = np.abs(samples) / 32768.0

    chunk_size = max(1, len(abs_samples) // num_peaks)
    peaks = []
    for i in range(num_peaks):
        start = i * chunk_size
        end = min(len(abs_samples), start + chunk_size)
        if start >= len(abs_samples):
            peaks.append(0.0)
        else:
            val = float(np.max(abs_samples[start:end]))
            peaks.append(round(min(1.0, val), 3))

    return peaks


