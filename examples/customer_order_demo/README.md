# Customer order review: before and after Reins

This is a small customer-side demonstration. Five example order rows contain a duplicate ID, a missing customer, and a negative amount. `before_reins.py` runs the existing local check. `with_reins.py` runs the same check after the hosted task grants permission, then records the outcome and actual cost. The business output is unchanged.

The operation is local and has **zero provider/API cost**. Reins's budget reservation is an upper-bound control demonstration, not a claim that this example saved money or called a model. No Reins server code or operator credential is included here.

From the `reins-sdk` repository root:

```bash
PYTHONPATH=src python3 examples/customer_order_demo/before_reins.py
PYTHONPATH=src python3 -m reins_sdk.pair
```

Give the displayed code to the Reins operator. They create a Hosted task and enter its ID and this code at **Settings → Pair a customer SDK** on the [isolated pilot site](https://47.245.114.167:8444/). The operator gives you the task ID. Then run:

```bash
PYTHONPATH=src python3 -m reins_sdk.pair YOUR_TASK_ID --check
PYTHONPATH=src python3 examples/customer_order_demo/with_reins.py YOUR_TASK_ID
PYTHONPATH=src python3 examples/customer_order_demo/with_reins.py YOUR_TASK_ID --run
```

The check-only command reads the task without changing it. `--run` records one local operation and finishes the task; use a new Hosted task for another full run. The pairing code remains in `~/.config/reins/demo-worker.token` with mode 0600 and must not be committed. The Reins operator can revoke it in Settings.
