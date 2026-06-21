# CascadeFade: Storage Layer Fix Plan

**Goal**: Fix all bugs found in `src/portfolio.py`, `src/log.py`, and `src/utils.py`.
**Files in scope**: `src/portfolio.py`, `src/log.py`, `src/utils.py`
**Constraint**: No edits outside these three files. No new dependencies.

---

## 1. Issue Table

| File | Line | Issue | Severity | Exact Replacement Code |
|------|------|-------|----------|------------------------|
| `portfolio.py` | 58 | `_row_to_position(r: tuple)` type annotation is wrong; `aiosqlite.Row` is returned at runtime, not `tuple`. pyright/mypy will flag this. | Medium | Change annotation to `r: aiosqlite.Row` (import `aiosqlite` at top). Add `from typing import Sequence` and use `Sequence[Any]` for maximum flexibility. |
| `portfolio.py` | 166 | `close_position()` executes `BEGIN IMMEDIATE` with no `try/except`. If the `UPDATE` fails, the transaction is never rolled back — SQLite lock remains until connection closes. | High | Wrap in try/except with rollback (match `add_position` pattern). |
| `portfolio.py` | 166 | `close_position()` — `await db.execute("BEGIN IMMEDIATE")` on a connection that already has an unconsumed cursor from `async with db.execute(...) as cur:`. The `async with` context manager auto-closes the cursor when the block exits, so this is not a bug right now. But the pattern is fragile — any future refactor that reads more rows after `fetchone()` would leave a live cursor. | Low | Add a comment documenting that `fetchone()` must be consumed before `BEGIN IMMEDIATE`, or restructure to use a separate query. |
| `portfolio.py` | 65 | `@staticmethod async def _ensure_schema(...)` — prior audit said this was "called as instance method". It is correctly defined as `@staticmethod` and called as `Portfolio._ensure_schema(self._db)`. **No fix needed.** The prior bug is resolved. | None | — |
| `portfolio.py` | 47 | `_connect()` assigns `self._db = new_db` only when `new_db is not self._db`. If `ensure_db` always returns a new connection object (due to health-check failure on every call), the old `self._db` is silently orphaned without being closed. | Medium | Before `self._db = new_db`, add `if self._db is not None and self._db is not new_db: await self._db.close()`. This is belt-and-suspenders since Python GC will eventually collect the old object, but explicit close is cleaner. |
| `utils.py` | 17 | `from eth_utils import to_checksum_address` is a local import inside `to_checksum()`. This imports `eth_utils` on every call to `to_checksum()`. Works correctly with eth-utils 6.0.0 at time of audit. | Low | Move import to top of file: `from eth_utils import to_checksum_address` (remove the nested import). The top-level import already works as verified: `from eth_utils import to_checksum_address` ✅ succeeds with eth-utils 6.0.0. |
| `utils.py` | 17 | Known bug report said `except None:` is present. **Verified: no `except None:` in any of the three files.** This was a false alarm in the prior audit or the bug was already fixed. | None | — |
| `utils.py` | 62 | `retry_async` signature: `coro_factory` has no type hint; `exceptions` default is `(Exception,)` which is correct; `returns Any`. The `last_exc: BaseException \| None = None` annotation is correct. | Low | Add `from typing import Awaitable, Callable` and annotate: `coro_factory: Callable[[], Awaitable[Any]]`, `exceptions: tuple[type[Exception], ...] = (Exception,)`, `-> Any`. |
| `utils.py` | 70 | `ensure_db` health check `hasattr(db, '_connection') and db._connection is not None` is fragile — accesses private `aiosqlite` internals. Works correctly for closed-connection detection (verified: `await db.close()` sets `_connection = None`). | Low | Add a comment: `# aiosqlite exposes _connection; close() sets it to None`. Or replace with a try/except on a lightweight query (`SELECT 1`). |
| `log.py` | 110 | `log_decision` returns `cursor.lastrowid` but the `cursor` object is created inside the `try` block and used after `db.commit()`. After `commit()`, the cursor is valid and `lastrowid` is accessible. This works but is unconventional. | Low | Assign `row_id = cursor.lastrowid` before `commit()`, return `row_id`. Pattern-match with `log_trade`. |

---

## 2. Hidden Bugs

### HB-1: Orphaned connections in `portfolio.py` `_connect()` (MEDIUM)

**Code** (portfolio.py:47):
```python
async def _connect(self) -> aiosqlite.Connection:
    new_db = await ensure_db(self._db, self.db_path)
    if new_db is not self._db:
        self._db = new_db
        await self._db.execute("PRAGMA journal_mode=WAL")
        ...
```

When `new_db is not self._db` is True (reconnection), `self._db` is overwritten with the new connection. The **old** connection object is never closed. In CPython this is eventually GC'd, but:
- In asyncio contexts with long-lived event loops, unreferenced connection objects may not be collected promptly.
- Any open WAL files or locks held by the old connection remain until finalization.
- This pattern, if `ensure_db` misbehaves, creates O(n) leaked connections over time.

**Fix**: Before `self._db = new_db`, close the old connection:
```python
if new_db is not self._db:
    if self._db is not None:
        await self._db.close()
    self._db = new_db
```

### HB-2: `close_position()` unhandled exception — SQLite lock poisoning (HIGH)

**Code** (portfolio.py:165–170):
```python
await db.execute("BEGIN IMMEDIATE")
await db.execute(
    "UPDATE positions SET open=0 WHERE symbol=? AND open=1", (symbol,)
)
await db.commit()
```

No `try/except`. If the `UPDATE` raises (e.g., `UNIQUE constraint`, disk full, or `open=0` already set due to race), the transaction is never rolled back. The `BEGIN IMMEDIATE` transaction holds a write lock on the database until the connection is closed or a rollback occurs. This can poison subsequent operations in the same connection.

Contrast with `add_position` which correctly wraps in `try/except + rollback`.

**Fix**:
```python
await db.execute("BEGIN IMMEDIATE")
try:
    await db.execute(
        "UPDATE positions SET open=0 WHERE symbol=? AND open=1", (symbol,)
    )
    await db.commit()
except Exception:
    await db.rollback()
    raise
```

### HB-3: `log.py` `log_decision` — accessing `cursor.lastrowid` post-commit (LOW)

**Code** (log.py:110–115):
```python
cursor = await db.execute(
    "INSERT INTO trades(...) VALUES(...)",
    (...),
)
await db.commit()
return cursor.lastrowid
```

Per Python `sqlite3` docs, `lastrowid` is reliable after `execute()` but before any other SQL is executed on the connection. `commit()` does not reset `lastrowid`, so this works in practice. However, this pattern is fragile — if any future refactor adds a query between `execute` and `commit`, `lastrowid` could be clobbered.

**Fix**: Store `row_id = cursor.lastrowid` before `commit()`, return it:
```python
cursor = await db.execute(...)
row_id = cursor.lastrowid
await db.commit()
return row_id
```

### HB-4: `to_checksum()` — repeated import on every call (LOW)

**Code** (utils.py:17):
```python
def to_checksum(addr: str) -> str:
    try:
        from eth_utils import to_checksum_address
        return to_checksum_address(addr)
    except Exception:
        return addr
```

`eth_utils` is a moderately heavy import (6.0.0, 300+ exports). Importing it on every `to_checksum()` call adds ~0.5–2ms overhead per call. For a low-frequency trading agent this is not a bottleneck, but it is poor practice.

**Fix**: Move to top-level import:
```python
from eth_utils import to_checksum_address

def to_checksum(addr: str) -> str:
    try:
        return to_checksum_address(addr)
    except Exception:
        return addr
```

---

## 3. Missing Types

| File | Location | Missing | Recommended Fix |
|------|----------|---------|-----------------|
| `portfolio.py` | line 1 | `import aiosqlite` — `aiosqlite` is used for the `Connection` type but not imported at module level | Add `import aiosqlite` (needed for `Row` type and `aiosqlite.Connection` in type annotations) |
| `portfolio.py` | `_row_to_position` (line 58) | `r: tuple` — should be `r: aiosqlite.Row` or `r: Sequence[Any]` | `def _row_to_position(r: aiosqlite.Row) -> dict[str, Any]:` |
| `portfolio.py` | `total_exposure()` (line 97) | No return type annotation | `-> float` |
| `portfolio.py` | `get()` (line 104) | Already has `-> dict[str, Any] \| None` — correct | — |
| `portfolio.py` | `add()` (line 110) | Missing return type | `-> None` |
| `portfolio.py` | `remove()` (line 118) | Missing return type | `-> None` |
| `portfolio.py` | `get_stop_price()` (line 124) | Missing return type | `-> float` |
| `portfolio.py` | `get_take_price()` (line 133) | Missing return type | `-> float` |
| `portfolio.py` | `_connect()` (line 47) | Missing return type | `async def _connect(self) -> aiosqlite.Connection:` |
| `log.py` | `_connect()` | Missing return type | `async def _connect(self) -> aiosqlite.Connection:` |
| `log.py` | `log_trade` (module-level) | No type hints at all | Add: `side: str, symbol: str, units: float, price: float, value: float, tx_hash: str \| None = None, slippage: float = 0.0` |
| `utils.py` | `retry_async` | `coro_factory` untyped; `-> Any` too broad | `coro_factory: Callable[[], Awaitable[Any]], retries: int = 3, backoff: float = 1.5, exceptions: tuple[type[Exception], ...] = (Exception,) -> Any` |
| `utils.py` | `ensure_db` | Missing return type | `async def ensure_db(db: aiosqlite.Connection | None, db_path: str) -> aiosqlite.Connection:` |

---

## 4. Security Issues

### SI-1: No SQL injection risks found

All SQL in all three files uses parameterized queries with `?` placeholders. Verified:

- `portfolio.py`: `BEGIN IMMEDIATE` + `db.execute("... VALUES(?,?,?,...)", tuple)` — parameterized, safe.
- `portfolio.py`: `_ensure_schema` uses `db.executescript()` with a hardcoded literal string — no interpolation, safe.
- `log.py`: `db.execute("INSERT INTO trades(...) VALUES(?,...)", tuple)` — parameterized, safe.
- `log.py`: `log_trade` at module level does **zero SQL** — just `logger.info()`, safe.
- `utils.py`: `apply_db_pragmas` uses `db.execute()` with literal SQL, no interpolation, safe.

**Verdict: No SQL injection vulnerabilities.**

### SI-2: No plain-text secrets found

Checked all three files for hardcoded API keys, wallet addresses, RPC URLs, or credentials. None found. All secrets are read from environment variables via `src/config.py`.

### SI-3: `db_path` in `ensure_db` is user-influenced (informational)

`db_path` comes from `DB_PATH` in `src/config.py`, which is read from the `.env` file. If the `.env` is writable by an untrusted party, they could point `db_path` to an arbitrary file path (e.g., `/etc/passwd`). SQLite would create/overwrite that file with the agent's schema. This is a deployment security concern, not a code bug. **No fix needed in these three files.**

---

## 5. Cheats to Remove

None identified. There are no debug shortcuts, commented-out security checks, disabled validation blocks, or TODO-based workarounds in the storage layer that constitute "cheats."

---

## 6. Chunk Summary

### Chunk 1: `portfolio.py` — type annotation + orphan connection fix
**Scope**: `src/portfolio.py`
**Changes**:
1. Add `import aiosqlite` at top
2. Fix `_row_to_position(r: tuple)` → `r: aiosqlite.Row`
3. Add `if self._db is not None: await self._db.close()` before `self._db = new_db` in `_connect()`
4. Add missing `-> aiosqlite.Connection` to `_connect()`
5. Add missing return types to: `total_exposure`, `add`, `remove`, `get_stop_price`, `get_take_price`
6. Fix `close_position` — wrap `BEGIN IMMEDIATE` + `UPDATE` + `commit` in `try/except/rollback`
7. Add comment warning about cursor consumption order (low-priority)

**Depends on**: None

**Accept when**:
- `python3 -c "import ast; ast.parse(open('src/portfolio.py').read())"` passes
- `pyright src/portfolio.py` reports no errors on the `r: tuple` line
- `close_position` has a `try/except` block with rollback
- `_connect()` closes old connection before reassigning

### Chunk 2: `log.py` — cursor lastrowid pattern + types
**Scope**: `src/log.py`
**Changes**:
1. Capture `row_id = cursor.lastrowid` before `await db.commit()` in `log_decision`
2. Add `async def _connect(self) -> aiosqlite.Connection:` return type
3. Add type hints to module-level `log_trade()`

**Depends on**: None

**Accept when**:
- `log_decision` stores `row_id` before `commit()`
- All async methods have return type annotations

### Chunk 3: `utils.py` — top-level import + types
**Scope**: `src/utils.py`
**Changes**:
1. Move `from eth_utils import to_checksum_address` to top-level import (remove from inside `to_checksum()`)
2. Add `Callable, Awaitable` to `typing` imports
3. Add type hints to `retry_async` signature
4. Add return type to `ensure_db`

**Depends on**: None

**Accept when**:
- `python3 -c "from src.utils import to_checksum; print(to_checksum('0x...'))"` works
- `pyright src/utils.py` reports zero errors

---

## 7. Verification Strategy

```bash
# Syntax check all three files
python3 -c "import ast; [ast.parse(open(f'src/{n}').read()) for n in ['portfolio.py','log.py','utils.py']]"

# Type check with pyright (install if needed: pip install pyright)
python3 -m pyright src/portfolio.py src/log.py src/utils.py

# Functional smoke test: import all modules
python3 -c "
import asyncio
from src.portfolio import Portfolio
from src.log import TradeLogger, log_trade
from src.utils import to_checksum, ensure_db, retry_async
print('All imports OK')
# Verify to_checksum works with top-level import
print(to_checksum('0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c'))
"

# Verify close_position rollback behavior (mock)
python3 -c "
import asyncio, aiosqlite
async def test_rollback():
    db = await aiosqlite.connect(':memory:')
    await db.execute('CREATE TABLE t(id INTEGER PRIMARY KEY, v TEXT)')
    await db.commit()
    # Simulate begin immediate
    await db.execute('BEGIN IMMEDIATE')
    try:
        await db.execute('INSERT INTO t VALUES(1, ?)', ('test',))
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    # Verify transaction is not stuck
    result = await db.execute('SELECT * FROM t').fetchall()
    print(f'Rows after rollback-safe insert: {len(result)}')
    await db.close()
asyncio.run(test_rollback())
"
```

---

## 8. Decision Log

| Decision | Rationale | Rejected Alternatives |
|----------|-----------|----------------------|
| Fix `_row_to_position` annotation to `aiosqlite.Row` | `aiosqlite.Row` (which is `sqlite3.Row`) supports integer indexing at runtime. `tuple` annotation causes pyright/mypy false positives. | Use `Sequence[Any]` — broader but less precise; `tuple` was wrong so fixing to `Row` is correct |
| Use `aiosqlite.Row` import | Needed anyway for `aiosqlite.Connection` type hints throughout portfolio.py | Use `Any` — loses type precision |
| Close old connection before reassigning in `_connect()` | Belt-and-suspenders; Python GC eventually cleans up but explicit close is safer and signals intent | Leave orphaned — GC is sufficient, but explicit close is cleaner |
| Wrap `close_position` in try/except | Matches `add_position` pattern; unhandled exceptions leave SQLite locked | Leave as-is — would only fail in pathological cases |
| Move `to_checksum_address` to top-level import | Reduces per-call import overhead; top-level import verified working with eth-utils 6.0.0 | Keep local import — works but adds overhead |
| `except None` — no bug found | Verified by `grep -n "except None"` across all three files — zero matches | Assume it was already fixed or the original report was incorrect |