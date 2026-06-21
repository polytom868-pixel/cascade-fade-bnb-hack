# Plan: Remaining Fixes Before Demo & Submission

**Date**: 2026-06-20  
**State**: Agent executes first paper trade cycle but has runtime/cash-sync issues  
**Deadline**: June 21 12:00 UTC (≈15h)

---

## 1. Current Audit: What Works ✅

| Component | Status | Evidence |
|---|---|---|
| CMC API fetch | ✅ | `BNB price=585.41` from live API every cycle |
| Signal engine | ✅ | Gaming/NFT selected, conviction 27/75, regime=TRANSITION |
| Decision engine | ✅ | 5 paper buys across basket, $21.60 deployed |
| Paper mode | ✅ | Skips TWAK, logs `0xPAPER_` tx hashes |
| Portfolio DB | ✅ | aiosqlite WAL mode, positions+snapshots tables |
| Risk guards | ✅ | drawdown, floor, exposure all pass |
| Main agent loop | ✅ | asyncio cycle, SIGINT shutdown |
| Logging | ✅ | trade journal writes to DB |

---

## 2. Current Audit: What Is Broken ⚠️ (ordered by severity)

### P0 — CRASH ON CYCLE 2
- **[#B1]** `agent.py` line ~108: `self.twak.price(f"{sym}/USDT")` — `TWAKExecutor` does **not** have a `.price()` method.
  - Trigger: As soon as the agent holds ≥1 position, the next cycle will call this → **crash**.
  - Fix: Build `price_map` from CMC `get_bulk_quotes()` for ALL tokens (held + basket), not just held.

### P0 — CASH NEVER DECREMENTS
- **[#B2]** `agent.py` passes `self.initial_cash` (1000) every cycle.
  - After buying $21.60, next cycle still thinks cash is $1000.
  - Fix: Replace with `await self.portfolio.get_cash_balance()`.

### P0 — PORTFOLIO STATE NOT SYNCED TO DB
- **[#B3]** `decision.py` calls `self.portfolio.add(token, price, units)` — this writes **only** to the in-memory dict.
  - DB has no positions. So health check shows 0 held, and `get_positions()` returns empty.
  - Fix: After every paper/live buy, call `await self.portfolio.sync_position_to_db(symbol)`.

### P1 — SELL LOGIC NOT EXECUTED
- **[#B4]** `agent.py` builds `forced_sells` list but **never** calls real sell logic.
  - It prepends `forced_sells` to the summary dict but no `twak.swap()` or `portfolio.close_position()`.
  - Fix: In `run_cycle`, after collecting forced_sells, iterate and execute close.

### P1 — DECISION.PY SELL LOOP ALWAYS CALLS TWAK
- **[#B5]** Paper mode still attempts `await self.twak.swap()` in sell block — will crash/fail.
  - Fix: Wrap sell swap in `AGENT_MODE == "paper"` check (same pattern as buy).

### P1 — DECISION.PY `_heartbeat_buy` CALLS `self.twak.price()`
- **[#B6]** Same missing method as #B1. This function is currently unreachable but should be fixed or removed.

### P1 — NO MAX-HOLD-HOURS SELL IN AGENT.PY
- **[#B7]** `decision.py` evaluates it for in-memory positions, but `agent.py` never drives the DB reconciliation.
  - Fix: After DB sync, agent should also evaluate DB positions for age > 48h.

### P2 — NO END-TO-END TEST VERIFIED
- **[#B8]** `tests/test_risk.py` passes, but no test covers the agent loop or decision engine with CMC mocked.

### P2 — README OUT OF DATE
- **[#B9]** README references old signal module name, old run command, etc.

---

## 3. Implementation Plan (phased — some parallel)

### Phase 1: Fix the CRASH + CASH BUG + DB SYNC  
*Files*: `src/agent.py`, `src/decision.py`, `src/portfolio.py`  
*Description*: Without this, the agent cannot survive past cycle 1.

- [ ] **Step 1a**: In `agent.py`, replace `self.initial_cash` with `await self.portfolio.get_cash_balance()` before passing to `decision.run_cycle()`.
- [ ] **Step 1b**: In `agent.py`, build `price_map` from CMC `get_bulk_quotes()` using ALL symbols from `ALLOWLIST` (or at least all narrative basket union). Remove `self.twak.price()` entirely.
- [ ] **Step 1c**: In `decision.py`, after every buy success, add `await self.portfolio.sync_position_to_db(token)`.
- [ ] **Step 1d**: In `decision.py`, wrap sell `twak.swap()` call with paper-mode guard.

### Phase 2: Sell execution wiring  
*Files*: `src/agent.py`  
*Description*: Force-sell paths need to actually close positions.

- [ ] **Step 2a**: In `agent.py`, after collecting `forced_sells`, iterate and call:
  ```python
  for sell in forced_sells:
      if self.mode != "paper":
          tx = await self.twak.swap(...)
      else:
          tx = f"0xSELL_PAPER_{...}"
      await self.portfolio.close_position(sell["token"], sell["price"], tx)
  ```

### Phase 3: Heartbeat / demo polish  
*Files*: `src/agent.py`, `src/decision.py`  
*Description*: Serve the demo scenario.

- [ ] **Step 3a**: Wire heartbeat check in `agent.py` (call `risk.check_heartbeat()` and if needed generate a forced buy).
- [ ] **Step 3b**: Fix `_heartbeat_buy` in `decision.py` to receive price from `price_map`.

### Phase 4: Tests + Documentation  
*Files*: `tests/`, `README.md`, `demo_script.md`  
*Description*: Validate, record, submit.

- [ ] **Step 4a**: Write a smoke test that mocks CMC and runs `dry_run(cycles=2)`.
- [ ] **Step 4b**: Update README with correct run command.
- [ ] **Step 4c**: Record demo video per `demo_script.md`.
- [ ] **Step 4d**: Submit DoraHacks form.

---

## 4. Parallel Execution Map

| Chunk | Scope | Files | Can Parallel? |
|---|---|---|---|
| Phase 1 | Crash fix + cash + sync | agent.py, decision.py, portfolio.py | **No** (sequential edits, same files) |
| Phase 2 | Sell wiring | agent.py | **After Phase 1** |
| Phase 3 | Heartbeat / demo | agent.py, decision.py | **After Phase 2** |
| Phase 4 | Tests + docs | tests/, README.md | **Yes, with Phase 2** |

**Parallel-safe right now:**
- Fix README (no source code overlap)
- Record demo video (no code edits)
- Fund the wallet / complete TWAK registration (manual)
- Write mock CMC test (Phase 4a, just new files)
