import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from .broker import broker
from .charts import render_candlestick
from .config import ExecutionMode, settings
from .models import OrderType, Side, TradingViewAlert
from .store import pending_store
from .strategy import plan_trade

logger = logging.getLogger(__name__)

# Callback data prefixes for the inline confirm/cancel buttons.
CONFIRM_PREFIX = "confirm:"
CANCEL_PREFIX = "cancel:"

HELP_TEXT = (
    "<b>📊 Quotes &amp; Charts</b>\n"
    "/price SYMBOL — live quote + candlestick chart (e.g. <code>/price AAPL</code>)\n"
    "/chart SYMBOL [timespan] — chart only; timespan: M5 M30 H1 D1 W1 (e.g. <code>/chart TSLA D1</code>)\n\n"
    "<b>💰 Trading</b>\n"
    "/buy SYMBOL QTY [LIMIT] — buy shares (<code>/buy AAPL 2</code> or <code>/buy AAPL 2 190.50</code>)\n"
    "/sell SYMBOL QTY [LIMIT] — sell shares\n\n"
    "<b>📈 Account</b>\n"
    "/positions — your open holdings\n"
    "/balance — cash &amp; buying power\n"
    "/status — broker &amp; execution mode\n\n"
    "<b>ℹ️ Other</b>\n"
    "/help — this message"
)


def _authorized(update: Update) -> bool:
    chat = update.effective_chat
    return chat is not None and chat.id == settings.telegram_chat_id


class TelegramNotifier:
    """Owns the python-telegram-bot Application, notifications, and the
    confirm/cancel button flow."""

    def __init__(self) -> None:
        self.app: Application = (
            Application.builder().token(settings.telegram_bot_token).build()
        )
        self.app.add_handler(CommandHandler("start", self._on_start))
        self.app.add_handler(CommandHandler("help", self._on_help))
        self.app.add_handler(CommandHandler("status", self._on_status))
        self.app.add_handler(CommandHandler("price", self._on_price))
        self.app.add_handler(CommandHandler("quote", self._on_price))
        self.app.add_handler(CommandHandler("chart", self._on_chart))
        self.app.add_handler(CommandHandler("buy", self._on_buy))
        self.app.add_handler(CommandHandler("sell", self._on_sell))
        self.app.add_handler(CommandHandler("positions", self._on_positions))
        self.app.add_handler(CommandHandler("balance", self._on_balance))
        self.app.add_handler(CallbackQueryHandler(self._on_button))

    # ---- lifecycle ----
    async def start(self) -> None:
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling(drop_pending_updates=True)
        logger.info("Telegram bot started (polling).")

    async def stop(self) -> None:
        if self.app.updater and self.app.updater.running:
            await self.app.updater.stop()
        await self.app.stop()
        await self.app.shutdown()
        logger.info("Telegram bot stopped.")

    # ---- outbound ----
    async def send(self, text: str) -> None:
        await self.app.bot.send_message(
            chat_id=settings.telegram_chat_id, text=text, parse_mode=ParseMode.HTML
        )

    async def ask_confirmation(self, order_id: str, summary: str) -> None:
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("✅ Confirm", callback_data=f"{CONFIRM_PREFIX}{order_id}"),
                    InlineKeyboardButton("❌ Cancel", callback_data=f"{CANCEL_PREFIX}{order_id}"),
                ]
            ]
        )
        await self.app.bot.send_message(
            chat_id=settings.telegram_chat_id,
            text=f"<b>Signal received</b> [{broker.mode_label}]\n<code>{summary}</code>\n\nExecute this trade?",
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML,
        )

    async def route_alert(self, alert: TradingViewAlert, source: str = "Signal") -> dict:
        """Shared execution path for both TradingView webhooks and Telegram
        commands: auto-execute or ask for confirmation based on mode."""
        mode = alert.mode or settings.execution_mode

        # Autonomous sizing: decide whether/how much to trade from holdings + risk settings.
        if alert.needs_sizing:
            try:
                plan = plan_trade(alert)
            except Exception as exc:
                await self.send(f"⚠️ <b>Strategy error</b> · {source}\n<code>{alert.human_summary()}</code>\n{exc}")
                return {"status": "error", "detail": str(exc)}
            if plan.alert is None:
                logger.info("Skipped %s: %s", alert.human_summary(), plan.reason)
                await self.send(f"⏭ <b>Skipped</b> · {source}\n<code>{alert.human_summary()}</code>\n{plan.reason}")
                return {"status": "skipped", "reason": plan.reason}
            alert = plan.alert
            logger.info("Strategy: %s -> %s", plan.reason, alert.human_summary())

        summary = alert.human_summary()

        if mode == ExecutionMode.AUTO:
            result = broker.place_order(alert)
            emoji = "✅" if result.ok else "⚠️"
            await self.send(
                f"{emoji} <b>Auto-executed</b> [{broker.mode_label}] · {source}\n"
                f"<code>{summary}</code>\n{result.message}"
            )
            return {"status": "executed", "ok": result.ok, "detail": result.message}

        pending = pending_store.add(alert)
        await self.ask_confirmation(pending.id, summary)
        return {"status": "pending_confirmation", "order_id": pending.id}

    # ---- handlers ----
    async def _on_start(self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not _authorized(update):
            return
        await update.message.reply_text(
            f"TradingView bot online. Broker mode: <b>{broker.mode_label}</b>. "
            f"You'll get alerts here when signals arrive.\n\n{HELP_TEXT}",
            parse_mode=ParseMode.HTML,
        )

    async def _on_help(self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not _authorized(update):
            return
        await update.message.reply_text(HELP_TEXT, parse_mode=ParseMode.HTML)

    async def _on_status(self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not _authorized(update):
            return
        await update.message.reply_text(
            f"<b>Broker:</b> {broker.mode_label}\n"
            f"<b>Execution mode:</b> {settings.execution_mode.value}\n\n"
            f"<b>Autonomous strategy</b>\n"
            f"Position size: ${settings.position_size_usd:,.0f} per trade\n"
            f"Max open positions: {settings.max_positions}\n"
            f"Shorting: {'on' if settings.allow_shorting else 'off'}",
            parse_mode=ParseMode.HTML,
        )

    async def _on_price(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not _authorized(update):
            return
        if not ctx.args:
            await update.message.reply_text("Usage: /price SYMBOL  (e.g. /price AAPL)")
            return
        symbol = ctx.args[0].upper()
        try:
            q = broker.get_quote(symbol)
            name = broker.get_company_name(symbol)
        except Exception as exc:
            await update.message.reply_text(f"⚠️ {exc}")
            return

        def num(key: str) -> str:
            v = q.get(key)
            return v if v is not None else "—"

        title = f"{symbol}" + (f" — {name}" if name else "")
        try:
            chg = float(q.get("change", 0))
            pct = float(q.get("change_ratio", 0)) * 100
            arrow = "🔺" if chg >= 0 else "🔻"
            change_line = f"{arrow} {chg:+.2f} ({pct:+.2f}%)"
        except (TypeError, ValueError):
            change_line = ""

        caption = (
            f"<b>{title}</b>\n"
            f"Price: <b>{num('price')}</b>  {change_line}\n"
            f"Bid/Ask: {num('bid')} / {num('ask')}\n"
            f"Day H/L: {num('high')} / {num('low')}\n"
            f"Open/PrevClose: {num('open')} / {num('pre_close')}\n"
            f"Volume: {num('volume')}\n\n"
            f"Trade it: <code>/buy {symbol} 1</code> · <code>/sell {symbol} 1</code>"
        )
        chart = await self._chart_image(symbol)
        if chart is not None:
            await update.message.reply_photo(photo=chart, caption=caption, parse_mode=ParseMode.HTML)
        else:
            await update.message.reply_text(caption, parse_mode=ParseMode.HTML)

    async def _chart_image(self, symbol: str, timespan: str = "M30", count: int = 60):
        """Fetch history bars and render a candlestick PNG, or None on failure."""
        try:
            res = broker.data.market_data.get_history_bar(
                symbol.upper(), "US_STOCK", timespan, count=str(count)
            )
            if res.status_code != 200:
                return None
            bars = res.json()
            if not bars:
                return None
            return render_candlestick(symbol.upper(), bars, f"{symbol.upper()} · {timespan}")
        except Exception as exc:
            logger.warning("chart failed for %s: %s", symbol, exc)
            return None

    async def _on_chart(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not _authorized(update):
            return
        if not ctx.args:
            await update.message.reply_text("Usage: /chart SYMBOL [timespan]  e.g. /chart TSLA D1")
            return
        symbol = ctx.args[0].upper()
        timespan = ctx.args[1].upper() if len(ctx.args) > 1 else "M30"
        valid = {"M1", "M5", "M15", "M30", "H1", "H2", "H4", "D1", "W1", "MN1"}
        if timespan not in valid:
            await update.message.reply_text(f"Timespan must be one of: {' '.join(sorted(valid))}")
            return
        await update.message.reply_chat_action("upload_photo")
        chart = await self._chart_image(symbol, timespan)
        if chart is None:
            await update.message.reply_text(f"⚠️ No chart data for {symbol}.")
            return
        await update.message.reply_photo(photo=chart, caption=f"{symbol} · {timespan}")

    async def _handle_trade_command(self, update: Update, ctx, side: Side) -> None:
        if not _authorized(update):
            return
        args = ctx.args
        if len(args) < 2:
            verb = side.value
            await update.message.reply_text(
                f"Usage: /{verb} SYMBOL QTY [LIMIT]\n"
                f"e.g. /{verb} AAPL 2   or   /{verb} AAPL 2 190.50"
            )
            return
        symbol = args[0].upper()
        try:
            qty = float(args[1])
            if qty <= 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text("QTY must be a positive number.")
            return

        limit_price = None
        order_type = OrderType.MARKET
        if len(args) >= 3:
            try:
                limit_price = float(args[2])
                order_type = OrderType.LIMIT
            except ValueError:
                await update.message.reply_text("LIMIT price must be a number.")
                return

        try:
            alert = TradingViewAlert(
                secret=settings.webhook_secret,
                symbol=symbol,
                side=side,
                qty=qty,
                order_type=order_type,
                limit_price=limit_price,
            )
        except Exception as exc:
            await update.message.reply_text(f"⚠️ {exc}")
            return

        result = await self.route_alert(alert, source="Manual")
        if result["status"] == "executed" and not result.get("ok"):
            return  # route_alert already messaged the failure
        if result["status"] == "executed":
            await update.message.reply_text("Order sent. See confirmation above.")

    async def _on_buy(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await self._handle_trade_command(update, ctx, Side.BUY)

    async def _on_sell(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await self._handle_trade_command(update, ctx, Side.SELL)

    async def _on_positions(self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not _authorized(update):
            return
        try:
            positions = broker.get_positions()
        except Exception as exc:
            await update.message.reply_text(f"⚠️ {exc}")
            return
        if not positions:
            await update.message.reply_text("No open positions.")
            return
        lines = ["<b>Open positions</b>"]
        for p in positions:
            sym = p.get("symbol") or p.get("ticker") or "?"
            qty = p.get("quantity") or p.get("position") or p.get("qty") or "?"
            pl = p.get("unrealized_profit_loss") or p.get("unrealizedProfitLoss") or ""
            cost = p.get("cost_price") or p.get("average_cost") or ""
            extra = f" · avg {cost}" if cost else ""
            extra += f" · P/L {pl}" if pl else ""
            lines.append(f"{sym}: {qty}{extra}")
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)

    async def _on_balance(self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not _authorized(update):
            return
        try:
            b = broker.get_balance()
        except Exception as exc:
            await update.message.reply_text(f"⚠️ {exc}")
            return
        assets = b.get("account_currency_assets") or [{}]
        first = assets[0] if assets else {}
        cur = b.get("total_asset_currency", "USD")
        await update.message.reply_text(
            f"<b>Account [{broker.mode_label}]</b> ({cur})\n"
            f"Net liquidation: {b.get('total_net_liquidation_value', '—')}\n"
            f"Cash: {b.get('total_cash_balance', '—')}\n"
            f"Buying power: {first.get('buying_power', '—')}\n"
            f"Market value: {b.get('total_market_value', '—')}\n"
            f"Unrealized P/L: {b.get('total_unrealized_profit_loss', '—')}",
            parse_mode=ParseMode.HTML,
        )

    async def _on_button(self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        await query.answer()

        if not _authorized(update):
            await query.edit_message_text("Unauthorized.")
            return

        data = query.data or ""
        if data.startswith(CANCEL_PREFIX):
            order_id = data[len(CANCEL_PREFIX):]
            pending_store.pop(order_id)
            await query.edit_message_text("❌ Trade cancelled.")
            return

        if data.startswith(CONFIRM_PREFIX):
            order_id = data[len(CONFIRM_PREFIX):]
            pending = pending_store.pop(order_id)
            if pending is None:
                await query.edit_message_text("⚠️ This signal expired or was already handled.")
                return
            result = broker.place_order(pending.alert)
            emoji = "✅" if result.ok else "⚠️"
            await query.edit_message_text(
                f"{emoji} <code>{pending.alert.human_summary()}</code>\n{result.message}",
                parse_mode=ParseMode.HTML,
            )


notifier = TelegramNotifier()
