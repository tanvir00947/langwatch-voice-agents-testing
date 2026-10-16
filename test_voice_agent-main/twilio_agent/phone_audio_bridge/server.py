"""FastAPI WebSocket Server for Twilio Media Streams.

Handles:
1. /media-stream: WebSocket endpoint streaming bidirectional audio with Twilio.
2. /twiml: HTTP endpoint serving TwiML for incoming or routed calls.
3. /hangup: HTTP endpoint to terminate call on demand.
4. /health: Health check and status.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse

from twilio_agent.phone_audio_bridge.audio_bridge import AudioBridge, LaptopAudioBridge
from twilio_agent.phone_audio_bridge.audio_codec import mulaw_to_pcm16, pcm16_to_mulaw
from twilio_agent.phone_audio_bridge.config import BridgeConfig
from twilio_agent.phone_audio_bridge.twilio_handler import TwilioCallManager

logger = logging.getLogger("phone_audio_bridge.server")


def create_app(
    config: Optional[BridgeConfig] = None,
    audio_bridge: Optional[AudioBridge] = None,
    call_manager: Optional[TwilioCallManager] = None,
) -> FastAPI:
    """Create and configure FastAPI server application."""
    cfg = config or BridgeConfig.from_env()
    bridge = audio_bridge or LaptopAudioBridge()
    manager = call_manager or TwilioCallManager(cfg)

    app = FastAPI(title="Twilio Phone-to-Laptop Audio Bridge", version="1.0.0")

    # Store state on app
    app.state.config = cfg
    app.state.bridge = bridge
    app.state.manager = manager
    app.state.active_stream_sid = None
    app.state.active_call_sid = None

    @app.get("/")
    async def root():
        """Root status overview."""
        return {
            "status": "online",
            "service": "Twilio Phone-to-Laptop Audio Bridge",
            "active_call": app.state.active_call_sid,
            "max_duration_seconds": cfg.max_duration_seconds,
            "dry_run": cfg.dry_run,
        }

    @app.get("/health")
    async def health():
        return {"status": "healthy"}

    @app.api_route("/twiml", methods=["GET", "POST"])
    async def twiml_endpoint(request: Request):
        """Generates TwiML response directing Twilio to connect to the Media Stream."""
        # Determine host for WebSocket URL
        host = request.headers.get("host", f"127.0.0.1:{cfg.port}")
        proto = "wss" if request.url.scheme == "https" or "ngrok" in host else "ws"
        ws_url = f"{proto}://{host}/media-stream"

        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect>
        <Stream url="{ws_url}">
            <Parameter name="app" value="phone_audio_bridge" />
        </Stream>
    </Connect>
</Response>"""
        return Response(content=xml, media_type="application/xml")

    @app.post("/hangup")
    async def hangup_endpoint():
        """Immediately hangs up active call."""
        if app.state.manager:
            await app.state.manager.hangup_call()
            return {"status": "hangup_triggered"}
        return {"status": "no_call_manager"}

    @app.websocket("/media-stream")
    async def websocket_media_stream(websocket: WebSocket):
        """Twilio Media Stream bidirectional WebSocket handler."""
        await websocket.accept()
        logger.info("⚡ Twilio connected to /media-stream WebSocket.")

        stream_sid: Optional[str] = None
        call_sid: Optional[str] = None
        send_task: Optional[asyncio.Task] = None

        try:
            # Start the audio bridge (laptop mic + speaker)
            await bridge.start()

            async def send_audio_to_twilio():
                """Coroutine continuously reading mic audio and streaming to Twilio."""
                try:
                    while True:
                        if not stream_sid:
                            await asyncio.sleep(0.01)
                            continue

                        pcm_chunk = await bridge.get_audio_to_phone()
                        if not pcm_chunk:
                            await asyncio.sleep(0.005)
                            continue

                        # Convert PCM16 (8kHz) -> G.711 mu-law (8kHz)
                        mulaw_chunk = pcm16_to_mulaw(pcm_chunk)
                        payload_b64 = base64.b64encode(mulaw_chunk).decode("ascii")

                        msg = {
                            "event": "media",
                            "streamSid": stream_sid,
                            "media": {"payload": payload_b64},
                        }
                        await websocket.send_text(json.dumps(msg))
                        await asyncio.sleep(0.001)
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    logger.debug("Send to Twilio task ended: %s", e)

            # Receive loop for incoming messages from Twilio
            while True:
                message_text = await websocket.receive_text()
                try:
                    data = json.loads(message_text)
                except json.JSONDecodeError:
                    continue

                event = data.get("event")

                if event == "connected":
                    logger.info("Twilio handshake 'connected' (Protocol: %s)", data.get("protocol"))

                elif event == "start":
                    start_data = data.get("start", {})
                    stream_sid = start_data.get("streamSid")
                    call_sid = start_data.get("callSid")
                    app.state.active_stream_sid = stream_sid
                    app.state.active_call_sid = call_sid
                    media_format = start_data.get("mediaFormat", {})

                    logger.info(
                        "🎙️  Twilio Media Stream started! StreamSid: %s, CallSid: %s, Format: %s",
                        stream_sid,
                        call_sid,
                        media_format,
                    )
                    print("\n" + "=" * 65)
                    print("  📞 CALL CONNECTED! AUDIO BRIDGE IS ACTIVE.")
                    print("  Speak into your laptop mic to talk to your phone.")
                    print("  Listen through your laptop speakers to hear your phone.")
                    print("  Press 'q' or 'Ctrl+C' in terminal to hang up early.")
                    print("=" * 65 + "\n")

                    # Start streaming laptop mic audio to Twilio
                    if send_task is None:
                        send_task = asyncio.create_task(send_audio_to_twilio())

                elif event == "media":
                    media_data = data.get("media", {})
                    payload_b64 = media_data.get("payload")
                    if payload_b64:
                        # Decode base64 -> mu-law bytes -> PCM16 linear bytes
                        mulaw_bytes = base64.b64decode(payload_b64)
                        pcm_bytes = mulaw_to_pcm16(mulaw_bytes)
                        # Route audio to bridge (laptop speakers)
                        await bridge.on_audio_from_phone(pcm_bytes)

                elif event == "stop":
                    logger.info("Twilio 'stop' event received. StreamSid: %s", stream_sid)
                    break

        except WebSocketDisconnect:
            logger.info("Twilio WebSocket disconnected.")
        except Exception as e:
            logger.error("Error in Twilio Media Stream WebSocket: %s", e)
        finally:
            if send_task and not send_task.done():
                send_task.cancel()
            await bridge.stop()
            app.state.active_stream_sid = None
            app.state.active_call_sid = None
            logger.info("Media stream connection closed cleanly.")

    return app

