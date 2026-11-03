#!/usr/bin/env python3
"""One-command HW6 deployment, verified result retrieval, and cleanup."""
import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import secrets
import signal
import subprocess
import tarfile
import time
from datetime import datetime, timezone

import config as C

ROOT = Path(__file__).resolve().parent
SOURCE_FILES = ("config.py", "database.py", "models.py", "run_models.py", "schema.sql", "migrate.sql", "requirements.txt")


def cloud(parts, json_output=False, absent=False, timeout=600):
    command = ["gcloud", *parts, f"--project={C.PROJECT}", "--quiet"]
    if json_output: command.append("--format=json")
    result = subprocess.run(command, capture_output=True, text=True, stdin=subprocess.DEVNULL,
        timeout=timeout, env={**os.environ, "CLOUDSDK_CORE_DISABLE_PROMPTS":"true"})
    if result.returncode:
        if absent and any(s in result.stderr for s in ("NOT_FOUND", "HTTPError 404", "not found: 404", "NotFoundException", "does not exist", "was not found", "No URLs matched")):
            return None
        raise RuntimeError("gcloud " + " ".join(parts[:3]) + " failed: " + result.stderr.strip())
    if json_output: return json.loads(result.stdout) if result.stdout.strip() else None
    return result.stdout


def describe(parts): return cloud(parts, json_output=True, absent=True)


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


def sql_status():
    result = describe(["sql", "instances", "describe", C.SQL_INSTANCE])
    if not result or result.get("settings",{}).get("userLabels",{}).get("homework") != "hw5":
        raise RuntimeError("Expected preserved HW5 database with homework=hw5 ownership label")
    return result


def check_owned(value):
    if value and value.get("description") != C.MARKER:
        raise RuntimeError("Refusing to modify a resource without the exact HW6 ownership marker")


def preflight():
    sql = sql_status()
    if sql["state"] != "STOPPED" or sql["settings"]["activationPolicy"] != "NEVER":
        raise RuntimeError("Start from STOPPED/NEVER SQL so this script cannot interrupt another active workload")
    cloud(["storage", "buckets", "describe", f"gs://{C.BUCKET}"])
    print("Preflight: preserved SQL is stopped; output bucket is accessible.",flush=True)


def prepare_identity():
    cloud(["services","enable","compute.googleapis.com","sqladmin.googleapis.com","storage.googleapis.com","secretmanager.googleapis.com","iam.googleapis.com"])
    identity = describe(["iam","service-accounts","describe",C.SERVICE_ACCOUNT])
    if identity:
        if identity.get("displayName") != C.MARKER or identity.get("disabled"):
            raise RuntimeError("Unexpected or disabled HW6 service account")
    else:
        cloud(["iam","service-accounts","create",C.SERVICE_ACCOUNT_NAME,f"--display-name={C.MARKER}"])
    member = f"--member=serviceAccount:{C.SERVICE_ACCOUNT}"
    cloud(["projects","add-iam-policy-binding",C.PROJECT,member,"--role=roles/cloudsql.client","--condition=None"])
    cloud(["secrets","add-iam-policy-binding",C.PASSWORD_SECRET,member,"--role=roles/secretmanager.secretAccessor"])
    bucket = describe(["storage","buckets","describe",f"gs://{C.SOURCE_BUCKET}"])
    if bucket:
        if bucket.get("labels",{}).get("homework") != "hw6": raise RuntimeError("Unrecognized artifact bucket")
    else:
        cloud(["storage","buckets","create",f"gs://{C.SOURCE_BUCKET}",f"--location={C.REGION}","--uniform-bucket-level-access","--public-access-prevention"])
        cloud(["storage","buckets","update",f"gs://{C.SOURCE_BUCKET}","--update-labels=course=cs528,homework=hw6"])
    cloud(["storage","buckets","add-iam-policy-binding",f"gs://{C.SOURCE_BUCKET}",member,"--role=roles/storage.objectViewer"])
    condition = f"title=hw6-output-only,expression=resource.name.startsWith('projects/_/buckets/{C.BUCKET}/objects/cs528-hw6/')"
    cloud(["storage","buckets","add-iam-policy-binding",f"gs://{C.BUCKET}",member,"--role=roles/storage.objectCreator",f"--condition={condition}"])


def package_source():
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer,mode="wb",mtime=0) as compressed:
        with tarfile.open(fileobj=compressed,mode="w") as archive:
            for name in SOURCE_FILES:
                data=(ROOT/name).read_bytes()
                info=tarfile.TarInfo(name);info.size=len(data);info.mtime=0;info.mode=0o644
                archive.addfile(info,io.BytesIO(data))
    data=buffer.getvalue();digest=hashlib.sha256(data).hexdigest()
    path=ROOT/"build"/f"source-{digest}.tar.gz";path.parent.mkdir(exist_ok=True);path.write_bytes(data)
    uri=f"gs://{C.SOURCE_BUCKET}/source/{path.name}"
    cloud(["storage","cp",str(path),uri])
    return uri,digest


def cleanup(state_path):
    state=json.loads(state_path.read_text())
    if state.get("project") != C.PROJECT or not re.fullmatch(r"cs528-hw6-[a-z0-9-]+",state.get("vm","")):
        raise RuntimeError("Invalid cleanup state")
    errors=[]
    def attempt(label, action):
        try: action()
        except Exception as exc: errors.append(f"{label}: {exc}")
    def stop_sql():
        sql=sql_status()
        if sql["settings"].get("activationPolicy") != "NEVER":
            cloud(["sql","instances","patch",C.SQL_INSTANCE,"--activation-policy=never"],timeout=900)
    if state.get("sql_start_intent"): attempt("stop SQL",stop_sql)
    def delete_vm():
        vm=describe(["compute","instances","describe",state["vm"],f"--zone={C.ZONE}"])
        check_owned(vm)
        if vm: cloud(["compute","instances","delete",state["vm"],f"--zone={C.ZONE}","--delete-disks=boot"])
    attempt("delete VM",delete_vm)
    def delete_subnet():
        subnet=describe(["compute","networks","subnets","describe",state["vm"],f"--region={C.REGION}"])
        check_owned(subnet)
        if subnet: cloud(["compute","networks","subnets","delete",state["vm"],f"--region={C.REGION}"])
    attempt("delete subnet",delete_subnet)
    def delete_network():
        network=describe(["compute","networks","describe",state["vm"]]);check_owned(network)
        if network: cloud(["compute","networks","delete",state["vm"]])
    attempt("delete network",delete_network)
    evidence={"checked_at":datetime.now(timezone.utc).isoformat(),"errors":errors,"vm_name":state["vm"]}
    try:
        sql=sql_status()
        evidence.update(sql_state=sql["state"],sql_activation_policy=sql["settings"]["activationPolicy"],
            vm_absent=describe(["compute","instances","describe",state["vm"],f"--zone={C.ZONE}"]) is None,
            boot_disk_absent=describe(["compute","disks","describe",state["vm"],f"--zone={C.ZONE}"]) is None,
            subnet_absent=describe(["compute","networks","subnets","describe",state["vm"],f"--region={C.REGION}"]) is None,
            network_absent=describe(["compute","networks","describe",state["vm"]]) is None)
        evidence["verified"]=(evidence["sql_state"]=="STOPPED" and evidence["sql_activation_policy"]=="NEVER"
                              and evidence["vm_absent"] and evidence["boot_disk_absent"] and evidence["subnet_absent"] and evidence["network_absent"] and not errors)
    except Exception as exc: errors.append("verification: "+str(exc));evidence["verified"]=False
    write(state_path.parent/"cleanup.json",evidence)
    if not evidence["verified"]: raise RuntimeError("Cleanup incomplete; see "+str(state_path.parent/"cleanup.json"))
    print("Cleanup verified: SQL STOPPED/NEVER; VM, boot disk, subnet and network absent.",flush=True)


def download_outputs(state, target):
    uri=state["output_uri"]
    manifest=json.loads(cloud(["storage","cat",uri+"done.json"]))
    if manifest.get("source_sha256") != state["source_sha256"] or manifest.get("mode") != "CLOUD_SQL_ON_VM" or manifest.get("cloud_run") != state["run"]:
        raise RuntimeError("Output provenance does not match this VM run")
    required={"country_predictions.csv","income_predictions.csv","summary.txt","metrics.json","migration.json","splits.csv"}
    if set(manifest.get("files",{})) != required: raise RuntimeError("Unexpected output manifest")
    target.mkdir(exist_ok=True)
    for name,digest in manifest["files"].items():
        cloud(["storage","cp",uri+name,str(target/name)])
        if hashlib.sha256((target/name).read_bytes()).hexdigest()!=digest: raise RuntimeError("Downloaded output checksum mismatch")
    write(target/"done.json",manifest)


def print_outputs(state, directory):
    # These are the complete files retrieved from the output bucket.
    for name in ("summary.txt","country_predictions.csv","income_predictions.csv"):
        print(f"\n--- {state['output_uri']}{name} ---",flush=True)
        print((directory/name).read_text(),end="",flush=True)
    write(ROOT/"report"/"latest-run.json",{"directory":str(directory),**state})


def resume(state_path):
    """Recover finished model outputs and cleanup without starting any resources."""
    state=json.loads(state_path.read_text())
    if state.get("project")!=C.PROJECT or not re.fullmatch(r"\d{8}-\d{6}-[a-f0-9]{4}",state.get("run","")):
        raise RuntimeError("Invalid resume state")
    if state.get("vm")!="cs528-hw6-"+state["run"] or state.get("output_uri")!=f"gs://{C.BUCKET}/cs528-hw6/runs/{state['run']}/":
        raise RuntimeError("Unexpected resource names in resume state")
    directory=state_path.parent
    try:
        download_outputs(state,directory)
        print("Existing model outputs downloaded and SHA-256 verified.",flush=True)
    finally:
        cleanup(state_path)
    print_outputs(state,directory)


def run():
    preflight()
    run_id=datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")+"-"+secrets.token_hex(2)
    directory=ROOT/"results"/run_id;directory.mkdir(parents=True)
    state_path=directory/"state.json"
    state={"project":C.PROJECT,"run":run_id,"vm":"cs528-hw6-"+run_id,
           "output_uri":f"gs://{C.BUCKET}/cs528-hw6/runs/{run_id}/","sql_start_intent":False}
    write(state_path,state)
    print("Run state:",state_path,flush=True)
    print("Outputs:",state["output_uri"],flush=True)
    def interrupted(signum, frame): raise KeyboardInterrupt(f"Signal {signum}")
    previous=signal.signal(signal.SIGTERM,interrupted)
    try:
        prepare_identity()
        uri,digest=package_source();state.update(source_uri=uri,source_sha256=digest);write(state_path,state)
        state["sql_start_intent"]=True;write(state_path,state)
        print("Starting preserved Cloud SQL instance...",flush=True)
        cloud(["sql","instances","patch",C.SQL_INSTANCE,"--activation-policy=always"],timeout=900)
        databases=cloud(["sql","databases","list",f"--instance={C.SQL_INSTANCE}"],json_output=True)
        if C.TARGET_DB not in {d["name"] for d in databases}:
            cloud(["sql","databases","create",C.TARGET_DB,f"--instance={C.SQL_INSTANCE}","--charset=utf8mb4","--collation=utf8mb4_bin"])
        cloud(["compute","networks","create",state["vm"],"--subnet-mode=custom",f"--description={C.MARKER}"])
        cloud(["compute","networks","subnets","create",state["vm"],f"--network={state['vm']}",f"--region={C.REGION}","--range=10.66.0.0/24",f"--description={C.MARKER}"])
        metadata=f"hw6-source={uri},hw6-sha256={digest},hw6-run={run_id},hw6-bucket={C.BUCKET}"
        print("Creating e2-standard-2 VM with startup script...",flush=True)
        cloud(["compute","instances","create",state["vm"],f"--zone={C.ZONE}","--machine-type=e2-standard-2",
            "--image-family=debian-12","--image-project=debian-cloud","--boot-disk-size=10GB","--boot-disk-type=pd-standard",
            f"--subnet={state['vm']}",f"--service-account={C.SERVICE_ACCOUNT}","--scopes=cloud-platform",
            "--labels=course=cs528,homework=hw6",f"--description={C.MARKER}",
            f"--metadata={metadata}",f"--metadata-from-file=startup-script={ROOT/'startup.sh'}"])
        vm=describe(["compute","instances","describe",state["vm"],f"--zone={C.ZONE}"])
        write(directory/"vm.json",vm)
        deadline=time.monotonic()+2400
        while time.monotonic()<deadline:
            failed=describe(["storage","objects","describe",state["output_uri"]+"failure.json"])
            if failed: raise RuntimeError("VM startup/training failed; inspect startup.log in "+state["output_uri"])
            done=describe(["storage","objects","describe",state["output_uri"]+"done.json"])
            if done: break
            time.sleep(15)
        else: raise TimeoutError("VM did not produce outputs within 40 minutes")
        download_outputs(state,directory)
        print("All model outputs downloaded and SHA-256 verified.",flush=True)
    finally:
        try:
            serial=cloud(["compute","instances","get-serial-port-output",state["vm"],f"--zone={C.ZONE}"],absent=True)
            if serial: (directory/"serial.log").write_text(serial)
        except Exception as exc: print("Serial log capture unavailable:",exc,flush=True)
        try: cleanup(state_path)
        finally: signal.signal(signal.SIGTERM,previous)
    print_outputs(state,directory)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action",choices=("plan","preflight","run","cleanup","resume"))
    parser.add_argument("--state",type=Path)
    args=parser.parse_args()
    if args.action=="plan":
        print(json.dumps({"project":C.PROJECT,"existing_sql":C.SQL_INSTANCE,"new_database":C.TARGET_DB,
            "formal_run":C.RUN_ID,"vm":"one temporary e2-standard-2 / Debian 12 / 10 GB disk",
            "outputs":f"gs://{C.BUCKET}/cs528-hw6/runs/<run-id>/",
            "cleanup":"Stop SQL, delete temporary VM/boot disk/subnet/network; retain data and output files",
            "failure_recovery":"python3 infra.py cleanup --state results/<run-id>/state.json"},indent=2))
    elif args.action=="preflight": preflight()
    elif args.action=="run": run()
    elif args.action=="resume" and args.state: resume(args.state)
    elif args.state: cleanup(args.state)
    else: parser.error("cleanup/resume requires --state")


if __name__=="__main__": main()
