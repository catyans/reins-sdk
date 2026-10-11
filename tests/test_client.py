import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from reins_sdk import (
    AdmissionDenied,
    Charge,
    ReinsAuthenticationError,
    ReinsClient,
    SettlementUnknown,
)

TOKEN = "w" * 48


class Handler(BaseHTTPRequestHandler):
    requests = []
    action = "continue"
    admission = "continue"
    settle_error = False

    def log_message(self, *_args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.requests.append((self.path, body, self.headers.get("Authorization")))
        if self.headers.get("Authorization") != "Bearer " + TOKEN:
            return self.send_json(403, {"error": "Worker credential required"})
        if self.path == "/api/console/runtime/decision":
            return self.send_json(
                200,
                {
                    "action": self.action,
                    "reason": "test-stop" if self.action == "stop" else "pinned",
                    "configuration": {"config": {"model": "google/test"}},
                },
            )
        if self.path == "/api/reserve":
            return self.send_json(200, {"decision": self.admission, "reason": "test-hold"})
        if self.path == "/api/settle" and self.settle_error:
            return self.send_json(503, {"error": "temporarily unavailable"})
        if self.path == "/api/status":
            return self.send_json(200, {"workflows": [{"id": body["workflow_id"]}]})
        if self.path == "/api/worker-pair/me":
            return self.send_json(200, {"customer_id": "demo-customer", "pairing_id": "demo-pair"})
        if self.path == "/api/worker-pair/start":
            return self.send_json(200, {"workflow_id": "run-" + body["run_key"]})
        return self.send_json(200, {"status": "recorded"})

    def send_json(self, status, body):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class ClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}/api"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)

    def setUp(self):
        Handler.requests = []
        Handler.action = "continue"
        Handler.admission = "continue"
        Handler.settle_error = False
        self.client = ReinsClient(self.url, token=TOKEN)

    def test_paid_call_orders_admission_provider_and_settlement(self):
        called = []

        def execute(config):
            called.append(config)
            return Charge({"answer": 42}, "0.03", {"input_tokens": 5, "output_tokens": 1})

        outcome = self.client.run_paid_call("job-1", execute, max_cost="0.10")
        self.assertEqual(outcome.result, {"answer": 42})
        self.assertEqual(called, [{"model": "google/test"}])
        self.assertEqual(
            [path for path, _, _ in Handler.requests],
            ["/api/console/runtime/decision", "/api/reserve", "/api/settle"],
        )
        _, reserve, _ = Handler.requests[1]
        _, settle, _ = Handler.requests[2]
        self.assertEqual(reserve["model"], "google/test")
        self.assertEqual(reserve["max_cost"], "0.10")
        self.assertEqual(settle["request_id"], reserve["request_id"])
        self.assertEqual(settle["actual_cost"], "0.03")
        self.assertEqual(settle["usage"], {"input_tokens": 5, "output_tokens": 1})
        self.assertTrue(all(auth == "Bearer " + TOKEN for _, _, auth in Handler.requests))

    def test_named_business_validation_reaches_settlement(self):
        self.client.run_paid_call(
            "job-1",
            lambda _: Charge(
                {"answer": "wrong"},
                "0.02",
                success=True,
                validated=False,
                validation_name="invoice-check-v1",
            ),
            max_cost="0.10",
        )
        settlement = Handler.requests[-1][1]
        self.assertEqual(settlement["validation_name"], "invoice-check-v1")
        self.assertFalse(settlement["validated"])
        self.assertTrue(settlement["success"])

    def test_stop_and_hold_never_dispatch_provider(self):
        def forbidden(_config):
            self.fail("Provider should not run")

        Handler.action = "stop"
        with self.assertRaises(AdmissionDenied):
            self.client.run_paid_call("job-1", forbidden, max_cost="0.10")
        self.assertEqual(len(Handler.requests), 1)
        Handler.requests = []
        Handler.action = "continue"
        Handler.admission = "hold"
        with self.assertRaises(AdmissionDenied):
            self.client.run_paid_call("job-1", forbidden, max_cost="0.10")
        self.assertEqual(len(Handler.requests), 2)

    def test_provider_exception_marks_charge_uncertain(self):
        def broken(_config):
            raise RuntimeError("provider timed out")

        with self.assertRaisesRegex(RuntimeError, "provider timed out"):
            self.client.run_paid_call("job-1", broken, max_cost="0.10")
        self.assertEqual(Handler.requests[-1][0], "/api/uncertain")
        self.assertEqual(
            Handler.requests[-1][1]["request_id"], Handler.requests[1][1]["request_id"]
        )

    def test_settlement_failure_exposes_original_request_id_without_retry(self):
        Handler.settle_error = True
        with self.assertRaises(SettlementUnknown) as caught:
            self.client.run_paid_call("job-1", lambda _: Charge("done", "0.02"), max_cost="0.10")
        self.assertEqual(caught.exception.request_id, Handler.requests[1][1]["request_id"])
        self.assertEqual([p for p, _, _ in Handler.requests].count("/api/settle"), 1)

    def test_auth_and_rejected_request(self):
        other = ReinsClient(self.url, token="z" * 48)
        with self.assertRaises(ReinsAuthenticationError):
            other.status("job-1")
        Handler.action = "stop"
        with self.assertRaises(AdmissionDenied):
            self.client.run_paid_call("job-1", lambda _: Charge(None, "0"), max_cost="0.10")
        with self.assertRaises(ValueError):
            self.client.post("../server", {})

    def test_status(self):
        self.assertEqual(self.client.status("job-1")["workflows"][0]["id"], "job-1")

    def test_pairing_and_start_run(self):
        self.assertEqual(self.client.pairing()["customer_id"], "demo-customer")
        first = self.client.start_run(run_key="a" * 32)["workflow_id"]
        self.assertEqual(first, "run-" + "a" * 32)
        self.assertEqual(Handler.requests[-1][1], {"run_key": "a" * 32})

    def test_tls_and_credentials_required(self):
        with self.assertRaises(ValueError):
            ReinsClient("http://example.com/api", token=TOKEN)
        with self.assertRaises(ValueError):
            ReinsClient("https://example.com/api?token=foo", token=TOKEN)
        with self.assertRaises(ValueError):
            ReinsClient(self.url, token="short")
        with self.assertRaises(ValueError):
            ReinsClient(self.url, token=TOKEN, token_file="somewhere")


if __name__ == "__main__":
    unittest.main()
