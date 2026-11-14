import argparse
import contextlib
import io
import json
import unittest
from unittest.mock import Mock, patch
from client import file_path, request_once, scheduled_requests
from experiment import health_states
from manage import Manager, MARKER, add_config
from startup import build_startup
from web_server import metadata_zone, validate_zone


class ZoneTests(unittest.TestCase):
    def test_actual_metadata_resource_parsed(self):
        response = Mock()
        response.headers = {"Metadata-Flavor": "Google"}
        response.read.return_value = b"projects/123/zones/us-central1-c"
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        opener = Mock()
        opener.open.return_value = response
        with patch("web_server.build_opener", return_value=opener):
            self.assertEqual(metadata_zone(), "us-central1-c")
        request = opener.open.call_args.args[0]
        self.assertEqual(request.get_header("Metadata-flavor"), "Google")

    def test_header_injection_and_missing_zone_rejected(self):
        for value in ("", "unknown", "us-central1-a\r\nX-Fake: yes", "projects/123/zones/us-central1-c"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_zone(value)


class ClientTests(unittest.TestCase):
    def test_instructor_bucket_and_webdir_conventions(self):
        self.assertEqual(file_path("/bucket", "data", 11999), "/bucket/data/11999.html")
        self.assertEqual(file_path("none", "data", 0), "/data/0.html")
        self.assertEqual(file_path("none", "none", 0), "/0.html")

    def test_refused_connection_recorded_not_fabricated_zone(self):
        conn = Mock()
        conn.connect.side_effect = ConnectionRefusedError("refused")
        with patch("client.http.client.HTTPConnection", return_value=conn):
            result = request_once("localhost", 8080, "/data/0.html")
        self.assertIsNone(result["status"])
        self.assertIsNone(result["zone"])
        self.assertFalse(result["ok"])
        self.assertIn("ConnectionRefusedError", result["error"])
        conn.close.assert_called_once()

    def test_http_denial_is_not_a_transport_failure(self):
        response = Mock()
        response.status = 400
        response.fp = None
        response.getheader.side_effect = lambda key: {"X-Server-Zone": "us-central1-c", "Content-Length": "3"}.get(key)
        response.getheaders.return_value = [("X-Server-Zone", "us-central1-c")]
        response.read.side_effect = [b"no\n", b""]
        conn = Mock()
        conn.getresponse.return_value = response
        conn.sock.getsockname.return_value = ("127.0.0.1", 50001)
        with patch("client.http.client.HTTPConnection", return_value=conn):
            result = request_once("localhost", 8080, "/data/0.html", expected=400)
        self.assertEqual(result["status"], 400)
        self.assertTrue(result["ok"])
        self.assertIsNone(result["error"])

    def test_worker_exception_propagates(self):
        def fail(_): raise ValueError("failure")
        with self.assertRaises(ValueError):
            scheduled_requests(2, .001, fail, lambda _: None)


class InfrastructureTests(unittest.TestCase):
    def manager(self, *extra):
        p = argparse.ArgumentParser()
        add_config(p)
        return Manager(p.parse_args(["--dry-run", *extra]))

    def test_rejects_same_or_different_region_zones(self):
        for args in [("--zone-b", "us-central1-a"), ("--zone-b", "us-east1-b")]:
            with self.assertRaises(ValueError): self.manager(*args)

    def test_refuses_unowned_resources(self):
        with self.assertRaises(RuntimeError): Manager.owned({"name": "other"})
        Manager.owned({"name": "own", "description": MARKER})
        with self.assertRaises(RuntimeError): Manager.owned({"name": "other", "labels": {}}, True)

    def test_web_does_not_restart_after_kill(self):
        web = build_startup("web", "project", "bucket", "topic", "subscription")
        reporter = build_startup("reporter", "project", "bucket", "topic", "subscription")
        self.assertIn("Restart=no\n", web)
        self.assertIn("Restart=on-failure\n", reporter)
        self.assertIn("X-Server-Zone", web)
        self.assertNotIn("--zone=", web)

    def test_plan_has_two_zones_real_health_endpoint_and_single_forward_port(self):
        manager = self.manager()
        with contextlib.redirect_stdout(io.StringIO()) as out:
            manager.create()
        plan = out.getvalue()
        self.assertIn("--zone=us-central1-a", plan)
        self.assertIn("--zone=us-central1-c", plan)
        self.assertIn("--request-path=/healthz", plan)
        self.assertIn("--check-interval=2s", plan)
        self.assertIn("--unhealthy-threshold=2", plan)
        self.assertIn("--ports=8080", plan)
        self.assertIn("--session-affinity=NONE", plan)
        self.assertIn("--source-ranges=35.235.240.0/20", plan)

    def test_delete_refuses_unexpected_attached_disk(self):
        manager = self.manager()
        manager.args.dry_run = False
        vm = {"name": "cs528-hw8-web-a", "description": MARKER,
              "labels": {"homework": "hw8"}, "disks": [{"boot": True, "source": "/disks/valuable"}]}
        with patch.object(manager, "cleanup_specs", return_value=[(["compute", "instances", "describe", vm["name"]], ["delete"], False)]), \
             patch.object(manager, "describe", return_value=vm), patch.object(manager, "run") as run:
            with self.assertRaises(RuntimeError): manager.delete()
            run.assert_not_called()

    def test_health_maps_instance_names(self):
        raw = [{"status": {"healthStatus": [{"instance": "projects/x/zones/z/instances/a", "healthState": "UNHEALTHY"}]}}]
        self.assertEqual(health_states(raw), {"a": "UNHEALTHY"})


if __name__ == "__main__":
    unittest.main()
