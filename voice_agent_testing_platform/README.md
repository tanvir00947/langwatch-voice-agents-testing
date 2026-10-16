# 🎙️ Voice Agent & IVA/IVR Testing Platform

A **generic, vendor-independent testing platform** for Voice Agents, Conversational AI, and IVA/IVR phone systems.

Built with **Zero Dependency on LangWatch or Scenario**. Completely self-contained, modular, and equipped with a **Tester Web Dashboard**, multi-protocol adapters, multi-accent callers, and hybrid evaluations.

---

## 🌟 Key Highlights

- **Zero LangWatch Dependency**: No external subscription, proprietary lock-in, or telemetry leaks. All evaluation, audio synthesis, and metric scoring run directly via open standard protocols and direct LLM calls (e.g. Gemini 2.5 Flash / LiteLLM).
- **Multi-Protocol Adapters**:
  - 🌐 **WebSocket Adapter**: Large 32MB frame buffers, JSON Base64 audio streaming, native barge-in interruptions, and millisecond latency telemetry.
  - 📞 **Twilio Media Streams**: Bidirectional G.711 mu-law (8kHz) streaming, Twilio event handling (`connected`, `start`, `media`, `dtmf`, `clear`, `stop`), and automated carrier-level `time_limit` guardrails.
  - 📡 **Telnyx Media Streams**: Bidirectional Telnyx TeXML / Call Control Media Streaming over WebSocket.
  - 🧪 **Mock Telephony**: **Zero-cost, 100% offline** local telecom simulation with automated IVR menu greetings, DTMF tone detection, and telecom bandpass filters.
- **Realistic Acoustic & Accent Simulation**:
  - **Multi-Accent Neural Callers**: Indian English (`en-IN`), US English (`en-US`), British English (`en-GB`), Australian English (`en-AU`).
  - **Acoustic Noise Injection**: Cafe ambient crowd chatter, office air conditioner hum, telephone line static.
  - **Telephony Bandpass Filter**: Realistic PSTN/3G network filtering (300Hz - 3.4kHz) with soft saturation.
- **Hybrid Evaluation Engine**:
  - **LLM-as-a-Judge**: Multi-criteria qualitative rubric evaluation plus 0–100 dimension scores:
    - 🛡️ *Comprehension Under Noise*
    - 🗣️ *Regional Accent Handling*
    - 🤝 *Politeness & Tone*
    - ⚡ *Interruption / Barge-in Recovery*
    - 🎯 *Goal Completion & Resolution*
  - **Deterministic Metrics**: Time-To-First-Byte / response latency (ms), keyword presence/absence assertions, DTMF keypad verification, and barge-in recovery tracking.
- **Tester-Friendly Web UI**:
  - Interactive dashboard designed for non-developer QA testers to select scenario presets, customize test parameters, launch tests, watch live turn bubbles, listen to recorded `.wav` conversations, and inspect metric scores.

---

## 🏗️ Architecture

```
┌────────────────────────────────────────────────────────────────────────┐
│                      TESTER WEB DASHBOARD (UI)                         │
│       Presets • Scenario Builder • Live Turn Feed • Scorecard          │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ REST / WebSocket
┌───────────────────────────────────▼────────────────────────────────────┐
│                       SCENARIO RUNNER ENGINE                           │
│     Coordinates Turns • Audio Recording (.wav) • Timers • Metrics      │
└─────────┬─────────────────────────┬──────────────────────────┬─────────┘
          │                         │                          │
          ▼                         ▼                          ▼
┌──────────────────┐      ┌──────────────────┐       ┌──────────────────┐
│  SIMULATED CALLER│      │   AGENT ADAPTER  │       │ HYBRID EVALUATOR │
│ • Scripted Steps │      │ • WebSocket (WS) │       │ • LLM Judge (0-100)
│ • Dynamic AI     │◄────►│ • Twilio Streams │◄─────►│   Noise / Accents│
│ • Accents (IN/US)│      │ • Telnyx Streams │       │ • Deterministic  │
│ • Cafe/Static    │      │ • Mock Telephony │       │   Latency / DTMF │
└──────────────────┘      └──────────────────┘       └──────────────────┘
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │   AGENT UNDER TEST   │
                         │ (SUT: Gemini Live,   │
                         │  IVR, Phone Bridge)  │
                         └──────────────────────┘
```

---

## 🚀 Quick Start

### 1. Environment Configuration

Copy the example configuration and add your Gemini API key (used for LLM Judge evaluation and dynamic persona callers):

```bash
cd voice_agent_testing_platform
cp .env.example .env
```

Ensure `.env` contains:
```ini
GEMINI_API_KEY=your_gemini_api_key_here
JUDGE_MODEL=gemini-2.5-flash
DEFAULT_WS_URL=ws://127.0.0.1:8765
```

### 2. Pre-flight Check

Verify that all audio dependencies (resamplers, G.711 codecs, neural voices, and ffmpeg) are ready:

```bash
python run_cli.py check
```

---

## 💻 Running the Platform

### Option A: Launch the Tester Web Dashboard (Recommended for QA)

```bash
python run_cli.py ui
```
Open **`http://127.0.0.1:8000`** in your browser.
From the UI, testers can:
1. Select a preset scenario (e.g. *WebSocket Agent: Resilience & Barge-in Test*, *Mock Telephony: IVR Menu & DTMF*).
2. Choose caller accent and background noise.
3. Click **"Run Test Scenario"**.
4. Watch real-time turn-by-turn dialogue, listen to recorded audio, and view evaluation scores.

---

### Option B: Run via CLI Commands

#### 1. Test WebSocket Voice Agent (e.g. Gemini Live SUT)
```bash
python run_cli.py test-ws
```

#### 2. Test Telephony & IVR Flows (Zero-cost local mock)
```bash
python run_cli.py test-telephony
```

---

### Option C: Run with Pytest

Run the comprehensive unit & scenario test suite:
```bash
pytest tests/ -v
```

---

## 📁 Directory Structure

```
voice_agent_testing_platform/
├── .env                          # Local environment variables
├── .env.example                  # Template configuration
├── README.md                     # Documentation
├── requirements.txt              # Dependencies
├── run_cli.py                    # Unified CLI launcher
├── core/
│   ├── models.py                 # Pydantic data schemas (TestScenario, Turn, TestResult)
│   ├── audio_utils.py            # Codecs: G.711 mu-law, PCM resampling, noise, telephony filter
│   ├── speech_engine.py          # Multi-accent neural TTS engine (US, Indian, British, Australian)
│   └── runner.py                 # Scenario execution coordinator
├── adapters/
│   ├── base.py                   # BaseAgentAdapter interface
│   ├── websocket_adapter.py      # WebSocket Agent Adapter (JSON Base64 / binary / barge-in)
│   └── telephony/
│       ├── base_telephony.py     # BaseTelephonyAdapter (G.711 <-> PCM24k conversions)
│       ├── twilio_adapter.py     # Twilio Media Streams (WebSocket G.711 mu-law & clear)
│       ├── telnyx_adapter.py     # Telnyx TeXML Media Streaming
│       └── mock_telephony_adapter.py # Zero-cost local simulated telephone switch & IVR
├── callers/
│   ├── base_caller.py            # BaseCaller interface with acoustic filtering pipeline
│   ├── scripted_caller.py        # Deterministic turn-by-turn script executor
│   └── dynamic_caller.py         # Autonomous AI persona caller
├── evaluator/
│   ├── judge.py                  # LLM-as-a-Judge (Gemini / LiteLLM) with 0-100 rubric scores
│   ├── deterministic.py          # Latency math, keyword assertions, DTMF verification
│   └── metrics.py                # Metric aggregator
├── ui/
│   ├── app.py                    # FastAPI server with WebSocket live streaming
│   ├── templates/index.html      # Responsive tester dashboard
│   └── static/                   # CSS and frontend JavaScript
├── scenarios/                    # Ready-to-run test scenarios
│   ├── test_websocket_agent.py   # WebSocket Gemini Live agent scenario
│   ├── test_telephony_mock.py    # Mock telephony IVR scenario
│   └── test_twilio_agent.py      # Twilio Media Stream scenario
├── tests/
│   └── test_platform.py          # Unit & integration test suite
└── outputs/                      # Generated conversation .wav files, transcripts, and JSON reports
```

---

## 🔧 Customizing & Extending Adapters

For customer-specific voice agents with custom wire protocols, implementation engineers can easily subclass `BaseAgentAdapter`:

```python
from voice_agent_testing_platform.adapters.base import BaseAgentAdapter
from voice_agent_testing_platform.core.models import AudioChunk

class CustomerCustomAdapter(BaseAgentAdapter):
    async def connect(self):
        # Establish proprietary connection
        ...

    async def send_audio(self, chunk: AudioChunk):
        # Forward chunk.data to customer endpoint
        ...

    async def receive_response(self, timeout=30.0) -> AudioChunk:
        # Await customer agent speech and transcript
        ...

    async def interrupt(self):
        # Send proprietary barge-in cancellation packet
        ...

    async def disconnect(self):
        # Clean teardown
        ...
```

