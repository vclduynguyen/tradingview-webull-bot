# TradingView → Webull Trading Bot

A FastAPI bot that receives **TradingView alerts** via webhook, places **stock
orders on Webull** (sandbox/paper or live) via the official Webull OpenAPI, and
uses **Telegram** to notify you and/or ask for confirmation before trading.

```
TradingView (Pine strategy / alert)
        │  webhook (JSON + secret)
        ▼
   This bot  ──►  Webull OpenAPI  (places the order)
        │
        └──►  Telegram  (notify, or confirm with ✅/❌ buttons)
```

> **Important:** TradingView cannot place real trades on its own. It only sends
> alerts. This bot is the piece that turns an alert into an actual order.

## Features

- **Two execution modes** (global default + per-alert override):
  - `confirm` — bot messages you on Telegram with **✅ Confirm / ❌ Cancel** buttons; the trade fires only when you tap Confirm.
  - `auto` — bot places the trade immediately, then notifies you.
- **Sandbox/paper trading by default** (fake money). Flip one env var to go live.
- **Shared-secret auth** so only your TradingView alerts are accepted.
- **Market & limit orders**, sized by share `qty` or dollar `notional`.
- **MMG indicator support** — send MMG signals (`B2O`/`S2C`/`S2O`/`B2C`) directly; the bot maps them to buy/sell.
- **Manual trading from Telegram** — look up quotes and place orders by chatting with the bot (`/price`, `/buy`, `/sell`, `/positions`, `/balance`).
- Telegram chat lock: only your chat id can confirm trades.

## Chat with the bot (Telegram commands)

Message your bot directly — you don't need TradingView for these:

| Command | What it does |
|---------|--------------|
| `/price AAPL` | Live quote + candlestick chart: price, change, bid/ask, day high/low, volume |
| `/chart TSLA D1` | Candlestick chart only; timespans: `M1 M5 M15 M30 H1 H2 H4 D1 W1 MN1` (default `M30`) |
| `/buy AAPL 2` | Buy 2 shares (market). Respects your execution mode (confirm/auto) |
| `/buy AAPL 2 190.50` | Buy 2 shares with a limit price of 190.50 |
| `/sell AAPL 1` | Sell 1 share (market) |
| `/positions` | Your current holdings |
| `/balance` | Cash, buying power, net liquidation, P/L |
| `/status` | Broker mode + execution mode |
| `/help` | List all commands |

In `confirm` mode, `/buy` and `/sell` still pop the ✅/❌ buttons before executing.

## Using the MMG (Market Maker Genie) indicator

MMG is a closed-source TradingView indicator that emits four signals:
`B2O` (Buy to Open), `S2C` (Sell to Close), `S2O` (Sell to Open), `B2C` (Buy to Close/Cover).
The bot maps them like this:

| MMG signal | Action |
|------------|--------|
| `B2O` | BUY (open long) |
| `S2C` | SELL (close long) |
| `B2C` | BUY (cover short) |
| `S2O` | SELL (open short — **needs a margin account**, not cash) |

## Fully autonomous mode (bot picks & sizes trades)

Leave `qty`/`notional` **out** of the alert and the bot manages the trade itself:

| Signal | What the bot does |
|--------|-------------------|
| `B2O` | If not already holding the symbol and under `MAX_POSITIONS`, buys `floor(POSITION_SIZE_USD / price)` whole shares at market. |
| `S2C` | Sells the **entire** held position of that symbol at market. Skips if nothing held. |
| `S2O` / `B2C` | Skipped unless `ALLOW_SHORTING=true` (needs a margin account). |

Every decision — trade or skip — is reported to Telegram with the reason
("Already holding", "Max positions reached", "No open position to close", etc.).

Settings in `.env`:
```
EXECUTION_MODE=auto      # fire immediately, no confirm tap
POSITION_SIZE_USD=1000   # dollars per new position
MAX_POSITIONS=5          # cap on simultaneous holdings
ALLOW_SHORTING=false
```

### Which stocks does it trade?
MMG is closed-source and runs only inside TradingView, so the bot can't scan the
market itself. Instead **you define the universe**: add an MMG alert to each stock
you want the bot to consider (your watchlist). The bot then autonomously trades
*whichever of those* MMG signals, within your position/size limits.

### TradingView alert setup (one per stock)
1. Add the **MMG V12.0** indicator to the chart.
2. Create an **Alert** → Condition: the **MMG** indicator (its buy/sell alert
   condition, or "Any alert() function call").
3. **Expiration:** set to *Open-ended* if your plan allows, otherwise renew when it expires.
4. **Notifications → Webhook URL:** `https://your-domain/webhook`
5. **Message** — entry alert:
   ```json
   {"secret":"your-webhook-secret","symbol":"{{ticker}}","signal":"B2O"}
   ```
   and a second alert for the exit:
   ```json
   {"secret":"your-webhook-secret","symbol":"{{ticker}}","signal":"S2C"}
   ```
`{{ticker}}` auto-fills the chart symbol, so the same message works on every stock.
Add `"qty": 5` to any alert to override auto-sizing for that alert.

> The number of alerts you can have depends on your TradingView plan
> (Essential ≈ 20, Plus ≈ 100, Premium ≈ 400). Since you're on a **cash** account,
> only `B2O`/`S2C` (long only) will execute; shorting is skipped.

## Setup

### 1. Install
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Get credentials

**Webull OpenAPI** (requires an approved API application):
1. Log in to the Webull OpenAPI management page for your region:
   - US: https://www.webull.com/center#openApiManagement
   - HK: https://www.webull.hk/open-api · JP: https://www.webull.co.jp/center/openapi/manage
   - SG / TH / AU / MY / UK / BR / MX / ZA / EU — see the [SDK README](https://github.com/webull-inc/webull-openapi-python-sdk).
2. Apply for **Open API** access and wait for approval.
3. Under **API Keys Management**, register your app and click **Generate Key**.
4. Copy the **App Key** and **App Secret** (secret is shown once).
5. For paper trading, apply for the **Sandbox** Trading API too.

> Webull OpenAPI is available only in the regions listed above. Approval is not
> instant like some brokers — you must be approved before keys work.

**Telegram:**
- **Bot token:** message [@BotFather](https://t.me/BotFather) → `/newbot`.
- **Chat id:** message [@userinfobot](https://t.me/userinfobot) → it replies with your id.

### 3. Configure
```bash
cp .env.example .env
# edit .env and fill in every value
```
Set a long random `WEBHOOK_SECRET` (e.g. `openssl rand -hex 24`).

### 4. Run
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```
On startup you should get a "🤖 TradingView bot online" message in Telegram.
Send `/start` or `/status` to the bot to check it.

### 5. Expose to the internet (so TradingView can reach it)
TradingView needs a public HTTPS URL. For local testing use a tunnel:
```bash
ngrok http 8000
```
Your webhook URL becomes `https://<something>.ngrok.io/webhook`.
For production, deploy behind HTTPS (Fly.io, Render, a VPS + Caddy, etc.).

## TradingView alert setup

1. Open a chart → create an **Alert**.
2. Set **Webhook URL** = `https://your-domain/webhook`.
3. Set the alert **Message** to JSON like below (must include your secret):

**Market buy, 1 share, ask before trading:**
```json
{
  "secret": "your-webhook-secret",
  "symbol": "AAPL",
  "side": "buy",
  "qty": 1,
  "order_type": "market",
  "mode": "confirm"
}
```

**Auto-execute a $500 buy:**
```json
{
  "secret": "your-webhook-secret",
  "symbol": "MSFT",
  "side": "buy",
  "notional": 500,
  "order_type": "market",
  "mode": "auto"
}
```

**Limit sell:**
```json
{
  "secret": "your-webhook-secret",
  "symbol": "TSLA",
  "side": "sell",
  "qty": 2,
  "order_type": "limit",
  "limit_price": 250.00
}
```

### Payload fields
| Field | Required | Notes |
|-------|----------|-------|
| `secret` | yes | Must equal `WEBHOOK_SECRET`. |
| `symbol` | yes | Ticker, e.g. `AAPL`. |
| `side` | one of side/signal | `buy` or `sell`. |
| `signal` | one of side/signal | MMG signal: `B2O`/`S2C`/`S2O`/`B2C` → mapped to buy/sell. |
| `qty` | one of qty/notional | Number of shares. |
| `notional` | one of qty/notional | Dollar amount. |
| `order_type` | no | `market` (default) or `limit`. |
| `limit_price` | for limit | Required when `order_type` is `limit`. |
| `mode` | no | `confirm` or `auto`; overrides `EXECUTION_MODE`. |

## Test without TradingView
```bash
curl -X POST http://localhost:8000/webhook \
  -H "Content-Type: application/json" \
  -d '{"secret":"your-webhook-secret","symbol":"AAPL","side":"buy","qty":1,"mode":"confirm"}'
```
You should get a Telegram message with Confirm/Cancel buttons.

## Going live
When you're confident, set `WEBULL_PAPER=false` in `.env` and restart.
**Real money will be used.** Start small.

## Notes / limits
- Pending confirmations are held in memory and cleared on restart (safe default — a restarted bot won't fire stale trades).
- Dollar-amount (`notional`) orders use Webull's `AMOUNT` entrust type, which is MARKET-only and intended for fractional shares.
- No persistent trade log/DB yet; Webull's app/dashboard is the source of truth.
- One Telegram chat is authorized. Multi-user support would need extra work.
- Some Webull regions/accounts require a 2FA token for the OpenAPI; the SDK stores it under `conf/token.txt` (configurable via `WEBULL_OPENAPI_TOKEN_DIR`).
