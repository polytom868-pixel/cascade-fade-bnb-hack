# Agent C — Runtime Fix Verification

**Date**: 2026-06-20
**Files changed**: `src/agent.py`, `src/decision.py`

---

## Errors Fixed (Before vs After)

| # | File | Line | Error | Severity | Fix |
|---|---|---|---|---|---|
| 1 | `src/agent.py` | 146 | `self.twak.price()` does not exist → **runtime crash on cycle 2** | HIGH | Replaced with `cmc.get_bulk_quotes()` over all held + basket + risk tokens |
| 2 | `src/agent.py` | 146 | `price_map` built only for held symbols; basket tokens got $1.00 fiction price | HIGH | Now fetches prices for ALL symbols in `NARRATIVE_BASKETS` |
| 3 | `src/agent.py` | pass | `initial_cash` hardcoded; cash never decremented after buys | HIGH | Now calls `await self.portfolio.get_cash_balance()` each cycle |
| 4 | `src/agent.py` | new | `forced_sells` collected but never executed (dead code) | MEDIUM | Added swap + `close_position()` loop for all forced sells |
| 5 | `src/decision.py` | 69 | `_heartbeat_buy` calls `self.twak.price()` → type error + runtime crash | HIGH | Removed entire method (dead code, no callers) |
| 6 | `src/decision.py` | sell block | `twak.swap()` called even in paper mode → TWAK error every cycle | MEDIUM | Added paper-mode guard (same pattern as buy block) |
| 7 | `src/decision.py` | buy block | `portfolio.add()` called before `tx_hash` known; `sync_position_to_db()` never called | HIGH | Moved `add()` before tx_hash, added `await self.portfolio.sync_position_to_db(token)` after |

## Pyright Error Count

| Metric | Before | After |
|---|---|---|
| `src/agent.py` errors | 1 (line 146 `twak.price()`) | 0 |
| `src/decision.py` errors | 1 (line 69 `_heartbeat_buy`) | 0 |
| Total (these 2 files) | **2** | **0** |

## Dry-Run Test

```
$ python -m src.agent --mode paper --cash 1000 --cycles 2
```

**Result**: 2 cycles completed without crash.

- **Cycle 1**: 5 paper buys (AXS, APE, CAKE, COMP, PENDLE) from Gaming/NFT basket at real CMC prices; positions synced to DB; cash decremented.
- **Cycle 2**: All 5 held correctly (top narrative unchanged, verdict=LONG); cooldown rejections applied; no new buys; no crash.

## Changes Summary

### `src/agent.py`

1. **Imports**: Added `NARRATIVE_BASKETS` from `src.config` and `CASH_CURRENCY`, `RISK_CURRENCY` from `src.decision`.
2. **price_map** (lines ~138-152): Replaced `self.twak.price(f"{sym}/USDT")` loop with `cmc.get_bulk_quotes()` fetching all held + basket + risk symbols.
3. **Cash tracking** (line ~169): Changed `self.decision.run_cycle(self.initial_cash, ...)` to `self.decision.run_cycle(await self.portfolio.get_cash_balance(), ...)`.
4. **Forced sell execution** (new block after forced_sells collection): Calls `twak.swap()` (live) or generates paper tx hash, then `portfolio.close_position()` for each stop-loss / take-profit triggered position.

### `src/decision.py`

1. **Removed `_heartbeat_buy`**: Synchronous method calling non-existent `self.twak.price()`; no callers found.
2. **Sell block paper guard**: Added `if os.getenv("AGENT_MODE") == "paper"` branch around `twak.swap()` in sell loop.
3. **Buy block DB sync**: Moved `self.portfolio.add(token, price, units)` before tx_hash generation; added `await self.portfolio.sync_position_to_db(token)` after tx_hash is assigned.

## Remaining Pyright Errors (Not in Scope)

These errors exist in other files (not in Agent C scope):
- `src/cache.py` line 21: `aiosqlite.Connection.closed` type issue
- `src/log.py` lines 22, 86, 110: same `closed` type issue + return type narrowing
- `src/portfolio.py` lines 85-86: `executescript`/`commit` on `None` db
- `src/quoter.py` lines 95, 182, 195: Web3 `Address` type mismatch
- `scripts/register_agent.py`: various type errors
- `scripts/test_signal.py`: dead import

These are tracked by Agent A (type fortress) and Agent B (DB consul).