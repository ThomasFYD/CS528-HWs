# HW8 retained evidence

`20261114T032031Z/` is the single completed three-trial measurement run.
All timestamps in raw evidence are UTC; the run began November 13, 2026 at
22:20:41 EST. There are 464 requests, 432 successful file responses, and
32 connection-refused failures during the deliberate outages.

| File | Meaning |
| --- | --- |
| `requests.jsonl` | Every client request, sequence, phase, clocks, status, zone, body bytes/hash, source port when connected, and errors. |
| `events.jsonl` | Remote kill/restart times, process state, NTP synchronization, readiness, and local command brackets. |
| `health.jsonl` | Complete backend health API responses with query send/receive timestamps. |
| `deployment.json` | Actual VM, health-check, backend, forwarding and address configuration; unrelated SSH public-key metadata omitted. |
| `config.json` | Client/controller parameters; output path identifies the original local run directory. |
| `summary.json` | Timing definitions, phase counts and calculated outcomes. |
| `verification.json`, `run-status.json`, `COMPLETE` | Evidence checks and successful controller completion. |
| `../functional/` | 32 HTTP checks, GCS source hash, matching web/reporter events, Cloud Logging entries and installed dependency versions. |
| `../final-health.json` | Both backends healthy after the experiment, before cleanup. |
| `../cs528-hw8-*-final-journal.txt` | Service lifecycle and reporter logs; may contain unrelated public HTTP probes, which are excluded from client measurement counts. |
| `../cleanup.json` | All 18 dedicated resource/disk lookups returned absent after deletion. |

`SHA256SUMS` covers all files in this evidence directory except itself. No service
account private keys or access tokens are included. SHA-256 values detect changed
evidence; they do not independently prove cloud execution. The live resource and
application records provide that context.

From the HW8 directory:

```bash
python3 check_submission.py report/evidence/20261114T032031Z
```

This recalculates the summary from raw records, checks counts and timing, and
checks that the submitted web startup script matches the measured VM source hash.
The report's distribution denominator is successful, complete HTTP 200 responses
with recognized zones; transport failures are reported separately. Normal
both-healthy phases exclude deliberate outage and transition windows.
