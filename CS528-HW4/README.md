# CS528 Homework 4

Python file service and forbidden-country reporter on Google Compute Engine.
Author: Yide Fang.

## Verified results

The [submission report](report/CS528_HW4_Report.pdf) contains implementation and
reproduction steps, browser screenshots, Cloud Logging evidence, billing and
cleanup records, and five performance figure pages. Its supporting files are
documented in the [evidence guide](report/evidence/README.md).

53 local tests pass using simulated Google Cloud dependencies and HTTP request
bytes. Initial live deployment confirmed that both services start automatically,
GET and POST return 200, and missing-file, PUT, and Iran requests return 404, 501,
and 400 respectively. The corresponding WARNING, ERROR, and CRITICAL cloud logs
were retrieved, and the Iran event ID matches the reporter's stdout.

The instructor client's first launch failed on Debian 12 with `GLIBC_2.38 not
found`. It now runs on Ubuntu 24.04 LTS (glibc 2.39). A live 100-request run
completed with 97 HTTP 200 responses and 3 expected forbidden-country HTTP 400
responses. All seven unsupported methods returned 501; all nine forbidden
countries returned 400 and the United States returned 200. Browser screenshots
retain GET 200, GET 404, and PUT 501 evidence. A five-request quiet probe exited
with code 0 and no output. GET, POST, and the GCS source object were subsequently
compared byte for byte: all three contain 97,586 bytes with SHA-256
`c3be7cacaad7e54bac9e5050419002b0545418e31094933b4239813e2a6f2b88`.

Run `20261014T032504Z-48ab4d` measured all four concurrency levels for at least
180 seconds each with complete web resource coverage and no client timeouts.
At four clients the peaks were CPU busy 7.84%, whole-VM memory 363.30 MiB,
RX 13.82 Mbps, and TX 13.81 Mbps. The two-client group includes additional
traffic: four 404s for paths outside the configured workload, plus a connection
reset from an IP other than the load VM. These records are retained and discussed
in the performance review, not attributed to overload.

The billing snapshot captured on October 13 at 23:58 Eastern shows a net cost of
$0.00 for October 1-13, including $0.04 of savings. The user confirmed that this
month's activity was HW4 only. The screenshot's month-end forecast is excluded.
This is the amount displayed at capture time, before cleanup; delayed usage
charges and the final total must not be inferred from this snapshot.

Final evidence export completed before deletion. At **2026-10-14 04:08:16 UTC**
(00:08:16 Eastern), verification confirmed that all 11 HW4 compute/network
resources were absent: three VMs, three boot disks, one static IP, two firewall
rules, one subnet and one VPC. The old web endpoint is no longer live. The HW2
bucket, runtime service accounts and Pub/Sub setup remain for recreation.

## Files

- `web_server.py`: Python `HTTPServer` with one request worker and an explicit
  connection queue size of 5. Downloads objects from the existing HW2 bucket.
- `reporter.py`: Pub/Sub pull subscriber using the VM's attached service account.
- `startup.py`: embeds the submitted code and configuration into Linux startup
  scripts and installs systemd services that start at creation and reboot.
- `manage.py`: builds startup scripts, creates three VMs, shows their status, or
  deletes the VMs and their dedicated networking resources.
- `requirements.txt`, `requirements-reporter.txt`: VM Python dependencies.
- `tests/`: offline behavior and lifecycle safety checks; standard library only.
- `scripts/`: bounded performance sweep, Linux resource sampler, evidence
  export and analysis. Deployment, measurement and evidence collection use the
  standard library; optional PDF tools use `requirements-report.txt`.
- `report/`: final PDF and reviewed evidence retained in Git.
- `client/http-client`: instructor-provided Linux x86-64 executable, supplied
  separately. The executable is excluded from Git by default.
- `build/`: generated startup scripts; excluded from Git and regenerated from
  submitted source.
- `results/`: local raw captures, including full VM metadata and verbose response
  bodies; excluded from Git. Selected submission evidence is copied to `report/`.

## Resources and configuration

Run these settings in the Mac terminal used for deployment. These identifiers
are not passwords. A TA can replace them with identifiers from their own project.

```bash
export HW4_PROJECT="dazzling-seat-508219-j3"
export HW4_ACCOUNT="fangyd@bu.edu"
export HW4_BUCKET="cs528-hw2-yf-2026"
export HW4_REGION="us-central1"
export HW4_ZONE="us-central1-a"
export HW4_WEB_SA="cs528-hw4-web-sa@${HW4_PROJECT}.iam.gserviceaccount.com"
export HW4_REPORTER_SA="cs528-hw4-reporter-sa@${HW4_PROJECT}.iam.gserviceaccount.com"
export HW4_TOPIC="cs528-hw4-forbidden"
export HW4_SUB="cs528-hw4-forbidden-sub"
```

The chosen account must be authenticated with gcloud and authorized to create
Compute Engine networking, addresses, disks, and VMs. This project's human account
is Owner. The application service accounts are separate and do not receive Editor.

The following setup has already been run in this project. In a new project,
enable the APIs, create the accounts/topic/subscription, and add the bindings.
An existing topic or account does not need another `create` command; inspect it
with `describe` and verify its configuration before proceeding.

```bash
gcloud services enable compute.googleapis.com storage.googleapis.com \
  pubsub.googleapis.com logging.googleapis.com monitoring.googleapis.com \
  iam.googleapis.com --project="$HW4_PROJECT" --account="$HW4_ACCOUNT"

gcloud iam service-accounts create cs528-hw4-web-sa \
  --display-name="CS528 HW4 Web Server" \
  --project="$HW4_PROJECT" --account="$HW4_ACCOUNT"
gcloud iam service-accounts create cs528-hw4-reporter-sa \
  --display-name="CS528 HW4 Forbidden Country Reporter" \
  --project="$HW4_PROJECT" --account="$HW4_ACCOUNT"
gcloud pubsub topics create "$HW4_TOPIC" \
  --project="$HW4_PROJECT" --account="$HW4_ACCOUNT"
gcloud pubsub subscriptions create "$HW4_SUB" --topic="$HW4_TOPIC" --ack-deadline=60 \
  --project="$HW4_PROJECT" --account="$HW4_ACCOUNT"

HW4_DATA_CONDITION="resource.name.startsWith('projects/_/buckets/${HW4_BUCKET}/objects/data/')"
gcloud storage buckets add-iam-policy-binding "gs://${HW4_BUCKET}" \
  --member="serviceAccount:${HW4_WEB_SA}" --role=roles/storage.objectViewer \
  --condition="title=hw4-data-read,expression=${HW4_DATA_CONDITION}" \
  --project="$HW4_PROJECT" --account="$HW4_ACCOUNT"
gcloud projects add-iam-policy-binding "$HW4_PROJECT" \
  --member="serviceAccount:${HW4_WEB_SA}" --role=roles/logging.logWriter \
  --condition=None --account="$HW4_ACCOUNT"
gcloud pubsub topics add-iam-policy-binding "$HW4_TOPIC" \
  --member="serviceAccount:${HW4_WEB_SA}" --role=roles/pubsub.publisher \
  --project="$HW4_PROJECT" --account="$HW4_ACCOUNT"
gcloud pubsub subscriptions add-iam-policy-binding "$HW4_SUB" \
  --member="serviceAccount:${HW4_REPORTER_SA}" --role=roles/pubsub.subscriber \
  --project="$HW4_PROJECT" --account="$HW4_ACCOUNT"

for HW4_SA_TO_ATTACH in "$HW4_WEB_SA" "$HW4_REPORTER_SA"; do
  gcloud iam service-accounts add-iam-policy-binding "$HW4_SA_TO_ATTACH" \
    --member="user:${HW4_ACCOUNT}" --role=roles/iam.serviceAccountUser \
    --condition=None --project="$HW4_PROJECT" --account="$HW4_ACCOUNT"
done
```

The conditional Storage grant requires uniform bucket-level access. It was
accepted for this existing bucket. The bucket still has a pre-existing
`allUsers` Object Viewer binding from HW2: the added conditional binding does
not revoke that public access. Direct public object URLs bypass country checks;
`X-country` is an assignment simulation, not verified geographic location.

## Local checks and startup generation

Run from this homework directory, using Python 3.9 or later and Bash:

```bash
python3 -m unittest discover -s tests -v
python3 manage.py build
```

These commands do not call Google Cloud. Google client libraries are installed
inside the VM by the generated startup scripts. Each service records its exact
installed dependency versions at `/opt/cs528-hw4/installed-requirements.txt`.

## Create the VMs

Before deployment, check that the selected machine definitions exist in the
chosen zone. The web default is the small N1 shared-core `f1-micro`; use a different
web machine only after checking the assignment's smallest-VM requirement and
documenting the reason. The reporter default is `e2-micro`; the client default is
`e2-small` to provide more client CPU and memory for the four-client experiment.
Actual capacity is determined at creation time, not by `machine-types describe`.

The script requires your current public IPv4 address with `/32` for SSH ingress.
Set `HW4_SSH_SOURCE` to that value. Do not use a private LAN address or a VM's IP.
The example below is a documentation address and must be replaced for a live run:

```bash
export HW4_SSH_SOURCE="203.0.113.7/32"
python3 manage.py create --dry-run
```

After reviewing the plan and setting the real SSH source, this single command
creates all three VMs and automatically starts the web and reporter programs:

```bash
python3 manage.py create
```

After creation, obtain the newly reserved address rather than using a recorded
IP from the report:

```bash
HW4_IP="$(gcloud compute addresses describe cs528-hw4-web-ip \
  --region="$HW4_REGION" --project="$HW4_PROJECT" \
  --account="$HW4_ACCOUNT" --format='value(address)')"
export HW4_URL="http://${HW4_IP}:8080"
```

`create` checks prerequisites, creates a dedicated VPC and subnet, adds HTTP and
SSH firewall rules, reserves a regional static external IP, and creates:

| VM | Identity | Application |
|---|---|---|
| `cs528-hw4-web` | `cs528-hw4-web-sa` | HTTP server on port 8080, static external IP |
| `cs528-hw4-reporter` | `cs528-hw4-reporter-sa` | Forbidden-country subscriber |
| `cs528-hw4-client` | No attached service account | Instructor client, uploaded after creation |

The web and reporter use Debian 12 x86-64. The client uses Ubuntu 24.04 LTS
(`ubuntu-2404-lts-amd64` in `ubuntu-os-cloud`) to satisfy the instructor binary's
`GLIBC_2.38` requirement. Debian 12's glibc 2.36 cannot load the Python library
bundled in this executable; installing a separate Python interpreter does not
resolve that loader error. Each VM has a 10 GB standard persistent boot disk,
explicitly named `<vm-name>-boot` using `--create-disk` with
`boot=yes,auto-delete=yes`; cleanup checks this name before deleting the VM.
The reporter/client receive ephemeral external IPs for installation and API
access. HTTP is reachable on port 8080 of the web VM. SSH is restricted to the
provided `/32`. The services use attached-account credentials; no private key
files or local impersonation adapter are copied to the VM. `cloud-platform`
access scope allows Google API calls, while IAM still determines which calls
each service account can perform.

Existing resources must carry the script's description marker and match the
expected configuration. Matching stopped VMs are started; changed configuration
is reported rather than silently reused. For source updates, retain evidence,
delete the HW4 VMs, and recreate them with the new startup scripts.

For an existing Debian client, first save any client-VM results to the Mac, then
replace only that VM. `delete-client` checks the resource ownership marker,
homework label, and boot-disk name before deleting the client and its boot disk.
The ordinary `create` action then reuses the web/reporter and shared network:

```bash
python3 manage.py delete-client --dry-run
python3 manage.py delete-client
python3 manage.py create
```

Upload `client/http-client` again after replacement. The updated client carries
an `os-image` label; an old Debian client is rejected instead of silently reused.
Do not use the full `delete` action for this client-only replacement.

Creation can finish before package installation and systemd startup finish.
Check service status and actual HTTP results before declaring deployment complete.

```bash
python3 manage.py status
gcloud compute ssh cs528-hw4-web --zone="$HW4_ZONE" \
  --project="$HW4_PROJECT" --account="$HW4_ACCOUNT" \
  --command='sudo systemctl --no-pager status cs528-hw4-web; sudo journalctl -u google-startup-scripts.service --no-pager -n 40'
gcloud compute ssh cs528-hw4-reporter --zone="$HW4_ZONE" \
  --project="$HW4_PROJECT" --account="$HW4_ACCOUNT" \
  --command='sudo systemctl --no-pager status cs528-hw4-reporter'
```

If your public IP changes, update the owned SSH firewall rule before connecting:

```bash
gcloud compute firewall-rules update cs528-hw4-ssh \
  --source-ranges="$HW4_SSH_SOURCE" \
  --project="$HW4_PROJECT" --account="$HW4_ACCOUNT"
```

## HTTP and logging behavior

GET `/data/0.html` and GET `/cs528-hw2-yf-2026/data/0.html` read the same object.
POST accepts JSON such as `{"filename":"data/0.html"}`. Responses carry the
original bytes, Content-Type, Content-Length, and `Cache-Control: no-store`.

| Case | Status | Cloud log severity |
|---|---|---|
| Existing object, allowed country | 200 | No per-success application log |
| Missing object or path outside `data/` | 404 | WARNING |
| PUT, DELETE, HEAD, CONNECT, OPTIONS, TRACE, PATCH | 501 | ERROR |
| Assignment's forbidden country | 400 | CRITICAL |
| Malformed POST | 400 | WARNING |
| Storage authentication/service failure | 500 | ERROR |
| Forbidden notification publication unconfirmed | 503 | CRITICAL denial and ERROR delivery failure |

Unsupported methods are checked first. Forbidden GET/POST requests are denied
before reading an object. All nine assignment countries are recognized, including
the HW3 aliases and case/whitespace normalization. Pub/Sub publication is awaited;
a timeout never results in file delivery. HEAD returns headers without a body.
CONNECT is rejected, never used to establish a proxy tunnel.

Cloud logs are sent using `google-cloud-logging`'s `log_struct` API; JSON stdout on
a plain VM is not automatically evidence of a Cloud Logging entry. The web log
is named `cs528-hw4-web`. Logging failures are printed explicitly to the VM journal
and must be resolved during live acceptance. The reporter prints and flushes each
event before acknowledging it. Pub/Sub delivery is at least once; duplicate
event IDs can appear after a retry. Unlike HW3's Mac service, HW4's reporter uses
the VM identity and prints to stdout as requested in HW4; it does not append a
GCS log object and does not receive Storage write privileges.

## Performance experiment

Place the instructor's Linux x86-64 executable at `client/http-client` locally,
then upload it and verify its compatibility on the Ubuntu client VM:

```bash
gcloud compute scp client/http-client 'cs528-hw4-client:~/http-client' \
  --zone="$HW4_ZONE" --project="$HW4_PROJECT" --account="$HW4_ACCOUNT"
gcloud compute ssh cs528-hw4-client \
  --zone="$HW4_ZONE" --project="$HW4_PROJECT" --account="$HW4_ACCOUNT" \
  --command='getconf GNU_LIBC_VERSION && chmod u+x ~/http-client && ~/http-client -h'
```

Run from this directory on the Mac, after functional checks pass and the
instructor executable has been uploaded to `~/http-client` on the client VM:

```bash
python3 scripts/run_performance.py
```

The script reads the current web VM's external IP, uploads two standard-library
Python tools, starts a bounded background resource sampler on the web VM, and
runs the original instructor executable on the client VM. It does not rebuild
or change either deployed service. SSH key passphrases are entered normally;
connections are sequential. Keep the Mac awake and this terminal open. Do not
run additional instructor clients or HTTP probes during the sweep.

There are four groups with 1, 2, 3, and 4 concurrent clients. Each has 15 seconds
of warmup followed by 180 seconds of measurement, with 30 seconds between groups.
The load portion takes about 15 minutes; upload/download and authentication add
time. The client VM also records its resources to help detect a client bottleneck.
All clients use the same endpoint and timeout (30 seconds), no `-v`, and seeds
0 through N-1. A large request limit keeps each process active for the timed
window. At the deadline the runner deliberately terminates its own process
groups. These termination exit codes are not load failures, and an in-flight
request at termination may not finish. Any unexpected earlier process exit stops
the sweep and preserves partial evidence. A timeout printed by a live instructor
client is retained; the client can continue after such a timeout.

The runner refuses to start if another sweep holds its lock or any process named
`http-client` is already present. It launches at most four clients. A remote
1000-second watchdog bounds the entire load sweep, and the independent web
monitor stops after at most 1800 seconds. Client output is connected to a PTY so
quiet-mode timeout messages are line buffered and survive timed termination.

Results are downloaded to `results/performance/<UTC-run-id>/`:

- `web-resources.jsonl`: raw one-second whole-VM Linux `/proc` samples and clock
  synchronization metadata. CPU busy excludes idle, iowait, and steal; guest
  CPU fields are not counted twice. Iowait and steal are retained separately.
  The percentage refers to guest logical CPUs, not the f1-micro CPU entitlement.
- `client/c1` through `client/c4`: exact commands, UTC and monotonic durations,
  process exit information, timestamped quiet output, and client-VM metrics.
- `cloud-errors.json`, `web-journal.jsonl`, `reporter-journal.jsonl`: real
  application evidence. Expected `forbidden_country` 400 events are counted
  separately from other warning/error records.
- `web-vm.json`, `reporter-vm.json`, `client-vm.json`: configurations used in the run.
- `summary.json`, `summary.txt`, `web-metrics.csv`: window-specific summaries and
  data for performance graphs. Missing/short measurements are explicitly flagged.

Memory usage is `MemTotal - MemAvailable`, not just Python process RSS. RX/TX
are counters on the default network interface, converted to decimal megabits per
second; they include HTTP, GCS, logging, Pub/Sub, and background VM traffic.
Peaks are maxima of approximately one-second samples that overlap the measured
window, rather than instantaneous hardware maxima. Both VM clocks must report
synchronization, and the sampler must cover the full window, for a valid summary.

Quiet mode does not emit HTTP status counts or throughput. Therefore an empty
client log alone does not establish zero errors. Review client timeouts, unexpected
exits, server errors and logging failures together. Do not treat expected country
denials as saturation. Cloud logs can arrive late; after the run, repeat collection
without generating any load, using the printed run ID:

```bash
python3 scripts/run_performance.py --collect RUN_ID
```

Review the four measurements, graph the retained samples, and report the observed
CPU, memory, and bandwidth peaks if no capacity failure is observed at four clients.
No synthetic measurements are substituted for live results.

## Report and evidence

The PDF and evidence under `report/` describe the completed run, not a currently
running deployment. Exact installed package versions and service-start records
were captured before cleanup. Creation-time automatic startup was verified;
a separate live reboot test was not performed. The billing amount is explicitly
the displayed snapshot, not a final settled invoice.

The submitted PDF can be read directly without installing anything. To rebuild
it from the retained evidence, install the optional report dependencies in a
local environment (these are not added to either service VM):

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-report.txt
.venv/bin/python scripts/build_report.py
```

The output is `report/CS528_HW4_Report.pdf`. The figure generator reads the
retained one-second samples and measured windows; it does not generate load.
Raw capture files copied into `report/evidence/` are not rewritten. The evidence
guide identifies the derived summaries and preserves the two-client error caveat.

## Delete after saving evidence

The instructor's Piazza clarification asks students to delete the VMs after the
report is completed and to provide automatic deletion. Before deletion, export
the reporter journal, installed dependency versions, and any metrics stored on
VM disks to the Mac; deleting the boot disks removes these local VM files.

The read-only final evidence helper exports VM/disk/network metadata, service
state, exact installed dependency versions, startup/application journals, and
Cloud Logging records to a timestamped directory under `results/final/`.
It exits with a nonzero status if any required export fails. After successful
export, delete the resources and verify that all 11 expected compute/network
resources (including boot disks) are absent:

```bash
python3 scripts/final_evidence.py capture && \
python3 manage.py delete && \
python3 scripts/final_evidence.py verify-cleanup
```

The helpers use the same `HW4_PROJECT`, `HW4_ACCOUNT`, `HW4_REGION`, and `HW4_ZONE`
configuration as `manage.py`. Authentication and permission errors stop the
verification rather than being reported as successful deletion. This sequence
retains the original bucket, service accounts and Pub/Sub setup for TA recreation.

Preview deletion, then execute it with the same project/region/zone settings:

```bash
python3 manage.py delete --dry-run
python3 manage.py delete
```

This deletes the three recognized HW4 VMs and their boot disks, releases the
static external IP, and removes the two firewall rules, subnet, and VPC created
by this script. It preserves the HW2 bucket, HW3 resources, service accounts,
Pub/Sub topic/subscription, and local repository files. Keeping the identity
and messaging setup allows the TA to recreate the VMs using `create`.
If a command fails, the script stops with an error; inspect the remaining
resources and rerun cleanup after resolving the cause. It does not claim success
after a permission or network failure and does not perform an implicit rollback.

## References

- [Linux VM startup scripts](https://docs.cloud.google.com/compute/docs/instances/startup-scripts/linux)
- [Compute Engine service accounts and access scopes](https://docs.cloud.google.com/compute/docs/access/service-accounts)
- [Python HTTP server](https://docs.python.org/3/library/http.server.html)
- [Cloud Logging structured payloads](https://docs.cloud.google.com/python/docs/reference/logging/latest/google.cloud.logging_v2.logger.Logger)
- [VM create command](https://docs.cloud.google.com/sdk/gcloud/reference/compute/instances/create)
- [VM delete command](https://docs.cloud.google.com/sdk/gcloud/reference/compute/instances/delete)
- [Linux /proc counters](https://docs.kernel.org/filesystems/proc.html)
- [Cloud Billing reports and data availability](https://docs.cloud.google.com/billing/docs/how-to/reports)
