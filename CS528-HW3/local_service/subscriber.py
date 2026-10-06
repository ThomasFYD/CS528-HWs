"""Mac service: pull forbidden-country events, print them, persist, then ack."""

import argparse
import json
import time
from datetime import datetime, timezone

from google.api_core.exceptions import (
    DeadlineExceeded, GoogleAPICallError, InternalServerError,
    ServiceUnavailable, TooManyRequests,
)
from google.auth.exceptions import GoogleAuthError
from google.cloud import pubsub_v1, storage

from gcloud_credentials import GcloudImpersonatedCredentials
from log_store import BucketLog


def process_message(client, subscription, received, log):
    """Never acknowledge a message before its contents have been persisted."""
    message = received.message
    try:
        event = json.loads(message.data.decode("utf-8"))
        if not isinstance(event, dict) or not isinstance(event.get("event_id"), str):
            raise ValueError("Missing event_id")
        if event.get("event") != "forbidden_country":
            raise ValueError("Unexpected event type")
        event["pubsub_message_id"] = message.message_id
        event["received_at"] = datetime.now(timezone.utc).isoformat()
        print("FORBIDDEN " + json.dumps(event, ensure_ascii=False), flush=True)
        appended = log.append(event)
        result = "APPENDED" if appended else "ALREADY_STORED"
        print(f"{result} event_id={event['event_id']}", flush=True)
        client.acknowledge(
            request={"subscription": subscription, "ack_ids": [received.ack_id]},
            timeout=20,
        )
        print(f"ACKED message_id={message.message_id}", flush=True)
        return True
    except Exception as exc:
        # Includes malformed input, storage failures and ambiguous ack failures.
        # Leave it unacknowledged for redelivery; do not discard any event.
        print(
            f"RETRY message_id={message.message_id} error_type={type(exc).__name__}",
            flush=True,
        )
        try:
            client.modify_ack_deadline(
                request={
                    "subscription": subscription, "ack_ids": [received.ack_id],
                    "ack_deadline_seconds": 0,
                }, timeout=20,
            )
        except GoogleAPICallError:
            pass  # The existing acknowledgement deadline will expire anyway.
        return False


def receive_forever(client, subscription, log):
    """Keep pulling through temporary network/service failures; Ctrl+C stops."""
    retry_delay = 2
    recovering = False
    while True:
        try:
            response = client.pull(
                request={"subscription": subscription, "max_messages": 1},
                retry=None, timeout=60,
            )
        except DeadlineExceeded:
            # An idle subscription can time out. Pause also prevents a tight
            # loop if a broken connection returns deadlines immediately.
            time.sleep(1)
            continue
        except (ServiceUnavailable, InternalServerError, TooManyRequests) as exc:
            # The gRPC channel reconnects on subsequent calls. Back off between
            # attempts instead of letting a temporary error terminate the Mac service.
            print(
                f"PULL_RETRY error_type={type(exc).__name__} "
                f"retry_in_seconds={retry_delay}", flush=True,
            )
            time.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 30)
            recovering = True
            continue
        if recovering:
            print("PULL_RESUMED connection recovered", flush=True)
        retry_delay, recovering = 2, False
        if not response.received_messages:
            time.sleep(1)
        for received in response.received_messages:
            if not process_message(client, subscription, received, log):
                time.sleep(5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default="dazzling-seat-508219-j3")
    parser.add_argument("--bucket", default="cs528-hw2-yf-2026")
    parser.add_argument("--subscription", default="cs528-hw3-forbidden-sub")
    parser.add_argument("--account", default="fangyd@bu.edu")
    parser.add_argument(
        "--service-account",
        default="cs528-hw3-sa@dazzling-seat-508219-j3.iam.gserviceaccount.com",
    )
    args = parser.parse_args()
    credentials = GcloudImpersonatedCredentials(
        args.account, args.service_account, args.project,
    )
    credentials.refresh(None)
    # Explicit credentials are essential: changing gcloud configuration alone
    # does not cause Python clients to use the same impersonated identity.
    bucket = storage.Client(project=args.project, credentials=credentials).bucket(args.bucket)
    log = BucketLog(bucket)
    with pubsub_v1.SubscriberClient(credentials=credentials) as client:
        subscription = client.subscription_path(args.project, args.subscription)
        print(f"Authenticated as: {args.service_account}", flush=True)
        print(f"Listening on: {subscription}", flush=True)
        print(f"Log object: gs://{args.bucket}/{log.object_name}", flush=True)
        receive_forever(client, subscription, log)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Subscriber stopped. Unacknowledged messages remain available.", flush=True)
    except GoogleAuthError as exc:
        raise SystemExit(f"Authentication error: {exc}") from None
    except GoogleAPICallError as exc:
        raise SystemExit(f"Cloud API error: {type(exc).__name__}: {exc}") from None
