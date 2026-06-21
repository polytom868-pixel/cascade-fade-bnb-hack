# CascadeFade System Throughput Report

**Date:** 2026-06-21  
**Method:** Manual `/proc/[pid]/` sampling + prior automated reports  
**PID:** 1677761 (live paper agent, interval=5 min)

---

## 1. Process-Level Throughput

| Metric | Value | Per Cycle |
|---|---|---|
| Completed cycles | 40 | — |
| Log lines | 276 | 7 lines/cycle |
| **CPU state** | **S (sleeping)** | — |
| **CPU%** | **~0%** (99%+ idle) | — |
| **VmRSS** | **70.6 MB** | 1.76 MB/cycle |
| **VmSize** | 226 MB | — |
| Threads | 3 | — |
| Open FDs | 11 | — |
| Voluntary context switches | 2,421 | 60/cycle |
| Involuntary context switches | 1,155 | 29/cycle |

## 2. Disk I/O Throughput

| Metric | Total | Per Cycle | Per Minute |
|---|---|---|---|
| Disk read bytes | 434 KB | 10.9 KB | 2.2 KB |
| Disk write bytes | 688 KB | 17.2 KB | 3.4 KB |
| Read syscalls | 6,814 | 170 | 34 |
| Write syscalls | 433 | 11 | 2 |

> Verdict: **I/O-bound, not disk-bound.** Most reads are log writes. SQLite WAL amortizes small writes.

## 3. Database Size

| File | Size | Ratio to Main |
|---|---|---|
| `cascade_fade.db` (main) | 40 KB | 1.0× |
| `cascade_fade.db-wal` | 382 KB | **9.6×** |
| `cascade_fade.db-shm` | 32 KB | 0.8× |
| **Total** | **454 KB** | — |

> WAL is 10× main DB. Frequent small commits accumulate. Run `PRAGMA wal_checkpoint(TRUNCATE)` to reclaim.

## 4. API Throughput (from prior report)

| Metric | Value |
|---|---|
| CMC bulk calls | 40 (one per cycle) |
| Symbols per call | 54 |
| Latency per call | 1,195 ms |
| Payload per call | 33.8 KB raw |
| **Calls per minute** | **0.2** |
| **Bytes received/min** | **11.3 KB** |

## 5. Event Loop Throughput (from prior report)

| Metric | Per Cycle |
|---|---|
| Epoll wakeups | 168 |
| `call_soon` schedules | 98 |
| `call_at` / `call_later` | 13 |
| `create_task()` calls | **5** |
| Duplicate callbacks | 29 (**25.9%** waste) |
| CMC fetch wakeups | 62 |
| DB write wakeups | 42 |
| Tasks per wakeup | 0.030 (very low) |

## 6. Copy Overhead (from prior report)

| Allocation | Per Cycle | Source |
|---|---|---|
| `json.decoder` | +7,320 B | CMC response parsing |
| `aiohttp` buffers | +2,984 B | Session internal |
| `signal.py` objects | +3,272 B | Dict + list builds, **0 frees** |
| `portfolio.py` | +1,297 B | Position tracking |
| `decision.py` | +720 B | Action dicts |
| **Total net/cycle** | **~12 KB** | — |
| **Total allocated/cycle** | **~22 KB** (before GC) | — |

> At 48 cycles/day, leak grows to **576 KB/day**. Running for 7 days = **4 MB leak**.

## 7. Efficiency Summary

| Dimension | Verdict |
|---|---|
| **CPU efficiency** | ✅ Excellent (0% CPU, pure I/O wait) |
| **Memory efficiency** | ⚠️ Fair (70 MB base, 12 KB leak/cycle) |
| **Disk efficiency** | ✅ Good (17 KB write/cycle) |
| **Network efficiency** | ⚠️ Fair (33.8 KB payload, no gzip) |
| **Event loop efficiency** | ⚠️ Fair (168 epoll wakes, 26% duplicate callbacks) |
| **API efficiency** | ✅ Good (one batch call per cycle) |
| **Copy efficiency** | ⚠️ Poor (JSON rebuilds, dict reconstructions, zero frees) |

## 8. Top 5 Resource Waste

| Rank | Waste | Impact | Culprit |
|---|---|---|---|
| 1 | **Callback duplication** | 25.9% of schedules are redundant | asyncio internals + aiohttp |
| 2 | **signal.py dict/list rebuild** | +3,272 B/cycle, zero frees | `global_scan()` + `score_*()` |
| 3 | **JSON deserialization** | +7,320 B/cycle, stdlib parser | `cmc_client.py:resp.json()` |
| 4 | **WAL bloat** | 382 KB WAL vs 40 KB main | No checkpointing |
| 5 | **Epoll wakeups** | 168 per cycle, mostly empty | aiohttp session churn |

## 9. Recommendations

1. **Reduce callback duplication** — consolidate aiohttp tasks into fewer schedules
2. **Fix signal.py memory leak** — pre-build static structures, free or reuse dicts
3. **Switch to orjson** — 3.5× faster, less memory churn
4. **Checkpoint WAL** — `PRAGMA wal_checkpoint(TRUNCATE)` on startup/hourly
5. **Add gzip** — saves 83% bandwidth once CMC enables it (or verify header)
