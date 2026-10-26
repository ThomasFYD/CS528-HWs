"""Compute HW5 answers from an isolated run's actual SQL records."""
from collections import Counter
import math


def describe_ns(values):
    if not values:
        return {"count": 0, "mean_ms": None, "p50_ms": None, "p95_ms": None, "max_ms": None}
    values = sorted(values)
    return {"count": len(values), "mean_ms": sum(values) / len(values) / 1e6,
        "p50_ms": values[math.ceil(0.50 * len(values)) - 1] / 1e6,
        "p95_ms": values[math.ceil(0.95 * len(values)) - 1] / 1e6, "max_ms": values[-1] / 1e6}


def modes(counter):
    maximum = max(counter.values(), default=0)
    return [{"group": group, "requests": count} for group, count in sorted(counter.items()) if count == maximum]


def summarize(snapshot, expected=None):
    requests, errors, timings = (snapshot[name] for name in ("requests", "failed_requests", "request_timings"))
    statuses = Counter(row["http_status"] for row in requests)
    age = Counter(row["age"] or "(missing)" for row in requests)
    income = Counter(row["income"] or "(missing)" for row in requests)
    gender = Counter(row["gender"] or "(missing)" for row in requests)
    country = Counter(row["country"] or "(missing)" for row in requests)
    request_ids = {row["request_id"] for row in requests}
    timing_ids = {row["request_id"] for row in timings}
    required_errors = {(str(row["request_time"]), row["requested_file"], row["http_status"])
                       for row in requests if row["http_status"] != 200}
    actual_errors = {(str(row["request_time"]), row["requested_file"], row["error_code"]) for row in errors}
    metadata_missing = sum(any(row.get(key) is None for key in
        ("country", "client_ip", "gender", "age", "income", "client_time", "time_of_day")) for row in requests)
    pair_fields = ("requested_file", "country", "client_ip", "gender", "age", "income", "time_of_day")
    pairs = Counter(tuple(row.get(key) for key in pair_fields) for row in requests)
    integrity = {"expected_requests": expected, "observed_requests": len(requests),
        "expected_count_matches": expected is None or len(requests) == expected,
        "unique_request_ids": len(request_ids) == len(requests),
        "error_rows_match_exactly": required_errors == actual_errors and len(errors) == len(actual_errors),
        "timing_rows_complete": request_ids == timing_ids and len(timings) == len(timing_ids),
        "response_send_failures": sum(not row["response_sent"] for row in timings),
        "requests_with_missing_metadata": metadata_missing,
        "odd_metadata_multiplicities": sum(count % 2 != 0 for count in pairs.values())}
    integrity["complete"] = all(integrity[key] for key in (
        "expected_count_matches", "unique_request_ids", "error_rows_match_exactly", "timing_rows_complete")) and not integrity["response_send_failures"] and not metadata_missing
    operations = {key: describe_ns([row[key] for row in timings]) for key in
                  ("extract_ns", "storage_ns", "response_ns", "database_ns", "total_ns")}
    operations["storage_when_attempted_ns"] = describe_ns([row["storage_ns"] for row in timings if row["storage_attempted"]])
    return {"run_id": snapshot["run_id"], "total_requests": len(requests),
        "successful_http_200": statuses[200], "unsuccessful_http_non_200": len(requests) - statuses[200],
        "http_status_counts": dict(sorted(statuses.items())),
        "banned_country_requests": sum(bool(row["is_banned"]) for row in requests),
        "gender_counts": dict(sorted(gender.items())),
        "top_5_countries": [{"country": key, "requests": value} for key, value in sorted(country.items(), key=lambda x: (-x[1], x[0]))[:5]],
        "age_counts": dict(sorted(age.items())), "most_frequent_age_groups": modes(age),
        "income_counts": dict(sorted(income.items())), "most_frequent_income_groups": modes(income),
        "timing": operations, "integrity": integrity,
        "notes": ["Age/income groups are the original instructor-client labels, not inferred numeric bins.",
            "X-time is client-simulated and has no supplied time zone. Receipt timestamps are UTC.",
            "HTTP status counts and response-send failures are separate; a completed write is not proof of client receipt.",
            "database_ns includes the metadata/error transaction; the later timing insert is excluded.",
            "Storage averages over all requests include zero for denied/unsupported requests. The attempted-read subset is also reported.",
            "Total time also includes policy checks, Cloud Logging and Pub/Sub waits; it need not equal the four reported stages."]}
