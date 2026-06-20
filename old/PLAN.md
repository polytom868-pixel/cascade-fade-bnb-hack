# CascadeFade — Implementation Plan (Refined)

> **Track 1: Autonomous Trading Agents** | BNB Hack: AI Trading Agent Edition  
> Submission deadline: **June 21, 2026, 12:00 UTC**  
> Today: **June 19, 2026** → **~1.5 days to build and submit**  
> Trading window: **June 22 – June 28, 2026**  
> On-chain registration: **must be completed before June 22**

---

## 1. Plan Philosophy

This plan is a **radical simplification** of the original 14-day architecture. The original design was over-engineered, relied on unavailable data sources, and misused several primitives (ERC-8183 as a PnL ledger, perps via TWAK, BNB-denominated x402, a free-tier BSC aggregator API). All of those issues have been verified by independent audit reports in `$M/audit/`.

**New direction:** build a **single spot-only agent** that can be submitted by June 21 12:00 UTC and run autonomously during June 22–28. The agent uses the **real interfaces that work**: CMC REST/MCP for data, TWAK CLI for non-custodial signing and swaps, PancakeSwap v3 via MEV Guard RPC for execution, SQLite for logging, and BSCScan as the authoritative PnL source. The BNB Agent SDK is used only for **ERC-8004 identity** if time permits (Phase 0.13), not for ERC-8183 PnL logging.

**MVP cut line:** if time runs out, the submission still qualifies if these five conditions are met: (1) TWAK wallet is funded and registered, (2) one live test swap confirmed on BSCScan, (3) the 149-token allowlist is hardcoded and enforced, (4) the agent loop guarantees a daily heartbeat trade and a 25% drawdown kill switch, (5) the DoraHacks form is submitted with the correct wallet address and a public demo video. **Every task below is tagged `MVP` (must ship) or `STRETCH` (skip if time runs out).** If any MVP task slips, the remaining MVP tasks must still be completed; STRETCH tasks are cut first.

---

## 2. Verified Facts from Audit Reports

These are the facts that constrain the plan. They are derived from the 7 audit reports in `$M/audit/` and cross-checked against multiple sources.

| # | Verified Fact | Implication |
|---|---|---|
| 1 | Submission deadline is **June 21, 2026, 12:00 UTC** (primary sources agree). | Plan to submit by **10:00 UTC June 21**. |
| 2 | On-chain registration must be done **before the trading window opens on June 22**. | `twak compete register` must run before June 22. |
| 3 | Competition is judged by **total return** with a **max drawdown cap** (roughly ~30% example). | Optimize for absolute return; internal hard stop at **25%** to stay safe. |
| 4 | **At least 1 trade per day** is required, **7 trades total minimum**. | Implement a **daily heartbeat trade** if no signal fires. |
| 5 | **Portfolio ≤ $1** at any hour → that hour recorded as **0% return**. | Keep portfolio well above $1; internal stop at **$5**. |
| 6 | Eligible tokens are a **fixed list of 149 BEP-20 tokens**. | Hardcode the exact list; reject all trades outside it. |
| 7 | **TWAK cannot sign perps** — no perp CLI/MCP command exists. | Agent is **spot-only**. |
| 8 | **ERC-8183 is agentic commerce/escrow**, not a PnL ledger. | Do not use ERC-8183 for PnL logging. Use **BSCScan + SQLite** for PnL proof. |
| 9 | **ERC-8004** is agent identity (gas-free on testnet, mainnet may need gas/MegaFuel sponsor). | Use it once to register a verifiable agent identity if time permits. |
| 10 | CMC x402 requires **USDC on Base**; TWAK x402 may support Base USDC/BSC USDC. | Do not claim BNB-funded x402. If x402 is used, fund a Base USDC wallet. |
| 11 | PancakeSwap MEV Guard RPC is **`https://bscrpc.pancakeswap.finance`** (Chain ID 56). | Configure this as the agent's BSC RPC endpoint. |
| 12 | CMC has **no per-token social-volume time series** and **no per-token liquidation series**. | Replace those signals with CMC DEX-activity proxies and global derivatives metrics. |
| 13 | CMC Basic (free) tier: **15,000 credits/month, 50 req/min**, no historical data, no community trending. | Build around free endpoints; avoid signals that require paid-only endpoints. |
| 14 | TWAK `swap` is provider-agnostic and may not guarantee PancakeSwap routing. | Use `twak swap` for execution; add **QuoterV2** for slippage estimates. |
| 15 | `twak start crypto` is campaign shorthand; the reliable primitive is the CLI subprocess. | Python agent calls `twak` commands via subprocess. |
| 16 | `twak` latest is `0.18.0` (npm `@trustwallet/cli`). | Pin to latest, not an outdated version. |

---

## 3. Requirements (What This Plan Must Deliver)

### Functional Requirements

1. A TWAK wallet is created, funded, and registered on-chain before June 22.
2. The agent polls CMC for prices, DEX activity, and global derivatives metrics.
3. The agent evaluates a simple, spot-only signal and generates buy/sell/hold decisions.
4. The agent invokes `twak swap` to execute trades on BSC.
5. All trades are submitted through the PancakeSwap MEV Guard RPC.
6. The agent enforces a 25% portfolio drawdown stop and a $5 portfolio floor.
7. The agent guarantees at least one trade per day via a heartbeat trade.
8. All trades are logged to SQLite with signal snapshot, tx hash, price, and PnL.
9. The BSCScan wallet address is the canonical PnL proof.
10. A demo video is recorded and the DoraHacks form is submitted by June 21 12:00 UTC.

### Non-Functional Requirements

1. The system runs as a **single Python process** (no Docker, no Redis, no Postgres, no VPS-specific features).
2. The codebase is small enough to write and test in ~1.5 days.
3. The repository is made public before submission.
4. README, ARCHITECTURE, and SUBMISSION docs are consistent with the audits and the actual rules.

### Out of Scope (Explicitly Dropped)

- Perps (Aster, Orderly, PancakeSwap Perps).
- ERC-8183 as PnL ledger.
- FastAPI dashboard, WebSocket, Redis, Docker, PostgreSQL, backtest harness.
- Two-regime design (simplified to one spot-only signal).
- Complex position sizing (volatility scaling, tick-depth modeling, archetype classification).
- Universal Router / Permit2 batch execution.
- Dual MEV RPC health-check failover module.
- BNB-denominated x402 payments.

---

## 4. Approach

**Single spot-only strategy using a DEX-activity proxy for attention:**

- **Buy condition:** a token in the 149-token allowlist has positive 7-day price momentum and its 24-hour DEX transaction velocity (or volume rank) is below recent average → low attention, stealth drift.
- **Sell condition:** the token enters the CMC top-3 DEX trending list, or its price drops 5% from entry, or it rises 10% from entry, or a 24-hour hold timeout is reached.
- **Daily heartbeat:** if no trade has occurred in 22 hours, perform a tiny BNB/USDT swap (inside the allowlist) to guarantee the 1-trade/day minimum.
- **Cash management:** keep a stablecoin reserve (USDT) to stay above the $1 floor and to fund swaps/gas.

This approach is simple, uses CMC data that actually exists on the free tier, avoids perps, satisfies the ≥7-trade requirement, and can be built and demoed in the remaining time.

---

## 5. Implementation Phases (Work Units)

### Phase 0 — Setup & Infra (Today, June 19)

**Goal:** Wallet, funding, registration, repo, and environment are ready.

| # | Task | Acceptance Criterion | Priority | MVP? |
|---|---|---|---|---|
| 0.1 | Create a fresh `velocis-cascade-fade` GitHub repo (public at submission time). | Repo exists and `.gitignore` is set. | CRITICAL | MVP |
| 0.2 | Move original `ARCHITECTURE.md`, `PLAN.md`, `SUBMISSION.md` to `old/` folder and do not edit them. | `old/` contains the 3 original docs only. | CRITICAL | MVP |
| 0.3 | Install TWAK CLI: `npm install -g @trustwallet/cli` or `npx @trustwallet/cli`. | `twak --version` returns `0.18.0` or later. | CRITICAL | MVP |
| 0.4 | Initialize TWAK credentials: `twak init --api-key <id> --api-secret <secret>` or set `TWAK_ACCESS_ID` + `TWAK_HMAC_SECRET`. | `twak wallet list` works without error. | CRITICAL | MVP |
| 0.5 | Create a TWAK wallet: `twak wallet create --password <strong_password>` or via env/keychain. | Wallet file exists in `~/.twak/wallet.json` and `twak wallet balance` shows a BNB balance (even if zero). | CRITICAL | MVP |
| 0.6 | Fund the wallet with **0.5+ BNB** for gas and **500–1000 USDT** (or other eligible stablecoin from the 149 list) for trading on BSC. | `twak wallet balance` shows BNB and trading capital balances. | CRITICAL | MVP |
| 0.7 | Set developer-defined policy / per-command limits: daily spend cap, allowlist, max slippage, restricted addresses. | Document policy in `POLICY.md` and pass strict flags to every `twak swap` call. | CRITICAL | MVP |
| 0.8 | Run `twak compete register` before June 22; verify the same address is also entered on the DoraHacks submission form. | BSCScan transaction exists for the competition contract `0x212c61b9b72c95d95bf29cf032f5e5635629aed5` and the wallet is registered. | CRITICAL | MVP |
| 0.9 | Get a free CMC API key. | Key is saved in `.env` and CMC status endpoint returns 200. | CRITICAL | MVP |
| 0.10 | Set up Python 3.11+ virtual environment and install dependencies. | `python -m src.agent --help` runs without import errors. | CRITICAL | MVP |
| 0.11 | Create `.env.example` and `.env` with all required secrets. | `.env.example` is committed; `.env` is not. | CRITICAL | MVP |
| 0.12 | Verify PancakeSwap MEV Guard RPC connection: `w3 = Web3(Web3.HTTPProvider("https://bscrpc.pancakeswap.finance")); print(w3.eth.block_number)`. | RPC returns latest block number. | CRITICAL | MVP |
| 0.13 | Optional: register ERC-8004 agent identity via BNBAgent SDK. | If completed, save `agentId` and transaction hash in `IDENTITY.md`. Note: mainnet may require gas or a MegaFuel sponsor policy; testnet is gas-free. | STRETCH | STRETCH |

**Phase 0 Definition of Done:**
- Wallet is funded, registered, and verified on BSCScan.
- Repo is clean, original docs are in `old/`, and `.env` is configured.
- `python -m src.agent` can start without errors.
- MEV Guard RPC is responsive.

---

### Phase 1 — Data Layer (Today, June 19)

**Goal:** Minimal CMC client that supplies the one signal with real data.

**MVP subset:** 1.1, 1.2, 1.3, 1.7. (1.4, 1.6 are HIGH; 1.5 is STRETCH.)

| # | Task | Acceptance Criterion | Priority | MVP? |
|---|---|---|---|---|
| 1.1 | Implement `src/config.py` with environment loader, 149-token allowlist, risk constants, CMC endpoints, RPC settings, and TWAK paths. | `python -c "from src.config import ALLOWLIST; print(len(ALLOWLIST))"` returns 149. | CRITICAL | MVP |
| 1.2 | Implement `src/cmc_client.py` — async CMC REST client with retries and rate-limit handling. | Can fetch `/v2/cryptocurrency/quotes/latest` and `/v3/fear-and-greed/latest` without errors. | CRITICAL | MVP |
| 1.3 | Implement `src/cmc_client.py` → `get_24h_change(id)` and `get_7d_change(id)` for allowlist tokens. | Returns numeric price changes for a sample token. | CRITICAL | MVP |
| 1.4 | Implement `src/cmc_client.py` → `get_dex_trending_tokens()` or use `/v1/dex/tokens/trending/list` if available on free tier. | Returns a list of trending symbols (or empty, with fallback documented). | HIGH | MVP |
| 1.5 | Implement `src/cmc_client.py` → `get_global_derivatives_metrics()` (optional, used as a regime filter). | Returns a dict with OI, funding, liquidation summary if endpoint works. | STRETCH | STRETCH |
| 1.6 | Add local SQLite cache in `src/cache.py` for recent quotes and trending data to respect CMC rate limits. | Data is cached and reused for 5 minutes. | HIGH | MVP |
| 1.7 | Write a simple test: `python scripts/test_data.py` fetches allowlist prices and prints them. | Output is reasonable and within rate limits. | CRITICAL | MVP |

**Phase 1 Definition of Done:**
- The agent can fetch live prices and 24h/7d changes for all 149 tokens.
- The agent can fetch DEX trending data or gracefully handle a missing/paid endpoint.
- Data is cached locally.

---

### Phase 2 — Signal & Strategy (Today, June 19)

**Goal:** A single, rule-based spot signal that can be implemented with CMC data that actually exists.

**Signal design:** use only today's CMC `quotes/latest` data plus a small locally cached rolling window. The buy rule uses a **DEX-activity proxy** that can be computed from the free CMC tier: either (a) `volume_24h_usd` from `quotes/latest` compared to the median of the last 5 cached days, or (b) 24h DEX transaction count / volume rank from a DEX endpoint if it is available on the Basic tier. If the proxy is missing, stale, or the cache is empty, fall back to a pure price-momentum rule (24h change > 0 and 7d change > 0). The sell rule is purely price- and time-based. A conservative 0.6% round-trip transaction cost is applied to the expected edge before any buy is approved.

**MVP subset:** 2.1, 2.2 (with fallback), 2.3, 2.5, 2.6. (2.4 and 2.7 are STRETCH.)

| # | Task | Acceptance Criterion | Priority | MVP? |
|---|---|---|---|---|
| 2.1 | Implement `src/signal.py` with the **DEX-activity proxy** rule. | Given sample data, returns a list of buy candidates and sell candidates. | CRITICAL | MVP |
| 2.2 | **Buy rule:** token in allowlist, 7d change > 0, DEX-activity proxy below its 5-day cached median (or pure price-momentum fallback if proxy/cache is missing), not currently in top-3 DEX trending, expected edge > 0.6% round-trip cost. | Unit test passes with synthetic inputs. | CRITICAL | MVP |
| 2.3 | **Sell rule:** token hits top-3 DEX trending, or entry price drops 5%, or entry price rises 10%, or 24h hold timeout. | Unit test passes with synthetic inputs. | CRITICAL | MVP |
| 2.4 | Implement a global risk filter: if Fear & Greed is "Extreme Fear" or global derivatives show a major cascade (BTC 1h liquidation > $100M and funding > 0.05%), skip new entries. | Unit test passes. | STRETCH | STRETCH |
| 2.5 | Implement `src/portfolio.py` to track current holdings and cash from the SQLite log. | Returns accurate available cash and token balances. | CRITICAL | MVP |
| 2.6 | Implement `src/decision.py` that combines signal, portfolio, and risk manager to produce a single trade action per cycle. | Returns `None`, `("buy", symbol, amount)`, or `("sell", symbol, amount)`. | CRITICAL | MVP |
| 2.7 | Add `scripts/test_signal.py` that runs the signal on live CMC data and prints candidates. | Output is sane and respects allowlist. | HIGH | STRETCH |

**Phase 2 Definition of Done:**
- Signal outputs buy/sell candidates on real data.
- Decision engine selects a trade or no-trade each cycle.
- No signal uses social volume, liquidation series, or per-token OI data that does not exist on CMC Basic.

---

### Phase 3 — Execution Layer (Today, June 19 / Early June 20)

**Goal:** Execute spot swaps via TWAK through the MEV Guard RPC.

**MVP subset:** 3.1, 3.2, 3.6, 3.7. (3.3 and 3.4 are HIGH; 3.5 and 3.8 are STRETCH.)

| # | Task | Acceptance Criterion | Priority | MVP? |
|---|---|---|---|---|
| 3.1 | Implement `src/twak.py` — a thin subprocess wrapper around `twak swap`. | Can run `twak swap --chain bsc --quote-only 5 <eligible> BNB` and parse output. | CRITICAL | MVP |
| 3.2 | Implement `src/twak.py` → `execute_swap(from_token, to_token, amount_usd, slippage)` that runs `twak swap` with strict flags. | A $5–$10 mainnet test swap executes and returns a BSCScan tx hash. | CRITICAL | MVP |
| 3.3 | Implement `src/quoter.py` using PancakeSwap QuoterV2 (`0xB048Bbc1Ee6b733FFfCFb9e9CeF7375518e25997`) via the MEV Guard RPC to estimate slippage for the exact token pair. | Returns expected output amount for sample pairs. | HIGH | MVP |
| 3.4 | Implement `src/risk.py` → pre-trade check: slippage estimate must be < 1%; if > 1%, reject the trade. | Unit test rejects high-slippage trade and accepts low-slippage trade. | HIGH | MVP |
| 3.5 | Implement `src/risk.py` → post-trade check: verify the actual realized price is within 1.5% of the QuoterV2 estimate; if not, log an anomaly. | After a test swap, anomaly check runs. | STRETCH | STRETCH |
| 3.6 | Implement `src/twak.py` → `get_balances()` wrapper to refresh BNB + token balances after each trade. | Balances match BSCScan after a test swap. | CRITICAL | MVP |
| 3.7 | Execute a live test swap on BSC mainnet (e.g., $5 of an eligible token → BNB) and confirm the tx on BSCScan. | Tx hash is recorded in `logs/test_swap.txt`. | CRITICAL | MVP |
| 3.8 | Experimental only: if time permits, test whether `twak serve` exposes a `wallet/swap` MCP tool; do not rely on it for the main loop. | Document result in `notes/twak_mcp.md`. | STRETCH | STRETCH |

**Phase 3 Definition of Done:**
- One real mainnet swap has been executed via TWAK + MEV Guard RPC.
- Slippage estimation works.
- Balance tracking works.
- The execution path is reproducible from the terminal.

---

### Phase 4 — Risk & Logging (June 20)

**Goal:** Hard constraints are enforced and every trade is recorded.

**MVP subset:** 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7. (4.8 is HIGH; 4.9 is STRETCH.)

| # | Task | Acceptance Criterion | Priority | MVP? |
|---|---|---|---|---|
| 4.1 | Implement `src/log.py` with SQLite schema: `trades`, `quotes`, `signals`, `drawdown`. | `logs/cascade_fade.db` is created and migrations run. | CRITICAL | MVP |
| 4.2 | Log every trade with: timestamp, side, symbol, amount, entry/exit price, tx hash, signal JSON, CMC snapshot, realized PnL. | A test swap appears in `trades` table with all fields. | CRITICAL | MVP |
| 4.3 | Implement `src/risk.py` → `check_drawdown()` that computes peak-to-trough portfolio value and triggers kill switch at 25%. | Unit test with synthetic prices triggers kill at 25%. | CRITICAL | MVP |
| 4.4 | Implement `src/risk.py` → `check_portfolio_floor()` that stops new trades if portfolio value < $5. | Unit test stops trading at $5. | CRITICAL | MVP |
| 4.5 | Implement `src/risk.py` → `check_heartbeat()` that triggers a tiny eligible-token swap if no trade occurred in the last 22 hours. | Unit test with 23h gap triggers heartbeat action. | CRITICAL | MVP |
| 4.6 | Implement `src/risk.py` → `check_daily_loss()` and kill switch if the day is down > 5% (soft warning) or portfolio is down > 25% (hard stop). | Kill switch triggers at 25%. | CRITICAL | MVP |
| 4.7 | Implement `src/risk.py` → `position_size()` returning a fixed % of portfolio (e.g., 5–10%) per trade, capped by slippage and cash. | Unit test returns correct size for sample inputs. | CRITICAL | MVP |
| 4.8 | Add `scripts/review_logs.py` to print recent trades, PnL, and drawdown from SQLite. | Output matches test data. | HIGH | MVP |
| 4.9 | Optional: add a simple on-chain hash anchor for the trade journal. | If implemented, script posts a daily hash to a memo self-transfer tx. | LOW | STRETCH |

**Phase 4 Definition of Done:**
- All trades are logged in SQLite with full context.
- 25% drawdown and $5 portfolio floor are enforced by tests.
- Daily heartbeat trade is enforced by tests.

---

### Phase 5 — Main Agent Loop (June 20)

**Goal:** A single asyncio process that runs the full cycle continuously.

**MVP subset:** 5.1, 5.2, 5.3, 5.6, 5.7 (2-hour minimum). (5.4 and 5.5 are HIGH; 4-hour run is STRETCH.)

| # | Task | Acceptance Criterion | Priority | MVP? |
|---|---|---|---|---|
| 5.1 | Implement `src/agent.py`: 30-min asyncio loop; wake at **20:00 UTC daily** for heartbeat trade if none has occurred. | Loop runs for 2 hours in paper mode without crashing. | CRITICAL | MVP |
| 5.2 | Add a `--paper` mode where trades are logged but not sent to TWAK. | Paper mode produces log entries with "paper" flag. | CRITICAL | MVP |
| 5.3 | Add a `--live` mode that actually submits trades. | Live mode calls `src/twak.execute_swap`. | CRITICAL | MVP |
| 5.4 | Add graceful shutdown: on `SIGINT`, stop new entries, do not close existing positions automatically (to avoid forced losses). | SIGINT handler logs shutdown and exits cleanly. | HIGH | MVP |
| 5.5 | Add health check: print status every cycle with portfolio value, last trade, next heartbeat, current drawdown. | Terminal output is readable. | HIGH | MVP |
| 5.6 | Add `run.sh` script that sets env, activates venv, and runs the agent in `tmux` or `nohup`. | `./run.sh --live` starts the agent. | CRITICAL | MVP |
| 5.7 | Run the agent in paper mode for at least **2 hours** with real CMC data; 4 hours as stretch. | Logs show decisions, no crashes, rate limits respected. | CRITICAL | MVP |

**Phase 5 Definition of Done:**
- The agent runs continuously in paper mode for at least 2 hours (4 hours as stretch).
- Live mode can be toggled with a flag or env variable.
- `run.sh` starts and restarts the agent reliably.

---

### Phase 6 — Docs, Demo, Submission (June 20–21)

**Goal:** Submit a clean, consistent, and honest project by June 21 10:00 UTC.

**MVP subset:** 6.1, 6.2, 6.3, 6.5, 6.6, 6.7, 6.8. (6.4 is HIGH; 6.9 is HIGH; 6.10 is STRETCH.)

| # | Task | Acceptance Criterion | Priority | MVP? |
|---|---|---|---|---|
| 6.1 | Rewrite `ARCHITECTURE.md` to reflect the simplified 2-layer design (Data → Trader/Execution → Logging). No perps, no ERC-8183 PnL ledger, no dashboard. | Doc is consistent with audits and the code that is built. | CRITICAL | MVP |
| 6.2 | Rewrite `SUBMISSION.md` to remove false claims (ERC-8183 PnL, BNB x402, perps, BNB benchmark, 100% sandwich prevention). | Special prize sections are truthful and evidence-based. | CRITICAL | MVP |
| 6.3 | Write `README.md` with: one-paragraph description, alpha thesis, setup steps, run commands, risk guardrails, BSCScan wallet address, evidence links, and a disclaimer. | README is complete enough for a judge to understand and reproduce. | CRITICAL | MVP |
| 6.4 | Write `POLICY.md` documenting the developer-defined limits (daily spend, allowlist, max slippage, kill switch). | Policy is human-readable and matches code. | HIGH | MVP |
| 6.5 | Record a 3-minute demo video: show terminal, one test swap on BSCScan, SQLite log, and risk guardrail explanation. | Video is uploaded to a public URL (YouTube/Vimeo). | CRITICAL | MVP |
| 6.6 | Prepare DoraHacks submission form: project name, tagline, description, GitHub link, demo video, track, special prize selections, **and the exact TWAK wallet address**. | All fields are ready before 10:00 UTC June 21; address matches `twak compete register`. | CRITICAL | MVP |
| 6.7 | Make the GitHub repository public. | Repo is accessible without authentication. | CRITICAL | MVP |
| 6.8 | Submit the DoraHacks form by **10:00 UTC June 21** (2 hours before hard deadline). | Submission confirmation received. | CRITICAL | MVP |
| 6.9 | Apply for special prizes (Best TWAK, Best BNB SDK, Best Agent Hub) with truthful explanations only after the main submission is complete. | Special prize entries are submitted. | HIGH | STRETCH |
| 6.10 | Optional: generate a simple `demo/chart_pnl.py` script that draws a PnL chart from SQLite for the demo video. | Script runs and produces PNG. | STRETCH | STRETCH |

**Phase 6 Definition of Done:**
- DoraHacks form is submitted with the wallet address that matches `twak compete register`.
- Repo is public with clean docs.
- Demo video is public.
- Agent is ready to run live starting June 22.

---

## 6. Simplified File Structure

```
track1-cascade-fade/
├── old/
│   ├── ARCHITECTURE.md          # Original docs (reference only, untouched)
│   ├── PLAN.md
│   └── SUBMISSION.md
├── src/
│   ├── __init__.py
│   ├── agent.py                 # Main asyncio loop (paper + live modes)
│   ├── config.py                # Env, 149-token allowlist, risk constants, addresses
│   ├── cmc_client.py            # Async CMC REST client with cache and retries
│   ├── cache.py                 # SQLite-based local data cache
│   ├── signal.py                # DEX-activity proxy rule
│   ├── decision.py              # Combine signal, portfolio, risk → trade action
│   ├── portfolio.py             # Current holdings and cash from SQLite log
│   ├── twak.py                  # TWAK CLI subprocess wrapper
│   ├── quoter.py                # PancakeSwap QuoterV2 slippage estimator
│   ├── risk.py                  # Drawdown, portfolio floor, heartbeat, sizing
│   ├── log.py                   # SQLite trade journal + PnL calc
│   └── utils.py                 # Helpers (checksum, retry, formatting)
├── scripts/                     # Runnable diagnostics and one-off tests
│   ├── test_data.py             # Verify CMC data fetch
│   ├── test_signal.py           # Verify signal logic on live data
│   ├── test_swap.py             # Execute one live test swap
│   └── review_logs.py           # Print trade log and PnL
├── tests/                       # Unit tests
│   └── test_risk.py             # Drawdown, floor, heartbeat, position size
├── demo/
│   └── chart_pnl.py             # Optional: PnL chart generator for video
├── logs/
│   └── cascade_fade.db          # SQLite journal (created at runtime, not committed)
├── README.md
├── ARCHITECTURE.md
├── PLAN.md
├── SUBMISSION.md
├── POLICY.md
├── requirements.txt
├── .env.example
├── .gitignore
└── run.sh
```

---

## 7. Hard Constraints Checklist (Verify Before Going Live)

These must be confirmed before the trading window opens.

| # | Constraint | Verification Method | Status |
|---|---|---|---|
| 1 | Agent wallet registered via `twak compete register` before June 22; same address is also entered on the DoraHacks submission form. | BSCScan transaction for `0x212c61b9b72c95d95bf29cf032f5e5635629aed5`; form field saved. | ☐ |
| 2 | 149-token allowlist is hardcoded and all trades stay inside it. | `python -c "from src.config import ALLOWLIST; print(len(ALLOWLIST))"` returns 149. | ☐ |
| 3 | Agent guarantees ≥1 trade/day via heartbeat trade. | `tests/test_risk.py` shows heartbeat triggers after 23h gap. | ☐ |
| 4 | 25% portfolio drawdown hard stop is in code and tested. | `tests/test_risk.py` passes kill-switch test. | ☐ |
| 5 | $5 portfolio floor soft stop is in code and tested. | `tests/test_risk.py` passes floor test. | ☐ |
| 6 | PancakeSwap MEV Guard RPC is configured as `https://bscrpc.pancakeswap.finance`. | `.env` and `config.py` use the verified URL. | ☐ |
| 7 | No perp logic in the code path. | Grep returns no matches for `aster`, `orderly`, `perp`, `short_position`, `_short`, `short_trade`. | ☐ |
| 8 | No ERC-8183 PnL ledger claims in code or docs. | Grep returns no matches for `ERC-8183` in docs except truthful context. | ☐ |
| 9 | CMC x402 asset is correctly described as USDC on Base (if used). | `README.md`/`SUBMISSION.md` does not claim BNB-funded x402. | ☐ |
| 10 | Submission is made by 10:00 UTC June 21, and agent is ready to start June 22. | DoraHacks confirmation email/screenshot saved. | ☐ |
| 11 | Wallet holds non-zero balance of eligible assets at competition start. | `twak wallet balance` shows USDT/BNB before June 22. | ☐ |
| 12 | Demo video is public and under 3 minutes. | Video URL works in an incognito window. | ☐ |
| 13 | Repo is public and README contains the BSCScan wallet address. | Repo is accessible and README is accurate. | ☐ |
| 14 | Paper-mode run of at least 2 hours completed without crash or rate-limit errors (4+ hours as stretch). | `logs/cascade_fade.db` shows 2+ hours of decisions. | ☐ |
| 15 | Live test swap executed and confirmed on BSCScan. | `scripts/test_swap.py` tx hash is on BSCScan. | ☐ |

---

## 8. Risk Mitigation from Audit Findings

Only findings that are **not already covered** by the hard-constraints checklist or verified-facts table are listed here.

| Audit Finding | Risk | Mitigation |
|---|---|---|
| CMC has no per-token social volume or liquidation series. | Original signal cannot be built. | Replaced with DEX-activity proxy and local cached volume rank. |
| No official source for the full 149-token list. | Wrong allowlist could void trades. | Source from the competition organizer/contract in Phase 0; hardcode the best available list and document any gaps. |
| 14-day plan is obsolete. | Submission deadline missed. | Compressed to 5 phases over 1.5 days with a hard MVP cut line. |

---

## 9. Special Prize Alignment

### Best Use of Trust Wallet Agent Kit — Target Score (Conditional)

> The table below shows the **maximum target** score if all pieces are implemented and judged favorably. x402 is optional; originality and demo are subjective and judged by reviewers, not guaranteed.

| Criterion | How CascadeFade Satisfies It | Target Points | Conditional? |
|---|---|---|---|
| TWAK integration depth | Entire execution layer runs through `twak swap` and `twak wallet balance`; agent is built around TWAK CLI. | 30/30 | Confident |
| Self-custody integrity | Keys stay in `~/.twak/wallet.json`; password via env/keychain; no custody transfer. | 25/25 | Confident |
| Autonomous execution + guardrails | Python loop calls TWAK within policy limits (daily spend, allowlist, slippage). | 20/20 | Confident |
| x402 usage | `twak x402 request` demonstrates self-funding (USDC on Base) **if implemented**. | 0/10 if skipped, 10/10 if implemented | Optional |
| Originality | "Buy the calm. Sell the crowd." thesis. | 10/10 | Subjective |
| Demo | Video shows the terminal loop, a real BSC tx, and risk guardrails. | 5/5 | Subjective |
| **Maximum total** | | **100/100** | Only if all optional/subjective rows score full. |

### Best Use of BNB AI Agent SDK ($2K)

> ERC-8004 identity is a **stretch goal** (Phase 0.13). If time runs out, the agent still qualifies via BSCScan wallet history.

| Criterion | How CascadeFade Satisfies It |
|---|---|
| ERC-8004 identity | Agent registers an on-chain identity NFT if time permits. |
| Verifiable PnL | BSCScan wallet address is the canonical ledger; SQLite journal provides structured audit trail. |
| No false ERC-8183 PnL claims | We do not misrepresent ERC-8183. If ERC-8183 is used at all, it is only as a genuine commerce/escrow demo (optional, out of main loop). |

### Best Use of CMC AI Agent Hub ($2K)

| Criterion | How CascadeFade Satisfies It |
|---|---|
| Reads markets via CMC | Prices, DEX trending, and global derivatives metrics all come from CMC REST or MCP. |
| x402 demo (optional) | One paid request via CMC x402 demonstrates self-funding. |
| No dependency on paid-only data | Strategy works on CMC Basic tier. |

---

## 10. Definition of Done

Submission-ready when the MVP cut line (§1.2) is met **and**:

1. The DoraHacks form is submitted by 10:00 UTC June 21 with the exact TWAK wallet address that was registered via `twak compete register` (same address on-chain and on the form).
2. The GitHub repository is public with README, ARCHITECTURE, PLAN, and SUBMISSION.
3. A 3-minute demo video is recorded and publicly accessible.
4. The agent has run in paper mode for at least 2 hours (4 hours as stretch) without crashes or rate-limit errors.
5. The agent is ready to start live trading at the beginning of the June 22 window.

---

## 11. Day-by-Day Execution Schedule (June 19–21)

| Date | Time Block | Focus | Output |
|---|---|---|---|
| **June 19 (today)** | Rest of day | Phases 0–2: setup, wallet, funding, registration, CMC data, signal, paper test. | Wallet funded and registered; agent can fetch data and decide in paper mode. |
| **June 20** | Morning | Phases 3–4: TWAK execution, slippage check, SQLite logging, risk guardrails, main loop. | Test swap executed; live mode ready; risk tests pass. |
| **June 20** | Afternoon/evening | Phase 5: paper-mode run; debug; live-mode dry run. | 4+ hour paper run completed; no crashes. |
| **June 21** | Morning | Phase 6: final docs, demo video, repo public, DoraHacks submission. | Submission confirmed by 10:00 UTC. |
| **June 22** | Before window | Start live agent; verify heartbeat and first trade. | Agent begins autonomous trading. |
| **June 22–28** | Daily check | Verify heartbeat trade executed; watch drawdown and gas. | 7+ trades completed; within risk limits. |

---

## 12. Evidence & Sources

All claims in this plan are derived from the following audit reports and should be traceable back to them:

- `$M/audit/00-key-corrections.md` — consolidated corrections for all writers.
- `$M/audit/01-rules-constraints.md` — official DoraHacks/BNB Chain rules, hard constraints, false positives.
- `$M/audit/02-twak-integration.md` — TWAK CLI capabilities, MCP, x402, version, perp limitations.
- `$M/audit/03-bnb-sdk.md` — ERC-8004 identity, ERC-8183 commerce protocol, MegaFuel, x402 asset.
- `$M/audit/04-pancakeswap-mev.md` — PancakeSwap v3 addresses, MEV Guard RPC, aggregator limitations.
- `$M/audit/05-cmc-agent-hub.md` — CMC MCP/REST/x402 endpoints, free-tier limits, data gaps.
- `$M/audit/06-aster-orderly-perps.md` — Aster/Orderly perp feasibility, TWAK limitations.
- `$M/audit/07-architecture-critique.md` — simplified architecture and 1-day MVP recommendation.

---

*End of refined PLAN.md.*
