# I/O benchmark — NVMe vs external USB3 SSD (2026-07-23)

fio, on this machine. NVMe: O_DIRECT (true device numbers). External (exFAT): O_DIRECT
unsupported → buffered, so its **seq + random-WRITE numbers are page-cache-inflated and
unreliable**. The **random-READ** number is the honest cross-comparison.

| Test | NVMe (local ext4) | External USB3 (exFAT) | NVMe advantage |
|---|---|---|---|
| Seq write (1M) | 3355 MB/s | 714 MB/s* | ~4.7× |
| Seq read (1M) | 2488 MB/s | 1067 MB/s* | ~2.3× |
| **Rand read 4K** | **1086 MB/s (265k IOPS)** | **16 MB/s (3.9k IOPS)** | **~67×** |
| Rand write 4K | 2256 MB/s (551k IOPS) | 590 MB/s* (cached) | — (not comparable) |

\* buffered — includes OS cache, overstates true external speed.

## Verdict
- **Random I/O is the killer:** the external is ~67× slower on 4K random reads (16 MB/s). That
  is exactly the pattern of Parquet scans, DuckDB queries, and millions-of-small-files PDF work.
- **Decision confirmed (was already the plan): working data on NVMe, external = sequential
  archive/backup only.** Never run the query/processing layer off the external.
- Sequential streaming to the external (bulk PDF archive, backups) is fine — even buffered it
  sustains hundreds of MB/s, well above the 1 Gbps (~125 MB/s) internet feed that gates downloads.
- exFAT kept (Windows-readable backup, per user) — but its lack of O_DIRECT + poor random I/O is
  another reason not to host hot data there.
