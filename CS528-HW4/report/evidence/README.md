# HW4 evidence

These files support the submitted PDF. Measurements and logs came from the actual
Google Cloud deployment and the instructor-provided client. Nothing here requires
the old web endpoint to remain live. All 11 dedicated compute/network resources
were verified absent at 2026-10-14 04:08:16 UTC.

| Path | Origin and interpretation |
|---|---|
| `screenshots/` | Original browser captures showing GET 200, GET 404 and PUT 501. |
| `functional/` | Retrieved Cloud Logging records and reporter stdout, client help and 100-request summary, method/country test output, and byte comparison hashes. |
| `20261014T032504Z-48ab4d/` | Complete retained performance run, including web/client resource samples, all client quiet logs, run windows, VM configurations, Cloud Logging and systemd journals. |
| `deployment-summary.json` | Selected fields from the final pre-deletion VM metadata; `RUNNING` describes capture time, not current state. |
| `installed-web.txt`, `installed-reporter.txt` | Exact installed dependency lists extracted from the final deployment export. |
| `web-startup.txt`, `reporter-startup.txt` | Selected service-state and startup lines from that export. |
| `cleanup-verification.json` | Original verification manifest confirming each of the 11 named resources is absent. |
| `billing/` | Original October 13 billing screenshot and a record of its reporting scope and limitations. |
| `SHA256SUMS` | Checksums of the other evidence files, including this guide. |

The performance directory was copied byte for byte from the downloaded run.
`summary.json`, `summary.txt`, `web-metrics.csv`, and `performance-review.md` are
derived analyses. The raw `*.jsonl`, client logs, run metadata and exported cloud
records remain available alongside them. Empty quiet-client logs are intentional:
the client suppresses successful responses without `-v`; a timeout would be
captured by the PTY. Empty output alone is not treated as a successful load test.

The two-client group retains four unrelated-path 404 records and a connection
reset from an IP different from the load VM. No samples were removed. Expected
forbidden-country HTTP 400 events are reported separately from unexpected errors.
The measured four-client window had no observed client timeout, unexpected HTTP
error log or server exception. Quiet mode does not provide complete response
counts, request throughput or latency; this run does not establish maximum capacity.

The final raw deployment capture remains in the author's local `results/final/`
directory. That larger export includes startup metadata and SSH public-key
metadata; the submission retains only the fields relevant to the report. The
large 100-request verbose log and downloaded HTML bodies also remain local.
The report includes their recorded counts and matching SHA-256 values.

Billing is a point-in-time observation: October 1-13 shows $0.00 net with $0.04
of savings at the October 13, 23:58 Eastern capture. The author confirmed that
the month's activity was HW4 only. The month-end forecast is not an actual cost,
and this screenshot does not establish a final settled bill after delayed usage.
