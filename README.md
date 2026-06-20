# CascadeFade

> **Buy the calm. Sell the crowd.**  
> A self-custody BSC trading agent that rotates on low DEX attention and exits on hype.

## What It Does

CascadeFade is a fully autonomous, spot-only trading agent on BNB Smart Chain. It reads CoinMarketCap market data, evaluates a **low-attention momentum fade** signal, and executes non-custodial swaps via Trust Wallet Agent Kit through PancakeSwap v3 with MEV Guard protection.

- **Spot-only** — no perps, no leverage, no shorts
- **Self-custodial** — TWAK signs locally; you hold the keys
- **MEV-protected** — routes through PancakeSwap MEV Guard RPC
- **Auditable** — every trade logged to SQLite with CMC snapshot and tx hash
- **Hard stops** — 25% drawdown kill switch, $5 portfolio floor, 5% stop-loss, 10% take-profit

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Set environment
cp .env.example .env
# Edit .env with your CMC_API_KEY, TWAK_WALLET_PASSWORD, TWAK_ACCESS_ID, TWAK_HMAC_SECRET

# 3. Initialize TWAK wallet
twak wallet create --password <strong_password>

# 4. Register for competition
twak compete register --chain bsc

# 5. Run in paper mode (recommended first)
python -m src.agent --mode paper --cash 1000

# 6. Run in live mode (with real swaps)
python -m src.agent --mode live --cash 1000

# Or use the run script
./run.sh paper 1000
```

## Architecture

```
CMC AI Hub → Signal Evaluator → Risk Manager → TWAK → PancakeSwap v3 (MEV Guard)
                                    ↓
                              SQLite Trade Journal
                                    ↓
                              BSCScan (PnL truth)
```

### Strategy: Low-Attention Momentum Fade

1. **Buy** tokens in the 149-token allowlist with:
   - Positive 7-day price drift
   - NOT in the top-3 CMC DEX trending (low attention proxy)
   - Expected edge > 0.6% round-trip cost
   - Slippage < 1%

2. **Sell** when ANY condition hits:
   - Token enters top-3 DEX trending (attention peak)
   - Stop-loss: -5% from entry
   - Take-profit: +10% from entry
   - 48-hour hold timeout
   - Portfolio drawdown hits 25% (hard kill switch)

3. **Daily heartbeat** trade guarantees ≥1 trade/day if no signal fires.

## Risk Guardrails

| Parameter | Value |
|---|---|
| Hard portfolio drawdown stop | **25%** |
| Per-trade stop-loss | 5% |
| Per-trade take-profit | 10% |
| Max concurrent positions | 2 |
| Max exposure per trade | 10% of portfolio |
| Min heartbeat trade | $5 |
| Portfolio floor | $5 |
| Max slippage | 1% |
| Max hold time | 48h |

## Tech Stack

- Python 3.11+ with asyncio
- `aiohttp` for CMC REST
- `web3.py` 6.x for QuoterV2 / BSC reads
- `aiosqlite` for WAL-mode SQLite journal
- `@trustwallet/cli` ≥ 0.18.0 for TWAK execution

## Verified BSC Contracts

| Contract | Address |
|---|---|
| PancakeSwap V3 Smart Router | `0x13f4EA83D0bd40E75C8222255bc855a974568Dd4` |
| PancakeSwap V3 QuoterV2 | `0xB048Bbc1Ee6b733FFfCFb9e9CeF7375518e25997` |
| Competition Registration | `0x212c61b9b72c95d95bf29cf032f5e5635629aed5` |
| ERC-8004 Identity Registry | `0x8004A169FB4a3325136EB29fA0ceB6D2e539a432` |

## File Structure

```
├── src/
│   ├── agent.py          # Main asyncio loop
│   ├── config.py         # Constants, allowlist, addresses
│   ├── cmc_client.py     # Async CMC REST client
│   ├── cache.py          # SQLite cache for CMC data
│   ├── signal.py         # Buy/sell signal rules
│   ├── decision.py       # Cycle orchestration
│   ├── portfolio.py      # Holdings and PnL tracking
│   ├── twak.py           # TWAK CLI wrapper
│   ├── quoter.py         # PancakeSwap QuoterV2
│   ├── risk.py           # Drawdown, heartbeat, sizing
│   ├── log.py            # Trade journal
│   └── utils.py          # Helpers
├── scripts/
│   ├── test_data.py      # Test CMC fetch
│   ├── test_signal.py    # Test signal logic
│   ├── test_swap.py      # Execute one live test swap
│   └── review_logs.py    # Print trade log
├── tests/
│   └── test_risk.py      # Drawdown, floor, heartbeat tests
├── logs/                 # SQLite DB + agent logs (gitignored)
├── .env.example
├── requirements.txt
├── run.sh
└── README.md
```

## License

MIT — built for BNB Hack Track 1.
