"""Failed exports and incomplete cleanup must never produce a success status."""

import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import final_evidence as evidence
from manage import Manager, parser


class FinalEvidenceTests(unittest.TestCase):
    def run_check(self, action, responses=None, failure=None, export_failure=None):
        manager = Manager(parser().parse_args(["status", "--project=test-project",
                                              "--account=student@example.edu"]))
        with tempfile.TemporaryDirectory() as temporary, \
                patch.object(evidence, "ROOT", Path(temporary)), \
                patch.object(evidence, "Manager", return_value=manager), \
                patch.object(manager, "describe", side_effect=failure or responses), \
                patch.object(evidence, "export", side_effect=export_failure) as export, \
                patch.object(sys, "argv", ["final_evidence.py", action]), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            status = evidence.main()
            manifest = next(Path(temporary).rglob("manifest.json"))
            return status, json.loads(manifest.read_text()), export.call_count

    def test_all_eleven_absent_is_verified_without_ssh(self):
        status, manifest, exports = self.run_check("verify-cleanup", responses=[None] * 11)
        self.assertEqual(status, 0)
        self.assertTrue(manifest["complete"])
        self.assertEqual(len(manifest["resources"]), 11)
        self.assertEqual(exports, 0)

    def test_remaining_disk_prevents_a_successful_cleanup_claim(self):
        responses = [None] * 11
        responses[1] = {"name": "cs528-hw4-web-boot"}
        status, manifest, exports = self.run_check("verify-cleanup", responses=responses)
        self.assertEqual(status, 1)
        self.assertFalse(manifest["complete"])
        self.assertIn("cs528-hw4-web-boot", manifest["error"])
        self.assertEqual(exports, 0)

    def test_authentication_error_is_not_treated_as_absence(self):
        status, manifest, _ = self.run_check("verify-cleanup", failure=RuntimeError("PERMISSION_DENIED"))
        self.assertEqual(status, 1)
        self.assertFalse(manifest["complete"])
        self.assertIn("PERMISSION_DENIED", manifest["error"])

    def test_failed_ssh_export_returns_failure_so_chained_delete_will_not_run(self):
        failure = subprocess.CalledProcessError(255, ["gcloud", "compute", "ssh"])
        status, manifest, exports = self.run_check("capture", responses=[{"id": "123"}] * 11,
                                                 export_failure=failure)
        self.assertEqual(status, 1)
        self.assertFalse(manifest["complete"])
        self.assertEqual(exports, 1)


if __name__ == "__main__":
    unittest.main()
