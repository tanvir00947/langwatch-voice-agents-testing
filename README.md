# 🎙️ Gemini Live & WebSocket Voice Agents with LangWatch

A collection of real-time conversational voice agents and testing suites integrated with **Google Gemini** and **LangWatch Scenario** for automated evaluation, acoustic resilience testing, and barge-in interruption analysis.

---

## 📂 Repository Overview

```
langwatch-demo/
├── gemini_websocket_voice_agent/  # Real native voice agent vs adversarial voice agent (WebSocket)
│   ├── voice_agent/               # Standalone Gemini Live native voice agent server
│   └── langwatch_test/            # Adversarial caller test suite & JudgeAgent
│
├── gemini-live-agent/             # Direct Gemini Live bidirectional audio streaming agent
│   ├── gemini-live.py             # Microphone-to-speaker native Gemini Live voice client
│   ├── adapter.py                 # Scenario adapter with real-time transcript logging
│   └── test_gemini_live.py        # Scenario test suite with cafe noise & barge-in
│
└── mock_voice_agent/              # WebSocket Voice Agent with STT -> LLM -> TTS pipeline
    ├── server.py                  # Server running Gemini STT -> Gemini LLM -> Neural TTS
    ├── protocol.py                # Base64 PCM16 JSON WebSocket protocol
    └── test_ws_agent.py           # Scenario test with background noise & barge-in
```

---

## 🚀 Projects

### 1. [`gemini_websocket_voice_agent/`](./gemini_websocket_voice_agent/)
- **Native Voice Model**: Powered natively by `gemini-2.5-flash-native-audio-latest`.
- **Architecture**: Pure multimodal audio streaming (No STT + LLM + TTS pipeline).
- **Two Independent Folders**:
  - `voice_agent/`: Standalone WebSocket server streaming native 24kHz audio (`Aoede` voice).
  - `langwatch_test/`: Adversarial voice caller (`Puck` voice) with cafe background noise, telephony filter, and `gemini-3.1-flash-lite` judge.

### 2. [`gemini-live-agent/`](./gemini-live-agent/)
- Direct bidirectional audio streaming using Google's GenAI Live API (`gemini-2.5-flash-native-audio-latest`).
- Real-time microphone input at 16kHz and low-latency audio playback at 24kHz.
- Multi-turn evaluation using Scenario with telephony filter and barge-in interruption.

### 3. [`mock_voice_agent/`](./mock_voice_agent/)
- Full conversational voice pipeline over WebSocket:
  1. **STT**: Gemini multimodal audio transcription.
  2. **LLM**: Gemini conversational reasoning.
  3. **TTS**: High-fidelity neural voice synthesis (`en-US-AriaNeural`).
- Multi-turn testing with realistic acoustic degradation and barge-in.

---

## ⚙️ Environment Setup

Each folder includes a `.env.example` file. Copy to `.env` and fill in your API keys:

```bash
# Google Gemini API Key
GEMINI_API_KEY=your_gemini_api_key_here

# LangWatch API Key (for analytics & simulations)
LANGWATCH_API_KEY=your_langwatch_api_key_here
```

---

## 📊 LangWatch Platform Analytics

Test runs automatically log simulations and evaluations to [LangWatch](https://app.langwatch.ai):
- **Simulations**: [app.langwatch.ai/simulations](https://app.langwatch.ai/simulations)
- **Evaluations**: [app.langwatch.ai/evaluations](https://app.langwatch.ai/evaluations)
