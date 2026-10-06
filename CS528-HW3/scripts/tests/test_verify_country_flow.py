"""Recheck uses the existing HTTP results; all bucket reads are simulated."""

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import verify_country_flow as flow


class RecheckTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.before = [{"event_id": "old"}]
        self.case = {"name": "iran-get", "country": "Iran", "method": "GET", "path": "/data/0.html", "expected_status": 400}
        result = {**self.case, "passed": True, "curl_exit_code": 0, "actual_status": "400", "body_matches": True}
        self.original = {"run_id": "original-run", "http_cases": [result], "passed": False}
        self.summary_path = self.folder / "summary.json"
        self.summary_path.write_text(json.dumps(self.original))
        (self.folder / "test-cases.json").write_text(json.dumps([self.case]))
        (self.folder / "forbidden-before.jsonl").write_text(json.dumps(self.before[0]) + "\n")
        self.after = self.before + [{
            "event_id": "new", "country": "Iran", "method": "GET", "path": "/data/0.html",
            "event": "forbidden_country", "status": 400,
            "pubsub_message_id": "message", "received_at": "later",
        }]

    def invoke(self, snapshots, wait=0):
        with patch.object(flow, "fetch_log", side_effect=snapshots), \
             patch.object(flow, "run_curl", side_effect=AssertionError("New HTTP request")) as curl, \
             patch.object(flow.time, "sleep"), contextlib.redirect_stdout(io.StringIO()):
            result = flow.recheck_existing(self.folder, wait)
        curl.assert_not_called()
        return result

    def test_recovery_passes_without_overwriting_failed_original(self):
        original_bytes = self.summary_path.read_bytes()
        self.assertEqual(self.invoke([self.before, self.after], wait=5), 0)
        self.assertEqual(self.summary_path.read_bytes(), original_bytes)
        paths = list(self.folder.glob("recheck-*/summary.json"))
        self.assertEqual(len(paths), 1)
        self.assertTrue(json.loads(paths[0].read_text())["passed"])

    def test_absent_delivery_still_fails(self):
        self.assertEqual(self.invoke([self.before]), 1)

    def test_duplicate_persisted_event_still_fails(self):
        self.assertEqual(self.invoke([self.after + self.after[-1:]]), 1)

    def test_wrong_original_http_status_cannot_pass_recheck(self):
        self.original["http_cases"][0]["actual_status"] = "503"
        self.summary_path.write_text(json.dumps(self.original))
        self.assertEqual(self.invoke([self.after]), 1)


if __name__ == "__main__":
    unittest.main()
