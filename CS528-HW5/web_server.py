"""HW5: retain HW4 behavior; add atomic SQL logging and per-operation timing."""
import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import config
from database import create_database
from hw4_service import Application, CloudBackend, MAX_BODY
from request_data import RequestClock, extract_headers


class TimedBackend:
    def __init__(self, backend):
        self.backend = backend
        self.local = threading.local()

    def begin(self):
        self.local.storage_ns = 0
        self.local.storage_attempted = False

    def read(self, name):
        self.local.storage_attempted = True
        start = time.perf_counter_ns()
        try:
            return self.backend.read(name)
        finally:
            self.local.storage_ns += time.perf_counter_ns() - start

    def log(self, *args, **kwargs):
        return self.backend.log(*args, **kwargs)

    def publish(self, *args, **kwargs):
        return self.backend.publish(*args, **kwargs)


class FileServer(ThreadingHTTPServer):
    daemon_threads = False
    block_on_close = True
    request_queue_size = 64

    def __init__(self, address, application, database, max_workers=8):
        self.application, self.database = application, database
        self.clock = RequestClock(database.latest_time())
        self.slots = threading.BoundedSemaphore(max_workers)
        super().__init__(address, FileHandler)

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(15)
        return connection, address

    def process_request(self, request, client_address):
        self.slots.acquire()
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


class FileHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def parse_request(self):
        self.request_start_ns = time.perf_counter_ns()
        try:
            return super().parse_request()
        finally:
            self.header_parse_ns = time.perf_counter_ns() - self.request_start_ns

    def log_message(self, *_):
        pass

    def read_request_body(self):
        if self.command != "POST":
            return b""
        lengths = self.headers.get_all("Content-Length", [])
        if self.headers.get("Transfer-Encoding") or len(lengths) != 1:
            raise ValueError("ambiguous or missing Content-Length")
        length = int(lengths[0])
        if not 0 <= length <= MAX_BODY:
            raise ValueError("invalid body size")
        body = self.rfile.read(length)
        if len(body) != length:
            raise ValueError("incomplete body")
        return body

    def send_result(self, result):
        status, payload, content_type = result
        self.close_connection = True
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(payload)
            self.wfile.flush()
            return True
        except (BrokenPipeError, ConnectionResetError, socket.timeout):
            return False

    def dispatch(self):
        total_start = self.request_start_ns
        app, db = self.server.application, self.server.database
        app.backend.begin()
        body, invalid_body = b"", False
        extract_start = time.perf_counter_ns()
        try:
            body = self.read_request_body()
        except (ValueError, socket.timeout):
            invalid_body = True
        record, effective_path = extract_headers(self.headers, self.client_address[0],
            self.command, self.path, body, app.bucket, self.server.clock)
        extract_ns = self.header_parse_ns + time.perf_counter_ns() - extract_start
        if invalid_body:
            result = app.error(self.command, effective_path, 400, "WARNING",
                               "invalid_payload", "Invalid POST body or Content-Length.")
        else:
            result = app.handle(self.command, effective_path, record["country"] or "", body)
        database_start = time.perf_counter_ns()
        try:
            db.save_request(record, result[0])
        except Exception as exc:
            # Journal evidence makes an incomplete DB run visible. Do not silently
            # serve a successful response when its required log could not commit.
            app.log("ERROR", {"event": "database_write_failed", "record": {
                k: str(v) if k == "request_time" else v for k, v in record.items()},
                "planned_status": result[0], "error_type": type(exc).__name__})
            self.send_result((503, b"Database logging unavailable.\n", "text/plain"))
            return
        database_ns = time.perf_counter_ns() - database_start
        response_start = time.perf_counter_ns()
        sent = self.send_result(result)
        response_ns = time.perf_counter_ns() - response_start
        measurements = {"extract_ns": extract_ns,
            "storage_ns": app.backend.local.storage_ns, "response_ns": response_ns,
            "database_ns": database_ns, "total_ns": time.perf_counter_ns() - total_start,
            "storage_attempted": app.backend.local.storage_attempted, "response_sent": sent}
        try:
            # This measurement insert happens after the response. Its overhead is
            # excluded from database_ns and total_ns to avoid self-measurement.
            db.save_timing(record["request_id"], measurements)
        except Exception as exc:
            app.log("ERROR", {"event": "timing_write_failed", "request_id": record["request_id"],
                              "timings": measurements, "error_type": type(exc).__name__})

    do_GET = do_POST = do_PUT = do_DELETE = do_HEAD = do_CONNECT = do_OPTIONS = do_TRACE = do_PATCH = dispatch

    def __getattr__(self, name):
        if name.startswith("do_"):
            return self.dispatch
        raise AttributeError(name)


def main():
    from google.cloud import logging as cloud_logging
    db = create_database()
    try:
        db.setup()
        backend = CloudBackend(config.PROJECT_ID, config.BUCKET_NAME, config.TOPIC_ID)
        backend.logger = cloud_logging.Client(project=config.PROJECT_ID).logger("cs528-hw5-web")
        app = Application(config.BUCKET_NAME, TimedBackend(backend))
        with FileServer(("0.0.0.0", config.PORT), app, db) as server:
            print(json.dumps({"event": "ready", "port": config.PORT, "max_workers": 8}), flush=True)
            server.serve_forever()
    finally:
        db.close()


if __name__ == "__main__":
    main()
