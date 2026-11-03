"""Read HW5 data, audit dependencies, and verify a lossless HW6 migration."""
import hashlib
import ipaddress
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import config as C

ROOT = Path(__file__).resolve().parent


def audit_source(snapshot, expected=C.EXPECTED_ROWS):
    rows = snapshot["requests"]
    if len(rows) != expected:
        raise ValueError(f"Expected {expected} requests; found {len(rows)}")
    ips, policies = defaultdict(set), defaultdict(set)
    ids, times = set(), set()
    for r in rows:
        for field in ("request_id", "request_time", "client_ip", "country", "age", "gender", "income", "client_time"):
            if r.get(field) is None or r.get(field) == "":
                raise ValueError(f"Missing {field}; this migration requires complete formal-run metadata")
        ipaddress.IPv4Address(r["client_ip"])
        if r["request_id"] in ids or str(r["request_time"]) in times:
            raise ValueError("Duplicate request ID or request timestamp")
        ids.add(r["request_id"])
        times.add(str(r["request_time"]))
        ips[r["client_ip"]].add(r["country"])
        policies[r["country"]].add(bool(r["is_banned"]))
        derived = datetime.strptime(r["client_time"], "%Y-%m-%d %H:%M:%S").strftime("%H:%M:%S")
        if derived != r["time_of_day"]:
            raise ValueError("client_time does not determine stored time_of_day")
        if r["run_id"] != C.RUN_ID:
            raise ValueError("Unexpected experiment run")
    if any(len(v) != 1 for v in ips.values()):
        raise ValueError("IP -> country dependency violated")
    if any(len(v) != 1 for v in policies.values()):
        raise ValueError("country -> is_banned dependency violated")
    expected_errors = [{"request_time": r["request_time"], "requested_file": r["requested_file"],
                        "error_code": r["http_status"]} for r in rows if r["http_status"] != 200]
    if fingerprint(expected_errors, "request_time") != fingerprint(snapshot["failed_requests"], "request_time"):
        raise ValueError("Failure rows cannot be reconstructed exactly")
    tids = [r["request_id"] for r in snapshot["request_timings"]]
    if len(tids) != len(set(tids)) or set(tids) != ids:
        raise ValueError("Timing records must match requests one to one")
    return {"requests": len(rows), "clients": len(ips), "countries": len(policies),
            "failed_requests": len(expected_errors), "request_timings": len(tids),
            "ip_country_conflicts": 0, "country_policy_conflicts": 0,
            "missing_required_fields": 0, "run_id": C.RUN_ID}


def fingerprint(rows, key):
    # MySQL returns BOOLEAN as 0/1; local JSON uses true/false.
    normalized = []
    for row in rows:
        normalized.append({k: int(v) if k in ("is_banned", "storage_attempted", "response_sent")
                           else str(v) if isinstance(v, datetime) else v for k, v in row.items()})
    payload = json.dumps(sorted(normalized, key=lambda r: str(r[key])), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def hashes(snapshot):
    return {name: fingerprint(snapshot[name], "request_time" if name == "failed_requests" else "request_id")
            for name in ("requests", "failed_requests", "request_timings")}


def read_snapshot(conn, database, view=False):
    from sqlalchemy import text
    if database not in (C.SOURCE_DB, C.TARGET_DB):
        raise ValueError("Unexpected database")
    table = "request_details" if view else "requests"
    params = {"run_id": C.RUN_ID}
    queries = {
        "requests": f"SELECT * FROM {database}.{table} WHERE run_id=:run_id",
        "failed_requests": f"SELECT f.* FROM {database}.failed_requests f JOIN {database}.requests r USING(request_time) WHERE r.run_id=:run_id",
        "request_timings": f"SELECT t.* FROM {database}.request_timings t JOIN {database}.requests r USING(request_id) WHERE r.run_id=:run_id",
    }
    return {"run_id": C.RUN_ID, **{name: [dict(r) for r in conn.execute(text(q), params).mappings()]
                                   for name, q in queries.items()}}


def sql_statements(name):
    # These reviewed SQL files contain no semicolons inside literals.
    lines = [line for line in (ROOT / name).read_text().splitlines() if not line.lstrip().startswith("--")]
    return [s.strip() for s in "\n".join(lines).split(";") if s.strip()]


def connect():
    """VM identity uses Secret Manager and the encrypted Cloud SQL connector."""
    import sqlalchemy
    from google.cloud import secretmanager
    from google.cloud.sql.connector import Connector, IPTypes
    secret = secretmanager.SecretManagerServiceClient(transport="rest")
    password = secret.access_secret_version(request={
        "name": f"projects/{C.PROJECT}/secrets/{C.PASSWORD_SECRET}/versions/latest"
    }).payload.data.decode()
    connector = Connector(refresh_strategy="LAZY")
    engine = sqlalchemy.create_engine("mysql+pymysql://", creator=lambda: connector.connect(
        C.CONNECTION_NAME, "pymysql", user=C.DB_USER, password=password, db=C.SOURCE_DB,
        ip_type=IPTypes.PUBLIC, charset="utf8mb4", connect_timeout=30),
        pool_size=1, max_overflow=0, pool_pre_ping=True)
    return engine, connector


def migrate(engine):
    from sqlalchemy import text
    # DDL commits implicitly in MySQL; keep it outside the data transaction.
    with engine.begin() as conn:
        for statement in sql_statements("schema.sql"):
            conn.execute(text(statement))
    with engine.begin() as conn:
        source = read_snapshot(conn, C.SOURCE_DB)
        audit = audit_source(source)
        for statement in sql_statements("migrate.sql"):
            conn.execute(text(statement), {"run_id": C.RUN_ID})
        target = read_snapshot(conn, C.TARGET_DB, view=True)
        audit_source(target)
        old_hashes, new_hashes = hashes(source), hashes(target)
        if old_hashes != new_hashes:
            raise ValueError("Migration round-trip mismatch; new INSERTs rolled back")
        counts = {table: conn.scalar(text(f"SELECT COUNT(*) FROM hw6.{table}"))
                  for table in ("countries", "clients", "requests", "request_timings")}
        if any(counts[k] != audit[k] for k in counts):
            raise ValueError("HW6 contains unexpected extra rows; new INSERTs rolled back")
    audit.update(source_hashes=old_hashes, reconstructed_hashes=new_hashes,
                 lossless=True, source_database=C.SOURCE_DB, target_database=C.TARGET_DB,
                 scope="Complete formal HW5 run; other HW5 experiments remain in hw5")
    return target["requests"], audit
