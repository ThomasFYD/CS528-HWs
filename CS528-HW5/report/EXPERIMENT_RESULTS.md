# CS528 HW5 — Verified experimental results

Author: Yide Fang. This is the measured-results section prepared for the final report. Deployment screenshots, shutdown evidence and billing are tracked separately; this file is not the complete submission PDF.

## Experiment and provenance

- Run ID: `load-20261021T075735Z-5b3f60c2`.
- Two instructor clients were launched before either was awaited. Each command specifies `-n 50000 -r 528 -i 11999 -t 30`; the complete command lines are identical and saved in `experiment.json`.
- Updated macOS client SHA-256: `10cb8c9f0fe29811c5201a25ba512e528d6e789ff576a94fd849d697ccb3a12a`.
- Project: `dazzling-seat-508219-j3`; region/zone: `us-central1 / us-central1-a`.
- Web: `e2-small`; Reporter: `e2-micro`; Cloud SQL: MySQL 8.4 Enterprise, `db-g1-small`, 10 GB SSD.
- Load start (UTC): 2026-10-21T07:57:43.556263+00:00.
- Load finish (UTC): 2026-10-21T10:58:49.526978+00:00.
- Elapsed load time: **10,866.021 seconds = 3 hours, 1 minute, 6.021 seconds**.
- Aggregate observed throughput: **9.203 requests/second** across both clients.
- Client exit codes: **0 and 0**. The runner recorded the hourly SQL guard as resumed.
- Compressed raw snapshot: `results/load-20261021T075735Z-5b3f60c2/database-snapshot.json.gz` (10,514,300 bytes).
- Snapshot SHA-256: `acfcd6cfb1d3fed0d05483197f138d6cefa74ca34f05bd35c4e6e5aa897877bc`.

All numbers below were independently recalculated from the raw snapshot and checked against the original summary. Only this run ID is included; the curl demo, smoke run and unrelated public requests are excluded. The local password-access fix and runner diagnostics were used for this run; server-side request handling was unchanged from the verified VM deployment.

## Six statistical answers

1. **Successful and unsuccessful requests:** 95,653 HTTP 200 (95.653%) and 4,347 non-200 (4.347%). Every non-200 was HTTP 400.
2. **Banned-country requests:** 4,347. Every one was rejected with HTTP 400; these are expected policy results, not unexpected server errors.
3. **Gender:** Female 50,081; Male 49,919. Neither field was missing in this run.
4. **Top five countries:**

| Rank | Country | Requests |
|---|---|---:|
| 1 | Micronesia | 579 |
| 2 | Somalia | 572 |
| 3 | Philippines | 566 |
| 4 | Togo | 566 |
| 5 | South Korea | 563 |

Philippines and Togo tie at 566 and are displayed alphabetically. Mexico is next with 562, so there is no tie at the fifth-place cutoff.

5. **Most frequent age group:** 36–45, with 12,638 requests (12.638%).
6. **Most frequent income group:** 20k–40k, with 12,784 requests (12.784%).

The age and income values are the instructor client's original category labels; no numeric ages or incomes were inferred. Neither modal category has a tie in this formal run.

## Operation timing

All time columns below are milliseconds. Each operation is measured in its own function with `time.perf_counter_ns()` and stored as integer nanoseconds. Percentiles use the nearest-rank definition.

| Operation | Samples | Mean (ms) | p50 (ms) | p95 (ms) | Maximum (ms) |
|---|---:|---:|---:|---:|---:|
| Header parsing and metadata extraction | 100,000 | 0.335557 | 0.323775 | 0.419734 | 3.079330 |
| GCS read, all requests (includes skipped-read zeros) | 100,000 | 48.967563 | 37.029859 | 103.702136 | 4821.151238 |
| Server response send/flush | 100,000 | 39.487487 | 66.870686 | 72.105763 | 2134.559141 |
| SQL metadata/error transaction | 100,000 | 7.335611 | 7.135867 | 9.073666 | 247.941632 |
| Total measured server work | 100,000 | 102.369571 | 106.444684 | 174.890668 | 4828.324650 |
| GCS read, attempted reads only | 95,653 | 51.192920 | 37.859784 | 104.974253 | 4821.151238 |

The four required average timings are therefore **0.335557 ms** for extraction, **48.967563 ms** for GCS access averaged over all requests, **39.487487 ms** for response sending, and **7.335611 ms** for database insertion. If the GCS denominator is restricted to actual attempted reads, its average is **51.192920 ms** over 95,653 reads. The 4,347 banned requests skip the GCS operation and contribute zero to the all-request GCS average.

The SQL measurement includes the transaction inserting request metadata and the error row when applicable. The later timing-row insert is excluded from its own measurement. Response timing covers server-side write/flush work; it is not a round-trip latency or proof of every byte being received by the client. Total time also includes policy handling, Cloud Logging, Pub/Sub and other application work, so it need not equal the sum of the four operation columns. Experiment wall-clock time is measured separately and includes client/network pacing.

## Data-integrity evidence

| Check | Observed result |
|---|---|
| Expected / observed requests | 100,000 / 100,000 |
| Unique request IDs / receipt timestamps | 100,000 / 100,000 |
| Error rows | 4,347; each matches exactly one non-200 request |
| Timing rows | 100,000; exactly one per request ID |
| Recorded server response-send failures | 0 |
| Requests with missing required metadata | 0 |
| Both clients completed normally | Exit codes [0, 0] |
| Independently recomputed timing matches saved summary | Yes |

Both commands use the same seed argument, but all 100,000 complete metadata tuples in the saved run are distinct (`odd_metadata_multiplicities=100000`). This is retained as an observation. It is not used as evidence of missing records, nor is the experiment described as producing two identical request sequences. The underlying client behavior has not been attributed to a particular cause.

## Complete category counts

| Age group | Requests |
|---|---:|
| 0-16 | 12,437 |
| 17-25 | 12,432 |
| 26-35 | 12,472 |
| 36-45 | 12,638 |
| 46-55 | 12,496 |
| 56-65 | 12,608 |
| 66-75 | 12,428 |
| 76+ | 12,489 |

| Income group | Requests |
|---|---:|
| 0-10k | 12,210 |
| 10k-20k | 12,440 |
| 20k-40k | 12,784 |
| 40k-60k | 12,357 |
| 60k-100k | 12,380 |
| 100k-150k | 12,554 |
| 150k-250k | 12,693 |
| 250k+ | 12,582 |

## Report evidence status

The genuine curl request/response and before/after SQL JSON are saved under `report/evidence/demo-8131a0d413fb4069/`. All nine user-captured screenshots of local replay are included in the final PDF with explicit replay captions. Post-load audit logs confirm scheduled shutdown and subscription activity; see `CLOUD_EVIDENCE.md` for the four-count acknowledgment metric discrepancy and its limits. `cleanup-verification.json` confirms SQL STOPPED/NEVER, absent VMs, released static address and absent scheduler. SQL data and the password secret are retained.

The accepted October 20-22 billing screenshot displays $0.00 at capture time; its owner-confirmed activity scope and delayed-billing limits are recorded. The final 18-page `CS528_HW5_Report.pdf` passed visual inspection on every page. The author confirmed `CS528-HW5` as the final directory.
