"""End-to-End Test for IVR & Telephony Voice Agent using Mock Telephony Adapter.

Zero external telecom setup. Zero cost.
Tests:
- Local simulated telephone switch.
- Automated IVR menu greeting.
- Keypad DTMF tone detection and routing.
- Telecom bandpass filtering (300Hz - 3.4kHz).
- LLM Judge evaluation.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

PLATFORM_DIR = Path(__file__).resolve().parent.parent
if str(PLATFORM_DIR.parent) not in sys.path:
    sys.path.insert(0, str(PLATFORM_DIR.parent))

load_dotenv(PLATFORM_DIR / ".env", override=True)

import pytest

from voice_agent_testing_platform.adapters.telephony.mock_telephony_adapter import MockTelephonyAdapter
from voice_agent_testing_platform.callers.scripted_caller import ScriptedCaller
from voice_agent_testing_platform.core.models import ScenarioStep, TestScenario, TurnAction
from voice_agent_testing_platform.core.runner import ScenarioRunner
from voice_agent_testing_platform.evaluator.judge import LLMJudge

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("test_telephony_mock")


@pytest.mark.asyncio
async def test_mock_telephony_ivr_flow():
    """Test IVR greeting, DTMF tone response, and telephone audio codecs."""
    scenario = TestScenario(
        id="mock_telephony_ivr_test",
        name="Telephony IVR Menu & DTMF Tone Verification",
        description="Verify telephone IVR greeting, DTMF tone 1 for Support, and audio fidelity.",
        adapter_type="mock_telephony",
        caller_type="scripted",
        steps=[
            ScenarioStep(action=TurnAction.WAIT, text="(Listening to IVR Greeting)"),
            ScenarioStep(action=TurnAction.DTMF, dtmf_digit="1", text="Pressing 1 for Support"),
            ScenarioStep(action=TurnAction.SAY, text="Hi, I would like to check my account status."),
        ],
        criteria=[
            "The IVR system delivered a clear telephone greeting",
            "The system processed the caller DTMF keypad press accurately",
            "The customer service agent responded appropriately to the account query",
        ],
        evaluate_metrics=True,
        max_turns=6,
    )

    adapter = MockTelephonyAdapter()
    caller = ScriptedCaller(
        steps=scenario.steps,
        accent="us_female",
        background_noise="static",
        noise_volume=0.04,
        apply_telephony_distortion=True,
        sample_rate=24000,
    )

    judge_model = os.environ.get("JUDGE_MODEL", "gemini-2.5-flash")
    runner = ScenarioRunner(judge=LLMJudge(model=judge_model))
    result = await runner.run(scenario=scenario, adapter=adapter, caller=caller)

    print("\n" + "=" * 60)
    print("📞 MOCK TELEPHONY TEST COMPLETED!")
    print(f"Status: {result.status.upper()}")
    print(f"Success: {result.success}")
    print(f"DTMF Tested: {result.deterministic_metrics.dtmf_tested} | Matched: {result.deterministic_metrics.dtmf_matched}")
    if result.metric_scores:
        print(f"Overall Metric Score: {result.metric_scores.overall_score}/100")
        print(f"  • Politeness & Tone: {result.metric_scores.politeness_and_tone}/100")
    print(f"Audio File: {result.audio_file_path}")
    print(f"Transcript: {result.transcript_file_path}")
    print("=" * 60)

    assert result.success, f"Test failed: {result.judge_reasoning}"


if __name__ == "__main__":
    asyncio.run(test_mock_telephony_ivr_flow())

