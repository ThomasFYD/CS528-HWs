"""Exercise real HTTP parsing/wire responses with fake GCP dependencies."""

import contextlib
import io
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from reporter import process_message
from web_server import Application, COUNTRIES, FileHandler, MissingObject


class Backend:
    def __init__(self):
        self.reads, self.logs, self.events = [], [], []
        self.read_error = self.publish_error = self.log_error = None

    def read(self, name):
        self.reads.append(name)
        if self.read_error:
            raise self.read_error
        if name != "data/0.html":
            raise MissingObject(name)
        return b"<html>original bytes\x00\xff</html>", "text/html"

    def log(self, entry, severity):
        if self.log_error:
            raise self.log_error
        self.logs.append((severity, entry))

    def publish(self, event):
        if self.publish_error:
            raise self.publish_error
        self.events.append(event)
        return "message-1"


class FakeSocket:
    def __init__(self, request):
        self.input, self.output = io.BytesIO(request), bytearray()

    def makefile(self, *args, **kwargs):
        return self.input

    def sendall(self, data):
        self.output.extend(data)


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.backend = Backend()
        self.app = Application("test-bucket", self.backend)
        self.stdout = io.StringIO()
        self.capture = contextlib.redirect_stdout(self.stdout)
        self.capture.__enter__()
        self.addCleanup(self.capture.__exit__, None, None, None)

    def raw(self, request):
        sock = FakeSocket(request)
        FileHandler(sock, ("127.0.0.1", 12345), SimpleNamespace(application=self.app))
        head, body = bytes(sock.output).split(b"\r\n\r\n", 1)
        return int(head.split(b" ", 2)[1]), head, body

    def request(self, method="GET", path="/data/0.html", body=b"", country=None):
        headers = f"{method} {path} HTTP/1.1\r\nHost: localhost\r\n"
        if country:
            headers += f"X-country: {country}\r\n"
        if method == "POST":
            headers += f"Content-Type: application/json\r\nContent-Length: {len(body)}\r\n"
        return self.raw(headers.encode() + b"\r\n" + body)

    def test_get_returns_exact_bytes_and_content_length(self):
        status, headers, data = self.request()
        self.assertEqual(status, 200)
        self.assertEqual(data, b"<html>original bytes\x00\xff</html>")
        self.assertIn(f"Content-Length: {len(data)}".encode(), headers)
        self.assertIn(b"Connection: close", headers)
        self.assertEqual(self.backend.logs, [])

    def test_get_bucket_prefix_and_query(self):
        self.assertEqual(self.request(path="/test-bucket/data/0.html?x=1")[0], 200)
        self.assertEqual(self.backend.reads, ["data/0.html"])

    def test_percent_encoded_get(self):
        self.assertEqual(self.request(path="/data/%30.html")[0], 200)

    def test_post_returns_file_from_payload_not_url(self):
        status, _, data = self.request("POST", "/anything", b'{"filename":"/test-bucket/data/0.html"}')
        self.assertEqual(status, 200)
        self.assertEqual(data, self.backend.read("data/0.html")[0])

    def test_missing_object_logs_warning(self):
        self.assertEqual(self.request(path="/data/missing.html")[0], 404)
        severity, entry = self.backend.logs[0]
        self.assertEqual((severity, entry["event"], entry["status"]), ("WARNING", "file_not_found", 404))

    def test_other_prefix_does_not_read_storage(self):
        self.assertEqual(self.request(path="/hw3-logs/private.jsonl")[0], 404)
        self.assertEqual(self.backend.reads, [])

    def test_all_seven_unsupported_methods(self):
        for method in ("PUT", "DELETE", "HEAD", "CONNECT", "OPTIONS", "TRACE", "PATCH"):
            with self.subTest(method=method):
                status, _, body = self.request(method, "localhost:443" if method == "CONNECT" else "/data/0.html")
                self.assertEqual(status, 501)
                self.assertEqual(self.backend.logs[-1][0], "ERROR")
                self.assertEqual(self.backend.logs[-1][1]["method"], method)
                self.assertEqual(body, b"" if method == "HEAD" else b"HTTP method not implemented.\n")
        self.assertEqual(self.backend.reads, [])

    def test_extension_method_is_logged_501(self):
        self.assertEqual(self.request("PROPFIND")[0], 501)
        self.assertEqual(self.backend.logs[-1][1]["method"], "PROPFIND")

    def test_all_nine_banned_countries_and_aliases(self):
        for country in COUNTRIES:
            with self.subTest(country=country):
                self.assertEqual(self.request(country=country)[0], 400)
                self.assertEqual(self.backend.logs[-1][0], "CRITICAL")
                self.assertEqual(self.backend.events[-1]["event_id"], self.backend.logs[-1][1]["event_id"])
        self.assertEqual(self.backend.reads, [])

    def test_allowed_country_not_matched_by_substring(self):
        for country in ("South Sudan", "South Korea", "Cabo Verde"):
            self.assertEqual(self.request(country=country)[0], 200)
        self.assertEqual(self.backend.events, [])

    def test_country_whitespace_and_post(self):
        self.assertEqual(self.request("POST", body=b'{"filename":"data/0.html"}', country="  NORTH   KOREA  ")[0], 400)
        self.assertEqual(self.backend.events[0]["country"], "North Korea")

    def test_method_check_precedes_country(self):
        self.assertEqual(self.request("PUT", country="Iran")[0], 501)
        self.assertEqual(self.backend.events, [])

    def test_publish_failure_fails_closed_and_still_logs_critical(self):
        self.backend.publish_error = TimeoutError()
        self.assertEqual(self.request(country="Iran")[0], 503)
        self.assertEqual([s for s, _ in self.backend.logs], ["CRITICAL", "ERROR"])
        self.assertEqual(self.backend.reads, [])

    def test_storage_permission_failure_is_not_a_404(self):
        self.backend.read_error = PermissionError()
        self.assertEqual(self.request()[0], 500)
        self.assertEqual(self.backend.logs[-1][1]["event"], "storage_error")

    def test_logging_failure_is_visible_locally(self):
        self.backend.log_error = RuntimeError()
        self.assertEqual(self.request("DELETE")[0], 501)
        self.assertIn("cloud_logging_failed", self.stdout.getvalue())

    def test_invalid_json_and_filename(self):
        for data in (b"", b"{", b"[]", b"null", b'{"filename":1}', b'{"filename":""}'):
            with self.subTest(data=data):
                self.assertEqual(self.request("POST", body=data)[0], 400)

    def test_rejects_ambiguous_oversized_or_incomplete_post(self):
        for headers, body in (
            ("", b""), ("Content-Length: -1\r\n", b""),
            ("Content-Length: 65537\r\n", b""),
            ("Content-Length: 2\r\nContent-Length: 2\r\n", b"{}"),
            ("Transfer-Encoding: chunked\r\n", b"0\r\n\r\n"),
            ("Content-Length: 10\r\n", b"{}"),
        ):
            with self.subTest(headers=headers):
                request = f"POST / HTTP/1.1\r\nHost: localhost\r\n{headers}\r\n".encode() + body
                self.assertEqual(self.raw(request)[0], 400)


class ReporterTests(unittest.TestCase):
    def setUp(self):
        self.received = SimpleNamespace(ack_id="ack-1", message=SimpleNamespace(
            message_id="message-1", data=json.dumps({"event_id": "event-1", "event": "forbidden_country",
                                                     "country": "Iran"}).encode()))

    def test_prints_and_flushes_before_acknowledging(self):
        client = Mock()
        calls = []
        client.acknowledge.side_effect = lambda **kwargs: calls.append("ack")
        with patch("reporter.print", side_effect=lambda *a, **kw: calls.append((a, kw))):
            self.assertTrue(process_message(client, "subscription-1", self.received))
        self.assertTrue(calls[0][0][0].startswith("FORBIDDEN "))
        self.assertTrue(calls[0][1]["flush"])
        self.assertEqual(calls[1], "ack")
        client.acknowledge.assert_called_once_with(request={"subscription": "subscription-1", "ack_ids": ["ack-1"]}, timeout=20)

    def test_bad_message_is_not_acknowledged(self):
        client = Mock()
        self.received.message.data = b"bad json"
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(process_message(client, "sub", self.received))
        client.acknowledge.assert_not_called()

    def test_output_failure_is_not_acknowledged(self):
        client = Mock()
        with patch("reporter.print", side_effect=[OSError(), None]):
            self.assertFalse(process_message(client, "sub", self.received))
        client.acknowledge.assert_not_called()

    def test_ack_failure_returns_retry(self):
        client = Mock()
        client.acknowledge.side_effect = TimeoutError()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(process_message(client, "sub", self.received))


if __name__ == "__main__":
    unittest.main()
