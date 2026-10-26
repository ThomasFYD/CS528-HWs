"""HW4 HTTP service on Compute Engine; adapted from the HW3 file service."""

import argparse
import json
import mimetypes
import os
import socket
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import unquote, urlsplit


# Assignment simulation, not a current legal sanctions list.
COUNTRIES = {name.casefold(): name for name in (
    "North Korea", "Iran", "Cuba", "Myanmar", "Iraq", "Libya", "Sudan",
    "Zimbabwe", "Syria",
)}
COUNTRIES.update({
    "korea, democratic people's republic of": "North Korea",
    "democratic people's republic of korea": "North Korea",
    "iran, islamic republic of": "Iran",
    "syrian arab republic": "Syria",
})
MAX_BODY = 65536


class MissingObject(Exception):
    pass


class CloudBackend:
    def __init__(self, project, bucket, topic):
        from google.cloud import logging as cloud_logging, pubsub_v1, storage
        from google.api_core.exceptions import NotFound

        self.not_found = NotFound
        self.bucket = storage.Client(project=project).bucket(bucket)
        self.publisher = pubsub_v1.PublisherClient()
        self.topic = self.publisher.topic_path(project, topic)
        # VM attached-service-account credentials are discovered automatically.
        # log_struct writes to the API; VM stdout alone is not Cloud Logging.
        self.logger = cloud_logging.Client(project=project).logger("cs528-hw4-web")

    def read(self, name):
        blob = self.bucket.blob(name)
        try:
            contents = blob.download_as_bytes(timeout=20, retry=None)
        except self.not_found as exc:
            raise MissingObject(name) from exc
        return contents, blob.content_type or mimetypes.guess_type(name)[0] or "application/octet-stream"

    def log(self, entry, severity):
        self.logger.log_struct(entry, severity=severity)

    def publish(self, event):
        return self.publisher.publish(
            self.topic, json.dumps(event).encode(), event_id=event["event_id"]
        ).result(timeout=15)


class Application:
    def __init__(self, bucket, backend):
        self.bucket, self.backend = bucket, backend

    def log(self, severity, entry):
        print(json.dumps({"severity": severity, **entry}), flush=True)
        try:
            self.backend.log(entry, severity)
        except Exception as exc:
            # Preserve an HTTP error even during a logging outage, but make the
            # delivery failure explicit in journalctl; live acceptance must check
            # that the corresponding Cloud Logging entries actually exist.
            print(json.dumps({"severity": "ERROR", "event": "cloud_logging_failed",
                              "error_type": type(exc).__name__, "original": entry}), flush=True)

    def error(self, method, path, status, severity, event, message, **details):
        self.log(severity, {"timestamp": datetime.now(timezone.utc).isoformat(),
                            "method": method, "path": path, "status": status,
                            "event": event, "message": message, **details})
        return status, (message + "\n").encode(), "text/plain; charset=utf-8"

    def handle(self, method, path, country="", body=b""):
        if method not in ("GET", "POST"):
            return self.error(method, path, 501, "ERROR", "unsupported_method",
                              "HTTP method not implemented.")
        canonical = COUNTRIES.get(" ".join(country.split()).casefold())
        if canonical:
            event = {"event_id": str(uuid.uuid4()), "event": "forbidden_country",
                     "timestamp": datetime.now(timezone.utc).isoformat(),
                     "method": method, "path": path, "country": canonical,
                     "country_header": country, "status": 400,
                     "message": f"Permission denied: request from {canonical}."}
            # Log CRITICAL even if Pub/Sub is unavailable. Never read the object.
            self.log("CRITICAL", event)
            try:
                self.backend.publish(event)
            except Exception as exc:
                return self.error(method, path, 503, "ERROR", "pubsub_publish_failed",
                                  "Permission denied; notification delivery unconfirmed.",
                                  event_id=event["event_id"], error_type=type(exc).__name__)
            # Keep HW3's assignment-specific 400 instead of silently changing to 403.
            return 400, (event["message"] + "\n").encode(), "text/plain; charset=utf-8"

        if method == "GET":
            try:
                filename = unquote(urlsplit(path).path)
            except ValueError:
                return self.error(method, path, 400, "WARNING", "invalid_path",
                                  "Invalid request path.")
        else:
            try:
                payload = json.loads(body)
                filename = payload.get("filename") if isinstance(payload, dict) else None
                if not isinstance(filename, str) or not filename.strip():
                    raise ValueError("missing filename")
            except (ValueError, UnicodeError):
                return self.error(method, path, 400, "WARNING", "invalid_payload",
                                  "POST requires JSON with a nonempty filename string.")
        name = filename.lstrip("/")
        if name.startswith(self.bucket + "/"):
            name = name[len(self.bucket) + 1:]
        if not name.startswith("data/") or name == "data/":
            return self.error(method, path, 404, "WARNING", "file_not_found",
                              "File not found.", object_name=name)
        try:
            contents, content_type = self.backend.read(name)
        except MissingObject:
            return self.error(method, path, 404, "WARNING", "file_not_found",
                              "File not found.", object_name=name)
        except Exception as exc:
            return self.error(method, path, 500, "ERROR", "storage_error",
                              "Unable to read the storage object.", object_name=name,
                              error_type=type(exc).__name__)
        return 200, contents, content_type


class FileServer(HTTPServer):
    # Keep this constant across Python versions and all stress-test rounds.
    request_queue_size = 5

    def __init__(self, address, application):
        self.application = application
        super().__init__(address, FileHandler)

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(10)
        return connection, address


class FileHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_):
        # Per-success stdout would distort the stress test. Errors use Application.log.
        pass

    def reply(self, result):
        status, data, content_type = result
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        if self.command != "HEAD":
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError, socket.timeout):
                pass

    def dispatch(self):
        app = self.server.application
        body = b""
        if self.command == "POST":
            try:
                lengths = self.headers.get_all("Content-Length", [])
                if self.headers.get("Transfer-Encoding") or len(lengths) != 1:
                    raise ValueError("ambiguous or missing request length")
                length = int(lengths[0])
                if not 0 <= length <= MAX_BODY:
                    raise ValueError("invalid body size")
                body = self.rfile.read(length)
                if len(body) != length:
                    raise ValueError("incomplete body")
            except (ValueError, socket.timeout):
                self.reply(app.error(self.command, self.path, 400, "WARNING",
                                     "invalid_payload", "Invalid POST body or Content-Length."))
                return
        self.reply(app.handle(self.command, self.path,
                              self.headers.get("X-country", ""), body))

    do_GET = do_POST = dispatch
    do_PUT = do_DELETE = do_HEAD = do_CONNECT = do_OPTIONS = do_TRACE = do_PATCH = dispatch

    def __getattr__(self, name):
        if name.startswith("do_"):
            return self.dispatch
        raise AttributeError(name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8080")))
    args = parser.parse_args()
    project, bucket = os.environ["PROJECT_ID"], os.environ["BUCKET_NAME"]
    app = Application(bucket, CloudBackend(project, bucket, os.environ["TOPIC_ID"]))
    with FileServer(("0.0.0.0", args.port), app) as server:
        print(f"Listening on port {args.port}; single request worker; queue=5", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
