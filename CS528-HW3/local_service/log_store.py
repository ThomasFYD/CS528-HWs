"""Append JSON lines to one ordinary GCS object with generation preconditions."""

import json
import time

from google.api_core.exceptions import NotFound, PreconditionFailed
from google.api_core.retry import Retry


class BucketLog:
    def __init__(self, bucket, object_name="hw3-logs/forbidden-requests.jsonl"):
        if not object_name.startswith("hw3-logs/"):
            raise ValueError("The log must be inside hw3-logs/.")
        self.bucket = bucket
        self.object_name = object_name
        self._last_write = None

    def append(self, record):
        """Return True for a new event, False for an already persisted event."""
        event_id = record.get("event_id")
        if not isinstance(event_id, str) or not event_id:
            raise ValueError("Every log record needs a nonempty event_id.")
        for attempt in range(6):
            blob = self.bucket.blob(self.object_name)
            try:
                try:
                    blob.reload(timeout=20, retry=Retry(deadline=30))
                    generation = int(blob.generation)
                    previous = blob.download_as_bytes(
                        if_generation_match=generation, timeout=20,
                        retry=Retry(deadline=30),
                    )
                except NotFound:
                    generation, previous = 0, b""

                # Persisted IDs survive process restarts and lost acknowledgments.
                for line in previous.splitlines():
                    if line.strip() and json.loads(line)["event_id"] == event_id:
                        return False

                suffix = json.dumps(record, ensure_ascii=False).encode("utf-8") + b"\n"
                if previous and not previous.endswith(b"\n"):
                    previous += b"\n"
                # Avoid replacing the same GCS object more than once per second.
                if self._last_write is not None:
                    time.sleep(max(0, 1.1 - (time.monotonic() - self._last_write)))
                try:
                    blob.upload_from_string(
                        previous + suffix, content_type="application/x-ndjson",
                        if_generation_match=generation, timeout=20,
                        retry=Retry(deadline=30),
                    )
                finally:
                    self._last_write = time.monotonic()
                return True
            except PreconditionFailed:
                # Another writer (or an ambiguous retried upload) changed the file.
                # Re-read and check event_id before trying again.
                time.sleep(min(0.5 * 2 ** attempt, 4))
        raise RuntimeError("Log generation changed repeatedly; retry this message.")
