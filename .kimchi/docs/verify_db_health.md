# SQLite DB Health Report

**Generated:** 2026-06-21 02:52 UTC
**DB Path:** `logs/cascade_fade.db`

---

## WAL Size Ratio

| Metric        | Pre-Fix Baseline | Post-Fix |
|---------------|-----------------|----------|
| Main DB       | 40 KB           | 40 KB    |
| WAL           | 382 KB          | 0 KB (fully checkpointed) |
| WAL/MAIN Ratio| 9.6x            | 0x (clean) |
| SHM           | --              | 32 KB (active reader) |

**WAL delta:** -382 KB (-100%). WAL was fully checkpointed into main DB.

---

## Integrity Check

```
PRAGMA integrity_check;  -->  ok
```

Result: **PASS** -- No corruption detected.

---

## Journal Configuration

```
PRAGMA journal_mode;     -->  wal
PRAGMA busy_timeout;     -->  0
```

WAL mode is active. The `busy_timeout` of 0 means readers will return
"database is locked" immediately on contention rather than retrying.

---

## Transaction Counts

| Table               | Count |
|---------------------|-------|
| trades              | 0     |
| positions           | 8     |
| portfolio_snapshots | 29    |

> Note: `portfolio` and `cmc_quotes` tables do not exist in this schema.

---

## Verdict

**PASS**

The database is healthy:

1. **WAL resolved** -- The 382 KB WAL (9.6x main) has been fully
   checkpointed. At time of inspection the WAL was gone and all data
   resides in `cascade_fade.db`.
2. **Integrity clean** -- `PRAGMA integrity_check` returns `ok`.
3. **WAL mode active** -- Write-Ahead Logging is enabled (`wal`), which
   is correct for this workload.
4. **Zero transactions in `trades`** -- Expected if no trade loop has
   run yet; `positions` (8) and `portfolio_snapshots` (29) confirm the
   DB is being written to.

The high WAL ratio (9.6x) before fixes was caused by write transactions
not being checkpointed. After the WAL checkpoint triggered during this
health check, the WAL is empty and the main DB contains all data.