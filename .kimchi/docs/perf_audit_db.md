# SQLite Database Layer — Performance Audit

**Files reviewed:** `src/portfolio.py`, `src/cache.py`, `src/log.py`
**Pragmas confirmed in all three:** `journal_mode=WAL`, `synchronous=NORMAL`
**DB path:** shared `DB_PATH` across all modules

---

## 1. Connection Management

### Finding: `SELECT 1` liveness probe is redundant overhead

`ensure_db()` in `utils.py` fires `SELECT 1` on every call to confirm a cached connection is alive:

```python
async def ensure_db(db, db_path):
    if db is not None:
        try:
            await db.execute("SELECT 1")   # <-- round-trip every call
            return db
        except (aiosqlite.Error, ValueError):
            pass
    new_db = await aiosqlite.connect(...)
    return new_db
```

Every `_connect()` call — which fires before every public read and write — incurs a synchronous `SELECT 1` round-trip to the database even when the connection is reused. For reads that dominate the call frequency (CMC polling every 30 min, signal evaluation every 30 min), this adds one unnecessary disk I/O per query.

**Fix:** Remove the `SELECT 1` check. The caller already holds `self._db` as a reference — if it is not `None` and not closed, it is alive. The exception handler only needs to catch the case where the connection was explicitly closed by a prior `await db.close()` or the process. A cleaner liveness probe:

```python
async def ensure_db(db, db_path):
    if db is not None:
        try:
            # Lightweight — just check a closed attribute, no I/O
            if hasattr(db, 'closed') and not db.closed:
                return db
        except Exception:
            pass
    new_db = await aiosqlite.connect(db_path, timeout=60.0)
    return new_db
```

### Finding: Three independent connection instances, no shared connection pool

| Module | Holds `self._db` | PRAGMAs set on connect |
|---|---|---|
| `Portfolio` | Yes | WAL, SYNC, FK |
| `Cache` | Yes | WAL, SYNC, FK, `temp_store=MEMORY`, `cache_size=10000` |
| `TradeLogger` | Yes | WAL, SYNC only |

`agent.py` instantiates three separate `Portfolio`/`Cache`/`TradeLogger` objects. With WAL mode this is technically safe for reads, but it means:
- Three separate WAL writer processes fighting for the same WAL lock.
- `temp_store=MEMORY` and `cache_size` tuning is only applied to `Cache`, leaving `Portfolio` and `TradeLogger` at defaults.

**Fix:** Extract a shared `db.py` helper module (or shared connection mixin) that all three classes import, ensuring all pragmas are applied once at startup and a single `aiosqlite.Connection` is reused.

### Finding: No `busy_timeout` set on any connection

SQLite's default `busy_timeout` is 0 — if a write encounters a lock, it fails immediately with `SQLITE_BUSY`. Under any concurrent load (even two coroutines writing to different tables simultaneously), writes can race. WAL mode serialises writers to one at a time; without `busy_timeout`, the second writer errors instead of waiting.

**Fix:** Add on every new connection:

```sql
PRAGMA busy_timeout = 30000;  -- 30 s; retry window before raising SQLITE_BUSY
```

---

## 2. Transaction Efficiency

### Critical: Portfolio and Cache writes are not wrapped in `BEGIN IMMEDIATE`

`log.py` gets this right:

```python
await db.execute("BEGIN IMMEDIATE")
cursor = await db.execute("INSERT INTO trades ...")
await db.commit()
```

But `portfolio.py` and `cache.py` use bare `execute() + commit()` auto-transaction:

```python
# portfolio.py add_position
await db.execute("INSERT INTO positions ... ON CONFLICT ...")
await db.commit()   # auto-transaction — no exclusive lock acquired upfront

# cache.py set_quote
await db.execute("INSERT INTO cmc_quotes ... ON CONFLICT ...")
await db.commit()
```

Under `BEGIN IMMEDIATE`, SQLite acquires an **exclusive write lock** at transaction start. Under bare `commit()`, SQLite issues an implicit transaction that only locks at commit time — creating a race window where two concurrent writers both begin a transaction and then both try to commit simultaneously, causing `SQLITE_BUSY` for the second writer.

With concurrent coroutines (signal evaluation + position sync + heartbeat + trade logging), this race is likely. Even a 2-writer scenario is enough to trigger contention.

**Fix:** Wrap all write sequences in `BEGIN IMMEDIATE`:

```python
async def add_position(self, ...):
    db = await self._connect()
    await db.execute("BEGIN IMMEDIATE")
    try:
        await db.execute("INSERT INTO positions ...", ...)
        await db.commit()
    except Exception:
        await db.rollback()
        raise
```

Apply the same pattern to every write in `cache.py` (`set_quote`, `set_trending`, `set_fear_greed`) and every write in `portfolio.py` that does not already use `BEGIN IMMEDIATE` (`add_position`, `close_position`, `update_cash`, `compute_value`, `initialize_cash`, `sync_position_to_db`, `remove_position_from_db`).

### Finding: Multiple sequential writes in `compute_value` lack atomicity

```python
# portfolio.py compute_value — two separate commits
async with db.execute("SELECT MAX(total_value) FROM portfolio_snapshots") as cur:
    ...
await db.commit()                        # commit 1: read
...
await db.execute("INSERT INTO portfolio_snapshots ...", ...)
await db.commit()                        # commit 2: write
```

If the process crashes between commit 1 and commit 2, an orphaned SELECT result is persisted. The `peak` value could be stale. The snapshot should be atomic.

**Fix:** Combine into a single transaction:

```python
await db.execute("BEGIN IMMEDIATE")
try:
    async with db.execute("SELECT MAX(total_value) FROM portfolio_snapshots") as cur:
        row = await cur.fetchone()
    peak = ...
    await db.execute("INSERT INTO portfolio_snapshots ...", (ts, total, cash_usd, positions_value, peak))
    await db.commit()
except Exception:
    await db.rollback()
    raise
```

### Finding: `update_cash` reads then writes in separate transactions

```python
# portfolio.py update_cash — non-atomic read-then-write
async with db.execute("SELECT id, total_value, positions_value, peak_value ...") as cur:
    row = await cur.fetchone()
...
await db.execute("UPDATE portfolio_snapshots SET cash_value=... WHERE id=?")
await db.commit()
```

Same race condition as above.

**Fix:** Wrap in `BEGIN IMMEDIATE`.

---

## 3. Schema & Indexing

### Finding: Missing index on `cmc_quotes.ts`

```sql
CREATE TABLE cmc_quotes (
    symbol TEXT PRIMARY KEY,
    data   TEXT NOT NULL,
    ts     TEXT NOT NULL
);
-- No index on ts
```

Query: `SELECT data FROM cmc_quotes WHERE symbol=? AND ts>?`

The PK on `symbol` handles the `symbol=?` filter efficiently (O(log n)). The `ts>?` predicate then filters among matching rows. With ~150 tokens cached, this is not yet a performance problem, but as the cache grows (if TTL expired entries are not purged), the `ts>?` filter requires a full-table scan per symbol lookup.

**Fix:** Add a partial index that only indexes non-expired entries, or a compound index:

```sql
CREATE INDEX IF NOT EXISTS idx_cmc_quotes_symbol_ts ON cmc_quotes(symbol, ts);
```

This covers both equality and inequality predicates with a single index seek.

### Finding: Missing TTL garbage-collection strategy

Expired cache rows (older than 5 minutes) accumulate in `cmc_quotes`, `cmc_trending`, and `cmc_fear_greed`. The application only ever reads non-expired rows via `ts>?`, so expired rows are dead weight that bloat the DB file and slow down `PRAGMA wal_checkpoint` operations.

**Fix:** Run a periodic DELETE on startup and/or as a low-priority background task:

```python
async def _gc_expired(self, db):
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=CACHE_TTL_SECONDS)).isoformat()
    await db.execute("DELETE FROM cmc_quotes WHERE ts < ?", (cutoff,))
    await db.execute("DELETE FROM cmc_trending WHERE ts < ?", (cutoff,))
    await db.execute("DELETE FROM cmc_fear_greed WHERE ts < ?", (cutoff,))
```

---

## 4. Async / Sync Mismatch

### Finding: `log_trade` module-level function blocks the event loop

```python
# log.py — synchronous function
def log_trade(side, symbol, units, price, value, tx_hash=None, slippage=0.0):
    logger.info("TRADE | ...")
```

This is synchronous Python `logger.info` — it does I/O (to stderr/stdout depending on handler config). For a production logging handler (e.g. `RotatingFileHandler` or `SocketHandler`), this can block the asyncio event loop for milliseconds per call.

**Assessment:** Low severity if the logging handler is `StreamHandler` to stderr (non-blocking pipe), but a latent risk if a file handler is added later. No action required now, but document that any future logging to file must use `logging.handlers.QueueHandler` with a dedicated listener thread.

---

## 5. Summary of Optimizations

### Pragma alignment

| Pragma | portfolio.py | cache.py | log.py | Recommended |
|---|---|---|---|---|
| `journal_mode` | WAL | WAL | WAL | WAL (ok) |
| `synchronous` | NORMAL | NORMAL | NORMAL | NORMAL (ok) |
| `foreign_keys` | ON | ON | — | ON (add to log.py) |
| `busy_timeout` | — | — | — | 30000 (add all) |
| `temp_store` | — | MEMORY | — | MEMORY (add all) |
| `cache_size` | — | 10000 | — | 10000 (add all) |
| `wal_autocheckpoint` | — | — | — | 1000 (add all) |

```python
# Unified PRAGMA block for every new connection
PRAGMAS = [
    "PRAGMA journal_mode=WAL",
    "PRAGMA synchronous=NORMAL",
    "PRAGMA foreign_keys=ON",
    "PRAGMA busy_timeout=30000",
    "PRAGMA temp_store=MEMORY",
    "PRAGMA cache_size=10000",
    "PRAGMA wal_autocheckpoint=1000",
]
```

### SQL changes (schema)

```sql
-- Add to cache.py _init_schema()
CREATE INDEX IF NOT EXISTS idx_cmc_quotes_symbol_ts ON cmc_quotes(symbol, ts);
```

### Write transaction pattern (apply everywhere)

```python
async def _write(self, sql: str, params: tuple) -> None:
    db = await self._connect()
    await db.execute("BEGIN IMMEDIATE")
    try:
        await db.execute(sql, params)
        await db.commit()
    except Exception:
        await db.rollback()
        raise
```

### Priority order

| Priority | Change | Impact |
|---|---|---|
| P1 | Add `BEGIN IMMEDIATE` to all Portfolio and Cache writes | Prevents `SQLITE_BUSY` crashes under concurrent load |
| P1 | Add `busy_timeout=30000` pragma | Graceful retry instead of hard failure on lock |
| P2 | Add `idx_cmc_quotes_symbol_ts` index | Eliminates table scan on cache reads |
| P2 | Remove redundant `SELECT 1` in `ensure_db` | Eliminates one I/O round-trip per query |
| P2 | Align PRAGMAs across all three modules | Consistent performance; `temp_store=MEMORY` speeds temp sorts |
| P3 | TTL garbage-collection on startup | Reduces WAL file bloat and checkpoint time |
| P3 | Shared connection instance | Eliminates WAL writer contention from three processes |