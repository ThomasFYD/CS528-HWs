"""Build, create, inspect, or delete this homework's three VMs and dedicated network."""

import argparse
import hashlib
import ipaddress
import json
import os
import re
import shlex
import subprocess

from startup import ROOT, build_startup

PREFIX = "cs528-hw4"
MARKER = "Managed by CS528 HW4 manage.py"
CLIENT_IMAGE = "ubuntu-2404-lts-amd64"


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=("build", "create", "status", "delete", "delete-client"))
    p.add_argument("--project", default=os.getenv("HW4_PROJECT", "dazzling-seat-508219-j3"))
    p.add_argument("--account", default=os.getenv("HW4_ACCOUNT", "fangyd@bu.edu"))
    p.add_argument("--bucket", default=os.getenv("HW4_BUCKET", "cs528-hw2-yf-2026"))
    p.add_argument("--region", default=os.getenv("HW4_REGION", "us-central1"))
    p.add_argument("--zone", default=os.getenv("HW4_ZONE", "us-central1-a"))
    p.add_argument("--topic", default=os.getenv("HW4_TOPIC", "cs528-hw4-forbidden"))
    p.add_argument("--subscription", default=os.getenv("HW4_SUB", "cs528-hw4-forbidden-sub"))
    p.add_argument("--web-sa", default=os.getenv("HW4_WEB_SA"))
    p.add_argument("--reporter-sa", default=os.getenv("HW4_REPORTER_SA"))
    p.add_argument("--web-machine", default="f1-micro")
    p.add_argument("--reporter-machine", default="e2-micro")
    p.add_argument("--client-machine", default="e2-small")
    p.add_argument("--ssh-source", default=os.getenv("HW4_SSH_SOURCE"),
                   help="Your current public IPv4 address followed by /32; required for create")
    p.add_argument("--dry-run", action="store_true", help="Print cloud commands without running them")
    return p


class Manager:
    def __init__(self, args):
        self.args = args
        self.project = args.project
        self.network = PREFIX + "-network"
        self.subnet = PREFIX + "-subnet"
        self.address = PREFIX + "-web-ip"
        self.web_sa = args.web_sa or f"{PREFIX}-web-sa@{args.project}.iam.gserviceaccount.com"
        self.reporter_sa = args.reporter_sa or f"{PREFIX}-reporter-sa@{args.project}.iam.gserviceaccount.com"
        self.scripts = {}
        if not args.zone.startswith(args.region + "-"):
            raise ValueError("The zone must belong to the selected region")
        for value in (args.project, args.bucket, args.topic, args.subscription):
            if not re.fullmatch(r"[a-zA-Z0-9_.-]+", value):
                raise ValueError("Invalid project, bucket, topic, or subscription identifier")

    def command(self, parts):
        return ["gcloud", *parts, f"--project={self.args.project}",
                f"--account={self.args.account}", "--quiet"]

    def run(self, parts, capture=False):
        cmd = self.command(parts)
        if self.args.dry_run:
            print(shlex.join(cmd))
            return "" if capture else None
        result = subprocess.run(cmd, text=True, capture_output=capture, check=True)
        return result.stdout if capture else None

    def describe(self, parts):
        cmd = self.command([*parts, "--format=json"])
        if self.args.dry_run:
            return None
        result = subprocess.run(cmd, text=True, capture_output=True)
        if result.returncode:
            # Auth, network, API, or permission errors must not be mistaken for absence.
            if "was not found" in result.stderr or "NOT_FOUND:" in result.stderr:
                return None
            raise RuntimeError(result.stderr.strip())
        return json.loads(result.stdout)

    @staticmethod
    def check_owned(resource, name):
        if resource and resource.get("description") != MARKER:
            raise RuntimeError(f"Refusing to modify or delete unrecognized existing resource: {name}")

    def build(self):
        output = ROOT / "build"
        output.mkdir(exist_ok=True)
        for role in ("web", "reporter", "client"):
            content = build_startup(role, self.project, self.args.bucket,
                                    self.args.topic, self.args.subscription)
            path = output / f"startup-{role}.sh"
            path.write_text(content)
            self.scripts[role] = path
        print(f"Startup scripts written to {output}")

    def ensure(self, describe_parts, create_parts, expected=None):
        name = create_parts[create_parts.index("create") + 1]
        resource = self.describe(describe_parts)
        self.check_owned(resource, name)
        if resource:
            if expected and not expected(resource):
                raise RuntimeError("Existing resource has different settings: " + name)
            print("Reusing " + name)
        else:
            self.run([*create_parts, f"--description={MARKER}"])
        return resource

    def machine(self, role):
        return getattr(self.args, role + "_machine")

    def matches_vm(self, resource, role, digest):
        email = self.web_sa if role == "web" else self.reporter_sa if role == "reporter" else None
        return (resource.get("machineType", "").endswith("/" + self.machine(role)) and
                resource.get("labels", {}).get("source") == digest and
                [a["email"] for a in resource.get("serviceAccounts", [])] == ([email] if email else []) and
                resource.get("networkInterfaces", [{}])[0].get("subnetwork", "").endswith("/" + self.subnet) and
                # Old Debian clients have the same startup source but cannot run
                # the instructor binary, which requires GLIBC_2.38 or newer.
                (role != "client" or resource.get("labels", {}).get("os-image") == CLIENT_IMAGE))

    def create(self):
        if not self.args.ssh_source:
            raise ValueError("create requires --ssh-source YOUR_PUBLIC_IPV4/32")
        cidr = ipaddress.ip_network(self.args.ssh_source)
        if cidr.version != 4 or cidr.prefixlen != 32:
            raise ValueError("Use one IPv4 address with /32 for --ssh-source")
        self.build()
        # Check identities, object, topic/subscription, and machine definitions first.
        for email in (self.web_sa, self.reporter_sa):
            identity = self.describe(["iam", "service-accounts", "describe", email])
            if not self.args.dry_run and (not identity or identity.get("disabled")):
                raise RuntimeError("Missing or disabled service account: " + email)
        self.run(["storage", "objects", "describe", f"gs://{self.args.bucket}/data/0.html",
                  "--format=value(name)"])
        self.run(["pubsub", "topics", "describe", self.args.topic, "--format=value(name)"])
        sub = self.describe(["pubsub", "subscriptions", "describe", self.args.subscription])
        if not self.args.dry_run and (not sub or
                sub.get("topic") != f"projects/{self.project}/topics/{self.args.topic}" or
                sub.get("pushConfig", {}).get("pushEndpoint") or sub.get("filter") or
                sub.get("bigqueryConfig") or sub.get("cloudStorageConfig")):
            raise RuntimeError("Expected an unfiltered pull subscription attached to the configured topic")
        for machine in sorted({self.machine(role) for role in self.scripts}):
            self.run(["compute", "machine-types", "describe", machine,
                      f"--zone={self.args.zone}", "--format=value(name)"])

        self.ensure(["compute", "networks", "describe", self.network],
                    ["compute", "networks", "create", self.network, "--subnet-mode=custom"],
                    lambda r: r.get("autoCreateSubnetworks") is False)
        self.ensure(["compute", "networks", "subnets", "describe", self.subnet, f"--region={self.args.region}"],
                    ["compute", "networks", "subnets", "create", self.subnet,
                     f"--network={self.network}", f"--region={self.args.region}", "--range=10.84.0.0/24"],
                    lambda r: r.get("ipCidrRange") == "10.84.0.0/24" and
                    r.get("network", "").endswith("/" + self.network))
        for rule, tag, port, source in (
            ("http", PREFIX + "-web", "8080", "0.0.0.0/0"),
            ("ssh", PREFIX, "22", str(cidr)),
        ):
            name = PREFIX + "-" + rule
            self.ensure(["compute", "firewall-rules", "describe", name],
                        ["compute", "firewall-rules", "create", name,
                         f"--network={self.network}", "--direction=INGRESS", "--priority=1000",
                         f"--allow=tcp:{port}", f"--source-ranges={source}", f"--target-tags={tag}"],
                        lambda r, s=source, t=tag, p=port: r.get("sourceRanges") == [s] and
                        r.get("targetTags") == [t] and not r.get("disabled", False) and
                        r.get("network", "").endswith("/" + self.network) and
                        r.get("direction") == "INGRESS" and
                        r.get("allowed") == [{"IPProtocol": "tcp", "ports": [p]}])
        self.ensure(["compute", "addresses", "describe", self.address, f"--region={self.args.region}"],
                    ["compute", "addresses", "create", self.address,
                     f"--region={self.args.region}", "--network-tier=PREMIUM"],
                    lambda r: r.get("addressType") == "EXTERNAL" and r.get("networkTier") == "PREMIUM")
        for role, script in self.scripts.items():
            name = PREFIX + "-" + role
            digest = hashlib.sha256(script.read_bytes()).hexdigest()[:32]
            email = self.web_sa if role == "web" else self.reporter_sa if role == "reporter" else None
            image_family, image_project = ((CLIENT_IMAGE, "ubuntu-os-cloud") if role == "client"
                                           else ("debian-12", "debian-cloud"))
            labels = f"course=cs528,homework=hw4,source={digest}"
            if role == "client":
                labels += f",os-image={image_family}"
            parts = ["compute", "instances", "create", name, f"--zone={self.args.zone}",
                     f"--machine-type={self.machine(role)}", f"--subnet={self.subnet}",
                     (f"--create-disk=name={name}-boot,boot=yes,auto-delete=yes,"
                      f"image-family={image_family},image-project={image_project},size=10GB,type=pd-standard"),
                     f"--tags={PREFIX},{name}", f"--labels={labels}",
                     f"--metadata-from-file=startup-script={script}"]
            parts += [f"--service-account={email}", "--scopes=cloud-platform"] if email else ["--no-service-account", "--no-scopes"]
            if role == "web":
                parts.append(f"--address={self.address}")
            def matches(r, vm_role=role, sha=digest):
                return self.matches_vm(r, vm_role, sha)
            reused = self.ensure(["compute", "instances", "describe", name, f"--zone={self.args.zone}"], parts, matches)
            if reused and reused.get("status") == "TERMINATED":
                self.run(["compute", "instances", "start", name, f"--zone={self.args.zone}"])
        if self.args.dry_run:
            print("Creation plan printed; no cloud resources were changed.")
        else:
            print("VM creation finished. Startup installation may still be running; verify systemd and HTTP before testing.")
        self.status()

    def status(self):
        for role in ("web", "reporter", "client"):
            self.run(["compute", "instances", "describe", PREFIX + "-" + role,
                      f"--zone={self.args.zone}",
                      "--format=yaml(name,status,machineType,networkInterfaces,serviceAccounts)"])

    def delete_one(self, describe_parts, delete_parts, vm=False):
        resource = self.describe(describe_parts)
        self.check_owned(resource, " ".join(describe_parts))
        if resource:
            if vm and resource.get("labels", {}).get("homework") != "hw4":
                raise RuntimeError("VM is missing the expected homework label")
            if vm:
                boot = [d for d in resource.get("disks", []) if d.get("boot")]
                if len(boot) != 1 or not boot[0].get("source", "").endswith("/" + resource["name"] + "-boot"):
                    raise RuntimeError("VM boot disk differs from the one created by this script")
            self.run(delete_parts)
        elif self.args.dry_run:
            self.run(delete_parts)
        else:
            print("Already absent: " + " ".join(describe_parts))

    def delete_client(self):
        name = PREFIX + "-client"
        self.delete_one(["compute", "instances", "describe", name, f"--zone={self.args.zone}"],
                        ["compute", "instances", "delete", name, f"--zone={self.args.zone}", "--delete-disks=boot"], vm=True)
        if self.args.dry_run:
            print("Client deletion plan printed; no cloud resources were changed.")
        else:
            print("Client cleanup finished. Run create to recreate it, then upload the instructor client.")

    def delete(self):
        for role in ("client", "reporter", "web"):
            name = PREFIX + "-" + role
            self.delete_one(["compute", "instances", "describe", name, f"--zone={self.args.zone}"],
                            ["compute", "instances", "delete", name, f"--zone={self.args.zone}", "--delete-disks=boot"], vm=True)
        self.delete_one(["compute", "addresses", "describe", self.address, f"--region={self.args.region}"],
                        ["compute", "addresses", "delete", self.address, f"--region={self.args.region}"])
        for rule in ("http", "ssh"):
            name = PREFIX + "-" + rule
            self.delete_one(["compute", "firewall-rules", "describe", name],
                            ["compute", "firewall-rules", "delete", name])
        self.delete_one(["compute", "networks", "subnets", "describe", self.subnet, f"--region={self.args.region}"],
                        ["compute", "networks", "subnets", "delete", self.subnet, f"--region={self.args.region}"])
        self.delete_one(["compute", "networks", "describe", self.network],
                        ["compute", "networks", "delete", self.network])
        if self.args.dry_run:
            print("Deletion plan printed; no cloud resources were changed.")
        else:
            print("Cleanup finished; service accounts, Pub/Sub, the HW2 bucket, and local files are retained.")


def main():
    args = parser().parse_args()
    try:
        getattr(Manager(args), args.action.replace("-", "_"))()
    except (ValueError, RuntimeError, subprocess.CalledProcessError, FileNotFoundError) as exc:
        raise SystemExit(f"ERROR: {exc}\nNo automatic rollback was performed; inspect existing resources before retrying.") from exc


if __name__ == "__main__":
    main()
