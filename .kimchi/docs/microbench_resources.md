# CascadeFade Agent — System-Level Resource Profiling Report

**Profile Date:** 2026-06-21
**Agent Mode:** paper (live paper trading with real market data)
**Agent Command:** `python3 -m src.agent --mode paper --cash 1000 --interval 5 --cycles 0`
**Monitored PID:** 1677761
**Profile Duration:** 90 seconds (18 samples × 5s interval)

---

## 1. Resource Consumption Over Time

| Time (s) | CPU% | RSS (MB) | VMS (MB) | Disk Read (MB) | Disk Write (MB) | Net Sent (MB) | Net Recv (MB) | Vol CS | Invol CS |
|----------|------|----------|----------|----------------|-----------------|---------------|---------------|--------|----------|
| 0        | 0.0  | 70.8     | 226.2    | 0.00           | 0.00            | 0.3           | 0.0           | 2274   | 57       |
| 5        | 0.0  | 70.8     | 226.2    | 0.00           | 0.00            | 0.7           | 0.2           | 2274   | 57       |
| 10       | 0.0  | 70.8     | 226.2    | 0.00           | 0.00            | 1.6           | 0.3           | 2274   | 57       |
| 15       | 0.0  | 70.8     | 226.2    | 0.00           | 0.00            | 2.3           | 0.7           | 2274   | 57       |
| 20       | 0.0  | 70.8     | 226.2    | 0.00           | 0.00            | 3.0           | 1.0           | 2274   | 57       |
| 25       | 0.0  | 70.8     | 226.2    | 0.00           | 0.00            | 3.1           | 1.2           | 2274   | 57       |
| 30       | 0.0  | 70.8     | 226.2    | 0.00           | 0.00            | 3.1           | 1.5           | 2274   | 57       |
| 35       | 0.0  | 70.8     | 226.2    | 0.00           | 0.00            | 3.6           | 1.6           | 2274   | 57       |
| 40       | 0.0  | 70.8     | 226.2    | 0.00           | 0.00            | 8.0           | 1.8           | 2274   | 57       |
| 45       | 0.0  | 70.8     | 226.2    | 0.00           | 0.00            | 10.1          | 2.1           | 2333   | 57       |
| 50       | 0.0  | 70.8     | 226.2    | 0.00           | 0.00            | 10.3          | 2.4           | 2333   | 57       |
| 55       | 0.0  | 70.8     | 226.2    | 0.00           | 0.00            | 10.7          | 2.7           | 2333   | 57       |
| 60       | 0.0  | 70.8     | 226.2    | 0.00           | 0.00            | 11.0          | 3.0           | 2335   | 57       |
| 65       | 0.0  | 70.8     | 226.2    | 0.00           | 0.00            | 11.1          | 3.6           | 2335   | 57       |
| 70       | 0.0  | 70.8     | 226.2    | 0.00           | 0.00            | 11.5          | 4.0           | 2335   | 57       |
| 75       | 0.0  | 70.8     | 226.2    | 0.00           | 0.00            | 12.2          | 4.2           | 2335   | 57       |
| 80       | 0.0  | 70.8     | 226.2    | 0.00           | 0.00            | 12.6          | 4.6           | 2335   | 57       |
| 85       | 0.0  | 70.8     | 226.2    | 0.00           | 0.00            | 12.9          | 4.7           | 2335   | 57       |

---

## 2. Summary Statistics

| Metric                        | Value          |
|-------------------------------|----------------|
| **CPU**                       |                |
| Mean CPU%                     | 0.00%          |
| Peak CPU%                     | 0.0%           |
| Min CPU%                      | 0.0%           |
| **Memory**                    |                |
| Peak RSS (MB)                 | 70.8           |
| Mean RSS (MB)                 | 70.8           |
| Final RSS (MB)                | 70.8           |
| VMS (virtual memory size)     | 226.2 MB       |
| RSS % of VMS                  | 31.3%          |
| **Disk I/O**                  |                |
| Total Read (MB)               | 0.00           |
| Total Write (MB)              | 0.01           |
| Bytes per cycle (write)       | ~0.5 KB        |
| **Network I/O**               |                |
| Total Sent (MB)               | 12.95          |
| Total Received (MB)           | 4.70           |
| Send Rate (KB/s)              | 147.5          |
| Receive Rate (KB/s)           | 53.5           |
| Sent/Received Ratio           | 2.76:1         |
| **Context Switches**          |                |
| Voluntary CTX Switches        | 61             |
| Involuntary CTX Switches      | 0              |
| CTX Switch Rate               | 0.68/sec       |
| **Syscalls (from /proc)**     |                |
| read syscalls (syscr)         | 6,806 total    |
| write syscalls (syscw)        | 425 total      |
| Read syscall rate             | 75.6/sec       |
| Write syscall rate            | 4.7/sec        |

---

## 3. Process State Snapshot

```
Name:    python3
State:   S (sleeping)
VmSize:  231,596 KB (226.2 MB)
VmRSS:   72,516 KB (70.8 MB)
voluntary_ctxt_switches:  2,335
nonvoluntary_ctxt_switches: 57
```

### Open File Descriptors

| FD  | Type   | Target                                               |
|-----|--------|------------------------------------------------------|
| 0   | ro     | /dev/null                                           |
| 1   | rw     | logs/paper_run_live.log                             |
| 2   | rw     | logs/paper_run_live.log                             |
| 3   | socket | 172.18.219.164:48504 → 166.117.36.137:443 (HTTPS)  |
| 4   | eventpoll | anon_inode                                       |
| 5   | socket | (internal event loop)                              |
| 6   | socket | (internal event loop)                              |
| 8   | rw     | logs/cascade_fade.db                                |
| 9   | rw     | logs/cascade_fade.db-wal                            |
| 10  | rw     | logs/cascade_fade.db-shm                            |

**Active Connection:** The socket to `166.117.36.137:443` is a Binance API endpoint (HTTPS).

---

## 4. Bottleneck Analysis

### Classification: **I/O-BOUND (Network-Heavy)**

The agent is **NOT CPU-bound**. With 0.00% mean CPU usage, the process spends >99% of its time sleeping, waiting for:

1. **Network I/O (primary bottleneck)**
   - 12.95 MB sent, 4.70 MB received over 90 seconds
   - Continuous polling of Binance API every ~5 seconds
   - Send rate (147.5 KB/s) is 2.76x receive rate
   - High read syscall count (75.6/sec) indicates constant network polling

2. **Memory Usage (minimal concern)**
   - Stable 70.8 MB RSS — no memory leaks detected
   - RSS is only 31% of virtual memory — low pressure

3. **Disk I/O (negligible)**
   - 0.01 MB writes over 90 seconds (SQLite WAL + logging)
   - No disk reads (database cached in memory or read at startup)

4. **Context Switching (healthy)**
   - Only 61 voluntary CTX switches in 90s (0.68/sec)
   - Zero involuntary CTX switches (no preemption)
   - Process is not competing for CPU

### Root Cause
The agent's `paper` mode is **network-bound** due to:
- Continuous Binance API polling (every 5 seconds per `--interval 5`)
- Receiving and processing market data
- Maintaining a persistent HTTPS connection

---

## 5. Resource Reduction Recommendations

| Recommendation                              | Impact                     | Effort  |
|---------------------------------------------|----------------------------|---------|
| **1. Increase polling interval**            | Reduce network I/O by 50%+ | Low     |
| Change `--interval 5` to `--interval 15`    | CPU remains same, net ↓    | Config  |
| **2. Enable HTTP keep-alive caching**       | Reduce connection overhead | Medium  |
| Reuse Binance connections across cycles     | Net sent ↓ 20-30%          | Code    |
| **3. Batch price fetches**                  | Reduce API calls           | Medium  |
| Fetch all prices in single request          | Net ↓ 40%, CPU ↑ minimal   | Code    |
| **4. Use Binance WebSocket streams**        | Replace polling with push  | High    |
| Subscribe once, receive updates             | Net ↓ 90%, CPU ≈ same      | Code    |
| **5. Reduce logging verbosity**             | Minor disk I/O reduction   | Low     |
| Lower log level for routine cycles          | Disk writes ↓ 50%          | Config  |
| **6. SQLite synchronous=OFF**               | Reduce db write latency    | Low     |
| Change WAL mode to async                    | CPU slightly ↓              | Config  |

### Prioritized Action Items

1. **Immediate (config change):** Increase `--interval` from 5s to 15-30s for paper mode
2. **Short-term (code):** Implement request batching for price fetches
3. **Long-term (architecture):** Migrate to WebSocket for real-time market data

---

## 6. Observations

- **Stability:** Memory is rock-solid at 70.8 MB — no growth, no leaks
- **Efficiency:** Process uses minimal CPU; resources are dominated by network wait
- **Network Profile:** Predominantly outbound (76% sent, 24% received) — mostly JSON payloads to Binance
- **No disk contention:** Reads=0 indicates good caching; writes are minimal WAL flushes
- **Context switching is healthy:** No CPU preemption, low voluntary switches

---

*Report generated by: profile_resources.py*
*Profile session: 2026-06-21 02:15-02:17 UTC*