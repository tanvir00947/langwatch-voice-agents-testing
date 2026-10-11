"""End-to-end audio agent vs audio agent test using LangWatch Scenario and Gemini.

- Caller: UserSimulatorAgent synthesizes real spoken voice audio (en-US-GuyNeural).
- Agent: Server transcribes audio (STT via Gemini) -> reasons (LLM via Gemini) -> speaks (TTS via en-US-AriaNeural).
- Judge: Evaluates the conversation conduct.
- Audio: Saves the complete, real two-party spoken conversation to mock_voice_agent/outputs/conversation.wav.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

# Prevent Windows console UnicodeEncodeError on cp1252
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pytest
from dotenv import load_dotenv

# Ensure local imports work
AGENT_DIR = Path(__file__).resolve().parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

# Load .env from mock_voice_agent/.env
_ENV_PATH = AGENT_DIR / ".env"
load_dotenv(_ENV_PATH, override=True)

import litellm
# Automatically retry on transient 503 high demand spikes
litellm.num_retries = 3

from tts_engine import synthesize_speech_pcm24k
import scenario
from scenario.voice.adapters.websocket import WebSocketAgentAdapter
from scenario.voice.tts import register_tts_provider
from protocol import JsonAudioWebSocketProtocol
from server import start_server

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("test_ws_agent")


# 1. Register a neural TTS synthesizer for the simulated caller (Guy voice)
async def _caller_tts_synth(text: str, voice_name: str) -> bytes:
    """Synthesize real spoken speech for the caller using en-US-GuyNeural."""
    return await synthesize_speech_pcm24k(text, voice="en-US-GuyNeural")

register_tts_provider("local", _caller_tts_synth)


async def check_server_already_running(url: str = "ws://127.0.0.1:8765") -> bool:
    """Check if a WebSocket server is already listening on the given URL."""
    import websockets
    try:
        async with websockets.connect(url, open_timeout=0.8):
            return True
    except Exception:
        return False


from typing import ClassVar
from scenario.voice.capabilities import AdapterCapabilities


class LargeFrameWebSocketAgentAdapter(WebSocketAgentAdapter):
    """WebSocket adapter configured with 32 MB frame limit and native interruption signal."""

    capabilities: ClassVar[AdapterCapabilities] = AdapterCapabilities(
        streaming_transcripts=False,
        native_vad=False,
        dtmf=False,
        interruption=True,  # Enables first-class interrupt signal (Twilio clear / native barge-in)
        input_formats=["pcm16/24000"],
        output_formats=["pcm16/24000"],
    )

    def __init__(self, url: str, protocol: Any):
        super().__init__(url=url, protocol=protocol)
        self.response_timeout = 90.0  # 90s budget for STT + LLM + TTS + audio effects

    async def connect(self) -> None:
        import websockets

        self._ws = await websockets.connect(
            self.url,
            max_size=32 * 1024 * 1024,  # 32 MB frame limit (websockets default is 1 MB)
            ping_interval=None,  # Disables keepalive ping timeout
        )

    async def interrupt(self) -> None:
        """Send native cancellation signal over WebSocket to cancel agent speech."""
        if self._ws is not None:
            import json
            await self._ws.send(json.dumps({"type": "interrupt"}))


@pytest.mark.asyncio
async def test_websocket_voice_agent():
    """Test the WebSocket Voice Agent using scenario.run() with Gemini."""
    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not gemini_key:
        pytest.skip(f"GEMINI_API_KEY is not set in {_ENV_PATH}. Please add your key to run this test.")

    # Configure Scenario's LLM model to use Gemini via LiteLLM
    gemini_model = os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite").strip()
    scenario.configure(default_model=f"gemini/{gemini_model}")
    os.environ["GEMINI_API_KEY"] = gemini_key

    # Initialize LangWatch for platform analytics and real-time visualization
    langwatch_key = os.environ.get("LANGWATCH_API_KEY", "").strip()
    if langwatch_key:
        import langwatch
        langwatch.setup(api_key=langwatch_key)
        os.environ["LANGWATCH_API_KEY"] = langwatch_key
        logger.info("[INFO] LangWatch platform analytics enabled with API key.")

    host = os.environ.get("WS_HOST", "127.0.0.1")
    port = int(os.environ.get("WS_PORT", "8765"))
    ws_url = f"ws://{host}:{port}"

    # Auto-detect if user already launched server.py in another terminal
    already_running = await check_server_already_running(ws_url)
    server = None

    if already_running:
        logger.info("[INFO] Detected existing server running on %s. Connecting directly...", ws_url)
    else:
        logger.info("[INFO] Starting internal WebSocket server on %s...", ws_url)
        server = await start_server(host=host, port=port)

    try:
        # 2. Instantiate the WebSocket adapter using our protocol and large frame buffer
        protocol = JsonAudioWebSocketProtocol()
        adapter = LargeFrameWebSocketAgentAdapter(
            url=ws_url,
            protocol=protocol,
        )

        # 3. Configure the multi-turn voice scenario with realistic background noise & telephony effects
        result = await scenario.run(
            name="Voice Agent Resilience: Background Noise & Telephony Quality",
            description="Testing agent robustness against realistic acoustic degradation: cafe background noise, telephone bandpass filtering, and outdoor street noise.",
            agents=[
                adapter,  # The WebSocket agent under test (STT -> LLM -> TTS)
                # User simulator with background noise & phone-line quality degradation
                scenario.UserSimulatorAgent(
                    persona="A customer calling while sitting in a busy coffee shop to ask about booking a demo for LangWatch AI",
                    voice="local/caller",
                    audio_effects=[
                        # 1. Background ambient cafe noise (voices, coffee shop environment)
                        scenario.effects.background_noise("cafe", volume=0.25),
                        # 2. Telephony bandpass filter (300Hz-3.4kHz) + compression (sounds like a real phone call)
                        scenario.effects.phone_quality(),
                        # 3. Subtle analog telephone static
                        scenario.effects.static(intensity=0.01),
                    ],
                ),
                scenario.JudgeAgent(
                    criteria=[
                        "The assistant understood the caller's request accurately despite the background noise and phone line quality",
                        "The assistant greeted and responded politely and concisely to the caller",
                        "When the caller interrupted mid-conversation to ask about self-hosting with Docker, the assistant seamlessly answered the interruption without confusion or repeating itself",
                        "The conversation was conducted smoothly without technical failures",
                    ]
                ),
            ],
            script=[
                # Turn 1: User calls from the cafe with ambient noise
                scenario.user("please explain langwatch ai"),
                scenario.agent(),
                # Turn 2: User barges in mid-utterance to ask a clarifying question!
                scenario.interrupt(
                    "Wait, sorry to interrupt!",
                    wait_for_speech_timeout = 2
                ),
                scenario.agent(),
                # Turn 3: User confirms and wraps up
                scenario.user(),
                scenario.agent(),
                # Judge evaluates performance under noisy real-world acoustic conditions AND barge-in handling
                scenario.judge(),
            ],
            max_turns=8,
        )

        print("\n" + "=" * 60)
        print("SCENARIO TEST COMPLETED (Fully Functional STT -> LLM -> TTS)!")
        print(f"Success: {result.success}")
        print(f"Reasoning:\n{result.reasoning}")

        # 4. Save the full conversation audio recording to disk
        output_dir = AGENT_DIR / "outputs"
        output_dir.mkdir(parents=True, exist_ok=True)
        from datetime import datetime

        # 1. Get the current date and time formatted safely for filenames
        # %Y = Year, %m = Month, %d = Day, %H = Hour, %M = Minute, %S = Second
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        wav_path = output_dir / f"conversation_{timestamp}.wav"

        if hasattr(result, "audio") and result.audio is not None:
            result.audio.save(str(wav_path))
            print(f"\n[AUDIO RECORDING SAVED]")
            print(f"File location: {wav_path}")
            print(f"Total duration: {getattr(result.audio, 'duration', 0):.2f} seconds")
            if getattr(result.audio, "segments", None):
                print(f"Audio segments: {len(result.audio.segments)} turns recorded")
        else:
            print("\n[NOTE] No audio stream attached to result.")

        if langwatch_key:
            print("\n" + "─" * 60)
            print("📊 VIEW YOUR ANALYTICS & SIMULATIONS IN LANGWATCH:")
            print("  • Simulations: https://app.langwatch.ai/simulations")
            print("  • Evaluations: https://app.langwatch.ai/evaluations")
            print("─" * 60)

        print("=" * 60)

        assert result.success, f"Test failed: {result.reasoning}"

    finally:
        # Gracefully stop the server only if we started it in this process
        if server is not None:
            server.close()
            await server.wait_closed()


if __name__ == "__main__":
    asyncio.run(test_websocket_voice_agent())
