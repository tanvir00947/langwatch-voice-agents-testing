"""Configuration and safety settings for the Twilio Phone-to-Laptop Audio Bridge."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

# Automatically use Windows native system certificate store for corporate proxies/SSL
try:
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass

# Path to the .env file in this package
BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
if ENV_PATH.exists():
    load_dotenv(ENV_PATH, override=True)
else:
    # Fallback to root .env if present
    load_dotenv(override=False)


def normalize_phone_number(number: str) -> str:
    """Normalize phone number: strip spaces, dashes, and duplicate '+' signs."""
    if not number:
        return ""
    clean = number.strip().replace(" ", "").replace("-", "")
    if clean.startswith("+"):
        clean = "+" + clean.lstrip("+")
    return clean


def is_valid_e164(number: str) -> bool:
    """Validate E.164 international phone number format (+ followed by 10-15 digits)."""
    norm = normalize_phone_number(number)
    if not norm:
        return False
    return bool(re.match(r"^\+[1-9]\d{6,14}$", norm))


def is_indian_number(number: str) -> bool:
    """Check if the phone number is an Indian mobile / telephone number (+91)."""
    norm = normalize_phone_number(number)
    if not norm:
        return False
    return norm.startswith("+91")


@dataclass(frozen=True)
class BridgeConfig:
    """Immutable runtime configuration with built-in safeguards."""

    account_sid: str
    auth_token: str
    twilio_phone_number: str
    to_phone_number: str
    public_url: str
    ngrok_authtoken: Optional[str]
    host: str
    port: int
    max_duration_seconds: int
    require_confirmation: bool
    dry_run: bool

    # Twilio Audio Stream specifications
    twilio_sample_rate: int = 8000
    twilio_channels: int = 1
    twilio_bytes_per_sample: int = 2  # Linear PCM 16-bit
    chunk_size_samples: int = 160  # 20ms at 8000Hz (standard telecom frame)

    @classmethod
    def from_env(cls) -> "BridgeConfig":
        """Load and validate configuration from environment variables."""
        account_sid = os.environ.get("TWILIO_ACCOUNT_SID", "").strip()
        auth_token = os.environ.get("TWILIO_AUTH_TOKEN", "").strip()
        twilio_phone = normalize_phone_number(os.environ.get("TWILIO_PHONE_NUMBER", ""))
        to_phone = normalize_phone_number(os.environ.get("TO_PHONE_NUMBER", ""))
        public_url = os.environ.get("PUBLIC_URL", "auto").strip()
        ngrok_authtoken = os.environ.get("NGROK_AUTHTOKEN", "").strip() or None
        host = os.environ.get("SERVER_HOST", "0.0.0.0").strip()
        port = int(os.environ.get("SERVER_PORT", "8000").strip())

        # Safety safeguards: duration limit and confirmation
        raw_duration = os.environ.get("MAX_CALL_DURATION_SECONDS", "60").strip()
        try:
            max_duration = int(raw_duration)
            if max_duration <= 0:
                max_duration = 60
        except ValueError:
            max_duration = 60

        require_confirmation = (
            os.environ.get("REQUIRE_CONFIRMATION", "true").strip().lower()
            in ("true", "1", "yes")
        )
        dry_run = (
            os.environ.get("DRY_RUN", "false").strip().lower()
            in ("true", "1", "yes")
        )

        return cls(
            account_sid=account_sid,
            auth_token=auth_token,
            twilio_phone_number=twilio_phone,
            to_phone_number=to_phone,
            public_url=public_url,
            ngrok_authtoken=ngrok_authtoken,
            host=host,
            port=port,
            max_duration_seconds=max_duration,
            require_confirmation=require_confirmation,
            dry_run=dry_run,
        )

    def validate_for_call(self) -> list[str]:
        """Validate readiness to place a call. Returns list of error messages (empty if valid)."""
        errors = []
        if self.dry_run:
            return errors  # Dry run doesn't require live credentials

        if not self.account_sid or not self.account_sid.startswith("AC"):
            errors.append("Invalid or missing TWILIO_ACCOUNT_SID (must start with 'AC')")
        if not self.auth_token:
            errors.append("Missing TWILIO_AUTH_TOKEN")
        if not is_valid_e164(self.twilio_phone_number):
            errors.append(f"TWILIO_PHONE_NUMBER must be in E.164 format (+XXXXXXXXXXX), got '{self.twilio_phone_number}'")
        if not is_valid_e164(self.to_phone_number):
            errors.append(f"TO_PHONE_NUMBER must be in E.164 format (+XXXXXXXXXXX), got '{self.to_phone_number}'")
        if not self.public_url:
            errors.append("PUBLIC_URL must be specified (or set to 'auto' for pyngrok)")

        return errors

