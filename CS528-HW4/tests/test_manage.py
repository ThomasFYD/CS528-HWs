"""Check startup syntax, repeatability, and cloud resource ownership boundaries."""

import contextlib
import io
import json
import subprocess
import unittest
from unittest.mock import Mock, patch

from manage import MARKER, Manager, PREFIX, parser
from startup import build_startup


def manager(action="create", dry_run=False):
    args = [action, "--project=test-project", "--bucket=test-bucket",
            "--account=student@example.edu", "--region=us-central1", "--zone=us-central1-a"]
    if action == "create":
        args += ["--ssh-source=203.0.113.7/32"]
    if dry_run:
        args += ["--dry-run"]
    return Manager(parser().parse_args(args))


class StartupTests(unittest.TestCase):
    def test_each_generated_script_has_valid_bash_syntax(self):
        for role in ("web", "reporter", "client"):
            with self.subTest(role=role):
                script = build_startup(role, "test-project", "test-bucket", "test-topic", "test-sub")
                result = subprocess.run(["bash", "-n"], input=script, text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertLess(len(script.encode()), 256 * 1024)

    def test_build_is_deterministic_and_contains_real_sources(self):
        first = build_startup("web", "p", "b", "t", "s")
        self.assertEqual(first, build_startup("web", "p", "b", "t", "s"))
        self.assertIn("class FileHandler", first)
        self.assertIn("systemctl enable cs528-hw4-web.service", first)
        self.assertIn("User=hw4", first)
        self.assertIn('PROJECT_ID="p"', first)

    def test_environment_injection_is_rejected(self):
        for bad in ('x\nExecStart=/tmp/other', 'x"', 'x\\'):
            with self.assertRaises(ValueError):
                build_startup("web", bad, "bucket", "topic", "subscription")


class ManagerTests(unittest.TestCase):
    def test_create_dry_run_never_runs_gcloud(self):
        m = manager(dry_run=True)
        with patch("manage.subprocess.run") as run, contextlib.redirect_stdout(io.StringIO()) as output:
            m.create()
        run.assert_not_called()
        commands = output.getvalue()
        self.assertEqual(commands.count("gcloud compute instances create"), 3)
        self.assertIn("--address=cs528-hw4-web-ip", commands)
        self.assertIn("--source-ranges=203.0.113.7/32", commands)
        self.assertIn("--no-service-account --no-scopes", commands)
        self.assertNotIn("roles/editor", commands)
        self.assertIn("no cloud resources were changed", commands)
        self.assertNotIn("VM creation finished", commands)
        self.assertNotIn("--boot-disk-name", commands)
        for role in ("web", "reporter"):
            self.assertIn(
                f"--create-disk=name=cs528-hw4-{role}-boot,boot=yes,auto-delete=yes,"
                "image-family=debian-12,image-project=debian-cloud,size=10GB,type=pd-standard",
                commands,
            )
        self.assertIn(
            "--create-disk=name=cs528-hw4-client-boot,boot=yes,auto-delete=yes,"
            "image-family=ubuntu-2404-lts-amd64,image-project=ubuntu-os-cloud,size=10GB,type=pd-standard",
            commands,
        )
        self.assertIn("os-image=ubuntu-2404-lts-amd64", commands)

    def test_old_client_is_rejected_but_ubuntu_client_can_be_reused(self):
        m = manager()
        resource = {"machineType": "machineTypes/e2-small", "labels": {"source": "same-source"},
                    "networkInterfaces": [{"subnetwork": "subnetworks/cs528-hw4-subnet"}]}
        self.assertFalse(m.matches_vm(resource, "client", "same-source"))
        resource["labels"]["os-image"] = "ubuntu-2404-lts-amd64"
        self.assertTrue(m.matches_vm(resource, "client", "same-source"))

    def test_existing_web_and_reporter_can_still_be_reused(self):
        m = manager()
        for role, email in (("web", m.web_sa), ("reporter", m.reporter_sa)):
            with self.subTest(role=role):
                resource = {"machineType": "machineTypes/" + m.machine(role),
                            "labels": {"source": "same-source"}, "serviceAccounts": [{"email": email}],
                            "networkInterfaces": [{"subnetwork": "subnetworks/cs528-hw4-subnet"}]}
                self.assertTrue(m.matches_vm(resource, role, "same-source"))

    def test_delete_client_plan_only_deletes_client_and_boot_disk(self):
        m = manager("delete-client", dry_run=True)
        with patch("manage.subprocess.run") as run, contextlib.redirect_stdout(io.StringIO()) as output:
            m.delete_client()
        run.assert_not_called()
        commands = [line for line in output.getvalue().splitlines() if line.startswith("gcloud ")]
        self.assertEqual(len(commands), 1)
        self.assertIn("compute instances delete cs528-hw4-client", commands[0])
        self.assertIn("--delete-disks=boot", commands[0])

    def test_delete_client_checks_ownership_before_deleting(self):
        m = manager("delete-client")
        with patch.object(m, "describe", return_value={"description": "Other project"}), \
             patch.object(m, "run") as run, self.assertRaises(RuntimeError):
            m.delete_client()
        run.assert_not_called()

    def test_rejects_worldwide_ssh(self):
        m = manager()
        m.args.ssh_source = "0.0.0.0/0"
        with patch.object(m, "run") as run, self.assertRaises(ValueError):
            m.create()
        run.assert_not_called()

    def test_different_zone_region_rejected(self):
        args = parser().parse_args(["build", "--region=us-central1", "--zone=us-east1-b"])
        with self.assertRaises(ValueError):
            Manager(args)

    def test_auth_failure_is_not_treated_as_absent_resource(self):
        m = manager()
        result = subprocess.CompletedProcess([], 1, "", "PERMISSION_DENIED: login needed")
        with patch("manage.subprocess.run", return_value=result), self.assertRaises(RuntimeError):
            m.describe(["compute", "instances", "describe", "cs528-hw4-web"])

    def test_not_found_is_treated_as_absent(self):
        result = subprocess.CompletedProcess([], 1, "", "The resource 'x' was not found")
        with patch("manage.subprocess.run", return_value=result):
            self.assertIsNone(manager().describe(["compute", "instances", "describe", "x"]))

    def test_existing_unrecognized_resource_is_not_reused(self):
        m = manager()
        with patch.object(m, "describe", return_value={"description": "someone else's resource"}), \
             patch.object(m, "run") as run, self.assertRaises(RuntimeError):
            m.ensure(["compute", "networks", "describe", "x"], ["compute", "networks", "create", "x"])
        run.assert_not_called()

    def test_existing_owned_resource_with_different_settings_fails(self):
        m = manager()
        with patch.object(m, "describe", return_value={"description": MARKER}), \
             patch.object(m, "run") as run, self.assertRaises(RuntimeError):
            m.ensure(["compute", "networks", "describe", "x"], ["compute", "networks", "create", "x"], lambda _: False)
        run.assert_not_called()

    def test_delete_refuses_unrecognized_vm(self):
        m = manager("delete")
        with patch.object(m, "describe", return_value={"description": "Other project"}), \
             patch.object(m, "run") as run, self.assertRaises(RuntimeError):
            m.delete()
        run.assert_not_called()

    def test_delete_refuses_changed_boot_disk(self):
        m = manager("delete")
        resource = {"description": MARKER, "labels": {"homework": "hw4"},
                    "name": "cs528-hw4-client", "disks": [{"boot": True, "source": "disks/other"}]}
        with patch.object(m, "describe", return_value=resource), \
             patch.object(m, "run") as run, self.assertRaises(RuntimeError):
            m.delete()
        run.assert_not_called()

    def test_delete_accepts_owned_vm_with_explicitly_named_boot_disk(self):
        m = manager("delete")
        name = "cs528-hw4-client"
        resource = {"description": MARKER, "labels": {"homework": "hw4"},
                    "name": name, "disks": [{"boot": True, "source": f"disks/{name}-boot"}]}
        describe = ["compute", "instances", "describe", name, "--zone=us-central1-a"]
        delete = ["compute", "instances", "delete", name, "--zone=us-central1-a", "--delete-disks=boot"]
        with patch.object(m, "describe", return_value=resource), patch.object(m, "run") as run:
            m.delete_one(describe, delete, vm=True)
        run.assert_called_once_with(delete)

    def test_cleanup_only_deletes_its_compute_resources(self):
        m = manager("delete", dry_run=True)
        with patch("manage.subprocess.run") as run, contextlib.redirect_stdout(io.StringIO()) as output:
            m.delete()
        run.assert_not_called()
        commands = output.getvalue()
        self.assertEqual(commands.count("gcloud compute instances delete"), 3)
        self.assertIn("--delete-disks=boot", commands)
        self.assertIn("gcloud compute addresses delete", commands)
        self.assertNotIn("gcloud storage", commands)
        self.assertNotIn("gcloud pubsub", commands)
        self.assertNotIn("gcloud iam", commands)
        self.assertIn("no cloud resources were changed", commands)
        self.assertNotIn("Cleanup finished", commands)


if __name__ == "__main__":
    unittest.main()
