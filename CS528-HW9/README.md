# CS528 Homework 9 — Serving Cloud Storage files with GKE

Yide Fang | Boston University

Repository &nbsp; [https://github.com/ThomasFYD/CS528-HWs](https://github.com/ThomasFYD/CS528-HWs) · Directory `CS528-HW9`

[Read the HW9 report (PDF)](report/CS528_HW9_Report.pdf) · [Experiment evidence](report/evidence)

## Recorded results

On November 23, 2026, the instructor client sent 300 requests from the Ubuntu VM and received 300 responses across 295 distinct paths. It received 289 HTTP 200 responses and 11 HTTP 400 country denials. All 11 denial events were matched between Cloud Logging and reporter stdout. A separate Iran probe produced the twelfth reporter event in the recorded experiment. GET and JSON POST returned the same 97,586 bytes as the HW2 source object. The missing file produced 404, and PUT, DELETE, HEAD, CONNECT, OPTIONS, TRACE and PATCH each produced 501 with a corresponding error log.

The curl screenshot covers the public load balancer. Chrome exercised all four status cases through an authenticated GKE port-forward to the deployed Pod. The formal [run summary](report/evidence/summary.json), [per-request results](report/evidence/client-responses.json) and [reporter output](report/evidence/reporter.txt) retain the observations. The earlier single-worker implementation was updated to allow an idle browser connection and an active request to coexist. All 22 local checks passed. The [post-cleanup inventory](report/evidence/cleanup.json) found no remaining HW9 resources or IAM bindings among the items checked. The original HW2 sample remained readable.

## Architecture

A GKE Standard Deployment runs the HW4 Python web server in a non-root Linux container. A Kubernetes LoadBalancer Service routes TCP port 80 to port 8080 in the Pod. The Pod reads the existing HW2 bucket, writes structured error entries to Cloud Logging and publishes denied requests to Pub/Sub. A separate Ubuntu 24.04 x86-64 Compute Engine VM runs both the HW4 subscriber as a systemd service and the instructor's HTTP client as a separate process.

## Reproduce the deployment

Run from this directory with Bash, Python 3.9+, curl, OpenSSH, OpenSSL, shasum and the Google Cloud CLI. Install its Kubernetes components with `gcloud components install kubectl gke-gcloud-auth-plugin`. Authenticate with `gcloud auth login`. The deploying identity needs permission to enable APIs, create billing-backed resources, configure IAM, attach the service accounts and connect to the VM through IAP.

The defaults in [settings.sh](settings.sh) select the original course project, bucket, HW4 application identities and zone. Set `HW9_PROJECT`, `HW9_BUCKET`, `HW9_ZONE`, `HW9_WEB_SA` or `HW9_REPORTER_SA` to use another environment. The two application identities must already exist. Grant the web identity `roles/storage.objectViewer` on the input bucket (the existing HW4 grant is conditioned on `data/`) and `roles/logging.logWriter` on the project. The script grants the topic and subscription roles on this run's resources. The instructor's Linux binary is read from the neighboring HW4 directory, or set `HW9_CLIENT` to its path. The original input collection uses indices 0 through 11999.

```bash
python3 -m unittest discover -s tests -v
./deploy.sh
./verify.sh
```

[deploy.sh](deploy.sh) creates a run identifier in `.state/`. Keep that directory until cleanup and rerun the same command to resume. It provisions a VPC, subnet, IAP SSH firewall rule, topic, subscription, Artifact Registry repository, single-node zonal GKE cluster and VM. [build-image.sh](build-image.sh) sends the Dockerfile and application inputs to Cloud Build. The build identity can store the build source/logs in a dedicated bucket and push images to the dedicated repository. The node identity can pull the image. The Pod uses a named Kubernetes service account annotated and bound to the HW4 web identity via Workload Identity Federation. The VM uses the attached HW4 reporter identity.

The script creates the namespace, Kubernetes service account, Deployment and Service with imperative commands. It assigns the service account and environment before starting the first replica, then waits for rollout and an externally successful file request. It also copies and starts [reporter.py](reporter.py) and transfers the instructor binary over IAP. The web code and Google dependencies are in [web_server.py](web_server.py), [Dockerfile](Dockerfile) and [requirements.txt](requirements.txt).

## Verify the running service

[verify.sh](verify.sh) compares the GET and JSON POST payloads byte-for-byte against the original Storage object, then exercises HTTP 404, all seven HTTP 501 methods, and an HTTP 400 request with a banned country. The latter preserves the HW4 protocol. Errors go to the named log `cs528-hw9-web`. The reporter prints the denied country's name and event ID to stdout and acknowledges the message after printing.

The script runs the provided client on the VM for 300 verbose requests (seed 528), retrieves its compressed output, and checks the status counts and number of distinct paths. [verify_results.py](verify_results.py) matches each error case to Cloud Logging and joins the deliberate denial to reporter stdout by event ID. Raw outputs are under `results/<UTC run>/`.

For the browser proof, open `http://EXTERNAL_IP/hw9-demo` and select **Run requests**. The page makes same-origin requests and reads the HTTP status of each browser response. For an interactive curl demonstration:

```bash
curl -i "http://$EXTERNAL_IP/data/hw9-missing.html"
curl -i -X PUT "http://$EXTERNAL_IP/data/0.html"
```

Open **Kubernetes Engine → Workloads → web** to inspect the deployed replica. View the cluster and its zone under **Clusters**. After collecting screenshots and logs, run `./cleanup.sh` to remove this deployment and its dedicated IAM bindings.

## References

- CS528 Lecture 2, *Cloud Tools and Console*, slide 19 (cluster creation and kubectl context). Lecture 6, *Computing Services*, slide 4 (GKE containers).
- [Google Cloud GKE deployment quickstart](https://cloud.google.com/kubernetes-engine/docs/deploy-app-cluster)
- [Authenticate GKE workloads to Google Cloud APIs](https://cloud.google.com/kubernetes-engine/docs/how-to/workload-identity)

After successful cleanup, move the private `.state` directory under the ignored `results/` directory before starting a separate deployment with fresh resource names.

To reproduce the browser route used in the report, run the following in Bash, then open the displayed local URL.

```bash
source ./settings.sh
kubectl -n "$RUN" port-forward --address=127.0.0.1 service/web 18810:80
# http://127.0.0.1:18810/hw9-demo
```

To rebuild the PDF from the archived evidence, install the Python packages `reportlab` and `Pillow` in a local virtual environment, then run `python3 build_report.py`.
