"""Protect shared Cloud Functions storage when removing only the HW5 source."""
import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import infra


class CleanupSourceTests(unittest.TestCase):
    def descriptor(self):
        source = {"bucket": f"gcf-v2-sources-12345-{infra.C.REGION}",
                  "object": f"{infra.FUNCTION}/function-source.zip", "generation": "98765"}
        return {"name": f"projects/{infra.C.PROJECT_ID}/locations/{infra.C.REGION}/functions/{infra.FUNCTION}",
                "labels": {"homework": "hw5"},
                "buildConfig": {"source": {"storageSource": source},
                                "sourceProvenance": {"resolvedStorageSource": copy.deepcopy(source)}}}

    def test_cleanup_deletes_exact_generation_after_function_and_retains_shared_bucket(self):
        calls = []
        function = self.descriptor()
        def fake(parts, **kwargs):
            calls.append(parts)
            if parts[:3] == ["functions", "describe", infra.FUNCTION]:
                return function
            if parts[:2] == ["projects", "describe"]:
                return {"projectNumber": "12345"}
            if parts[:3] == ["storage", "objects", "describe"]:
                return {"generation": "98765"}
            return None
        with tempfile.TemporaryDirectory() as directory, patch("infra.ROOT", Path(directory)), \
                patch("infra.cloud", side_effect=fake), patch("infra.stop_sql") as stop, \
                patch("infra.status"), contextlib.redirect_stdout(io.StringIO()):
            infra.cleanup()
            stop.assert_called_once()
            cached = json.loads((Path(directory) / "report/evidence/function-before-cleanup.json").read_text())
            self.assertEqual(cached, function)
        source_delete = ["storage", "rm", f"gs://gcf-v2-sources-12345-{infra.C.REGION}/{infra.FUNCTION}/function-source.zip#98765"]
        deletes = [c for c in calls if c[:2] == ["storage", "rm"]]
        self.assertEqual(deletes, [source_delete])
        function_delete = next(i for i, c in enumerate(calls) if c[:2] == ["functions", "delete"])
        self.assertLess(function_delete, calls.index(source_delete))
        self.assertFalse(any(c[:3] == ["sql", "instances", "delete"] for c in calls))

    def test_rejects_other_project_object_or_missing_generation_before_deleting(self):
        for key, value in (("bucket", "another-project-bucket"), ("object", "other-function/function-source.zip"),
                           ("generation", ""), ("generation", "123#456")):
            function = self.descriptor()
            function["buildConfig"]["source"]["storageSource"][key] = value
            with self.subTest(field=key, value=value), tempfile.TemporaryDirectory() as directory, \
                    patch("infra.ROOT", Path(directory)), patch("infra.describe", return_value=function), \
                    patch("infra.cloud", return_value={"projectNumber": "12345"}) as cloud:
                with self.assertRaisesRegex(RuntimeError, "Unexpected function source"):
                    infra.function_cleanup_sources()
                self.assertTrue(all(c.args[0][:2] == ["projects", "describe"] for c in cloud.call_args_list))
                self.assertFalse((Path(directory) / "report/evidence/function-before-cleanup.json").exists())

    def test_retry_uses_saved_descriptor_after_function_has_been_deleted(self):
        with tempfile.TemporaryDirectory() as directory, patch("infra.ROOT", Path(directory)), \
                patch("infra.describe", return_value=None), \
                patch("infra.cloud", return_value={"projectNumber": "12345"}):
            cache = Path(directory) / "report/evidence/function-before-cleanup.json"
            cache.parent.mkdir(parents=True)
            cache.write_text(json.dumps(self.descriptor()))
            self.assertEqual(infra.function_cleanup_sources(), [
                f"gs://gcf-v2-sources-12345-{infra.C.REGION}/{infra.FUNCTION}/function-source.zip#98765"])

    def test_cached_descriptor_cannot_name_an_unrelated_function(self):
        with tempfile.TemporaryDirectory() as directory, patch("infra.ROOT", Path(directory)), \
                patch("infra.describe", return_value=None), patch("infra.cloud") as cloud:
            cache = Path(directory) / "report/evidence/function-before-cleanup.json"
            cache.parent.mkdir(parents=True)
            function = self.descriptor()
            function["name"] += "-unrelated"
            cache.write_text(json.dumps(function))
            with self.assertRaisesRegex(RuntimeError, "different resource"):
                infra.function_cleanup_sources()
            cloud.assert_not_called()


if __name__ == "__main__":
    unittest.main()
