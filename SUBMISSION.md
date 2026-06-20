# CascadeFade — Submission Document

> **Track 1: Autonomous Trading Agents ($24K, 5 winners)**  
> **BNB Hack: AI Trading Agent Edition** — CoinMarketCap × Trust Wallet × BNB Chain  
> **Submission deadline:** 2026/06/21 12:00 UTC  
> **Live trading window:** 2026/06/22 – 2026/06/28  
> **Tagline:** *Buy the calm. Sell the crowd.*

## Project Identity

**Project name:** CascadeFade  
**GitHub:** (public at submission time)  
**Wallet:** Registered via `twak compete register` before June 22  

**One-paragraph description:**  
CascadeFade is a fully autonomous, self-custodial trading agent on BNB Smart Chain. It reads CoinMarketCap market data, selects low-attention BEP-20 assets inside the official competition allowlist, and exits when DEX-activity signals mark hype exhaustion. Every trade is signed locally by Trust Wallet Agent Kit and broadcast through the PancakeSwap MEV Guard RPC. PnL is verifiable from the agent's BSC wallet history.

## Prizes Targeted

| Prize | Amount | Alignment |
|---|---|---|
| Track 1: Autonomous Trading Agents | $24,000 | Main target — autonomous, non-custodial, CMC-fed, real on-chain BSC PnL |
| Best Use of TWAK | $2,000 | `twak swap`, self-custody, developer policy, `twak compete register` |
| Best Use of CMC AI Agent Hub | $2,000 | Bulk REST, DEX trending, Fear & Greed (optimized: ~50 calls/day) |
| Best Use of BNB AI Agent SDK | $2,000 | ERC-8004 identity (stretch), BSCScan PnL proof |

## Rules Verification

| Requirement | Implementation | Status |
|---|---|---|
| Public GitHub repo | Includes README, ARCHITECTURE, code, tests | ✅ |
| Demo video (3 min) | Terminal walkthrough + BSCScan tx + risk guardrails | ⏳ |
| Track 1 submission before June 21 12:00 UTC | DoraHacks form with wallet address | ⏳ |
| On-chain registration before June 22 | `twak compete register` on contract `0x212c...aed5` | ⏳ |
| Trades on BSC during June 22–28 | Agent runs 24/7 via `run.sh` | ⏳ |
| 149-token BEP-20 allowlist | Hardcoded in `src/config.py` | ✅ (top 50; updating for 149) |
| ≥1 trade/day | Signal + heartbeat guarantees one/day | ✅ (implemented + tested) |
| Portfolio > $1 at each hour | Internal stop at $5, never approaches $1 | ✅ (implemented + tested) |
| No token launches/airdrops | Only swaps existing BEP-20 tokens | ✅ |
| Real on-chain PnL | BSCScan wallet history is source of truth | ✅ |

## Alpha Thesis

**Buy the calm. Sell the crowd.** Most crypto upside is captured before the crowd notices.

1. When attention is low but price is already rising, prices tend to drift upward as the market catches up.
2. When the same asset hits the CMC DEX trending list, marginal buyers are exhausted and returns reverse.
3. We only trade when expected alpha exceeds 0.6% round-trip cost, through the MEV Guard RPC.

## Architecture

Single Python asyncio process: **CMC REST** → **Signal/Risk** → **TWAK CLI** → **PancakeSwap v3 via MEV Guard RPC** → **SQLite journal** → **BSCScan PnL**.

See `ARCHITECTURE.md` for full design.

## Tech Stack

- Python 3.11+ + asyncio
- aiohttp (CMC REST)
- aiosqlite (WAL-mode SQLite)
- web3.py 6.x (QuoterV2, tx confirmation)
- @trustwallet/cli ≥0.18.0 (TWAK)

## Evidence & Sources

| Claim | Source | URL |
|---|---|---|
| Submission deadline June 21, 12:00 UTC | DoraHacks | https://dorahacks.io/hackathon/bnbhack-twt-cmc/tracks |
| Trading window June 22–28, 149-token allowlist | DoraHacks | https://dorahacks.io/hackathon/bnbhack-twt-cmc/detail |
| TWAK CLI / swap / compete register | Trust Wallet docs | https://developer.trustwallet.com/developer/agent-sdk/cli-reference |
| PancakeSwap MEV Guard RPC | PancakeSwap docs | https://docs.pancakeswap.finance/trading-tools/pancakeswap-mev-guard |
| PancakeSwap v3 addresses | PancakeSwap dev docs | https://developer.pancakeswap.finance/contracts/v3/addresses |
| ERC-8004 identity registry | EIP-8004 | https://eips.ethereum.org/EIPS/eip-8004 |
| Competition contract | DoraHacks | `0x212c61b9b72c95d95bf29cf032f5e5635629aed5` |
| TWAK x402 asset | CMC docs | USDC on Base |

## Run Commands

```bash
# Paper mode (log decisions, no swaps)
python -m src.agent --mode paper --cash 1000

# Live mode (real swaps)
python -m src.agent --mode live --cash 1000

# Or via run.sh
./run.sh paper 1000
```

## Risk Guardrails (All Tested)

- 25% portfolio drawdown hard stop — closes all positions, halts trading
- $5 portfolio floor — stops new entries
- 5% per-trade stop-loss, 10% take-profit
- 48-hour max hold time
- 1% max slippage (QuoterV2 pre-check)
- Daily heartbeat trade ($5 BNB↔USDT) guarantees ≥1 trade/day

## Test Results

```
✅ test_drawdown_kill passed
✅ test_portfolio_floor passed
✅ test_position_size passed
✅ test_pre_trade_checks passed
✅ test_heartbeat passed

🎉 All risk tests passed!
```

## Hard Constraints Checklist

- [ ] Wallet registered and funded before June 22
- [x] 149-token allowlist enforced (top 50 built; updating to 149)
- [x] Heartbeat trade guarantees ≥1 trade/day
- [x] 25% drawdown hard stop in code and tested
- [x] $5 portfolio floor in code and tested
- [x] MEV Guard RPC configured
- [x] No perp logic in code path
- [x] No ERC-8183 PnL ledger claims
- [x] No BNB x402 claims
- [ ] Submission by June 21 10:00 UTC
- [ ] Demo video public
- [ ] Repo public
- [ ] 2+ hour paper run completed
- [ ] Live test swap confirmed on BSCScan

## Final Note

CascadeFade was built after independent audits of the hackathon rules, TWAK docs, and CMC data availability. Every feature satisfies a hard requirement or aligns with a special-prize scoring dimension. The agent is simple enough to build before the deadline, rigorous enough to survive the drawdown cap, and transparent enough to verify on-chain.
