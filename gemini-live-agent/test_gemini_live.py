"""End-to-end multi-turn Scenario test for Gemini Live Voice Agent.

- Agent: Real-time Gemini Live bidirectional native-audio stream (gemini-2.5-flash-native-audio-latest).
- Caller: UserSimulatorAgent synthesizing real voice with cafe background noise, telephony filter, & static.
- Barge-in: Tests real-time user interruption mid-utterance.
- Judge: Evaluates comprehension under acoustic noise, politeness, and interruption recovery.
- Live Transcript: Recorded turn-by-turn to gemini-live-agent/outputs/conversation_<timestamp>.txt.
- Audio Recording: Complete multi-party conversation saved to gemini-live-agent/outputs/conversation_<timestamp>.wav.
- LangWatch: Real-time traces and simulations streamed to https://app.langwatch.ai.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

# Prevent Windows console UnicodeEncodeError on cp1252
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
os.environ["PYTHONIOENCODING"] = "utf-8"

import pytest
from dotenv import load_dotenv

# Ensure local imports work
AGENT_DIR = Path(__file__).resolve().parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

# Load environment configuration from gemini-live-agent/.env
_ENV_PATH = AGENT_DIR / ".env"
load_dotenv(_ENV_PATH, override=True)

import litellm
# Automatically retry on transient spikes
litellm.num_retries = 3

import scenario
from scenario.voice.tts import register_tts_provider
from tts_engine import synthesize_speech_pcm24k
from adapter import GeminiLiveVoiceAgentAdapter

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("test_gemini_live")


# 1. Register local neural TTS synthesizer for the simulated caller
async def _caller_tts_synth(text: str, voice_name: str) -> bytes:
    """Synthesize real spoken speech for the caller using en-US-GuyNeural."""
    return await synthesize_speech_pcm24k(text, voice="en-US-GuyNeural")

register_tts_provider("local", _caller_tts_synth)


@pytest.mark.asyncio
async def test_gemini_live_voice_agent():
    """Test Gemini Live Native Audio agent using Scenario and LangWatch analytics."""
    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not gemini_key:
        pytest.skip(f"GEMINI_API_KEY is not set in {_ENV_PATH}. Please add your key to run this test.")

    # Configure Scenario default model for simulator & judge reasoning
    judge_model = os.environ.get("JUDGE_MODEL", "gemini-3.1-flash-lite").strip()
    scenario.configure(default_model=f"gemini/{judge_model}")
    os.environ["GEMINI_API_KEY"] = gemini_key

    # Initialize LangWatch for platform analytics and real-time visualization
    langwatch_key = os.environ.get("LANGWATCH_API_KEY", "").strip()
    if langwatch_key:
        import langwatch
        langwatch.setup(api_key=langwatch_key)
        os.environ["LANGWATCH_API_KEY"] = langwatch_key
        logger.info("[INFO] LangWatch platform analytics enabled with API key.")

    # Gemini Live Model
    live_model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-native-audio-latest").strip()
    logger.info("[INFO] Using Gemini Live model: %s", live_model)

    # Prepare output directory and filenames
    output_dir = AGENT_DIR / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    transcript_path = output_dir / f"conversation_{timestamp}.txt"
    wav_path = output_dir / f"conversation_{timestamp}.wav"

    # Initialize the real-time transcript file immediately with session header
    with open(transcript_path, "w", encoding="utf-8") as f:
        f.write("=" * 60 + "\n")
        f.write("GEMINI LIVE VOICE AGENT CONVERSATION TRANSCRIPT\n")
        f.write(f"Session Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Model: {live_model}\n")
        f.write(f"Audio File: {wav_path.name}\n")
        f.write("Mode: Real-time turn-by-turn native-audio streaming\n")
        f.write("=" * 60 + "\n\n")
        f.flush()

    logger.info("[TRANSCRIPT] Live transcript initialized at: %s", transcript_path)

    system_instruction = (
        "You are a friendly, concise, and professional voice assistant for LangWatch AI on a live phone call. "
        "Keep your responses natural and concise (1 to 2 short conversational sentences), as your speech "
        "is spoken directly to the caller over the phone. Warmly assist the caller with LangWatch questions."
    )

    # 2. Instantiate Gemini Live voice adapter
    adapter = GeminiLiveVoiceAgentAdapter(
        model=live_model,
        voice="Algieba",
        system_instruction=system_instruction,
        api_key=gemini_key,
        transcript_path=transcript_path,
    )

    # 3. Configure the multi-turn voice scenario with realistic acoustic degradation and barge-in
    result = await scenario.run(
        name="Gemini Live Voice Agent: Acoustic Resilience & Barge-in Test",
        description="Testing Gemini Live native audio agent robustness against cafe background noise, telephone audio filtering, and mid-conversation barge-in interruptions.",
        agents=[
            adapter,  # The Gemini Live agent under test
            # User simulator with realistic cafe background noise & phone-line quality degradation
            scenario.UserSimulatorAgent(
                persona="A customer calling from a coffee shop to ask about LangWatch AI and book a demo",
                voice="local/caller",
                audio_effects=[
                    # 1. Background cafe ambient noise (coffee machine, chatter)
                    scenario.effects.background_noise("cafe", volume=0.20),
                    # 2. Telephony bandpass filter (300Hz-3.4kHz) + phone compression
                    scenario.effects.phone_quality(),
                    # 3. Subtle telephone line static
                    scenario.effects.static(intensity=0.01),
                ],
            ),
            scenario.JudgeAgent(
                criteria=[
                    "The assistant understood the caller's inquiries accurately despite the background noise and phone line degradation",
                    "The assistant greeted and responded politely, naturally, and concisely",
                    "When the caller interrupted mid-conversation, the assistant stopped and addressed the interruption politely",
                    "The assistant offered or helped to schedule a demo when asked",
                    "The conversation was conducted smoothly without technical failures",
                ]
            ),
        ],
        script=[
            # Turn 1: User calls from the cafe with ambient noise
            scenario.user("Hello, could you explain what LangWatch AI is?"),
            # Caller barges in mid-speech while the agent is speaking!
            scenario.interrupt(
                "Wait, sorry to interrupt! Does LangWatch support real-time voice evaluations?",
                wait_for_speech_timeout=3.0,
            ),
            # Agent finishes addressing the interruption
            scenario.agent(),
            # Turn 2: User confirms and wraps up
            scenario.user("That sounds great! Can you help me schedule a demo for this week?"),
            scenario.agent(),
            # Judge evaluates multi-turn resilience, acoustic robustness, and barge-in handling
            scenario.judge(),
        ],
        max_turns=8,
    )

    print("\n" + "=" * 60)
    print("GEMINI LIVE SCENARIO TEST COMPLETED!")
    print(f"Success: {result.success}")
    print(f"Reasoning:\n{result.reasoning}")

    # 4. Save the full conversation audio recording to disk
    if hasattr(result, "audio") and result.audio is not None:
        result.audio.save(str(wav_path))
        print(f"\n[AUDIO RECORDING SAVED]")
        print(f"File location: {wav_path}")
        print(f"Total duration: {getattr(result.audio, 'duration', 0):.2f} seconds")
        if getattr(result.audio, "segments", None):
            print(f"Audio segments: {len(result.audio.segments)} turns recorded")
    else:
        print("\n[NOTE] No audio stream attached to result.")

    # 5. Finalize the real-time transcript file with completion footer
    with open(transcript_path, "a", encoding="utf-8") as f:
        f.write("=" * 60 + "\n")
        f.write(f"Session Finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Status: {'SUCCESS' if result.success else 'FAILED'}\n")
        f.write(f"Judge Evaluation:\n{result.reasoning}\n")
        f.write("=" * 60 + "\n")
        f.flush()

    print(f"\n[REAL-TIME TRANSCRIPT SAVED]")
    print(f"File location: {transcript_path}")
    print("\n--- TRANSCRIPT CONTENT ---")
    try:
        with open(transcript_path, "r", encoding="utf-8") as f:
            print(f.read())
    except Exception as e:
        logger.warning("Could not display transcript file: %s", e)
    print("---------------------------\n")

    if langwatch_key:
        print("\n" + "─" * 60)
        print("📊 VIEW YOUR ANALYTICS & SIMULATIONS IN LANGWATCH:")
        print("  • Simulations: https://app.langwatch.ai/simulations")
        print("  • Evaluations: https://app.langwatch.ai/evaluations")
        print("─" * 60)

    print("=" * 60)

    assert result.success, f"Test failed: {result.reasoning}"


if __name__ == "__main__":
    asyncio.run(test_gemini_live_voice_agent())
