from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

from .models import TradingViewAlert


@dataclass
class PendingOrder:
    id: str
    alert: TradingViewAlert
    created_at: float = field(default_factory=time.time)


class PendingStore:
    """In-memory store of orders awaiting Telegram confirmation.

    Ephemeral by design: pending confirmations are lost on restart, which is
    the safe default (a restarted bot won't fire stale trades).
    """

    def __init__(self, ttl_seconds: int = 3600) -> None:
        self._items: dict[str, PendingOrder] = {}
        self._ttl = ttl_seconds

    def add(self, alert: TradingViewAlert) -> PendingOrder:
        self._evict_expired()
        order = PendingOrder(id=uuid.uuid4().hex[:12], alert=alert)
        self._items[order.id] = order
        return order

    def pop(self, order_id: str) -> PendingOrder | None:
        self._evict_expired()
        return self._items.pop(order_id, None)

    def _evict_expired(self) -> None:
        now = time.time()
        expired = [k for k, v in self._items.items() if now - v.created_at > self._ttl]
        for k in expired:
            self._items.pop(k, None)


pending_store = PendingStore()
