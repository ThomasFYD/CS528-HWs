"""Parse the headers observed from the instructor's updated macOS client."""
import json
import re
import threading
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote, urlsplit

from hw4_service import COUNTRIES

RUN_PATTERN = re.compile(r"^/__runs/([A-Za-z0-9_-]{1,64})(/.*)$")


class RequestClock:
    """Unique UTC receipt timestamps for this single-process threaded server.

    Seed with MAX(request_time) after restart. Never use the repeating X-time
    header as a primary key. A one-microsecond adjustment resolves clock ties.
    """
    def __init__(self, last=None):
        self.last = last or datetime.min
        self.lock = threading.Lock()

    def next(self):
        with self.lock:
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            self.last = max(now, self.last + timedelta(microseconds=1))
            return self.last


def route(path):
    match = RUN_PATTERN.match(path)
    return (match.group(2), match.group(1)) if match else (path, None)


def extract_headers(headers, peer_ip, method, path, body, bucket, clock):
    # HTTPMessage is case-insensitive; normalize too for plain dictionaries/tests.
    values = {key.lower(): value for key, value in headers.items()}

    def value(name, length):
        raw = values.get(name)
        return raw.strip()[:length] if raw is not None else None

    effective_path, run_id = route(path)
    country = value("x-country", 128)
    raw_time = value("x-time", 64)
    time_of_day = None
    if raw_time:
        try:
            time_of_day = datetime.strptime(raw_time, "%Y-%m-%d %H:%M:%S").strftime("%H:%M:%S")
        except ValueError:
            pass  # Preserve the raw value; do not invent a client time.
    requested_file = effective_path
    try:
        requested_file = unquote(urlsplit(effective_path).path).lstrip("/")
    except ValueError:
        pass
    if method == "POST":
        try:
            payload = json.loads(body)
            if isinstance(payload, dict) and isinstance(payload.get("filename"), str):
                requested_file = payload["filename"].lstrip("/")
        except (ValueError, UnicodeError):
            pass
    if requested_file.startswith(bucket + "/"):
        requested_file = requested_file[len(bucket) + 1:]
    return {
        "request_id": str(uuid.uuid4()), "request_time": clock.next(),
        "run_id": run_id, "method": method[:32],
        "requested_file": requested_file[:1024], "country": country,
        "client_ip": value("x-client-ip", 45) or peer_ip[:45],
        "peer_ip": peer_ip[:45], "gender": value("x-gender", 32),
        "age": value("x-age", 32), "income": value("x-income", 32),
        "client_time": raw_time, "time_of_day": time_of_day,
        "is_banned": " ".join((country or "").split()).casefold() in COUNTRIES,
    }, effective_path
