"""Twilio helpers and command-line launcher for the phone/laptop call."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

from dotenv import load_dotenv
from twilio.jwt.access_token import AccessToken
from twilio.jwt.access_token.grants import VoiceGrant
from twilio.rest import Client

load_dotenv(Path(__file__).resolve().with_name(".env"), override=False)

CALL_DURATION_SECONDS = 60


def required_setting(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Set the {name} environment variable before starting.")
    return value


def public_url() -> str:
    url = required_setting("PUBLIC_URL").rstrip("/")
    if not url.startswith("https://"):
        raise RuntimeError("PUBLIC_URL must be your public HTTPS tunnel URL.")
    return url


def twilio_client() -> Client:
    return Client(
        required_setting("TWILIO_ACCOUNT_SID"),
        required_setting("TWILIO_AUTH_TOKEN"),
    )


def create_call(room: str):
    """Dial the phone into the named conference with a 60-second hard limit."""
    from_number = required_setting("TWILIO_PHONE_NUMBER")
    to_number = required_setting("TO_PHONE_NUMBER")
    callback = f"{public_url()}/twilio/status"
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Dial>
    <Conference beep="false" endConferenceOnExit="true" maxParticipants="2">{room}</Conference>
  </Dial>
</Response>"""
    return twilio_client().calls.create(
        to=to_number,
        from_=from_number,
        twiml=twiml,
        time_limit=CALL_DURATION_SECONDS,
        status_callback=callback,
        status_callback_event=["answered", "completed"],
    )


def create_access_token(identity: str) -> str:
    """Create a short-lived token for the laptop browser's Twilio Voice SDK."""
    token = AccessToken(
        required_setting("TWILIO_ACCOUNT_SID"),
        required_setting("TWILIO_API_KEY_SID"),
        required_setting("TWILIO_API_KEY_SECRET"),
        identity=identity,
        ttl=300,
    )
    token.add_grant(
        VoiceGrant(
            outgoing_application_sid=required_setting("TWILIO_TWIML_APP_SID"),
        )
    )
    return token.to_jwt()


def hangup_call(call_sid: str) -> None:
    twilio_client().calls(call_sid).update(status="completed")


def is_valid_twilio_signature(url: str, params: dict, signature: str | None) -> bool:
    from twilio.request_validator import RequestValidator

    if not signature:
        return False
    validator = RequestValidator(required_setting("TWILIO_AUTH_TOKEN"))
    return validator.validate(url, params, signature)


def start_from_terminal() -> int:
    """Start the server-side call and open the laptop browser as its second leg."""
    try:
        if input("This places a call that ends after at most 60 seconds. Type YES: ").strip() != "YES":
            print("Call cancelled.")
            return 1

        server_url = os.environ.get("LOCAL_SERVER_URL", "http://127.0.0.1:8000").rstrip("/")
        pin = required_setting("CALL_PIN")
        request = urllib.request.Request(
            f"{server_url}/start-call",
            data=json.dumps({"pin": pin}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            result = json.loads(response.read().decode("utf-8"))

        browser_url = f"{server_url}/?room={result['room']}"
        webbrowser.open(browser_url)
        print("Call started. Answer your phone and speak using the laptop's browser audio.")
        print("The call will end automatically after no more than 60 seconds.")
        print(f"Call SID: {result['call_sid']}")
        return 0
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        print(f"Could not start the call ({error.code}): {detail}", file=sys.stderr)
    except (urllib.error.URLError, TimeoutError) as error:
        print(f"Cannot reach the local Flask server: {error}", file=sys.stderr)
    except (KeyError, json.JSONDecodeError) as error:
        print(f"The server returned an invalid response: {error}", file=sys.stderr)
    except (RuntimeError, OSError) as error:
        print(str(error), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(start_from_terminal())
