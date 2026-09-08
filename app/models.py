from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, model_validator

from .config import ExecutionMode


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"


class MMGSignal(str, Enum):
    """Signals emitted by the MMG (Market Maker Genie) TradingView indicator."""

    B2O = "B2O"  # Buy to Open   -> open long  -> BUY
    S2C = "S2C"  # Sell to Close -> close long -> SELL
    S2O = "S2O"  # Sell to Open  -> open short -> SELL (needs a margin account)
    B2C = "B2C"  # Buy to Close  -> cover short -> BUY


# Maps an MMG signal to the order side we submit.
_MMG_TO_SIDE = {
    MMGSignal.B2O: "buy",
    MMGSignal.S2C: "sell",
    MMGSignal.S2O: "sell",
    MMGSignal.B2C: "buy",
}


class TradingViewAlert(BaseModel):
    """JSON payload TradingView sends to the /webhook endpoint.

    Example:
        {
          "secret": "your-webhook-secret",
          "symbol": "AAPL",
          "side": "buy",
          "qty": 1,
          "order_type": "market",
          "mode": "confirm"
        }
    """

    secret: str
    symbol: str
    # Provide either `side` (buy/sell) directly, or an MMG `signal` (B2O/S2C/...).
    side: Optional[Side] = None
    signal: Optional[MMGSignal] = None
    order_type: OrderType = OrderType.MARKET

    # Provide at most one of qty (share count) or notional (dollar amount).
    # Omit both to let the bot auto-size the trade (autonomous mode).
    qty: Optional[float] = Field(default=None, gt=0)
    notional: Optional[float] = Field(default=None, gt=0)

    # Required for limit orders.
    limit_price: Optional[float] = Field(default=None, gt=0)

    # Optional per-alert override of the global EXECUTION_MODE.
    mode: Optional[ExecutionMode] = None

    @model_validator(mode="after")
    def _validate(self) -> "TradingViewAlert":
        # Resolve side from an MMG signal if side wasn't given explicitly.
        if self.side is None and self.signal is not None:
            self.side = Side(_MMG_TO_SIDE[self.signal])
        if self.side is None:
            raise ValueError("Provide either 'side' (buy/sell) or 'signal' (B2O/S2C/S2O/B2C).")
        if self.qty is not None and self.notional is not None:
            raise ValueError("Provide only one of 'qty' or 'notional', not both.")
        if self.order_type == OrderType.LIMIT and self.limit_price is None:
            raise ValueError("'limit_price' is required for limit orders.")
        return self

    @property
    def needs_sizing(self) -> bool:
        """True when neither qty nor notional was given -> bot decides size."""
        return self.qty is None and self.notional is None

    def human_summary(self) -> str:
        if self.needs_sizing:
            amount = "auto-sized"
        else:
            amount = f"{self.qty} shares" if self.qty is not None else f"${self.notional}"
        prefix = f"[{self.signal.value}] " if self.signal else ""
        line = f"{prefix}{self.side.value.upper()} {amount} of {self.symbol.upper()} ({self.order_type.value})"
        if self.order_type == OrderType.LIMIT:
            line += f" @ {self.limit_price}"
        return line
