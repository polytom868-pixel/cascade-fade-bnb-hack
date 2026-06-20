# CascadeFade — Build Context for Agents

## Project Overview

**CascadeFade** is an autonomous, self-custodial spot-only trading agent on BNB Smart Chain (BSC) for BNB Hack Track 1. It reads CoinMarketCap data, evaluates a "low-attention momentum fade" signal, and executes swaps via Trust Wallet Agent Kit (TWAK) through PancakeSwap v3 with MEV Guard RPC.

- **Submission deadline:** June 21, 2026, 12:00 UTC
- **Trading window:** June 22–28, 2026
- **Tagline:** *Buy the calm. Sell the crowd.*

## Key Decisions from Research

### CMC API Strategy
- Use **v2 REST** (`/v2/cryptocurrency/quotes/latest`) with comma-separated `id` parameter to bulk-fetch all 149 token prices in **1 call per poll**.
- Poll every 30 min = ~48 calls/day = ~1,440/month for quotes. Well under 15K free tier.
- DEX trending: `POST /v1/dex/tokens/trending/list` — likely on Basic tier. If unavailable, fallback to price-based exits.
- Auth header: `CMC_API_KEY` for REST, `X-CMC_MCP-API-KEY` for MCP. We use REST only.

### TWAK Execution
- Always pass `--json --chain bsc --slippage 0.5`.
- Default chain is `ethereum` — **must specify `--chain bsc`**.
- `--quote-only` for slippage preview before execution.
- After swap, poll `w3.eth.get_transaction_receipt(tx_hash)` for confirmation.

### SQLite + Asyncio
- Use **`aiosqlite`** (not stdlib sqlite3).
- Config: `PRAGMA journal_mode = WAL`, `PRAGMA synchronous = NORMAL`, `timeout=60`.
- Write transactions use `BEGIN IMMEDIATE`.

### QuoterV2
- Address: `0xB048Bbc1Ee6b733FFfCFb9e9CeF7375518e25997` on BSC mainnet.
- Function: `quoteExactInputSingle(tuple params)` where params = `{tokenIn, tokenOut, fee, amountIn, sqrtPriceLimitX96}`.
- Fee tiers: 100 (0.01%), 500 (0.05%), 3000 (0.25%), 10000 (1%).
- Try all 4 tiers, pick best `amountOut`.

### Allowlist (CRITICAL MISSING)
- Official 149-token list is NOT published anywhere verified as of 2026-06-20.
- **Build with top 50 BEP-20 tokens** by market cap. Make the list swappable in `src/config.py`.
- Document: "Will be updated with official list before trading window."

### Price & Drawdown
- Primary: CMC bulk quotes call.
- Fallback: QuoterV2 for held positions (on-chain, no stale data).
- Drawdown uses the **more conservative** of CMC and QuoterV2 prices.

### x402
- TWAK blog shows `twak x402 pay --asset BNB` but architecture says USDC on Base.
- **Treat as untested.** Skip x402 for MVP. Document as optional stretch.

### PancakeSwap MEV Guard RPC
- URL: `https://bscrpc.pancakeswap.finance` (Chain ID 56).
- Default in `config.py` and `.env`.

## Hard Constraints (Must Verify Before Going Live)

1. Wallet registered via `twak compete register` before June 22.
2. 149-token allowlist enforced.
3. ≥1 trade/day via heartbeat.
4. 25% drawdown hard stop.
5. $5 portfolio floor.
6. MEV Guard RPC configured.
7. No perp logic.
8. No ERC-8183 PnL claims.
9. No BNB x402 claims.
10. Submission by June 21 10:00 UTC.
11. Wallet funded before June 22.
12. Demo video public.
13. Repo public with README.
14. 2+ hour paper run completed.
15. Live test swap confirmed on BSCScan.

## Verified Contract Addresses (BSC Mainnet)

| Contract | Address |
|---|---|
| PancakeSwap V3 Smart Router | `0x13f4EA83D0bd40E75C8222255bc855a974568Dd4` |
| PancakeSwap V3 QuoterV2 | `0xB048Bbc1Ee6b733FFfCFb9e9CeF7375518e25997` |
| PancakeSwap V3 SwapRouter | `0x1b81D678ffb9C0263b24A97847620C99d213eB14` |
| WBNB | `0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c` |
| Competition Registration | `0x212c61b9b72c95d95bf29cf032f5e5635629aed5` |
| ERC-8004 Identity Registry | `0x8004A169FB4a3325136EB29fA0ceB6D2e539a432` |

## Tech Stack

- Python 3.11+ with asyncio
- `aiohttp` for CMC REST
- `web3.py` 6.x for QuoterV2 and tx confirmation
- `aiosqlite` for SQLite trade journal
- `twak` CLI 0.18.0+ for execution
- `toml` for config

## File Structure

```
track1-cascade-fade/
├── src/
│   ├── __init__.py
│   ├── agent.py          # Main asyncio loop
│   ├── config.py         # Env, allowlist, constants, addresses
│   ├── cmc_client.py     # Async CMC REST client with cache
│   ├── cache.py          # SQLite-based local data cache
│   ├── signal.py         # DEX-activity proxy rule
│   ├── decision.py       # Combine signal + portfolio + risk
│   ├── portfolio.py      # Current holdings and cash
│   ├── twak.py           # TWAK CLI subprocess wrapper
│   ├── quoter.py         # PancakeSwap QuoterV2 slippage estim
│   ├── risk.py           # Drawdown, floor, heartbeat, sizing
│   ├── log.py            # SQLite trade journal + PnL
│   └── utils.py          # Helpers
├── scripts/
│   ├── test_data.py
│   ├── test_signal.py
│   ├── test_swap.py
│   └── review_logs.py
├── tests/
│   └── test_risk.py
├── logs/
│   └── cascade_fade.db   # Created at runtime
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

## Build Order (Phases)

1. **Project structure + config + .env + .gitignore**
2. **CMC client + cache** (can test standalone)
3. **Signal + portfolio + decision** (pure logic, testable)
4. **TWAK wrapper + QuoterV2** (needs wallet for test swap)
5. **Risk + logging** (SQLite with aiosqlite)
6. **Main agent loop** (asyncio, paper/live modes)
7. **Tests + run.sh**
8. **Docs (README, POLICY, rewrite ARCHITECTURE/SUBMISSION)**

## Risk Constants

| Parameter | Value |
|---|---|
| Hard portfolio drawdown stop | 25% |
| Per-trade stop-loss | 5% |
| Per-trade take-profit | 10% |
| Max concurrent positions | 2 |
| Max exposure per trade | 10% of portfolio |
| Min heartbeat trade size | $5 |
| Portfolio floor | $5 (stop new trades) |
| Max slippage | 1% |
| Max hold time | 48 hours |
| Trade interval | 30 minutes |
| Heartbeat time | 20:00 UTC daily |

## Signals

### Buy (ALL must be true)
1. Token in allowlist
2. 7-day price change > 0
3. Token NOT in top-3 CMC DEX trending (or fallback: not detected as hype)
4. Not already held (max 2 positions)
5. Global fear & greed not "Extreme Fear"
6. Slippage estimate < 1%

### Sell (ANY true)
1. Token enters top-3 CMC DEX trending
2. Price drops 5% from entry (stop-loss)
3. Price rises 10% from entry (take-profit)
4. 48-hour hold timeout
5. Portfolio drawdown hits 25%

## Environment Variables

```
CMC_API_KEY=
TWAK_WALLET_PASSWORD=
TWAK_ACCESS_ID=
TWAK_HMAC_SECRET=
BNB_RPC_URL=https://bscrpc.pancakeswap.finance
TRADE_INTERVAL_MINUTES=30
MAX_POSITIONS=2
MAX_POSITION_PCT=0.10
STOP_LOSS_PCT=0.05
TAKE_PROFIT_PCT=0.10
MAX_DRAWDOWN_PCT=0.25
HEARTBEAT_SIZE_USD=5
MAX_SLIPPAGE_PCT=0.01
```
