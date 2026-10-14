# Performance evidence review

Run: `20261014T032504Z-48ab4d`. Web: `f1-micro`, external IP `136.64.82.14`.
Client: `e2-small`, external IP `34.123.133.194`. Instructor binary unchanged;
quiet mode, request timeout 30 seconds, 15-second warmup before each measured
180-second window. Maximum controlled load: four concurrent clients.

| Concurrent clients | Seconds | CPU mean / peak (%) | Memory peak (MiB) | RX peak (Mbps) | TX peak (Mbps) | Client timeouts |
|---|---:|---:|---:|---:|---:|---:|
| 1 | 180.09 | 3.97 / 6.93 | 359.02 | 12.07 | 12.07 | 0 |
| 2 | 180.10 | 4.06 / 10.20 | 363.18 | 11.32 | 11.30 | 0 |
| 3 | 180.10 | 4.60 / 7.92 | 362.90 | 12.71 | 12.69 | 0 |
| 4 | 180.02 | 4.69 / 7.84 | 363.30 | 13.82 | 13.81 | 0 |

All four web resource windows have uninterrupted coverage and synchronized VM
clocks. There were no early client exits, no captured client timeout messages,
and no other client output. Deadline termination exit codes of -15 are intentional.
Expected country denials in the measurement windows were 107, 79, 97, and 90.

## Two-client CHECK: preserve and explain

The automatic summary correctly flagged four HTTP 404 records and a server
exception during the two-client measurement window. These have been reviewed,
not deleted or silently reclassified in `summary.json`.

- At 03:30:19.990, 03:30:27.566, and 03:31:40.697 UTC, requests for `/` returned 404.
- At 03:30:40.302 UTC, a request for `/login` returned 404.
- Those paths are outside the instructor workload, whose configured path is
  `/cs528-hw2-yf-2026/data/<index>.html`. The 404 entries do not include source IPs,
  so they cannot be attributed to a particular caller from this evidence.
- At 03:30:16 UTC, the web journal identifies a connection reset from
  `66.132.159.21:50606`, while reading an HTTP request line. This peer is different
  from the load VM (`34.123.133.194`). It is not evidence that a load-client
  request failed because the server was overloaded.

The public endpoint received additional traffic. The whole-VM measurements
include its effects; the two-client group is not a fully isolated experiment.
Its CPU peak should not be interpreted as a controlled scaling trend.
The four-client measurement window contains only expected country-denial log
records and no captured server exception lines.

## Evidence completeness

Canonical comparison of JSON payloads found 417 structured application events in
the downloaded web journal and the identical 417 payloads in Cloud Logging:
411 forbidden-country events plus 6 missing-path events over the entire capture
period (including warmup and gaps). No local structured payload is missing from
the downloaded Cloud Logging export.

The reporter journal contains 411 unique event IDs, exactly matching the 411
unique forbidden-country IDs in Cloud Logging. No missing or duplicate IDs were
observed in this capture. This does not change Pub/Sub's at-least-once semantics.

## Interpretation and limits

Under the required maximum of four controlled clients, the experiment did not
observe overload-related failures in its three-minute measurement window.
The four-client peaks satisfy the assignment's fallback measurement: CPU busy
7.84%, whole-VM memory 363.30 MiB (64.17% of Linux-visible memory), inbound
13.82 Mbps, and outbound 13.81 Mbps.

Mean outbound traffic grew from 6.55 to 8.48 Mbps between one and four clients,
about 29.35%. This is bandwidth, not requests per second. Quiet mode does not
expose complete HTTP status counts, latency, or request throughput. The data do
not establish the maximum supported concurrency or eliminate all possible
bottlenecks. The serial server waits on GCS and, for country denials, logging
and Pub/Sub; low CPU and sublinear bandwidth growth are consistent with time
spent waiting on I/O, but per-operation latency was not measured here.

CPU excludes idle, iowait, and steal and refers to guest logical CPUs, not the
shared-core CPU entitlement. Memory is MemTotal minus MemAvailable, rather than
Python-process memory alone. Network counters include HTTP, GCS, cloud API, and
background traffic. Peaks are approximately one-second samples. There is one
run per concurrency level, so no statistical uncertainty intervals are claimed.

## Retained sources

- `summary.json`, `web-metrics.csv`, `web-resources.jsonl`
- `client/c1/round.json` through `client/c4/round.json`, all client logs/events
- `cloud-errors.json`, `web-journal.jsonl`, `reporter-journal.jsonl`
- `web-vm.json`, `client-vm.json`, `experiment.json`

Actual billing, final content equality evidence, and final cleanup remain
separate completion items. No monetary amount is inferred from these metrics.
