"""Create, inspect, or remove the dedicated HW8 experiment resources."""
import argparse
import hashlib
import json
import os
import re
import shlex
import subprocess
from pathlib import Path
from startup import ROOT, build_startup

PREFIX = "cs528-hw8"
MARKER = "Managed by CS528 HW8 manage.py"


def add_config(p):
    p.add_argument("--project", default=os.getenv("HW8_PROJECT", "dazzling-seat-508219-j3"))
    p.add_argument("--account", default=os.getenv("HW8_ACCOUNT", "fangyd@bu.edu"))
    p.add_argument("--bucket", default=os.getenv("HW8_BUCKET", "cs528-hw2-yf-2026"))
    p.add_argument("--region", default="us-central1")
    p.add_argument("--zone-a", default="us-central1-a")
    p.add_argument("--zone-b", default="us-central1-c")
    p.add_argument("--web-sa", help="Defaults to the existing HW4 web identity")
    p.add_argument("--reporter-sa", help="Defaults to the existing HW4 reporter identity")
    p.add_argument("--web-machine", default="f1-micro")
    p.add_argument("--dry-run", action="store_true")


class Manager:
    def __init__(self, args):
        self.args = args
        if args.zone_a == args.zone_b or any(not z.startswith(args.region + "-") for z in (args.zone_a, args.zone_b)):
            raise ValueError("Use two different zones in the same region")
        for value in (args.project, args.bucket, args.region, args.zone_a, args.zone_b):
            if not re.fullmatch(r"[a-zA-Z0-9_.-]+", value):
                raise ValueError("Invalid identifier")
        self.web_sa = args.web_sa or f"cs528-hw4-web-sa@{args.project}.iam.gserviceaccount.com"
        self.reporter_sa = args.reporter_sa or f"cs528-hw4-reporter-sa@{args.project}.iam.gserviceaccount.com"
        self.network, self.subnet = PREFIX + "-network", PREFIX + "-subnet"
        self.topic, self.subscription = PREFIX + "-forbidden", PREFIX + "-forbidden-sub"
        self.backend, self.hc, self.address, self.forwarding = (
            PREFIX + "-backend", PREFIX + "-health", PREFIX + "-ip", PREFIX + "-forwarding")
        self.vms = [(PREFIX + "-web-a", args.zone_a, "web"),
                    (PREFIX + "-web-b", args.zone_b, "web"),
                    (PREFIX + "-reporter", args.zone_a, "reporter")]

    def command(self, parts):
        return ["gcloud", *parts, f"--project={self.args.project}", f"--account={self.args.account}", "--quiet"]

    def run(self, parts, capture=True, timeout=240):
        cmd = self.command(parts)
        if self.args.dry_run:
            print(shlex.join(cmd), flush=True)
            return ""
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode:
            raise RuntimeError(shlex.join(cmd) + "\n" + result.stderr.strip())
        if not capture:
            print(result.stdout.strip() or result.stderr.strip(), flush=True)
        return result.stdout

    def describe(self, parts):
        if self.args.dry_run:
            return None
        result = subprocess.run(self.command([*parts, "--format=json"]),
                                capture_output=True, text=True, timeout=60)
        if result.returncode:
            if "was not found" in result.stderr or "NOT_FOUND:" in result.stderr:
                return None
            raise RuntimeError(result.stderr.strip())
        return json.loads(result.stdout)

    @staticmethod
    def owned(resource, pubsub=False):
        if resource is not None:
            valid = (resource.get("labels", {}).get("managed_by") == PREFIX if pubsub
                     else resource.get("description") == MARKER)
            if not valid:
                raise RuntimeError("Refusing to change unrecognized resource: " + resource.get("name", "unknown"))

    def ensure(self, describe, create, check=lambda _: True, pubsub=False):
        existing = self.describe(describe)
        self.owned(existing, pubsub)
        if existing:
            if not check(existing):
                raise RuntimeError("Existing configuration differs: " + existing.get("name", "unknown"))
            print("Reusing " + existing["name"], flush=True)
        else:
            suffix = f"--labels=managed_by={PREFIX}" if pubsub else f"--description={MARKER}"
            self.run([*create, suffix], capture=False)
        return existing

    def build(self):
        folder = ROOT / "build"
        folder.mkdir(exist_ok=True)
        for role in ("web", "reporter"):
            (folder / f"startup-{role}.sh").write_text(build_startup(
                role, self.args.project, self.args.bucket, self.topic, self.subscription))
        return folder

    def preflight(self):
        for email in (self.web_sa, self.reporter_sa):
            item = self.describe(["iam", "service-accounts", "describe", email])
            if not self.args.dry_run and (not item or item.get("disabled")):
                raise RuntimeError("Required HW4 service identity unavailable: " + email)
        self.run(["storage", "objects", "describe", f"gs://{self.args.bucket}/data/0.html", "--format=value(size)"])
        for zone in (self.args.zone_a, self.args.zone_b):
            self.run(["compute", "machine-types", "describe", self.args.web_machine,
                      f"--zone={zone}", "--format=value(name)"])

    def create(self):
        folder = self.build()
        self.preflight()
        a = self.args
        self.run(["services", "enable", "compute.googleapis.com", "pubsub.googleapis.com", "iap.googleapis.com"], capture=False)
        self.ensure(["pubsub", "topics", "describe", self.topic],
                    ["pubsub", "topics", "create", self.topic], pubsub=True)
        self.ensure(["pubsub", "subscriptions", "describe", self.subscription],
                    ["pubsub", "subscriptions", "create", self.subscription, f"--topic={self.topic}", "--ack-deadline=60"],
                    lambda r: r.get("topic", "").endswith("/" + self.topic) and not r.get("filter") and not r.get("pushConfig"), pubsub=True)
        self.run(["pubsub", "topics", "add-iam-policy-binding", self.topic,
                  f"--member=serviceAccount:{self.web_sa}", "--role=roles/pubsub.publisher"], capture=False)
        self.run(["pubsub", "subscriptions", "add-iam-policy-binding", self.subscription,
                  f"--member=serviceAccount:{self.reporter_sa}", "--role=roles/pubsub.subscriber"], capture=False)
        self.ensure(["compute", "networks", "describe", self.network],
                    ["compute", "networks", "create", self.network, "--subnet-mode=custom"],
                    lambda r: r.get("autoCreateSubnetworks") is False)
        self.ensure(["compute", "networks", "subnets", "describe", self.subnet, f"--region={a.region}"],
                    ["compute", "networks", "subnets", "create", self.subnet, f"--region={a.region}",
                     f"--network={self.network}", "--range=10.88.0.0/24"],
                    lambda r: r.get("ipCidrRange") == "10.88.0.0/24" and r.get("network", "").endswith("/" + self.network))
        for name, ports, source, tag in [(PREFIX + "-http", "8080", "0.0.0.0/0", PREFIX + "-web"),
                                          (PREFIX + "-iap-ssh", "22", "35.235.240.0/20", PREFIX)]:
            self.ensure(["compute", "firewall-rules", "describe", name],
                        ["compute", "firewall-rules", "create", name, f"--network={self.network}",
                         f"--allow=tcp:{ports}", f"--source-ranges={source}", f"--target-tags={tag}"],
                        lambda r, s=source, p=ports, t=tag: r.get("sourceRanges") == [s] and r.get("targetTags") == [t]
                        and r.get("allowed") == [{"IPProtocol": "tcp", "ports": [p]}]
                        and not r.get("disabled") and r.get("network", "").endswith("/" + self.network))
        for name, zone, role in self.vms:
            script = folder / f"startup-{role}.sh"
            digest = hashlib.sha256(script.read_bytes()).hexdigest()[:32]
            machine = a.web_machine if role == "web" else "e2-micro"
            email = self.web_sa if role == "web" else self.reporter_sa
            existing = self.ensure(["compute", "instances", "describe", name, f"--zone={zone}"],
                ["compute", "instances", "create", name, f"--zone={zone}", f"--machine-type={machine}",
                 f"--subnet={self.subnet}", f"--tags={PREFIX},{PREFIX}-{role}",
                 f"--create-disk=name={name}-boot,boot=yes,auto-delete=yes,image-family=debian-12,image-project=debian-cloud,size=10GB,type=pd-standard",
                 f"--metadata-from-file=startup-script={script}", f"--labels=course=cs528,homework=hw8,source={digest}",
                 f"--service-account={email}", "--scopes=cloud-platform"],
                lambda r, sha=digest, m=machine, sa=email: r.get("labels", {}).get("source") == sha
                and r.get("machineType", "").endswith("/" + m)
                and [s["email"] for s in r.get("serviceAccounts", [])] == [sa]
                and r.get("networkInterfaces", [{}])[0].get("subnetwork", "").endswith("/" + self.subnet))
            if existing and existing.get("status") == "TERMINATED":
                self.run(["compute", "instances", "start", name, f"--zone={zone}"], capture=False)
            if role == "web":
                group = name + "-group"
                self.ensure(["compute", "instance-groups", "unmanaged", "describe", group, f"--zone={zone}"],
                            ["compute", "instance-groups", "unmanaged", "create", group, f"--zone={zone}"])
                members = self.run(["compute", "instance-groups", "unmanaged", "list-instances", group,
                                    f"--zone={zone}", "--format=json"])
                names = [x["instance"].rsplit("/", 1)[-1] for x in json.loads(members or "[]")]
                if names and names != [name]:
                    raise RuntimeError("Unexpected instance group membership")
                if not names:
                    self.run(["compute", "instance-groups", "unmanaged", "add-instances", group,
                              f"--zone={zone}", f"--instances={name}"], capture=False)
        self.ensure(["compute", "health-checks", "describe", self.hc, f"--region={a.region}"],
                    ["compute", "health-checks", "create", "http", self.hc, f"--region={a.region}",
                     "--port=8080", "--request-path=/healthz", "--check-interval=2s", "--timeout=1s",
                     "--healthy-threshold=2", "--unhealthy-threshold=2"],
                    lambda r: r.get("type") == "HTTP" and r.get("httpHealthCheck", {}).get("port") == 8080
                    and r["httpHealthCheck"].get("requestPath") == "/healthz"
                    and all(r.get(k) == v for k, v in {"checkIntervalSec": 2, "timeoutSec": 1,
                            "healthyThreshold": 2, "unhealthyThreshold": 2}.items()))
        existing = self.ensure(["compute", "backend-services", "describe", self.backend, f"--region={a.region}"],
                    ["compute", "backend-services", "create", self.backend, f"--region={a.region}",
                     "--protocol=TCP", "--load-balancing-scheme=EXTERNAL", f"--health-checks={self.hc}",
                     f"--health-checks-region={a.region}", "--session-affinity=NONE",
                     "--connection-persistence-on-unhealthy-backends=NEVER_PERSIST"],
                    lambda r: r.get("protocol") == "TCP" and r.get("loadBalancingScheme") == "EXTERNAL"
                    and r.get("sessionAffinity") == "NONE"
                    and r.get("healthChecks", [""])[0].endswith("/" + self.hc))
        backend_groups = [b["group"] for b in (existing or {}).get("backends", [])]
        expected_groups = [f"/zones/{z}/instanceGroups/{n}-group" for n, z, r in self.vms if r == "web"]
        if any(not any(g.endswith(e) for e in expected_groups) for g in backend_groups):
            raise RuntimeError("Unexpected backend group")
        for name, zone, role in self.vms:
            if role == "web" and not any(g.endswith("/" + name + "-group") for g in backend_groups):
                self.run(["compute", "backend-services", "add-backend", self.backend, f"--region={a.region}",
                          f"--instance-group={name}-group", f"--instance-group-zone={zone}"], capture=False)
        self.ensure(["compute", "addresses", "describe", self.address, f"--region={a.region}"],
                    ["compute", "addresses", "create", self.address, f"--region={a.region}", "--network-tier=PREMIUM"],
                    lambda r: r.get("addressType") == "EXTERNAL" and r.get("networkTier") == "PREMIUM")
        self.ensure(["compute", "forwarding-rules", "describe", self.forwarding, f"--region={a.region}"],
                    ["compute", "forwarding-rules", "create", self.forwarding, f"--region={a.region}",
                     "--load-balancing-scheme=EXTERNAL", "--ip-protocol=TCP", "--ports=8080",
                     f"--address={self.address}", f"--backend-service={self.backend}"],
                    lambda r: r.get("backendService", "").endswith("/" + self.backend)
                    and r.get("IPProtocol") == "TCP" and r.get("ports") == ["8080"])
        self.status()

    def health(self):
        return json.loads(self.run(["compute", "backend-services", "get-health", self.backend,
                                   f"--region={self.args.region}", "--format=json"]) or "[]")

    def inventory(self):
        a = self.args
        specs = [("forwarding", ["compute", "forwarding-rules", "describe", self.forwarding, f"--region={a.region}"]),
                 ("backend", ["compute", "backend-services", "describe", self.backend, f"--region={a.region}"]),
                 ("health_check", ["compute", "health-checks", "describe", self.hc, f"--region={a.region}"]),
                 ("address", ["compute", "addresses", "describe", self.address, f"--region={a.region}"])]
        specs.extend((name, ["compute", "instances", "describe", name, f"--zone={zone}"]) for name, zone, _ in self.vms)
        return {name: self.describe(cmd) for name, cmd in specs}

    def status(self):
        if self.args.dry_run:
            return
        result = self.inventory()
        output = ROOT / "results"
        output.mkdir(exist_ok=True)
        (output / "deployment.json").write_text(json.dumps(result, indent=2) + "\n")
        for name, resource in result.items():
            if resource:
                print(name, resource.get("status", ""), resource.get("IPAddress", ""), flush=True)
        print(json.dumps(self.health(), indent=2), flush=True)

    def ssh(self, name, zone, command, timeout=60):
        if (name, zone) not in [(n, z) for n, z, _ in self.vms]:
            raise ValueError("SSH target must be one of the HW8 VMs")
        resource = self.describe(["compute", "instances", "describe", name, f"--zone={zone}"])
        if not resource and not self.args.dry_run:
            raise RuntimeError("HW8 VM does not exist")
        self.owned(resource)
        return self.run(["compute", "ssh", name, f"--zone={zone}", "--tunnel-through-iap",
                         f"--command={command}", "--ssh-flag=-oBatchMode=yes"], timeout=timeout)

    def cleanup_specs(self):
        region = f"--region={self.args.region}"
        specs = []
        for kind, name in [("forwarding-rules", self.forwarding), ("backend-services", self.backend),
                           ("health-checks", self.hc), ("addresses", self.address)]:
            specs.append((["compute", kind, "describe", name, region], ["compute", kind, "delete", name, region], False))
        for name, zone, role in self.vms:
            z = f"--zone={zone}"
            if role == "web":
                specs.append((["compute", "instance-groups", "unmanaged", "describe", name + "-group", z],
                              ["compute", "instance-groups", "unmanaged", "delete", name + "-group", z], False))
            specs.append((["compute", "instances", "describe", name, z],
                          ["compute", "instances", "delete", name, z, "--delete-disks=boot"], False))
        for suffix in ("http", "iap-ssh"):
            specs.append((["compute", "firewall-rules", "describe", PREFIX + "-" + suffix],
                          ["compute", "firewall-rules", "delete", PREFIX + "-" + suffix], False))
        specs.extend([
            (["compute", "networks", "subnets", "describe", self.subnet, region],
             ["compute", "networks", "subnets", "delete", self.subnet, region], False),
            (["compute", "networks", "describe", self.network], ["compute", "networks", "delete", self.network], False),
            (["pubsub", "subscriptions", "describe", self.subscription], ["pubsub", "subscriptions", "delete", self.subscription], True),
            (["pubsub", "topics", "describe", self.topic], ["pubsub", "topics", "delete", self.topic], True)])
        return specs

    def delete(self):
        for desc, command, pubsub in self.cleanup_specs():
            resource = self.describe(desc)
            self.owned(resource, pubsub)
            if resource and desc[:2] == ["compute", "instances"]:
                disks = resource.get("disks", [])
                if len(disks) != 1 or not disks[0].get("boot") or not disks[0].get("source", "").endswith("/" + resource["name"] + "-boot") or resource.get("labels", {}).get("homework") != "hw8":
                    raise RuntimeError("Unexpected VM disk or label; refusing deletion")
            if resource or self.args.dry_run:
                self.run(command, capture=False)
        if not self.args.dry_run:
            remaining = {" ".join(d): self.describe(d) for d, _, _ in self.cleanup_specs()}
            for name, zone, _ in self.vms:
                remaining[name + "-boot"] = self.describe(["compute", "disks", "describe", name + "-boot", f"--zone={zone}"])
            (ROOT / "results").mkdir(exist_ok=True)
            (ROOT / "results/cleanup.json").write_text(json.dumps(remaining, indent=2) + "\n")
            if any(v is not None for v in remaining.values()):
                raise RuntimeError("Cleanup incomplete; inspect results/cleanup.json")
            print("Verified all dedicated HW8 resources absent. HW2 data and HW4 identities retained.")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=("build", "preflight", "create", "status", "delete"))
    add_config(p)
    args = p.parse_args()
    try:
        getattr(Manager(args), args.action)()
    except (RuntimeError, ValueError, OSError, subprocess.TimeoutExpired) as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
