# 🌐 Gemini WebSocket Voice Agent & LangWatch Test

This project contains two **completely independent** directories for developing and testing real-time Gemini voice agents:

```
gemini_websocket_voice_agent/
├── voice_agent/      # Standalone WebSocket Voice Agent (gemini-2.5-flash-native-audio-latest)
└── langwatch_test/   # LangWatch Scenario Test with Adversarial Voice Agent & Judge
```

---

## 📁 1. `voice_agent/`
A standalone voice agent server that listens on a WebSocket and internally uses **`gemini-2.5-flash-native-audio-latest`** as its native multimodal audio model.
- **Pure Native Audio**: No separate STT + text LLM + TTS pipeline. Ingests raw audio chunks and streams back raw spoken speech directly from Gemini Live.
- **Real-Time Interruption**: Supports native barge-in cancellation when an interrupt signal is received.
- **Run Standalone**:
  ```bash
  cd voice_agent
  python server.py
  ```

---

## 📁 2. `langwatch_test/`
A standalone testing suite that tests the voice agent using:
- **Adversarial Voice Agent**: Powered natively by **`gemini-2.5-flash-native-audio-latest`** (Voice: `Puck`). Generates spoken caller turns with realistic cafe ambient noise, telephony bandpass filtering, and mid-turn barge-in interruptions.
- **AI Judge**: Powered by **`gemini-3.1-flash-lite`** to evaluate politeness, accuracy, and interruption handling.
- **LangWatch Analytics**: Real-time simulation and evaluation reporting to `https://app.langwatch.ai`.
- **Live Output**: Turn-by-turn live transcript (`.txt`) and complete audio recording (`.wav`).
- **Run Standalone**:
  ```bash
  cd langwatch_test
  python test_voice_agent.py
  ```
