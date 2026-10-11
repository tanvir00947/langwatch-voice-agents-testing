# 🧪 LangWatch Scenario Voice Agent Test Suite

A standalone test suite testing a real WebSocket voice agent using an **Adversarial Voice Agent** (powered natively by `gemini-2.5-flash-native-audio-latest`) and an AI **Judge** (powered by `gemini-3.1-flash-lite`).

---

## 🎯 Architecture: Real Voice Agent vs. Voice Agent

```
  ┌─────────────────────────────────────────────────────────────┐
  │                 Adversarial Voice Agent                     │
  │     (gemini-2.5-flash-native-audio-latest, Voice: Puck)     │
  │     • Generates native spoken audio directly (PCM 24k)     │
  │     • Simulates realistic cafe chatter & phone filter      │
  └──────────────────────────────┬──────────────────────────────┘
                                 │ Audio over WebSocket
                                 ▼
  ┌─────────────────────────────────────────────────────────────┐
  │                   WebSocket Voice Agent                     │
  │     (gemini-2.5-flash-native-audio-latest, Voice: Aoede)    │
  │     • Real-time bidirectional streaming over ws://...       │
  │     • Pure native multimodal voice (No STT+LLM+TTS)         │
  └──────────────────────────────┬──────────────────────────────┘
                                 │
                                 ▼
  ┌─────────────────────────────────────────────────────────────┐
  │                 Scenario Judge Agent                        │
  │                   (gemini-3.1-flash-lite)                   │
  │     • Evaluates politeness, accuracy, barge-in recovery     │
  │     • Reports analytics & traces to https://app.langwatch.ai│
  └─────────────────────────────────────────────────────────────┘
```

- **Zero STT + LLM + TTS pipeline in either folder.**
- **Real Voice Agent vs Voice Agent.**
- **Judge Model**: `gemini-3.1-flash-lite`.
- **Live Transcript**: Recorded turn-by-turn to `outputs/conversation_<timestamp>.txt`.
- **Audio Recording**: Full multi-party conversation saved to `outputs/conversation_<timestamp>.wav`.
- **LangWatch Analytics**: Streamed directly to `https://app.langwatch.ai`.

---

## 🚀 Setup & Execution

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure Environment (`.env`)
Create or edit `.env`:
```env
GEMINI_API_KEY=your_gemini_api_key_here
LANGWATCH_API_KEY=your_langwatch_api_key_here
JUDGE_MODEL=gemini-3.1-flash-lite
ADVERSARIAL_MODEL=gemini-2.5-flash-native-audio-latest
ADVERSARIAL_VOICE=Puck
WS_URL=ws://127.0.0.1:8765
```

### 3. Run the Test
```bash
python test_voice_agent.py
```
*(Or run via pytest: `pytest test_voice_agent.py -s`)*

The test script will:
1. Detect if the voice agent server is already running on `ws://127.0.0.1:8765`. If not, it automatically boots the companion server from `../voice_agent/server.py`.
2. Connect the adversarial caller and support agent in a multi-turn spoken dialogue.
3. Simulate cafe background noise, telephony bandpass filtering, and mid-utterance barge-in interruption.
4. Evaluate the conversation with `gemini-3.1-flash-lite`.
5. Stream traces to LangWatch and save WAV and TXT recordings in `outputs/`.
