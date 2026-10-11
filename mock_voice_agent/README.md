# WebSocket Voice Agent (Powered by Google Gemini)

A lightweight, standalone **WebSocket Voice Agent** built to test your QE evaluation pipeline using LangWatch Scenario's `WebSocketAgentAdapter`.

**100% OpenAI-Free**: Uses **Google Gemini** for LLM responses and local 24kHz audio synthesis.

---

## 1. Setup Environment

Create a `.env` file inside this `mock_voice_agent` folder by copying `.env.example`:

```bash
# On Windows PowerShell:
Copy-Item mock_voice_agent\.env.example mock_voice_agent\.env
```

Open `mock_voice_agent\.env` and paste your Gemini API key:
```ini
GEMINI_API_KEY=AIzaSy...your_gemini_api_key...
GEMINI_MODEL=gemini-2.5-flash
WS_HOST=127.0.0.1
WS_PORT=8765
```

---

## 2. Test Your Gemini API Key

Verify that your Gemini API key is working:
```bash
python mock_voice_agent/test_llm.py
```
*Expected output:*
```
Connecting to Gemini (model: 'gemini-2.5-flash')...

✅ Gemini Response:
--------------------------------------------------
Artificial intelligence works by processing vast amounts of data...
--------------------------------------------------
LLM test successful!
```

---

## 3. Run the Voice Agent Server

Start the WebSocket voice server:
```bash
python mock_voice_agent/server.py
```
*Output:*
```
[INFO] Starting WebSocket Voice Agent server on ws://127.0.0.1:8765 ...
[INFO] Gemini client initialized with model: gemini-2.5-flash
[INFO] WebSocket Voice Agent is listening on ws://127.0.0.1:8765
```

The server:
1. Listens for incoming audio packets (`{"type": "audio", "data": "<base64 PCM16>"}`).
2. Uses **Gemini** to dynamically generate spoken responses.
3. Encodes the 24kHz PCM16 audio and returns it over the WebSocket.

---

## 4. Run the Scenario QE Test

Run the automated test using LangWatch Scenario:
```bash
python mock_voice_agent/test_ws_agent.py
# or using pytest:
pytest mock_voice_agent/test_ws_agent.py -s
```

---

## File Structure

- **`.env.example`**: Template for your configuration.
- **`.env`**: Your local environment file (never commit this).
- **`test_llm.py`**: Quick sanity test for your Gemini API key.
- **`server.py`**: The WebSocket voice agent server.
- **`protocol.py`**: The Scenario `WebSocketProtocol` adapter.
- **`audio_util.py`**: 24kHz PCM16 audio waveform generator.
- **`test_ws_agent.py`**: Automated test using `scenario.run(...)`.
