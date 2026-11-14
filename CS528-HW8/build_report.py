"""Build the verified HW8 report in the same plain black-and-white format as HW6/HW7."""
import argparse
import json
import statistics
from pathlib import Path
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Preformatted, Image

ROOT = Path(__file__).resolve().parent
EVIDENCE = ROOT / "report/evidence"
RUN_ID = "20261114T032031Z"
RUN = EVIDENCE / RUN_ID
WIDTH = 504
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


def table(rows, widths):
    converted = [[p("<b>"+escape(str(cell))+"</b>" if i == 0 else escape(str(cell)), "CellHW")
                  for cell in row] for i, row in enumerate(rows)]
    t = Table(converted, colWidths=[w*WIDTH/sum(widths) for w in widths], hAlign="LEFT", repeatRows=1)
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                          ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    story.extend([t, Spacer(1, 8)])


def page(title):
    story.append(PageBreak())
    add(title, "HeadingHW")


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(colors.black)
    canvas.setFont("Helvetica", 8)
    canvas.drawRightString(558, 27, str(doc.page))
    canvas.restoreState()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default="November 14, 2026")
    parser.add_argument("--output", type=Path, default=ROOT / "report/CS528_HW8_Report.pdf")
    args = parser.parse_args()
    s = json.loads((RUN / "summary.json").read_text())
    check = json.loads((RUN / "verification.json").read_text())
    cleanup = json.loads((EVIDENCE / "cleanup.json").read_text())
    functional = json.loads((EVIDENCE / "functional/responses.json").read_text())
    source = json.loads((EVIDENCE / "functional/source-object.json").read_text())
    assert s["complete"] and check["passed"] and len(s["trials"]) == 3
    assert cleanup and all(v is None for v in cleanup.values())
    assert len(functional) == 32 and all(r["ok"] for r in functional)
    trials = s["trials"]
    failover = [r["client_sustained_success_completion_delay_s"] for r in trials]
    recovery = [r["recovery_first_zone_a_response_delay_s"] for r in trials]
    assert all(0 < t < 60 for t in failover + recovery)

    add("CS528 Homework 8", "TitleHW")
    add("Network Load Balancing and Failover", "HeadingHW")
    add("<b>Yide Fang</b> | Boston University | " + escape(args.date))
    add('Code: <link href="https://github.com/ThomasFYD/CS528-HWs">https://github.com/ThomasFYD/CS528-HWs</link><br/>Directory: <b>CS528-HW8</b>')
    section("1. Design and measured results")
    add("I extended the HW4 Python file service and deployed two web VMs in different zones of us-central1. A regional external passthrough Network Load Balancer distributes TCP connections to the two backends. Each HTTP response includes the actual VM zone in an X-Server-Zone header. A separate small VM runs the HW4 Pub/Sub reporter.")
    add("Three live trials deliberately killed the web process in us-central1-a with SIGKILL and then restarted it. The client launched one request per second throughout the run. All observed failover and recovery times were below one minute.")
    rows = [["Trial", "Client failover (s)", "Client recovery (s)", "Connection failures"]]
    for t in trials:
        rows.append([t["trial"], f'{t["client_sustained_success_completion_delay_s"]:.2f}',
                     f'{t["recovery_first_zone_a_response_delay_s"]:.2f}', t["post_stop_client_failure_count"]])
    table(rows, [50, 150, 150, 154])
    add(f"Median client-observed failover: <b>{statistics.median(failover):.2f} s</b>. Median recovery: <b>{statistics.median(recovery):.2f} s</b>. Failover means the first completed response in the sustained survivor-only sequence after the last failed probe; recovery means the first completed response from the restarted backend. Section 4 defines the clocks and limits of these observations.")
    section("Request distribution")
    add("During the baseline and stable recovered phases, all 196 requests succeeded: <b>100 (51.02%)</b> came from us-central1-a and <b>96 (48.98%)</b> from us-central1-c. The 45 deliberately single-backend steady-state requests all came from us-central1-c. A network load balancer does not guarantee exact alternation or a perfect 50:50 split.")
    add("The complete run contains 464 requests: 432 successful HTTP 200 responses and 32 connection-refused errors during the deliberate failures. No HTTP application errors occurred in the timing workload. Configuration, raw measurements, checks and cleanup evidence are retained with the source.")
    add('Source and reproduction steps: <link href="https://github.com/ThomasFYD/CS528-HWs/tree/main/CS528-HW8">github.com/ThomasFYD/CS528-HWs/tree/main/CS528-HW8</link>', "SmallHW")

    page("2. Applications and cloud configuration")
    table([["VM", "Zone", "Machine / purpose"],
           ["cs528-hw8-web-a", "us-central1-a", "f1-micro; Python web service"],
           ["cs528-hw8-web-b", "us-central1-c", "f1-micro; Python web service"],
           ["cs528-hw8-reporter", "us-central1-a", "e2-micro; Pub/Sub receive/print/ack"]], [180, 115, 209])
    add("All VMs use Debian 12 and 10 GB standard boot disks. Each web VM belongs to a separate unmanaged instance group. The backend service, forwarding rule and reserved external IPv4 address are regional. The experiment uses a dedicated VPC and the 10.88.0.0/24 subnet.")
    table([["Setting", "Actual configuration"],
           ["Project / region", "dazzling-seat-508219-j3 / us-central1"],
           ["Backend service / forwarding", "cs528-hw8-backend; TCP; EXTERNAL; port 8080"],
           ["Health check", "Regional HTTP; port 8080; GET /healthz"],
           ["Health thresholds", "2-second interval; 1-second timeout; 2 unhealthy / 2 healthy probes"],
           ["Connection selection", "Session affinity NONE; fresh TCP connection for every request"],
           ["Unhealthy connection persistence", "NEVER_PERSIST"],
           ["Firewall", "HTTP TCP 8080 allowed; SSH TCP 22 only through IAP (35.235.240.0/20)"]], [160, 344])
    section("Modified server and retained HW4 behavior")
    add("The server reads instance/zone from the Compute Engine metadata service with Metadata-Flavor: Google, validates the zone, and adds X-Server-Zone when completing response headers. It listens on 0.0.0.0:8080. Threaded request handling lets health probes run while a file request is in progress. /healthz reports application liveness; it does not test GCS or Pub/Sub availability.")
    add("GET and POST still return the original GCS file bytes. Missing files return 404; unsupported methods return 501; forbidden-country GET/POST requests return the assignment's 400 and publish a notification. Cloud Logging and the reporter remain active. The web unit uses Restart=no, so the deliberate SIGKILL leaves it down until the explicit restart.")
    code("HTTP/1.1 200 OK\nContent-Type: text/html\nContent-Length: 97586\nConnection: close\nX-Server-Zone: us-central1-c")

    page("3. Configuration and execution")
    add("Prerequisites: Python 3.9 or later, Google Cloud CLI, active project billing, an authorized account and a loaded SSH key. The existing HW2 bucket contains data/0.html through data/11999.html. The completed HW4 supplies web and reporter service identities. Defaults are pinned to the project and account shown below; README.md documents overrides for another project.")
    code("git clone https://github.com/ThomasFYD/CS528-HWs.git\ncd CS528-HWs/CS528-HW8\ngcloud auth login fangyd@bu.edu\nssh-add ~/.ssh/google_compute_engine\npython3 -m unittest discover -s tests -v\npython3 manage.py create --dry-run\npython3 manage.py create\npython3 manage.py status")
    add("If the repository already exists, enter its HW8 directory. The setup script enables Compute Engine, Pub/Sub and IAP, creates HW8 resources, attaches identities and installs dependencies and systemd services through startup scripts. Wait for both backends to become HEALTHY; VM creation alone does not prove application readiness.")
    table([["Identity / resource", "Permission used"],
           ["Existing cs528-hw4-web-sa", "Read HW2 data/ objects; write Cloud Logging; publish to the new HW8 topic"],
           ["Existing cs528-hw4-reporter-sa", "Subscribe to the new HW8 subscription"],
           ["Human account fangyd@bu.edu", "Provision resources, attach identities, and use IAP SSH"]], [215, 289])
    add("VMs use attached-service-account credentials; no private key is copied to them. The setup grants publish/subscribe access on HW8's own topic/subscription. Existing HW4 Storage and Logging grants are prerequisites, not recreated. The web VMs have ephemeral external IPs for package installation and API access.", "SmallHW")
    code("HW8_IP=$(gcloud compute addresses describe cs528-hw8-ip \\\n  --region=us-central1 --project=dazzling-seat-508219-j3 \\\n  --format='value(address)')\npython3 client.py -d \"$HW8_IP\" -p 8080 -b /cs528-hw2-yf-2026 \\\n  -w data -i 11999 -r 528 -n 60 --interval 1 \\\n  --output results/manual.jsonl\npython3 verify_live.py\npython3 experiment.py --trials 3")
    add("The client implements the instructor's GET path and country-header format, maximum-index and seed options, and prints every zone response. It also supports POST, explicit methods/headers, and replay of captured requests. The timing workload fixes an allowed country and selects existing file indices so expected country denials cannot be confused with failover failures. It does not claim to duplicate the executable's private random sequence.", "SmallHW")

    page("4. Measurement protocol and timing definitions")
    add("The run began on November 13, 2026 at 22:20:41 EST (November 14 at 03:20:41 UTC). Sampling continued for approximately 463 seconds, ending at 03:28:25 UTC. A 60-second baseline was followed by three kill/restart trials. The boundary-inclusive baseline contains 61 requests; each stable recovered phase contains 45.")
    add("For each trial, the controller records synchronized VM timestamps immediately before and after SIGKILL and verifies that the process exited. It waits for UNHEALTHY plus 15 consecutive successful survivor responses, then observes another 15 seconds. After restarting, it records application readiness, waits for HEALTHY and responses from both zones, then measures 45 more seconds. Each convergence check has a 55-second deadline; failure stops the client and restores the service.")
    section("Client-observed failover and recovery")
    add("Failover is measured from confirmed process termination to completion of the first request in the final uninterrupted survivor-only success sequence before restart. The preceding request was a connection failure. Each such success sequence was observed for another 32 seconds by request-start time. The first success immediately after a kill is insufficient evidence because a request can still be routed to the already-healthy VM.")
    add("Recovery is measured from the VM's restart command start to completion of the first HTTP 200 response bearing the restarted VM's zone. Application readiness occurred 1.64, 0.74 and 0.84 seconds after restart; observed return of traffic was later. There were no client connection errors during restart/recovered phases.")
    section("Separate health API observations")
    table([["Trial", "UNHEALTHY observed after kill (s)", "HEALTHY observed after restart (s)"],
           *[[t["trial"], f'{t["api_unhealthy_observed_delay_s"]:.2f}', f'{t["api_healthy_observed_delay_s"]:.2f}'] for t in trials]], [50, 227, 227])
    add("These API timings record when get-health returned the new state. They are distinct from the client-observed times on page 1 and include command/API latency. The measurements show that an API state change did not immediately coincide with the observed change in request routing; they do not identify the exact internal propagation delay.")
    section("Sampling and uncertainty")
    add(f"Every request uses a fresh TCP connection and no silent retries. A monotonic schedule launches one per second even when a previous request fails. Recorded intervals were {s['timing']['request_spacing_min_s']:.3f}-{s['timing']['request_spacing_max_s']:.3f} seconds (median {s['timing']['request_spacing_median_s']:.5f}). There were {s['timing']['health_query_count']} successful API polls and no poll errors.")
    add("The VM reported NTP synchronization; client wall-clock drift relative to its monotonic clock stayed below 0.002 s. Cross-host timing still assumes synchronized clocks. One-second probing, response latency, connection hashing and API polling limit precision. Three trials describe this setup; they are not a general SLA. Two decimal places preserve arithmetic, not hundredth-second detection accuracy.", "SmallHW")

    page("5. Request distribution and timeline")
    rows = [["Observation window", "A count", "C count", "Successes", "A / C percentage"]]
    phases = s["phases"]
    for label, record in [("Baseline", phases["baseline"]), *[(f"Recovered trial {i}", phases[f"trial-{i}-recovered"]) for i in range(1, 4)],
                          ("All stable both-healthy", s["both_healthy_windows"]),
                          ("All single-backend steady phases", {"counts": {"us-central1-a": 0, "us-central1-c": 45}, "successful_200": 45,
                                                                  "percent": {"us-central1-a": 0, "us-central1-c": 100}}),
                          ("Complete run (includes transitions)", s["total"])]:
        rows.append([label, record["counts"]["us-central1-a"], record["counts"]["us-central1-c"], record["successful_200"],
                     f'{record["percent"]["us-central1-a"]:.2f}% / {record["percent"]["us-central1-c"]:.2f}%'])
    table(rows, [178, 48, 48, 65, 165])
    add("A = us-central1-a; C = us-central1-c. Percentages use complete successful HTTP 200 file responses as the denominator. The 32 transport failures have no returned zone and are counted separately. The complete-run ratio is intentionally skewed by the repeated periods in which A is down; the stable both-healthy ratio is the appropriate view of normal balancing.")
    story.append(Image(str(ROOT / "report/request_timeline.png"), width=504, height=190.8))
    add("Figure 1. One marker per request at its start time. S1-S3 (dashed) mark confirmed process termination; R1-R3 (dotted) mark restart initiation. Crosses indicate connection-refused errors. Points on a zone row identify successful file responses from that backend.", "SmallHW")
    add("The network load balancer distributes connections using packet characteristics, including source port when session affinity is NONE. The client received responses from both zones, but individual windows were not exactly balanced. No round-robin or exact 50:50 guarantee is assumed.")

    page("6. Verification, cleanup and submission evidence")
    add("Forty local tests passed. They cover real HTTP parsing with simulated cloud dependencies, zone headers on success/error responses, metadata parsing, health checks, preserved country and method behavior, client failure records, timing analysis and resource ownership/deletion protections. The generated startup scripts passed shell syntax checks.")
    add("Thirty-two live HTTP checks passed: six cases against each direct backend and twenty file requests through the load balancer. GET and POST bytes matched the GCS source; 404, 501 and forbidden-country 400 responses were correct. Reporter event IDs matched both web servers' denial events. Cloud Logging retained WARNING, ERROR and CRITICAL records.")
    add(f"Verified source file: {escape(source['object'])}<br/>Size: {source['bytes']:,} bytes<br/>SHA-256: {source['sha256']}", "SmallHW")
    section("Cleanup and reproducible evidence checks")
    code("python3 check_submission.py results/20261114T032031Z\npython3 collect_evidence.py results/20261114T032031Z\npython3 manage.py delete\npython3 collect_evidence.py results/20261114T032031Z --finalize-cleanup")
    add(f"Cleanup verified {len(cleanup)} dedicated resource/disk entries absent: three VMs and boot disks, two instance groups, the forwarding rule, backend service, health check, reserved IP, two firewall rules, subnet, VPC, topic and subscription. The HW2 data and reusable HW4 identities remain. The recorded load balancer IP is historical and is no longer an active submission endpoint.", "SmallHW")
    table([["Files", "Purpose"],
           ["web_server.py; reporter.py; client.py", "Modified applications and request/zone client"],
           ["manage.py; startup.py", "Cloud setup, automatic startup and verified cleanup"],
           ["experiment.py; analyze.py", "Bounded live measurement and explicit timing definitions"],
           ["verify_live.py; check_submission.py", "Real service checks and evidence/source consistency"],
           ["collect_evidence.py; build_report.py; build_plot.py", "Retained evidence and reproducible report"]], [257, 247])
    add(f"Raw requests, actions, health polls, deployment settings, summary and verification are in report/evidence/{RUN_ID}/. Functional responses, original object hash, reporter/web logs and installed package versions are under report/evidence/functional/. cleanup.json records final absence checks. SHA256SUMS protects the retained evidence. The submitted startup source hash matches the measured VM labels.", "SmallHW")
    section("References")
    add("1. CS528-HW_8.pdf: items 1-6 and submission requirements.<br/>2. Lecture 18, Virtual Private Cloud and Load Balancers: slides 2-6 (purpose and network flow), 17 (backend-service option), 18 (listener binding).<br/>3. HW4 server, reporter and deployment source in this repository.", "SmallHW")
    for label, url in [("Google Cloud: regional external passthrough NLB setup", "https://docs.cloud.google.com/load-balancing/docs/network/setting-up-network-backend-service"),
                       ("Google Cloud: traffic distribution and connection tracking", "https://docs.cloud.google.com/load-balancing/docs/network/ext-netlb-traffic-distribution"),
                       ("Google Cloud: instance metadata queries", "https://docs.cloud.google.com/compute/docs/metadata/querying-metadata")]:
        add(f'<link href="{url}">{escape(label)}</link>', "SmallHW")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(args.output), pagesize=(612, 792), leftMargin=54, rightMargin=54,
                            topMargin=44, bottomMargin=55, title="CS528 Homework 8 - Yide Fang", author="Yide Fang")
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    print(args.output)


if __name__ == "__main__":
    main()
