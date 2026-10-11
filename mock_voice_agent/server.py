"""Fully functional WebSocket Voice Agent powered by STT -> LLM -> TTS.

Pipeline:
1. STT (Speech-to-Text): Transcribes incoming PCM16 audio using Google Gemini multimodal audio.
2. LLM (Reasoning): Queries Google Gemini with conversation history to generate a natural response.
3. TTS (Text-to-Speech): Synthesizes the agent's reply into canonical 24kHz PCM16 audio using neural TTS.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Ensure local imports work
current_dir = Path(__file__).resolve().parent
if str(current_dir) not in sys.path:
    sys.path.insert(0, str(current_dir))

# Load .env from this directory
_ENV_PATH = current_dir / ".env"
load_dotenv(_ENV_PATH, override=True)

from tts_engine import synthesize_speech_pcm24k, pcm16_to_wav_bytes

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ws_voice_agent.server")

# Gemini Configuration
_GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
_GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash").strip()

if not _GEMINI_API_KEY:
    logger.error("GEMINI_API_KEY is not set in %s! The server requires a Gemini API key.", _ENV_PATH)
    sys.exit(1)

from google import genai
from google.genai import types

_GEMINI_CLIENT = genai.Client(api_key=_GEMINI_API_KEY)
logger.info("Gemini client initialized with model: %s", _GEMINI_MODEL)


# --------------------------------------------------------------------------- #
# 1. STT (Speech-to-Text) using Gemini Multimodal Audio
# --------------------------------------------------------------------------- #
async def stt_transcribe_audio(incoming_pcm: bytes) -> str:
    """Transcribe raw PCM16 24kHz audio into text using Google Gemini."""
    if not incoming_pcm or len(incoming_pcm) < 480:  # less than 10ms
        return ""

    # Wrap raw PCM16 bytes in standard WAV container
    wav_bytes = pcm16_to_wav_bytes(incoming_pcm, sample_rate=24000)

    loop = asyncio.get_running_loop()
    try:
        response = await loop.run_in_executor(
            None,
            lambda: _GEMINI_CLIENT.models.generate_content(
                model=_GEMINI_MODEL,
                contents=[
                    types.Part.from_bytes(data=wav_bytes, mime_type="audio/wav"),
                    (
                        "You are an accurate audio transcriber. Listen to the audio and transcribe "
                        "what is spoken verbatim. Output ONLY the transcription text. "
                        "Do not include any commentary, explanations, or quotes."
                    ),
                ],
            ),
        )
        transcript = response.text.strip() if response.text else ""
        logger.info("[STT] Transcribed caller audio: '%s'", transcript)
        return transcript
    except Exception as exc:
        logger.error("[STT] Transcription error: %s", exc)
        return ""


# --------------------------------------------------------------------------- #
# 2. LLM (Conversational Reasoning) using Gemini
# --------------------------------------------------------------------------- #
async def llm_generate_reply(caller_text: str, history: list[dict]) -> str:
    """Generate agent reply text using Gemini based on conversation history."""
    system_prompt = (
        "You are a helpful, courteous customer support voice agent for LangWatch AI on a live phone call. "
        "When a caller asks to book a demo, warmly assist them and offer to take their preferred date and time. "
        # "CRITICAL INSTRUCTION: Keep your response strictly under 25 words (1 to 2 short conversational sentences). "
        # "Do not output long bullet lists or monologues, as your output is spoken directly to the caller over the phone."
    )

    # Format dialogue history for context
    dialogue_context = ""
    for turn in history[-6:]:  # Keep last 3 turns
        role = "Caller" if turn["role"] == "user" else "Agent"
        dialogue_context += f"{role}: {turn['content']}\n"

    prompt = (
        f"{system_prompt}\n\n"
        f"Conversation History:\n{dialogue_context}\n"
        f"Caller: {caller_text}\n"
        f"Agent:"
    )

    loop = asyncio.get_running_loop()
    try:
        response = await loop.run_in_executor(
            None,
            lambda: _GEMINI_CLIENT.models.generate_content(
                model=_GEMINI_MODEL,
                contents=prompt,
            ),
        )
        reply = response.text.strip().replace("\n", " ")
        logger.info("[LLM] Agent generated reply: '%s'", reply)
        return reply
    except Exception as exc:
        logger.error("[LLM] Generation error: %s", exc)
        return "I apologize, I am having a moment of trouble processing that. Could you please repeat?"


# --------------------------------------------------------------------------- #
# 3. TTS (Text-to-Speech) using Neural Synthesis
# --------------------------------------------------------------------------- #
async def tts_synthesize_audio(agent_reply_text: str) -> bytes:
    """Synthesize agent text into canonical PCM16 24kHz audio."""
    pcm_audio = await synthesize_speech_pcm24k(
        text=agent_reply_text,
        voice="en-US-AriaNeural",  # Clear, natural customer service voice
    )
    logger.info("[TTS] Synthesized %d bytes of PCM16 24kHz speech", len(pcm_audio))
    return pcm_audio


# --------------------------------------------------------------------------- #
# WebSocket Connection Handler
# --------------------------------------------------------------------------- #
async def handle_client(websocket) -> None:
    """Handle an incoming WebSocket connection and process multi-turn voice turns."""
    client_ip = websocket.remote_address
    logger.info("New voice client connected: %s", client_ip)

    # Session state: conversation history across turns
    history: list[dict] = []
    turn_count = 0
    audio_queue: asyncio.Queue[dict] = asyncio.Queue()
    speech_cancel_event = asyncio.Event()

    async def worker():
        nonlocal turn_count
        while True:
            data = await audio_queue.get()
            speech_cancel_event.clear()
            turn_count += 1

            b64_audio = data.get("data", "")
            incoming_pcm = base64.b64decode(b64_audio)
            logger.info("--- Starting Voice Turn #%d (%d bytes PCM) ---", turn_count, len(incoming_pcm))

            # Step 1: STT (Speech-to-Text)
            caller_text = await stt_transcribe_audio(incoming_pcm)
            if not caller_text:
                caller_text = "Hello?"

            if speech_cancel_event.is_set():
                logger.info("[BARGE-IN] Turn #%d was interrupted during STT; dropping.", turn_count)
                audio_queue.task_done()
                continue

            # Step 2: LLM (Reasoning with history)
            agent_reply = await llm_generate_reply(caller_text, history)
            history.append({"role": "user", "content": caller_text})
            history.append({"role": "assistant", "content": agent_reply})

            if speech_cancel_event.is_set():
                logger.info("[BARGE-IN] Turn #%d was interrupted during LLM; dropping.", turn_count)
                audio_queue.task_done()
                continue

            # Step 3: TTS (Text-to-Speech)
            response_pcm = await tts_synthesize_audio(agent_reply)

            # Stream audio in chunks so caller barge-in can cut the speech short mid-utterance
            chunk_size = 24000  # 0.5s chunk of 24kHz PCM16 audio
            total_bytes = len(response_pcm)
            was_interrupted = False

            for offset in range(0, total_bytes, chunk_size):
                if speech_cancel_event.is_set():
                    logger.info("[BARGE-IN] Agent cut off mid-speech at byte %d / %d!", offset, total_bytes)
                    was_interrupted = True
                    break

                chunk_bytes = response_pcm[offset : offset + chunk_size]
                response_msg = {
                    "type": "audio",
                    "data": base64.b64encode(chunk_bytes).decode("utf-8"),
                }
                await websocket.send(json.dumps(response_msg))
                if offset + chunk_size < total_bytes:
                    await asyncio.sleep(0.12)  # slight pacing so client can hear and barge in

            if not was_interrupted:
                logger.info("--- Finished Voice Turn #%d: All audio chunks sent ---", turn_count)

            audio_queue.task_done()

    worker_task = asyncio.create_task(worker())

    try:
        async for message in websocket:
            if not isinstance(message, str):
                logger.warning("Received binary frame, ignoring (expected JSON)")
                continue

            try:
                data = json.loads(message)
            except json.JSONDecodeError:
                logger.warning("Invalid JSON received: %s", message[:100])
                continue

            msg_type = data.get("type")

            if msg_type == "interrupt":
                logger.info("[BARGE-IN] Received native interrupt signal from client! Cancelling agent speech.")
                speech_cancel_event.set()

            elif msg_type == "audio":
                # Incoming audio immediately cancels agent speech (VAD / acoustic barge-in)
                speech_cancel_event.set()
                await audio_queue.put(data)

            elif msg_type == "ping":
                await websocket.send(json.dumps({"type": "pong"}))

    except Exception as exc:
        logger.info("Connection closed with %s (%r)", client_ip, exc)
    finally:
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass
        logger.info("Voice client disconnected: %s", client_ip)


async def start_server(host: str | None = None, port: int | None = None):
    """Start the WebSocket Voice Agent server."""
    import websockets

    host = host or os.environ.get("WS_HOST", "127.0.0.1")
    port = port or int(os.environ.get("WS_PORT", "8765"))

    logger.info("Starting fully functional WebSocket Voice Agent on ws://%s:%d ...", host, port)
    server = await websockets.serve(
        handle_client,
        host,
        port,
        max_size=32 * 1024 * 1024,  # 32 MB frame limit (prevents 1009 frame too big errors)
        ping_interval=None,  # Disables keepalive ping timeout during heavy inference
    )
    logger.info("Voice Agent Server is listening on ws://%s:%d", host, port)
    return server


if __name__ == "__main__":
    async def main():
        server = await start_server()
        try:
            await asyncio.Future()  # run forever
        except KeyboardInterrupt:
            logger.info("Shutting down voice server...")
            server.close()
            await server.wait_closed()

    asyncio.run(main())
