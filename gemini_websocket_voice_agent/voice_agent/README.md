# 🎙️ Standalone Gemini Live WebSocket Voice Agent

A standalone, real-time voice agent communicating over WebSocket and powered natively by **`gemini-2.5-flash-native-audio-latest`**.

## 💡 Architecture & Key Features

- **Pure Native Audio**: Zero discrete STT + text LLM + TTS pipeline. Ingests raw audio chunks and streams back raw spoken speech directly from Google's Gemini Live API.
- **WebSocket Protocol**: Exchanges base64-encoded PCM16 audio frames with real-time text transcription and turn delimiters.
- **Dynamic Resampling**: Ingests canonical 24kHz PCM16 caller audio, resamples to 16kHz for Gemini input, and streams back Gemini's native 24kHz audio output.
- **Real-Time Interruption / Barge-in**: Listens for `{"type": "interrupt"}` events and terminates in-flight speech instantly.

---

## 🚀 Setup & Running

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure Environment (`.env`)
Create or edit `.env`:
```env
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-2.5-flash-native-audio-latest
VOICE_NAME=Aoede
WS_HOST=127.0.0.1
WS_PORT=8765
```

### 3. Launch the Server
```bash
python server.py
```

Expected output:
```text
============================================================
🚀 Gemini Live Native WebSocket Voice Agent Started
  • Model: gemini-2.5-flash-native-audio-latest
  • Voice: Aoede
  • Address: ws://127.0.0.1:8765
  • Architecture: Pure Native Audio (No STT/TTS pipeline)
============================================================
```

---

## 📡 Wire Protocol Specification

### Client to Server:
- **Audio Chunk**:
  ```json
  {"type": "audio", "data": "<base64_pcm16_24000hz>"}
  ```
- **Barge-In / Interruption**:
  ```json
  {"type": "interrupt"}
  ```

### Server to Client:
- **Streaming Audio**:
  ```json
  {"type": "audio", "data": "<base64_pcm16_24000hz>", "transcript": "..."}
  ```
- **Turn Complete**:
  ```json
  {"type": "turn_complete", "transcript": "Full response transcript text"}
  ```
- **Interruption Acknowledged**:
  ```json
  {"type": "interrupted"}
  ```
