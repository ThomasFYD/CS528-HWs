"""HW3 HTTP function: serve files, filter countries, publish denied requests."""

import json
import mimetypes
import os
import uuid
from datetime import datetime, timezone
from functools import lru_cache

import functions_framework
from flask import Response
from google.api_core.exceptions import GoogleAPICallError, NotFound
from google.auth.exceptions import GoogleAuthError
from google.cloud import pubsub_v1, storage


BUCKET_NAME = os.environ.get("BUCKET_NAME", "cs528-hw2-yf-2026")
PROJECT_ID = os.environ.get("PROJECT_ID", "dazzling-seat-508219-j3")
TOPIC_ID = os.environ.get("TOPIC_ID", "cs528-hw3-forbidden")
DATA_PREFIX = "data/"

# This is the list specified by the homework, not a current legal sanctions list.
FORBIDDEN_COUNTRIES = (
    "North Korea", "Iran", "Cuba", "Myanmar", "Iraq", "Libya", "Sudan",
    "Zimbabwe", "Syria",
)
COUNTRY_NAMES = {name.casefold(): name for name in FORBIDDEN_COUNTRIES}
COUNTRY_NAMES.update({
    "korea, democratic people's republic of": "North Korea",
    "democratic people's republic of korea": "North Korea",
    "iran, islamic republic of": "Iran",
    "syrian arab republic": "Syria",
})


@lru_cache(maxsize=1)
def get_publisher():
    return pubsub_v1.PublisherClient()


@lru_cache(maxsize=1)
def get_bucket():
    # In the cloud, credentials come from the attached runtime service account.
    return storage.Client().bucket(BUCKET_NAME)


def error_response(request, status, event, message, object_name=None, **details):
    """Write one plain-text log and one structured JSON log per error."""
    entry = {
        "severity": "ERROR",
        "message": message,
        "event": event,
        "status": status,
        "method": request.method,
        "path": request.path,
        "country": request.headers.get("X-country", ""),
        "object_name": object_name,
        **details,
    }
    print(f"{status} {event}: {message}", flush=True)
    # Cloud Logging recognizes serialized JSON written to standard output.
    print(json.dumps(entry, ensure_ascii=False), flush=True)
    return Response(
        message + "\n",
        status=status,
        content_type="text/plain; charset=utf-8",
        headers={"Cache-Control": "no-store"},
    )


def object_name_from_filename(filename):
    """Accept an object path with or without this bucket's URL prefix."""
    name = filename.lstrip("/")
    bucket_prefix = BUCKET_NAME + "/"
    if name.startswith(bucket_prefix):
        name = name[len(bucket_prefix):]
    return name


def deny_forbidden_country(request):
    raw_country = request.headers.get("X-country", "")
    canonical = COUNTRY_NAMES.get(" ".join(raw_country.split()).casefold())
    if canonical is None:
        return None

    event = {
        "event_id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": "forbidden_country",
        "status": 400,
        "country": canonical,
        "country_header": raw_country,
        "method": request.method,
        "path": request.path,
        "message": f"Permission denied: request from {canonical}.",
    }
    try:
        publisher = get_publisher()
        future = publisher.publish(
            publisher.topic_path(PROJECT_ID, TOPIC_ID),
            json.dumps(event, ensure_ascii=False).encode("utf-8"),
            event_id=event["event_id"],
        )
        # Wait for publication before the function can return and be suspended.
        message_id = future.result(timeout=15)
    except Exception as exc:
        # Fail closed. A 503 identifies a delivery failure, never a served file.
        return error_response(
            request, 503, "pubsub_publish_failed",
            "Permission denied; unable to confirm notification delivery.",
            event_id=event["event_id"], error_type=type(exc).__name__,
        )
    return error_response(
        request, 400, "forbidden_country", event["message"],
        event_id=event["event_id"], pubsub_message_id=message_id,
        country_canonical=canonical,
    )


@functions_framework.http
def get_file(request):
    # Check this explicitly: the assignment requires 501 for every other method.
    if request.method not in ("GET", "POST"):
        return error_response(
            request, 501, "unsupported_method", "HTTP method not implemented."
        )

    denied = deny_forbidden_country(request)
    if denied is not None:
        return denied

    if request.method == "GET":
        filename = request.path
    else:
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return error_response(
                request, 400, "invalid_payload", "POST requires a JSON object."
            )
        filename = payload.get("filename")
        if not isinstance(filename, str) or not filename:
            return error_response(
                request, 400, "invalid_payload",
                "POST requires a nonempty string field named filename.",
            )

    object_name = object_name_from_filename(filename)

    # Serve the HW2 dataset. The separate hw3-logs/ prefix is not a web endpoint.
    if not object_name.startswith(DATA_PREFIX) or object_name == DATA_PREFIX:
        return error_response(
            request, 404, "file_not_found", "File not found.", object_name
        )

    try:
        blob = get_bucket().blob(object_name)
        contents = blob.download_as_bytes(timeout=30)
    except NotFound:
        return error_response(
            request, 404, "file_not_found", "File not found.", object_name
        )
    except (GoogleAPICallError, GoogleAuthError):
        # A storage/authentication failure is not evidence that a file is absent.
        return error_response(
            request, 500, "storage_error",
            "Unable to read the storage object.", object_name,
        )

    content_type = (
        blob.content_type
        or mimetypes.guess_type(object_name)[0]
        or "application/octet-stream"
    )
    return Response(
        contents,
        status=200,
        content_type=content_type,
        headers={"Cache-Control": "no-store"},
    )
