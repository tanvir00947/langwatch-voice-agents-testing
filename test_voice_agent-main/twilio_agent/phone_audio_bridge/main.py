"""Main CLI Application for Twilio Phone-to-Laptop Audio Bridge.

Commands:
  python main.py check        - Run pre-flight credentials, Indian number & audio checks
  python main.py test-audio   - Test laptop mic and speakers locally (0 Twilio credits)
  python main.py dry-run      - Run server in simulated call mode (0 Twilio credits)
  python main.py run          - Place live Twilio call with two-way audio bridge
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import Optional

# Ensure Windows terminal handles Unicode characters cleanly
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
os.environ["PYTHONIOENCODING"] = "utf-8"

# Ensure package and repository roots are in sys.path
_CURRENT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _CURRENT_DIR.parents[1]
for _p in (str(_CURRENT_DIR), str(_REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import uvicorn
from twilio_agent.phone_audio_bridge.audio_bridge import LaptopAudioBridge, MockAudioBridge
from twilio_agent.phone_audio_bridge.audio_io import test_audio_loopback
from twilio_agent.phone_audio_bridge.config import BridgeConfig
from twilio_agent.phone_audio_bridge.preflight_check import run_preflight_check
from twilio_agent.phone_audio_bridge.server import create_app
from twilio_agent.phone_audio_bridge.twilio_handler import TwilioCallManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("phone_audio_bridge.main")


def start_tunnel(port: int, authtoken: Optional[str] = None) -> Optional[str]:
    """Start pyngrok tunnel if available and return public HTTPS URL."""
    try:
        from pyngrok import conf, ngrok

        if authtoken:
            ngrok.set_auth_token(authtoken)

        tunnel = ngrok.connect(port, "http")
        public_url = tunnel.public_url
        if public_url.startswith("http://"):
            public_url = public_url.replace("http://", "https://", 1)
        logger.info("Tunnel established: %s -> http://127.0.0.1:%d", public_url, port)
        return public_url
    except Exception as e:
        logger.warning("Could not auto-start pyngrok tunnel: %s", e)
        print("\n💡 NOTE: If you don't have pyngrok configured:")
        print(f"   1. Run 'ngrok http {port}' or 'cloudflared tunnel' in a separate terminal.")
        print(f"   2. Copy the https URL into your .env file as PUBLIC_URL=https://...\n")
        return None


def get_stream_url(public_url: str) -> str:
    """Derive WebSocket stream URL (wss://) from public HTTPS URL."""
    clean_url = public_url.strip().rstrip("/")
    if clean_url.startswith("https://"):
        return clean_url.replace("https://", "wss://", 1) + "/media-stream"
    elif clean_url.startswith("http://"):
        return clean_url.replace("http://", "ws://", 1) + "/media-stream"
    elif clean_url.startswith("wss://") or clean_url.startswith("ws://"):
        return clean_url if clean_url.endswith("/media-stream") else f"{clean_url}/media-stream"
    return f"wss://{clean_url}/media-stream"


async def monitor_keyboard_hangup(call_manager: TwilioCallManager):
    """Monitors standard input for user pressing Enter or 'q' to hang up early."""
    loop = asyncio.get_running_loop()

    def read_key():
        try:
            if not sys.stdin or not hasattr(sys.stdin, "isatty") or not sys.stdin.isatty():
                return None
            print("\n  👉 Press ENTER or type 'q' then ENTER at any time to HANG UP immediately...\n")
            line = sys.stdin.readline()
            if not line:
                return None
            return line.strip()
        except Exception:
            return None

    while call_manager.active_call_sid:
        key = await loop.run_in_executor(None, read_key)
        if key is None:
            await asyncio.sleep(1.0)
            continue
        if call_manager.active_call_sid:
            print("\n🛑 Hangup requested by user in terminal.")
            await call_manager.hangup_call()
            break


async def run_live_bridge(dry_run: bool = False):
    """Main flow: start server, setup tunnel, prompt confirmation, dial, and bridge."""
    cfg = BridgeConfig.from_env()
    if dry_run:
        # Override to dry run
        object.__setattr__(cfg, "dry_run", True)

    # 1. Validation Check
    if not cfg.dry_run:
        errors = cfg.validate_for_call()
        if errors:
            print("\n❌ Configuration errors detected in .env:")
            for err in errors:
                print(f"   - {err}")
            print("\nPlease fix these settings in .env or run 'python main.py check' for diagnostics.\n")
            return

    # 2. Public URL Resolution
    public_url = cfg.public_url
    ngrok_tunnel = None
    if public_url.lower() == "auto":
        print("Starting public tunnel for Twilio webhook...")
        public_url = start_tunnel(cfg.port, cfg.ngrok_authtoken)
        if not public_url and not cfg.dry_run:
            print("❌ Cannot proceed without a public URL. Please configure PUBLIC_URL in .env.")
            return
        elif not public_url and cfg.dry_run:
            public_url = f"http://127.0.0.1:{cfg.port}"

    stream_url = get_stream_url(public_url)
    logger.info("Twilio Stream URL: %s", stream_url)

    # 3. Initialize Audio Bridge & Call Manager
    bridge = MockAudioBridge() if cfg.dry_run else LaptopAudioBridge()
    call_manager = TwilioCallManager(cfg)

    # 4. Create FastAPI app
    app = create_app(config=cfg, audio_bridge=bridge, call_manager=call_manager)

    # 5. Start Uvicorn Server in background thread
    server_config = uvicorn.Config(
        app,
        host=cfg.host,
        port=cfg.port,
        log_level="warning",
    )
    server = uvicorn.Server(server_config)

    server_thread = threading.Thread(target=server.run, daemon=True, name="uvicorn-server")
    server_thread.start()

    # Wait for server to bind
    await asyncio.sleep(0.5)
    logger.info("Local server listening on http://%s:%d", cfg.host, cfg.port)

    # 6. Place Outbound Call with Confirmation & Safeguards
    try:
        call_sid = await call_manager.initiate_call(stream_url=stream_url)
        if not call_sid:
            # User rejected confirmation prompt
            return

        # Start keyboard listener for early hangup
        hangup_listener = asyncio.create_task(monitor_keyboard_hangup(call_manager))

        # Wait until call terminates (either via watchdog, phone hangup, or 'q')
        while call_manager.active_call_sid:
            await asyncio.sleep(0.5)

        hangup_listener.cancel()

    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("\nInterrupted by user. Triggering immediate hangup...")
        await call_manager.hangup_call()
    finally:
        server.should_exit = True
        if ngrok_tunnel:
            try:
                from pyngrok import ngrok
                ngrok.kill()
            except Exception:
                pass


def main():
    parser = argparse.ArgumentParser(
        description="Twilio Phone-to-Laptop Real-Time Audio Bridge"
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="run",
        choices=["run", "dry-run", "check", "test-audio"],
        help="Command to execute (default: run)",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=None,
        help="Override MAX_CALL_DURATION_SECONDS for this run",
    )

    args = parser.parse_args()

    if args.command == "check":
        run_preflight_check()
    elif args.command == "test-audio":
        duration = args.duration or 5
        asyncio.run(test_audio_loopback(duration_seconds=duration))
    elif args.command == "dry-run":
        asyncio.run(run_live_bridge(dry_run=True))
    elif args.command == "run":
        asyncio.run(run_live_bridge(dry_run=False))


if __name__ == "__main__":
    main()
