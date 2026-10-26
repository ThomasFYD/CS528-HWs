"""Regression checks for a timeout before any instructor client is launched."""
import base64
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import config
import database


ROOT = Path(__file__).resolve().parents[1]
with patch.object(sys, "path", [str(ROOT / "tools"), *sys.path]):
    spec = importlib.util.spec_from_file_location("hw5_test_runner", ROOT / "tools/run_experiment.py")
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)


class LocalDatabaseTests(unittest.TestCase):
    def test_local_password_uses_cli_without_grpc_and_preserves_bytes(self):
        password = "  test-password-é\n"
        encoded = base64.urlsafe_b64encode(password.encode()).decode() + "\n"
        output = io.StringIO()
        with patch("database.subprocess.run", return_value=Mock(returncode=0, stdout=encoded)) as command, \
                patch("google.cloud.secretmanager.SecretManagerServiceClient") as secrets, \
                patch("google.cloud.sql.connector.Connector") as connector, \
                patch("sqlalchemy.create_engine") as engine, contextlib.redirect_stdout(output):
            db = database.create_database(local=True)
            engine.call_args.kwargs["creator"]()
            self.assertEqual(connector.return_value.connect.call_args.kwargs["password"], password)
            secrets.assert_not_called()
            args, kwargs = command.call_args
            self.assertIn(f"--project={config.PROJECT_ID}", args[0])
            self.assertIn(f"--secret={config.PASSWORD_SECRET}", args[0])
            self.assertIn("--format=get(payload.data)", args[0])
            self.assertEqual(kwargs["timeout"], 60)
            self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)
            self.assertEqual(kwargs["env"]["CLOUDSDK_CORE_DISABLE_PROMPTS"], "true")
            self.assertTrue(kwargs["capture_output"])
            self.assertEqual(output.getvalue(), "")
            db.close()

    def test_local_secret_failures_do_not_connect_or_expose_output(self):
        marker = "do-not-print-this-test-payload"
        failures = [
            {"return_value": Mock(returncode=1, stdout=marker, stderr=marker)},
            {"return_value": Mock(returncode=0, stdout=marker)},
            {"return_value": Mock(returncode=0, stdout="")},
            {"side_effect": subprocess.TimeoutExpired("gcloud", 60, output=marker, stderr=marker)},
        ]
        for failure in failures:
            with self.subTest(failure=failure), patch("database.subprocess.run", **failure), \
                    patch("google.cloud.sql.connector.Connector") as connector, \
                    patch("sqlalchemy.create_engine") as engine, \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                with self.assertRaises(RuntimeError) as raised:
                    database.create_database(local=True)
                self.assertNotIn(marker, str(raised.exception))
                self.assertEqual(output.getvalue(), "")
                connector.assert_not_called()
                engine.assert_not_called()

    def test_vm_still_uses_attached_identity_and_secret_manager(self):
        with patch("database._local_gcloud_value") as local, \
                patch("google.cloud.secretmanager.SecretManagerServiceClient") as secrets, \
                patch("google.cloud.sql.connector.Connector") as connector, \
                patch("sqlalchemy.create_engine") as engine:
            secrets.return_value.access_secret_version.return_value.payload.data = b"vm-test-password"
            db = database.create_database()
            engine.call_args.kwargs["creator"]()
            local.assert_not_called()
            secrets.assert_called_once_with(credentials=None)
            connector.assert_called_once_with(credentials=None, refresh_strategy="LAZY")
            self.assertEqual(connector.return_value.connect.call_args.kwargs["password"], "vm-test-password")
            db.close()

    def test_token_refresh_retains_refreshable_gcloud_identity(self):
        with patch("database.subprocess.run", return_value=Mock(returncode=0, stdout="test-token\n")) as command:
            credentials = database.gcloud_credentials()
            credentials.refresh(None)
            self.assertEqual(credentials.token, "test-token")
            self.assertIsNotNone(credentials.expiry)
            self.assertEqual(command.call_args.args[0][:3], ["gcloud", "auth", "print-access-token"])
            self.assertEqual(command.call_args.kwargs["timeout"], 60)


class ExperimentPreflightTests(unittest.TestCase):
    def run_failed_preflight(self, resume_error=None):
        with tempfile.TemporaryDirectory() as directory, contextlib.ExitStack() as stack:
            root = Path(directory)
            client = root / "test-client"
            client.write_bytes(b"not-an-executable-test-fixture")
            client.chmod(0o700)
            stack.enter_context(patch.object(runner, "ROOT", root))
            stack.enter_context(patch.object(runner.config, "CLIENT_SHA256", hashlib.sha256(client.read_bytes()).hexdigest()))
            stack.enter_context(patch.object(sys, "argv", ["run_experiment.py", "--client", str(client), "--requests", "100"]))
            stack.enter_context(patch.object(runner, "endpoint", return_value=("127.0.0.1", 8080)))
            pause = stack.enter_context(patch.object(runner.infra, "pause_guard"))
            stack.enter_context(patch.object(runner.infra, "sql"))
            resume = stack.enter_context(patch.object(runner.infra, "resume_guard", side_effect=resume_error))
            stack.enter_context(patch.object(runner, "create_database", side_effect=RuntimeError("simulated secret timeout")))
            launch = stack.enter_context(patch.object(runner.subprocess, "Popen"))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            with self.assertRaises(SystemExit) as raised:
                runner.main()
            evidence = next((root / "report/evidence").glob("*/experiment.json"))
            metadata = json.loads(evidence.read_text())
            pause.assert_called_once()
            resume.assert_called_once()
            launch.assert_not_called()
            self.assertEqual(metadata["exit_codes"], [])
            self.assertNotIn("load_started_at", metadata)
            self.assertFalse(metadata["complete"])
            self.assertEqual(metadata["phase"], "failed")
            self.assertEqual(metadata["failure_phase"], "opening_local_database")
            self.assertTrue(metadata["failure_frames"])
            return metadata, str(raised.exception)

    def test_preflight_failure_restores_guard_and_records_stage(self):
        metadata, message = self.run_failed_preflight()
        self.assertTrue(metadata["guard_resumed"])
        self.assertIn("opening_local_database", message)
        self.assertIn("guard was restored", message)
        self.assertNotIn("infra.py resume-guard", message)

    def test_guard_resume_failure_provides_recovery_command(self):
        metadata, message = self.run_failed_preflight(RuntimeError("simulated scheduler outage"))
        self.assertFalse(metadata["guard_resumed"])
        self.assertIn("simulated scheduler outage", metadata["guard_error"])
        self.assertIn("infra.py resume-guard", message)


if __name__ == "__main__":
    unittest.main()
