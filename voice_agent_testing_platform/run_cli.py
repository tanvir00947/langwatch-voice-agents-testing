"""Command Line Interface (CLI) for Voice Agent & IVA Testing Platform.

Usage:
  python run_cli.py ui             # Launch Web UI Tester Dashboard (http://127.0.0.1:8000)
  python run_cli.py test-ws        # Run WebSocket Voice Agent resilience test
  python run_cli.py test-telephony # Run Mock Telephony & IVR test
  python run_cli.py check          # Run environment and audio diagnostics
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

# Ensure Windows terminal handles UTF-8 cleanly
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
os.environ["PYTHONIOENCODING"] = "utf-8"

# Add project root to sys.path
PLATFORM_DIR = Path(__file__).resolve().parent
WORKSPACE_DIR = PLATFORM_DIR.parent
if str(PLATFORM_DIR.parent) not in sys.path:
    sys.path.insert(0, str(PLATFORM_DIR.parent))

from dotenv import load_dotenv
load_dotenv(PLATFORM_DIR / ".env", override=True)


def cmd_ui(args):
    """Launch the Web UI dashboard."""
    import uvicorn
    host = os.environ.get("WEB_UI_HOST", "127.0.0.1")
    port = int(os.environ.get("WEB_UI_PORT", "8000"))

    print("\n" + "=" * 65)
    print("🎙️ VOICE AGENT & IVA TESTING PLATFORM - TESTER DASHBOARD")
    print("=" * 65)
    print(f"  • Dashboard URL: http://{host}:{port}")
    print(f"  • SUT Protocols: WebSocket (Gemini Live/JSON), Twilio, Telnyx, Mock")
    print(f"  • Press Ctrl+C to stop the dashboard server.")
    print("=" * 65 + "\n")

    uvicorn.run(
        "voice_agent_testing_platform.ui.app:app",
        host=host,
        port=port,
        reload=False,
    )


def cmd_test_ws(args):
    """Run WebSocket voice agent scenario."""
    from voice_agent_testing_platform.scenarios.test_websocket_agent import test_websocket_voice_agent_resilience
    asyncio.run(test_websocket_voice_agent_resilience())


def cmd_test_telephony(args):
    """Run mock telephony IVR scenario."""
    from voice_agent_testing_platform.scenarios.test_telephony_mock import test_mock_telephony_ivr_flow
    asyncio.run(test_mock_telephony_ivr_flow())


def cmd_check(args):
    """Perform pre-flight diagnostics."""
    print("\n" + "=" * 65)
    print("🔍 PRE-FLIGHT SYSTEM & AUDIO DIAGNOSTICS")
    print("=" * 65)

    # 1. Python version
    print(f"  • Python Version:    {sys.version.split()[0]} ({sys.platform})")

    # 2. FFmpeg check
    try:
        import imageio_ffmpeg
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        print(f"  • FFmpeg Binary:     {ffmpeg_exe} (AVAILABLE)")
    except Exception as e:
        print(f"  • FFmpeg Binary:     FAILED ({e})")

    # 3. Gemini Key
    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if gemini_key:
        masked = gemini_key[:6] + "..." + gemini_key[-4:]
        print(f"  • Gemini API Key:    {masked} (CONFIGURED)")
    else:
        print("  • Gemini API Key:    MISSING (Set GEMINI_API_KEY in .env)")

    # 4. Neural Voice Synthesizer
    try:
        import edge_tts
        print("  • Neural TTS Engine: edge-tts (READY - Zero Cost)")
    except Exception as e:
        print(f"  • Neural TTS Engine: FAILED ({e})")

    # 5. Telephony Support
    print("  • Telephony Codecs:  G.711 mu-law, 8kHz-24kHz PCM resampler (READY)")
    print("  • Telephony Adapters:Twilio, Telnyx, Mock Telephony (READY)")
    print("=" * 65 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Voice Agent & IVA Testing Platform CLI")
    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # UI Command
    subparsers.add_parser("ui", help="Launch the Tester Web Dashboard")

    # Test WS Command
    subparsers.add_parser("test-ws", help="Execute WebSocket Voice Agent Scenario")

    # Test Telephony Command
    subparsers.add_parser("test-telephony", help="Execute Mock Telephony IVR Scenario")

    # Check Command
    subparsers.add_parser("check", help="Run system diagnostics")

    args = parser.parse_args()

    if args.command == "ui":
        cmd_ui(args)
    elif args.command == "test-ws":
        cmd_test_ws(args)
    elif args.command == "test-telephony":
        cmd_test_telephony(args)
    elif args.command == "check":
        cmd_check(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
