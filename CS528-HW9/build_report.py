"""Build the HW9 report from the retained cloud observations and original screenshots."""
from io import BytesIO
import json
from pathlib import Path
from xml.sax.saxutils import escape

from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Image, PageBreak, Paragraph, Preformatted, SimpleDocTemplate, Spacer, Table, TableStyle

ROOT = Path(__file__).resolve().parent
EVIDENCE = ROOT / "report/evidence"
REPO = "https://github.com/ThomasFYD/CS528-HWs"
WIDTH = 504
story = []


def load(name):
    return json.loads((EVIDENCE / name).read_text())


def style(name, font, size, leading, before=0, after=0):
    return ParagraphStyle(name, fontName=font, fontSize=size, leading=leading,
                          spaceBefore=before, spaceAfter=after, textColor=colors.black)


body = style("Body", "Helvetica", 9.4, 13, after=8)
small = style("Small", "Helvetica", 8.2, 11, after=6)
title = style("Title", "Helvetica-Bold", 22, 27, after=12)
heading = style("Heading", "Helvetica-Bold", 16, 20, after=12)
subhead = style("Section", "Helvetica-Bold", 11, 14, before=8, after=6)
mono = style("Code", "Courier", 7.5, 9.5, after=9)
cell = style("Cell", "Helvetica", 8.4, 11)


def add(text, fmt=body):
    story.append(Paragraph(text, fmt))


def page(text):
    story.append(PageBreak())
    add(text, heading)


def code(text):
    story.append(Preformatted(text, mono))


def table(rows, widths):
    grid = []
    for i, row in enumerate(rows):
        vals = [escape(str(value)) for value in row]
        grid.append([Paragraph(f"<b>{v}</b>" if i == 0 else v, cell) for v in vals])
    item = Table(grid, colWidths=widths, hAlign="LEFT")
    item.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                              ("TOPPADDING", (0, 0), (-1, -1), 5),
                              ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    story.extend((item, Spacer(1, 7)))


def figure(file, box, display_width, caption):
    with PILImage.open(EVIDENCE / file) as src:
        picture = src.crop(box).convert("L")
    buffer = BytesIO()
    picture.save(buffer, format="PNG")
    buffer.seek(0)
    story.append(Image(buffer, width=display_width, height=display_width * picture.height / picture.width,
                       hAlign="LEFT"))
    story.append(Spacer(1, 5))
    add(caption, small)


r = load("summary.json")
cluster = load("cluster.json")
build = load("build.json")
deployment = load("deployment.json")
cleanup = load("cleanup.json")
assert cleanup["verified"] and r["requests"] == r["responses"] == 300
assert r["client_denials_delivered"] == r["status_counts"]["400"]
assert build["status"] == "SUCCESS"
image = deployment["spec"]["template"]["spec"]["containers"][0]["image"]
assert image.endswith("@" + build["results"]["images"][0]["digest"])
counts = r["status_counts"]
event = next(json.loads(line[10:]) for line in (EVIDENCE / "reporter.txt").read_text().splitlines()
             if line.startswith("FORBIDDEN ") and r["denial_event_id"] in line)

add("CS528 Homework 9", title)
add("Serving Cloud Storage files with Google Kubernetes Engine", heading)
add("<b>Yide Fang</b> | Boston University | November 23, 2026")
add(f'Code: <link href="{REPO}">{REPO}</link><br/>Directory: <b>CS528-HW9</b>')
add("1. Deployment and measured results", subhead)
add(f"The instructor's HTTP client sent {r['requests']} requests from an Ubuntu VM to a public GKE LoadBalancer Service. "
    f"The server returned {counts['200']} successful file responses and denied {counts['400']} requests from countries on the assignment list. "
    "Each denial has a matching event in the monitoring VM's standard output.")
table([["Component", "Configuration used in the experiment"],
       ["File service", "One Python container in one GKE Deployment replica. Service port 80 forwards to container port 8080."],
       ["Cluster", f"{cluster['name']} in {cluster['location']}. One {cluster['nodeConfig']['machineType']} node. GKE {cluster['currentMasterVersion']}."],
       ["Source files", "gs://cs528-hw2-yf-2026/data/ contains the original HW2 collection."],
       ["Client and monitor", "Two processes on a separate e2-small Compute Engine VM. The supplied x86-64 client sends requests. A systemd service pulls Pub/Sub messages and prints denials."],
       ["Observed errors", "A missing object returned 404. All seven specified unsupported methods returned 501. The application logged each error to Cloud Logging."]], [112,392])
add("Request handling", subhead)
add("A GET names the object in the URL. A JSON POST supplies its filename. For these two methods, the server checks the X-country header before reading storage. A match on the HW4 list returns HTTP 400 after Pub/Sub confirms publication. The reporter prints the event and then acknowledges the message. Other methods return 501 before object access.")
add("Submitted source", subhead)
add("Python web server &nbsp; web_server.py &nbsp;&nbsp; Monitoring app &nbsp; reporter.py"
    "<br/>GKE creation and startup &nbsp; deploy.sh &nbsp;&nbsp; Build recipe &nbsp; Dockerfile")

page("2. Configure and start the applications")
add("Prerequisites", subhead)
add("Use a billing-enabled GCP project and an authenticated account permitted to provision Compute Engine, GKE, Artifact Registry, Cloud Build, Pub/Sub and IAM resources and connect through IAP. On the workstation, install the Google Cloud CLI, Bash, Python 3.9+, curl, OpenSSH, OpenSSL and shasum. Place the supplied Linux binary at CS528-HW4/client/http-client or set HW9_CLIENT.")
code("gcloud auth login\ngcloud components install kubectl gke-gcloud-auth-plugin\ncd CS528-HW9\npython3 -m unittest discover -s tests -v\n./deploy.sh")
add("The recorded run used the existing HW4 web and reporter Google service accounts. In another project, provide HW9_PROJECT, HW9_BUCKET, HW9_ZONE, HW9_WEB_SA and HW9_REPORTER_SA. Grant the web account Storage Object Viewer on the source objects and Logs Writer on the project. The original bucket grant limits object access to data/. The script creates a dedicated topic and subscription and adds their application bindings.")
add("What the deployment script does", subhead)
table([["Step", "Action"],
       ["1. Create resources", "Enable the required APIs. Create a VPC and subnet, an IAP-only SSH rule for the VM, a topic, a pull subscription and an Artifact Registry repository."],
       ["2. Build the image", "Cloud Build installs the Python dependencies from requirements.txt. Its account can write the dedicated build bucket and image repository. The Dockerfile starts web_server.py as UID 65532."],
       ["3. Create the cluster", "gcloud container clusters create creates a one-node zonal cluster with Workload Identity Federation enabled. Its node account can pull the image. get-credentials sets a deployment-specific kubectl context."],
       ["4. Set Pod identity", "Create a namespace and Kubernetes service account named web within it. Bind roles/iam.workloadIdentityUser on the HW4 web identity and annotate the Kubernetes account with its Google service account email."],
       ["5. Start the workload", "Create the Deployment with zero replicas. Set its service account, environment and image digest, scale to one replica, and expose it with a LoadBalancer Service. The shell script uses imperative kubectl commands throughout."],
       ["6. Start the VM apps", "Create an Ubuntu 24.04 amd64 VM with the reporter identity. Install the subscriber dependencies in a virtual environment, enable the systemd unit and transfer the original client binary over IAP."]], [110,394])
add("Run ./verify.sh from the same directory to exercise the deployed system. Keep .state/ until ./cleanup.sh finishes. The README documents all configurable paths and identifiers.", small)

page("3. Kubernetes deployment in Cloud Console")
add("The Clusters view shows the experiment's healthy single-zone cluster. The Deployment overview identifies its active replica, Pod and external Service. The figures are crops of the original Google Cloud Console screenshots.")
figure("console-clusters.jpg",(0,0,1660,485),504,"Figure 1. Clusters overview in the course project. The row shows the cluster name, zone, one node and two vCPUs.")
figure("console-deployment.jpg",(285,625,1320,925),475,"Figure 2. Deployment overview. The selected namespace and cluster match this run. The replica summary reports one updated, ready and available replica.")
figure("console-deployment.jpg",(285,1060,1225,1355),475,"Figure 3. Managed Pods and exposing services. The web Pod is running with zero restarts. The Service lists the external endpoint.")
add("Image identity", subhead)
add("The digest below matches the Cloud Build result and the image reference in the running Deployment.")
code(build["results"]["images"][0]["digest"])

page("4. Curl and browser demonstrations")
add("The two curl commands target the public load balancer. For the browser test, Chrome sent same-origin requests to the deployed Pod over an authenticated Kubernetes port-forward. The page displays the status and reason phrase returned by each browser fetch.")
figure("curl-live.jpg",(28,20,670,495),365,"Figure 4. Live curl output displayed in a browser transcript. A missing object returns 404 and PUT against an existing object returns 501.")
figure("browser-live.jpg",(130,46,1150,451),485,"Figure 5. Chrome issued a successful GET, a missing-object GET, an unsupported HEAD, and a GET with X-country set to Iran.")
add("To repeat the browser test", subhead)
code('source ./settings.sh\nkubectl -n "$RUN" port-forward --address=127.0.0.1 service/web 18810:80')
add("Open http://127.0.0.1:18810/hw9-demo and select Run requests. The ./curl-demo.sh EXTERNAL_IP command reproduces the two public curl requests.", small)

page("5. VM client, error logs and reporter delivery")
add("Instructor client", subhead)
add(f"The Linux executable ran on the reporter VM with glibc 2.39. It requested {r['unique_paths']} distinct object paths in {r['requests']} attempts. Every attempt received an HTTP response. The command below uses the public address allocated during the experiment.")
code(f"./http-client -d {r['external_ip']} -p 80 -b /cs528-hw2-yf-2026 -w data \\\n  -n 300 -i 11999 -r 528 -t 30 -v")
table([["Check", "Recorded observation"],
       ["VM workload", f"{counts['200']} HTTP 200 responses and {counts['400']} HTTP 400 responses. Each of the {counts['400']} denied client paths matched a CRITICAL Cloud Logging entry and reporter event ID."],
       ["File integrity", f"GET and JSON POST for data/0.html each returned {r['source_bytes']:,} bytes, identical to the object downloaded directly from Cloud Storage."],
       ["404 and 501 logging", "The named log cs528-hw9-web contains a WARNING for the absent object and an ERROR for each of PUT, DELETE, HEAD, CONNECT, OPTIONS, TRACE and PATCH."],
       ["Banned-country probe", "A separate GET with X-country: Iran returned HTTP 400. Counting this probe, the monitor printed 12 distinct events in the formal run."]], [110,394])
add("One denial traced from the Pod to the VM", subhead)
add("The application generated the event ID below, logged it at CRITICAL severity, and published the event. The VM's stdout contains the same ID and country plus the Pub/Sub message ID. Comparing distinct event IDs accommodates possible redelivery.")
code(f"Country: {event['country']}       HTTP status: {event['status']}\nEvent ID: {event['event_id']}\nPub/Sub message ID: {event['pubsub_message_id']}\nReporter received (UTC): {event['received_at']}")
add("Cleanup and evidence", subhead)
add("After the screenshots and logs were saved, ./cleanup.sh deleted the Service, cluster, VM and dedicated resources. Post-cleanup inventory checks covered the compute instances, disks, forwarding rule and target pool. The original HW2 sample object remained readable.")
add("The report/evidence directory contains the run summary, Cloud Logging entries, reporter output and cleanup checks.", small)
add("Course references &nbsp; Lecture 2, <i>Cloud Tools and Console</i>, slide 19 (GKE cluster commands). Lecture 6, <i>Computing Services</i>, slide 4 (Kubernetes Engine containers).", small)


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.drawRightString(558, 27, str(doc.page))
    canvas.restoreState()


output = ROOT / "report/CS528_HW9_Report.pdf"
doc = SimpleDocTemplate(str(output), pagesize=(612,792), rightMargin=54, leftMargin=54,
                        topMargin=44, bottomMargin=55, title="CS528 Homework 9 - Yide Fang", author="Yide Fang")
doc.build(story, onFirstPage=footer, onLaterPages=footer)
