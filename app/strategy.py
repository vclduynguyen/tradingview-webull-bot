"""Autonomous position management for MMG signals.

When a signal arrives without an explicit qty/notional, this module decides
whether to trade and how much, based on current holdings and risk settings.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

from .broker import broker
from .config import settings
from .models import MMGSignal, OrderType, Side, TradingViewAlert

logger = logging.getLogger(__name__)

_OPEN_SIGNALS = {MMGSignal.B2O, MMGSignal.S2O}
_CLOSE_SIGNALS = {MMGSignal.S2C, MMGSignal.B2C}
_SHORT_SIGNALS = {MMGSignal.S2O, MMGSignal.B2C}


@dataclass
class Plan:
    alert: TradingViewAlert | None  # sized order to place, or None to skip
    reason: str  # human-readable explanation


def plan_trade(alert: TradingViewAlert) -> Plan:
    """Turn an unsized signal into a concrete order (or a skip with a reason)."""
    if not alert.needs_sizing:
        return Plan(alert, "explicit size provided")

    symbol = alert.symbol.upper()
    signal = alert.signal

    if signal in _SHORT_SIGNALS and not settings.allow_shorting:
        return Plan(None, f"{signal.value} is a short-side signal; shorting is disabled (cash account).")

    held = broker.held_qty(symbol)
    is_close = (signal in _CLOSE_SIGNALS) if signal else (alert.side == Side.SELL)

    if is_close:
        if held <= 0:
            return Plan(None, f"No open position in {symbol} to close.")
        sized = alert.model_copy(update={"qty": held, "order_type": OrderType.MARKET, "limit_price": None})
        return Plan(sized, f"Closing full position: {held:g} shares.")

    # Opening a new long position
    if held > 0:
        return Plan(None, f"Already holding {held:g} {symbol}; not adding.")

    positions = broker.get_positions()
    open_count = sum(1 for p in positions if broker.position_qty(p) > 0)
    if open_count >= settings.max_positions:
        return Plan(None, f"Max positions reached ({open_count}/{settings.max_positions}).")

    price = broker.current_price(symbol)
    qty = math.floor(settings.position_size_usd / price)
    if qty < 1:
        return Plan(
            None,
            f"{symbol} @ ${price:.2f} exceeds position size ${settings.position_size_usd:.0f}; skipping.",
        )

    sized = alert.model_copy(update={"qty": float(qty), "order_type": OrderType.MARKET, "limit_price": None})
    return Plan(
        sized,
        f"Opening position {open_count + 1}/{settings.max_positions}: "
        f"{qty} shares @ ~${price:.2f} (~${qty * price:,.0f}).",
    )
