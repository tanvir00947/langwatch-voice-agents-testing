"""Test FastAPI endpoints and Twilio Media Stream WebSocket protocol."""

import base64
import json
import numpy as np
import pytest
from starlette.testclient import TestClient

from twilio_agent.phone_audio_bridge.audio_bridge import MockAudioBridge
from twilio_agent.phone_audio_bridge.audio_codec import mulaw_to_pcm16, pcm16_to_mulaw
from twilio_agent.phone_audio_bridge.config import BridgeConfig
from twilio_agent.phone_audio_bridge.server import create_app
from twilio_agent.phone_audio_bridge.twilio_handler import TwilioCallManager


@pytest.fixture
def mock_app():
    config = BridgeConfig(
        account_sid="AC_MOCK_ACCOUNT_SID_SERVER",
        auth_token="mock_token",
        twilio_phone_number="+12025550100",
        to_phone_number="+919876543210",
        public_url="https://mock.ngrok.app",
        ngrok_authtoken=None,
        host="127.0.0.1",
        port=8000,
        max_duration_seconds=30,
        require_confirmation=False,
        dry_run=True,
    )
    bridge = MockAudioBridge()
    manager = TwilioCallManager(config)
    app = create_app(config=config, audio_bridge=bridge, call_manager=manager)
    return app, bridge


def test_http_endpoints(mock_app):
    app, _ = mock_app
    client = TestClient(app)

    # Health check
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "healthy"}

    # Root status
    res = client.get("/")
    assert res.status_code == 200
    assert res.json()["status"] == "online"

    # TwiML endpoint
    res = client.post("/twiml")
    assert res.status_code == 200
    assert "<Response>" in res.text
    assert "<Stream" in res.text
    assert "/media-stream" in res.text


def test_websocket_media_stream_protocol(mock_app):
    app, bridge = mock_app
    client = TestClient(app)

    with client.websocket_connect("/media-stream") as ws:
        # 1. Send handshake
        ws.send_text(json.dumps({"event": "connected", "protocol": "Call", "version": "1.0.0"}))

        # 2. Send start event
        ws.send_text(
            json.dumps(
                {
                    "event": "start",
                    "sequenceNumber": "1",
                    "start": {
                        "streamSid": "MZ_TEST_STREAM_123",
                        "callSid": "CA_TEST_CALL_123",
                        "mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": 8000, "channels": 1},
                    },
                }
            )
        )

        # 3. Send media chunk from caller
        # 160 samples (20ms) of 400Hz audio
        t = np.linspace(0, 0.02, 160, endpoint=False)
        pcm_orig = (np.sin(2 * np.pi * 400 * t) * 8000).astype(np.int16).tobytes()
        mulaw_orig = pcm16_to_mulaw(pcm_orig)
        b64_payload = base64.b64encode(mulaw_orig).decode("ascii")

        ws.send_text(
            json.dumps(
                {
                    "event": "media",
                    "sequenceNumber": "2",
                    "media": {"track": "inbound", "chunk": "1", "payload": b64_payload},
                }
            )
        )

        # 4. Inject mock audio to be sent back to caller
        test_reply_pcm = (np.cos(2 * np.pi * 800 * t) * 7000).astype(np.int16).tobytes()
        bridge.inject_mock_audio(test_reply_pcm)

        # Receive outgoing message from WebSocket
        reply_msg_text = ws.receive_text()
        reply_data = json.loads(reply_msg_text)

        assert reply_data.get("event") == "media"
        assert reply_data.get("streamSid") == "MZ_TEST_STREAM_123"
        reply_payload_b64 = reply_data.get("media", {}).get("payload")
        assert reply_payload_b64 is not None

        # Decode received payload
        decoded_mulaw = base64.b64decode(reply_payload_b64)
        assert len(decoded_mulaw) == 160  # 160 samples

        # 5. Send stop event
        ws.send_text(json.dumps({"event": "stop", "stop": {"callSid": "CA_TEST_CALL_123"}}))

    # Verify bridge received caller audio
    assert len(bridge.received_chunks) >= 1

