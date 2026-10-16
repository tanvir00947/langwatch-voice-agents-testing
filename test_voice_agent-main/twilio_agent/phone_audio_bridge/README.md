# 📞 Twilio Phone-to-Laptop Real-Time Audio Bridge

A bidirectional, real-time audio bridge connecting a personal mobile phone to a laptop's microphone and speakers via **Twilio Media Streams** over WebSocket.

Architected with strict trial balance protections, auto-hangup safeguards, pre-flight diagnostics, and full compatibility for future integration with **LangWatch Scenario**.

---

## 🏗️ Architecture Overview

```
                                 ┌──────────────────────────────────────────────────┐
                                 │            Twilio Cloud Infrastructure           │
                                 └─────────▲──────────────────────────────┬─────────┘
                                           │ Outbound Call                │ Twilio Media Stream
                                           │ (TwiML with time_limit)      │ (G.711 mu-law, 8kHz WSS)
                                           │                              ▼
┌──────────────────┐             ┌─────────┴─────────┐            ┌─────────────────────────┐
│  Personal Mobile │ ◄────────── │   Twilio Voice    │            │     FastAPI Server      │
│  Phone (+91...)  │ Audio Call  │     Carrier       │            │      /media-stream      │
└──────────────────┘             └───────────────────┘            └───────────┬─────────────┘
                                                                              │
                                                                              ▼
                                                                 ┌──────────────────────────┐
                                                                 │   Audio Bridge Layer     │
                                                                 │ (LaptopAudio / LangWatch)│
                                                                 └─────┬──────────────▲─────┘
                                              Incoming Phone Audio     │              │ Outgoing Laptop Audio
                                                  (G.711 -> PCM16)     ▼              │ (PCM16 -> G.711)
                                                                 ┌───────────┐  ┌───────────┐
                                                                 │  Laptop   │  │  Laptop   │
                                                                 │  Speakers │  │    Mic    │
                                                                 └───────────┘  └───────────┘
```

---

## 🛡️ Trial Balance & Cost Safeguards

If you are on a Twilio Trial account or have limited call minutes:

1. **Carrier-Enforced `time_limit`**:
   Every call is initiated with Twilio's carrier-level `time_limit` parameter (default: 60s). Twilio's telecom switches automatically disconnect the call when the limit is reached—even if your laptop loses internet or power.
2. **Local Async Watchdog**:
   A local timer runs concurrently and triggers an immediate REST API hangup if the duration limit is reached.
3. **Mandatory Interactive Confirmation**:
   The application **never dials automatically**. Before any real call is placed, you must explicitly confirm by typing `YES` in the terminal.
4. **Instant Early Hangup**:
   Press **ENTER** or type **`q`** in the terminal at any time during an active call to hang up immediately.
5. **Zero-Cost Dry-Run & Test Modes**:
   - `python main.py check`: Checks configuration, verified numbers, and audio hardware without dialing.
   - `python main.py test-audio`: 5-second microphone and speaker loopback test on your laptop.
   - `python main.py dry-run`: Simulates the entire server and call flow with 0 Twilio credits used.

---

## 🇮🇳 Special Rules for Calling Indian Mobile Numbers (+91)

If you are dialing an Indian mobile number, Twilio enforces specific requirements:

### 1. Voice Geographic Permissions (Mandatory)
By default, Twilio disables outbound calls to India (+91) to prevent toll fraud.
- Go to [Twilio Console -> Voice -> Settings -> Geo Permissions](https://console.twilio.com/us1/develop/voice/settings/geo-permissions).
- Search for **India**, select the checkbox, and click **Save**.
- *(If this is not enabled, Twilio rejects calls with Error `21215`).*

### 2. Twilio Trial Account - Verified Caller ID (Mandatory)
If your Twilio account is a **Trial Account**:
- Twilio only allows outbound calls to phone numbers that you have explicitly verified.
- Verify your personal mobile number at: [Twilio Console -> Verified Caller IDs](https://console.twilio.com/us1/develop/phone-numbers/manage/verified).
- Twilio will send you a verification code via SMS or voice call.
- *(If unverified, calls fail with Error `21216`).*

### 3. Number Format
Numbers must follow the standard E.164 format:
```
+91<10-digit-mobile-number>
Example: +919876543210
```

---

## ⚙️ Setup & Configuration

### 1. Copy Environment File
In this folder (`twilio_agent/phone_audio_bridge/`), copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

### 2. Fill in `.env` Values

```ini
# Twilio Account SID & Auth Token (from Twilio Console Dashboard)
TWILIO_ACCOUNT_SID=ACXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
TWILIO_AUTH_TOKEN=your_twilio_auth_token_here

# Your Twilio Voice Phone Number (in E.164 format)
TWILIO_PHONE_NUMBER=+12025550143

# Your Personal Mobile Number to call (in E.164 format)
TO_PHONE_NUMBER=+919876543210

# Public URL for Twilio to reach your local server:
# Option A: Run `ngrok http 8000` in a separate terminal and paste the URL:
PUBLIC_URL=https://your-subdomain.ngrok-free.app

# Option B: Set to 'auto' to let pyngrok start a tunnel automatically:
# PUBLIC_URL=auto
# NGROK_AUTHTOKEN=your_ngrok_token_if_using_auto

# Safety Limits
MAX_CALL_DURATION_SECONDS=60
REQUIRE_CONFIRMATION=true
DRY_RUN=false
```

---

## 🚀 Usage

All commands can be run from the root directory or inside `twilio_agent/phone_audio_bridge/`.

### Step 1: Run Pre-Flight Diagnostics
Checks your audio hardware, Twilio account, verified caller IDs, and India permissions:
```bash
python twilio_agent/phone_audio_bridge/main.py check
```

### Step 2: Test Laptop Microphone & Speakers (Zero Credits)
Runs a 5-second echo test: speak into your laptop mic and hear your voice in your speakers:
```bash
python twilio_agent/phone_audio_bridge/main.py test-audio
```

### Step 3: Run Dry-Run Simulation (Zero Credits)
Starts the server and simulates the full call lifecycle without contacting Twilio:
```bash
python twilio_agent/phone_audio_bridge/main.py dry-run
```

### Step 4: Run Real Outbound Call
Exposes the server, prompts for your explicit `YES` confirmation, places the call, and bridges audio:
```bash
python twilio_agent/phone_audio_bridge/main.py run
```
- When your mobile phone rings, answer the call.
- Speak through your phone: you will hear your voice from your laptop speakers.
- Speak through your laptop mic: you will hear your voice through your phone earpiece.
- Press **ENTER** or type **`q`** at any time in the terminal to hang up immediately.

---

## 🧪 Running Automated Tests

Run the full pytest suite (12 tests covering audio codecs, WebSockets, watchdog, and safeguards):
```bash
pytest twilio_agent/phone_audio_bridge/tests
```

---

## 🔮 Future LangWatch Scenario Integration

The code is pre-architected with `AudioBridge` and `langwatch_interface.py`:
- `LangWatchScenarioBridge` accepts Twilio's 8kHz G.711 stream, resamples it to 16kHz/24kHz for LangWatch Scenario's audio models (Gemini Live / Puck / Aoede).
- Scenario's test agent can converse directly with the person on the phone and pass the live transcript to an LLM Judge (`LangWatchEvaluationPlan`) to grade response accuracy and sentiment.

