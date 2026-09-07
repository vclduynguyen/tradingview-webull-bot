import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request

from .broker import broker
from .config import settings
from .models import TradingViewAlert
from .telegram_bot import notifier

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("tvbot")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await notifier.start()
    try:
        await notifier.send(
            f"🤖 TradingView bot online.\nBroker: {broker.mode_label}\n"
            f"Execution mode: {settings.execution_mode.value}"
        )
    except Exception as exc:  # don't crash startup if Telegram is misconfigured
        logger.warning("Could not send startup Telegram message: %s", exc)
    yield
    await notifier.stop()


app = FastAPI(title="TradingView -> Alpaca Bot", lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "broker": broker.mode_label, "mode": settings.execution_mode.value}


@app.post("/webhook")
async def webhook(request: Request) -> dict:
    # TradingView sends the alert message body as JSON.
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Body must be valid JSON.")

    try:
        alert = TradingViewAlert(**payload)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Invalid alert: {exc}")

    # Authenticate via shared secret (constant-time-ish compare).
    if alert.secret != settings.webhook_secret:
        raise HTTPException(status_code=401, detail="Invalid secret.")

    logger.info("Alert accepted: %s", alert.human_summary())
    return await notifier.route_alert(alert, source="TradingView")
