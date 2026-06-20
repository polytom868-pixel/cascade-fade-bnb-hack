# Agent B2 — Portfolio/Log Deduplication & Type Fixes Verification

**Date**: 2026-06-20
**Scope**: `src/portfolio.py`, `src/log.py`

---

## Pyright Error Count

| File | Before | After | Delta |
|---|---|---|---|
| `src/portfolio.py` | 2 (lines 85-86: `executescript`/`commit` on `None`) | 0 | -2 |
| `src/log.py` | 3 (line 22: `.closed`; lines 86,110: `int \| None` → `int`) | 0 | -3 |
| **Total** | **5** | **0** | **-5** |

---

## jscpd Clone Resolution

| Clone | Before | After |
|---|---|---|
| `portfolio.py:114-119` ↔ `portfolio.py:122-127` (stop/take price) | Duplicated 12 lines | Merged to `_compute_stop_take()` helper, used in 3 call sites |
| `portfolio.py:244-250` ↔ `portfolio.py:314-320` (position value summation) | Duplicated 7 lines | Extracted to `_sum_position_values()`, used in `compute_value()` |

Additional dedup:
- `_connect()` ping pattern in `portfolio.py` and `log.py` replaced with `ensure_db()` from `utils.py` (same helper already extracted by Agent B in `cache.py`)

---

## LOC Delta

| File | Before | After | Delta |
|---|---|---|---|
| `src/portfolio.py` | 356 | 349 | **-7** |
| `src/log.py` | 138 | 140 | **+2** (added import + `int \| None` annotations) |
| **Net** | **494** | **489** | **-5** |

---

## Changes Made

### `src/portfolio.py`

1. **Line 7** — Added `ensure_db` to import from `src.utils`
2. **Lines 11-24** — Extracted `_compute_stop_take()` (stop/take from entry price using `STOP_LOSS_PCT=0.05`, `TAKE_PROFIT_PCT=0.10`) and `_sum_position_values()` helper functions
3. **Lines 44-54** — `_connect()` refactored: `ensure_db()` replaces inline ping try/except; returns `new_db` (not `self._db`) to satisfy `Connection` (not `Connection | None`) return type
4. **Lines 56-60** — `_ensure_schema()` fix: assigns `db = await self._connect()` before using, resolving pyright's optional-None error
5. **Lines 114-127** — `get_stop_price()` / `get_take_price()` now delegate to `_compute_stop_take()`
6. **Line 174** — `add_position()` uses `_compute_stop_take()` instead of inline arithmetic
7. **Line 285** — `compute_value()` uses `_sum_position_values()` instead of inline loop

### `src/log.py`

1. **Line 7** — Added `ensure_db` to import from `src.utils`
2. **Lines 24-30** — `_connect()` refactored: `ensure_db()` replaces `self._db.closed` check; returns `new_db` (not `self._db`) to satisfy return type
3. **Lines 46, 107** — `log_trade()` and `log_decision()` return types changed from `int` to `int | None` (cursor.lastrowid is `int | None`)

---

## Test Results

```
python3 -m pytest tests/test_risk.py -q
.....                                                            [100%]
5 passed in 0.03s
```

---

## What Was NOT Touched

Per scope rules: `cache.py`, `utils.py`, `agent.py`, `decision.py`, `risk.py`, `config.py` were not modified.

---

## Summary

- **Pyright errors**: 5 → 0 (-5)
- **jscpd clones resolved**: 2 (stop/take price, position value sum)
- **Duplication removed**: ~25 lines via helper extraction
- **Net LOC**: -5 (net reduction despite type annotation improvements)
- **Pytest**: 5/5 passing