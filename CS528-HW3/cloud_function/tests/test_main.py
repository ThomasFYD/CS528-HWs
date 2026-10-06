"""HTTP contract checks using real Functions Framework and simulated storage.

Run: python -m unittest discover -s tests -v
No Google credentials or cloud requests are used by these tests.
"""

import contextlib
import io
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

import functions_framework
from google.api_core.exceptions import Forbidden, NotFound


class HTTPContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = functions_framework.create_app(
            target="get_file",
            source=str(Path(__file__).resolve().parents[1] / "main.py"),
        )
        cls.app.testing = True
        # Obtain the module actually loaded by the Functions Framework.
        import sys
        cls.module = sys.modules["main"]

    def setUp(self):
        self.client = self.app.test_client()
        self.bucket = Mock()
        self.blob = self.bucket.blob.return_value
        self.blob.content_type = "text/html"
        self.blob.download_as_bytes.return_value = b"<html>original bytes</html>"
        self.patcher = patch.object(self.module, "get_bucket", return_value=self.bucket)
        self.get_bucket = self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.publisher = Mock()
        self.publisher.topic_path.return_value = "projects/test/topics/forbidden"
        self.publisher.publish.return_value.result.return_value = "message-123"
        publisher_patch = patch.object(self.module, "get_publisher", return_value=self.publisher)
        publisher_patch.start()
        self.addCleanup(publisher_patch.stop)

    def test_instructor_bucket_path_returns_original_file_bytes(self):
        response = self.client.get(
            "/cs528-hw2-yf-2026/data/8471.html", headers={"X-country": "Cabo Verde"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b"<html>original bytes</html>")
        self.assertEqual(response.mimetype, "text/html")
        self.bucket.blob.assert_called_once_with("data/8471.html")

    def test_direct_object_path(self):
        response = self.client.get("/data/0.html")
        self.assertEqual(response.status_code, 200)
        self.bucket.blob.assert_called_once_with("data/0.html")

    def test_post_reads_filename_from_json(self):
        response = self.client.post("/", json={"filename": "data/0.html"})
        self.assertEqual(response.status_code, 200)
        self.bucket.blob.assert_called_once_with("data/0.html")

    def test_post_accepts_bucket_prefixed_filename(self):
        response = self.client.post(
            "/", json={"filename": "cs528-hw2-yf-2026/data/0.html"}
        )
        self.assertEqual(response.status_code, 200)
        self.bucket.blob.assert_called_once_with("data/0.html")

    def test_missing_object_generates_plain_and_structured_logs(self):
        self.blob.download_as_bytes.side_effect = NotFound("Missing")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            response = self.client.get(
                "/data/missing.html", headers={"X-country": "Cabo Verde"}
            )
        self.assertEqual(response.status_code, 404)
        lines = output.getvalue().splitlines()
        self.assertTrue(lines[0].startswith("404 file_not_found:"))
        entry = json.loads(lines[1])
        self.assertEqual(entry["severity"], "ERROR")
        self.assertEqual(entry["object_name"], "data/missing.html")
        self.assertEqual(entry["country"], "Cabo Verde")
        self.assertEqual(entry["status"], 404)

    def test_all_eight_other_methods_reach_501_and_log(self):
        for method in ("PUT", "DELETE", "HEAD", "CONNECT", "OPTIONS", "TRACE", "PATCH", "CUSTOM"):
            with self.subTest(method=method):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    response = self.client.open("/data/0.html", method=method)
                self.assertEqual(response.status_code, 501)
                lines = output.getvalue().splitlines()
                self.assertTrue(lines[0].startswith("501 unsupported_method:"))
                entry = json.loads(lines[1])
                self.assertEqual(entry["method"], method)
                self.assertEqual(entry["status"], 501)
                if method == "HEAD":
                    self.assertEqual(response.data, b"")
        self.get_bucket.assert_not_called()

    def test_invalid_json_payloads_return_400_without_storage_access(self):
        for payload in (None, [], {}, {"filename": 42}, {"filename": ""}):
            with self.subTest(payload=payload), contextlib.redirect_stdout(io.StringIO()):
                response = self.client.post("/", json=payload)
                self.assertEqual(response.status_code, 400)
        self.get_bucket.assert_not_called()

    def test_storage_denial_is_500_not_404(self):
        self.blob.download_as_bytes.side_effect = Forbidden("Denied")
        with contextlib.redirect_stdout(io.StringIO()):
            response = self.client.get("/data/0.html")
        self.assertEqual(response.status_code, 500)

    def test_log_prefix_is_not_served(self):
        with contextlib.redirect_stdout(io.StringIO()):
            response = self.client.get("/hw3-logs/forbidden-requests.jsonl")
        self.assertEqual(response.status_code, 404)
        self.get_bucket.assert_not_called()

    def test_html_type_is_inferred_if_blob_metadata_is_unset(self):
        self.blob.content_type = None
        response = self.client.get("/data/0.html")
        self.assertEqual(response.mimetype, "text/html")

    def test_all_nine_countries_publish_then_return_400(self):
        for country in self.module.FORBIDDEN_COUNTRIES:
            with self.subTest(country=country), contextlib.redirect_stdout(io.StringIO()):
                self.publisher.reset_mock()
                response = self.client.get("/data/0.html", headers={"X-country": country})
                self.assertEqual(response.status_code, 400)
                self.publisher.publish.assert_called_once()
                args, kwargs = self.publisher.publish.call_args
                event = json.loads(args[1])
                self.assertEqual(event["country"], country)
                self.assertEqual(event["status"], 400)
                self.assertEqual(kwargs["event_id"], event["event_id"])
                self.publisher.publish.return_value.result.assert_called_once_with(timeout=15)
        self.get_bucket.assert_not_called()

    def test_country_normalization_and_client_country_aliases(self):
        for header, canonical in (
            ("  nOrTh   kOrEa  ", "North Korea"),
            ("Korea, Democratic People's Republic of", "North Korea"),
            ("Iran, Islamic Republic of", "Iran"),
            ("Syrian Arab Republic", "Syria"),
        ):
            with self.subTest(header=header), contextlib.redirect_stdout(io.StringIO()):
                response = self.client.get("/data/0.html", headers={"X-country": header})
                self.assertEqual(response.status_code, 400)
                event = json.loads(self.publisher.publish.call_args.args[1])
                self.assertEqual(event["country"], canonical)

    def test_similar_allowed_names_are_not_blocked(self):
        for country in ("Cabo Verde", "South Korea", "Korea, Republic of", "South Sudan", ""):
            with self.subTest(country=country):
                response = self.client.get("/data/0.html", headers={"X-country": country})
                self.assertEqual(response.status_code, 200)
        self.publisher.publish.assert_not_called()

    def test_forbidden_post_is_blocked_before_reading_file(self):
        with contextlib.redirect_stdout(io.StringIO()):
            response = self.client.post(
                "/", json={"filename": "data/0.html"}, headers={"X-country": "Cuba"},
            )
        self.assertEqual(response.status_code, 400)
        event = json.loads(self.publisher.publish.call_args.args[1])
        self.assertEqual(event["method"], "POST")
        self.get_bucket.assert_not_called()

    def test_publication_failure_does_not_serve_file_or_claim_delivery(self):
        self.publisher.publish.return_value.result.side_effect = TimeoutError("timeout")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            response = self.client.get("/data/0.html", headers={"X-country": "Iran"})
        self.assertEqual(response.status_code, 503)
        self.get_bucket.assert_not_called()
        entry = json.loads(output.getvalue().splitlines()[1])
        self.assertEqual(entry["event"], "pubsub_publish_failed")

    def test_unsupported_method_keeps_501_even_with_forbidden_country(self):
        with contextlib.redirect_stdout(io.StringIO()):
            response = self.client.put("/data/0.html", headers={"X-country": "Iran"})
        self.assertEqual(response.status_code, 501)
        self.publisher.publish.assert_not_called()

    def test_400_has_both_log_formats_and_pubsub_correlation(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            response = self.client.get("/data/0.html", headers={"X-country": "Iraq"})
        self.assertEqual(response.status_code, 400)
        lines = output.getvalue().splitlines()
        self.assertTrue(lines[0].startswith("400 forbidden_country:"))
        entry = json.loads(lines[1])
        event = json.loads(self.publisher.publish.call_args.args[1])
        self.assertEqual(entry["event_id"], event["event_id"])
        self.assertEqual(entry["pubsub_message_id"], "message-123")


if __name__ == "__main__":
    unittest.main()
