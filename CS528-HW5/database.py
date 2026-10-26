"""Cloud SQL connector, schema, and atomic request/error persistence."""
import base64
import binascii
import os
import subprocess
from datetime import datetime, timedelta, timezone

import config


def schema():
    from sqlalchemy import (MetaData, Table, Column, String, DateTime, Integer,
                            BigInteger, Boolean, ForeignKey, UniqueConstraint)
    from sqlalchemy.dialects.mysql import DATETIME
    metadata = MetaData()
    timestamp = DateTime().with_variant(DATETIME(fsp=6), "mysql")
    requests = Table("requests", metadata,
        Column("request_id", String(36), primary_key=True),
        Column("request_time", timestamp, nullable=False, unique=True),
        Column("run_id", String(64), index=True),
        Column("method", String(32), nullable=False),
        Column("requested_file", String(1024), nullable=False),
        Column("country", String(128)), Column("client_ip", String(45)),
        Column("peer_ip", String(45)), Column("gender", String(32)),
        Column("age", String(32)), Column("income", String(32)),
        Column("is_banned", Boolean, nullable=False),
        Column("client_time", String(64)), Column("time_of_day", String(8)),
        Column("http_status", Integer, nullable=False),
        mysql_charset="utf8mb4")
    # Exactly the three assignment fields; request_time is a PK and FK.
    errors = Table("failed_requests", metadata,
        Column("request_time", timestamp, ForeignKey("requests.request_time"), primary_key=True),
        Column("requested_file", String(1024), nullable=False),
        Column("error_code", Integer, nullable=False), mysql_charset="utf8mb4")
    timings = Table("request_timings", metadata,
        Column("request_id", String(36), ForeignKey("requests.request_id"), primary_key=True),
        Column("extract_ns", BigInteger, nullable=False),
        Column("storage_ns", BigInteger, nullable=False),
        Column("response_ns", BigInteger, nullable=False),
        Column("database_ns", BigInteger, nullable=False),
        Column("total_ns", BigInteger, nullable=False),
        Column("storage_attempted", Boolean, nullable=False),
        Column("response_sent", Boolean, nullable=False), mysql_charset="utf8mb4")
    return metadata, requests, errors, timings


def _local_gcloud_value(parts, purpose):
    """Capture credential output in memory, with a bounded noninteractive call."""
    try:
        result = subprocess.run(
            ["gcloud", *parts, f"--project={config.PROJECT_ID}", "--quiet", "--verbosity=error"],
            capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60,
            env={**os.environ, "CLOUDSDK_CORE_DISABLE_PROMPTS": "true"})
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Local {purpose} timed out after 60 seconds; check network connectivity.") from None
    if result.returncode:
        # Neither stdout nor stderr may be echoed: these commands return secrets.
        raise RuntimeError(f"Local {purpose} failed (gcloud exit {result.returncode}); "
                           "check gcloud login and access to the homework project.")
    value = result.stdout.strip()
    if not value:
        raise RuntimeError(f"Local {purpose} returned no data.")
    return value


def gcloud_credentials():
    """Use the user's gcloud login without creating or revoking ADC credentials."""
    from google.auth.credentials import Credentials

    class GcloudCredentials(Credentials):
        def refresh(self, request):
            self.token = _local_gcloud_value(["auth", "print-access-token"], "access-token refresh")
            self.expiry = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=45)

    return GcloudCredentials()


def create_database(local=False):
    import sqlalchemy
    from google.cloud import secretmanager
    from google.cloud.sql.connector import Connector, IPTypes
    credentials = gcloud_credentials() if local else None
    if local:
        # Local gcloud already works over HTTPS. Avoid the separate gRPC secret
        # access/auth callback that timed out before the load clients launched.
        encoded = _local_gcloud_value(
            ["secrets", "versions", "access", "latest", f"--secret={config.PASSWORD_SECRET}",
             "--format=get(payload.data)"], "database-password retrieval")
        try:
            password = base64.b64decode(encoded, altchars=b"-_", validate=True).decode("utf-8")
        except (ValueError, binascii.Error, UnicodeDecodeError):
            raise RuntimeError("Local database-password retrieval returned an invalid encoded payload.") from None
        if not password:
            raise RuntimeError("Local database-password retrieval returned an empty password.")
    else:
        secret_client = secretmanager.SecretManagerServiceClient(credentials=credentials)
        secret_path = f"projects/{config.PROJECT_ID}/secrets/{config.PASSWORD_SECRET}/versions/latest"
        password = secret_client.access_secret_version(request={"name": secret_path}).payload.data.decode()
    connector = Connector(credentials=credentials, refresh_strategy="LAZY")

    def connect():
        return connector.connect(config.INSTANCE_CONNECTION_NAME, "pymysql",
            user=config.DB_USER, password=password, db=config.DB_NAME,
            ip_type=IPTypes.PUBLIC, charset="utf8mb4", connect_timeout=20)

    engine = sqlalchemy.create_engine("mysql+pymysql://", creator=connect,
        pool_size=4, max_overflow=4, pool_timeout=30, pool_recycle=1800, pool_pre_ping=True)
    return Database(engine, connector)


class Database:
    def __init__(self, engine, connector=None):
        self.engine, self.connector = engine, connector
        self.metadata, self.requests, self.errors, self.timings = schema()

    def setup(self):
        from sqlalchemy import inspect
        existing = set(inspect(self.engine).get_table_names())
        self.metadata.create_all(self.engine, checkfirst=True)
        inspector = inspect(self.engine)
        for table in self.metadata.sorted_tables:
            actual = {c["name"] for c in inspector.get_columns(table.name)}
            if actual != set(table.columns.keys()):
                raise RuntimeError(f"Existing {table.name} schema differs; no destructive migration performed")
            expected_pk = [column.name for column in table.primary_key.columns]
            if inspector.get_pk_constraint(table.name)["constrained_columns"] != expected_pk:
                raise RuntimeError(f"Unexpected primary key for {table.name}")
        return {"created": sorted(set(self.metadata.tables) - existing),
                "reused": sorted(set(self.metadata.tables) & existing)}

    def latest_time(self):
        from sqlalchemy import select, func
        with self.engine.connect() as conn:
            return conn.scalar(select(func.max(self.requests.c.request_time)))

    def save_request(self, record, status):
        # Both inserts commit together. A DB failure must never produce HTTP 200.
        with self.engine.begin() as conn:
            conn.execute(self.requests.insert().values(**record, http_status=status))
            if status != 200:
                conn.execute(self.errors.insert().values(request_time=record["request_time"],
                    requested_file=record["requested_file"], error_code=status))

    def save_timing(self, request_id, timings):
        with self.engine.begin() as conn:
            conn.execute(self.timings.insert().values(request_id=request_id, **timings))

    def snapshot(self, run_id=None):
        from sqlalchemy import select
        req_query = select(self.requests).order_by(self.requests.c.request_time)
        err_query = select(self.errors).join(self.requests,
            self.errors.c.request_time == self.requests.c.request_time).order_by(self.errors.c.request_time)
        timing_query = select(self.timings).join(self.requests)
        if run_id is not None:
            req_query = req_query.where(self.requests.c.run_id == run_id)
            err_query = err_query.where(self.requests.c.run_id == run_id)
            timing_query = timing_query.where(self.requests.c.run_id == run_id)
        with self.engine.connect() as conn:
            req = [dict(row) for row in conn.execute(req_query).mappings()]
            err = [dict(row) for row in conn.execute(err_query).mappings()]
            timing = [dict(row) for row in conn.execute(timing_query).mappings()]
        return {"run_id": run_id, "requests": req, "failed_requests": err, "request_timings": timing}

    def counts(self, run_id=None):
        from sqlalchemy import select, func
        output = {}
        with self.engine.connect() as conn:
            for name, table in (("requests", self.requests), ("failed_requests", self.errors), ("request_timings", self.timings)):
                query = select(func.count()).select_from(table)
                if run_id is not None:
                    if table is self.errors:
                        query = query.join(self.requests, self.errors.c.request_time == self.requests.c.request_time)
                    elif table is self.timings:
                        query = query.join(self.requests)
                    query = query.where(self.requests.c.run_id == run_id)
                output[name] = conn.scalar(query)
        return output

    def close(self):
        self.engine.dispose()
        if self.connector:
            self.connector.close()
