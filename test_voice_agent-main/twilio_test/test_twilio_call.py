"""Local Flask server connecting a Twilio phone call to the laptop browser."""

from __future__ import annotations

import hmac
import logging
import re
import secrets
import threading
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from flask import Flask, Response, jsonify, request
from twilio_flask import (
    CALL_DURATION_SECONDS,
    create_access_token,
    create_call,
    hangup_call,
    is_valid_twilio_signature,
    public_url,
    required_setting,
)

load_dotenv(Path(__file__).resolve().with_name(".env"), override=False)

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("twilio_phone_laptop")

active_calls: dict[str, str] = {}
call_timers: dict[str, threading.Timer] = {}
state_lock = threading.Lock()
call_starting = False


def _valid_pin(candidate: Any) -> bool:
    if not isinstance(candidate, str):
        return False
    return hmac.compare_digest(candidate, required_setting("CALL_PIN"))


def _twilio_request_is_valid() -> bool:
    base = public_url()
    query = f"?{request.query_string.decode('ascii')}" if request.query_string else ""
    return is_valid_twilio_signature(
        f"{base}{request.path}{query}",
        request.form.to_dict(flat=True),
        request.headers.get("X-Twilio-Signature"),
    )


def _expire_call(call_sid: str) -> None:
    try:
        hangup_call(call_sid)
        logger.info("Call %s ended by the 60-second server timer.", call_sid)
    except Exception:
        logger.exception("Could not end call %s from the duration timer.", call_sid)
    finally:
        _forget_call(call_sid)


def _forget_call(call_sid: str) -> None:
    with state_lock:
        timer = call_timers.pop(call_sid, None)
        if timer and timer is not threading.current_thread():
            timer.cancel()
        for room, active_sid in list(active_calls.items()):
            if active_sid == call_sid:
                active_calls.pop(room, None)


PAGE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Phone and laptop call</title>
  <script src="https://sdk.twilio.com/js/voice/releases/2.11.1/twilio.min.js"></script>
  <style>
    body { font: 16px system-ui, sans-serif; max-width: 36rem; margin: 3rem auto; padding: 0 1rem; }
    button { font: inherit; padding: .6rem 1rem; }
    #status { margin-top: 1rem; }
  </style>
</head>
<body>
  <h1>Phone and laptop call</h1>
  <p>Allow microphone access when your browser asks. Use the laptop microphone and speakers
     to talk with the person answering the phone.</p>
  <p id="status">Connecting to the call…</p>
  <p id="timer" aria-live="polite"></p>
  <button id="hangup" type="button" disabled>Hang up</button>
  <script>
    const room = new URLSearchParams(location.search).get("room");
    const status = document.getElementById("status");
    const timer = document.getElementById("timer");
    const hangup = document.getElementById("hangup");
    let device;
    let call;
    let countdown;
    let ended = false;

    function finish(message) {
      if (ended) return;
      ended = true;
      clearInterval(countdown);
      status.textContent = message;
      timer.textContent = "";
      hangup.disabled = true;
      if (device) device.destroy();
    }

    async function connect() {
      if (!room || !/^[a-f0-9]{32}$/.test(room)) {
        finish("No active call was provided. Start the call with python twilio_flask.py.");
        return;
      }
      try {
        const response = await fetch("/token?room=" + encodeURIComponent(room));
        const body = await response.json();
        if (!response.ok) throw new Error(body.error || "Could not get a call token.");
        if (!window.Twilio || !window.Twilio.Device) {
          throw new Error("Twilio Voice SDK did not load. Check your internet connection.");
        }
        device = new Twilio.Device(body.token);
        device.on("error", error => finish("Call error: " + error.message));
        call = await device.connect({params: {To: room}});
        hangup.disabled = false;
        status.textContent = "Connected. Speak using your laptop microphone and speakers.";
        let remaining = 60;
        timer.textContent = "Time remaining: " + remaining + " seconds";
        countdown = setInterval(() => {
          remaining -= 1;
          timer.textContent = "Time remaining: " + remaining + " seconds";
          if (remaining <= 0) {
            clearInterval(countdown);
            call.disconnect();
            finish("The 60-second call limit has been reached.");
          }
        }, 1000);
        call.on("disconnect", () => finish("Call ended."));
        call.on("error", error => finish("Call error: " + error.message));
      } catch (error) {
        finish("Could not connect: " + error.message);
      }
    }

    hangup.addEventListener("click", () => {
      if (call) call.disconnect();
      finish("Call ended.");
    });
    connect();
  </script>
</body>
</html>"""


@app.get("/")
def home() -> Response:
    return Response(PAGE, mimetype="text/html")


@app.get("/health")
def health():
    return {"status": "healthy", "max_duration_seconds": CALL_DURATION_SECONDS}


@app.post("/start-call")
def start_call():
    global call_starting
    data = request.get_json(silent=True) or {}
    if not _valid_pin(data.get("pin")):
        return jsonify(error="Invalid or missing CALL_PIN."), 403

    with state_lock:
        if active_calls or call_starting:
            return jsonify(error="A call is already active."), 409
        call_starting = True

    room = secrets.token_hex(16)
    try:
        call = create_call(room)
    except Exception:
        with state_lock:
            call_starting = False
        logger.exception("Twilio could not create the outbound call.")
        return jsonify(error="Twilio could not start the call. Check server logs and Twilio settings."), 502

    with state_lock:
        active_calls[room] = call.sid
        call_starting = False
    return jsonify(room=room, call_sid=call.sid)


@app.get("/token")
def token():
    room = request.args.get("room", "")
    if not re.fullmatch(r"[a-f0-9]{32}", room):
        return jsonify(error="Invalid call room."), 400
    with state_lock:
        is_active = room in active_calls
    if not is_active:
        return jsonify(error="That call is no longer active."), 404
    try:
        return jsonify(token=create_access_token(f"laptop-{room}"))
    except Exception:
        logger.exception("Could not create a Twilio Voice access token.")
        return jsonify(error="Could not authorize the laptop audio connection. Check server settings."), 500


@app.post("/client-voice")
def client_voice():
    if not _twilio_request_is_valid():
        return Response("Invalid Twilio signature.", status=403)

    room = request.form.get("To", "")
    if not re.fullmatch(r"[a-f0-9]{32}", room):
        return Response("Invalid conference room.", status=400)
    with state_lock:
        is_active = room in active_calls
    if not is_active:
        return Response("Call is no longer active.", status=404)

    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Dial>
    <Conference beep="false" endConferenceOnExit="true" maxParticipants="2">{room}</Conference>
  </Dial>
</Response>"""
    return Response(twiml, mimetype="application/xml")


@app.post("/twilio/status")
def twilio_status():
    if not _twilio_request_is_valid():
        return Response("Invalid Twilio signature.", status=403)

    call_sid = request.form.get("CallSid", "")
    status = request.form.get("CallStatus", "")
    if status == "in-progress" or status == "answered":
        with state_lock:
            if call_sid in call_timers:
                return "", 204
            timer = threading.Timer(CALL_DURATION_SECONDS, _expire_call, args=(call_sid,))
            timer.daemon = True
            call_timers[call_sid] = timer
        timer.start()
    elif status in {"completed", "canceled", "failed", "busy", "no-answer"}:
        _forget_call(call_sid)
    return "", 204


@app.post("/hangup")
def hangup():
    data = request.get_json(silent=True) or {}
    if not _valid_pin(data.get("pin")):
        return jsonify(error="Invalid or missing CALL_PIN."), 403

    room = data.get("room", "")
    with state_lock:
        call_sid = active_calls.get(room)
    if not call_sid:
        return jsonify(error="No active call for that room."), 404
    try:
        hangup_call(call_sid)
    except Exception:
        logger.exception("Could not hang up call %s.", call_sid)
        return jsonify(error="Twilio could not end the call."), 502
    _forget_call(call_sid)
    return jsonify(status="ended")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=False)
