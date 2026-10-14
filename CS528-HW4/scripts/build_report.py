"""Build the HW4 submission report from the retained, reviewed evidence."""

from html import escape
import json
from pathlib import Path
import tempfile

from pypdf import PdfReader, PdfWriter
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, PageBreak, Preformatted, Table,
    TableStyle, Image, KeepTogether,
)

from plot_performance import build as build_figures

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "report"
EVIDENCE = REPORT / "evidence"
RUN = "20261014T032504Z-48ab4d"
PERF = EVIDENCE / RUN
INK = colors.HexColor("#17324A")
BLUE = colors.HexColor("#1673A8")
GRAY = colors.HexColor("#526273")
PALE = colors.HexColor("#EEF3F7")
WIDTH = 504
STYLES = {
    "title": ParagraphStyle("Title", fontName="Helvetica-Bold", fontSize=22, leading=27,
                            textColor=INK, spaceAfter=12),
    "h1": ParagraphStyle("H1", fontName="Helvetica-Bold", fontSize=16, leading=20,
                         textColor=INK, spaceAfter=12),
    "h2": ParagraphStyle("H2", fontName="Helvetica-Bold", fontSize=11, leading=14,
                         textColor=INK, spaceBefore=9, spaceAfter=6),
    "body": ParagraphStyle("Body", fontName="Helvetica", fontSize=9.4, leading=13,
                           textColor=INK, spaceAfter=8),
    "small": ParagraphStyle("Small", fontName="Helvetica", fontSize=8.2, leading=11,
                            textColor=GRAY, spaceAfter=6),
    "caption": ParagraphStyle("Caption", fontName="Helvetica", fontSize=8.3, leading=11,
                              textColor=GRAY, spaceBefore=3, spaceAfter=9),
    "code": ParagraphStyle("Code", fontName="Courier", fontSize=7.5, leading=9.3,
                           textColor=INK, backColor=PALE, borderPadding=7, spaceAfter=10),
    "cell": ParagraphStyle("Cell", fontName="Helvetica", fontSize=8.1, leading=10.5,
                           textColor=INK),
}


def p(text, style="body"):
    return Paragraph(text, STYLES[style])


def code(text):
    if max(map(len, text.splitlines()), default=0) > 110:
        raise ValueError("Report code line too long: " + max(text.splitlines(), key=len))
    return Preformatted(text.strip(), STYLES["code"])


def table(headers, rows, widths):
    cells = [[p(escape(str(x)), "cell") for x in row] for row in [headers, *rows]]
    item = Table(cells, colWidths=widths, hAlign="LEFT", repeatRows=1)
    item.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), PALE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#DDE5EC")),
    ]))
    return item


def screenshot(path, width=480):
    w, h = ImageReader(str(path)).getSize()
    item = Image(str(path), width=width, height=width * h / w)
    item.hAlign = "CENTER"
    return item


def footer(canvas, doc):
    canvas.setStrokeColor(colors.HexColor("#DDE5EC"))
    canvas.line(54, 40, 558, 40)
    canvas.setFillColor(GRAY)
    canvas.setFont("Helvetica", 8)
    canvas.drawString(54, 27, "CS528 HW4 | Yide Fang | October 14, 2026")
    canvas.drawRightString(558, 27, str(doc.page))


def main_pages():
    story = []
    add = story.extend
    add([
        p("CS528 Homework 4", "title"),
        p("HTTP Services and Performance on Google Compute Engine", "h1"),
        p("<b>Yide Fang</b> | Boston University | October 14, 2026"),
        p('Code: <link href="https://github.com/ThomasFYD/CS528-HWs">'
          'https://github.com/ThomasFYD/CS528-HWs</link><br/>Directory: <b>CS528-HW4</b>'),
        p("1. Design and deployed resources", "h2"),
        p("I moved the HW3 file service and forbidden-country reporting service to separate VMs. "
          "A third VM runs the unchanged instructor client. The web service reads the existing HW2 "
          "objects in <b>gs://cs528-hw2-yf-2026/data/</b> and serves their original bytes. "
          "For forbidden-country requests it writes a CRITICAL Cloud Logging event and publishes "
          "the event to Pub/Sub. The reporter prints the event to stdout before acknowledging it."),
        table(["VM", "Machine / operating system", "Recorded public IP"], [
            ["cs528-hw4-web", "f1-micro; Debian 12; 1 shared vCPU; 614 MB configured RAM", "136.64.82.14 (static)"],
            ["cs528-hw4-reporter", "e2-micro; Debian 12", "136.113.233.208"],
            ["cs528-hw4-client", "e2-small; Ubuntu 24.04 LTS amd64", "34.123.133.194"],
        ], [135, 249, 120]),
        Spacer(1, 9),
        p("All VMs used us-central1-a and 10 GB standard persistent boot disks. I selected "
          "f1-micro for the web server as the smallest-memory available machine used in this setup. "
          "The dedicated VPC is cs528-hw4-network, with subnet 10.84.0.0/24. HTTP port 8080 "
          "was public; SSH was restricted to my current public IPv4 /32. All recorded IPs are "
          "historical: the VMs and static IP were removed after evidence collection."),
        p("Implementation", "h2"),
        p("The web server uses Python HTTPServer with one request worker, queue size 5, and a "
          "10-second socket timeout. Each successful request downloads an object from GCS; no "
          "application object cache is used. GET obtains the filename from the URL, while POST "
          'accepts JSON such as <font name="Courier">{"filename":"data/0.html"}</font>. '
          "Responses include Content-Length, Content-Type, Connection: close, and Cache-Control: no-store."),
        p("Unsupported methods return 501 before country processing. Missing objects return 404. "
          "The nine assignment countries return 400 and never receive file contents. A Pub/Sub "
          "publish failure returns 503 rather than reporting notification success. The reporter "
          "uses pull delivery; a failed print or acknowledgement leaves the message for retry."),
        p("Identity and assignment scope", "h2"),
        p("The web and reporter VMs attach separate service accounts; the client has no attached "
          "service account. No service-account private keys are copied to the VMs. The cloud-platform "
          "OAuth scope permits API access, while the IAM bindings on page 3 determine permissions. "
          "The services run as the unprivileged Linux user hw4."),
        p("The HW2 bucket retains its pre-existing public Object Viewer binding. Direct bucket URLs "
          "therefore bypass the application's country check. X-country is a simulated assignment "
          "header, not verified geography. The country list is the assignment list, not a claim "
          "about current sanctions law.", "small"),
        PageBreak(),
        p("2. Configuration and prerequisites", "h1"),
        p("Run the following from CS528-HW4 in a local terminal with Python 3.9+, Bash-compatible "
          "shell syntax, and the Google Cloud CLI. The project must have billing enabled, Compute "
          "Engine quota in the chosen zone, and the original HW2 objects data/0.html through "
          "data/11999.html. A TA can replace the project, bucket and account values below."),
        code('''export HW4_PROJECT="dazzling-seat-508219-j3"
export HW4_ACCOUNT="fangyd@bu.edu"
export HW4_BUCKET="cs528-hw2-yf-2026"
export HW4_REGION="us-central1"
export HW4_ZONE="us-central1-a"
export HW4_WEB_SA="cs528-hw4-web-sa@${HW4_PROJECT}.iam.gserviceaccount.com"
export HW4_REPORTER_SA="cs528-hw4-reporter-sa@${HW4_PROJECT}.iam.gserviceaccount.com"
export HW4_TOPIC="cs528-hw4-forbidden"
export HW4_SUB="cs528-hw4-forbidden-sub"

gc() { gcloud "$@" --project="$HW4_PROJECT" --account="$HW4_ACCOUNT"; }
gcloud auth login "$HW4_ACCOUNT"

gc services enable compute.googleapis.com storage.googleapis.com \\
  pubsub.googleapis.com logging.googleapis.com monitoring.googleapis.com \\
  iam.googleapis.com'''),
        p("Create the dedicated identities and messaging resources", "h2"),
        code('''gc iam service-accounts create cs528-hw4-web-sa \\
  --display-name="CS528 HW4 Web Server"
gc iam service-accounts create cs528-hw4-reporter-sa \\
  --display-name="CS528 HW4 Forbidden Country Reporter"
gc pubsub topics create "$HW4_TOPIC"
gc pubsub subscriptions create "$HW4_SUB" \\
  --topic="$HW4_TOPIC" --ack-deadline=60

gc storage objects describe "gs://${HW4_BUCKET}/data/0.html"
gc pubsub subscriptions describe "$HW4_SUB"
gc compute machine-types describe f1-micro --zone="$HW4_ZONE"'''),
        p("This subscription must be an unfiltered pull subscription attached to the specified "
          "topic. These are one-time setup commands: if the accounts or messaging resources "
          "already exist, inspect and reuse the matching resources. The setup in this project was "
          "retained after VM cleanup so that the TA can recreate the VMs."),
        p("Runtime dependencies and client compatibility", "h2"),
        p("Startup installs Python, a virtual environment and the required Google libraries. "
          "The observed web versions were google-cloud-storage 3.17.0, google-cloud-logging 3.17.0, "
          "and google-cloud-pubsub 2.42.0; the reporter used google-cloud-pubsub 2.42.0. "
          "The exact installed dependency lists are retained in report/evidence/installed-*.txt. "
          "The submitted requirements allow compatible major versions; future installations may differ."),
        p("The instructor Linux x86-64 executable initially failed on Debian 12 because its bundled "
          "Python library required GLIBC_2.38. I recreated only the client VM with Ubuntu 24.04 LTS "
          "(glibc 2.39), then uploaded the same executable. The web and reporter remained on Debian 12."),
        PageBreak(),
        p("3. IAM permissions", "h1"),
        p("The deployment account in this project was Owner. The runtime service accounts did not "
          "receive Owner or Editor; they received the scoped roles below. The Storage condition "
          "requires uniform bucket-level access, which was enabled on the existing bucket."),
        table(["Principal", "Role", "Scope"], [
            ["Web service account", "roles/storage.objectViewer", "Existing bucket; object prefix data/"],
            ["Web service account", "roles/logging.logWriter", "Project"],
            ["Web service account", "roles/pubsub.publisher", "Forbidden-country topic"],
            ["Reporter service account", "roles/pubsub.subscriber", "Forbidden-country subscription"],
            ["Deployment user", "roles/iam.serviceAccountUser", "Each runtime service account"],
        ], [132, 178, 194]),
        Spacer(1, 10),
        code('''HW4_DATA_CONDITION="resource.name.startsWith('projects/_/buckets/${HW4_BUCKET}/objects/data/')"

gc storage buckets add-iam-policy-binding "gs://${HW4_BUCKET}" \\
  --member="serviceAccount:${HW4_WEB_SA}" \\
  --role=roles/storage.objectViewer \\
  --condition="title=hw4-data-read,expression=${HW4_DATA_CONDITION}"

gc projects add-iam-policy-binding "$HW4_PROJECT" \\
  --member="serviceAccount:${HW4_WEB_SA}" \\
  --role=roles/logging.logWriter --condition=None

gc pubsub topics add-iam-policy-binding "$HW4_TOPIC" \\
  --member="serviceAccount:${HW4_WEB_SA}" --role=roles/pubsub.publisher

gc pubsub subscriptions add-iam-policy-binding "$HW4_SUB" \\
  --member="serviceAccount:${HW4_REPORTER_SA}" --role=roles/pubsub.subscriber

for HW4_SA_TO_ATTACH in "$HW4_WEB_SA" "$HW4_REPORTER_SA"; do
  gc iam service-accounts add-iam-policy-binding "$HW4_SA_TO_ATTACH" \\
    --member="user:${HW4_ACCOUNT}" --role=roles/iam.serviceAccountUser --condition=None
done'''),
        p("The conditional bucket grant does not revoke the public HW2 binding noted on page 1. "
          "The reporter needs no Storage write permission because HW4 requires it to print "
          "messages to stdout, which systemd retains in its journal."),
        p("Startup and reuse behavior", "h2"),
        p("startup.py builds self-contained metadata startup scripts. Each creates the hw4 Linux "
          "user, installs dependencies in /opt/cs528-hw4/venv, writes configuration and service "
          "files, then enables and starts its systemd unit. Dependencies are installed once per "
          "requirements hash. The service restarts on failure and is enabled for future boots. "
          "Creation-time automatic startup was verified live; a separate reboot test was not performed."),
        p("manage.py creates or reuses resources only when its ownership marker and required "
          "configuration match. It checks service identities, subscription configuration, the "
          "source object and machine types before creation. Unexpected configuration or API "
          "errors stop the operation; there is no silent rollback or permission bypass."),
        PageBreak(),
        p("4. Create, start and exercise the services", "h1"),
        p("Set SSH ingress to the current public IPv4 /32 of the local machine. After the "
          "one-time setup on pages 2-3, the single create command provisions all three VMs and "
          "automatically starts the two services. The public IP may differ on recreation."),
        code('''export HW4_SSH_SOURCE="$(curl -4 -fsS --max-time 15 https://api.ipify.org)/32"
python3 -m unittest discover -s tests -v
python3 manage.py create

HW4_IP="$(gc compute addresses describe cs528-hw4-web-ip \\
  --region="$HW4_REGION" --format='value(address)')"
export HW4_URL="http://${HW4_IP}:8080"
for role in web reporter; do
  gc compute ssh "cs528-hw4-${role}" --zone="$HW4_ZONE" \\
    --command="sudo systemctl --no-pager status cs528-hw4-${role}.service"
done'''),
        p("Allow startup installation to finish before testing. Live journals recorded the web "
          "service starting at 02:16:43 UTC and the reporter at 02:16:40 UTC on October 14. "
          "Both remained enabled and active when evidence was exported before cleanup."),
        p("Instructor client: 100 requests on the separate client VM", "h2"),
        code('''gc compute scp client/http-client 'cs528-hw4-client:~/http-client' \\
  --zone="$HW4_ZONE"
gc compute ssh cs528-hw4-client --zone="$HW4_ZONE" \\
  --command="chmod u+x ~/http-client && timeout 300s ~/http-client \\
  -d $HW4_IP -p 8080 -b /$HW4_BUCKET -w data \\
  -n 100 -i 11999 -r 0 -t 30 -v"'''),
        p("The bucket argument deliberately includes a leading slash. The observed run exited "
          "with code 0 and produced 100 requests and 100 responses: <b>97 HTTP 200 and 3 expected "
          "HTTP 400 country denials</b> (Libya, North Korea and Myanmar). The supplied executable "
          "is provided separately at client/http-client and excluded from Git."),
        p("HTTP checks from the local terminal", "h2"),
        code('''curl -i -H 'X-country: United States' "$HW4_URL/data/0.html"
curl -i -H 'X-country: United States' \\
  -H 'Content-Type: application/json' \\
  -d '{"filename":"data/0.html"}' "$HW4_URL/"
curl -i "$HW4_URL/data/hw4-does-not-exist.html"
curl -i -X PUT "$HW4_URL/data/0.html"
curl -i -H 'X-country: Iran' "$HW4_URL/data/0.html"'''),
        p("Observed results: GET and POST 200, missing file 404, PUT 501, and Iran 400. "
          "All seven unsupported methods (PUT, DELETE, HEAD, CONNECT, OPTIONS, TRACE, PATCH) "
          "returned 501. All nine assignment countries returned 400; the United States returned 200. "
          "HEAD was checked with curl --head. There are 53 passing local tests in addition to these live checks."),
        p("Byte-for-byte correctness", "h2"),
        p("The GCS source data/0.html and downloaded GET and POST bodies were compared with cmp. "
          "All three were 97,586 bytes and had the same SHA-256:", "small"),
        code("c3be7cacaad7e54bac9e5050419002b0545418e31094933b4239813e2a6f2b88"),
        PageBreak(),
        p("5. Browser demonstrations", "h1"),
        p("Chrome DevTools Network &gt; Headers shows the request URL, method and returned status "
          "for each required case. These screenshots were captured from the live web VM.", "small"),
    ])
    for status, caption in (("200", "Figure 1. GET /data/0.html returned 200 OK."),
                            ("404", "Figure 2. GET /data/hw4-does-not-exist.html returned 404 Not Found."),
                            ("501", "Figure 3. PUT /data/0.html returned 501 Not Implemented.")):
        add([screenshot(EVIDENCE / "screenshots" / f"browser-{status}.png", width=480), p(caption, "caption")])
    add([PageBreak(), p("6. Cloud Logging and forbidden-country reporting", "h1"),
         p("The following are selected fields from actual Cloud Logging records, not reconstructed "
           "test output. The full three records are retained in report/evidence/functional/cloud-errors.json. "
           "They belong to log <b>cs528-hw4-web</b>, resource type <b>gce_instance</b>, instance "
           "<b>6024668474438277977</b>, in project dazzling-seat-508219-j3.")])
    logs = json.loads((EVIDENCE / "functional/cloud-errors.json").read_text())
    for status, title in ((404, "Missing file: WARNING"), (501, "Unsupported method: ERROR"),
                          (400, "Forbidden country: CRITICAL")):
        entry = next(e for e in logs if e["jsonPayload"]["status"] == status)
        payload = entry["jsonPayload"]
        lines = ["{", f'  "severity": "{entry["severity"]}",',
                 f'  "timestamp": "{entry["timestamp"]}",', '  "jsonPayload": {',
                 f'    "event": "{payload["event"]}", "method": "{payload["method"]}", "status": {status},',
                 f'    "path": "{payload["path"]}",']
        if "event_id" in payload:
            lines += [f'    "event_id": "{payload["event_id"]}",', f'    "country": "{payload["country"]}",']
        lines += [f'    "message": "{payload["message"]}"', "  }", "}"]
        add([p(title, "h2"), code("\n".join(lines))])
    add([
        p("Reporter stdout confirms delivery", "h2"),
        p("The reporter printed the same Iran event ID, "
          "<font name=\"Courier\">a779625a-032f-423b-ac13-20249c682b0f</font>, "
          "at <b>2026-10-14T02:22:26.645567+00:00</b>, with Pub/Sub message ID "
          "<b>22021644937616833</b> and message <i>Permission denied: request from Iran.</i> "
          "The web event timestamp was 02:22:25.735086 UTC. The original stdout is retained in "
          "report/evidence/functional/reporter-journal.txt."),
        p("During the performance capture, all 417 structured web-journal payloads matched the "
          "Cloud Logging export. All 411 unique forbidden-country event IDs matched reporter "
          "stdout, with no missing IDs in that capture. This observed match does not change "
          "Pub/Sub's at-least-once delivery semantics.", "small"),
        PageBreak(),
        p("7. Stress-test method and findings", "h1"),
        p("I ran 1, 2, 3 and 4 concurrent copies of the unchanged instructor client on the "
          "e2-small VM. Each group had 15 seconds of warmup followed by a full 180-second "
          "measurement, with 30 seconds between groups. The timeout stayed at 30 seconds. "
          "Seeds were 0 through N-1, verbose output was disabled, and a large request limit "
          "kept every process alive until the timed stop. No more than four controlled clients ran."),
        code("python3 scripts/run_performance.py"),
        p("The runner captures quiet-mode timeout output through a PTY, records client and web VM "
          "resources, and downloads Cloud Logging and systemd journals. The web sampler reads "
          "/proc once per second. All four windows had synchronized clocks and uninterrupted "
          "web-sample coverage. Deadline termination (-15) was intentional, not a load failure."),
    ])
    results = json.loads((PERF / "summary.json").read_text())["rounds"]
    add([table(["Clients", "CPU mean / peak", "Memory peak", "RX / TX peak", "Timeouts"], [
        [r["clients"], f"{r['web']['mean']['cpu_busy_pct']:.2f}% / {r['web']['peak']['cpu_busy_pct']:.2f}%",
         f"{r['web']['peak']['memory_used_mib']:.2f} MiB",
         f"{r['web']['peak']['rx_mbps']:.2f} / {r['web']['peak']['tx_mbps']:.2f} Mbps", 0]
        for r in results], [43, 119, 103, 174, 65]), Spacer(1, 10),
        p("Saturation result", "h2"),
        p("At four clients, no client timeout, unexpected HTTP error log, or server exception "
          "was observed in the measured three-minute window. I therefore report the required "
          "fallback peaks: <b>CPU busy 7.84%, memory 363.30 MiB, RX 13.82 Mbps, and TX 13.81 Mbps.</b> "
          "The expected country-denial counts were 107, 79, 97 and 90; they are not capacity failures."),
        p("Scaling and measurement definitions", "h2"),
        p("Mean CPU busy increased from 3.97% to 4.69%, while memory remained near 359-363 MiB. "
          "Mean outbound traffic increased from 6.55 to 8.48 Mbps, about 29.35%, rather than "
          "quadrupling. The single worker serializes requests and waits on GCS and, for denials, "
          "logging and Pub/Sub. Low CPU and sublinear bandwidth growth are consistent with "
          "I/O waiting, although per-operation latency was not measured. The client VM's mean "
          "CPU stayed around 1.0-1.2%, so there was no observed CPU saturation on that VM."),
        p("CPU is guest logical-CPU busy time excluding idle, iowait and steal, not the f1-micro "
          "CPU entitlement. Memory is whole-VM MemTotal minus MemAvailable; network rates include "
          "GCS, HTTP, API and background traffic. Peaks are maxima of approximately one-second "
          "samples. Quiet mode provides no complete response counts, request throughput or latency, "
          "so this experiment does not establish maximum server capacity."),
        p("Two-client exception and external traffic", "h2"),
        p("The two-client group contained three GET / requests and one GET /login that returned "
          "404. Those paths are outside the configured file workload; their source IPs were not "
          "logged. A separate connection reset came from 66.132.159.21, not the load VM. "
          "I retained all samples and error records. This group includes external traffic and "
          "is not fully isolated; its 10.20% CPU peak is not evidence of overload caused by two clients."),
        p("The five figure pages following page 8 show the comparison and complete time series "
          "for each concurrency level. Raw samples, run windows and the error review are in "
          "report/evidence/20261014T032504Z-48ab4d/.", "small"),
        PageBreak(),
        p("8. Cost, cleanup and reproduction", "h1"),
        p("At the billing screenshot time, <b>October 13, 2026, 23:58 Eastern</b>, the report for "
          "October 1-13 showed <b>$0.00 net cost</b>, including <b>$0.04 in savings</b>. "
          "This month was used for HW4. The screenshot below preserves the amount actually "
          "displayed; the right-hand month-end forecast is not treated as actual spending."),
        screenshot(EVIDENCE / "billing/billing-2026-10-13.png", width=504),
        p("Figure 4. Billing snapshot before cleanup. This is a point-in-time reported cost, "
          "not a final settled invoice; delayed usage charges may appear later [4].", "caption"),
        p("Resource cleanup", "h2"),
        p("Before deletion, I exported VM, disk and network metadata, service state, exact package "
          "versions, startup/application journals, and Cloud Logging records. Both services were "
          "enabled and active. Export and cleanup are separate operations joined with &amp;&amp; "
          "so failed evidence export prevents the deletion command from running."),
        code('''python3 scripts/final_evidence.py capture && \\
python3 manage.py delete && \\
python3 scripts/final_evidence.py verify-cleanup'''),
        p("Verification completed at <b>2026-10-14 04:08:16 UTC</b> (00:08:16 Eastern): all "
          "<b>11 resources were absent</b> - three VMs, three boot disks, one reserved static IP, "
          "two firewall rules, one subnet and one VPC. The verification manifest is retained "
          "as report/evidence/cleanup-verification.json. The web endpoint is no longer live."),
        p("The HW2 bucket, runtime service accounts and Pub/Sub resources remain for recreation. "
          "With the configuration and permissions on pages 2-3, <b>python3 manage.py create</b> "
          "recreates the VMs and starts both services automatically. Ownership markers and boot-disk "
          "checks constrain deletion to the resources managed by this homework."),
        p("Submission contents", "h2"),
        p("The GitHub folder contains web_server.py, reporter.py, startup.py, manage.py, dependency "
          "files, 53 local tests, experiment tools, README instructions and reviewed evidence. "
          "The PDF is report/CS528_HW4_Report.pdf. The instructor executable and generated startup "
          "scripts are excluded from Git; the executable is supplied separately and startup "
          "scripts are rebuilt from submitted Python source."),
        p("References", "h2"),
        p('[1] CS528-HW_4.pdf, assignment requirements; Piazza clarification on automatic VM deletion.<br/>'
          '[2] <link href="https://docs.cloud.google.com/compute/docs/instances/startup-scripts/linux">'
          'Google Cloud: Linux VM startup scripts</link>; '
          '<link href="https://docs.cloud.google.com/compute/docs/access/service-accounts">VM service accounts</link>.<br/>'
          '[3] <link href="https://docs.kernel.org/filesystems/proc.html">Linux kernel: /proc counters</link>; '
          '<link href="https://docs.python.org/3/library/http.server.html">Python: http.server</link>.<br/>'
          '[4] <link href="https://docs.cloud.google.com/billing/docs/how-to/reports">Google Cloud Billing: Reports and data availability</link>.<br/>'
          '[5] <link href="https://docs.cloud.google.com/sdk/gcloud/reference/compute/instances/create">gcloud instances create</link>; '
          '<link href="https://docs.cloud.google.com/sdk/gcloud/reference/compute/instances/delete">instances delete</link>.', "small"),
    ])
    return story


def main():
    REPORT.mkdir(exist_ok=True)
    destination = REPORT / "CS528_HW4_Report.pdf"
    with tempfile.TemporaryDirectory(prefix="hw4-report-") as directory:
        main_pdf = Path(directory) / "main.pdf"
        doc = SimpleDocTemplate(str(main_pdf), pagesize=letter, leftMargin=54, rightMargin=54,
                                topMargin=44, bottomMargin=55,
                                title="CS528 Homework 4 - Yide Fang", author="Yide Fang")
        doc.build(main_pages(), onFirstPage=footer, onLaterPages=footer)
        main_count = len(PdfReader(main_pdf).pages)
        if main_count != 8:
            raise ValueError(f"Expected eight main pages; got {main_count}. Review pagination.")
        figures = Path(directory) / "figures.pdf"
        build_figures(PERF, figures, page_offset=main_count)
        writer = PdfWriter()
        writer.append(main_pdf)
        writer.append(figures)
        writer.add_metadata({"/Title": "CS528 Homework 4 - HTTP Services on Compute Engine",
                             "/Author": "Yide Fang", "/Subject": "Implementation, live evidence, performance and cleanup"})
        with destination.open("wb") as stream:
            writer.write(stream)
    print(destination)


if __name__ == "__main__":
    main()
