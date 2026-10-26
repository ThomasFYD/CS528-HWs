"""Ensure an application update retains resources and restores the SQL guard."""
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import infra


class RefreshVMTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.vms = {}
        for role, machine in (("web", infra.C.WEB_MACHINE), ("reporter", infra.C.REPORTER_MACHINE)):
            self.vms[infra.C.PREFIX + "-" + role] = {
                "labels": {"homework": "hw5"}, "status": "RUNNING",
                "machineType": "zones/test/machineTypes/" + machine,
                "serviceAccounts": [{"email": infra.C.service_account(role)}]}
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.cloud = self.stack.enter_context(patch("infra.cloud", side_effect=self.fake_cloud))
        self.pause = self.stack.enter_context(patch("infra.pause_guard"))
        self.resume = self.stack.enter_context(patch("infra.resume_guard"))
        self.sql = self.stack.enter_context(patch("infra.sql"))
        self.archive = self.stack.enter_context(patch("infra.archive_source",
            return_value=("a" * 64, "gs://test/source.tar.gz")))
        self.wait = self.stack.enter_context(patch("infra.wait_for_startup"))
        self.status = self.stack.enter_context(patch("infra.status"))

    def fake_cloud(self, parts, **kwargs):
        self.calls.append(parts)
        if parts[:3] == ["compute", "instances", "describe"]:
            return self.vms[parts[3]]
        return ""

    def test_update_retains_resources_and_uses_startup_metadata(self):
        infra.refresh_vms()
        self.pause.assert_called_once()
        self.sql.assert_called_once()
        self.resume.assert_called_once()
        self.assertEqual([call.args[0] for call in self.wait.call_args_list], ["web", "reporter"])
        self.assertFalse(any("delete" in call or "ssh" in call for call in self.calls))
        for role in ("web", "reporter"):
            name = infra.C.PREFIX + "-" + role
            changes = [call for call in self.calls if len(call) > 3 and call[3] == name]
            self.assertEqual([call[2] for call in changes],
                             ["describe", "stop", "add-metadata", "add-labels", "start"])
            metadata = next(call for call in changes if call[2] == "add-metadata")
            self.assertIn(f"--metadata-from-file=startup-script={infra.ROOT / 'startup.sh'}", metadata)
            self.assertTrue(any("hw5-source-sha256=" + "a" * 64 in arg for arg in metadata))

    def test_unowned_second_vm_prevents_any_mutation(self):
        self.vms[infra.C.PREFIX + "-reporter"]["labels"] = {"homework": "hw4"}
        with self.assertRaisesRegex(RuntimeError, "not marked HW5"):
            infra.refresh_vms()
        self.pause.assert_not_called()
        self.archive.assert_not_called()
        self.assertTrue(all(call[2] == "describe" for call in self.calls))

    def test_startup_failure_still_resumes_hourly_guard(self):
        self.wait.side_effect = RuntimeError("simulated startup failure")
        with self.assertRaisesRegex(RuntimeError, "startup failure"):
            infra.refresh_vms()
        self.resume.assert_called_once()
        self.status.assert_not_called()
        self.assertFalse(any(call[:4] == ["compute", "instances", "stop", infra.C.PREFIX + "-reporter"]
                             for call in self.calls))


class StartupEvidenceTests(unittest.TestCase):
    def test_old_completion_cannot_satisfy_current_restart(self):
        digest, token = "a" * 64, "b" * 32
        old = (f"HW5 web startup beginning. source={digest} refresh=old\n"
               f"HW5 web startup completed. source={digest} refresh=old\n")
        new = (old + f"HW5 web startup beginning. source={digest} refresh={token}\n"
               f"HW5 web startup completed. source={digest} refresh={token}\n")
        with tempfile.TemporaryDirectory() as directory:
            with patch("infra.ROOT", Path(directory)), patch("infra.cloud", side_effect=[old, new]) as cloud, \
                    patch("infra.time.sleep") as sleep, contextlib.redirect_stdout(io.StringIO()):
                infra.wait_for_startup("web", digest, token)
            self.assertEqual(cloud.call_count, 2)
            sleep.assert_called_once_with(15)
            log = Path(directory) / "report/evidence/web-startup-after-refresh.log"
            self.assertIn(f"refresh={token}", log.read_text())


if __name__ == "__main__":
    unittest.main()
