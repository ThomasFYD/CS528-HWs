#!/usr/bin/env python3
"""Reproducible, explicitly scoped HW5 infrastructure operations via gcloud."""
import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import subprocess
import tarfile
import tempfile
import time

import config as C

ROOT = Path(__file__).resolve().parent
NETWORK, SUBNET = C.PREFIX + "-network", C.PREFIX + "-subnet"
ADDRESS, FIREWALL = C.PREFIX + "-web-ip", C.PREFIX + "-http"
FUNCTION, JOB = C.PREFIX + "-stop-sql", C.PREFIX + "-hourly-stop"
DOCKER_REPO = C.PREFIX + "-functions"
CUSTOM_ROLE = "cs528Hw5SqlStopper"
LABELS = "course=cs528,homework=hw5"


def cloud(parts, json_output=False, allow_absent=False, quiet_output=False):
    command = ["gcloud", *parts, f"--project={C.PROJECT_ID}", "--quiet"]
    if json_output:
        command.append("--format=json")
    elif not quiet_output:
        print("Running: gcloud " + " ".join(parts[:4]), flush=True)
    # Component bootstrapping can happen before gcloud parses --quiet. Never
    # let a hidden prompt wait on the caller's terminal while output is captured.
    environment = {**os.environ, "CLOUDSDK_CORE_DISABLE_PROMPTS": "true"}
    result = subprocess.run(command, text=True, capture_output=True,
                            stdin=subprocess.DEVNULL, env=environment)
    if result.returncode:
        absent = any(token in result.stderr for token in (
            "NOT_FOUND", "not found", "does not exist", "HTTPError 404", "HTTPError 410"))
        if allow_absent and absent:
            return None
        # Never print command arguments: a SQL user command may contain a password.
        raise RuntimeError("gcloud " + " ".join(parts[:3]) + " failed:\n" + result.stderr.strip())
    if json_output:
        return json.loads(result.stdout) if result.stdout.strip() else None
    if not quiet_output:
        print(result.stdout.strip() or result.stderr.strip(), flush=True)
    return result.stdout.strip()


def describe(parts):
    return cloud(parts, json_output=True, allow_absent=True)


def owned(resource, name, sql=False, bucket=False):
    if not resource:
        return
    if sql:
        labels = resource.get("settings", {}).get("userLabels", {})
    else:
        labels = resource.get("labels", {})
    if labels.get("homework") != "hw5" and resource.get("description") != C.MARKER:
        raise RuntimeError(f"Refusing to change an existing resource not marked HW5: {name}")


def ensure(description, creation, label_check=True, sql=False):
    current = describe(description)
    if current:
        if label_check:
            owned(current, " ".join(description), sql=sql)
        return current
    cloud(creation)
    return None


def bind_project(email, role):
    cloud(["projects", "add-iam-policy-binding", C.PROJECT_ID,
        f"--member=serviceAccount:{email}", f"--role={role}", "--condition=None"], quiet_output=True)


def require_beta_component():
    installed = cloud(["components", "list", "--only-local-state"], json_output=True)
    if not any(item.get("id") == "beta" for item in (installed or [])):
        raise RuntimeError(
            "The local gcloud beta component is required for Cloud SQL labels. "
            "Run `gcloud components install beta --quiet` directly in your terminal, "
            "then retry setup.sh. No component installation was started by this check.")


def prepare():
    require_beta_component()  # Fail before creating any cloud resources.
    cloud(["services", "enable", "compute.googleapis.com", "storage.googleapis.com",
        "pubsub.googleapis.com", "logging.googleapis.com", "sqladmin.googleapis.com",
        "secretmanager.googleapis.com", "cloudfunctions.googleapis.com", "run.googleapis.com",
        "cloudbuild.googleapis.com", "artifactregistry.googleapis.com", "cloudscheduler.googleapis.com",
        "iam.googleapis.com"])
    cloud(["storage", "objects", "describe", f"gs://{C.BUCKET_NAME}/data/0.html"], quiet_output=True)
    for role in ("web", "reporter", "guard", "scheduler", "build"):
        email = C.service_account(role)
        identity = describe(["iam", "service-accounts", "describe", email])
        if identity:
            if identity.get("displayName") != C.MARKER + " " + role or identity.get("disabled"):
                raise RuntimeError("Unexpected or disabled existing service account: " + email)
        else:
            cloud(["iam", "service-accounts", "create", C.PREFIX + "-" + role,
                   f"--display-name={C.MARKER} {role}"])
    for role in ("roles/cloudsql.client", "roles/logging.logWriter"):
        bind_project(C.service_account("web"), role)
    bind_project(C.service_account("build"), "roles/cloudbuild.builds.builder")
    condition = f"title=hw5-data-read,expression=resource.name.startsWith('projects/_/buckets/{C.BUCKET_NAME}/objects/data/')"
    cloud(["storage", "buckets", "add-iam-policy-binding", f"gs://{C.BUCKET_NAME}",
        f"--member=serviceAccount:{C.service_account('web')}", "--role=roles/storage.objectViewer",
        f"--condition={condition}"], quiet_output=True)
    ensure(["pubsub", "topics", "describe", C.TOPIC_ID],
           ["pubsub", "topics", "create", C.TOPIC_ID, f"--labels={LABELS}"])
    sub = ensure(["pubsub", "subscriptions", "describe", C.SUBSCRIPTION_ID],
        ["pubsub", "subscriptions", "create", C.SUBSCRIPTION_ID, f"--topic={C.TOPIC_ID}",
         "--ack-deadline=60", f"--labels={LABELS}"])
    if sub and (sub.get("topic") != f"projects/{C.PROJECT_ID}/topics/{C.TOPIC_ID}" or sub.get("filter")
                or sub.get("pushConfig", {}).get("pushEndpoint")):
        raise RuntimeError("Existing HW5 subscription configuration differs")
    cloud(["pubsub", "topics", "add-iam-policy-binding", C.TOPIC_ID,
        f"--member=serviceAccount:{C.service_account('web')}", "--role=roles/pubsub.publisher"], quiet_output=True)
    cloud(["pubsub", "subscriptions", "add-iam-policy-binding", C.SUBSCRIPTION_ID,
        f"--member=serviceAccount:{C.service_account('reporter')}", "--role=roles/pubsub.subscriber"], quiet_output=True)
    bucket = describe(["storage", "buckets", "describe", f"gs://{C.ARTIFACT_BUCKET}"])
    if bucket:
        owned(bucket, C.ARTIFACT_BUCKET)
    else:
        cloud(["storage", "buckets", "create", f"gs://{C.ARTIFACT_BUCKET}",
            f"--location={C.REGION}", "--uniform-bucket-level-access", "--public-access-prevention"])
        cloud(["storage", "buckets", "update", f"gs://{C.ARTIFACT_BUCKET}", f"--update-labels={LABELS}"])
    # Only the dedicated disposable deployment bucket; never change the HW2 data bucket.
    cloud(["storage", "buckets", "update", f"gs://{C.ARTIFACT_BUCKET}", "--clear-soft-delete"])
    for role in ("web", "reporter", "build"):
        cloud(["storage", "buckets", "add-iam-policy-binding", f"gs://{C.ARTIFACT_BUCKET}",
            f"--member=serviceAccount:{C.service_account(role)}", "--role=roles/storage.objectViewer"], quiet_output=True)
    secret = describe(["secrets", "describe", C.PASSWORD_SECRET])
    if secret:
        owned(secret, C.PASSWORD_SECRET)
    else:
        cloud(["secrets", "create", C.PASSWORD_SECRET, "--replication-policy=automatic", f"--labels={LABELS}"])
    versions = cloud(["secrets", "versions", "list", C.PASSWORD_SECRET, "--filter=state:ENABLED"], json_output=True)
    if not versions:
        with tempfile.NamedTemporaryFile(mode="w", prefix="hw5-password-") as handle:
            handle.write(secrets.token_urlsafe(32))
            handle.flush()
            cloud(["secrets", "versions", "add", C.PASSWORD_SECRET, f"--data-file={handle.name}"], quiet_output=True)
    cloud(["secrets", "add-iam-policy-binding", C.PASSWORD_SECRET,
        f"--member=serviceAccount:{C.service_account('web')}", "--role=roles/secretmanager.secretAccessor"], quiet_output=True)
    print("Prerequisites ready.")


def sql():
    require_beta_component()  # Also protect direct infra.py sql invocations.
    # gcloud rejects an explicitly specified bin-log flag (even its --no-
    # form) together with --no-backup. Omit that flag for this new instance.
    current = ensure(["sql", "instances", "describe", C.SQL_INSTANCE],
        ["beta", "sql", "instances", "create", C.SQL_INSTANCE, "--database-version=MYSQL_8_4",
         "--edition=enterprise", f"--tier={C.SQL_TIER}", f"--region={C.REGION}",
         "--availability-type=zonal", "--storage-size=10GB", "--storage-type=SSD",
         "--no-storage-auto-increase", "--no-backup",
         "--deletion-protection", f"--labels={LABELS}"], sql=True)
    if current:
        if not current.get("databaseVersion", "").startswith("MYSQL_8_4") or current.get("region") != C.REGION:
            raise RuntimeError("Existing SQL version or region differs")
        if current["settings"].get("activationPolicy") != "ALWAYS":
            cloud(["sql", "instances", "patch", C.SQL_INSTANCE, "--activation-policy=always"])
    databases = cloud(["sql", "databases", "list", f"--instance={C.SQL_INSTANCE}"], json_output=True)
    if C.DB_NAME not in {row["name"] for row in databases}:
        cloud(["sql", "databases", "create", C.DB_NAME, f"--instance={C.SQL_INSTANCE}",
               "--charset=utf8mb4", "--collation=utf8mb4_unicode_ci"])
    users = cloud(["sql", "users", "list", f"--instance={C.SQL_INSTANCE}"], json_output=True)
    if C.DB_USER not in {row["name"] for row in users}:
        password = cloud(["secrets", "versions", "access", "latest", f"--secret={C.PASSWORD_SECRET}"], quiet_output=True)
        cloud(["sql", "users", "create", C.DB_USER, f"--instance={C.SQL_INSTANCE}",
               "--host=%", f"--password={password}"], quiet_output=True)
    print("Cloud SQL ready. startup.sh calls setup_schema.py to create only missing tables.")


def archive_source():
    names = ("config.py", "web_server.py", "hw4_service.py", "reporter.py", "request_data.py",
             "database.py", "setup_schema.py", "requirements.txt", "requirements-reporter.txt", "startup.sh")
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb", mtime=0) as gz:
        with tarfile.open(fileobj=gz, mode="w") as archive:
            for name in names:
                data = (ROOT / name).read_bytes()
                info = tarfile.TarInfo(name)
                info.size, info.mtime, info.mode = len(data), 0, 0o644
                archive.addfile(info, io.BytesIO(data))
    payload = buffer.getvalue()
    digest = hashlib.sha256(payload).hexdigest()
    build = ROOT / "build"
    build.mkdir(exist_ok=True)
    target = build / f"source-{digest}.tar.gz"
    target.write_bytes(payload)
    uri = f"gs://{C.ARTIFACT_BUCKET}/{target.name}"
    cloud(["storage", "cp", str(target), uri])
    return digest, uri


def deploy_guard():
    permissions = "cloudsql.instances.get,cloudsql.instances.update"
    role = describe(["iam", "roles", "describe", CUSTOM_ROLE])
    operation = "update" if role else "create"
    cloud(["iam", "roles", operation, CUSTOM_ROLE, "--title=CS528 HW5 SQL Stopper",
           f"--permissions={permissions}", "--stage=GA"])
    bind_project(C.service_account("guard"), f"projects/{C.PROJECT_ID}/roles/{CUSTOM_ROLE}")
    ensure(["artifacts", "repositories", "describe", DOCKER_REPO, f"--location={C.REGION}"],
        ["artifacts", "repositories", "create", DOCKER_REPO, f"--location={C.REGION}",
         "--repository-format=docker", f"--labels={LABELS}", f"--description={C.MARKER}"])
    function = describe(["functions", "describe", FUNCTION, "--gen2", f"--region={C.REGION}"])
    owned(function, FUNCTION)
    cloud(["functions", "deploy", FUNCTION, "--gen2", f"--region={C.REGION}",
        "--runtime=python312", f"--source={ROOT / 'guard'}", "--entry-point=stop_database",
        "--trigger-http", "--no-allow-unauthenticated", "--memory=256MiB", "--timeout=60s",
        "--min-instances=0", "--max-instances=1", f"--service-account={C.service_account('guard')}",
        f"--build-service-account=projects/{C.PROJECT_ID}/serviceAccounts/{C.service_account('build')}",
        f"--docker-repository=projects/{C.PROJECT_ID}/locations/{C.REGION}/repositories/{DOCKER_REPO}",
        f"--stage-bucket={C.ARTIFACT_BUCKET}", f"--update-labels={LABELS}",
        f"--set-env-vars=PROJECT_ID={C.PROJECT_ID},SQL_INSTANCE={C.SQL_INSTANCE}"])
    function = describe(["functions", "describe", FUNCTION, "--gen2", f"--region={C.REGION}"])
    url = function["serviceConfig"]["uri"]
    service = function["serviceConfig"]["service"].rsplit("/", 1)[-1]
    cloud(["run", "services", "add-iam-policy-binding", service, f"--region={C.REGION}",
        f"--member=serviceAccount:{C.service_account('scheduler')}", "--role=roles/run.invoker"], quiet_output=True)
    job = describe(["scheduler", "jobs", "describe", JOB, f"--location={C.REGION}"])
    if job and job.get("description") != C.MARKER:
        raise RuntimeError("Unrecognized existing scheduler job")
    cloud(["scheduler", "jobs", "update" if job else "create", "http", JOB,
        f"--location={C.REGION}", "--schedule=5 * * * *", "--time-zone=Etc/UTC",
        f"--uri={url}", "--http-method=POST", "--message-body={}",
        f"--oidc-service-account-email={C.service_account('scheduler')}",
        f"--oidc-token-audience={url}", "--attempt-deadline=120s", "--max-retry-attempts=3",
        f"--description={C.MARKER}"])
    resume_guard()


def deploy():
    digest, artifact = archive_source()
    network = ensure(["compute", "networks", "describe", NETWORK],
        ["compute", "networks", "create", NETWORK, "--subnet-mode=custom", f"--description={C.MARKER}"])
    if network and network.get("autoCreateSubnetworks"):
        raise RuntimeError("HW5 network is not a custom network")
    subnet = ensure(["compute", "networks", "subnets", "describe", SUBNET, f"--region={C.REGION}"],
        ["compute", "networks", "subnets", "create", SUBNET, f"--network={NETWORK}",
         f"--region={C.REGION}", "--range=10.85.0.0/24", "--enable-private-ip-google-access", f"--description={C.MARKER}"])
    if subnet and (subnet.get("ipCidrRange") != "10.85.0.0/24" or not subnet.get("network", "").endswith("/" + NETWORK)):
        raise RuntimeError("Existing HW5 subnet differs")
    rule = ensure(["compute", "firewall-rules", "describe", FIREWALL],
        ["compute", "firewall-rules", "create", FIREWALL, f"--network={NETWORK}",
         f"--allow=tcp:{C.PORT}", "--source-ranges=0.0.0.0/0", f"--target-tags={C.PREFIX}-web", f"--description={C.MARKER}"])
    if rule and (rule.get("targetTags") != [C.PREFIX + "-web"] or
                 rule.get("allowed") != [{"IPProtocol": "tcp", "ports": [str(C.PORT)]}]):
        raise RuntimeError("Existing HW5 HTTP firewall differs")
    ensure(["compute", "addresses", "describe", ADDRESS, f"--region={C.REGION}"],
        ["compute", "addresses", "create", ADDRESS, f"--region={C.REGION}", f"--description={C.MARKER}"])
    # Retrieve the address allocated by this project; never embed a literal IP.
    ip = describe(["compute", "addresses", "describe", ADDRESS, f"--region={C.REGION}"])["address"]
    for role, machine in (("web", C.WEB_MACHINE), ("reporter", C.REPORTER_MACHINE)):
        name = C.PREFIX + "-" + role
        current = describe(["compute", "instances", "describe", name, f"--zone={C.ZONE}"])
        if current:
            owned(current, name)
            if current.get("labels", {}).get("source") != digest[:32]:
                raise RuntimeError("Source changed: run `python3 infra.py refresh-vms` to update the owned VMs and retain SQL/data")
            if (not current.get("machineType", "").endswith("/" + machine) or
                [sa["email"] for sa in current.get("serviceAccounts", [])] != [C.service_account(role)]):
                raise RuntimeError("Existing VM configuration differs: " + name)
            if current.get("status") == "TERMINATED":
                cloud(["compute", "instances", "start", name, f"--zone={C.ZONE}"])
            continue
        parts = ["compute", "instances", "create", name, f"--zone={C.ZONE}",
            f"--machine-type={machine}", f"--subnet={SUBNET}", f"--tags={name}",
            f"--create-disk=name={name}-boot,boot=yes,auto-delete=yes,image-family=debian-12,image-project=debian-cloud,size=10GB,type=pd-standard",
            f"--service-account={C.service_account(role)}", "--scopes=cloud-platform",
            f"--labels={LABELS},source={digest[:32]}", f"--description={C.MARKER}",
            f"--metadata-from-file=startup-script={ROOT / 'startup.sh'}",
            f"--metadata=hw5-role={role},hw5-project={C.PROJECT_ID},hw5-subscription={C.SUBSCRIPTION_ID},hw5-artifact={artifact},hw5-source-sha256={digest}"]
        if role == "web":
            parts.append(f"--address={ip}")
        cloud(parts)
    deploy_guard()


def wait_for_startup(role, digest, token, timeout=600):
    marker = f"HW5 {role} startup completed. source={digest} refresh={token}"
    beginning = f"HW5 {role} startup beginning. source={digest} refresh={token}"
    path = ROOT / "report" / "evidence" / f"{role}-startup-after-refresh.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    print(f"Waiting for {role} startup (up to {timeout}s); log: {path}", flush=True)
    while time.monotonic() < deadline:
        output = cloud(["compute", "instances", "get-serial-port-output", C.PREFIX + "-" + role,
                        f"--zone={C.ZONE}"], quiet_output=True)
        path.write_text(output + "\n")
        if beginning in output:
            current_boot = output.rsplit(beginning, 1)[-1]
            if 'Script "startup-script" failed' in current_boot:
                raise RuntimeError(f"{role} startup failed; inspect {path}")
            if marker in current_boot:
                print(f"{role} startup completed for the new source.", flush=True)
                return
        time.sleep(15)
    raise RuntimeError(f"Timed out waiting for {role} startup; inspect {path}")


def refresh_vms():
    """Apply a source/dependency update through startup metadata, retaining disks/SQL."""
    machines = (("web", C.WEB_MACHINE), ("reporter", C.REPORTER_MACHINE))
    current_vms = {}
    # Validate both VMs before changing either of them.
    for role, machine in machines:
        name = C.PREFIX + "-" + role
        current = describe(["compute", "instances", "describe", name, f"--zone={C.ZONE}"])
        if not current:
            raise RuntimeError(f"Missing {name}; run setup.sh first")
        owned(current, name)
        if (not current.get("machineType", "").endswith("/" + machine) or
            [sa["email"] for sa in current.get("serviceAccounts", [])] != [C.service_account(role)]):
            raise RuntimeError("Unexpected VM configuration: " + name)
        if current.get("status") not in ("RUNNING", "TERMINATED"):
            raise RuntimeError(f"{name} is changing state; retry after it settles")
        current_vms[role] = current
    pause_guard()
    try:
        sql()
        digest, artifact = archive_source()
        for role, machine in machines:
            name = C.PREFIX + "-" + role
            if current_vms[role]["status"] == "RUNNING":
                cloud(["compute", "instances", "stop", name, f"--zone={C.ZONE}"])
            token = secrets.token_hex(16)
            cloud(["compute", "instances", "add-metadata", name, f"--zone={C.ZONE}",
                   f"--metadata-from-file=startup-script={ROOT / 'startup.sh'}",
                   f"--metadata=hw5-role={role},hw5-project={C.PROJECT_ID},hw5-subscription={C.SUBSCRIPTION_ID},hw5-artifact={artifact},hw5-source-sha256={digest},hw5-refresh-token={token}"])
            cloud(["compute", "instances", "add-labels", name, f"--zone={C.ZONE}",
                   f"--labels=source={digest[:32]}"])
            cloud(["compute", "instances", "start", name, f"--zone={C.ZONE}"])
            wait_for_startup(role, digest, token)
    finally:
        resume_guard()
    status("refresh-status.json")
    print("VM startup completed. SQL, disks and static IP were retained. Verify real HTTP/SQL behavior next.")


def pause_guard():
    job = describe(["scheduler", "jobs", "describe", JOB, f"--location={C.REGION}"])
    if not job or job.get("description") != C.MARKER:
        raise RuntimeError("Missing or unrecognized HW5 guard; run setup.sh first")
    if job.get("state") != "PAUSED":
        cloud(["scheduler", "jobs", "pause", JOB, f"--location={C.REGION}"])


def resume_guard():
    job = describe(["scheduler", "jobs", "describe", JOB, f"--location={C.REGION}"])
    if not job or job.get("description") != C.MARKER:
        raise RuntimeError("Missing or unrecognized HW5 guard")
    if job.get("state") == "PAUSED":
        cloud(["scheduler", "jobs", "resume", JOB, f"--location={C.REGION}"])


def stop_sql():
    current = describe(["sql", "instances", "describe", C.SQL_INSTANCE])
    owned(current, C.SQL_INSTANCE, sql=True)
    if current and current["settings"].get("activationPolicy") != "NEVER":
        cloud(["sql", "instances", "patch", C.SQL_INSTANCE, "--activation-policy=never"])


def finish():
    # Use after evidence export, before the final teardown if continued work is planned.
    stop_sql()
    resume_guard()
    for role in ("web", "reporter"):
        name = C.PREFIX + "-" + role
        current = describe(["compute", "instances", "describe", name, f"--zone={C.ZONE}"])
        owned(current, name)
        if current and current.get("status") == "RUNNING":
            cloud(["compute", "instances", "stop", name, f"--zone={C.ZONE}"])
    print("SQL/VMs stopped, hourly guard enabled. Disks/IP still incur charges; use cleanup.sh for teardown.")


def remove(description, deletion, vm=False):
    current = describe(description)
    if not current:
        return
    owned(current, " ".join(description))
    if vm:
        boot = [disk for disk in current.get("disks", []) if disk.get("boot")]
        if len(boot) != 1 or not boot[0].get("source", "").endswith("/" + current["name"] + "-boot"):
            raise RuntimeError("Unexpected boot disk; refusing VM deletion")
    cloud(deletion)


def function_cleanup_sources():
    """Retain the function descriptor and scope shared-bucket deletes to its source version."""
    cache = ROOT / "report" / "evidence" / "function-before-cleanup.json"
    function = describe(["functions", "describe", FUNCTION, "--gen2", f"--region={C.REGION}"])
    live = function is not None
    if function is None and cache.exists():
        function = json.loads(cache.read_text())
    if function is None:
        return []
    owned(function, FUNCTION)
    expected_name = f"projects/{C.PROJECT_ID}/locations/{C.REGION}/functions/{FUNCTION}"
    if function.get("name") != expected_name:
        raise RuntimeError("Function cleanup descriptor belongs to a different resource")
    build = function.get("buildConfig", {})
    sources = [build.get("source", {}).get("storageSource"),
               build.get("sourceProvenance", {}).get("resolvedStorageSource")]
    shared = [source for source in sources if source and source.get("bucket") != C.ARTIFACT_BUCKET]
    uris = set()
    if shared:
        project = cloud(["projects", "describe", C.PROJECT_ID], json_output=True)
        number = str(project.get("projectNumber", ""))
        if not number.isascii() or not number.isdecimal():
            raise RuntimeError("Cannot verify the project number for function source cleanup")
        expected_bucket = f"gcf-v2-sources-{number}-{C.REGION}"
        for source in shared:
            generation = str(source.get("generation", ""))
            if (source.get("bucket") != expected_bucket or
                    source.get("object") != f"{FUNCTION}/function-source.zip" or
                    not generation.isascii() or not generation.isdecimal()):
                raise RuntimeError("Unexpected function source location/version; refusing shared-bucket deletion")
            uris.add(f"gs://{expected_bucket}/{FUNCTION}/function-source.zip#{generation}")
    if live:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(function, indent=2) + "\n")
    return sorted(uris)


def cleanup():
    stop_sql()  # Preserve the database, schema, records and password secret.
    source_uris = function_cleanup_sources()
    job = describe(["scheduler", "jobs", "describe", JOB, f"--location={C.REGION}"])
    if job:
        if job.get("description") != C.MARKER:
            raise RuntimeError("Unrecognized scheduler job")
        cloud(["scheduler", "jobs", "delete", JOB, f"--location={C.REGION}"])
    remove(["functions", "describe", FUNCTION, "--gen2", f"--region={C.REGION}"],
           ["functions", "delete", FUNCTION, "--gen2", f"--region={C.REGION}"])
    for uri in source_uris:
        if describe(["storage", "objects", "describe", uri]):
            # Exact object generation only: never remove a shared service bucket.
            cloud(["storage", "rm", uri])
    for role in ("web", "reporter"):
        name = C.PREFIX + "-" + role
        remove(["compute", "instances", "describe", name, f"--zone={C.ZONE}"],
               ["compute", "instances", "delete", name, f"--zone={C.ZONE}", "--delete-disks=boot"], vm=True)
    remove(["compute", "addresses", "describe", ADDRESS, f"--region={C.REGION}"],
           ["compute", "addresses", "delete", ADDRESS, f"--region={C.REGION}"])
    remove(["compute", "firewall-rules", "describe", FIREWALL], ["compute", "firewall-rules", "delete", FIREWALL])
    remove(["compute", "networks", "subnets", "describe", SUBNET, f"--region={C.REGION}"],
           ["compute", "networks", "subnets", "delete", SUBNET, f"--region={C.REGION}"])
    remove(["compute", "networks", "describe", NETWORK], ["compute", "networks", "delete", NETWORK])
    remove(["pubsub", "subscriptions", "describe", C.SUBSCRIPTION_ID], ["pubsub", "subscriptions", "delete", C.SUBSCRIPTION_ID])
    remove(["pubsub", "topics", "describe", C.TOPIC_ID], ["pubsub", "topics", "delete", C.TOPIC_ID])
    remove(["artifacts", "repositories", "describe", DOCKER_REPO, f"--location={C.REGION}"],
           ["artifacts", "repositories", "delete", DOCKER_REPO, f"--location={C.REGION}"])
    bucket = describe(["storage", "buckets", "describe", f"gs://{C.ARTIFACT_BUCKET}"])
    if bucket:
        owned(bucket, C.ARTIFACT_BUCKET)
        cloud(["storage", "rm", "--recursive", f"gs://{C.ARTIFACT_BUCKET}"])
    status("cleanup-verification.json")
    print("HW5 teardown complete. SQL stopped (not deleted); its storage and password secret are retained.")


def status(filename="deployment-status.json"):
    result = {"project": C.PROJECT_ID, "sql": describe(["sql", "instances", "describe", C.SQL_INSTANCE]), "vms": {}}
    for role in ("web", "reporter"):
        result["vms"][role] = describe(["compute", "instances", "describe", C.PREFIX + "-" + role, f"--zone={C.ZONE}"])
    result["address"] = describe(["compute", "addresses", "describe", ADDRESS, f"--region={C.REGION}"])
    result["guard"] = describe(["scheduler", "jobs", "describe", JOB, f"--location={C.REGION}"])
    dest = ROOT / "report" / "evidence" / filename
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(result, indent=2) + "\n")
    summary = {"project": C.PROJECT_ID, "sql_policy": (result["sql"] or {}).get("settings", {}).get("activationPolicy"),
        "vms": {role: value.get("status") if value else "absent" for role, value in result["vms"].items()},
        "web_ip": (result["address"] or {}).get("address"), "guard": (result["guard"] or {}).get("state"), "evidence": str(dest)}
    print(json.dumps(summary, indent=2))


def plan(cleanup=False):
    print(json.dumps({"action": "cleanup" if cleanup else "setup", "project": C.PROJECT_ID,
        "region": C.REGION, "zone": C.ZONE, "web_vm": C.WEB_MACHINE,
        "reporter_vm": C.REPORTER_MACHINE, "sql": {"name": C.SQL_INSTANCE, "version": "MYSQL_8_4",
        "edition": "ENTERPRISE", "tier": C.SQL_TIER, "storage_gb": 10, "cleanup": "STOP, never DELETE"},
        "existing_hw2_bucket": C.BUCKET_NAME, "release_static_ip_on_cleanup": True,
        "guard": "Authenticated gen2 function, hourly at minute 5 UTC; runner pauses/resumes it",
        "data_retained_after_cleanup": ["Cloud SQL instance and data", "DB password secret", "local evidence", "HW2 bucket"],
        "billing": "No fixed quote. VM, SQL, network egress, storage and build usage are billable; stopped SQL retains storage charges.",
        "changes_made": False}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["plan", "prepare", "sql", "deploy", "refresh-vms", "status", "pause-guard", "resume-guard", "finish", "cleanup", "cleanup-plan"])
    args = parser.parse_args()
    if os.getenv("HW5_PROJECT_ID", C.PROJECT_ID) != C.PROJECT_ID:
        raise SystemExit("Project mismatch: this submission intentionally fixes its GCP project")
    actions = {"plan": plan, "prepare": prepare, "sql": sql, "deploy": deploy, "status": status,
        "refresh-vms": refresh_vms,
        "pause-guard": pause_guard, "resume-guard": resume_guard, "finish": finish,
        "cleanup": cleanup, "cleanup-plan": lambda: plan(True)}
    try:
        actions[args.action]()
    except (RuntimeError, subprocess.CalledProcessError, FileNotFoundError) as exc:
        raise SystemExit(f"ERROR: {exc}\nRetain the output. No implicit rollback or data deletion was attempted.") from exc


if __name__ == "__main__":
    main()
