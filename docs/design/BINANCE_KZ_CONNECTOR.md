# Binance KZ connector — plan and design

Status: **STAGE-1 CODE, UNARMED**. Live execution stays off.  
Date: 2026-09-13 (rev 3)  
Scope v1: **M15 only**, **USD-M BTCUSDT**, **Portfolio Margin (PAPI)**, **leverage 2x**, **risk 1% of live PM equity**, **CatBoost on**.

Paper LIVE1B is unchanged: `paper_only=true`, `real_execution_enabled=false`. This connector is a separate execution sink. It does not write paper books.

---

## Locked operator answers (2026-09-13)

| # | Decision | Lock |
| --- | --- | --- |
| 1 | Product | USD-M BTCUSDT perpetual. Collateral is **BTC + ETH** via **Portfolio Margin**. No stables on the account. |
| 2 | Leverage | **2x** set explicitly. Cap = 2x. Never higher. |
| 3 | Hard cap | **The cap is 1%.** No separate dollar ceiling. `risk_usd = 0.01 * live_pm_adjusted_equity`. CatBoost then re-caps back to 1%. |
| 4 | CatBoost | **On for live v1.** Same hybrid multiplier as LIVE1B (clip 0.5–1.5), then **re-cap** to 1%. |
| — | `sleeve_equity_usd` | **Dropped.** Size off whatever is actually in the PM account (read from PAPI). Do not invent a second equity number. |

### Isolated vs Portfolio Margin (cannot both be true on the venue)

Binance **does not allow Isolated USD-M together with Portfolio Margin**. Isolated is also mutually exclusive with Multi-Assets Mode. PM is always a **unified cross** pool (Cross Margin + USD-M + COIN-M wallets). Liquidation is **uniMMR ≤ 1.05** of that pool, not of one position.

What we keep from “isolated”:

- **Software isolation:** one M15 position, BTCUSDT only, 2x, 1% of live PM equity, exchange-native SL/TP, kill-flatten if uniMMR gets tight.
- **Spot vs PM:** coins in **Spot** are not PM collateral until transferred. If ~1 BTC + ~22 ETH all sit in PM, that whole pile is the book and the liquidation pool. If part stays in Spot, it is not sized and not liquidated with the futures position.

Do **not** enable Multi-Assets Mode as a substitute: it is also Cross-only. PM is the right venue mode for “BTC and ETH, no stables”.

---

## 1. What “Binance KZ API” actually is

There is **no separate public REST host** `api.binance.kz`. Binance Kazakhstan is a local AIFC entity. Trading API is the global Binance Open Platform. Travel Rule is deposits/withdrawals only.

Official sources:

| Layer | URL |
| --- | --- |
| Developer Center | https://developers.binance.com |
| Portfolio Margin API | https://developers.binance.com/docs/derivatives/portfolio-margin |
| PM general / PAPI | https://developers.binance.com/docs/derivatives/portfolio-margin/general-info |
| USD-M market data (still fapi) | https://developers.binance.com/docs/derivatives/usds-margined-futures |
| PM API key caveat (KZ) | https://www.binance.com/en-KZ/support/faq/detail/ccf04078d7774d479f11ae15c4f56081 |
| Activate PM | https://www.binance.com/en/support/faq/detail/7ee6b3f65d5a421491c0a5588223fd14 |
| uniMMR | https://www.binance.com/en/support/faq/detail/4868b2f1aa6c4d08af973328462bb0bd |
| Ed25519 keys | https://www.binance.com/en/support/faq/detail/6b9a63f1e3384cf48a2eedb82767a69a |
| SDK | `binance-sdk-derivatives-trading-portfolio-margin` |

Hosts:

| Env | REST (trade/account) | User WS | Public market WS |
| --- | --- | --- | --- |
| Live PM | `https://papi.binance.com` | `wss://fstream.binance.com/pm/ws/<listenKey>` | `wss://fstream.binance.com` (`@bookTicker`, `@aggTrade`) |
| Live market data | `https://fapi.binance.com` (NONE / MARKET_DATA only) | — | same |

**There is no working Portfolio Margin testnet.** Binance confirmed `/papi` on futures testnet is empty. Soak plan: unit tests + **live read-only** + first live orders at 1% of then-current PM equity. No fake PM demo.

After PM is enabled:

- Existing keys **permanently lose** `Enable Futures`.
- `fapi`/`dapi` TRADE and USER_DATA are dead. Market data on fapi still works.
- Need a **new** key with **Enable Portfolio Margin Trading**.

---

## 2. Product / account mode

| Knob | v1 |
| --- | --- |
| Contract | USD-M `BTCUSDT` perpetual |
| Account | Portfolio Margin (classic PM, not PM Pro unless the account already is) |
| Venue margin | Unified (not Isolated) |
| Position mode | One-way (`BOTH`) |
| Leverage | `POST /papi/v1/um/leverage` symbol=`BTCUSDT` leverage=`2` on every start |
| Auto-borrow | **Off.** Refuse start if margin debt / auto-borrow is on |
| Other products | Connector must not place CM, spot-margin, or non-BTCUSDT UM orders |
| Collateral | BTC + ETH already in PM wallets (haircut per collateral table, BTC typically ~0.95) |

PnL of USD-M is still USDT-denominated. PM is allowed to show a **negative USDT UM balance** while uniMMR stays healthy — that is how “no stables” works. We do not convert BTC/ETH to USDT.

**Stop-loss does not make liquidation impossible.** See §7.1. SL is the first exit. uniMMR kill is the second, because on Portfolio Margin Binance can liquidate the **account** (BTC+ETH together) before or through the BTCUSDT stop.

---

## 3. Place in the existing architecture

Cognition and S4.1 stay the only brain. The connector is a sink.

```
WS aggTrade
  → closed M15 candles
  → auction / cognitive / final / lifecycle memory
  → S4.1 TimeframeManager            ← sole entry clock
  → command-bus (append-only)
        │
        ├─ LIVE1B paper-manager      ← paper books, unchanged, paper_only
        └─ binance-kz-executor       ← NEW, isolated process, M15 filter
              → papi signed REST (UM BTCUSDT only)
              → PM user-data WS fills
              → own ledger (not paper books)
```

Invariants (unchanged):

- Closed bar = cognition clock, not fill price.
- Fill = live BBO / exchange match on the next forming candle.
- Consume `OPEN_LONG` / `OPEN_SHORT` / `CLOSE` for `timeframe=M15` only.
- LIVE1A journal observe-only.
- Same-episode second OPEN blocked by S4.1 one-shot **and** local `last_entry_episode_id`.
- Paper and live do not dual-fill the same book. Basis vs paper is observe-only on `manager_command_id`.

---

## 4. Security canons

Fail-closed. Separate process from paper-manager. `paper_only_guard.py` continues to refuse `BINANCE_API_KEY` in the paper container.

### 4.1 Keys

- **Ed25519** (HMAC fallback).
- Permissions: **Enable Reading + Enable Portfolio Margin Trading**. Nothing else.
- **Enable Withdrawals = off**. Enable Spot & Margin = off. Enable Futures will not exist on a post-PM key.
- **IP whitelist** — executor static IPv4 only.
- Create the key **after** PM is enabled. Never reuse a pre-PM key.
- Secret: `0600` file / Docker secret. Env: `BINANCE_KZ_API_KEY` + `BINANCE_KZ_ED25519_KEY_PATH`.
- Never in git, compose, logs, Sentry, chart, command-bus.

### 4.2 Double gate

| Gate | Live (only real PM path) |
| --- | --- |
| `config.network` | `live` |
| `config.account_mode` | `portfolio_margin` |
| `BINANCE_KZ_LIVE_ENABLED` | `true` |
| `config.real_execution_enabled` | `true` |
| REST host | **exactly** `https://papi.binance.com` |
| Kill flag | absent |

Paper-manager `real_execution_enabled` stays `false` forever. Host mismatch (papi vs fapi trade) = refuse start.

### 4.3 Operator preflight (account, once)

PM activation is account-level and API-key-destructive. Do this by hand, not by the bot:

1. Close **all** Isolated USD-M / COIN-M positions and orders. Isolated must be off.
2. Multi-Assets Mode **off** (PM activation requires this).
3. Cross Margin account activated; no loans, no negative balances.
4. Enable Portfolio Margin.
5. Create **new** Ed25519 key: Reading + PM Trading, IP lock, no withdraw.
6. Move into PM only the BTC/ETH that should back this bot. Anything left in Spot is outside uniMMR.
7. Confirm: no other UM/CM/margin positions, auto-borrow off, uniMMR healthy while flat (should be very high with no position).

The connector **never** calls universal transfer / withdraw. Sleeve funding is operator-only.

### 4.4 Signing / transport

Same as Binance SIGNED: `X-MBX-APIKEY`, `timestamp`, `recvWindow=5000`, Ed25519/HMAC.
Clock: refuse start if `|local - serverTime| > 1000ms` (`GET /fapi/v1/time` is fine for clock).
429 → back off. 418 → **kill + flatten**, no retry.
`POST /papi/v1/um/order` HTTP 503 unknown: **do not retry POST**. Reconcile `GET /papi/v1/um/order?origClientOrderId=...` + user WS.

### 4.5 Logging

Log `command_id`, `clientOrderId`, `orderId`, qty, prices, uniMMR, status, error **code**. Never key/PEM.

---

## 5. Allowed API surface (whitelist)

Market data (fapi, unsigned):

- `GET /fapi/v1/ping`
- `GET /fapi/v1/time`
- `GET /fapi/v1/exchangeInfo`
- `GET /fapi/v1/premiumIndex`
- `GET /fapi/v1/ticker/bookTicker`

PAPI (signed):

- `GET /papi/v1/account` (uniMMR, adjusted equity)
- `GET /papi/v1/balance`
- `GET /papi/v1/um/account` or `GET /papi/v2/um/account`
- `GET /papi/v1/um/positionRisk`
- `GET /papi/v1/um/leverageBracket`
- `POST /papi/v1/um/leverage` (2x only)
- `POST /papi/v1/um/order`
- `GET /papi/v1/um/order`
- `DELETE /papi/v1/um/order` / `DELETE /papi/v1/um/allOpenOrders`
- `GET /papi/v1/um/openOrders`
- `GET /papi/v1/um/userTrades`
- `POST/PUT/DELETE /papi/v1/listenKey`

Forbidden: `/sapi` wallet/withdraw/transfer, `fapi` TRADE/USER_DATA, any `/papi/v1/cm/*`, any `/papi/v1/margin/*` borrow, `batchOrders`, auto-collect / auto-borrow toggles.

---

## 6. Command → order mapping

Filter: `timeframe==M15`, `action_allowed`, after `consume_after`, unknown `command_id`, kill not tripped, no OPEN M15 on venue or ledger.

### 6.1 Idempotency

```
clientOrderId = "s41" + sha256(command_id)[:33]
```

(`newClientOrderId` ≤ 36 chars.) Replay → cursor no-op or venue duplicate. 503 unknown → GET by this id, never a second POST.

### 6.2 OPEN

1. Refresh PM account (uniMMR, adjusted equity), UM `positionRisk`, mark, BBO.
2. Fail closed if BBO older than `max_bbo_age_ms` (2000).
3. Fail closed if uniMMR `< min_unimmr_open` (default **2.0**).
4. Fail closed if any UM/CM/margin position exists that is not our BTCUSDT M15 ledger row (inventory surprise).
5. Ensure leverage=2 for BTCUSDT. Refuse if venue reports anything else after the set call.
6. Size (§7).
7. IOC aggressive LIMIT through live BBO. MARKET fallback only if IOC size=0 and command TTL still valid.
8. On fill: reduce-only `STOP_MARKET` (SL, `workingType=MARK_PRICE`) and `TAKE_PROFIT_MARKET` (TP). Qty = filled. Must live on the exchange if our process dies.
9. Persist `{command_id, episode_id, side, qty, avg_px, sl_id, tp_id}`.

### 6.3 CLOSE

Cancel SL/TP, reduce-only flatten BTCUSDT, mark FLAT with S4.1 `exit_reason`. If already flat, no-op after reconcile.

### 6.4 Re-entry

New episode + living M15 context → S4.1 may OPEN again. Executor allows it. Same episode → blocked.

---

## 7. Risk (v1)

Paper M15 0.5% / $100k is not this book. Do not mutate `timeframe_trader_risk.json`.

Equity is **whatever PAPI reports** as adjusted equity (BTC+ETH in PM, after haircut). Approximate stack ~1 BTC + ~22 ETH is **not** hardcoded. The connector reads the live number every OPEN.

```
equity_usd = papi_adjusted_equity          # live, not a config guess
risk_usd   = equity_usd * 0.01             # the only cap
qty        = (risk_usd * catboost_mult) / stop_distance
# re-cap so dollar risk at stop ≤ 1% of equity
```

With paper-style SL 100 bps (1% of price) this implies **notional ≈ equity** and **initial margin ≈ equity / 2** at 2x. That is a large position relative to the account. CatBoost 0.5–1.5 scales it, then 1% re-cap clips the top.

| Parameter | v1 |
| --- | --- |
| Timeframe | M15 only |
| Risk cap | **1% of live PM adjusted equity** |
| Separate USD hard cap | none |
| CatBoost | LIVE1B hybrid; fail-open 1.0; clip 0.5–1.5; then re-cap to 1% |
| Max open | 1 |
| Leverage | 2x |
| Equity | PAPI adjusted equity. **Never** paper `100000`. **Never** a guessed 1 BTC / 22 ETH |

Pre-trade: refuse if BBO stale, if projected uniMMR `< min_unimmr_open`, if any foreign position exists.

### 7.1 Why a stop-loss is not “no liquidation”

On **isolated** USD-M, liquidation is per position. At 2x, venue liq is roughly a ~50% move. A 1% SL should fire first. That intuition is why this feels safe.

On **Portfolio Margin** liquidation is **not** “BTCUSDT hit −50%”. It is **uniMMR of the whole PM account**:

```
uniMMR = adjusted_equity(BTC + ETH + UM PnL, after haircuts)
       / maintenance_margin(all PM positions)
```

| uniMMR | What it means |
| --- | --- |
| high (flat account, lots of coin, no position) | healthy |
| `< 2.0` | we **do not OPEN** |
| `≤ 1.5` | we **flatten ourselves** (kill) |
| `≤ 1.05` | **Binance** starts account liquidation |

SL can fail to prevent that because:

1. SL is an order on **BTCUSDT**. PM can go critical because **ETH** (or BTC haircut) dropped, even if BTCUSDT never touched the stop.
2. SL is `STOP_MARKET`. A gap/wick can skip the trigger price; fill is worse than the stop, sometimes much worse.
3. PM may already be eating the account (uniMMR ≤ 1.05) **before** the stop order is processed.
4. Haircut: 1 BTC in PM is not 1 BTC of equity (often ~95%).

So: **SL is the trade exit. uniMMR 2.0 / 1.5 is the account fuse.** We keep both. The goal is that Binance’s 1.05 path never runs.

---

## 8. Module layout (when we implement)

```
src/btc_ml/trading/binance_kz/
  config.py          # live + papi + leverage==2 + risk 1%
  constants.py
  signing.py
  client.py          # PAPI whitelist + fapi market data
  user_stream.py     # wss://fstream.binance.com/pm
  orders.py
  sizing.py          # 1% live equity, CatBoost, uniMMR
  executor.py
  consumer.py        # M15 command-bus cursor
  reconcile.py
  kill_switch.py     # KILL file, 418, uniMMR, inventory surprise
  ledger.py          # data/trading/binance_kz/
  guard.py

config/binance_kz_live.json     # unusable without BINANCE_KZ_LIVE_ENABLED
deploy/vps/entrypoints/binance_kz_guard.py
```

No `binance_kz_demo.json` for PM (no testnet). Cursor: `s41_binance_kz_command_cursor_v1`.

---

## 9. Kill switch

Trip → cancel UM BTCUSDT orders → reduce-only flatten → refuse OPEN until **manual** reset.

Triggers:

- kill flag `data/trading/binance_kz/KILL`
- N consecutive exchange errors
- HTTP 418
- uniMMR ≤ `kill_unimmr` (**1.5**). This is us flattening. Binance liquidation is later, at 1.05.
- mark within `liq_proximity_bps` of account liquidation
- clock skew
- inventory surprise (position we did not open)
- venue leverage ≠ 2 after set
- margin loan / auto-borrow detected

---

## 10. Plan

| Stage | What | Armed? |
| --- | --- | --- |
| **0 — this doc** | Design locked except dollar numbers. | no |
| **1 — client + tests** | Signing, `clientOrderId`, 503-no-retry, M15 filter, uniMMR gates, paper isolation. Implemented, unarmed. | no |
| **2 — live read-only** | After PM + new key: 24h `GET account/positionRisk/listenKey`. Confirm live equity, uniMMR, flat UM. **Zero orders.** | read |
| **3 — kill drill** | Dry flatten path against a flat account (cancel-all + reduce-only no-op). | no size |
| **4 — live micro** | `BINANCE_KZ_LIVE_ENABLED=true` + explicit go. First orders still 1% of **then-current** PM equity. One M15. | yes, gated |
| **5 — not v1** | Other TFs, Isolated, raising leverage, PM Pro extras, auto-borrow, transferring funds from the bot. | — |

No stage writes LIVE1B books. Epoch `PER_TF_EQUITY_1PCT_V1_VPS_20260907_095442` untouched.

---

## 11. Still open

Product/risk numbers are locked. Remaining is operator account work, not config invention:

1. Enable PM, new PM API key, IP lock.
2. Decide what of ~1 BTC + ~22 ETH sits in PM vs Spot (live equity is read from the API either way).
3. Stage-1 is in tree (`src/btc_ml/trading/binance_kz/`). Stage-2 is live read-only after PM key exists.

---

## 12. Explicit non-goals

- Do not enable `real_execution_enabled` on paper config.
- Do not put keys in compose or git.
- Do not mix HL vault code into this client.
- Do not copy M15 onto other TFs.
- Do not use candle close as fill.
- Do not treat HTTP 503 unknown as a failed order.
- Do not call Isolated `marginType` on a PM account.
- Do not transfer or withdraw from the executor.
