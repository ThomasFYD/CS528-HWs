# CS528 Homework 7: Apache Beam and Cloud Dataflow

Author: Yide Fang | Boston University

## Overview

This project analyzes the original 12,000 [HW2](https://github.com/ThomasFYD/CS528-HWs/blob/main/CS528-HW2/README.md) HTML objects with
one Apache Beam pipeline. It finds the five files with the most incoming links,
the five with the most outgoing links, and the five most frequent word trigrams.
The same program reads the original bucket in both the local and cloud experiments.

## Report

[Read the HW7 report (PDF)](report/CS528_HW7_Report.pdf)

The six-page report uses the same black-and-white format as HW6. It includes
configuration steps, program behavior, complete Top 5 outputs, measured runtimes
and the source link. Its visual review is recorded in
[report-visual-review.json](report/evidence/report-visual-review.json).

## Project structure

| Path | Purpose |
| --- | --- |
| [README.md](README.md) | Homework overview, setup, counting rules and recorded results. |
| [START_HERE.zh-CN.md](START_HERE.zh-CN.md) | Short Chinese guide to the report and results. |
| [report/CS528_HW7_Report.pdf](report/CS528_HW7_Report.pdf) | Final homework report. |
| [hw7/parsing.py](hw7/parsing.py), [hw7/pipeline.py](hw7/pipeline.py) | HTML parsing and Apache Beam transforms. |
| [run_hw7.py](run_hw7.py), [run.sh](run.sh), [show_results.py](show_results.py) | Measured execution, runner configuration and printed rankings. |
| [configure_cloud.sh](configure_cloud.sh), [setup.py](setup.py) | Cloud resource configuration and worker package. |
| [verify_results.py](verify_results.py), [check_oracle.py](check_oracle.py) | Full result comparison and independent generator-based verification. |
| [collect_evidence.py](collect_evidence.py) | Dataflow job, metrics and compute cleanup records. |
| [requirements.txt](requirements.txt), [requirements-dev.txt](requirements-dev.txt) | Pinned runtime and development dependencies. |
| [tests/](tests/) | Independent correctness tests. |
| [build_report.py](build_report.py) | Rebuild the report from retained measured evidence. |
| [report/evidence/](report/evidence/) | Measured results, logs, hashes and verified output archive. |
| [report/latest-run.json](report/latest-run.json) | Pointers to the successful local and cloud measurements. |
| `results/` | Local run outputs and metadata, excluded from Git. |

## Resources and requirements

Use Python 3.12, Google Cloud CLI, internet access and an authorized identity
for the existing course project. Cloud execution requires active billing.
Authentication uses the local Google Cloud login and application-default
credentials; no service-account key file is created.

| Resource | Value |
| --- | --- |
| Project | `dazzling-seat-508219-j3` |
| Input | `gs://cs528-hw2-yf-2026/data/*.html` |
| Region | `us-central1` |
| Private result bucket | `gs://cs528-hw7-yf-2026` |
| Worker | `cs528-hw7-worker@dazzling-seat-508219-j3.iam.gserviceaccount.com` |
| Cloud workers | 2 fixed `e2-standard-2`, 30 GB boot disks, one SDK process each |
| Local workers | 8 worker threads on Beam's FnApiRunner |
| SDK | Apache Beam 2.77.0 |

### Submission layout and direct execution

All HW7 files live under `CS528-HW7/`. Entry points are at the directory's top
level, the importable Beam package is in `hw7/`, and the PDF and evidence are
in `report/`. The shell scripts and Python programs with a shebang have Git
mode `100755`; source files use Unix line endings. Local environments, caches
and run directories are excluded from Git. The reviewed PDF and compact
experiment evidence are included.

`run.sh` locates its own directory and uses its `.venv`, so it can also be
invoked as `./CS528-HW7/run.sh local trial-01` from the repository root.
For Python entry points, activate the HW7 environment or use the documented
`.venv/bin/python` commands.

## Implementation details

### Counting rules

- Input is restricted to the HW2 `data/*.html` objects, not later homework outputs.
- Links are resolved relative to their source and counted only when they target
  a file in this input set. Repeated hyperlinks and self-links count repeatedly,
  matching HW2's degree convention. Zero-degree files are included.
- Words come from parsed visible HTML text, including link anchor text. The
  head, scripts, styles, templates and comments are excluded. Block tags insert
  whitespace; inline formatting preserves words. Entities are decoded.
- Words are Unicode alphabetic sequences, optionally with internal apostrophes.
  Text is case-folded; curly apostrophes normalize to straight apostrophes.
  Numbers and punctuation are separators. CSS is not evaluated.
- Trigrams are overlapping triples across line and paragraph boundaries within
  one file, but never across files. A file with `w` words has `max(w-2, 0)` triples.
- Rankings sort by count descending, then exact item string ascending. Filename
  ties use lexicographic order, not numeric filename order. Exactly five items
  are returned even when more items tie at the cutoff.

### Beam pipeline and verification

`hw7/pipeline.py` uses `MatchFiles`, `Reshuffle`, `ReadMatches`, a document DoFn,
`CombinePerKey(sum)` and `Top.Smallest` with key `(-count, item)`. Whole-file
reads preserve trigrams across line boundaries. Each file first combines
repeated destinations and trigrams with `Counter`, reducing shuffle volume;
the global Beam combine still computes exact corpus totals.

Each run writes eight result files: per-file audit records, aggregate totals,
three complete count files and three Top 5 files. `verify_results.py` checks
zero-degree coverage, unique file IDs, total incoming equals total outgoing,
per-file trigram totals, rankings and full output equality across runners.
Sorted SHA-256 fingerprints confirm identical source bytes for all input files
and identical complete count maps. The timed programs' source hashes must match.

`check_oracle.py` independently replays the instructor generator with seed 0,
12,000 files and `-m 325`. It verifies every input file's hash, reconstructs all
link counts, and calculates trigrams algebraically from the repeated template
and its two boundary triples. This oracle is validation only; neither measured
Beam job generates its input or substitutes predicted results for bucket reads.

The 12 tests cover duplicate/self/external links, URL resolution, visible text,
entities, inline formatting, case and punctuation, line boundaries, overlaps,
empty/short documents, complete Beam outputs, deterministic ties and missing input.

### Timing definitions

Timing uses `perf_counter` from just before pipeline construction to completed
result writes and `wait_until_finish`. It includes source listing/download,
parsing, computation, output and runner startup; cloud timing also includes
staging, provisioning and completion polling. Installation, result printing,
independent verification and report creation are excluded. Both graph and
trigram tasks share a single pass, so the reported time is their combined time.

Local output is written to disk and cloud output to GCS. The experiments are
single runs with different hardware and network paths, not an equal-hardware
benchmark or a claim of general cloud speedup.

## Setup and execution

### Installation and cloud configuration

Use Python 3.12 and an installed Google Cloud CLI. Authenticate locally; no
service-account key file is needed. The documented course-project owner has
the permissions needed to provision this assignment's resources.

```bash
git clone https://github.com/ThomasFYD/CS528-HWs.git
cd CS528-HWs/CS528-HW7
gcloud auth login fangyd@bu.edu --update-adc
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
bash configure_cloud.sh
```

If the repository already exists, use its `CS528-HW7` folder instead of cloning
again. Billing must be active. The configuration script enables the APIs,
creates the dedicated worker identity and private result bucket if absent,
and grants Dataflow Worker on the project, Object Viewer on the input bucket
and Object Admin on the result bucket. It reuses the existing default VPC and
its internal-communication rule; it does not create public firewall rules.

### Run the analysis and print results

Choose a fresh tag each time; each measured run has its own output path. The
wrapper prints all three Top 5 lists after a successful, validated run.

```bash
bash run.sh local trial-01
bash run.sh cloud trial-01
.venv/bin/python verify_results.py \
  --local results/local-trial-01/metadata.json \
  --cloud results/cloud-trial-01/metadata.json \
  --output results/trial-01-verification.json
.venv/bin/python check_oracle.py \
  --metadata results/local-trial-01/metadata.json \
  --output results/trial-01-oracle.json
.venv/bin/python collect_evidence.py \
  --metadata results/cloud-trial-01/metadata.json \
  --output results/trial-01-evidence
```

### Rebuild the submitted report

After installing dependencies, recreate the PDF from its retained, verified
evidence. New trial results remain in their separate directories.

```bash
.venv/bin/python build_report.py
```

## Results and evidence

| Execution | Successful complete runtime |
| --- | ---: |
| Local, 8 threads | 722.983 seconds |
| Dataflow, 2 workers | 1033.472 seconds |

Top five incoming:

| Item | Count |
| --- | ---: |
| 5984.html | 233 |
| 6710.html | 210 |
| 9835.html | 209 |
| 1912.html | 208 |
| 10186.html | 207 |

Top five outgoing:

| Item | Count |
| --- | ---: |
| 10190.html | 323 |
| 10602.html | 323 |
| 10817.html | 323 |
| 10838.html | 323 |
| 10889.html | 323 |

Top five trigrams:

| Item | Count |
| --- | ---: |
| ad minim veniam | 1,946,934 |
| adipiscing elit sed | 1,946,934 |
| aliqua ut enim | 1,946,934 |
| aliquip ex ea | 1,946,934 |
| amet consectetur adipiscing | 1,946,934 |

All 12,000 input hashes and complete count maps match between runners, and the independent generator oracle passes. Worker VMs and boot disks are absent after completion.

The actual submitted runs used `results/local-run2/metadata.json` and
`results/cloud-run1/metadata.json`; their metadata are copied into the evidence
folder. Actual cloud output is `gs://cs528-hw7-yf-2026/runs/run1/output/`.
The exact measured pipeline arguments are in those metadata files. The local
engine is selected explicitly by its full class name:
`apache_beam.runners.portability.fn_api_runner.FnApiRunner`.
This is Beam's direct batch execution engine. Beam 2.77.0's generic
`DirectRunner` can select Prism automatically; selecting FnApiRunner makes
the eight-thread local configuration explicit and reproducible.
The platform fields in cloud runtime metadata describe the submitting laptop;
the actual cloud worker configuration is recorded in `dataflow-job.json`.

### Local retry

An initial four-process local attempt failed after 1,265.444 seconds with a
gRPC ping timeout and `Channel closed prematurely`. Its metadata and log are
preserved as `local-failed-attempt.*`. A small real-data smoke test checked
eight-thread mode before the successful full local run. Only the successful
full runs enter the runtime comparison. The parsing and Beam pipeline source
are identical to the successful cloud run.

### Retained evidence

The successful comparison is recorded in [verification.json](report/evidence/verification.json).
The independent oracle passed in [oracle.json](report/evidence/oracle.json), and
all 12 tests passed as recorded in [tests.json](report/evidence/tests.json).
See [printed-results.txt](report/evidence/printed-results.txt) and
[cloud-printed-results.txt](report/evidence/cloud-printed-results.txt) for terminal output.
The complete verified result files are also available in
[verified-output.zip](report/evidence/verified-output.zip).

The Dataflow job record, service metrics, exact commands, source fingerprints,
dependency versions and both successful run logs are retained beside these files.

## Cleanup

The cloud run is batch, with
autoscaling disabled and exactly two requested workers. The one-hour cloud
wait limit requests cancellation if the job is still active; Ctrl-C also
requests cancellation. A killed controller or disconnected laptop can leave
a cloud job running; recover using its saved job ID:

```bash
gcloud dataflow jobs describe JOB_ID --region=us-central1 \
  --project=dazzling-seat-508219-j3
# Only for a job that is still running and should be stopped:
gcloud dataflow jobs cancel JOB_ID --region=us-central1 \
  --project=dazzling-seat-508219-j3
```

Dataflow releases batch workers on completion. The evidence collector checks
both worker VMs and disks; rerun it if automatic deletion is still in progress.
The small private output bucket and reusable worker identity remain. Original
HW2 objects are retained.

Final [cleanup.json](report/evidence/cleanup.json) confirms `JOB_STATE_DONE`,
zero remaining HW7 worker instances and zero remaining worker disks.

## References

- [HW2 dataset and degree conventions](https://github.com/ThomasFYD/CS528-HWs/blob/main/CS528-HW2/README.md)
- [Apache Beam Python quickstart](https://beam.apache.org/get-started/quickstart-py/)
- [Apache Beam file I/O](https://beam.apache.org/releases/pydoc/current/apache_beam.io.fileio.html)
- [Google Cloud Dataflow Python pipeline guide](https://docs.cloud.google.com/dataflow/docs/guides/create-pipeline-python)
- [Dataflow permissions](https://docs.cloud.google.com/dataflow/docs/concepts/security-and-permissions)
