"""Pre-Flight Verification and Indian Telecom Diagnostics.

Performs verification of:
1. Twilio Account SID & Auth Token credentials.
2. Destination number formatting & Twilio Voice capability.
3. Twilio Trial Account restrictions & Verified Caller ID check.
4. Indian Mobile Number (+91) Voice Geographic Permissions requirements.
5. Laptop microphone & speaker hardware detection.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any, Optional

# Ensure Windows terminal handles Unicode cleanly
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

_CURRENT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _CURRENT_DIR.parents[1]
for _p in (str(_CURRENT_DIR), str(_REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)
from twilio.rest import Client
import pyaudio

from twilio_agent.phone_audio_bridge.config import (
    BridgeConfig,
    is_indian_number,
    is_valid_e164,
)

logger = logging.getLogger("phone_audio_bridge.preflight")


def check_audio_hardware() -> tuple[bool, str]:
    """Verify laptop microphone and speaker availability."""
    p = pyaudio.PyAudio()
    try:
        count = p.get_device_count()
        if count == 0:
            return False, "No audio input/output devices found on this system."

        try:
            default_in = p.get_default_input_device_info()
            in_name = default_in.get("name", "Unknown Mic")
        except Exception:
            return False, "No default microphone detected."

        try:
            default_out = p.get_default_output_device_info()
            out_name = default_out.get("name", "Unknown Speaker")
        except Exception:
            return False, "No default speaker detected."

        return True, f"Mic: '{in_name}' | Speaker: '{out_name}'"
    finally:
        p.terminate()


def run_preflight_check(config: Optional[BridgeConfig] = None) -> bool:
    """Run diagnostics and return True if system is ready for calls."""
    if config is None:
        config = BridgeConfig.from_env()

    print("\n" + "=" * 70)
    print("      🔍 PRE-FLIGHT DIAGNOSTICS & TELECOM RESTRICTIONS CHECK")
    print("=" * 70)

    all_passed = True
    warnings_list: list[str] = []

    # 1. Hardware Check
    hw_ok, hw_msg = check_audio_hardware()
    if hw_ok:
        print(f"  [1/5] Audio Hardware:         ✅ OK ({hw_msg})")
    else:
        print(f"  [1/5] Audio Hardware:         ❌ FAILED: {hw_msg}")
        all_passed = False

    # 2. Basic Configuration Format Check
    config_errors = config.validate_for_call()
    if not config_errors:
        print(f"  [2/5] Configuration:          ✅ OK (SID, Token, Numbers formatted)")
    else:
        print(f"  [2/5] Configuration:          ❌ MISSING / INVALID:")
        for err in config_errors:
            print(f"        - {err}")
        all_passed = False

    # Check Indian number
    is_in = is_indian_number(config.to_phone_number)

    # 3. Twilio Account & Credential Live Check
    if not config.dry_run and config.account_sid.startswith("AC") and config.auth_token:
        try:
            client = Client(config.account_sid, config.auth_token)
            account = client.api.accounts(config.account_sid).fetch()
            account_type = getattr(account, "type", "Standard")
            status = getattr(account, "status", "active")
            print(f"  [3/5] Twilio Authentication:  ✅ OK (Status: {status}, Type: {account_type})")

            # Check Caller ID verification for trial accounts
            is_trial = account_type.lower() == "trial"
            if is_trial:
                print("\n  ℹ️  [TWILIO TRIAL ACCOUNT DETECTED]")
                print("     Twilio Trial accounts have two strict rules:")
                print("     a) You can ONLY call verified phone numbers.")
                print("     b) Twilio plays a trial greeting before connecting the call.")

                # Check if TO_PHONE_NUMBER is in verified caller IDs
                verified_numbers = [
                    v.phone_number for v in client.outgoing_caller_ids.list()
                ]
                clean_to = config.to_phone_number.replace(" ", "")
                if clean_to in verified_numbers:
                    print(f"     ✅ Destination {clean_to} is VERIFIED in your Twilio Console.")
                else:
                    print(f"     ⚠️  DESTINATION {clean_to} IS NOT VERIFIED!")
                    print("     Your call WILL FAIL with Twilio Error 21216.")
                    print("     👉 Please verify your phone number now at:")
                    print("     https://console.twilio.com/us1/develop/phone-numbers/manage/verified")
                    warnings_list.append("Destination number not in Twilio Verified Caller IDs.")
                    all_passed = False

            # Check Twilio Phone Number Voice capability
            numbers = client.incoming_phone_numbers.list(phone_number=config.twilio_phone_number)
            if numbers:
                voice_enabled = numbers[0].capabilities.get("voice", False)
                if voice_enabled:
                    print(f"  [4/5] Twilio Caller ID Voice: ✅ OK ({config.twilio_phone_number} has Voice)")
                else:
                    print(f"  [4/5] Twilio Caller ID Voice: ❌ {config.twilio_phone_number} lacks Voice capability!")
                    all_passed = False
            else:
                print(f"  [4/5] Twilio Caller ID Voice: ℹ️  Number check skipped (Active in project)")

        except Exception as e:
            print(f"  [3/5] Twilio Authentication:  ❌ FAILED: {e}")
            all_passed = False
    elif config.dry_run:
        print(f"  [3/5] Twilio Authentication:  ⚡ SKIPPED (DRY_RUN is enabled)")
        print(f"  [4/5] Twilio Caller ID Voice: ⚡ SKIPPED (DRY_RUN is enabled)")
    else:
        print(f"  [3/5] Twilio Authentication:  ❌ SKIPPED (Missing credentials)")
        all_passed = False

    # 4. Indian Mobile Telecom Regulations & Geo-Permissions
    print(f"  [5/5] Country Regulations:    " + ("🇮🇳 INDIA (+91)" if is_in else "International"))
    if is_in:
        print("\n  " + "-" * 66)
        print("  🇮🇳  TWILIO RESTRICTIONS FOR CALLING INDIA (+91):")
        print("  " + "-" * 66)
        print("  1. VOICE GEOGRAPHIC PERMISSIONS (CRITICAL):")
        print("     By default, Twilio BLOCKS outbound voice calls to India.")
        print("     If you have not enabled India in Voice Geo Permissions,")
        print("     Twilio will reject the call with Error 21215.")
        print("     👉 Enable India here:")
        print("     https://console.twilio.com/us1/develop/voice/settings/geo-permissions")
        print("     (Search 'India', tick the checkbox, and click Save)")
        print("")
        print("  2. NUMBER FORMATTING:")
        print("     Must be full E.164 format: +91 followed by 10 digits.")
        print(f"     Configured: {config.to_phone_number} -> " + ("Valid E.164" if is_valid_e164(config.to_phone_number) else "INVALID FORMAT"))
        print("")
        print("  3. CALL TIME LIMIT SAFEGUARD:")
        print(f"     Max duration is capped at {config.max_duration_seconds}s to preserve your trial balance.")
        print("  " + "-" * 66)

    print("\n" + "=" * 70)
    if all_passed:
        print("  🎉 PRE-FLIGHT CHECK: ALL SYSTEMS READY FOR LIVE CALL!")
    else:
        print("  ⚠️  PRE-FLIGHT CHECK: ISSUES DETECTED. Review errors above before dialing.")
    print("=" * 70 + "\n")

    return all_passed


if __name__ == "__main__":
    run_preflight_check()
