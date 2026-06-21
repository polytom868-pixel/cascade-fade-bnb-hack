# Handoff: CascadeFade BSC Trading Agent

> Date: 2026-06-21 ~11:15 UTC  
> Last commit: `f2189a6` + runtime patches (`0e2b89d`, `19026c1`)  
> Agent PID: `2307054` (alive but crippled by signal bug)  

---

## Session Goal
Build, audit, profile, and fix CascadeFade: an autonomous spot-only BSC trading agent for BNB Hack Track 1 (June 22–28 trading window).

---

## ✅ What Was Done (this session)

### Architecture & Code
- 18 Python source files + tests + scripts + docs built from scratch
- AI trading loop with CMC client, signal engine, TWAK executor, QuoterV2, risk manager, SQLite journal
- ALLOWLIST restricted to official 55 competition tokens (53 + BNB/WBNB)
- ~30 subagents executed across optimization waves, speed agents, fix agents, plan agents, and verification agents
- 15+ commits pushed to `main` (`ed55493` → `19026c1`)

### API & Wallet
- CMC API verified: BNB $589.22, batch fetch working
- TWAK wallet: `0x0012CCc0835099e3f3006297Acf88b634a28be89`
- `twak compete status`: NOT registered; deadline June 25 2026
- BSC wallet: `0x3EE70657C1331bd5C53D360EA6e7BB560D4D3d18`
- Wallet backup stored at `~/cascade-fade-wallet-backup/` (mnemonic + password — **outside repo**)
- Secrets in `.kimchi/secrets/` (never committed)

### Performance Optimizations (all committed)
1. Persistent aiohttp session + DNS resolver
2. Pre-computed signal weights (eliminated 10 duplicate calls/cycle)
3. Parallel DB gather + rate-limited logging
4. SQLite WAL mode + periodic checkpoint
5. Bulk CMC fetch + spend data deduplication

### Bugs Fixed (this session)
1. Nested `BEGIN IMMEDIATE` in `sync_position_to_db` → removed outer wrapper
2. `aiohttp.AsyncResolver` requires `aiodns` → graceful fallback (commit `0e2b89d`)
3. `asyncio.create_subprocess_exec` rejects `text=True` → manual decode (commit `19026c1`)
4. 21 bugs across 12 files from PLAN_FIX_* documents (commit `f2189a6`)
5. `Row` type mismatch, orphaned DB connections, `to_checksum` import path, lastrowid before commit, timeout in `.call()`, password subprocess leak, per-position stop-loss logic, circuit breaker DB query, WAL fully checkpointed

### Tests & Profiling
- 5 risk tests pass ✅
- pyright: 0 errors across `src/`, `tests/`, `scripts/`
- Cumulative profiling reports in `.kimchi/docs/`:
  - `microbench_resources.md`
  - `microbench_eventloop.md`
  - `microbench_throughput.md`
  - `microbench_agent_loop.md`
  - `microbench_zero_copy_signals.md`

### Documentation
- README polished (contract addresses, badges, badges, tables)
- POLICY.md, ARCHITECTURE.md, SUBMISSION.md all present
- `demo_script.md` created for terminal demo recording

---

## 🚨 CRITICAL BLOCKING BUGS

### 1. Signal Engine Crashes Every Cycle
- **Symptom**: `AttributeError: 'CMCClient' object has no attribute 'get_trending_symbols'`
- **File**: `src/signal.py`, `_fetch_narrative_data()` line 344
- **Impact**: Agent alive but makes ZERO buy/sell decisions. Just holds stale positions forever.
- **Root cause**: A fix agent INVENTED `_fetch_narrative_data()` (it never existed in git). It calls a fictional method name and returns per-token data structure, but `global_scan` expects per-narrative data structure.
- **Historical context**: The FIRST commit that created `signal.py` (`892f252`) had `await self._fetch_narrative_data()` in `evaluate()` but had **no definition**. The original running process likely used stale `.pyc` bytecode or ran a different code path entirely. Restarting the process loaded the current source, exposing the missing method.
- **Fix needed**: Correct method name (`get_dex_trending`), then align data structure with what `global_scan`/`compute_narrative_score` expect, OR remove `_fetch_narrative_data` entirely and rewrite `evaluate()` to a simpler form.

### 2. Paper Run State Preservation
- DB preserves held positions across restarts. Current holds: `['APE', 'CAKE', 'COMP', 'PENDLE', 'INJ', 'FET', 'FIL']`
- Because signal crashes, no sells happen. These 7 positions will rot until bug is fixed.
- `portfolio.py` has `_ensure_schema` fix; DB integrity verified as OK +WAL checkpointed ✅

---

## 📋 WHAT REMAINS (outside codebase fixes)

| Item | Deadline | Status |
|---|---|---|
| Fix signal engine (`get_trending_symbols` → real CMC method + data structure) | ASAP | 🚨 CRITICAL |
| Fund wallet ~$6 BNB (mainnet) | before June 22 | BLOCKED |
| `twak compete register` | before June 22 | BLOCKED |
| Live BSC swap test | before June 22 | BLOCKED |
| Record demo video | June 21 | Not started |
| DoraHacks Track 1 submission | June 21 ~12:00 UTC | CRITICAL |
| 2-hour paper run evidence | before submit | 40 cycles yes, 0 trades after restart |

---

## 🗂️ Key Files & Artifacts

### Source (all must parse: `python3 -c "import ast; ast.parse(open('src/FILE.py').read())"`)
- `src/agent.py` — main asyncio loop
- `src/signal.py` — **BROKEN** (see blocking bug #1)
- `src/cmc_client.py` — CMC bulk quotes, trending, fear greed
- `src/decision.py` — signal + portfolio + risk merge
- `src/portfolio.py` — holdings and cash tracking
- `src/quoter.py` — QuoterV2 slippage estimation
- `src/twak.py` — TWAK CLI subprocess wrapper
- `src/position.py` — Position dataclass
- `src/cache.py` — SQLite data cache
- `src/signal.py` — remove or rewrite `_fetch_narrative_data()`

### Plans & Bug Reports
- `.kimchi/docs/PLAN_FIX_ARCHITECTURE.md` — 8 issues (broken sell path, stale units, etc.)
- `.kimchi/docs/PLAN_FIX_SIGNAL.md` — 29 issues (missing method, semicolons, inverted logic, etc.)
- `.kimchi/docs/PLAN_FIX_STORAGE.md` — 6 issues
- `.kimchi/docs/PLAN_FIX_EXECUTION.md` — 16 issues
- `.kimchi/docs/PERF_AUDIT_SYNTHESIS.md`
- `.kimchi/docs/MASTER_AUDIT_REPORT.md`

### Demo & Submission
- `README.md` — 70 lines, badges, all contract addresses
- `SUBMISSION.md` — ready but may need refresh
- `AGENTS.md` — custom agent rules
- `POLICY.md` — trading policy doc
- `run.sh` — convenience startup script
- `.kimchi/docs/demo_script.md` — terminal demo script

---

## 🔐 Security Notes (redacted in this doc)

- API keys, wallet password, mnemonic → `.kimchi/secrets/` only
- `CMC_API_KEY`, `TWAK_WALLET_PASSWORD` needed in env for agent run
- Wallet backup at `~/cascade-fade-wallet-backup/` — outside repo
- Never committed; `.gitignore` includes secrets

---

## 🧠 Context for Next Agent

1. **Signal bug is urgent**: The agent is technically "running" but completely ineffective because every cycle crashes in signal evaluation. Caught exception allows agent loop to continue, producing NO trades.
2. **Git is clean** (`main...origin/main` clean). Safe to commit fixes.
3. **DB is healthy**: Integrity check passes, WAL checkpointed, no lock errors.
4. **If fixing signal**: Read latest CMC client (`get_dex_trending()` real method signature) and match `global_scan` expectations for `narrative_data` keys. See `grep 'data.get(' src/signal.py` for full list of fields.
5. **If registering**: Wallet needs ~$6 BNB on mainnet. `pipenv run python -m src.agent --mode live` after registration.
6. **If demo/submit**: Terminal demo is sufficient. No frontend needed.

### 🛠️ Suggested Skills for Next Session
- `samber/cc-skills-golang@golang-troubleshooting` — Systematic debug methodology to trace signal crash chain
- `samber/cc-skills-golang@golang-testing` — Table-driven tests for the fixed signal path
- `samber/cc-skills-golang@golang-debugging` — Instrument `_fetch_narrative_data` step-by-step
- `samber/cc-skills-golang@golang-observability` — Structured logging for real trade confirmation
- `samber/cc-skills-golang@golang-safety` — Defensive guard against similar `AttributeError` regressions

---

## 🔔 Last Agent Status
- **PID**: 2307054
- **Log**: `logs/paper_run_live.log`
- **Alive**: Yes, every 5 min cycle, 0 trades since restart
- **Held**: APE, CAKE, COMP, PENDLE, INJ, FET, FIL
- **Submission clock**: ~8h remain before deadline
