"""Offline tests; fake GCS generations and Pub/Sub messages, no cloud calls."""

import contextlib
import io
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from google.api_core.exceptions import (
    DeadlineExceeded, Forbidden, InternalServerError, NotFound, PreconditionFailed,
    ServiceUnavailable, TooManyRequests,
)
from google.auth.exceptions import RefreshError
from gcloud_credentials import GcloudImpersonatedCredentials
from log_store import BucketLog
from subscriber import process_message, receive_forever


class FakeBucket:
    """Atomic generation comparisons approximate GCS object replacements."""
    def __init__(self):
        self.data = None
        self.generation = 0
        self.write_conditions = []
        self.before_write = None
        self.lose_response = False

    def blob(self, name):
        bucket = self

        class Blob:
            def reload(self, **kwargs):
                if bucket.data is None:
                    raise NotFound("missing")
                self.generation = bucket.generation

            def download_as_bytes(self, if_generation_match, **kwargs):
                if if_generation_match != bucket.generation:
                    raise PreconditionFailed("changed")
                return bucket.data

            def upload_from_string(self, data, if_generation_match, **kwargs):
                bucket.write_conditions.append(if_generation_match)
                if bucket.before_write:
                    callback, bucket.before_write = bucket.before_write, None
                    callback()
                if if_generation_match != bucket.generation:
                    raise PreconditionFailed("changed")
                bucket.data = data
                bucket.generation += 1
                if bucket.lose_response:
                    bucket.lose_response = False
                    # A repeated upload with the old generation would produce 412.
                    raise PreconditionFailed("write succeeded, response lost")
        return Blob()


class LogTests(unittest.TestCase):
    def setUp(self):
        sleeper = patch("log_store.time.sleep")
        sleeper.start()
        self.addCleanup(sleeper.stop)
        self.bucket = FakeBucket()
        self.log = BucketLog(self.bucket)

    def records(self):
        return [json.loads(line) for line in self.bucket.data.splitlines()]

    def test_creates_one_file_then_preserves_prior_lines(self):
        self.assertTrue(self.log.append({"event_id": "a"}))
        self.assertTrue(self.log.append({"event_id": "b"}))
        self.assertEqual(self.records(), [{"event_id": "a"}, {"event_id": "b"}])
        self.assertEqual(self.bucket.write_conditions, [0, 1])

    def test_redelivery_after_restart_does_not_append_duplicate(self):
        self.log.append({"event_id": "a"})
        restarted = BucketLog(self.bucket)
        self.assertFalse(restarted.append({"event_id": "a", "received_at": "later"}))
        self.assertEqual(len(self.records()), 1)
        self.assertEqual(self.bucket.write_conditions, [0])

    def test_generation_race_preserves_other_writer(self):
        def competing_write():
            self.bucket.data = b'{"event_id":"other"}\n'
            self.bucket.generation = 1
        self.bucket.before_write = competing_write
        self.log.append({"event_id": "mine"})
        self.assertEqual([r["event_id"] for r in self.records()], ["other", "mine"])
        self.assertEqual(self.bucket.write_conditions, [0, 1])

    def test_lost_upload_response_is_deduplicated(self):
        self.bucket.lose_response = True
        self.assertFalse(self.log.append({"event_id": "a"}))
        self.assertEqual(len(self.records()), 1)

    def test_corrupt_existing_file_is_not_overwritten(self):
        self.bucket.data = b"not json\n"
        self.bucket.generation = 1
        with self.assertRaises(ValueError):
            self.log.append({"event_id": "a"})
        self.assertEqual(self.bucket.data, b"not json\n")
        self.assertFalse(self.bucket.write_conditions)


class MessageTests(unittest.TestCase):
    def setUp(self):
        self.client, self.log = Mock(), Mock()
        self.event = {"event_id": "a", "event": "forbidden_country", "country": "Iran"}
        self.received = SimpleNamespace(
            ack_id="ack-1", message=SimpleNamespace(
                message_id="message-1", data=json.dumps(self.event).encode(),
            ),
        )
        self.output = io.StringIO()

    def run_message(self):
        with contextlib.redirect_stdout(self.output):
            return process_message(self.client, "subscription", self.received, self.log)

    def test_ack_only_after_successful_append(self):
        order = []
        self.log.append.side_effect = lambda event: order.append("write") or True
        self.client.acknowledge.side_effect = lambda **kwargs: order.append("ack")
        self.assertTrue(self.run_message())
        self.assertEqual(order, ["write", "ack"])
        self.assertIn("FORBIDDEN", self.output.getvalue())

    def test_failed_write_is_not_acknowledged(self):
        self.log.append.side_effect = Forbidden("denied")
        self.assertFalse(self.run_message())
        self.client.acknowledge.assert_not_called()
        args = self.client.modify_ack_deadline.call_args.kwargs["request"]
        self.assertEqual(args["ack_deadline_seconds"], 0)

    def test_already_stored_redelivery_is_acknowledged(self):
        self.log.append.return_value = False
        self.assertTrue(self.run_message())
        self.client.acknowledge.assert_called_once()
        self.assertIn("ALREADY_STORED", self.output.getvalue())

    def test_lost_ack_then_redelivery_leaves_single_log_record(self):
        bucket = FakeBucket()
        self.log = BucketLog(bucket)
        self.client.acknowledge.side_effect = [RuntimeError("lost ack"), None]
        self.assertFalse(self.run_message())
        self.assertTrue(self.run_message())
        self.assertEqual(len(bucket.data.splitlines()), 1)

    def test_malformed_message_is_not_silently_discarded(self):
        self.received.message.data = b"bad json"
        self.assertFalse(self.run_message())
        self.client.acknowledge.assert_not_called()
        self.log.append.assert_not_called()


class PullRecoveryTests(unittest.TestCase):
    def test_connection_reset_recovers_and_persists_pending_message(self):
        event = {"event_id": "pending", "event": "forbidden_country", "country": "Iran"}
        received = SimpleNamespace(
            ack_id="ack-pending", message=SimpleNamespace(
                message_id="pubsub-pending", data=json.dumps(event).encode(),
            ),
        )
        bucket, client = FakeBucket(), Mock()
        client.pull.side_effect = [
            ServiceUnavailable("Stream removed: Connection reset by peer (54)"),
            SimpleNamespace(received_messages=[received]), KeyboardInterrupt(),
        ]
        output = io.StringIO()
        with patch("subscriber.time.sleep") as sleep, contextlib.redirect_stdout(output):
            with self.assertRaises(KeyboardInterrupt):
                receive_forever(client, "subscription", BucketLog(bucket))
        sleep.assert_called_once_with(2)
        self.assertEqual(json.loads(bucket.data)["event_id"], "pending")
        client.acknowledge.assert_called_once()
        self.assertIn("PULL_RESUMED", output.getvalue())

    def test_repeated_temporary_failures_back_off_to_thirty_seconds(self):
        client = Mock()
        client.pull.side_effect = [ServiceUnavailable("offline") for _ in range(6)] + [KeyboardInterrupt()]
        with patch("subscriber.time.sleep") as sleep, contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(KeyboardInterrupt):
                receive_forever(client, "subscription", Mock())
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [2, 4, 8, 16, 30, 30])

    def test_success_resets_retry_delay(self):
        client = Mock()
        client.pull.side_effect = [
            ServiceUnavailable("offline"), ServiceUnavailable("offline"),
            SimpleNamespace(received_messages=[]), ServiceUnavailable("offline"),
            KeyboardInterrupt(),
        ]
        with patch("subscriber.time.sleep") as sleep, contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(KeyboardInterrupt):
                receive_forever(client, "subscription", Mock())
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [2, 4, 1, 2])

    def test_idle_deadline_and_retryable_api_failures_do_not_exit(self):
        for error in (DeadlineExceeded("idle"), InternalServerError("retry"), TooManyRequests("retry")):
            with self.subTest(error=type(error).__name__):
                client = Mock()
                client.pull.side_effect = [error, KeyboardInterrupt()]
                with patch("subscriber.time.sleep"), contextlib.redirect_stdout(io.StringIO()):
                    with self.assertRaises(KeyboardInterrupt):
                        receive_forever(client, "subscription", Mock())
                self.assertEqual(client.pull.call_count, 2)

    def test_permission_denied_is_reported_instead_of_retried_forever(self):
        client = Mock()
        client.pull.side_effect = Forbidden("permission denied")
        with patch("subscriber.time.sleep") as sleep:
            with self.assertRaises(Forbidden):
                receive_forever(client, "subscription", Mock())
        sleep.assert_not_called()


class CredentialsTests(unittest.TestCase):
    def setUp(self):
        with patch("gcloud_credentials.shutil.which", return_value="/sdk/gcloud"):
            self.credentials = GcloudImpersonatedCredentials("user@example.org", "sa@example.org", "p")
        self.expiry = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(hours=1)
        self.result = SimpleNamespace(returncode=0, stdout=json.dumps({"credential": {
            "access_token": "fake-token", "token_expiry": self.expiry.isoformat(),
        }}))

    def test_explicit_impersonation_and_actual_expiry(self):
        with patch("gcloud_credentials.subprocess.run", return_value=self.result) as run:
            self.credentials.refresh(None)
        args = run.call_args.args[0]
        self.assertIn("--impersonate-service-account=sa@example.org", args)
        self.assertIn("--account=user@example.org", args)
        self.assertIn("--force-auth-refresh", args)
        self.assertNotIn("application-default", args)
        self.assertEqual(self.credentials.expiry, self.expiry.replace(tzinfo=None))
        self.assertEqual(self.credentials.token, "fake-token")

    def test_refresh_failure_does_not_expose_command_output(self):
        self.result.returncode, self.result.stdout = 1, "secret-in-output"
        with patch("gcloud_credentials.subprocess.run", return_value=self.result):
            with self.assertRaises(RefreshError) as caught:
                self.credentials.refresh(None)
        self.assertNotIn("secret-in-output", str(caught.exception))

    def test_rejects_expired_token(self):
        self.result.stdout = json.dumps({"credential": {
            "access_token": "fake-token", "token_expiry": "2000-01-01T00:00:00Z",
        }})
        with patch("gcloud_credentials.subprocess.run", return_value=self.result):
            with self.assertRaises(RefreshError):
                self.credentials.refresh(None)


if __name__ == "__main__":
    unittest.main()
