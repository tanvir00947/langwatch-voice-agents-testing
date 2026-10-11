import asyncio
import os
import sys
import math
import struct
import time
from pathlib import Path
from dotenv import load_dotenv
from google import genai
from google.genai import types
import pyaudio

# Ensure Windows terminal handles UTF-8 output cleanly without crashing on cp1252
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

# Audio Configuration
# Gemini Live expects 16kHz linear PCM input, and streams back 24kHz linear PCM audio
FORMAT = pyaudio.paInt16
CHANNELS = 1
INPUT_SAMPLE_RATE = 16000    # Mic input sample rate
OUTPUT_SAMPLE_RATE = 24000   # Gemini output sample rate
CHUNK_SIZE = 1024

# Environment Configuration
_ENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(_ENV_PATH, override=True)

api_key = os.environ.get("GEMINI_API_KEY", "").strip()
# Gemini Native Audio model for realtime bidirectional audio streaming
DEFAULT_LIVE_MODEL = "gemini-2.5-flash-native-audio-latest"
env_model = os.environ.get("GEMINI_MODEL", "").strip()
if env_model and ("native-audio" in env_model or "realtime" in env_model):
    model_name = env_model
else:
    model_name = DEFAULT_LIVE_MODEL

def calculate_rms(data: bytes) -> int:
    """Calculate RMS volume level of 16-bit PCM chunk to detect voice activity."""
    count = len(data) // 2
    if count == 0:
        return 0
    shorts = struct.unpack(f"<{count}h", data)
    sum_squares = sum(s * s for s in shorts)
    return int(math.sqrt(sum_squares / count))

def read_mic_blocking(mic_stream):
    """Synchronous helper function to be run safely inside a worker thread."""
    return mic_stream.read(CHUNK_SIZE, exception_on_overflow=False)

async def audio_input_stream(session, p):
    """Captures microphone audio and streams it to Gemini Live safely using worker threads."""
    print("🎙️  Opening microphone stream (16kHz)...")
    mic_stream = p.open(
        format=FORMAT,
        channels=CHANNELS,
        rate=INPUT_SAMPLE_RATE,
        input=True,
        frames_per_buffer=CHUNK_SIZE
    )
    print("🎤 Voice agent active. Microphone is live! Start speaking...\n")
    
    last_detected_time = 0.0
    chunks_sent = 0

    try:
        while True:
            # Offload blocking mic read to a thread
            data = await asyncio.to_thread(read_mic_blocking, mic_stream)
            if not data:
                await asyncio.sleep(0.01)
                continue

            # Check volume level for visual speech activity feedback
            volume = calculate_rms(data)
            now = time.time()
            if volume > 400 and (now - last_detected_time > 0.8):
                print(f"🎙️  [Audio detected - vol: {volume} - sending to Gemini...]")
                last_detected_time = now

            # Stream raw audio chunk with explicit sample rate metadata
            await session.send_realtime_input(
                media=types.Blob(data=data, mime_type=f"audio/pcm;rate={INPUT_SAMPLE_RATE}")
            )
            chunks_sent += 1
            
            # Yield control back to the event loop
            await asyncio.sleep(0.001)
    except asyncio.CancelledError:
        print(f"\n⏹️  Microphone stream stopped (sent {chunks_sent} chunks).")
    except Exception as e:
        print(f"\n❌ Microphone stream error: {e}", file=sys.stderr)
    finally:
        try:
            mic_stream.stop_stream()
            mic_stream.close()
        except Exception:
            pass

async def audio_output_stream(session, p):
    """Receives streaming audio chunks & transcriptions from Gemini Live and plays them back."""
    print(f"🔊 Opening speaker stream ({OUTPUT_SAMPLE_RATE}Hz)...")
    speaker_stream = p.open(
        format=FORMAT,
        channels=CHANNELS,
        rate=OUTPUT_SAMPLE_RATE,
        output=True,
        frames_per_buffer=CHUNK_SIZE
    )
    print("👂 Listening for Gemini responses...\n" + "-" * 50)
    
    first_model_chunk = True
    user_speaking = False

    try:
        # Continuously listen for incoming server events
        async for response in session.receive():
            server_content = response.server_content
            if server_content is None:
                continue

            # Display real-time transcription of what the user is saying
            if server_content.input_transcription and server_content.input_transcription.text:
                if not user_speaking:
                    print("\n👤 You: ", end="", flush=True)
                    user_speaking = True
                print(server_content.input_transcription.text, end="", flush=True)
                first_model_chunk = True

            # If user interrupted Gemini while speaking
            if server_content.interrupted:
                print("\n⚡ [Interrupted by user]")
                user_speaking = False
                first_model_chunk = True

            # Display real-time transcription of what Gemini is saying
            if server_content.output_transcription and server_content.output_transcription.text:
                if user_speaking:
                    user_speaking = False
                if first_model_chunk:
                    print("\n🤖 Gemini: ", end="", flush=True)
                    first_model_chunk = False
                print(server_content.output_transcription.text, end="", flush=True)

            # Play back incoming audio chunks
            model_turn = server_content.model_turn
            if model_turn:
                for part in model_turn.parts:
                    if part.inline_data and part.inline_data.data:
                        # Non-blocking speaker write to prevent stalling the asyncio loop
                        await asyncio.to_thread(speaker_stream.write, part.inline_data.data)

            # Turn completed indicator
            if server_content.turn_complete:
                user_speaking = False
                first_model_chunk = True
                print("\n\n✅ [Turn complete. Waiting for your next query...]\n" + "-" * 50)

    except asyncio.CancelledError:
        print("\n⏹️  Speaker stream stopped.")
    except Exception as e:
        print(f"\n❌ Audio output stream error: {e}", file=sys.stderr)
    finally:
        try:
            speaker_stream.stop_stream()
            speaker_stream.close()
        except Exception:
            pass

async def run_voice_agent():
    if not api_key:
        print("❌ Error: GEMINI_API_KEY environment variable not set in .env.", file=sys.stderr)
        return

    print("=" * 50)
    print(" Gemini Live Voice Agent")
    print(f" Model: {model_name}")
    print("=" * 50)
    print("🔄 Initializing client and connecting to Gemini Live API...")

    client = genai.Client(api_key=api_key)
    p = pyaudio.PyAudio()

    # Configure Live API for bidirectional audio and live speech-to-text transcriptions
    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        input_audio_transcription={},
        output_audio_transcription={},
    )

    try:
        async with client.aio.live.connect(model=model_name, config=config) as session:
            print(" Connected to Gemini Live successfully!")
            
            # Run input and output streams concurrently
            input_task = asyncio.create_task(audio_input_stream(session, p))
            output_task = asyncio.create_task(audio_output_stream(session, p))
            
            done, pending = await asyncio.wait(
                [input_task, output_task],
                return_when=asyncio.FIRST_EXCEPTION
            )
            for task in pending:
                task.cancel()
    except Exception as e:
        print(f"\n❌ Connection error: {e}", file=sys.stderr)
    finally:
        p.terminate()
        print("\n PyAudio terminated.")

if __name__ == "__main__":
    try:
        asyncio.run(run_voice_agent())
    except KeyboardInterrupt:
        print("\n Voice agent session closed by user.")

