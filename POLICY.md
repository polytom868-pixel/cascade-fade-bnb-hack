# CascadeFade — Developer-Defined Policy

> This document describes the hard limits and guardrails enforced by the agent **and** by the TWAK CLI developer policy.

## Daily Limits

| Parameter | Value | Rationale |
|---|---|---|
| **Max daily trades** | 5 | Prevents overtrading and gas waste |
| **Max daily spend** | $100 | Caps capital at risk per day |
| **Max single trade** | $100 | No trade approaches disqualification threshold |
| **Min trade** | $5 | Heartbeat size; ensures on-chain tx counts |

## Asset Restrictions

- **Allowlist only:** Only tokens in `src/config.py` `ALLOWLIST` may be traded.
- **No external transfers:** Agent only swaps between allowlist tokens and BNB/USDT.
- **No new token deployments:** Agent does not deploy, mint, list, or create any token.
- **Stablecoin preference:** Heartbeat uses BNB↔USDT for minimal price risk.

## Slippage & Execution

- **Max slippage:** 1% per trade. Rejected if exceeded.
- **Slippage sanity:** QuoterV2 check before every swap.
- **RPC:** All txs via PancakeSwap MEV Guard (`https://bscrpc.pancakeswap.finance`).
- **No public mempool fallback:** If MEV Guard RPC is down, agent retries once. No unprotected submission.

## Risk Kill Switches

| Trigger | Action |
|---|---|
| Portfolio drawdown ≥ 25% | **Close ALL positions, halt trading** |
| Portfolio value < $5 | Stop new entries; heartbeat only |
| Per-trade loss ≥ 5% | Close position |
| Per-trade gain ≥ 10% | Close position (take profit) |
| Hold time ≥ 48h | Close position (time decay) |
| CMC data stale > 30 min | No new entries; manage existing only |
| BSC RPC unavailable > 5 min | Halt; alert operator |
| Manual `kill.json` flag | Immediate market-close of all positions |

## TWAK Policy Flags (per-command)

Every `twak swap` call includes:
```bash
--chain bsc --slippage 0.5 --json
```

## Kill Switch File

Create `logs/kill.json` with `{"kill": true}` to trigger immediate shutdown on next cycle.
