"""Metric arithmetic, evidence classification and real child-process cleanup."""

import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import monitor_resources as monitor
import stress_client as stress
import summarize_performance as summarize
import run_performance as runner


class MetricsTests(unittest.TestCase):
    def test_guest_cpu_is_not_double_counted_and_default_interface_is_used(self):
        with tempfile.TemporaryDirectory() as temporary:
            proc = Path(temporary)
            (proc / "net").mkdir()
            (proc / "stat").write_text("cpu 10 2 8 65 5 1 4 5 100 100\n")
            (proc / "meminfo").write_text("MemTotal: 1024 kB\nMemAvailable: 256 kB\n")
            (proc / "net/route").write_text("Iface Destination Gateway Flags\nens4 00000000 0 0003\n")
            (proc / "net/dev").write_text("header\nheader\n ens4: 1000 0 0 0 0 0 0 0 2000 0 0 0 0 0 0 0\n")
            interface = monitor.default_interface(proc)
            result = monitor.counters(proc, interface)
            self.assertEqual(interface, "ens4")
            self.assertEqual(sum(result["cpu"]), 100)
            self.assertEqual(result["memory_used_bytes"], 768 * 1024)
            self.assertEqual(result["tx_bytes"], 2000)

    def test_cpu_steal_memory_and_megabit_units(self):
        first = {"cpu": [0] * 8, "rx_bytes": 0, "tx_bytes": 0}
        last = {"cpu": [10, 2, 8, 65, 5, 1, 4, 5],
                "rx_bytes": 2_000_000, "tx_bytes": 1_000_000,
                "memory_used_bytes": 256 * 2**20, "memory_total_bytes": 512 * 2**20}
        metrics = monitor.rates(first, last, 2)
        self.assertEqual(metrics["cpu_busy_pct"], 25)
        self.assertEqual(metrics["cpu_steal_pct"], 5)
        self.assertEqual(metrics["cpu_iowait_pct"], 5)
        self.assertEqual(metrics["memory_used_pct"], 50)
        self.assertEqual(metrics["rx_mbps"], 8)
        self.assertEqual(metrics["tx_mbps"], 4)
        with self.assertRaises(RuntimeError):
            monitor.rates(last, first, 1)

    def test_window_boundary_weighting_and_gap_detection(self):
        def sample(left, right, value):
            return {"type": "sample", "interval_start": f"2026-01-01T00:00:{left:02d}+00:00",
                    "timestamp": f"2026-01-01T00:00:{right:02d}+00:00",
                    "elapsed_seconds": right - left, **{m: value for m in summarize.METRICS}}
        start = summarize.epoch("2026-01-01T00:00:01+00:00")
        selected = summarize.window_samples([sample(0, 2, 10), sample(2, 4, 20)], start, start + 2)
        result = summarize.resource_summary(selected, start, start + 2)
        self.assertEqual(result["coverage_seconds"], 2)
        self.assertEqual(result["mean"]["cpu_busy_pct"], 15)
        self.assertEqual(result["peak"]["cpu_busy_pct"], 20)
        gap = summarize.resource_summary(selected[:1], start, start + 2)
        self.assertEqual(gap["coverage_seconds"], 1)
        self.assertEqual(gap["max_gap_seconds"], 1)

    def test_only_expected_country_denials_are_excluded_from_failure_records(self):
        when = "2026-01-01T00:00:01Z"
        logs = [{"timestamp": when, "jsonPayload": {"event": event, "status": status}}
                for event, status in (("forbidden_country", 400), ("publish_failed", 503),
                                      ("malformed_request", 400), ("storage_failed", 500))]
        start = summarize.epoch(when)
        counts = summarize.cloud_counts(logs, start, start + 1)
        self.assertEqual(counts["expected_country_denials"], 1)
        self.assertEqual(counts["other_warning_or_error_records"], 3)
        self.assertEqual(counts["status_400"], 1)
        self.assertEqual(summarize.cloud_counts(logs, start - 1, start), {})

    def test_full_window_summary_is_valid_but_a_missing_sample_is_flagged(self):
        from datetime import datetime, timedelta, timezone
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            client = root / "client/c1"
            client.mkdir(parents=True)
            start = datetime(2026, 1, 1, tzinfo=timezone.utc)
            end = start + timedelta(seconds=180)
            (client / "round.json").write_text(json.dumps({
                "complete": True, "measurement_start": start.isoformat(),
                "measurement_end": end.isoformat(), "measured_seconds": 180}))
            metadata = {"type": "metadata", "clock_synchronized": "yes"}
            records = [metadata] + [{
                "type": "sample", "interval_start": (start + timedelta(seconds=i)).isoformat(),
                "timestamp": (start + timedelta(seconds=i + 1)).isoformat(),
                "elapsed_seconds": 1, **{m: 12 for m in summarize.METRICS}}
                for i in range(180)]
            (client / "client-resources.jsonl").write_text(json.dumps(metadata) + "\n")
            (root / "cloud-errors.json").write_text("[]")
            (root / "web-journal.jsonl").write_text("")
            resource_path = root / "web-resources.jsonl"
            resource_path.write_text("\n".join(map(json.dumps, records)) + "\n")
            with contextlib.redirect_stdout(io.StringIO()):
                result = summarize.summarize(root)
            self.assertTrue(result["rounds"][0]["measurement_valid"])
            self.assertEqual(result["rounds"][0]["web"]["coverage_seconds"], 180)
            self.assertFalse(result["rounds"][1]["measurement_valid"])
            del records[90]
            resource_path.write_text("\n".join(map(json.dumps, records)) + "\n")
            with contextlib.redirect_stdout(io.StringIO()):
                result = summarize.summarize(root)
            self.assertFalse(result["rounds"][0]["measurement_valid"])


class FakeSampler:
    def sample(self):
        return {"type": "sample", "timestamp": monitor.utc()}


class ClientLifecycleTests(unittest.TestCase):
    def round(self, count, commands, path, **kwargs):
        with patch.object(stress, "metadata", return_value={"type": "metadata"}), \
                contextlib.redirect_stdout(io.StringIO()):
            return stress.run_round(count, commands, path, warmup=0.1,
                                    sample_factory=FakeSampler, **kwargs)

    def test_four_clients_remain_alive_for_window_then_all_stop_and_flush_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            code = "import os,time; print('Timeout received'); print('PID',os.getpid()); time.sleep(30)"
            before = time.monotonic()
            result = self.round(4, [[sys.executable, "-c", code]] * 4, root / "c4", seconds=0.5)
            self.assertGreaterEqual(time.monotonic() - before, 0.6)
            self.assertTrue(result["complete"])
            self.assertGreaterEqual(result["measured_seconds"], 0.5)
            self.assertEqual(len(result["process_exit_codes_after_stop"]), 4)
            for i in range(1, 5):
                text = (root / f"c4/client-{i}.log").read_text()
                self.assertIn("Timeout received", text)
                pid = int(next(line.split()[1] for line in text.splitlines() if line.startswith("PID ")))
                with self.assertRaises(ProcessLookupError):
                    os.kill(pid, 0)

    def test_early_success_exit_is_not_a_successful_three_minute_test(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "c2"
            commands = [[sys.executable, "-c", "pass"],
                        [sys.executable, "-c", "import time; time.sleep(30)"]]
            with self.assertRaisesRegex(RuntimeError, "exited early"):
                self.round(2, commands, output, seconds=1)
            result = json.loads((output / "round.json").read_text())
            self.assertFalse(result["complete"])
            self.assertTrue(all(code is not None for code in result["process_exit_codes_after_stop"]))

    def test_never_launch_five_clients(self):
        with patch.object(stress.subprocess, "Popen") as launch, self.assertRaises(ValueError):
            stress.run_round(5, [["fake"]] * 5, Path("unused"))
        launch.assert_not_called()

    def test_quiet_instructor_command_preserves_bucket_prefix_timeout_and_seed(self):
        command = stress.client_command(Path("/tmp/http-client"), "203.0.113.1", "bucket", 4, 30)
        self.assertEqual(command[command.index("-b") + 1], "/bucket")
        self.assertEqual(command[command.index("-r") + 1], "3")
        self.assertEqual(command[command.index("-t") + 1], "30")
        self.assertNotIn("-v", command)

    def test_orchestrator_remote_command_is_one_argument_and_pins_project(self):
        import argparse
        args = argparse.Namespace(collect="test-run", project="test-project", account="test@example.edu",
                                  zone="us-central1-a", bucket="test-bucket")
        exp = runner.Experiment(args)
        command = "printf '%s' 'value with spaces'"
        parts = exp.gcloud(exp.ssh_parts("cs528-hw4-client", command))
        self.assertIn("--command=" + command, parts)
        self.assertIn("--project=test-project", parts)


if __name__ == "__main__":
    unittest.main()
