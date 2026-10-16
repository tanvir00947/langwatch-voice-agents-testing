"""Resilient Speech Synthesis Engine supporting Gemini Live native audio and multi-accent TTS.

Synthesis Strategies:
1. Gemini Live Native Audio (gemini-2.5-flash-native-audio-latest):
   - Direct multimodal audio generation using Gemini API.
   - Built-in natural human voices (Puck, Aoede, Fenrir, Kore, Leda).
   - Accents controlled via system instruction (Indian, British, US, etc.).
2. Edge-TTS neural voice synthesis.
3. Offline synthetic speech envelope fallback (ensures tests never crash even when offline).
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import subprocess
import wave
from typing import Dict, Optional

import numpy as np

from voice_agent_testing_platform.core.audio_utils import resample_pcm

logger = logging.getLogger("platform.speech_engine")

ACCENT_PRESETS: Dict[str, Dict[str, str]] = {
    "indian_male": {"voice": "Puck", "accent_prompt": "Speak with a natural, clear Indian English accent.", "label": "Indian English (Male - Puck)"},
    "indian_female": {"voice": "Aoede", "accent_prompt": "Speak with a natural, polite Indian English accent.", "label": "Indian English (Female - Aoede)"},
    "us_male": {"voice": "Fenrir", "accent_prompt": "Speak with a natural, standard American accent.", "label": "US English (Male - Fenrir)"},
    "us_female": {"voice": "Kore", "accent_prompt": "Speak with a standard American accent.", "label": "US English (Female - Kore)"},
    "british_male": {"voice": "Puck", "accent_prompt": "Speak with a natural British accent.", "label": "British English (Male - Puck)"},
    "british_female": {"voice": "Aoede", "accent_prompt": "Speak with a British accent.", "label": "British English (Female - Aoede)"},
    "australian_male": {"voice": "Fenrir", "accent_prompt": "Speak with an Australian accent.", "label": "Australian English (Male - Fenrir)"},
}


async def _synthesize_gemini_live(
    text: str,
    voice_name: str = "Puck",
    accent_instruction: str = "",
    sample_rate: int = 24000,
) -> Optional[bytes]:
    """Generate spoken speech natively via Gemini Live API."""
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        return None

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)

        instruction = (
            "You are a test caller speaking aloud over the phone.\n"
            f"{accent_instruction}\n"
            "Speak ONLY the exact text provided by the user. Do not add commentary or greeting."
        )

        config = types.LiveConnectConfig(
            response_modalities=[types.Modality.AUDIO],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice_name)
                )
            ),
            system_instruction=instruction,
        )

        audio_chunks = bytearray()
        async with client.aio.live.connect(
            model="gemini-2.5-flash-native-audio-latest",
            config=config,
        ) as session:
            prompt = f"Speak the following words aloud naturally: {text}"
            await session.send_client_content(
                turns=[types.Content(role="user", parts=[types.Part.from_text(text=prompt)])],
                turn_complete=True,
            )

            async for msg in session.receive():
                sc = getattr(msg, "server_content", None)
                if not sc:
                    continue
                if sc.model_turn and sc.model_turn.parts:
                    for part in sc.model_turn.parts:
                        if part.inline_data and part.inline_data.data:
                            audio_chunks.extend(part.inline_data.data)
                if sc.turn_complete:
                    break

        raw_pcm = bytes(audio_chunks)
        if raw_pcm:
            # Gemini Live outputs 24000Hz mono PCM16
            return resample_pcm(raw_pcm, 24000, sample_rate)

    except Exception as exc:
        logger.warning("Gemini Live native speech synthesis error: %s", exc)

    return None


async def _synthesize_edge_tts(
    text: str,
    voice: str = "en-US-GuyNeural",
    sample_rate: int = 24000,
) -> Optional[bytes]:
    """Attempt edge-tts synthesis if available."""
    try:
        import edge_tts
        import imageio_ffmpeg
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()

        comm = edge_tts.Communicate(text, voice)
        mp3_chunks = []
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                mp3_chunks.append(chunk["data"])

        mp3_data = b"".join(mp3_chunks)
        if not mp3_data:
            return None

        loop = asyncio.get_running_loop()

        def _transcode() -> bytes:
            proc = subprocess.Popen(
                [
                    ffmpeg_exe, "-y", "-i", "pipe:0",
                    "-f", "s16le", "-acodec", "pcm_s16le",
                    "-ar", str(sample_rate), "-ac", "1", "pipe:1",
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            out, _ = proc.communicate(input=mp3_data)
            return out

        pcm = await loop.run_in_executor(None, _transcode)
        return pcm[:-1] if len(pcm) % 2 != 0 else pcm

    except Exception as exc:
        logger.debug("Edge-TTS attempt not available: %s", exc)
        return None


def _generate_synthetic_speech_fallback(text: str, sample_rate: int = 24000) -> bytes:
    """Generate a clean modulated acoustic formant wave for offline fallback."""
    duration_s = max(0.5, len(text) * 0.06)
    n_samples = int(duration_s * sample_rate)
    t = np.linspace(0, duration_s, n_samples, endpoint=False)

    f0 = 140.0  # Base fundamental frequency
    formant1 = 600.0
    formant2 = 1400.0

    # Syllable modulation
    mod = (np.sin(2 * np.pi * 4.0 * t) + 1.0) * 0.5

    wave_data = (
        np.sin(2 * np.pi * f0 * t) * 0.5 +
        np.sin(2 * np.pi * formant1 * t) * 0.3 +
        np.sin(2 * np.pi * formant2 * t) * 0.2
    ) * mod * 12000.0

    return wave_data.astype("<i2").tobytes()


async def synthesize_speech_pcm(
    text: str,
    accent_or_voice: str = "indian_male",
    sample_rate: int = 24000,
) -> bytes:
    """Synthesize text into raw PCM16 mono bytes using Gemini Live or fallbacks."""
    if not text.strip():
        return b""

    # Resolve preset
    preset = ACCENT_PRESETS.get(accent_or_voice, {})
    voice_name = preset.get("voice", "Puck")
    accent_prompt = preset.get("accent_prompt", "")

    # 1. Primary: Gemini Live Native Voice (High quality, multi-accent, real human cadence)
    if os.environ.get("GEMINI_API_KEY"):
        gemini_audio = await _synthesize_gemini_live(
            text=text,
            voice_name=voice_name,
            accent_instruction=accent_prompt,
            sample_rate=sample_rate,
        )
        if gemini_audio and len(gemini_audio) > 100:
            return gemini_audio

    # 2. Secondary: Edge-TTS
    edge_audio = await _synthesize_edge_tts(text=text, sample_rate=sample_rate)
    if edge_audio and len(edge_audio) > 100:
        return edge_audio

    # 3. Offline Acoustic Fallback
    logger.info("Using offline synthetic speech fallback for: %r", text[:40])
    return _generate_synthetic_speech_fallback(text, sample_rate=sample_rate)


def pcm_to_wav_bytes(pcm_bytes: bytes, sample_rate: int = 24000) -> bytes:
    """Wrap PCM16 bytes into an in-memory WAV stream."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)
    return buf.getvalue()

