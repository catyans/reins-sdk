import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from reins_sdk import AdmissionDenied, Charge, LocalReinsClient


class LocalLedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.client = LocalReinsClient(Path(self.temp.name) / "ledger.sqlite3")

    def tearDown(self):
        self.temp.cleanup()

    def test_budget_wrapup_and_exact_settlement(self):
        task = self.client.start_task(workflow="research", budget="0.10", wrapup_reserve="0.02")
        first = self.client.reserve(task_id=task, model="m", max_cost="0.08", operation_key="source")
        with self.assertRaises(AdmissionDenied):
            self.client.reserve(task_id=task, model="m", max_cost="0.01", operation_key="extra")
        self.client.settle(request_id=first, actual_cost="0.06", input_tokens=10, output_tokens=2)
        final = self.client.reserve(task_id=task, model="m", max_cost="0.04", phase="wrapup")
        self.client.settle(request_id=final, actual_cost="0.03")
        self.client.finish_task(task, accepted=True)
        summary = self.client.summary()
        self.assertEqual((summary["confirmed_usd"], summary["reserved_usd"], summary["denied"]),
                         ("0.090000", "0.000000", 1))
        with self.assertRaises(ValueError):
            self.client.settle(request_id=first, actual_cost="0.07", input_tokens=10, output_tokens=2)

    def test_repeat_limit_and_uncertain_charges(self):
        task = self.client.start_task(workflow="agent", budget="1", max_operations=2)
        rid = self.client.reserve(task_id=task, model="m", max_cost="0.4", operation_key="step-1")
        self.client.uncertain(rid)
        with self.assertRaises(AdmissionDenied):
            self.client.reserve(task_id=task, model="m", max_cost="0.1", operation_key="step-1")
        self.client.reserve(task_id=task, model="m", max_cost="0.4", operation_key="step-2")
        with self.assertRaises(AdmissionDenied):
            self.client.reserve(task_id=task, model="m", max_cost="0.01")
        self.assertEqual(self.client.summary()["reserved_usd"], "0.800000")

    def test_concurrent_admission_never_oversubscribes(self):
        task = self.client.start_task(workflow="team", budget="1")
        def reserve(index):
            try:
                self.client.reserve(task_id=task, model="m", max_cost="0.20",
                                    operation_key=str(index))
                return True
            except AdmissionDenied:
                return False
        with ThreadPoolExecutor(max_workers=12) as pool:
            outcomes = list(pool.map(reserve, range(20)))
        self.assertEqual(sum(outcomes), 5)
        self.assertEqual(self.client.summary()["reserved_usd"], "1.000000")

    def test_savings_only_for_accepted_settled_match(self):
        baseline = self.client.start_task(workflow="refresh", budget="1", case_id="c1", variant="baseline")
        candidate = self.client.start_task(workflow="refresh", budget="1", case_id="c1", variant="candidate")
        for task, cost in [(baseline, "0.5"), (candidate, "0.2")]:
            charge = self.client.run_paid_call(task_id=task, model="m", max_cost="0.6",
                                               execute=lambda cost=cost: Charge("ok", cost))
            self.assertEqual(charge.result, "ok")
        self.client.finish_task(baseline, accepted=True)
        self.assertEqual(self.client.summary()["matched_pairs"], [])
        self.client.finish_task(candidate, accepted=True)
        self.assertEqual(self.client.summary()["matched_pairs"][0]["difference_usd"], "0.300000")

    def test_failed_provider_keeps_reservation(self):
        task = self.client.start_task(workflow="failure", budget="0.1")
        def failing():
            raise RuntimeError("provider timed out")
        with self.assertRaises(RuntimeError):
            self.client.run_paid_call(task_id=task, model="m", max_cost="0.1", execute=failing)
        self.assertEqual(self.client.summary()["reserved_usd"], "0.100000")


if __name__ == "__main__":
    unittest.main()
