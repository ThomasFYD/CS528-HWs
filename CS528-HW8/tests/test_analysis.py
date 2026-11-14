import unittest
from analyze import distribution, trial_summary


def row(seq, start, zone="us-central1-c", ok=True):
    return {"sequence": seq, "started_epoch": start, "finished_epoch": start + .2,
            "status": 200 if ok else None, "zone": zone if ok else None,
            "ok": ok, "error": None if ok else "TimeoutError"}


class AnalysisTests(unittest.TestCase):
    def summary(self, rows, health=None):
        return trial_summary(rows, health or [],
                             {"phase": "trial-1-stop", "before_epoch": 100, "after_epoch": 100.1},
                             {"before_epoch": 140, "after_epoch": 140.1, "ready_epoch": 141},
                             "us-central1-a", "us-central1-c")

    def test_first_survivor_success_does_not_define_failover(self):
        result = self.summary([row(0, 101), row(1, 102, ok=False), row(2, 103), row(3, 104)])
        self.assertAlmostEqual(result["client_sustained_success_completion_delay_s"], 3.1)
        self.assertEqual(result["failure_request_sequences"], [1])

    def test_no_errors_does_not_claim_instant_failover(self):
        result = self.summary([row(0, 101), row(1, 102)])
        self.assertIsNone(result["client_sustained_success_completion_delay_s"])

    def test_failed_probe_excluded_from_ratio_but_preserved(self):
        result = distribution([row(0, 1, "us-central1-a"), row(1, 2), row(2, 3, ok=False)],
                              ["us-central1-a", "us-central1-c"])
        self.assertEqual(result["successful_200"], 2)
        self.assertEqual(result["attempts"], 3)
        self.assertEqual(result["transport_errors"], 1)
        self.assertEqual(result["percent"], {"us-central1-a": 50, "us-central1-c": 50})

    def test_health_from_next_trial_not_used_as_first_trial_failover(self):
        health = [{"sent_epoch": 180, "received_epoch": 181,
                   "states": {"cs528-hw8-web-a": "UNHEALTHY"}}]
        self.assertIsNone(self.summary([row(0, 101)], health)["api_unhealthy_observed_delay_s"])

    def test_recovery_measured_from_restart_and_app_ready(self):
        result = self.summary([row(0, 101), row(1, 143, "us-central1-a")])
        self.assertAlmostEqual(result["recovery_first_zone_a_response_delay_s"], 3.2)
        self.assertAlmostEqual(result["recovery_after_app_ready_delay_s"], 2.2)


if __name__ == "__main__":
    unittest.main()
