# CascadeFade — System Architecture (Built)

> **Track 1: Autonomous Trading Agents** | BNB Hack: AI Trading Agent Edition  
> Trading window: **June 22 – 28, 2026**

## 1. System Overview

CascadeFade is a **spot-only, autonomous BSC trading agent**. It reads market data from the CoinMarketCap AI Agent Hub, evaluates a rule-based signal, executes non-custodial swaps through Trust Wallet Agent Kit (TWAK), and records a local SQLite trade journal. The verifiable PnL ground truth is the **registered TWAK wallet's BSC transaction history** on BSCScan.

**Built as a single Python 3.11+ asyncio process.** No Docker, Redis, dashboard, or web server.

```
CMC AI Hub (REST) → Signal Evaluator → Risk Manager → TWAK CLI → PancakeSwap v3 (MEV Guard RPC)
                           ↓                  ↓
                    SQLite Cache      SQLite Trade Journal
                           ↓                  ↓
                    BSCScan (tx hashes)    BSCScan (PnL truth)
```

## 2. Principles

1. **Spot-only** — TWAK supports `twak swap` and ERC-20 transfers. No perp or short primitive exists.
2. **Non-custodial** — TWAK wallet is created locally; the agent never holds the mnemonic.
3. **Hard constraints first** — Daily heartbeat trade, 25% drawdown hard stop, 149-token allowlist.
4. **Evidence-backed** — Every claim drawn from official docs and verified contract addresses.

## 3. Data Layer

**Source:** CoinMarketCap REST API (free Basic tier, 15K credits/month).

| Endpoint | Path | Rate | Purpose |
|---|---|---|---|
| Bulk quotes | `GET /v2/cryptocurrency/quotes/latest` | 1 call per cycle | All 149 token prices in one request |
| Fear & Greed | `GET /v3/fear-and-greed/latest` | 1 call per day | Global risk backdrop |
| DEX Trending | `POST /v1/dex/tokens/trending/list` | 1 call per 2h | Exit signal: attention proxy |

**Optimization:** Instead of 149 individual calls per poll, the agent uses bulk `id=` parameter — reducing the entire data fetch to ~1 call per 30-minute cycle (~50 calls/day, well under free tier).

**Cache:** 5-minute SQLite WAL-mode cache (`src/cache.py`) to avoid redundant API calls.

## 4. Decision Layer

### Signal: Low-Attention Momentum Fade

**Buy (ALL must be true):**
1. Token is in the hardcoded allowlist.
2. 7-day price change > 0 (positive drift).
3. Token is NOT in CMC top-3 DEX trending.
4. Token is not already held (max 2 positions).
5. Fear & Greed is not "Extreme Fear".
6. Expected edge > 0.6% round-trip cost.
7. QuoterV2 slippage estimate < 1%.

**Sell (ANY true):**
1. Token enters top-3 CMC DEX trending (attention peak).
2. Stop-loss: -5% from entry.
3. Take-profit: +10% from entry.
4. 48-hour max hold timeout.
5. Portfolio drawdown hits 25% (hard kill).

**Daily heartbeat:** If no natural trade in 22 hours, a $5 BNB↔USDT swap guarantees the ≥1 trade/day minimum.

### Risk Manager

| Parameter | Value | Enforced In |
|---|---|---|
| Hard drawdown stop | 25% | `src/risk.py` + tests |
| Per-trade stop-loss | 5% | `src/signal.py` |
| Per-trade take-profit | 10% | `src/signal.py` |
| Max concurrent positions | 2 | `src/signal.py` |
| Max exposure per trade | 10% portfolio | `src/risk.py` |
| Min heartbeat trade | $5 | `src/risk.py` |
| Portfolio floor | $5 | `src/risk.py` + tests |
| Max slippage | 1% | `src/risk.py` + pre-trade check |

## 5. Execution Layer

### TWAK CLI

All swaps executed via subprocess:
```bash
twak swap <amount> <from> <to> --chain bsc --slippage 0.5 --json
```

- `--json` for machine-parseable output.
- Default chain is `ethereum` — **must always pass `--chain bsc`**.
- `--quote-only` for slippage preview before execution.

### PancakeSwap v3 + MEV Guard RPC

- RPC: `https://bscrpc.pancakeswap.finance` (Chain ID 56)
- QuoterV2: `0xB048Bbc1Ee6b733FFfCFb9e9CeF7375518e25997`
- Fee tiers tried: 100 (0.01%), 500 (0.05%), 3000 (0.25%), 10000 (1%)
- Smart Router fallback address: `0x13f4EA83D0bd40E75C8222255bc855a974568Dd4`

### Execution flow

1. QuoterV2 sanity check — verify slippage < 1%.
2. TWAK swap with `--quote-only` preview.
3. Live swap execution (if not in paper mode).
4. Poll BSCScan for tx receipt confirmation.
5. Log to SQLite with tx hash, CMC snapshot, PnL.

## 6. Logging & Proof

### On-chain PnL (source of truth)

The official hackathon evaluates **real on-chain total return**. The canonical proof is the **registered TWAK wallet's transaction history on BSCScan**.

### Local trade journal (audit trail)

SQLite schema in `logs/cascade_fade.db`:

| Table | Fields |
|---|---|
| `trades` | timestamp, side, symbol, token_in/out, amount_in/out, prices, slippage, tx_hash, signal_snapshot, realized_pnl, portfolio_value, mode, status |
| `positions` | symbol, entry_ts, entry_price, amount, tx_hash, stop_price, take_price, open |
| `portfolio_snapshots` | ts, total_value, cash_value, positions_value, peak_value |
| `cmc_quotes` | symbol, data_json, timestamp (cache) |

### Optional on-chain hash anchor

Periodically compute `keccak256` of the journal and post as a self-transfer `data` field. Implemented in `src/log.py` as optional stretch.

## 7. Deployment

- Single Python asyncio process.
- Runs in `tmux` session or `nohup` background.
- Graceful shutdown on SIGINT/SIGTERM.
- Health check printed every cycle: portfolio value, drawdown, held positions, next heartbeat.

## 8. Tech Stack

| Tool | Version | Purpose |
|---|---|---|
| Python | 3.11+ | Core runtime |
| aiohttp | 3.x | Async CMC REST client |
| aiosqlite | 0.19+ | WAL-mode SQLite journal |
| web3.py | 6.x | QuoterV2 reads, tx confirmation |
| TWAK CLI | ≥0.18.0 | Non-custodial signing and swaps |
| CMC AI Agent Hub | REST | Price, trending, Fear & Greed |

## 9. Special Prize Alignment

### Best Use of Trust Wallet Agent Kit
- Full execution layer via `twak swap`, `twak wallet balance`, `twak compete register`
- Self-custody: keys in `~/.twak/wallet.json`, password via env
- Developer policy in `POLICY.md`

### Best Use of CMC AI Agent Hub
- Bulk price fetch via REST, DEX trending, Fear & Greed
- Optimized: ~50 calls/day, well under free tier

### Best Use of BNB AI Agent SDK
- ERC-8004 identity registration (stretch: Phase 0.13)
- Wallet registered on `0x212c...aed5` before trading window

## 10. Verified Contracts

| Name | Address |
|---|---|
| PancakeSwap V3 Smart Router | `0x13f4EA83D0bd40E75C8222255bc855a974568Dd4` |
| PancakeSwap V3 QuoterV2 | `0xB048Bbc1Ee6b733FFfCFb9e9CeF7375518e25997` |
| PancakeSwap V3 SwapRouter | `0x1b81D678ffb9C0263b24A97847620C99d213eB14` |
| WBNB | `0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c` |
| Competition Registration | `0x212c61b9b72c95d95bf29cf032f5e5635629aed5` |
| ERC-8004 Registry | `0x8004A169FB4a3325136EB29fA0ceB6D2e539a432` |
