"""End-to-end multi-turn Scenario test for Gemini Live WebSocket Voice Agent.

Architecture:
- Agent Under Test: Voice agent server over WebSocket (gemini-2.5-flash-native-audio-latest).
- Adversarial Caller: Adversarial voice agent (gemini-2.5-flash-native-audio-latest, voice: Puck).
- Judge: gemini-3.1-flash-lite evaluating conversation conduct, politeness, and interruption recovery.
- Zero separate STT + text LLM + TTS pipeline — real native voice agent vs native voice agent.
- Live Transcript: Recorded turn-by-turn to outputs/conversation_<timestamp>.txt.
- Audio Recording: Complete multi-party conversation saved to outputs/conversation_<timestamp>.wav.
- LangWatch Analytics: Traces and simulations streamed to https://app.langwatch.ai.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

# Ensure Windows terminal handles UTF-8 output cleanly
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
TEST_DIR = Path(__file__).resolve().parent
if str(TEST_DIR) not in sys.path:
    sys.path.insert(0, str(TEST_DIR))

# Load environment configuration from langwatch_test/.env
_ENV_PATH = TEST_DIR / ".env"
load_dotenv(_ENV_PATH, override=True)

import litellm
# Automatically retry on transient spikes
litellm.num_retries = 3

import scenario
from client_adapter import LargeFrameWebSocketAgentAdapter
from adversarial_agent import AdversarialGeminiLiveAgent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("test_voice_agent")


async def check_server_running(url: str = "ws://127.0.0.1:8765") -> bool:
    """Check if the WebSocket voice agent server is already running."""
    import websockets

    try:
        async with websockets.connect(url, open_timeout=1.0):
            return True
    except Exception:
        return False


@pytest.mark.asyncio
async def test_real_voice_agent_vs_voice_agent():
    """Run real native voice agent vs adversarial native voice agent test."""
    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not gemini_key:
        pytest.skip(f"GEMINI_API_KEY is not set in {_ENV_PATH}. Please provide a valid key.")

    # 1. Configure Scenario's default model for Judge reasoning (gemini-3.1-flash-lite)
    judge_model = os.environ.get("JUDGE_MODEL", "gemini-3.1-flash-lite").strip()
    scenario.configure(default_model=f"gemini/{judge_model}")
    os.environ["GEMINI_API_KEY"] = gemini_key

    # 2. Configure LangWatch platform analytics
    langwatch_key = os.environ.get("LANGWATCH_API_KEY", "").strip()
    if langwatch_key:
        import langwatch
        langwatch.setup(api_key=langwatch_key)
        os.environ["LANGWATCH_API_KEY"] = langwatch_key
        logger.info(" LangWatch platform analytics enabled with API key.")

    ws_url = os.environ.get("WS_URL", "ws://127.0.0.1:8765").strip()
    adversarial_model = os.environ.get("ADVERSARIAL_MODEL", "gemini-2.5-flash-native-audio-latest").strip()
    adversarial_voice = os.environ.get("ADVERSARIAL_VOICE", "Puck").strip()

    # 3. Check or launch WebSocket voice agent server
    server_process = None
    server_running = await check_server_running(ws_url)

    if server_running:
        logger.info(" Detected running Voice Agent server on %s. Connecting directly...", ws_url)
    else:
        # Auto-launch internal voice agent server from companion directory
        logger.info(" Server not running. Starting companion Voice Agent server from ../voice_agent/server.py...")
        companion_dir = TEST_DIR.parent / "voice_agent"
        if str(companion_dir) not in sys.path:
            sys.path.insert(0, str(companion_dir))
        try:
            import server as agent_server
            # Extract host and port
            from urllib.parse import urlparse
            parsed = urlparse(ws_url)
            host = parsed.hostname or "127.0.0.1"
            port = parsed.port or 8765
            server_process = await agent_server.start_server(host=host, port=port)
            logger.info(" Companion Voice Agent server started on ws://%s:%d.", host, port)
        except Exception as err:
            logger.error("Could not auto-start Voice Agent server: %s", err)
            pytest.fail(f"Voice agent server not reachable at {ws_url}. Please start voice_agent/server.py first.")

    try:
        # 4. Prepare output directories and transcript file
        output_dir = TEST_DIR / "outputs"
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        transcript_path = output_dir / f"conversation_{timestamp}.txt"
        wav_path = output_dir / f"conversation_{timestamp}.wav"

        # Initialize the real-time transcript file immediately with session header
        with open(transcript_path, "w", encoding="utf-8") as f:
            f.write("=" * 60 + "\n")
            f.write("REAL VOICE AGENT VS ADVERSARIAL VOICE AGENT TRANSCRIPT\n")
            f.write(f"Session Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"SUT Agent: WebSocket (gemini-2.5-flash-native-audio-latest)\n")
            f.write(f"Adversarial Caller: {adversarial_model} (Voice: {adversarial_voice})\n")
            f.write(f"Judge Model: {judge_model}\n")
            f.write(f"Audio File: {wav_path.name}\n")
            f.write("Architecture: Native Multimodal Voice (Zero STT+LLM+TTS pipeline)\n")
            f.write("=" * 60 + "\n\n")
            f.flush()

        logger.info(" Live transcript initialized at: %s", transcript_path)

        # 5. Instantiate WebSocket client adapter (SUT)
        client_adapter = LargeFrameWebSocketAgentAdapter(
            url=ws_url,
            transcript_path=transcript_path,
        )

        # 6. Instantiate Adversarial Voice Agent (Caller)
        caller_agent = AdversarialGeminiLiveAgent(
            model=adversarial_model,
            voice=adversarial_voice,
            api_key=gemini_key,
            transcript_path=transcript_path,
            audio_effects=[
                # Cafe background ambient chatter & coffee shop sounds
                scenario.effects.background_noise("cafe", volume=0.20),
                # Bandpass telephony filter (300Hz-3.4kHz) & phone compression
                scenario.effects.phone_quality(),
                # Subtle phone line static
                scenario.effects.static(intensity=0.01),
            ],
        )

        # 7. Configure and run the Scenario evaluation
        result = await scenario.run(
            name="Real Voice Agent vs Adversarial Voice Agent: Resilience & Interruption",
            description=(
                "Real native voice agent (WebSocket gemini-2.5-flash-native-audio-latest) vs "
                "adversarial native voice agent (gemini-2.5-flash-native-audio-latest). "
                "Testing handling of skeptical customer questions, cafe background noise, "
                "telephony distortion, and mid-conversation barge-in interruption."
            ),
            agents=[
                client_adapter,  # Agent Under Test (WebSocket Voice Agent)
                caller_agent,    # Adversarial Voice Agent (Caller)
                scenario.JudgeAgent(
                    criteria=[
                        "The support assistant understood the caller's inquiries despite background noise and phone line quality",
                        "The support assistant responded politely, naturally, and concisely",
                        "When the caller interrupted mid-conversation, the assistant handled the interruption smoothly without repeating itself",
                        "The assistant addressed the caller's skepticism and offered or helped to schedule a demo",
                        "The conversation was conducted smoothly without technical failures",
                    ]
                ),
            ],
            script=[
                # Turn 1: Adversarial caller asks a challenging opening question
                scenario.user("Hello? Can someone explain what LangWatch AI actually does, and why it's so expensive?"),
                # Turn 2: Support agent replies
                scenario.agent(),
                # Turn 3: Caller interrupts mid-utterance to challenge real-time voice latency!
                scenario.interrupt(
                    "Wait, hold on a second! Does LangWatch even support real-time voice evaluations?",
                    wait_for_speech_timeout=3.0,
                ),
                # Turn 4: Support agent recovers and responds to the barge-in
                scenario.agent(),
                # Turn 5: Caller follows up
                scenario.user("Alright, that actually sounds reasonable. Can I test this with a live demo this week?"),
                # Turn 6: Support agent answers and wraps up
                scenario.agent(),
                # Turn 7: Judge evaluates the complete multi-turn conversation
                scenario.judge(),
            ],
            max_turns=8,
        )

        print("\n" + "=" * 60)
        print("🎉 SCENARIO TEST COMPLETED (Real Voice Agent vs Voice Agent)!")
        print(f"Success: {result.success}")
        print(f"Reasoning:\n{result.reasoning}")

        # 8. Save the full multi-party audio recording to disk
        if hasattr(result, "audio") and result.audio is not None:
            result.audio.save(str(wav_path))
            print(f"\n[AUDIO RECORDING SAVED]")
            print(f"File location: {wav_path}")
            print(f"Total duration: {getattr(result.audio, 'duration', 0):.2f} seconds")
            if getattr(result.audio, "segments", None):
                print(f"Audio segments: {len(result.audio.segments)} turns recorded")
        else:
            print("\n[NOTE] No audio stream attached to result.")

        # 9. Finalize the real-time transcript file with completion footer
        with open(transcript_path, "a", encoding="utf-8") as f:
            f.write("=" * 60 + "\n")
            f.write(f"Session Finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Status: {'SUCCESS' if result.success else 'FAILED'}\n")
            f.write(f"Judge Evaluation ({judge_model}):\n{result.reasoning}\n")
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

        # Teardown caller session
        try:
            await caller_agent.disconnect()
        except Exception:
            pass

        assert result.success, f"Test failed: {result.reasoning}"

    finally:
        # Cleanly stop internal server if we started it
        if server_process is not None:
            server_process.close()
            try:
                await asyncio.wait_for(server_process.wait_closed(), timeout=2.0)
            except Exception:
                pass


if __name__ == "__main__":
    asyncio.run(test_real_voice_agent_vs_voice_agent())
