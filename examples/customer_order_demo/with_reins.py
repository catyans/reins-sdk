"""The same order review with a Reins control and recording boundary.

This first pairing demo uses a local, zero-cost operation. It does not call a
model API or claim model-cost savings. The paired server still makes the
admission decision and records the result, cost and workflow state.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from business import review_orders

from reins_sdk import Charge, ReinsClient

API_URL = "https://47.245.114.167:8444/api"
TOKEN_FILE = Path.home() / ".config/reins/demo-worker.token"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task_id", help="Hosted task ID assigned by the Reins operator")
    parser.add_argument("--run", action="store_true", help="Execute and record the order review")
    parser.add_argument("--base-url", default=API_URL)
    parser.add_argument("--token-file", type=Path, default=TOKEN_FILE)
    args = parser.parse_args()
    client = ReinsClient(args.base_url, token_file=args.token_file)

    status = client.status(args.task_id)
    workflow = status["workflows"][0]
    print("Connected to Reins task:", workflow["workflow_id"])
    print("Task state:", workflow["state"])
    if not args.run:
        print("Connection verified. Add --run to execute the local order review.")
        return

    plan = client.decision(args.task_id)
    if plan.get("action") not in ("continue", "escalate"):
        raise ValueError("Reins did not admit this task: " + str(plan.get("reason", "stopped")))
    if plan.get("configuration", {}).get("config", {}).get("model") != "demo/lite":
        raise ValueError("This local demonstration only supports the pinned demo/lite plan")

    def execute(_config: dict) -> Charge:
        result = review_orders()
        return Charge(
            result=result,
            actual_cost="0",
            validated=result["rows_checked"] == 5 and len(result["issues"]) == 3,
            validation_name="all-five-orders-reviewed-v1",
        )

    client.progress(args.task_id, "order-review", 0, 1)
    charge = client.run_paid_call(args.task_id, execute, max_cost="0.01")
    client.progress(args.task_id, "order-review", 1, 1)
    client.post("transition", {"workflow_id": args.task_id, "action": "finish", "accepted": True})
    print("Order review:")
    print(json.dumps(charge.result, indent=2))
    print("Recorded actual API cost: $0.00 (local demo operation)")
    print("Final task state:", client.status(args.task_id)["workflows"][0]["state"])


if __name__ == "__main__":
    main()
