"""Render candlestick charts from Webull history-bar data for Telegram."""

from __future__ import annotations

import io
import logging
from datetime import datetime
from typing import Any

import matplotlib

matplotlib.use("Agg")  # headless rendering

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

logger = logging.getLogger(__name__)

# Dark TradingView-ish palette.
_BG = "#131722"
_UP = "#26a69a"
_DOWN = "#ef5350"
_TEXT = "#d1d4dc"
_GRID = "#2a2e39"


def render_candlestick(symbol: str, bars: list[dict[str, Any]], title: str = "") -> io.BytesIO:
    """Render OHLC bars to a PNG in memory. `bars` are Webull history-bar dicts."""
    times, opens, highs, lows, closes, volumes = [], [], [], [], [], []
    for b in sorted(bars, key=lambda x: x["time"]):
        times.append(datetime.fromisoformat(b["time"].replace("Z", "+0000").replace("+0000", "+00:00")))
        opens.append(float(b["open"]))
        highs.append(float(b["high"]))
        lows.append(float(b["low"]))
        closes.append(float(b["close"]))
        volumes.append(float(b.get("volume", 0)))

    fig, (ax, vol_ax) = plt.subplots(
        2, 1, figsize=(9, 5.5), sharex=True,
        gridspec_kw={"height_ratios": [4, 1], "hspace": 0.03},
    )
    fig.patch.set_facecolor(_BG)

    for ax_ in (ax, vol_ax):
        ax_.set_facecolor(_BG)
        ax_.grid(True, color=_GRID, linewidth=0.5, alpha=0.7)
        ax_.tick_params(colors=_TEXT, labelsize=8)
        for spine in ax_.spines.values():
            spine.set_color(_GRID)

    width = mdates.date2num(times[1]) - mdates.date2num(times[0])
    candle_w = width * 0.7

    for t, o, h, l, c in zip(times, opens, highs, lows, closes):
        color = _UP if c >= o else _DOWN
        tn = mdates.date2num(t)
        ax.plot([tn, tn], [l, h], color=color, linewidth=0.8)
        body = Rectangle(
            (tn - candle_w / 2, min(o, c)), candle_w, abs(c - o) or 1e-9,
            facecolor=color, edgecolor=color,
        )
        ax.add_patch(body)

    vol_colors = [_UP if c >= o else _DOWN for o, c in zip(opens, closes)]
    vol_ax.bar([mdates.date2num(t) for t in times], volumes, width=candle_w, color=vol_colors)

    ax.set_title(title or f"{symbol}", color=_TEXT, fontsize=12, pad=8, loc="left")
    ax.xaxis_date()
    vol_ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    vol_ax.tick_params(axis="x", rotation=0)
    fig.autofmt_xdate(rotation=0)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight", facecolor=_BG)
    plt.close(fig)
    buf.seek(0)
    return buf
