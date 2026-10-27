# CS528 Homework 5: Cloud SQL Request Logging and Operation Timing

Author: Yide Fang | Boston University

## Overview

This project extends the [HW4](https://github.com/ThomasFYD/CS528-HWs/blob/main/CS528-HW4/README.md) file service with Cloud SQL request logging and operation timing. Two instructor clients send requests to the web service, while the unchanged [HW4](https://github.com/ThomasFYD/CS528-HWs/blob/main/CS528-HW4/README.md) reporter handles forbidden-country events.

## Report

[Read the HW5 report (PDF)](report/CS528_HW5_Report.pdf)

See `report/REPORT_CHECKLIST.md`. The final PDF is `report/CS528_HW5_Report.pdf`;
its visual review is recorded in `report/evidence/report-visual-review.json`.
The updated binary is kept locally, excluded from Git; the code's dependencies
are recorded by the VM at `/opt/cs528-hw5/installed-requirements.txt`.

The project and report use the repository directory **CS528-HW5**, as confirmed
by the author. Source, scripts, reviewed evidence and the final PDF are kept together.

## Project structure

| Path | Purpose |
| --- | --- |
| [README.md](README.md) | Homework overview, reproduction steps, and recorded results. |
| [report/](report/) | Final PDF, reviewed experiment evidence, screenshots, and report sources. |
| [web_server.py](web_server.py), [hw4_service.py](hw4_service.py) | HTTP service and retained [HW4](https://github.com/ThomasFYD/CS528-HWs/blob/main/CS528-HW4/README.md) application behavior. |
| [reporter.py](reporter.py) | Unchanged [HW4](https://github.com/ThomasFYD/CS528-HWs/blob/main/CS528-HW4/README.md) forbidden-country reporter. |
| [database.py](database.py), [setup_schema.py](setup_schema.py), [request_data.py](request_data.py) | Database access, schema setup, and request metadata handling. |
| [analysis.py](analysis.py), [queries.sql](queries.sql) | Experiment analysis and equivalent SQL queries. |
| [config.py](config.py) | Homework resource and application configuration. |
| [setup.sh](setup.sh), [infra.py](infra.py), [startup.sh](startup.sh) | Deployment, resource management, and VM initialization. |
| [cleanup.sh](cleanup.sh), [guard/](guard/) | Cleanup entry point and scheduled SQL shutdown function. |
| [verify_local.sh](verify_local.sh), [tests/](tests/) | Local verification and offline tests. |
| [tools/](tools/) | Client probing, curl demonstrations, experiments, evidence export, and report generation. |
| `client/http-client-mac` | Instructor-provided macOS executable; kept locally and excluded from Git. |

## Resources and requirements

### Authentication and project

Authentication: `gcloud auth login fangyd@bu.edu`. The grader may authenticate
with their authorized identity; all scripts still use the fixed project
`dazzling-seat-508219-j3`, never the grader's current default project.

### CLI prerequisite

Before deployment, install the required local CLI component explicitly:

```bash
gcloud components install beta --quiet
```

The deployment preflight checks installed components using local state only and
stops with this instruction if beta is missing. Cloud commands cannot wait for
hidden terminal input. This component is required for labels on SQL creation.

## Implementation details

### Design and [HW4](https://github.com/ThomasFYD/CS528-HWs/blob/main/CS528-HW4/README.md) continuity

`hw4_service.py` is the original [HW4](https://github.com/ThomasFYD/CS528-HWs/blob/main/CS528-HW4/README.md) first application, retained as an imported
module. `web_server.py` adds a bounded, single-process threaded HTTP server, a
database transaction per request and operation timing. `reporter.py` is byte for
byte identical to [HW4](https://github.com/ThomasFYD/CS528-HWs/blob/main/CS528-HW4/README.md) (SHA-256
`095e77c433957dd45185d4c0fce3efa3a948866308839bdabb9c22dbb93c87b0`).

GET and POST serve original Cloud Storage bytes. Unsupported methods return 501;
missing files return 404; the nine assignment countries return 400 and publish
the original forbidden-country event. A Pub/Sub failure returns 503 without
serving a banned request. Country filtering is a homework simulation based on
the supplied header, not verified geolocation. The existing [HW2](https://github.com/ThomasFYD/CS528-HWs/blob/main/CS528-HW2/README.md) bucket may still
be public, as documented in [HW4](https://github.com/ThomasFYD/CS528-HWs/blob/main/CS528-HW4/README.md); this submission does not change its public ACL.

### Instructor client fields and schema

The supplied updated macOS ARM64 client was successfully observed sending 20
requests to localhost. Its evidence is `report/evidence/client-probe.json`.

| Observed header | Database field | Meaning |
| --- | --- | --- |
| `X-country` | `country` | Original country label |
| `X-client-IP` | `client_ip` | Simulated client IP; actual peer is separately stored |
| `X-gender` | `gender` | Original Male/Female label |
| `X-age` | `age` | Original ranges such as `0-16`, `17-25`, `76+` |
| `X-income` | `income` | Original ranges such as `0-10k`, `100k-150k`, `250k+` |
| `X-time` | `client_time`, `time_of_day` | Original simulated datetime plus extracted `HH:MM:SS` |

The client does not provide an `is_banned` field. The application derives it
from the same [HW4](https://github.com/ThomasFYD/CS528-HWs/blob/main/CS528-HW4/README.md) country policy. Missing metadata remains SQL NULL; it is not
silently converted to a fabricated age, gender, or income. X-time has no supplied
time zone and is not interpreted as UTC. It repeats and must not be a request ID.

Tables in the MySQL 8.4 `hw5` database:

- `requests`: every application-handled request, including failures. UUID
  `request_id` is its primary key. It also contains a unique UTC `request_time`
  (`DATETIME(6)`), the metadata above, method, requested file, peer IP, run ID and
  HTTP status.
- `failed_requests`: exactly `request_time`, `requested_file`, `error_code`.
  `request_time` is both the primary key and a foreign key to the main table.
  The main and failure records commit in one transaction. UTC receipt timestamps
  are serialized across threads, with a one-microsecond tie adjustment. The
  clock is seeded from the database on restart. This design assumes one server
  process; do not add multiple independent server processes without revising it.
- `request_timings`: one row per request ID, linked to `requests`, with integer
  nanosecond measurements and flags for attempted storage reads and completed
  server writes.

SQL is parameterized through SQLAlchemy. The Cloud SQL Python Connector handles
encrypted connections and VM identity authorization. SQL has a public address
but setup adds no public authorized-network range. A dedicated SQL account's
generated password lives in Secret Manager and is never committed to Git. The
web VM receives Cloud SQL Client and access to this one secret. The MySQL user
created by Cloud SQL is a database owner account for this homework; it is not
presented as a fully restricted production DML account.

### Timing definitions

`time.perf_counter_ns()` measures four separate operations:

1. HTTP header parsing, request-body validation and metadata extraction.
2. The Cloud Storage download, including an attempted read that returns 404.
3. Sending/flushing HTTP response headers and body on the server socket.
4. The SQL transaction for request metadata and, when needed, the error row.

The later insert of timing measurements is excluded from its own measurement.
`total_ns` includes the four stages plus policy handling, Cloud Logging, Pub/Sub
and other application work; it is not the sum of four exclusive measurements.
Response timing is server-side socket work, not a network RTT or proof that a
client received every byte. The analysis reports failed socket writes separately.
Storage summaries include both all-request averages (zero when no read was
attempted) and an attempted-read-only average. Mean, nearest-rank p50/p95 and max
are reported with sample counts.

Request records commit before a response is sent. A database write failure
returns 503 and writes explicit journal/Cloud Logging evidence; the program does
not falsely return 200 for an unlogged request. Timing insert failures are also
logged. The experiment is rejected as incomplete if SQL counts do not reconcile.

## Setup and execution

### Local verification

Run this one-line command from the development directory:

```bash
bash verify_local.sh
```

It creates `.venv`, installs the listed Python dependencies, checks shell/Python
syntax, and runs offline tests with a real temporary SQLite database and mocked
cloud services. Tests cover transaction rollback, concurrent requests, original
HTTP behavior, group parsing, guard behavior and cleanup ownership checks. These
checks do not establish Cloud SQL compatibility or cloud deployment success;
those require the live steps below.

### Deployment

Review the resource plan, then deploy when ready:

```bash
bash setup.sh --plan
```

```bash
bash setup.sh
```

The setup uses the existing [HW2](https://github.com/ThomasFYD/CS528-HWs/blob/main/CS528-HW2/README.md) bucket and creates dedicated HW5 resources.
It uses the official `gcloud beta sql instances create` command because SQL
instance creation labels are exposed on the beta command, not the stable one.

| Resource | Configuration |
| --- | --- |
| Web VM | `e2-small`, Debian 12, 10 GB standard disk, up to 8 request workers |
| Reporter VM | `e2-micro`, Debian 12, unchanged reporter code |
| SQL | MySQL 8.4 Enterprise, `db-g1-small`, zonal, 10 GB SSD |
| Networking | Dedicated VPC/subnet, web port 8080, one dynamically allocated static web IP |
| Database guard | Authenticated gen2 function plus hourly Cloud Scheduler job |
| Artifacts | Dedicated deployment bucket and function image repository |

These are initial capacity choices, subject to the 200-request smoke test and
observed full-load results. No claim of measured capacity is made before testing.
Cloud SQL automatic backup/binlog and automatic disk growth are disabled for
this bounded coursework environment. Retain local exports before cleanup.

`setup.sh` has a Cloud SQL function that starts an existing owned instance or
creates a new one, ensures the database/user exist and skips recreating them.
The VM's `startup.sh` calls `setup_schema.py`, which creates only missing tables
and rejects an incompatible existing column layout. Existing data is retained.
Source is uploaded as an explicit small archive and checked by SHA-256 on the VM.
No client binary, local credential, raw result or report is embedded in it.

All internal VM configuration is performed by the submitted `startup.sh`, passed
via `--metadata-from-file=startup-script=...`. The script runs as root, installs
dependencies once, enables systemd services and restarts them on subsequent boots.
It never uses SSH commands to configure a VM. A source mismatch on an existing
VM stops setup and directs the user to the explicit update operation below.
This stops and starts each owned VM, updates its startup metadata and source
hash, and waits for a completion marker unique to that restart. Existing VM
disks, SQL instance/data, secrets and static IP are retained. Dependency changes
are applied by `startup.sh`; unchanged package-installation steps are skipped.
The SQL guard is paused during the update and restored on success or a handled
failure. After an abrupt termination, use `python3 infra.py resume-guard`.

```bash
python3 infra.py refresh-vms
```

The update saves `report/evidence/web-startup-after-refresh.log` and
`report/evidence/reporter-startup-after-refresh.log`. Startup success still needs
the real HTTP/database checks below. Do not run an update during an experiment.

VM creation completing does not imply application readiness. Inspect status and
startup output before sending test traffic:

```bash
python3 infra.py status
```

```bash
gcloud compute instances get-serial-port-output cs528-hw5-web --zone=us-central1-a --project=dazzling-seat-508219-j3
```

```bash
gcloud compute instances get-serial-port-output cs528-hw5-reporter --zone=us-central1-a --project=dazzling-seat-508219-j3
```

Look for completed startup and both services running. Resolve errors before
proceeding. `report/evidence/deployment-status.json` preserves the actual resources.

### Curl demonstration and experiment

Do the curl demonstration **before** the load run, while the tables remain small:

```bash
.venv/bin/python tools/curl_demo.py
```

It uses actual `curl` for one 200, one 404 and one banned-country 400 request,
prints full request/error table contents before and after each, and saves response
headers, response bodies, commands and all six snapshots. Capture terminal
screenshots of each before/request/after sequence for the required PDF. The script
refuses to flood the terminal if more than 200 old request rows already exist;
do not delete prior evidence just to bypass this check.

Use the updated instructor binary at `client/http-client-mac`, not an older
semester client. The runner checks its SHA-256 against the successfully probed
binary before launching it. First execute two clients with **100 requests each**:

```bash
caffeinate -i .venv/bin/python tools/run_experiment.py --requests 100
```

Review the 200-request summary and both client exit codes. After that passes,
run the assignment's two clients with **50,000 requests each**:

```bash
caffeinate -i .venv/bin/python tools/run_experiment.py --requests 50000
```

Both processes are launched before waiting on either; both use seed `528`. The
maximum file index is `11999` for [HW2](https://github.com/ThomasFYD/CS528-HWs/blob/main/CS528-HW2/README.md)'s 12,000 files indexed 0–11999. The runner
defaults to a six-hour safety timeout. Keep the Mac connected to power/network;
`caffeinate` inhibits idle sleep while the command runs. Closing the laptop or
forcibly terminating the runner can still interrupt it.

The client `-w` parameter includes a unique `/__runs/<id>/data` path. The server
records the run ID, strips this routing prefix, and serves the same [HW2](https://github.com/ThomasFYD/CS528-HWs/blob/main/CS528-HW2/README.md) objects.
This separates the experiment from curl tests, smoke tests and unrelated scans.
All actual command arguments, binary SHA-256, timestamps and exit codes are saved.

The runner pauses the hourly database guard while the clients run, then re-enables
it on normal completion or a handled exception/interrupt. If the process is killed
forcibly, or gcloud authentication expires before the final resume call, run:

```bash
python3 infra.py resume-guard
```

The hourly function checks `activationPolicy`, since a stopped SQL instance may
still report state RUNNABLE. It requests `NEVER` only for a running instance; it
does not delete the instance or grant the function general project administration.

Outputs:

- `report/evidence/<run>/experiment.json`: execution record and guard state.
- `report/evidence/<run>/summary.json`: all six requested statistical answers,
  timing distributions and integrity checks.
- `report/evidence/<run>/client-{1,2}.log`: actual client stdout/stderr.
- `results/<run>/database-snapshot.json.gz`: full SQL export, excluded from Git.

The accepted full run must contain exactly 100,000 request and timing rows, with
one matching failure row for every non-200 response, no missing metadata, and no
failed server socket writes. Expected banned-country 400s are counted as HTTP
failures, not as overload. The metadata-multiplicity check is diagnostic only. Both command lines specify
the same seed, but the formal run contains 100,000 distinct metadata tuples;
it is not described as two identical request sequences.

`queries.sql` provides the equivalent SQL queries. Tied most-frequent age or
income groups are all reported. Statistics include successful and failed requests
and retain the client's original group definitions.

## Results and evidence

61 offline tests passed, curl 200/404/400 passed, and the formal
100,000-request run `load-20261021T075735Z-5b3f60c2` passed. Both clients used seed
528 and exited 0. The raw snapshot was independently checked: 95,653 HTTP 200,
4,347 expected banned-country HTTP 400, 100,000 timing rows, no missing metadata
and no recorded response-send failures. Load duration was 3 h 1 m 6.021 s.
The guard was resumed by the runner. See `report/EXPERIMENT_RESULTS.md` and
`report/evidence/formal-run-review.json` for verified results and timing boundaries.

Cloud audit evidence now confirms scheduled SQL shutdown and a successful retry
after one platform HTTP 500. SQL and both VMs were verified stopped. Pub/Sub
metrics show 4,347 sends, 4,343 acknowledgments and latest backlog 0; the four-count
difference is retained without asserting a cause or exact per-message completion.
See `report/CLOUD_EVIDENCE.md`. Teardown is complete: SQL is retained and
STOPPED/NEVER, the VMs and static address are absent, and the scheduler is removed.
All nine curl replay screenshots and the accepted October 20-22 billing snapshot
are included in `report/CS528_HW5_Report.pdf`. All 18 PDF pages passed visual review.
The screenshot displays $0.00 at capture time; it is not a final settled bill.
The reviewed submission uses directory **CS528-HW5**.

Cleanup also targets the exact function source object generation in the
Google-managed bucket, without deleting the shared bucket. All 61 offline tests,
including the four cleanup regression tests, passed in the final local check.
Post-load collection and teardown are complete; reproduction commands below
describe a new experiment, not additional work required for the completed run.
Metric activity does not establish individual reporter stdout contents.

## Cleanup

After exporting evidence, temporarily stop the SQL and VMs while preserving the
guard and deployment for later work:

```bash
python3 infra.py finish
```

For full teardown, inspect then execute:

```bash
bash cleanup.sh --plan
```

```bash
bash cleanup.sh
```

Cleanup stops **but never deletes** Cloud SQL. It removes the owned VMs and boot
disks, releases the static IP, removes dedicated networking and Pub/Sub resources,
and deletes the guard/scheduler and dedicated deployment artifacts. The SQL data,
password secret and nonbillable IAM identities are retained for recreation. It
does not delete or alter other homeworks. The guard is recreated/enabled by the
next setup. No application-default login is used or ADC state changed, so no ADC
revocation is needed.

Stopping SQL removes running-instance charges but does **not** eliminate stored
data charges. Record actual GCP billing for HW5 development/execution rather than
reporting an estimated or preexisting [HW4](https://github.com/ThomasFYD/CS528-HWs/blob/main/CS528-HW4/README.md) amount. Billing may arrive later; the
assignment permits its separate billing PDF the next day. Save a dated screenshot
and state its reporting interval and any delayed charges. Never claim a zero
total merely because the billing console has not updated.

## References

- [Google Cloud SQL Python connector example](https://docs.cloud.google.com/sql/docs/mysql/samples/cloud-sql-mysql-sqlalchemy-connect-connector)
- [MySQL instance creation](https://docs.cloud.google.com/sql/docs/mysql/create-instance)
- [Starting and stopping Cloud SQL](https://docs.cloud.google.com/sql/docs/mysql/start-stop-restart-instance)
- [Authenticated Cloud Scheduler HTTP targets](https://docs.cloud.google.com/scheduler/docs/http-target-auth)
- [Cloud Functions deployment options](https://docs.cloud.google.com/sdk/gcloud/reference/functions/deploy)
