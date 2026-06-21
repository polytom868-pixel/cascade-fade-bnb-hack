# CascadeFade
[![Python](https://img.shields.io/badge/python-3.11-blue)](https://python.org)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![BSC](https://img.shields.io/badge/chain-BNB%20Smart%20Chain-yellow)]()
> **Buy the calm. Sell the crowd.** Autonomous, self-custodial BSC trading agent — BNB Hack Track 1.
## What It Does
| Feature | Detail |
|---|---|
| **Spot-only** | No perps, no leverage, no shorts |
| **Self-custodial** | TWAK signs locally; you hold the keys |
| **MEV-protected** | PancakeSwap MEV Guard RPC |
| **Auditable** | SQLite journal + BSCScan PnL |
| **Hard stops** | 25% drawdown kill, $5 floor, 5% SL, 10% TP |
## Paper Run Evidence
| Metric | Value |
|---|---|
| Cycles completed | **40+** |
| Wall-run time | **3h+** |
| Allowlist tokens | **55** (official set) |
| Trades/day | **≥1** (heartbeat) |
| Cycle interval | 5 min |
| CPU mean | ~0% (I/O-bound) |
| RAM peak | 71 MB |
| WAL integrity | ✅ verified |
## Quick Start
```bash
pip install -r requirements.txt
cp .env.example .env
# Edit: CMC_API_KEY, TWAK_ACCESS_ID, TWAK_HMAC_SECRET, TWAK_WALLET_PASSWORD
twak compete register --chain bsc          # needs BNB gas
python3 -m src.agent --mode paper --cash 1000   # paper run
python3 -m src.agent --mode live --cash 1000    # live swaps
```
## Strategy
1. **Buy** when: positive 7d drift, NOT top-3 DEX trending, slippage <1%
2. **Sell** when: DEX trending peak, stop-loss −5%, take-profit +10%, 48h timeout, or 25% drawdown
3. **Heartbeat** guarantees ≥1 trade/day
## Risk Guardrails
| Parameter | Value |
|---|---|
| Portfolio drawdown stop | **25%** |
| Per-trade stop-loss | 5% |
| Per-trade take-profit | 10% |
| Max concurrent positions | 2 |
| Max exposure/trade | 10% of portfolio |
| Portfolio floor | $5 |
| Max slippage | 1% |
| Max hold time | 48h |
## Architecture
```
CMC REST → Signal → Risk → TWAK → PancakeSwap v3 (MEV Guard) → SQLite → BSCScan
```
## Performance
| Optimization | Impact |
|---|---|
| Persistent aiohttp + DNS cache | −400ms/cycle |
| Parallel DB queries + rate-limited logs | −2× wakeups |
| Pre-computed signal weights | −10 exhaustion calls/cycle |
| SQLite BEGIN IMMEDIATE + WAL | Zero contention |
| Gzip CMC + retry | −83% bandwidth |
## Verified Contracts (BSC)
| Contract | Address |
|---|---|
| PancakeSwap V3 Router | `0x13f4EA83D0bd40E75C8222255bc855a974568Dd4` |
| QuoterV2 | `0xB048Bbc1Ee6b733FFfCFb9e9CeF7375518e25997` |
| Competition Registration | `0x212c61b9b72c95d95bf29cf032f5e5635629aed5` |
## Files
`src/agent.py` `src/config.py` `src/signal.py` `src/decision.py` `src/portfolio.py` `src/risk.py` `src/twak.py` `src/cmc_client.py` `src/quoter.py` `src/cache.py` `src/log.py`
MIT — BNB Hack Track 1.
