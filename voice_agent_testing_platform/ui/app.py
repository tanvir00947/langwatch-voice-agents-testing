"""FastAPI Web UI Server for Voice Agent & Telephony Testing Platform.

Designed for QA Testers:
- Graphical scenario runner & configurator (WebSocket, Twilio, Telnyx, Mock Telephony).
- Real-time turn-by-turn conversation streaming over WebSocket.
- Visual audio player, metric score gauges, and LLM Judge rubric breakdown.
- Past test runs history and report downloads.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure Windows terminal handles UTF-8 cleanly
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
os.environ["PYTHONIOENCODING"] = "utf-8"

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from dotenv import load_dotenv

# Load local environment
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env", override=True)

from voice_agent_testing_platform.adapters.websocket_adapter import WebSocketAgentAdapter
from voice_agent_testing_platform.adapters.telephony.twilio_adapter import TwilioMediaStreamAdapter
from voice_agent_testing_platform.adapters.telephony.telnyx_adapter import TelnyxMediaStreamAdapter
from voice_agent_testing_platform.adapters.telephony.mock_telephony_adapter import MockTelephonyAdapter
from voice_agent_testing_platform.callers.scripted_caller import ScriptedCaller
from voice_agent_testing_platform.callers.dynamic_caller import DynamicAICaller
from voice_agent_testing_platform.core.models import (
    ScenarioStep,
    TestResult,
    TestScenario,
    Turn,
    TurnAction,
)
from voice_agent_testing_platform.core.runner import ScenarioRunner
from voice_agent_testing_platform.core.speech_engine import ACCENT_PRESETS
from voice_agent_testing_platform.evaluator.judge import LLMJudge

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("platform.ui")

app = FastAPI(title="Voice Agent Testing Platform", version="1.0.0")

# Mount static and templates
STATIC_DIR = Path(__file__).resolve().parent / "static"
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
OUTPUTS_DIR = BASE_DIR / "outputs"
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# WebSocket live test broadcast clients
active_websockets: List[WebSocket] = []
is_test_running = False
current_test_task: Optional[asyncio.Task] = None


class RunTestRequest(BaseModel):
    scenario_id: str = "custom_test"
    scenario_name: str = "Voice Agent Quality Test"
    adapter_type: str = "websocket"  # "websocket", "twilio", "telnyx", "mock_telephony"
    target_url: str = "ws://127.0.0.1:8765"
    caller_type: str = "scripted"  # "scripted", "dynamic"
    caller_accent: str = "us_male"
    background_noise: str = "none"  # "none", "cafe", "office", "static"
    noise_volume: float = 0.15
    apply_telephony_filter: bool = True
    persona: str = "A skeptical customer asking about pricing and requesting a live demo."
    goal: str = "Confirm features and schedule a demo this week."
    custom_script: List[Dict[str, Any]] = []
    criteria: List[str] = []
    evaluate_metrics: bool = True
    max_turns: int = 8


# Preset templates for testers
PRESET_SCENARIOS = [
    {
        "id": "ws_barge_in_resilience",
        "name": "WebSocket Agent: Resilience & Barge-in Test",
        "description": "Tests handling of skeptical customer questions, cafe noise, and barge-in interruption.",
        "adapter_type": "websocket",
        "target_url": "ws://127.0.0.1:8765",
        "caller_type": "scripted",
        "caller_accent": "indian_male",
        "background_noise": "cafe",
        "noise_volume": 0.18,
        "apply_telephony_filter": True,
        "custom_script": [
            {"action": "say", "text": "Hello? Can someone explain what your voice platform does, and why it's so expensive?"},
            {"action": "interrupt", "text": "Wait, hold on a second! Does your platform even support real-time voice evaluations?"},
            {"action": "say", "text": "Alright, that sounds reasonable. Can I test this with a live demo this week?"},
        ],
        "criteria": [
            "The assistant understood the caller's inquiries despite cafe background noise and accent",
            "The assistant responded politely, naturally, and concisely",
            "When interrupted mid-conversation, the assistant handled the barge-in smoothly without repeating old audio",
            "The assistant addressed skepticism and offered or helped to schedule a live demo",
        ],
        "evaluate_metrics": True,
        "max_turns": 8,
    },
    {
        "id": "mock_telephony_ivr_dtmf",
        "name": "Mock Telephony: IVR Menu & DTMF Navigation",
        "description": "Zero-cost local phone test validating IVR greeting, DTMF tone handling, and telephone bandpass filtering.",
        "adapter_type": "mock_telephony",
        "target_url": "local://mock-ivr",
        "caller_type": "scripted",
        "caller_accent": "us_female",
        "background_noise": "static",
        "noise_volume": 0.05,
        "apply_telephony_filter": True,
        "custom_script": [
            {"action": "wait", "text": "(Listening to IVR greeting)"},
            {"action": "dtmf", "dtmf_digit": "1", "text": "Pressing keypad 1 for Support"},
            {"action": "say", "text": "Hi, I need help configuring my audio stream."},
        ],
        "criteria": [
            "The IVR system delivered a clear initial phone greeting",
            "The system accurately received and processed DTMF keypad tone 1",
            "The conversation proceeded naturally over telecom line quality",
        ],
        "evaluate_metrics": True,
        "max_turns": 6,
    },
    {
        "id": "dynamic_ai_customer_stress",
        "name": "Dynamic AI Caller: Multi-Turn Persona Stress Test",
        "description": "Autonomous AI persona challenging the voice agent dynamically with British accent and office noise.",
        "adapter_type": "websocket",
        "target_url": "ws://127.0.0.1:8765",
        "caller_type": "dynamic",
        "caller_accent": "british_male",
        "background_noise": "office",
        "noise_volume": 0.15,
        "apply_telephony_filter": True,
        "persona": "An impatient IT Director evaluating enterprise voice AI solutions.",
        "goal": "Verify whether the agent can answer technical architecture questions and schedule a pilot.",
        "custom_script": [],
        "criteria": [
            "The agent adapted professionally to the demanding caller persona",
            "The agent gave technically sound and concise spoken responses",
            "The agent maintained a polite, confident tone and worked towards scheduling next steps",
        ],
        "evaluate_metrics": True,
        "max_turns": 6,
    },
]


@app.get("/", response_class=HTMLResponse)
async def get_index(request: Request):
    """Render main tester dashboard."""
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "accents": ACCENT_PRESETS,
            "presets": PRESET_SCENARIOS,
        },
    )


@app.get("/api/presets")
async def get_presets():
    return PRESET_SCENARIOS


@app.get("/api/runs")
async def list_runs():
    """Return historical test runs stored in outputs directory."""
    runs = []
    for file in sorted(OUTPUTS_DIR.glob("run_*.json"), key=os.path.getmtime, reverse=True):
        try:
            with open(file, "r", encoding="utf-8") as f:
                runs.append(json.load(f))
        except Exception:
            pass
    return runs


@app.get("/api/audio/{filename}")
async def get_audio_file(filename: str):
    """Serve recorded test audio file (.wav)."""
    file_path = OUTPUTS_DIR / filename
    if file_path.exists():
        return FileResponse(file_path, media_type="audio/wav")
    return JSONResponse(status_code=404, content={"error": "File not found"})


@app.websocket("/ws/live")
async def websocket_live_endpoint(websocket: WebSocket):
    """WebSocket connection for real-time turn streaming to UI."""
    await websocket.accept()
    active_websockets.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        if websocket in active_websockets:
            active_websockets.remove(websocket)


async def broadcast_live_event(event_type: str, data: Any):
    """Send live turn updates and status messages to connected browser clients."""
    payload = json.dumps({"event": event_type, "data": data})
    for ws in list(active_websockets):
        try:
            await ws.send_text(payload)
        except Exception:
            if ws in active_websockets:
                active_websockets.remove(ws)


@app.post("/api/run")
async def start_test_run(req: RunTestRequest):
    """Trigger a new test run from the UI."""
    global is_test_running
    if is_test_running:
        return JSONResponse(status_code=400, content={"error": "A test run is already in progress."})

    is_test_running = True

    async def _execute():
        global is_test_running
        try:
            await broadcast_live_event("test_started", {"scenario_name": req.scenario_name})

            # 1. Build Adapter
            if req.adapter_type == "websocket":
                adapter = WebSocketAgentAdapter(url=req.target_url)
            elif req.adapter_type == "twilio":
                adapter = TwilioMediaStreamAdapter(url=req.target_url)
            elif req.adapter_type == "telnyx":
                adapter = TelnyxMediaStreamAdapter(url=req.target_url)
            elif req.adapter_type == "mock_telephony":
                adapter = MockTelephonyAdapter()
            else:
                adapter = WebSocketAgentAdapter(url=req.target_url)

            # 2. Build Steps
            steps = []
            for s in req.custom_script:
                action_str = s.get("action", "say").lower()
                action = TurnAction.SAY
                if action_str == "interrupt":
                    action = TurnAction.INTERRUPT
                elif action_str == "dtmf":
                    action = TurnAction.DTMF
                elif action_str == "wait":
                    action = TurnAction.WAIT

                steps.append(
                    ScenarioStep(
                        action=action,
                        text=s.get("text"),
                        dtmf_digit=s.get("dtmf_digit"),
                        expected_keywords=s.get("expected_keywords", []),
                        forbidden_keywords=s.get("forbidden_keywords", []),
                    )
                )

            # 3. Build Caller
            if req.caller_type == "dynamic":
                caller = DynamicAICaller(
                    persona=req.persona,
                    goal=req.goal,
                    accent=req.caller_accent,
                    background_noise=req.background_noise,
                    noise_volume=req.noise_volume,
                    apply_telephony_distortion=req.apply_telephony_filter,
                    should_interrupt_on_turn=3,
                )
            else:
                caller = ScriptedCaller(
                    steps=steps,
                    accent=req.caller_accent,
                    background_noise=req.background_noise,
                    noise_volume=req.noise_volume,
                    apply_telephony_distortion=req.apply_telephony_filter,
                )

            # 4. Turn Callback to stream turns live to UI
            def _on_turn(turn: Turn):
                asyncio.create_task(
                    broadcast_live_event(
                        "turn_update",
                        {
                            "turn_index": turn.turn_index,
                            "timestamp": turn.timestamp,
                            "role": turn.role.value,
                            "text": turn.text,
                            "latency_ms": turn.latency_ms,
                            "start_time_s": turn.start_time_s,
                            "end_time_s": turn.end_time_s,
                            "is_interruption": turn.is_interruption,
                            "dtmf_digits": turn.dtmf_digits,
                            "audio_duration": turn.audio_duration,
                        },
                    )
                )

            # 5. Build Scenario & Runner
            scenario = TestScenario(
                id=req.scenario_id,
                name=req.scenario_name,
                adapter_type=req.adapter_type,
                caller_type=req.caller_type,
                steps=steps,
                criteria=req.criteria,
                evaluate_metrics=req.evaluate_metrics,
                max_turns=req.max_turns,
            )

            judge_model = os.environ.get("JUDGE_MODEL", "gemini-3.5-flash-lite")
            judge = LLMJudge(model=judge_model)
            runner = ScenarioRunner(output_dir=OUTPUTS_DIR, judge=judge, on_turn_callback=_on_turn)

            # 6. Execute Test
            result = await runner.run(scenario=scenario, adapter=adapter, caller=caller)

            # Broadcast completion with dual waveform audio assets
            res_dict = result.model_dump()
            if result.audio_file_path:
                res_dict["audio_filename"] = Path(result.audio_file_path).name
            if result.caller_audio_path:
                res_dict["caller_audio_filename"] = Path(result.caller_audio_path).name
            if result.agent_audio_path:
                res_dict["agent_audio_filename"] = Path(result.agent_audio_path).name
            if result.stereo_audio_path:
                res_dict["stereo_audio_filename"] = Path(result.stereo_audio_path).name

            # Check if JSON file has peak data
            json_matches = sorted(OUTPUTS_DIR.glob(f"run_{scenario.id}_*.json"), key=os.path.getmtime, reverse=True)
            if json_matches:
                try:
                    with open(json_matches[0], "r", encoding="utf-8") as jf:
                        saved_meta = json.load(jf)
                        res_dict["caller_peaks"] = saved_meta.get("caller_peaks", [])
                        res_dict["agent_peaks"] = saved_meta.get("agent_peaks", [])
                        res_dict["total_duration_s"] = saved_meta.get("total_duration_s", 0.0)
                except Exception:
                    pass

            await broadcast_live_event("test_completed", res_dict)

        except Exception as exc:
            logger.error("Test execution failed: %s", exc, exc_info=True)
            await broadcast_live_event("test_error", {"error": str(exc)})
        finally:
            is_test_running = False

    asyncio.create_task(_execute())
    return {"status": "started", "scenario_name": req.scenario_name}
