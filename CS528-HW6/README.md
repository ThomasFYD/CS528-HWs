# CS528 Homework 6: Normalization and Predictive Models

Yide Fang | Boston University

This homework builds on the preserved HW5 formal experiment, run
`load-20261021T075735Z-5b3f60c2`. It migrates all 100,000 records from that run
into a separate `hw6` database on the existing Cloud SQL instance, verifies a
lossless reconstruction, and runs two predictive models on a new Compute Engine
VM. Other HW5 experiments and the original tables remain in `hw5`.

## Current verification status

Cloud execution completed on a new VM for run `20261103-015057-b504`.
All 100,000 formal-run requests were migrated losslessly from Cloud SQL.
The IP-country model scored **100%** on 19,975 held-out requests with no shared
IPs between training and test. The selected income random forest scored
**34.27%** on 20,000 held-out requests; the majority
baseline was **12.675%**. Income is below the assignment's 35% aim and is reported
as such. The assignment permits reporting problems reaching that aim.

Outputs were uploaded to the original bucket and downloaded with SHA-256
verification. The report uses these cloud measurements. The local snapshot
check scored 34.28%; it is kept separately and is not the reported cloud result.
Cleanup was verified after recovery: SQL is STOPPED/NEVER; the VM, boot disk,
subnet and network are absent. Source, the PDF report and compact run evidence
are included in this directory.

Actual output prefix:
`gs://cs528-hw2-yf-2026/cs528-hw6/runs/20261103-015057-b504/`

Compact run evidence is included under `report/evidence/`; complete prediction
files and partition membership are in the bucket and local `results/` directory.

## Files

- `schema.sql`: four 3NF base tables plus reconstruction/error views.
- `migrate.sql`: the parameterized data-transfer statements.
- `database.py`: dependency audits, SQL connection and transaction verification.
- `models.py`: training, validation selection, held-out evaluation and CSV output.
- `run_models.py`: local/VM entry point, provenance and cloud output upload.
- `infra.py`, `run.sh`, `startup.sh`: cloud lifecycle and VM initialization.
- `tests/test_hw6.py`: data-integrity, split-isolation and cleanup failure tests.
- `build_report.py`: reproducible PDF report generation from measured results.
- `report/CS528_HW6_Report.pdf`: report, including schema and migration SQL.
- `START_HERE.zh-CN.md`: short Chinese operating guide.

## Prerequisites and fixed resources

Use Python 3.11 or 3.12 and the Google Cloud CLI. Authenticate with an identity
authorized for the existing project. The owner can use:

```bash
gcloud auth login fangyd@bu.edu
```

All cloud commands explicitly select `dazzling-seat-508219-j3`. The existing
Cloud SQL instance is `cs528-hw5-mysql` in `us-central1`. Source database/user:
`hw5`; target database: `hw6`; password stays in Secret Manager under
`cs528-hw5-db-password`. Output bucket: `gs://cs528-hw2-yf-2026`.

The caller needs permission to use these resources, create a VM, VPC and subnet,
create/use the HW6 service account, and grant the documented scoped IAM roles.
The VM gets Cloud SQL Client on the project, access to the single DB password
secret, read access to the private HW6 source bucket and object-creation access
only under the output bucket's `cs528-hw6/` prefix. No service-account key file
or public inbound firewall rule is created. The existing database owner account
is reused for the homework DDL and is not claimed to be a production read-only
account. The existing output bucket's access policy is not otherwise changed.

## One-command cloud execution

Run from `CS528-HW6`:

```bash
python3 infra.py plan
python3 infra.py preflight
bash run.sh
```

Preflight requires the preserved SQL instance to be `STOPPED/NEVER` so the run
does not interrupt an already active workload. The script then:

1. Prepares the HW6 identity and private source bucket; uploads a checksummed archive.
2. Starts SQL and creates `hw6` if absent.
3. Creates one temporary `e2-standard-2` VM, Debian 12, 10 GB standard boot disk,
   in `us-central1-a`, with a dedicated VPC/subnet and ephemeral public IP.
4. Uses VM startup metadata to install dependencies and execute the Python code.
5. Reads HW5 directly from SQL; checks the functional dependencies; inserts into
   the new tables in one transaction and compares SHA-256 hashes of every
   reconstructed request, failure and timing field before commit.
6. Trains and evaluates both models; uploads the files below; writes `done.json`
   last only after all uploads succeed.
7. Downloads and verifies every output checksum, stops SQL, deletes the VM with
   its boot disk and removes the temporary subnet/network.
8. Prints the actual downloaded summary and both complete prediction CSV files
   to the terminal. Redirect stdout to a file if desired; the CSVs contain about
   40,000 lines in total.

Every run has a unique output directory and bucket prefix:

```text
gs://cs528-hw2-yf-2026/cs528-hw6/runs/<run-id>/
  country_predictions.csv
  income_predictions.csv
  splits.csv
  metrics.json
  migration.json
  summary.txt
  done.json
  startup.log
```

`metrics.json` includes exact accuracy, baseline, validation scores, class
reports, confusion matrices and dependency versions. `migration.json` records
counts and matching reconstruction hashes. `done.json` contains output hashes
and the source-archive hash. Startup failure produces `failure.json` when the
VM can still upload. The local `results/<run-id>/` contains VM metadata, serial
output, lifecycle state, verified outputs and `cleanup.json`.

Cleanup is attempted on normal completion, Python exceptions, Ctrl-C and
SIGTERM, and attempts VM removal even if stopping SQL fails. A killed process,
lost network or expired credentials can prevent cleanup. Recover using the
state path printed at launch:

```bash
python3 infra.py cleanup --state results/<run-id>/state.json
```

If model uploads completed but the controller was interrupted, recover the
same outputs, verify cleanup, and print both CSVs without starting resources:

```bash
python3 infra.py resume --state results/<run-id>/state.json
```

The measured run encountered a client-side timeout while deleting its VM.
The delete operation succeeded, and recovery rechecked the resource state.
The original failure record is preserved in
`report/evidence/cleanup-before-retry.json`.

SQL databases, model output objects, the small source archive and reusable HW6
identity are retained. SQL storage remains allocated even while stopped.

## Why the schema is in 3NF

HW5's request table contains `request_id -> client_ip -> country -> is_banned`
and `client_time -> time_of_day`. `client_ip`, `country` and `client_time` are not
request-table candidate keys. These transitive dependencies violate 3NF.

- `countries(country PK, is_banned)`: country determines the policy flag.
- `clients(client_ip PK, country FK)`: IP determines country.
- `requests(request_id PK, request_time UNIQUE, run_id, method, requested_file,
  client_ip FK, peer_ip, gender, age, income, client_time, http_status)`: request ID
  and unique receipt timestamp are candidate keys; other stored values describe
  that request. Country, the policy flag and extracted clock time are omitted.
- `request_timings(request_id PK/FK, extract_ns, storage_ns, response_ns,
  database_ns, total_ns, storage_attempted, response_sent)`: one measurement row
  per request, with values dependent on its key.

Under the assignment's fixed IP-country and country-policy assumptions, no
base table contains the identified partial or transitive dependencies. Client
age/gender/income are event metadata, not asserted to be functionally determined
by IP. `request_details` reconstructs the old request schema. `failed_requests`
is a view over non-200 requests; the old failure records are checked for exact
agreement before migration. Views may expose derived values without duplicating
them in base tables. Rerunning inserts only missing keys and verifies all existing
values; changed/incompatible target data causes an error rather than silent loss.

## Models and evaluation

**Country:** training-only majority country for each /24 IPv4 prefix, with
backoff to /16, /8 and the training-set majority. The split uses seed 528 on
sorted unique IPs: 80% of IPs for training, 20% for test. It does not join a test
IP to the full database mapping. This is a classifier of instructor-generated
IP patterns, not a real-world geolocation service.

**Income:** sort request IDs, shuffle once with seed 528, reserve 60%/20%/20%
for selection training/validation/test. Compare an age-mode categorical model,
a random forest and histogram gradient boosting on the validation set. The
latter two use only age, gender, country and simulated hour. Encoders are fit
only on training data. Choose the best validation score, refit on the first 80%
and evaluate the untouched final 20%. The test set and seed are not changed to
chase 35%. Exact income-range classification accuracy is used, not numeric
regression error or a tolerance window.

| Candidate | Validation accuracy |
| --- | ---: |
| Age-mode classifier | 33.375% |
| Random forest (selected) | 33.655% |
| Histogram gradient boosting | 33.205% |

The random forest uses 120 trees, maximum depth 18, minimum leaf size 20,
`max_features=0.8`, one-hot categorical encoding and seed 528. The observed
34.27% test result misses the 35% aim by 0.73 percentage points. Age is useful,
while adding other available fields did not reliably push accuracy above the
target. This is an observed limitation of this data/model evaluation, not proof
of a theoretical accuracy ceiling or a claim that all remaining signal is random.

## Local verification without cloud charges

Fifteen local tests passed, including data integrity, partition isolation,
repeatable transfer queries, and cleanup/recovery failure handling.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 .venv/bin/python run_models.py \
  --snapshot ../CS528-HW5/results/load-20261021T075735Z-5b3f60c2/database-snapshot.json.gz \
  --output results/local-check
```

Use a new output directory on each invocation. Snapshot mode validates input
and runs the models; it never reports that SQL migration or VM execution occurred.

Generate the PDF using a Python environment with ReportLab installed:

```bash
python3 build_report.py --results results/<run-id>
```

For a local snapshot result the PDF remains marked DRAFT. For a real cloud run,
the report requires a successful cleanup record before labeling cloud execution
verified. See the report for sources and full SQL listings.
