"""One fresh HTTP connection per request, with zone and timing evidence (stdlib)."""
import argparse
import hashlib
import http.client
import json
import random
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path


def utc():
    return datetime.now(timezone.utc).isoformat()


def file_path(bucket, webdir, index):
    parts = [p.strip("/") for p in (bucket, webdir) if p and p.lower() != "none"]
    return "/" + "/".join([*parts, f"{index}.html"])


def request_once(host, port, path, *, method="GET", headers=None, body=None,
                 timeout=2.0, tls=False, sequence=0, phase="manual", expected=200):
    start_wall, start_mono = time.time(), time.monotonic()
    record = {"sequence": sequence, "phase": phase, "started_at": utc(),
              "started_epoch": start_wall, "started_monotonic": start_mono,
              "method": method, "path": path, "expected_status": expected,
              "status": None, "zone": None, "error": None}
    connection = (http.client.HTTPSConnection if tls else http.client.HTTPConnection)(
        host, port, timeout=timeout)
    try:
        connection.connect()
        record["local_port"] = connection.sock.getsockname()[1]
        request_headers = {"Connection": "close", **(headers or {})}
        connection.request(method, path, body=body, headers=request_headers)
        response = connection.getresponse()
        record.update(status=response.status, zone=response.getheader("X-Server-Zone"),
                      response_headers=dict(response.getheaders()))
        digest, size = hashlib.sha256(), 0
        # Bound the overall operation as well as individual socket calls.
        while True:
            remaining = timeout - (time.monotonic() - start_mono)
            if remaining <= 0:
                raise TimeoutError("overall response deadline exceeded")
            if response.fp and hasattr(response.fp, "raw"):
                response.fp.raw._sock.settimeout(remaining)
            chunk = response.read(65536)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
        declared = response.getheader("Content-Length")
        if method != "HEAD" and declared is not None and size != int(declared):
            raise http.client.IncompleteRead(b"", int(declared) - size)
        record.update(bytes=size, sha256=digest.hexdigest())
    except (OSError, http.client.HTTPException, ValueError) as exc:
        record["error"] = type(exc).__name__ + ": " + str(exc)
    finally:
        connection.close()
    record.update(finished_at=utc(), finished_epoch=time.time(),
                  elapsed_seconds=time.monotonic() - start_mono)
    record["ok"] = record["error"] is None and record["status"] == expected and bool(record["zone"])
    return record


def print_record(record):
    print(f"{record['started_at']} #{record['sequence']} {record['phase']} "
          f"HTTP={record['status']} zone={record['zone']} "
          f"elapsed={record['elapsed_seconds']:.3f}s error={record['error']}", flush=True)


def scheduled_requests(count, interval, make_request, on_record):
    """Launch on a monotonic schedule so a failed connection doesn't lower request rate."""
    if count < 1 or interval <= 0:
        raise ValueError("count and interval must be positive")
    start = time.monotonic()
    pending = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        for i in range(count):
            delay = start + i * interval - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            # Never silently queue an unbounded failed-service load.
            for future in pending:
                if future.done():
                    future.result()
            pending = [f for f in pending if not f.done()]
            if len(pending) >= 8:
                raise RuntimeError("Eight requests remain in flight; stop and debug the endpoint")
            def run(sequence=i):
                result = make_request(sequence)
                on_record(result)
            pending.append(pool.submit(run))
        for future in pending:
            future.result()


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("-d", "--domain", required=True)
    p.add_argument("-p", "--port", type=int, default=8080)
    p.add_argument("-b", "--bucket", default="cs528-hw2-yf-2026")
    p.add_argument("-w", "--webdir", default="data")
    p.add_argument("-n", "--num_requests", type=int, default=60)
    p.add_argument("-i", "--index", type=int, default=11999, help="Maximum existing index, inclusive")
    p.add_argument("-r", "--random", type=int, default=528)
    p.add_argument("-t", "--timeout", type=float, default=2.0)
    p.add_argument("-s", "--ssl", action="store_true")
    p.add_argument("--interval", type=float, default=1.0)
    p.add_argument("--country", default="United States")
    p.add_argument("--method", choices=("GET", "POST", "PUT", "DELETE", "HEAD", "OPTIONS", "TRACE", "PATCH"), default="GET")
    p.add_argument("--header", action="append", default=[], help="Additional request header as Name: Value")
    p.add_argument("--expected-status", type=int, default=200)
    p.add_argument("--path", help="Fixed request path instead of random existing file indices")
    p.add_argument("--replay", type=Path, help="JSON list of captured requests: method, path, headers, body")
    p.add_argument("--output", type=Path, default=Path("results/client.jsonl"))
    return p


def main():
    import threading
    args = parser().parse_args()
    if args.timeout <= 0 or args.index < 0:
        raise SystemExit("timeout must be positive and index nonnegative")
    rng = random.Random(args.random)
    requests = []
    headers = {"X-country": args.country}
    for raw in args.header:
        key, sep, value = raw.partition(":")
        if not sep or not key.strip() or "\n" in raw or "\r" in raw:
            raise SystemExit("Use --header 'Name: Value'")
        headers[key.strip()] = value.strip()
    replay = json.loads(args.replay.read_text()) if args.replay else None
    if replay is not None and (not isinstance(replay, list) or not replay):
        raise SystemExit("replay must be a nonempty JSON list")
    for i in range(args.num_requests):
        path = args.path or file_path(args.bucket, args.webdir, rng.randint(0, args.index))
        entry = {"path": path, "method": args.method, "headers": headers,
                 "body": json.dumps({"filename": path}) if args.method == "POST" else None}
        if replay:
            entry = replay[i % len(replay)]
        request_headers = {k: v for k, v in entry.get("headers", {}).items()
                           if k.lower() not in ("host", "connection", "content-length")}
        if entry.get("method", "GET") == "POST":
            request_headers.setdefault("Content-Type", "application/json")
        requests.append({**entry, "headers": request_headers})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    lock = threading.Lock()
    with args.output.open("x") as stream:
        def record(item):
            with lock:
                stream.write(json.dumps(item) + "\n")
                stream.flush()
                print_record(item)
        def make(i):
            entry = requests[i]
            return request_once(args.domain, args.port, entry["path"], method=entry.get("method", "GET"),
                                headers=entry.get("headers"), body=entry.get("body"), timeout=args.timeout,
                                tls=args.ssl, sequence=i, expected=entry.get("expected_status", args.expected_status))
        scheduled_requests(args.num_requests, args.interval, make, record)


if __name__ == "__main__":
    main()
