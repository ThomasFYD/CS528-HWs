#!/usr/bin/env python3
"""Build the verified HW7 report using the plain black-and-white HW6 format."""
import json
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Preformatted,
)

ROOT = Path(__file__).resolve().parent
EVIDENCE = ROOT / "report/evidence"
summary = json.loads((EVIDENCE / "verification.json").read_text())
oracle = json.loads((EVIDENCE / "oracle.json").read_text())
cleanup = json.loads((EVIDENCE / "cleanup.json").read_text())
job = json.loads((EVIDENCE / "dataflow-job.json").read_text())
assert summary["runners_match"] and summary["results"]["verified"]
assert oracle["verified"] and cleanup["verified"]
results = summary["results"]
local, cloud = summary["local"], summary["cloud"]
totals = results["totals"]
assert job["id"] == cloud["job_id"] == cleanup["job_id"]
assert oracle["links"] == totals["outgoing"]
assert oracle["words"] == totals["words"]
assert oracle["trigrams"] == totals["trigrams"]
WIDTH = 504
# Match CS528-HW6: plain black text, Helvetica typography, unshaded tables,
# numbered sections, and only a page number in the footer.
styles = {
    "BodyHW": ParagraphStyle("BodyHW", fontName="Helvetica", fontSize=9.4, leading=13, spaceAfter=8, textColor=colors.black),
    "SmallHW": ParagraphStyle("SmallHW", fontName="Helvetica", fontSize=8.2, leading=11, spaceAfter=6, textColor=colors.black),
    "TitleHW": ParagraphStyle("TitleHW", fontName="Helvetica-Bold", fontSize=22, leading=27, spaceAfter=12, textColor=colors.black),
    "HeadingHW": ParagraphStyle("HeadingHW", fontName="Helvetica-Bold", fontSize=16, leading=20, spaceAfter=12, textColor=colors.black),
    "SectionHW": ParagraphStyle("SectionHW", fontName="Helvetica-Bold", fontSize=11, leading=14, spaceBefore=9, spaceAfter=6, textColor=colors.black),
    "CodeHW": ParagraphStyle("CodeHW", fontName="Courier", fontSize=7.5, leading=9.3, spaceAfter=10, textColor=colors.black),
    "CellHW": ParagraphStyle("CellHW", fontName="Helvetica", fontSize=8.1, leading=10.5, textColor=colors.black),
}
story = []


def p(text, style="BodyHW"):
    return Paragraph(text, styles[style])


def add(text, style="BodyHW"):
    story.append(p(text, style))


def section(text):
    add(text, "SectionHW")


def code(text):
    story.append(Preformatted(text, styles["CodeHW"]))


def table(rows, widths, header=True):
    converted = [[p(("<b>" + escape(str(cell)) + "</b>") if header and index == 0 else escape(str(cell)), "CellHW") for cell in row] for index, row in enumerate(rows)]
    scaled_widths = [width * WIDTH / sum(widths) for width in widths]
    t = Table(converted, colWidths=scaled_widths, hAlign="LEFT", repeatRows=1 if header else 0)
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(t)
    story.append(Spacer(1, 8))


def page(title):
    story.append(PageBreak())
    add(title, "HeadingHW")


def number(value):
    return f"{value:,}"


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(colors.black)
    canvas.setFont("Helvetica", 8)
    canvas.drawRightString(558, 27, str(doc.page))
    canvas.restoreState()


add("CS528 Homework 7", "TitleHW")
add("Apache Beam and Cloud Dataflow", "HeadingHW")
add("<b>Yide Fang</b> | Boston University | November 9, 2026")
add('Code: <link href="https://github.com/ThomasFYD/CS528-HWs">https://github.com/ThomasFYD/CS528-HWs</link><br/>Directory: <b>CS528-HW7</b>')
section("1. Data and measured results")
add("This application uses Apache Beam to analyze the original HW2 HTML files. The same pipeline was executed on a local laptop and on Google Cloud Dataflow. Both runs completed, all input file hashes and complete count maps agree, and an independent reconstruction from the instructor's generator confirms the results.")
table([["Measure", "Verified value"],
       ["Input objects", number(totals["files"]) + " HTML files"],
       ["Input size", number(totals["bytes"]) + f" bytes ({totals['bytes'] / 2**30:.3f} GiB)"],
       ["Hyperlinks within the dataset", number(totals["outgoing"])],
       ["Input path", "gs://cs528-hw2-yf-2026/data/*.html"]], [195, 327])
add('Python source and reproducible commands: <link href="https://github.com/ThomasFYD/CS528-HWs/tree/main/CS528-HW7">github.com/ThomasFYD/CS528-HWs/tree/main/CS528-HW7</link>', "SmallHW")
section("Five files with the most incoming and outgoing links")
rows = [["Rank", "Incoming: file", "Links", "Outgoing: file", "Links"]]
for index, (incoming, outgoing) in enumerate(zip(results["top5"]["incoming"], results["top5"]["outgoing"]), 1):
    rows.append([index, incoming["item"], number(incoming["count"]), outgoing["item"], number(outgoing["count"])])
table(rows, [48, 143, 65, 156, 110])
add("Incoming counts measure hyperlinks pointing to a file; outgoing counts measure hyperlinks contained in that file. Repeated hyperlinks and self-links count separately, as in HW2. Files with no links are still included. Unknown or external targets are excluded.")
add("All rankings sort by count descending, then item string ascending. Filename ties therefore use lexicographic order. Exactly five items are printed; this does not imply only five items share the largest counts.", "SmallHW")

page("2. Word trigrams and counting rules")
add("A word trigram is an overlapping sequence of three consecutive words in one document. Whole-file reads preserve triples that cross line breaks. Triples may span paragraphs and punctuation, but never cross from one file into another.")
section("Five most frequent trigrams")
rows = [["Rank", "Trigram", "Occurrences"]]
for index, row in enumerate(results["top5"]["trigrams"], 1):
    rows.append([index, row["item"], number(row["count"])])
table(rows, [44, 330, 148])
cutoff = results["cutoff_ties"]["trigrams"]
add(f"There are {number(results['distinct_trigrams'])} distinct trigrams and {number(totals['trigrams'])} total occurrences in {number(totals['words'])} words. At the fifth-place cutoff, {number(cutoff['items_at_cutoff'])} different trigrams have the same frequency ({number(cutoff['cutoff_count'])}). The table shows the lexicographically first five among the top-ranked items.")
section("Text normalization")
add("The HTML parser decodes entities and retains visible body text, including anchor labels such as 'This is a link'. It excludes the head, scripts, styles, templates and comments. Block tags insert whitespace, while inline formatting does not split a word. CSS visibility is not evaluated.")
add("Text is case-folded. A word is a Unicode alphabetic sequence, optionally containing internal apostrophes; curly apostrophes are normalized. Numbers and punctuation separate words. For a file containing w words, the number of overlapping trigrams is max(w - 2, 0). These choices are explicit because the assignment does not specify tokenization details.")
section("Why many frequencies tie")
add(f"The HW2 generator repeats a fixed paragraph followed by the same anchor text. Each repetition contains {oracle['template_words']} words. Trigrams inside that block repeat once per block, while two boundary trigrams occur between adjacent blocks in a nonempty file. This repeated template explains the large tie groups; the pipeline still reads and counts every original cloud object.")

page("3. Pipeline implementation and verification")
add("One bounded Beam pipeline computes both the graph statistics and trigrams. Parsing each source object once lets both analyses share input I/O. The same Python modules are packaged for the Dataflow workers.")
table([["Stage", "Work performed"],
       ["1. MatchFiles", "List only data/*.html and build the input filename membership set."],
       ["2. Reshuffle + ReadMatches", "Distribute whole files across workers; read original GCS bytes."],
       ["3. ParseDocument", "Parse anchors and visible text; count repeated targets and trigrams within each file; record its byte hash and totals."],
       ["4. CombinePerKey(sum)", "Sum incoming-link contributions and trigram contributions globally. Emit outgoing counts directly from each file. Add zero entries for every file's indegree."],
       ["5. Top.Smallest(5)", "Use (-count, item) to select a deterministic descending-count ranking with ascending lexical ties."],
       ["6. Write and verify", "Write complete count maps, Top 5 lists, document audit and totals. Print verified rankings after measured execution."]], [165, 357])
section("Efficiency and correctness")
add("A Counter combines repeated destinations and trigrams before shuffle. This is exact because the final global operation sums those partial counts. It greatly reduces intermediate records for the repeated text in this dataset without changing the answer. Files are individually small enough for document-level parsing; very large single objects would need a different splitting strategy.")
add("Twelve tests passed. They cover repeated/self/external links, URL resolution, HTML entities and inline formatting, case and punctuation, cross-line triples, overlaps, empty/short files, zero degrees, deterministic ties, known complete Beam outputs and missing input.")

section("Full-dataset verification")
table([["Validation", "Outcome"],
       ["All file contents", "12,000 SHA-256 hashes match the original generator"],
       ["Complete link count maps", "Independent incoming and outgoing counts match"],
       ["Complete trigram count map", "Independent template-and-boundary formula matches"],
       ["Local versus Dataflow", "Every file audit and every aggregate count matches"]], [195, 327])

page("4. Configuration and execution")
add("Prerequisites: Python 3.12, Google Cloud CLI, an authenticated project owner (or equivalent scoped permissions), active project billing and access to the existing HW2 bucket. The experiment uses Apache Beam 2.77.0. No service-account key file is created.")
code("git clone https://github.com/ThomasFYD/CS528-HWs.git\ncd CS528-HWs/CS528-HW7\ngcloud auth login fangyd@bu.edu --update-adc\npython3.12 -m venv .venv\n.venv/bin/python -m pip install -r requirements-dev.txt\n.venv/bin/python -m pytest -q\nbash configure_cloud.sh")
add("If the repository is already present, enter its HW7 folder instead of cloning again. configure_cloud.sh enables Dataflow, Compute Engine, Storage and IAM; creates the dedicated worker and private result bucket if needed; and adds the following permissions.")
table([["Scope", "Worker permission / resource"],
       ["Project", "dazzling-seat-508219-j3: roles/dataflow.worker"],
       ["Original bucket", "cs528-hw2-yf-2026: roles/storage.objectViewer"],
       ["Private result bucket", "cs528-hw7-yf-2026: roles/storage.objectAdmin"],
       ["Region and network", "us-central1; existing default VPC and internal communication rule"]], [145, 377])
add("Worker identity: cs528-hw7-worker@dazzling-seat-508219-j3.iam.gserviceaccount.com. The owner can act as this service account. The result bucket blocks public access. The source bucket's existing access is preserved.", "SmallHW")
code("# Use a new tag for every pair of runs.\nbash run.sh local trial-01\nbash run.sh cloud trial-01\n.venv/bin/python verify_results.py \\\n  --local results/local-trial-01/metadata.json \\\n  --cloud results/cloud-trial-01/metadata.json \\\n  --output results/trial-01-verification.json\n.venv/bin/python check_oracle.py \\\n  --metadata results/local-trial-01/metadata.json \\\n  --output results/trial-01-oracle.json")
add("run.sh prints all rankings and exposes the exact runner options. Locally it selects Beam's FnApiRunner direct batch engine with eight worker threads. Dataflow uses two fixed e2-standard-2 workers, 30 GB boot disks and one SDK process per worker. Autoscaling is disabled. setup.py distributes the hw7 package; processing uses only the standard library beyond Beam.", "SmallHW")

page("5. Runtimes, limitations and cleanup")
table([["Measure", "Local laptop", "Cloud Dataflow"],
       ["Complete measured runtime", f"{local['elapsed_seconds']:.3f} s ({local['elapsed_seconds']/60:.2f} min)", f"{cloud['elapsed_seconds']:.3f} s ({cloud['elapsed_seconds']/60:.2f} min)"],
       ["Execution engine", "FnApiRunner, 8 threads", "DataflowRunner, 2 workers"],
       ["Hardware", "Apple M2, 8 logical CPUs; 8 GiB RAM", "2 x e2-standard-2 (4 vCPUs total)"],
       ["Input / output", "Original GCS objects / local files", "Same GCS objects / private GCS bucket"],
       ["Final state", local["state"], cloud["state"]]], [155, 183, 184])
ratio = cloud["elapsed_seconds"] / local["elapsed_seconds"]
add(f"The measured cloud/local runtime ratio is {ratio:.3f}. " +
    (f"The cloud run took {100*(1-ratio):.1f}% less elapsed time in this experiment." if ratio < 1 else f"The cloud run took {100*(ratio-1):.1f}% more elapsed time in this experiment."))
add("Both values use a monotonic timer from before pipeline construction until successful completion and output writes. They include listing, downloads, parsing, aggregation and runner startup. Dataflow additionally includes staging, worker provisioning and completion polling. Package installation, printing/verification and report generation are excluded. The time covers the combined graph and trigram workload.")
add("These are one-run end-to-end measurements, not statistically stable averages or equal-hardware comparisons. Local GCS traffic crosses the laptop's network; Dataflow runs in the bucket's region. The processor architectures, worker scheduling, I/O destinations and startup overhead differ. The result does not establish a general cloud speedup.")
add("An initial four-process local attempt failed after 1,265.444 s with a gRPC ping timeout and Channel closed prematurely. Its log and metadata are retained. Eight-thread mode was checked on a small real-data sample, then the full local measurement was restarted. The failed attempt and smoke test are excluded from the runtime table; the counting code is unchanged.", "SmallHW")
section("Job identity, verification and cleanup")
add(f"Dataflow job: {escape(cloud['job_id'])}<br/>State: {escape(job['currentState'])}. Worker VMs and their disks were confirmed absent after completion. The small result bucket, output evidence and reusable service account remain; original HW2 data remain unchanged.", "SmallHW")
add('Cloud console: <link href="https://console.cloud.google.com/dataflow/jobs/us-central1/' + cloud["job_id"] + '?project=dazzling-seat-508219-j3">Open the recorded Dataflow job</link>', "SmallHW")
add("The controller requests cancellation if its one-hour cloud wait expires or Ctrl-C is received. If the controller is lost, use gcloud dataflow jobs cancel JOB_ID --region=us-central1 --project=dazzling-seat-508219-j3 for an active job that should be stopped. collect_evidence.py checks automatic compute cleanup; its verified result is saved in report/evidence/cleanup.json.", "SmallHW")
page("6. Source files and evidence")
section("Files in the submission")
table([["File", "Purpose"],
       ["hw7/parsing.py; hw7/pipeline.py", "HTML semantics and Beam transforms"],
       ["run_hw7.py; run.sh; show_results.py", "Measured execution, fixed runner options and printed results"],
       ["configure_cloud.sh; setup.py", "Cloud provisioning and worker package"],
       ["verify_results.py; check_oracle.py", "Cross-run validation and independent reference calculation"],
       ["collect_evidence.py; build_report.py", "Cloud cleanup evidence and reproducible PDF"]], [245, 277])

add("Measured core source SHA-256:<br/>" + local["source_sha256"] + "<br/>Canonical input SHA-256:<br/>" + results["input_sha256"], "SmallHW")
add("Evidence includes both runtime metadata files, verification.json, oracle.json, dataflow-job.json, dataflow-metrics.json, cleanup.json and printed-results.txt. A compressed copy of the complete verified outputs is retained in verified-output.zip. Full cloud outputs remain under gs://cs528-hw7-yf-2026/runs/run1/output/. The PDF builder refuses incomplete or unverified measurements.", "SmallHW")
add("Runtime metadata platform fields describe the submitting laptop. Actual cloud worker configuration and service state are recorded separately in dataflow-job.json.", "SmallHW")
section("References")
for label, url in [
    ("Apache Beam: Python quickstart", "https://beam.apache.org/get-started/quickstart-py/"),
    ("Apache Beam: file I/O transforms", "https://beam.apache.org/releases/pydoc/current/apache_beam.io.fileio.html"),
    ("Google Cloud: Python Dataflow pipelines", "https://docs.cloud.google.com/dataflow/docs/guides/create-pipeline-python"),
    ("Google Cloud: Dataflow permissions", "https://docs.cloud.google.com/dataflow/docs/concepts/security-and-permissions"),
]:
    add(f'<link href="{url}">{escape(label)}</link>', "SmallHW")

output = ROOT / "report/CS528_HW7_Report.pdf"
doc = SimpleDocTemplate(str(output), pagesize=(612, 792), rightMargin=54, leftMargin=54,
                        topMargin=44, bottomMargin=55, title="CS528 Homework 7 - Yide Fang",
                        author="Yide Fang")
doc.build(story, onFirstPage=footer, onLaterPages=footer)
print(output)
