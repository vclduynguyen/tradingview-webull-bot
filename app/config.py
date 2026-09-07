from enum import Enum

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


settings = Settings()
