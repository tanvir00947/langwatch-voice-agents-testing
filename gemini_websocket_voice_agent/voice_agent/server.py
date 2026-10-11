"""Standalone WebSocket Voice Agent powered by Gemini Live Native Audio.

Architecture:
- Native Voice Model: gemini-2.5-flash-native-audio-latest.
- Bidirectional real-time audio over WebSocket.
- No discrete STT + text LLM + TTS pipeline — audio flows directly into and out of Gemini Live.
- Fast numpy audio resampling (incoming 24kHz -> 16kHz for Gemini input; outgoing 24kHz returned directly).
- Real-time barge-in cancellation on interrupt signal with concurrent WebSocket message processing.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import signal
import sys
from pathlib import Path
from dotenv import load_dotenv
import numpy as np

# Ensure Windows terminal handles UTF-8 characters cleanly
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
os.environ["PYTHONIOENCODING"] = "utf-8"

# Load local environment configuration
_DIR = Path(__file__).resolve().parent
_ENV_PATH = _DIR / ".env"
load_dotenv(_ENV_PATH, override=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("voice_agent.server")

# Configuration
_GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
_GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-native-audio-latest").strip()
_VOICE_NAME = os.environ.get("VOICE_NAME", "Aoede").strip()
_HOST = os.environ.get("WS_HOST", "127.0.0.1").strip()
_PORT = int(os.environ.get("WS_PORT", "8765"))

if not _GEMINI_API_KEY:
    logger.error("GEMINI_API_KEY is not set in %s! A valid Gemini API key is required.", _ENV_PATH)
    sys.exit(1)

from google import genai
from google.genai import types

_CLIENT = genai.Client(api_key=_GEMINI_API_KEY)


def resample_24k_to_16k(data: bytes) -> bytes:
    """Downsample mono PCM16 little-endian bytes from 24000Hz to 16000Hz using numpy linear interpolation."""
    if not data:
        return b""
    samples = np.frombuffer(data, dtype="<i2")
    n_out = int(len(samples) * 16000 / 24000)
    if n_out == 0:
        return b""
    x_old = np.linspace(0, 1, len(samples))
    x_new = np.linspace(0, 1, n_out)
    res = np.interp(x_new, x_old, samples).astype("<i2").tobytes()
    return res[:-1] if len(res) % 2 == 1 else res


async def handle_client(websocket) -> None:
    """Handle an incoming WebSocket connection with concurrent listener and Gemini Live worker."""
    client_addr = websocket.remote_address
    logger.info("🎙️ Client connected: %s", client_addr)

    system_instruction = (
        "You are an expert, courteous, and concise customer support voice agent for LangWatch AI on a live phone call. "
        "LangWatch provides LLM observability, evaluations, cost tracking, and real-time voice latency monitoring. "
        "Keep your spoken answers natural, helpful, and concise (1 to 2 short conversational sentences), "
        "as your speech is spoken directly to the caller over the phone. "
        "When asked about features (such as real-time voice evaluations) or scheduling a demo, "
        "warmly confirm and offer to help schedule a live demo this week."
    )

    config = types.LiveConnectConfig(
        response_modalities=[types.Modality.AUDIO],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=_VOICE_NAME)
            )
        ),
        system_instruction=system_instruction,
        output_audio_transcription=types.AudioTranscriptionConfig(),
        realtime_input_config=types.RealtimeInputConfig(
            automatic_activity_detection=types.AutomaticActivityDetection(disabled=True)
        ),
    )

    turn_count = 0
    audio_queue: asyncio.Queue[bytes] = asyncio.Queue()
    interrupted_event = asyncio.Event()
    active_turn_task: Optional[asyncio.Task] = None

    try:
        async with _CLIENT.aio.live.connect(model=_GEMINI_MODEL, config=config) as session:
            logger.info(" Connected to Gemini Live API (%s, voice: %s)", _GEMINI_MODEL, _VOICE_NAME)

            async def _process_turn(incoming_pcm: bytes, curr_turn: int) -> None:
                """Stream a single turn to Gemini Live and forward audio back to WebSocket."""
                pcm_16k = resample_24k_to_16k(incoming_pcm)
                logger.info(
                    "[Turn %d] Ingested caller audio: %d bytes (24k) -> %d bytes (16k) -> streaming to Gemini Live...",
                    curr_turn,
                    len(incoming_pcm),
                    len(pcm_16k),
                )

                # Send activity boundaries and audio blob
                await session.send_realtime_input(activity_start=types.ActivityStart())
                await session.send_realtime_input(
                    audio=types.Blob(data=pcm_16k, mime_type="audio/pcm;rate=16000")
                )
                await session.send_realtime_input(activity_end=types.ActivityEnd())

                transcript_accum = ""
                audio_bytes_sent = 0

                async for resp in session.receive():
                    if interrupted_event.is_set():
                        logger.info("⚡ [Turn %d] Cut short by barge-in interruption.", curr_turn)
                        break

                    sc = getattr(resp, "server_content", None)
                    if not sc:
                        continue

                    if sc.output_transcription and sc.output_transcription.text:
                        transcript_accum += sc.output_transcription.text

                    if sc.model_turn and sc.model_turn.parts:
                        for part in sc.model_turn.parts:
                            if part.inline_data and part.inline_data.data:
                                chunk = part.inline_data.data
                                b64_out = base64.b64encode(chunk).decode("utf-8")
                                await websocket.send(
                                    json.dumps({
                                        "type": "audio",
                                        "data": b64_out,
                                    })
                                )
                                audio_bytes_sent += len(chunk)

                    if sc.turn_complete:
                        if not audio_bytes_sent and not transcript_accum:
                            continue  # Skip spurious empty interrupt markers
                        logger.info(
                            "🤖 [Turn %d Complete] Sent %d bytes 24k audio. Transcript: %r",
                            curr_turn,
                            audio_bytes_sent,
                            transcript_accum,
                        )
                        # Send turn completion message
                        await websocket.send(
                            json.dumps({
                                "type": "turn_complete",
                                "transcript": transcript_accum,
                            })
                        )
                        # Send empty audio marker so downstream drains terminate immediately
                        await websocket.send(
                            json.dumps({
                                "type": "audio",
                                "data": "",
                                "transcript": transcript_accum,
                            })
                        )
                        break

            async def _turn_worker() -> None:
                """Consume audio turns from queue and run each turn sequentially."""
                nonlocal turn_count, active_turn_task
                while True:
                    incoming_pcm = await audio_queue.get()
                    turn_count += 1
                    interrupted_event.clear()
                    active_turn_task = asyncio.create_task(_process_turn(incoming_pcm, turn_count))
                    try:
                        await active_turn_task
                    except asyncio.CancelledError:
                        logger.info("Active turn task cancelled.")
                    except Exception as err:
                        logger.error("Error during turn processing: %s", err)
                    finally:
                        active_turn_task = None
                        audio_queue.task_done()

            # Start background worker for turns
            worker_task = asyncio.create_task(_turn_worker())

            # Reader loop: reads incoming WebSocket messages concurrently
            async for raw_message in websocket:
                try:
                    payload = json.loads(raw_message)
                except json.JSONDecodeError:
                    continue

                msg_type = payload.get("type")

                # Real-time barge-in signal
                if msg_type == "interrupt":
                    logger.info("⚡ [INTERRUPT] Received barge-in interruption signal from caller!")
                    interrupted_event.set()
                    if active_turn_task and not active_turn_task.done():
                        active_turn_task.cancel()
                    # Acknowledge interrupt to client immediately
                    await websocket.send(json.dumps({"type": "interrupted"}))
                    continue

                # Audio turn message
                if msg_type == "audio":
                    b64_data = payload.get("data", "")
                    if b64_data:
                        raw_pcm = base64.b64decode(b64_data)
                        await audio_queue.put(raw_pcm)

            # Cleanup worker on disconnect
            worker_task.cancel()
            try:
                await worker_task
            except asyncio.CancelledError:
                pass

    except Exception as exc:
        if not isinstance(exc, (asyncio.CancelledError,)):
            logger.info("Client session ended: %s (%s)", client_addr, exc)
    finally:
        logger.info("Client disconnected: %s", client_addr)


async def start_server(host: str = _HOST, port: int = _PORT):
    """Start the WebSocket server instance and return the server object."""
    import websockets

    server = await websockets.serve(
        handle_client,
        host=host,
        port=port,
        max_size=32 * 1024 * 1024,  # 32 MB frame limit
        ping_interval=None,         # Disables keepalive ping timeout
    )
    logger.info("=" * 60)
    logger.info("🚀 Gemini Live Native WebSocket Voice Agent Started")
    logger.info("  • Model: %s", _GEMINI_MODEL)
    logger.info("  • Voice: %s", _VOICE_NAME)
    logger.info("  • Address: ws://%s:%d", host, port)
    logger.info("  • Architecture: Pure Native Audio (No STT/TTS pipeline)")
    logger.info("=" * 60)
    return server


async def main() -> None:
    server = await start_server()
    stop_event = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except (NotImplementedError, AttributeError):
            pass

    try:
        await stop_event.wait()
    except (asyncio.CancelledError, KeyboardInterrupt):
        pass
    finally:
        logger.info("Shutting down WebSocket Voice Agent server...")
        server.close()
        await server.wait_closed()
        logger.info("Server closed successfully.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Server terminated by user.")
