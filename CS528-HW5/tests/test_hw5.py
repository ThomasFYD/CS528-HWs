import contextlib
from datetime import datetime
import hashlib
import http.client
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch, Mock

from sqlalchemy import create_engine, event, inspect, select
from analysis import summarize
from database import Database
from hw4_service import Application, MissingObject
import infra
from request_data import RequestClock, extract_headers, route
from web_server import FileServer, TimedBackend

ROOT = Path(__file__).resolve().parents[1]
HEADERS = {"X-country": "Austria", "X-client-IP": "175.241.56.50", "X-gender": "Male",
           "X-age": "76+", "X-income": "250k+", "X-time": "2026-10-20 01:00:00"}


class MemoryCloud:
    def __init__(self):
        self.events, self.reads, self.logs = [], [], []
        self.publish_fails = False

    def read(self, name):
        self.reads.append(name)
        if name != "data/0.html":
            raise MissingObject(name)
        return b"<p>HW5 test</p>\n", "text/html"

    def publish(self, event):
        if self.publish_fails:
            raise TimeoutError("simulated")
        self.events.append(event)
        return "test-id"

    def log(self, record, severity):
        self.logs.append((record, severity))


class DatabaseCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = create_engine("sqlite:///" + str(Path(self.temp.name) / "test.db"),
                                    connect_args={"check_same_thread": False, "timeout": 30})

        @event.listens_for(self.engine, "connect")
        def foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

        self.db = Database(self.engine)
        self.db.setup()

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def record(self, **headers):
        return extract_headers({**HEADERS, **headers}, "127.0.0.1", "GET",
                               "/__runs/test/data/0.html", b"", "bucket", RequestClock())[0]

    def test_schema_has_primary_keys_and_exact_error_columns(self):
        inspector = inspect(self.engine)
        for name in ("requests", "failed_requests", "request_timings"):
            self.assertTrue(inspector.get_pk_constraint(name)["constrained_columns"])
        self.assertEqual(set(self.db.errors.columns.keys()), {"request_time", "requested_file", "error_code"})

    def test_setup_reuses_data(self):
        record = self.record()
        self.db.save_request(record, 200)
        self.assertEqual(self.db.setup()["created"], [])
        self.assertEqual(self.db.counts()["requests"], 1)

    def test_failure_writes_both_tables(self):
        record = self.record()
        self.db.save_request(record, 404)
        snapshot = self.db.snapshot("test")
        self.assertEqual(len(snapshot["requests"]), 1)
        self.assertEqual(snapshot["failed_requests"][0]["error_code"], 404)

    def test_error_insert_failure_rolls_back_request(self):
        @event.listens_for(self.engine, "before_cursor_execute")
        def fail_error_insert(conn, cursor, statement, parameters, context, executemany):
            if statement.startswith("INSERT INTO failed_requests"):
                raise RuntimeError("simulated failed second insert")
        with self.assertRaises(RuntimeError):
            self.db.save_request(self.record(), 404)
        self.assertEqual(self.db.counts()["requests"], 0)

    def test_client_groups_and_time_are_not_reinterpreted(self):
        record = self.record()
        self.assertEqual(record["age"], "76+")
        self.assertEqual(record["income"], "250k+")
        self.assertEqual(record["client_time"], "2026-10-20 01:00:00")
        self.assertEqual(record["time_of_day"], "01:00:00")
        self.assertNotEqual(record["request_time"], datetime(2026, 10, 20, 1))

    def test_missing_or_invalid_headers_remain_missing(self):
        record, _ = extract_headers({"X-time": "bad"}, "127.0.0.1", "GET", "/data/0.html", b"", "bucket", RequestClock())
        self.assertIsNone(record["age"])
        self.assertEqual(record["client_time"], "bad")
        self.assertIsNone(record["time_of_day"])
        self.assertEqual(record["client_ip"], "127.0.0.1")

    def test_header_names_are_case_insensitive(self):
        record, _ = extract_headers({k.upper(): v for k, v in HEADERS.items()}, "127.0.0.1", "GET", "/data/0.html", b"", "bucket", RequestClock())
        self.assertEqual(record["client_ip"], HEADERS["X-client-IP"])

    def test_clock_handles_threads_and_backward_wall_clock(self):
        clock = RequestClock(datetime(2099, 1, 1))
        with ThreadPoolExecutor(max_workers=8) as pool:
            times = list(pool.map(lambda _: clock.next(), range(200)))
        self.assertEqual(len(set(times)), 200)
        self.assertGreater(min(times), datetime(2099, 1, 1))

    def test_post_filename_and_run_are_separate(self):
        record, effective = extract_headers(HEADERS, "127.0.0.1", "POST", "/__runs/abc/",
            b'{"filename":"bucket/data/0.html"}', "bucket", RequestClock())
        self.assertEqual(record["run_id"], "abc")
        self.assertEqual(record["requested_file"], "data/0.html")
        self.assertEqual(effective, "/")


class HttpTests(DatabaseCase):
    def setUp(self):
        super().setUp()
        self.cloud = MemoryCloud()
        self.app = Application("bucket", TimedBackend(self.cloud))
        self.app.log = lambda severity, entry: self.cloud.log(entry, severity)
        self.server = FileServer(("127.0.0.1", 0), self.app, self.db)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        super().tearDown()

    def request(self, method="GET", filename="data/0.html", headers=None, body=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        connection.request(method, "/__runs/test/" + filename, body=body,
                           headers=HEADERS if headers is None else headers)
        response = connection.getresponse()
        result = response.status, response.read()
        connection.close()
        return result

    def settle(self):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            counts = self.db.counts("test")
            if counts["requests"] == counts["request_timings"]:
                return self.db.snapshot("test")
            time.sleep(0.01)
        self.fail("timings never completed")

    def test_success_commits_metadata_and_timing(self):
        self.assertEqual(self.request(), (200, b"<p>HW5 test</p>\n"))
        snapshot = self.settle()
        self.assertEqual(len(snapshot["requests"]), 1)
        self.assertFalse(snapshot["failed_requests"])
        self.assertTrue(snapshot["request_timings"][0]["response_sent"])

    def test_missing_file_is_logged(self):
        self.assertEqual(self.request(filename="data/missing.html")[0], 404)
        snapshot = self.settle()
        self.assertEqual(snapshot["failed_requests"][0]["error_code"], 404)
        self.assertTrue(snapshot["request_timings"][0]["storage_attempted"])

    def test_banned_request_preserves_reporter_event(self):
        self.assertEqual(self.request(headers={**HEADERS, "X-country": "Iran"})[0], 400)
        snapshot = self.settle()
        self.assertTrue(snapshot["requests"][0]["is_banned"])
        self.assertEqual(len(self.cloud.events), 1)
        self.assertEqual(self.cloud.reads, [])
        self.assertFalse(snapshot["request_timings"][0]["storage_attempted"])

    def test_pubsub_failure_does_not_serve_file(self):
        self.cloud.publish_fails = True
        self.assertEqual(self.request(headers={**HEADERS, "X-country": "Iran"})[0], 503)
        self.assertEqual(self.settle()["failed_requests"][0]["error_code"], 503)
        self.assertFalse(self.cloud.reads)

    def test_unsupported_method_is_recorded(self):
        self.assertEqual(self.request(method="PATCH")[0], 501)
        self.assertEqual(self.settle()["failed_requests"][0]["error_code"], 501)

    def test_head_has_no_response_body(self):
        self.assertEqual(self.request(method="HEAD"), (501, b""))

    def test_invalid_post_is_recorded(self):
        self.assertEqual(self.request(method="POST", body=b"bad-json")[0], 400)
        self.assertEqual(self.settle()["failed_requests"][0]["error_code"], 400)

    def test_valid_post_keeps_original_behavior(self):
        self.assertEqual(self.request(method="POST", filename="", body=b'{"filename":"data/0.html"}')[0], 200)
        self.assertEqual(self.settle()["requests"][0]["requested_file"], "data/0.html")

    def test_database_outage_cannot_return_success(self):
        with patch.object(self.db, "save_request", side_effect=RuntimeError("offline")):
            self.assertEqual(self.request()[0], 503)
        self.assertEqual(self.db.counts()["requests"], 0)
        self.assertTrue(any(entry[0]["event"] == "database_write_failed" for entry in self.cloud.logs))

    def test_concurrent_clients_do_not_lose_rows(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            replies = list(pool.map(lambda _: self.request(), range(20)))
        self.assertTrue(all(status == 200 for status, body in replies))
        snapshot = self.settle()
        self.assertEqual(len(snapshot["requests"]), 20)
        self.assertEqual(len({row["request_time"] for row in snapshot["requests"]}), 20)
        summary = summarize(snapshot, expected=20)
        self.assertTrue(summary["integrity"]["complete"])
        self.assertEqual(summary["most_frequent_age_groups"], [{"group": "76+", "requests": 20}])

    def test_statistics_detect_missing_error_and_timing_rows(self):
        self.request(filename="data/missing.html")
        snapshot = self.settle()
        snapshot["failed_requests"] = []
        snapshot["request_timings"] = []
        integrity = summarize(snapshot, expected=1)["integrity"]
        self.assertFalse(integrity["complete"])
        self.assertFalse(integrity["error_rows_match_exactly"])
        self.assertFalse(integrity["timing_rows_complete"])


class GuardAndInfrastructureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("hw5_guard", ROOT / "guard" / "main.py")
        cls.guard = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.guard)

    def guard_call(self, policy="ALWAYS", state="RUNNABLE"):
        session = Mock()
        session.get.return_value.json.return_value = {"state": state, "settings": {"activationPolicy": policy}}
        session.patch.return_value.json.return_value = {"name": "operation"}
        with patch.dict("os.environ", {"PROJECT_ID": "test-project", "SQL_INSTANCE": "test-instance"}):
            result = self.guard.stop_database(Mock(method="POST"), session)
        return result, session

    def test_guard_stops_running_sql(self):
        result, session = self.guard_call()
        self.assertEqual(result[0]["action"], "stop_requested")
        self.assertEqual(session.patch.call_args.kwargs["json"], {"settings": {"activationPolicy": "NEVER"}})

    def test_guard_does_not_restart_stopped_sql(self):
        result, session = self.guard_call("NEVER")
        self.assertEqual(result[0]["action"], "already_stopped")
        session.patch.assert_not_called()

    def test_guard_retries_transitional_instance(self):
        result, session = self.guard_call(state="MAINTENANCE")
        self.assertEqual(result[1], 503)
        session.patch.assert_not_called()

    def test_unowned_resource_is_rejected(self):
        with self.assertRaises(RuntimeError):
            infra.owned({"labels": {"homework": "hw4"}}, "existing-vm")

    def test_permission_error_is_not_treated_as_absent(self):
        with patch("infra.subprocess.run", return_value=Mock(returncode=1, stdout="", stderr="PERMISSION_DENIED")):
            with self.assertRaises(RuntimeError):
                infra.describe(["compute", "instances", "describe", "test"])

    def test_cloud_command_always_uses_fixed_project(self):
        with patch("infra.subprocess.run", return_value=Mock(returncode=0, stdout="{}", stderr="")) as run:
            infra.describe(["compute", "instances", "describe", "test"])
            self.assertIn("--project=dazzling-seat-508219-j3", run.call_args.args[0])
            self.assertEqual(run.call_args.kwargs["stdin"], infra.subprocess.DEVNULL)
            self.assertEqual(run.call_args.kwargs["env"]["CLOUDSDK_CORE_DISABLE_PROMPTS"], "true")

    def test_missing_beta_stops_setup_before_cloud_mutations(self):
        with patch("infra.cloud", return_value=[{"id": "core"}]) as cloud:
            with self.assertRaisesRegex(RuntimeError, "gcloud components install beta"):
                infra.prepare()
        cloud.assert_called_once_with(
            ["components", "list", "--only-local-state"], json_output=True)

    def test_missing_beta_stops_direct_sql_before_cloud_mutations(self):
        with patch("infra.cloud", return_value=[]) as cloud:
            with self.assertRaisesRegex(RuntimeError, "gcloud components install beta"):
                infra.sql()
        cloud.assert_called_once_with(
            ["components", "list", "--only-local-state"], json_output=True)

    def test_installed_beta_passes_without_installation(self):
        with patch("infra.cloud", return_value=[{"id": "core"}, {"id": "beta"}]) as cloud:
            infra.require_beta_component()
        cloud.assert_called_once_with(
            ["components", "list", "--only-local-state"], json_output=True)

    def sql_calls(self, existing=None):
        calls = []
        def fake(parts, **kwargs):
            calls.append(parts)
            if parts[:2] == ["components", "list"]:
                return [{"id": "beta"}]
            if parts[:3] == ["sql", "instances", "describe"]:
                return existing
            if parts[:3] == ["sql", "databases", "list"]:
                return [{"name": infra.C.DB_NAME}]
            if parts[:3] == ["sql", "users", "list"]:
                return [{"name": infra.C.DB_USER}]
            return ""
        with patch("infra.cloud", side_effect=fake), contextlib.redirect_stdout(io.StringIO()):
            infra.sql()
        return calls

    def test_new_sql_creation_avoids_conflicting_backup_options(self):
        creations = [call for call in self.sql_calls()
                     if call[:4] == ["beta", "sql", "instances", "create"]]
        self.assertEqual(len(creations), 1)
        self.assertIn("--no-backup", creations[0])
        # gcloud checks IsSpecified, so both positive and negative forms conflict.
        forbidden = ("--enable-bin-log", "--no-enable-bin-log",
                     "--enable-point-in-time-recovery", "--no-enable-point-in-time-recovery")
        self.assertFalse(any(arg.split("=", 1)[0] in forbidden for arg in creations[0]))
        self.assertIn("--deletion-protection", creations[0])
        self.assertIn("--labels=course=cs528,homework=hw5", creations[0])

    def test_existing_sql_reuses_instance_and_validates_start_policy(self):
        for policy in ("ALWAYS", "NEVER"):
            with self.subTest(policy=policy):
                calls = self.sql_calls({"databaseVersion": "MYSQL_8_4", "region": infra.C.REGION,
                    "settings": {"userLabels": {"homework": "hw5"}, "activationPolicy": policy}})
                self.assertFalse(any(call[:4] == ["beta", "sql", "instances", "create"] for call in calls))
                patches = [call for call in calls if call[:3] == ["sql", "instances", "patch"]]
                expected = [] if policy == "ALWAYS" else [["sql", "instances", "patch",
                    infra.C.SQL_INSTANCE, "--activation-policy=always"]]
                self.assertEqual(patches, expected)

    def test_plan_does_not_access_cloud(self):
        with patch("infra.cloud") as cloud, contextlib.redirect_stdout(io.StringIO()):
            infra.plan()
            infra.plan(True)
        cloud.assert_not_called()

    def test_reporter_is_byte_identical_to_hw4(self):
        expected = "095e77c433957dd45185d4c0fce3efa3a948866308839bdabb9c22dbb93c87b0"
        self.assertEqual(hashlib.sha256((ROOT / "reporter.py").read_bytes()).hexdigest(), expected)

    def test_cleanup_stops_sql_and_releases_ip(self):
        calls = []
        def fake(parts, **kwargs):
            calls.append(parts)
            if "describe" in parts:
                if parts[:3] == ["sql", "instances", "describe"]:
                    return {"settings": {"userLabels": {"homework": "hw5"}, "activationPolicy": "ALWAYS"}}
                if parts[:3] == ["compute", "addresses", "describe"]:
                    return {"description": infra.C.MARKER}
                return None
            return ""
        with tempfile.TemporaryDirectory() as directory:
            with patch("infra.ROOT", Path(directory)), patch("infra.cloud", side_effect=fake), \
                    patch("infra.status"), contextlib.redirect_stdout(io.StringIO()):
                infra.cleanup()
        self.assertTrue(any(call[:4] == ["sql", "instances", "patch", infra.C.SQL_INSTANCE] and "--activation-policy=never" in call for call in calls))
        self.assertTrue(any(call[:3] == ["compute", "addresses", "delete"] for call in calls))
        self.assertFalse(any(call[:3] == ["sql", "instances", "delete"] for call in calls))


if __name__ == "__main__":
    unittest.main()
