# CS528 Homework 8: Network Load Balancing and Failover

Author: Yide Fang | Boston University

## Implementation

Two copies of the HW4 Python file service run in `us-central1-a` and
`us-central1-c`, behind a regional external passthrough Network Load Balancer.
Each VM belongs to its own unmanaged instance group. A third small VM runs the
HW4 Pub/Sub reporter. HW8 uses a separate VPC, subnet, topic, subscription,
health check, backend service, forwarding rule and IP address.

`web_server.py` preserves HW4 file responses, country filtering, Cloud Logging,
and Pub/Sub notifications. It adds `X-Server-Zone` to response headers, using the
actual Compute Engine instance metadata at startup. `/healthz` checks the running
HTTP application without downloading files. Threaded HTTP handling prevents a
slow file download from blocking health probes. The service binds to `0.0.0.0:8080`.

The HTTP health check uses port 8080, path `/healthz`, a 2-second interval,
1-second timeout, and healthy/unhealthy thresholds of 2. Both backends are active
normally. Session affinity is `NONE`; TCP backend selection uses the connection
5-tuple. Each client request opens a fresh connection. This is not round-robin,
and a measured split need not be exactly 50:50. Connection persistence on unhealthy
backends is `NEVER_PERSIST`. The web systemd unit has `Restart=no` so SIGKILL really
leaves it down until the explicit restart. The reporter can restart automatically.

## Files

- `web_server.py`, `reporter.py`: server and subscriber applications.
- `client.py`: request-compatible Python client with zone, status and timing output.
- `startup.py`: embeds source and dependencies into VM startup scripts.
- `manage.py`: resource setup, inspection, and ownership-checked cleanup.
- `experiment.py`: bounded live experiment with one request launched per second.
- `tests/`: offline service, client, deployment and deletion checks.
- `results/`: generated raw evidence; excluded from Git.
- `report/`: final report and selected evidence, populated after live verification.

## Prerequisites

Python 3.9+, Google Cloud CLI, and an authenticated account authorized to create
Compute Engine and Pub/Sub resources, attach the HW4 service identities, and use
IAP SSH. Default project: `dazzling-seat-508219-j3`; account: `fangyd@bu.edu`.
The HW2 object `gs://cs528-hw2-yf-2026/data/0.html` and other indices 0-11999 must exist.

This builds on a completed HW4. By default it reuses `cs528-hw4-web-sa` (Storage
object read on `data/` and Cloud Logging writer) and `cs528-hw4-reporter-sa`.
For another project, pass `--project`, `--account`, `--bucket`, `--web-sa` and
`--reporter-sa` to the scripts and first configure the equivalent HW4 permissions.
`manage.py create` grants publisher/subscriber permissions on HW8's own topic
and subscription. VM attached identities supply credentials; no key files are copied.

SSH is limited to IAP's `35.235.240.0/20` source range. HTTP port 8080 is publicly
reachable, including Google's health probes. The VMs have ephemeral external IPs
for package installation and Google API access. The load balancer reserves one
regional external IP. Service accounts and the HW2 bucket are retained at cleanup.

## Run

From this directory:

```bash
python3 -m unittest discover -s tests -v
python3 manage.py create --dry-run
python3 manage.py create
python3 manage.py status
```

VM creation can finish before startup installation. Wait for both backends to be
`HEALTHY` and verify actual file responses before the measurement run.

```bash
python3 client.py -d LOAD_BALANCER_IP -p 8080 -b /cs528-hw2-yf-2026 \
  -w data -n 60 -i 11999 -r 528 --interval 1 --output results/manual.jsonl
python3 experiment.py --trials 3
```

The client supports the instructor's domain, port, bucket, webdir, request count,
maximum file index, seed and timeout conventions. `none` omits the bucket or webdir.
GET requests use `/BUCKET/data/INDEX.html`; `--country` sets `X-country`, and repeated
`--header 'Name: Value'` arguments support other headers. `--method POST` sends the
HW4 filename JSON payload. `--replay capture.json` cycles through a list of captured
request objects (`method`, `path`, `headers`, `body`, optional `expected_status`),
preserving application headers and regenerating Host/Content-Length/Connection.
The default timing workload uses allowed-country GETs to existing files so expected
400 country denials cannot be mistaken for failover errors. It does not claim to
reproduce the instructor executable's private random distribution or seed stream.

Each request records UTC and monotonic times, elapsed time, status, zone, source
port, bytes, body SHA-256, and transport exceptions. Records finish asynchronously
when a timeout overlaps a later scheduled request; analyze by sequence/start time.
Requests never retry silently. The timeout is 2 seconds for the experiment, with
bounded concurrency. The output file must not already exist.

## Measurement protocol

The experiment first checks both backend health states and measures a 60-second
baseline. For each of three trials it kills web A's process with SIGKILL, waits for
UNHEALTHY plus 15 successful survivor responses, observes a further 15 seconds,
restarts A, waits for HEALTHY plus responses from both zones, and records a further
45 seconds. Each transition has a 55-second deadline. If convergence is not
observed, request generation stops and the failed service is restored; debug with
`curl --max-time 2 -i http://LOAD_BALANCER_IP:8080/healthz` before rerunning.

Remote action records bracket SIGKILL/restart using the VM's synchronized UTC clock;
client measurements use the Mac's UTC clock. NTP state and command send/receive
times are retained to check gross clock disagreement. The health poll records its
own send/receive times and complete API result. Client observations at 1 Hz and
API polling are sampled observations, not exact internal load balancer timestamps.
The first success from the surviving VM alone does not prove failed-backend removal.
Raw evidence distinguishes client errors, subsequent sustained successful routing,
API health changes, application readiness and return of traffic to the recovered VM.

After preserving evidence:

```bash
python3 manage.py delete --dry-run
python3 manage.py delete
```

Deletion checks ownership markers and expected boot disks, then verifies dedicated
resources and disks are absent. It does not delete HW2 data or the HW4 identities.

## References

- HW8 assignment, items 1-6 and submission requirements.
- Lecture 18, *Virtual Private Cloud and Load Balancers*, slides 2-6 (purpose and
  network LB flow), 17 (backend-service option), 18 (bind the listener to all IPs).
- [Google Cloud: set up a backend-service-based regional external passthrough NLB](https://docs.cloud.google.com/load-balancing/docs/network/setting-up-network-backend-service).
- [Google Cloud: traffic distribution and connection tracking](https://docs.cloud.google.com/load-balancing/docs/network/ext-netlb-traffic-distribution).
- [Google Cloud: querying instance metadata](https://docs.cloud.google.com/compute/docs/metadata/querying-metadata).

## Verified results and report

[Read the six-page report](report/CS528_HW8_Report.pdf). It follows the plain
black-and-white report format used for HW6 and HW7.

Run `20261114T032031Z` recorded 464 requests at a median launch interval of
1.00002 seconds. There were 432 complete HTTP 200 file responses and 32
connection-refused errors during deliberate failures.

| Trial | Client-observed failover | First recovered-backend response | Connection errors |
| --- | ---: | ---: | ---: |
| 1 | 25.31 s | 20.72 s | 14 |
| 2 | 23.41 s | 36.47 s | 9 |
| 3 | 27.22 s | 26.60 s | 9 |

Failover is measured from confirmed process termination to completion of the first
request in the final sustained survivor-only sequence after the last failed probe.
Recovery is measured from restart initiation to completion of the first HTTP 200
from the restarted zone. These are sampled observations, not exact internal LB
detection times. The separately recorded health API observations are in the report.

The 196 stable both-healthy requests all succeeded: 100 from `us-central1-a`
(51.02%) and 96 from `us-central1-c` (48.98%). All 45 single-backend steady-phase
requests came from C. Across the complete run, including deliberate outages, the
successful response counts were A=109 and C=323.

All 40 local tests and 32 live HTTP checks passed. Both server responses matched
the GCS source bytes; denial events reached the reporter and Cloud Logging.
The submitted web startup hash matches both measured VM labels. Cleanup verified
all 18 dedicated resource/disk entries absent. The recorded IP is historical.

Retained evidence is indexed in [report/evidence/README.md](report/evidence/README.md).
To check the archived run without deploying anything:

```bash
python3 check_submission.py report/evidence/20261114T032031Z
```

To rebuild the figure and PDF, install the optional report dependencies into a
virtual environment and run:

```bash
python3 -m pip install -r requirements-report.txt
python3 build_plot.py
python3 build_report.py
```
