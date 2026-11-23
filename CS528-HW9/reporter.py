"""HW3 Pub/Sub receive/print/ack loop, adapted to a VM's attached identity."""

import json
import os
import time
from datetime import datetime, timezone


def process_message(client, subscription, received):
    try:
        event = json.loads(received.message.data.decode())
        if (not isinstance(event, dict) or event.get("event") != "forbidden_country"
                or not isinstance(event.get("event_id"), str)):
            raise ValueError("invalid forbidden-country event")
        event["pubsub_message_id"] = received.message.message_id
        event["received_at"] = datetime.now(timezone.utc).isoformat()
        print("FORBIDDEN " + json.dumps(event), flush=True)
        # HW4 asks for stdout. journald retains it locally; no bucket write grant.
        # At-least-once delivery means a repeated event_id may appear after failure.
        client.acknowledge(request={"subscription": subscription,
                                    "ack_ids": [received.ack_id]}, timeout=20)
        return True
    except Exception as exc:
        print(f"RETRY message_id={received.message.message_id} "
              f"error_type={type(exc).__name__}", flush=True)
        return False  # Ack deadline expires; do not discard a failed event.


def main():
    from google.api_core.exceptions import (
        DeadlineExceeded, InternalServerError, ServiceUnavailable, TooManyRequests,
    )
    from google.cloud import pubsub_v1

    with pubsub_v1.SubscriberClient() as client:
        subscription = client.subscription_path(os.environ["PROJECT_ID"], os.environ["SUBSCRIPTION_ID"])
        print(f"Listening on {subscription} using VM service-account credentials", flush=True)
        delay = 2
        while True:
            try:
                response = client.pull(request={"subscription": subscription, "max_messages": 10},
                                       retry=None, timeout=30)
            except DeadlineExceeded:
                time.sleep(1)
                continue
            except (InternalServerError, ServiceUnavailable, TooManyRequests) as exc:
                print(f"PULL_RETRY {type(exc).__name__}; delay={delay}", flush=True)
                time.sleep(delay)
                delay = min(30, delay * 2)
                continue
            delay = 2
            if not response.received_messages:
                time.sleep(1)
            for received in response.received_messages:
                if not process_message(client, subscription, received):
                    time.sleep(1)


if __name__ == "__main__":
    main()
