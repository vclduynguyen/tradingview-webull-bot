import sys
from enum import Enum

from pydantic import ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict


class ExecutionMode(str, Enum):
    CONFIRM = "confirm"
    AUTO = "auto"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Server
    webhook_secret: str

    # Execution
    execution_mode: ExecutionMode = ExecutionMode.CONFIRM

    # Autonomous strategy (used when a signal arrives without qty/notional)
    position_size_usd: float = 1000.0  # dollars to deploy per new position
    max_positions: int = 5  # max simultaneous open positions
    allow_shorting: bool = False  # S2O/B2C need a margin account

    # Webull OpenAPI
    webull_app_key: str
    webull_app_secret: str
    # Region: us, hk, jp, sg, th, au, my, uk, br, mx, za, eu
    webull_region_id: str = "us"
    # Leave blank to auto-pick the first account from your Webull account list.
    webull_account_id: str = ""
    # true  = sandbox (paper trading), false = LIVE (real money)
    webull_paper: bool = True

    # Telegram
    telegram_bot_token: str
    telegram_chat_id: int


def _load_settings() -> Settings:
    try:
        return Settings()
    except ValidationError as exc:
        missing = [".".join(str(p) for p in e["loc"]).upper() for e in exc.errors() if e["type"] == "missing"]
        other = [e for e in exc.errors() if e["type"] != "missing"]
        lines = ["", "=" * 60, "CONFIGURATION ERROR - the bot cannot start.", ""]
        if missing:
            lines.append("Missing required environment variables:")
            lines += [f"  - {m}" for m in missing]
            lines.append("")
            lines.append("Set them in your .env file (local) or in Railway -> Variables (cloud).")
        for e in other:
            lines.append(f"Invalid {'.'.join(str(p) for p in e['loc']).upper()}: {e['msg']}")
        lines += ["See .env.example for the full list.", "=" * 60, ""]
        sys.stderr.write("\n".join(lines))
        sys.exit(1)


settings = _load_settings()
