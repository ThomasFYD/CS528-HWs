#!/usr/bin/env python3
"""Observe the instructor client's real headers against a localhost-only server."""
import argparse
import hashlib
import json
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("report/evidence/client-probe.json"))
    args = parser.parse_args()
    client = args.client.expanduser().resolve()
    records = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_):
            pass

        def capture(self):
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length) if length else b""
            records.append({"method": self.command, "path": self.path,
                            "headers": dict(self.headers.items()),
                            "body": body.decode(errors="replace")})
            payload = b"<!doctype html><title>HW5 local probe</title><p>OK</p>\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Connection", "close")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(payload)
            self.close_connection = True

        do_GET = do_POST = do_PUT = do_DELETE = do_HEAD = do_OPTIONS = capture

        def __getattr__(self, name):
            if name.startswith("do_"):
                return self.capture
            raise AttributeError(name)

    help_result = subprocess.run([str(client), "-h"], capture_output=True, text=True,
                                 timeout=30, check=True)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    command = [str(client), "-d", "127.0.0.1", "-p", str(server.server_port),
               "-b", "none", "-w", "data", "-n", "20", "-i", "100",
               "-r", "528", "-t", "5"]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=180)
    finally:
        server.shutdown()
        server.server_close()
        worker.join()
    evidence = {"client_sha256": hashlib.sha256(client.read_bytes()).hexdigest(),
                "help": help_result.stdout, "command": command,
                "exit_code": result.returncode, "stdout": result.stdout,
                "stderr": result.stderr, "requests": records}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2) + "\n")
    unique = {}
    for record in records:
        for key, value in record["headers"].items():
            if key.lower().startswith("x-"):
                unique.setdefault(key, set()).add(value)
    print(json.dumps({"requests_observed": len(records), "exit_code": result.returncode,
                      "custom_headers": {k: sorted(v) for k, v in unique.items()},
                      "first_request": records[0] if records else None,
                      "evidence": str(args.output.resolve())}, indent=2))
    if result.returncode or not records:
        print(result.stdout, result.stderr)
        raise SystemExit("Client probe did not complete successfully; retain this output.")


if __name__ == "__main__":
    main()
