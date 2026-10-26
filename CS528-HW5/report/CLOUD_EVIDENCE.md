# HW5 — Cloud operation evidence

Reviewed source: `report/evidence/post-load-20261022T075851442425Z/`.

## Verified stop state

At the end of collection, Cloud SQL had activation policy `NEVER`; Web and Reporter VMs both had state `TERMINATED`; the hourly guard remained `ENABLED`. SQL and its data were retained. The static IP, VM disks and other undeleted resources remained allocated at this stage. This is a verified stop, not the final teardown.

## Hourly SQL guard

Cloud Scheduler recorded 26 completed attempts in the saved log window: 25 HTTP 200 responses and one HTTP 500 response. No scheduled invocation appears during the formal load interval, consistent with the runner pausing the job.

Cloud SQL audit logs identify the guard service account as the actor for four successful `STOP_INSTANCE` operations. For the post-load stop:

| Event | UTC timestamp |
|---|---|
| Initial invocation could not obtain an available Cloud Run instance; HTTP 500 | 2026-10-21 11:05:00.964124 |
| Retry submitted activationPolicy=NEVER | 2026-10-21 11:05:30.055253 |
| Scheduler recorded the retry's HTTP 200 | 2026-10-21 11:05:32.670792 |
| SQL audit recorded completed STOP_INSTANCE, status OK | 2026-10-21 11:06:13.728159 |

The completed stop occurred at **07:06:13 EDT on October 21, 2026**. Operation ID: `2c4be193-7882-407b-b333-130e00000032`. This evidence confirms actual scheduled shutdown; it is stronger than the job merely being enabled. The initial platform error and successful retry are both retained.

## Subscription activity and limits

The saved query window begins one minute before the formal experiment and extends to collection time.

| Observation | Value |
|---|---:|
| Sent-message DELTA samples, summed | 4,347 |
| Acknowledged-message DELTA samples, summed | 4,343 |
| Latest sampled unacknowledged backlog | 0 |
| Latest backlog sample time (UTC) | 2026-10-22 07:58:00 |

Both count series are labeled `delivery_type=pull`. The resource-level IAM binding grants subscriber access to the HW5 Reporter service account. These observations support that subscription delivery and acknowledgments were active; the collected metrics do not identify individual messages or reproduce Reporter stdout.

The count difference is **four** and remains unreconciled. Google documents that Pub/Sub monitoring can have [gaps in its metrics](https://docs.cloud.google.com/pubsub/docs/monitoring), but the saved samples do **not** establish that gaps caused this particular difference. We do not claim that all 4,347 individual messages were proven acknowledged. The separate SQL experiment still contains all 100,000 requests, all 4,347 matching error rows and all 100,000 timing rows.

## Cleanup scope

The prepared cleanup keeps Cloud SQL and its data, the database password secret, the original HW2 bucket and local evidence. It removes the owned VMs and boot disks, releases the static IP, and removes the HW5 network, Pub/Sub resources, guard deployment and deployment artifacts. Function source cleanup is limited to exact object generations named by the owned function descriptor; the Google-managed shared source bucket is retained. Cleanup completed. The saved `cleanup-verification.json` confirms SQL state `STOPPED` with activation policy `NEVER`, both VMs absent, the static address absent and the scheduler job absent. These fields were independently reviewed in `cleanup-review.json`. Other cleanup actions are supported by the successful completion message, rather than a separate full inventory. Retained SQL storage and the password secret may still incur charges.
