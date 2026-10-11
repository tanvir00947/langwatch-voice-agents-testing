"""High-fidelity Text-To-Speech (TTS) engine for Gemini Live Agent testing.

Synthesizes text into canonical PCM16 24kHz mono audio bytes (Scenario format)
using neural voices, without requiring any OpenAI API key or paid subscription.
"""

from __future__ import annotations

import asyncio
import io
import logging
import subprocess
import wave
import edge_tts
import imageio_ffmpeg

logger = logging.getLogger("gemini_live.tts")

# Get bundled ffmpeg executable path from imageio_ffmpeg
_FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()


async def synthesize_speech_pcm24k(
    text: str,
    voice: str = "en-US-GuyNeural",
) -> bytes:
    """Synthesize text into raw PCM16 24kHz mono bytes.

    Args:
        text: The string to speak.
        voice: The neural voice to use (e.g. 'en-US-GuyNeural', 'en-US-AriaNeural').

    Returns:
        Raw PCM16 24kHz mono audio bytes.
    """
    if not text.strip():
        return b""

    # 1. Synthesize audio via edge-tts (returns MP3 stream)
    comm = edge_tts.Communicate(text, voice)
    mp3_chunks = []
    async for chunk in comm.stream():
        if chunk["type"] == "audio":
            mp3_chunks.append(chunk["data"])

    mp3_data = b"".join(mp3_chunks)
    if not mp3_data:
        logger.warning("TTS yielded empty audio data for: %s", text[:50])
        return b""

    # 2. Transcode MP3 to raw PCM16 24kHz mono using bundled ffmpeg
    loop = asyncio.get_running_loop()

    def _transcode() -> bytes:
        proc = subprocess.Popen(
            [
                _FFMPEG_EXE,
                "-i", "pipe:0",
                "-f", "s16le",
                "-acodec", "pcm_s16le",
                "-ar", "24000",
                "-ac", "1",
                "pipe:1",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        pcm_out, err = proc.communicate(input=mp3_data)
        if proc.returncode != 0:
            logger.error("FFmpeg transcode failed: %s", err.decode(errors="replace"))
            return b""
        return pcm_out

    pcm_bytes = await loop.run_in_executor(None, _transcode)

    # Ensure even length (PCM16 invariant: 2 bytes per sample)
    if len(pcm_bytes) % 2 != 0:
        pcm_bytes = pcm_bytes[:-1]

    return pcm_bytes


def pcm16_to_wav_bytes(pcm_bytes: bytes, sample_rate: int = 24000) -> bytes:
    """Wrap raw PCM16 mono bytes into a valid in-memory WAV container."""
    wav_io = io.BytesIO()
    with wave.open(wav_io, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)
    return wav_io.getvalue()
