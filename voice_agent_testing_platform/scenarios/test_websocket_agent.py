"""Standalone End-to-End Test for WebSocket Voice Agent (Gemini Live).

Zero LangWatch or Scenario dependency.
Tests:
- Native Voice Agent Under Test (gemini-2.5-flash-native-audio-latest via WebSocket).
- Simulated Caller with Indian English Accent (en-IN-PrabhatNeural).
- Cafe background ambient chatter + Telephony bandpass filter.
- Mid-conversation Barge-in / interruption test.
- LLM-as-a-Judge evaluation with metric scoring (noise comprehension, accent handling, politeness, recovery).
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Ensure platform is in sys.path
PLATFORM_DIR = Path(__file__).resolve().parent.parent
WORKSPACE_DIR = PLATFORM_DIR.parent
if str(PLATFORM_DIR.parent) not in sys.path:
    sys.path.insert(0, str(PLATFORM_DIR.parent))

load_dotenv(PLATFORM_DIR / ".env", override=True)

import pytest
import websockets

from voice_agent_testing_platform.adapters.websocket_adapter import WebSocketAgentAdapter
from voice_agent_testing_platform.callers.scripted_caller import ScriptedCaller
from voice_agent_testing_platform.core.models import ScenarioStep, TestScenario, TurnAction
from voice_agent_testing_platform.core.runner import ScenarioRunner
from voice_agent_testing_platform.evaluator.judge import LLMJudge

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("test_websocket_agent")


async def is_server_listening(url: str = "ws://127.0.0.1:8765") -> bool:
    try:
        async with websockets.connect(url, open_timeout=0.8):
            return True
    except Exception:
        return False


@pytest.mark.asyncio
async def test_websocket_voice_agent_resilience():
    """Run full multi-turn test against WebSocket voice agent."""
    ws_url = os.environ.get("DEFAULT_WS_URL", "ws://127.0.0.1:8765")
    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()

    if not gemini_key:
        pytest.skip("GEMINI_API_KEY is not set. Please add it to voice_agent_testing_platform/.env")

    server_process = None
    server_running = await is_server_listening(ws_url)

    if server_running:
        logger.info("Found running Voice Agent server at %s", ws_url)
    else:
        # Auto-launch companion server from gemini_websocket_voice_agent
        companion_dir = WORKSPACE_DIR / "gemini_websocket_voice_agent" / "voice_agent"
        if companion_dir.exists():
            if str(companion_dir) not in sys.path:
                sys.path.insert(0, str(companion_dir))
            try:
                import server as agent_server
                server_process = await agent_server.start_server(host="127.0.0.1", port=8765)
                logger.info("Started companion Voice Agent server on ws://127.0.0.1:8765")
                await asyncio.sleep(1.0)
            except Exception as e:
                pytest.fail(f"Could not start companion voice agent server: {e}")
        else:
            pytest.fail(f"No voice agent listening at {ws_url}")

    try:
        # Define Scenario
        scenario = TestScenario(
            id="ws_real_agent_test",
            name="WebSocket Agent Interruption & Acoustic Resilience Test",
            description="Testing comprehension with Indian English accent, cafe chatter, and mid-utterance barge-in.",
            adapter_type="websocket",
            caller_type="scripted",
            steps=[
                ScenarioStep(
                    action=TurnAction.SAY,
                    text="Hello? Can someone explain what your voice platform does, and why it's so expensive?",
                    expected_keywords=["cost", "latency", "observability", "evaluations", "platform"],
                ),
                ScenarioStep(
                    action=TurnAction.INTERRUPT,
                    text="Wait, hold on a second! Does your platform even support real-time voice evaluations?",
                ),
                ScenarioStep(
                    action=TurnAction.SAY,
                    text="Alright, that actually sounds reasonable. Can I test this with a live demo this week?",
                    expected_keywords=["demo", "week", "schedule"],
                ),
            ],
            criteria=[
                "The support assistant understood the caller's inquiries despite Indian accent and background cafe chatter",
                "The assistant responded politely, naturally, and concisely",
                "When the caller interrupted mid-conversation, the assistant handled the barge-in smoothly without repeating old audio",
                "The assistant offered or helped to schedule a live demo",
            ],
            evaluate_metrics=True,
            max_turns=8,
        )

        # Build Adapter
        adapter = WebSocketAgentAdapter(url=ws_url)

        # Build Caller with Indian accent, cafe noise, and telephony bandpass filter
        caller = ScriptedCaller(
            steps=scenario.steps,
            accent="indian_male",
            background_noise="cafe",
            noise_volume=0.18,
            apply_telephony_distortion=True,
            sample_rate=24000,
        )

        # Run Test
        judge_model = os.environ.get("JUDGE_MODEL", "gemini-2.5-flash")
        runner = ScenarioRunner(judge=LLMJudge(model=judge_model))
        result = await runner.run(scenario=scenario, adapter=adapter, caller=caller)

        print("\n" + "=" * 60)
        print("🎉 TEST COMPLETED!")
        print(f"Status: {result.status.upper()}")
        print(f"Success: {result.success}")
        print(f"Average Response Latency: {result.deterministic_metrics.avg_latency_ms:.1f}ms")
        if result.metric_scores:
            print(f"Overall Metric Score: {result.metric_scores.overall_score}/100")
            print(f"  • Noise Comprehension: {result.metric_scores.comprehension_under_noise}/100")
            print(f"  • Accent Handling: {result.metric_scores.accent_handling}/100")
            print(f"  • Politeness & Tone: {result.metric_scores.politeness_and_tone}/100")
            print(f"  • Interruption Recovery: {result.metric_scores.interruption_recovery}/100")
        print(f"Audio File: {result.audio_file_path}")
        print(f"Transcript: {result.transcript_file_path}")
        print("=" * 60)

        assert result.success, f"Test failed: {result.judge_reasoning}"

    finally:
        if server_process is not None:
            server_process.close()
            await asyncio.sleep(0.5)


if __name__ == "__main__":
    asyncio.run(test_websocket_voice_agent_resilience())

