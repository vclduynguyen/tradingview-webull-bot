from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from webull.core.client import ApiClient
from webull.data.data_client import DataClient
from webull.trade.trade_client import TradeClient

from .config import settings
from .models import OrderType, Side, TradingViewAlert

logger = logging.getLogger(__name__)

_US_STOCK = "US_STOCK"

# Sandbox = paper trading, prod = live money.
_SANDBOX_ENDPOINT = "api.sandbox.webull.com"
_PROD_ENDPOINT = "api.webull.com"

_SIDE_MAP = {Side.BUY: "BUY", Side.SELL: "SELL"}
_ORDER_TYPE_MAP = {OrderType.MARKET: "MARKET", OrderType.LIMIT: "LIMIT"}


@dataclass
class OrderResult:
    ok: bool
    message: str
    order_id: str | None = None


class Broker:
    """Wrapper around the Webull OpenAPI trading client (sandbox or live)."""

    def __init__(self) -> None:
        self.region = settings.webull_region_id
        self.market = self.region.upper()
        self._endpoint = _SANDBOX_ENDPOINT if settings.webull_paper else _PROD_ENDPOINT
        self._account_id = settings.webull_account_id or None
        self._trade: TradeClient | None = None
        self._data: DataClient | None = None

    def _new_api_client(self) -> ApiClient:
        api_client = ApiClient(
            settings.webull_app_key, settings.webull_app_secret, self.region
        )
        api_client.add_endpoint(self.region, self._endpoint)
        return api_client

    @property
    def mode_label(self) -> str:
        return "PAPER" if settings.webull_paper else "LIVE"

    @property
    def trade(self) -> TradeClient:
        """Lazily build the Webull client. Constructing TradeClient
        authenticates against Webull, so we defer it until first use to keep
        app startup independent of credential/network state."""
        if self._trade is None:
            self._trade = TradeClient(self._new_api_client())
        return self._trade

    @property
    def data(self) -> DataClient:
        """Lazily build the Webull market-data client."""
        if self._data is None:
            self._data = DataClient(self._new_api_client())
        return self._data

    def account_id(self) -> str:
        """Return the configured account id, or auto-fetch the first one."""
        if self._account_id:
            return self._account_id
        res = self.trade.account_v2.get_account_list()
        if res.status_code != 200:
            raise RuntimeError(f"Could not fetch Webull accounts: {res.status_code} {res.text}")
        data = res.json()
        accounts = data.get("data", data) if isinstance(data, dict) else data
        if not accounts:
            raise RuntimeError("No Webull accounts found for these credentials.")
        first = accounts[0]
        self._account_id = str(first.get("account_id") or first.get("accountId"))
        logger.info("Using Webull account_id=%s", self._account_id)
        return self._account_id

    def _build_order(self, alert: TradingViewAlert) -> dict:
        if alert.needs_sizing:
            raise ValueError("Order has no qty/notional; run it through the strategy first.")
        order: dict = {
            "combo_type": "NORMAL",
            "client_order_id": uuid.uuid4().hex,  # 32 chars, unique per order
            "symbol": alert.symbol.upper(),
            "instrument_type": "EQUITY",
            "market": self.market,
            "order_type": _ORDER_TYPE_MAP[alert.order_type],
            "side": _SIDE_MAP[alert.side],
            "time_in_force": "DAY",
            "support_trading_session": "N",
        }
        if alert.notional is not None:
            # Dollar-amount order (fractional). Webull requires a MARKET order.
            order["entrust_type"] = "AMOUNT"
            order["order_type"] = "MARKET"
            order["total_cash_amount"] = str(alert.notional)
        else:
            order["entrust_type"] = "QTY"
            qty = alert.qty
            order["quantity"] = str(int(qty)) if float(qty).is_integer() else str(qty)
        if alert.order_type == OrderType.LIMIT and alert.notional is None:
            order["limit_price"] = str(alert.limit_price)
        return order

    def place_order(self, alert: TradingViewAlert) -> OrderResult:
        try:
            account_id = self.account_id()
            order = self._build_order(alert)
            res = self.trade.order_v2.place_order(account_id, [order])
        except Exception as exc:
            return OrderResult(ok=False, message=f"Webull request failed: {exc}")

        if res.status_code != 200:
            return OrderResult(ok=False, message=f"Webull rejected the order: {res.status_code} {res.text}")

        return OrderResult(
            ok=True,
            message=f"Order submitted ({self.mode_label}).",
            order_id=order["client_order_id"],
        )

    # ---- market data / account queries ----
    def get_quote(self, symbol: str) -> dict:
        """Return a snapshot dict for a US stock symbol."""
        res = self.data.market_data.get_snapshot(symbol.upper(), _US_STOCK)
        if res.status_code != 200:
            raise RuntimeError(f"Quote lookup failed: {res.status_code} {res.text}")
        data = res.json()
        if isinstance(data, list):
            if not data:
                raise RuntimeError(f"No data for '{symbol}'. Check the ticker.")
            return data[0]
        return data

    def get_company_name(self, symbol: str) -> str | None:
        try:
            res = self.data.instrument.get_company_profile(symbol.upper())
            if res.status_code == 200:
                d = res.json()
                d = d[0] if isinstance(d, list) and d else d
                return d.get("name") or d.get("company_name")
        except Exception:
            pass
        return None

    def get_balance(self) -> dict:
        res = self.trade.account_v2.get_account_balance(self.account_id())
        if res.status_code != 200:
            raise RuntimeError(f"Balance lookup failed: {res.status_code} {res.text}")
        return res.json()

    def get_positions(self) -> list:
        res = self.trade.account_v2.get_account_position(self.account_id())
        if res.status_code != 200:
            raise RuntimeError(f"Positions lookup failed: {res.status_code} {res.text}")
        data = res.json()
        if isinstance(data, dict):
            return data.get("holdings") or data.get("positions") or data.get("data") or []
        return data or []

    @staticmethod
    def position_symbol(p: dict) -> str:
        sym = p.get("symbol") or p.get("ticker")
        if not sym and isinstance(p.get("instrument"), dict):
            sym = p["instrument"].get("symbol")
        return (sym or "").upper()

    @staticmethod
    def position_qty(p: dict) -> float:
        for key in ("quantity", "qty", "position", "shares"):
            v = p.get(key)
            if v not in (None, ""):
                try:
                    return float(v)
                except (TypeError, ValueError):
                    pass
        return 0.0

    def held_qty(self, symbol: str) -> float:
        """Shares currently held for `symbol` (0 if none)."""
        symbol = symbol.upper()
        return sum(
            self.position_qty(p) for p in self.get_positions()
            if self.position_symbol(p) == symbol
        )

    def current_price(self, symbol: str) -> float:
        q = self.get_quote(symbol)
        for key in ("price", "close", "ask", "bid"):
            v = q.get(key)
            if v not in (None, ""):
                return float(v)
        raise RuntimeError(f"No price available for {symbol}.")


broker = Broker()
